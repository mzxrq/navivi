"""Orchestration entry points: the master pipeline, NLE fast re-render, and step-duration estimates."""

import copy
import json
import sys
import time
from pathlib import Path
from typing import Optional

from services import tuning
from services.config.job_config import JobConfigManager
from services.config.upscaled_images import upscale_enabled
from services.logger.progress import tracker
from services.render_estimate import StageRecorder
from services.vdoprocessing.vdoexporter import VideoExporter, sweep_stale_temp_files

from .attraction_step import render_attraction_videos
from .audio_step import apply_cued_scripts, generate_audio, set_route_only_legs, stop_tts_server
from .gps_step import process_gps
from .helpers import (
    attraction_videos_enabled,
    logger,
    project_subtitle_dir,
    project_video_dir,
    skip_rich_media,
)
from .intro_step import intro_text_item, render_intro_clip
from .leg_pieces import compute_leg_narration_splits
from .narration_step import add_default_cues, add_overview_cues, record_cue_times
from .outro_step import render_outro_clip
from .render_step import render_route_video
from .subtitle_step import (
    build_attraction_subtitles,
    build_overview_subtitle,
    build_subtitles,
)
from .timeline_step import build_timeline
from .upscale_step import upscale_waypoint_images


# GPS, TTS, subtitles, photo upscale, attraction videos, route render, intro/outro.
PIPELINE_STAGES = 7


def _stop_gpu_servers() -> None:
    """Frees the RAM/VRAM the narration and diffusion servers still hold."""
    stop_tts_server()
    from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient

    ComfyUII2VClient.stop_server()


def run_full_pipeline(
    raw_source_path: str,
    output_video_dir: Optional[str] = None,
    force_regenerate: bool = False,
) -> dict:
    """Executes all steps sequentially, reporting progress on the same
    "[mm:ss] [n/N] ..." live status line main.py's CLI test commands use
    (see services.logger.progress) — each step function below (gps_step,
    audio_step, attraction_step, render_step, subtitle_step) calls
    `tracker.show(...)` itself for its own per-waypoint work, so this
    function only needs to mark where each top-level stage begins."""
    source_path = Path(raw_source_path)
    project_dir = source_path.parent
    config_file_path = project_dir / "job_config.json"
    job_config = JobConfigManager(config_file_path)

    if not output_video_dir:
        base_path = Path(job_config.get("directory_path", project_dir))
        output_video_dir = str(project_video_dir(base_path).resolve())

    # Route (overview/residential) and attraction outputs get their own
    # subfolders under output_video_dir instead of sharing one flat folder —
    # see helpers.project_route_video_dir/project_attraction_video_dir.
    route_video_dir = str(Path(output_video_dir) / "route")
    sweep_stale_temp_files(output_video_dir, recursive=True)

    waypoints = job_config.get("waypoints", [])
    min_free_ram = job_config.get("settings", {}).get("min_free_ram_gb")

    # [NOTE] [Core] total (the "[n/N]" denominator) is only set on this first stage() call — later stage() calls rely on the tracker remembering it rather than re-declaring it each time.
    # Every path below makes exactly PIPELINE_STAGES stage() calls (a skipped
    # stage still announces itself), so the frontend's progress bar and stage
    # list never see "[9/8]". Sub-work inside a stage uses tracker.show().
    recorder = StageRecorder(job_config.to_dict())
    tracker.on_stage = recorder.on_stage
    tracker.stage("Parsing GPS track...", total=PIPELINE_STAGES)
    cleaned_route = process_gps(raw_source_path)

    settings = job_config.get("settings", {})
    fast_render = skip_rich_media(settings)
    attractions_on = attraction_videos_enabled(settings)

    # --- STEP 2 ---
    tracker.stage("Generating TTS narration...")
    tuning.ensure_free_ram("TTS narration", min_free_ram)
    # The script's own timing cues ({start}/{arrive}/{end}) tell the video where
    # the voice is: the walker has to have arrived by {arrive}. They are never
    # spoken. settings.use_narration_cues=false ignores them; a script without
    # any uses the "at most 3 s early" rule. Scripts that have none get default
    # cues (stored beside job_config.json): on by default
    # (tuning.DEFAULT_AUTO_NARRATION_CUES), settings.auto_narration_cues=false
    # turns it off.
    use_cues = bool(job_config.get("settings", {}).get("use_narration_cues", True))
    # With attraction videos on, each attraction clip speaks its waypoint's
    # attraction text, so a leg speaks only its route (arriving) text -
    # otherwise the same attraction text played twice, leg then clip.
    set_route_only_legs(attractions_on)
    if fast_render:
        logger.info("Step 2: settings.skip_rich_media is on — skipping TTS.")
        audio_data = {
            "audio_durations": [], "audio_pauses": [], "audio_paths": [],
            "subtitle_paths": [], "attraction_audio_paths": [],
            "attraction_audio_durations": [], "overview_audio_path": None,
            "overview_audio_duration": 0.0, "overview_cue_times": {},
        }
    else:
        add_default_cues(str(config_file_path))
        # {n} / {go} for a hand-written overview script, so the overview stops at
        # each waypoint while it is described (on by default:
        # tuning.DEFAULT_AUTO_OVERVIEW_CUES; settings.auto_overview_cues=false turns it off).
        add_overview_cues(str(config_file_path))
        audio_data = generate_audio(
            cleaned_route, str(config_file_path), force=force_regenerate
        )
        # Where each cue falls in the real audio; render_step sizes each walk from it.
        if use_cues:
            record_cue_times(str(config_file_path), audio_data)

        # [NOTE] [TTS] Force-stop the TTS server now instead of leaving it to its
        # idle timeout — otherwise it stays loaded in VRAM while the attraction
        # step's ComfyUI/Wan pipeline and the renderer below start competing for
        # the same VRAM right after, which can overcommit a tight GPU budget.
        tracker.show("Stopping TTS server...")
        stop_tts_server()

    # --- STEP 2b ---
    # Subtitles carry the same cue-free text the audio speaks. Done on a copy
    # so nothing added here leaks into job_config's own waypoints.
    waypoints = copy.deepcopy(waypoints)
    if fast_render:
        tracker.stage("Skipping subtitles (settings.skip_rich_media is on)...")
        logger.info("Step 2b: settings.skip_rich_media is on — skipping subtitles.")
        subtitle_paths = []
        overview_subtitle_path = None
        attraction_subtitle_paths = []
    else:
        tracker.stage("Generating subtitles...")
        subtitle_dir = project_subtitle_dir(project_dir)
        apply_cued_scripts(waypoints, project_dir)
        subtitle_paths = build_subtitles(
            waypoints, audio_data.get("audio_paths", []), str(subtitle_dir), force=force_regenerate
        )
        # Re-read: TTS restores overview_narration on disk after job_config was loaded.
        overview_subtitle_path = build_overview_subtitle(
            JobConfigManager(config_file_path).data,
            audio_data.get("overview_audio_path"),
            str(subtitle_dir),
            force=force_regenerate,
        )
        attraction_subtitle_paths = build_attraction_subtitles(
            waypoints,
            audio_data.get("attraction_audio_paths", []),
            str(subtitle_dir),
            force=force_regenerate,
        )

    # --- STEP 2c ---
    # Small waypoint photos get an upscaled copy; JobConfigManager then hands
    # every later step those paths (job_config.json keeps the originals).
    # Off with settings.upscale_popup_images=false, and always under
    # skip_rich_media.
    if upscale_enabled(settings):
        tracker.stage("Upscaling waypoint photos...")
        tuning.ensure_free_ram("photo upscale", min_free_ram, relief=stop_tts_server)
        upscale_waypoint_images(str(config_file_path), force=force_regenerate)
        job_config = JobConfigManager(config_file_path)
        if not attractions_on:
            from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient
            ComfyUII2VClient.stop_server()
    else:
        tracker.stage("Skipping photo upscale...")
        logger.info("Step 2c: photo upscale is off (upscale_popup_images / skip_rich_media).")

    # --- STEP 3 ---
    # Opt-out per project via job_config.json's settings.enable_attraction_videos
    # (default True — unset/existing projects keep generating them as before).
    # Off skips the whole ComfyUI/Wan2.2 (or local pan/zoom fallback) step
    # entirely — the slowest, most GPU-heavy stage in the pipeline — for a
    # project that only wants the route/overview video.
    if attractions_on:
        tracker.stage("Generating attraction videos...")
        tuning.ensure_free_ram("attraction videos", min_free_ram, relief=stop_tts_server)
        attraction_videos = render_attraction_videos(
            str(config_file_path),
            audio_durations=audio_data.get("attraction_audio_durations"),
            audio_paths=audio_data.get("attraction_audio_paths"),
            force=force_regenerate,
        )

        # Same VRAM-contention reasoning as the TTS server above — the
        # attraction step's ComfyUI/Wan pipeline would otherwise stay loaded
        # into the renderer below via its own idle timeout.
        from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient
        ComfyUII2VClient.stop_server()

        # [NOTE] [GPU] See tuning.GPU_STAGE_COOLDOWN_SECONDS — a brief pause
        # here before the Chromium/WebGL render stage starts, giving the GPU
        # a moment to release VRAM/thermal load from the diffusion stage
        # above instead of jumping straight into another sustained GPU
        # workload.
        tracker.show("Cooling down GPU before video rendering...")
        time.sleep(tuning.GPU_STAGE_COOLDOWN_SECONDS)
    else:
        tracker.stage("Skipping attraction videos (disabled for this project)...")
        logger.info(
            "Step 3: attraction videos are off (enable_attraction_videos / skip_rich_media) — skipping "
            "attraction video generation."
        )
        attraction_videos = []

    # --- STEP 4 ---
    tracker.stage("Rendering overview & residential video...")
    tuning.ensure_free_ram("video rendering", min_free_ram, relief=_stop_gpu_servers)
    video_paths = render_route_video(
        cleaned_route=cleaned_route,
        project_config_path=str(config_file_path),
        output_video_dir=route_video_dir,
        audio_durations=audio_data.get("audio_durations"),
        audio_pauses=audio_data.get("audio_pauses"),
        overview_audio_duration=audio_data.get("overview_audio_duration"),
        overview_cue_times=audio_data.get("overview_cue_times") if use_cues else None,
        force=force_regenerate,
    )

    # A connectToRoute stop-by's fullscreen photo-pause (see pydeckrecorder/
    # pedestrian.py's `landmarks` docstring) can cut one leg's silent video
    # into several "_contN" pieces, each one the walk TOWARD its own next
    # stop. Resolved here (once, from Step 4's video_paths) into each piece's
    # own target narration — padding that piece's video first if its
    # target's narration runs longer than the piece's own natural length —
    # and used by build_timeline (so the right audio and subtitles land on
    # each piece at final export) — see
    # leg_pieces.py. video_paths is replaced with the (possibly padded)
    # result so every later step sees the final piece lengths.
    video_paths, leg_narration_splits = compute_leg_narration_splits(
        video_paths, audio_data.get("audio_paths"), subtitle_paths, waypoints, str(project_dir)
    )
    all_videos = video_paths + attraction_videos

    # Subtitles are burned once, onto the whole video, at export (render_timeline).
    final_videos = list(all_videos)

    # --- STEP 5b ---
    # Intro/outro carry no narration, so they're attached here, directly to
    # the final clip order. Prepending intro to BOTH video_paths and final_videos (rather
    # than just final_videos) keeps build_timeline's own indexing correct,
    # since it uses len(video_paths) as the boundary between "route" and
    # "attraction" clips; outro is only ever appended to the very end of
    # final_videos, where build_timeline's attraction-index lookup already
    # falls back to the clip's own filename once the index runs past
    # attraction_videos, so it needs no such adjustment.
    tracker.stage("Building intro/outro clips...")
    intro_path = render_intro_clip(str(config_file_path))
    outro_path = render_outro_clip(str(config_file_path))
    if intro_path:
        video_paths = [intro_path] + video_paths
        final_videos = [intro_path] + final_videos
    if outro_path:
        final_videos = final_videos + [outro_path]

    timeline_path = build_timeline(
        video_paths=video_paths,
        attraction_videos=attraction_videos,
        final_videos=final_videos,
        audio_paths=audio_data.get("audio_paths"),
        subtitle_paths=subtitle_paths,
        project_dir=str(project_dir),
        overview_audio_path=audio_data.get("overview_audio_path"),
        overview_subtitle_path=overview_subtitle_path,
        attraction_audio_paths=audio_data.get("attraction_audio_paths"),
        attraction_subtitle_paths=attraction_subtitle_paths,
        leg_narration_splits=leg_narration_splits,
        # settings.attraction_fade_seconds: how long a leg's arrival photo
        # dissolves into the attraction video after it (0 = hard cut).
        attraction_fade_seconds=float(
            job_config.get("settings", {}).get("attraction_fade_seconds", 0.8)
        ),
        intro_text=intro_text_item(str(config_file_path)) if intro_path else None,
        place_label_look=job_config.get("settings", {}).get("place_label_look"),
    )
    recorder.finish()
    tracker.on_stage = None
    tracker.clear()

    return {
        "video_paths": final_videos,
        "summary": cleaned_route.get("summary", {}),
        "timeline_path": timeline_path,
    }


def recover_narration_paths(timeline_data: dict) -> int:
    """Re-links narration to its clip for a timeline.json the editor saved without per-clip audio_path.

    The editor keeps each narration as its own audio clip that starts with its video clip (ui_state.clips);
    the exporter only reads video_tracks[].audio_path. Returns how many clips were re-linked.
    """
    tracks = timeline_data.get("video_tracks", [])
    if any(t.get("audio_path") for t in tracks):
        return 0
    clips = (timeline_data.get("ui_state") or {}).get("clips") or []
    audio_track_ids = {
        t.get("id") for t in (timeline_data.get("ui_state") or {}).get("tracks", []) if t.get("type") == "audio"
    }
    voices = [
        c for c in clips
        if c.get("source") and c.get("type") == "audio"
        and (c.get("trackId") in audio_track_ids or c.get("audioRole") == "voice")
    ]
    start_of = {c.get("id"): c.get("startTime", 0.0) for c in clips}
    fixed = 0
    for track in tracks:
        start = start_of.get(track.get("clip_id"))
        if start is None:
            continue
        voice = next((v for v in voices if abs(v.get("startTime", 0.0) - start) < 0.05), None)
        if voice:
            track["audio_path"] = voice["source"]
            fixed += 1
    return fixed


def _project_caption_style(project_dir: Path) -> dict:
    """Caption look from the project's settings (job_config.json beside timeline.json)."""
    config_path = project_dir / "job_config.json"
    if not config_path.exists():
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            style = (json.load(f).get("settings") or {}).get("caption_style")
        return style if isinstance(style, dict) else {}
    except Exception as exc:  # a bad config must not block the export
        logger.warning("Caption style: could not read %s (%s); using the default.", config_path, exc)
        return {}


def render_from_timeline(
    timeline_json_path: str, output_video_path: Optional[str] = None
) -> str:
    """Reads an existing timeline.json file and instantly re-renders the master video."""
    timeline_path = Path(timeline_json_path)
    if not timeline_path.exists():
        raise FileNotFoundError(f"Timeline JSON not found: {timeline_path}")

    with open(timeline_path, "r", encoding="utf-8") as f:
        timeline_data = json.load(f)

    # The editor saves project-relative paths; resolve them against the project, not the cwd.
    project_dir = timeline_path.resolve().parent
    relinked = recover_narration_paths(timeline_data)
    if relinked:
        logger.info("NLE Engine: re-linked narration for %d clips from the editor state", relinked)
    for track in timeline_data.get("video_tracks", []):
        for key in ("file_path", "audio_path", "extra_audio_path"):
            if track.get(key) and not Path(track[key]).is_absolute():
                track[key] = str(project_dir / track[key])
    timeline_data["burn_subtitles"] = True
    if "caption_style" not in timeline_data:
        timeline_data["caption_style"] = _project_caption_style(project_dir)
    music = timeline_data.get("music") or {}
    if music.get("path") and not Path(music["path"]).is_absolute():
        music["path"] = str(project_dir / music["path"])

    if not output_video_path:
        output_video_path = str(project_video_dir(project_dir) / "01_overview_rerendered.mp4")

    print(f"NLE Engine: Re-rendering video from {timeline_path.name}...")
    logger.info("NLE Engine: Re-rendering video from %s...", timeline_path.name)

    last = [-1]

    def progress(pct: float) -> None:
        # Read by export_video in lib.rs, which forwards it to the app as "export-progress".
        if int(pct) != last[0]:
            last[0] = int(pct)
            print(f"EXPORT_PROGRESS {int(pct)}", file=sys.stderr, flush=True)

    final_path = VideoExporter.concat_from_timeline(
        timeline_data=timeline_data, output_path=output_video_path, save_json_path=None,
        on_progress=progress,
    )

    print(f"Fast re-render complete  {final_path}")
    logger.info("NLE Engine: Fast re-render complete  %s", final_path)
    return final_path
