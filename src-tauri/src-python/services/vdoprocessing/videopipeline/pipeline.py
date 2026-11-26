"""Orchestration entry points: the master pipeline, NLE fast re-render, and step-duration estimates."""

import copy
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple, Optional

from services import tuning
from services.config.job_config import JobConfigManager
from services.config.upscaled_images import upscale_enabled
from services.ollama_memory import unload_ollama_models
from services.logger.progress import tracker
from services.render_estimate import StageRecorder
from services.localization.overview_script import overview_style
from services.vdoprocessing.stopby_visits import set_visit_all_stopbys
from services.vdoprocessing.storyboard import of as storyboard_of
from services.vdoprocessing.vdoexporter import VideoExporter, sweep_stale_temp_files

from .attraction_step import render_attraction_videos
from .audio_step import apply_cued_scripts, generate_audio, require_some_voice, set_route_only_legs, stop_tts_server
from .gps_step import process_gps
from .helpers import (
    attraction_videos_enabled,
    logger,
    project_export_dir,
    project_subtitle_dir,
    project_video_dir,
    skip_rich_media,
)
from .intro_step import intro_text_items, place_overview_voice, render_intro_clip
from .leg_pieces import compute_leg_narration_splits
from .narration_step import add_default_cues, add_overview_cues, record_cue_times
from .finale_step import render_finale_clip
from .outro_step import outro_text_item, render_outro_clip
from .render_step import render_route_video
from .subtitle_step import (
    build_attraction_subtitles,
    build_finale_subtitle,
    build_overview_subtitle,
    build_subtitles,
)
from .sub_course_step import append_sub_course, render_sub_course
from .timeline_step import build_timeline
from .upscale_step import upscale_waypoint_images


# GPS, TTS, subtitles, photo upscale, attraction videos, route render, intro/outro.
PIPELINE_STAGES = 7


def _stop_gpu_servers() -> None:
    """Frees the RAM/VRAM the narration and diffusion servers still hold (and the script model Ollama keeps loaded)."""
    unload_ollama_models()
    stop_tts_server()
    from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient

    ComfyUII2VClient.stop_server()


@dataclass(frozen=True)
class _Run:
    """What every stage of one run_full_pipeline call reads."""

    config_file_path: Path
    project_dir: Path
    job_config: JobConfigManager
    force: bool
    settings: dict
    fast_render: bool
    attractions_on: bool
    min_free_ram: Optional[float]
    use_cues: bool


class _Subtitles(NamedTuple):
    """The subtitle files stage 2b made (all empty/None when it was skipped)."""

    legs: list
    overview: Optional[str]
    intro: Optional[str]
    attractions: list


def _silent_audio_data() -> dict:
    """The narration data of a run with no voice (settings.skip_rich_media)."""
    return {
        "audio_durations": [], "audio_pauses": [], "audio_paths": [],
        "subtitle_paths": [], "attraction_audio_paths": [],
        "attraction_audio_durations": [], "overview_audio_path": None,
        "overview_audio_duration": 0.0, "overview_cue_times": {},
    }


def _generate_voice(run: _Run, cleaned_route: dict, waypoints: list) -> dict:
    """Stage 2: the narration of the overview, every leg and every attraction, and where the script's cues fall in it."""
    tracker.stage("Generating TTS narration...")
    tuning.ensure_free_ram("TTS narration", run.min_free_ram, relief=unload_ollama_models)
    # The script's own timing cues ({start}/{arrive}/{end}) tell the video where
    # the voice is: the walker has to have arrived by {arrive}. They are never
    # spoken. settings.use_narration_cues=false ignores them; a script without
    # any uses the "at most 3 s early" rule. Scripts that have none get default
    # cues (stored beside job_config.json): on by default
    # (tuning.DEFAULT_AUTO_NARRATION_CUES), settings.auto_narration_cues=false
    # turns it off.
    # With attraction videos on, each attraction clip speaks its waypoint's
    # attraction text, so a leg speaks only its route (arriving) text -
    # otherwise the same attraction text played twice, leg then clip.
    set_route_only_legs(run.attractions_on)
    # "Whole route first" (overview_style "course"): every stop-by with a photo
    # is visited - narrated, a fullscreen photo in its leg, its own clip.
    set_visit_all_stopbys(storyboard_of(overview_style(run.job_config.to_dict())).visit_all_stopbys)
    if run.fast_render:
        logger.info("Step 2: settings.skip_rich_media is on — skipping TTS.")
        return _silent_audio_data()

    config_path = str(run.config_file_path)
    add_default_cues(config_path)
    # {n} / {go} for a hand-written overview script, so the overview stops at
    # each waypoint while it is described (on by default:
    # tuning.DEFAULT_AUTO_OVERVIEW_CUES; settings.auto_overview_cues=false turns it off).
    add_overview_cues(config_path)
    audio_data = generate_audio(cleaned_route, config_path, force=run.force)
    require_some_voice(waypoints, audio_data)
    # Where each cue falls in the real audio; render_step sizes each walk from it.
    if run.use_cues:
        record_cue_times(config_path, audio_data)

    # [NOTE] [TTS] Force-stop the TTS server now instead of leaving it to its
    # idle timeout — otherwise it stays loaded in VRAM while the attraction
    # step's ComfyUI/Wan pipeline and the renderer below start competing for
    # the same VRAM right after, which can overcommit a tight GPU budget.
    tracker.show("Stopping TTS server...")
    stop_tts_server()
    return audio_data


def _generate_subtitles(run: _Run, waypoints: list, audio_data: dict) -> _Subtitles:
    """Stage 2b: the subtitle files, carrying the same cue-free text the audio speaks.

    `waypoints` is a copy, so nothing added here leaks into job_config's own waypoints.
    """
    if run.fast_render:
        tracker.stage("Skipping subtitles (settings.skip_rich_media is on)...")
        logger.info("Step 2b: settings.skip_rich_media is on — skipping subtitles.")
        return _Subtitles([], None, None, [])

    tracker.stage("Generating subtitles...")
    subtitle_dir = str(project_subtitle_dir(run.project_dir))
    apply_cued_scripts(waypoints, run.project_dir)
    legs = build_subtitles(waypoints, audio_data.get("audio_paths", []), subtitle_dir, force=run.force)
    # Re-read: TTS restores overview_narration on disk after job_config was loaded.
    overview = build_overview_subtitle(
        JobConfigManager(run.config_file_path).data,
        audio_data.get("overview_audio_path"),
        subtitle_dir,
        force=run.force,
        script=audio_data.get("overview_text"),
    )
    intro_voice_data = audio_data.get("intro_voice") or {}
    intro = build_overview_subtitle(
        JobConfigManager(run.config_file_path).data, intro_voice_data.get("audio_path"), subtitle_dir,
        force=run.force, script=intro_voice_data.get("text"),
    ) if intro_voice_data else None
    attractions = build_attraction_subtitles(
        waypoints, audio_data.get("attraction_audio_paths", []), subtitle_dir, force=run.force,
    )
    build_finale_subtitle(JobConfigManager(run.config_file_path).data, run.project_dir, subtitle_dir)
    return _Subtitles(legs, overview, intro, attractions)


def _upscale_photos(run: _Run) -> None:
    """Stage 2c: small waypoint photos get an upscaled copy; JobConfigManager then hands
    every later step those paths (job_config.json keeps the originals).
    Off with settings.upscale_popup_images=false, and always under skip_rich_media."""
    if not upscale_enabled(run.settings):
        tracker.stage("Skipping photo upscale...")
        logger.info("Step 2c: photo upscale is off (upscale_popup_images / skip_rich_media).")
        return
    tracker.stage("Upscaling waypoint photos...")
    tuning.ensure_free_ram("photo upscale", run.min_free_ram, relief=stop_tts_server)
    upscale_waypoint_images(str(run.config_file_path), force=run.force)
    JobConfigManager(run.config_file_path)
    # Clip workers start their own server: one owned here couldn't be
    # restarted by them between LTXV sampling and decoding.
    if not run.attractions_on or tuning.ATTRACTION_CLIP_IN_CHILD:
        from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient
        ComfyUII2VClient.stop_server()


def _generate_attraction_clips(run: _Run, audio_data: dict) -> list:
    """Stage 3: an attraction video per stop photo (ComfyUI/Wan2.2, or the local fallback).

    Opt-out per project via job_config.json's settings.enable_attraction_videos
    (default True — unset/existing projects keep generating them as before).
    Off skips the whole ComfyUI/Wan2.2 (or local pan/zoom fallback) step
    entirely — the slowest, most GPU-heavy stage in the pipeline — for a
    project that only wants the route/overview video.
    """
    if not run.attractions_on:
        tracker.stage("Skipping attraction videos (disabled for this project)...")
        logger.info(
            "Step 3: attraction videos are off (enable_attraction_videos / skip_rich_media) — skipping "
            "attraction video generation."
        )
        return []

    tracker.stage("Generating attraction videos...")
    tuning.ensure_free_ram("attraction videos", run.min_free_ram, relief=stop_tts_server)
    attraction_videos = render_attraction_videos(
        str(run.config_file_path),
        audio_durations=audio_data.get("attraction_audio_durations"),
        audio_paths=audio_data.get("attraction_audio_paths"),
        force=run.force,
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
    return attraction_videos


def _render_route_stage(
    run: _Run, cleaned_route: dict, waypoints: list, audio_data: dict, subtitle_paths: list,
    attraction_videos: list, route_video_dir: str,
) -> tuple:
    """Stage 4: the intro, every leg and the overview, then the legs' narration splits and the sub course.

    Returns (overview voice placement, route video paths, leg narration splits, sub course timeline).
    """
    config_path = str(run.config_file_path)
    tracker.stage("Rendering overview & residential video...")
    # The overview voice starts on the intro: its opening (up to {start}) plays over the intro.
    tracker.show("Building intro clip...")
    voice = place_overview_voice(
        run.settings, audio_data, run.use_cues,
        lambda seconds, cues: render_intro_clip(
            config_path, duration_sec=seconds, attraction_videos=attraction_videos, cue_times=cues,
        ),
    )

    tuning.ensure_free_ram("video rendering", run.min_free_ram, relief=_stop_gpu_servers)
    video_paths = render_route_video(
        cleaned_route=cleaned_route,
        project_config_path=config_path,
        output_video_dir=route_video_dir,
        audio_durations=audio_data.get("audio_durations"),
        audio_pauses=audio_data.get("audio_pauses"),
        overview_audio_duration=voice["overview_audio"],
        overview_cue_times=voice["overview_cues"],
        force=run.force,
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
        video_paths, audio_data.get("audio_paths"), subtitle_paths, waypoints, str(run.project_dir)
    )
    # The sub course (job_config sub_course) runs inside this stage, so the stage count stays the same.
    sub_timeline = render_sub_course(config_path, run.force, run.attractions_on, run.fast_render)
    return voice, video_paths, leg_narration_splits, sub_timeline


def _finish_timeline(
    run: _Run, audio_data: dict, subtitles: _Subtitles, voice: dict, video_paths: list,
    attraction_videos: list, leg_narration_splits: list, waypoints: list, sub_timeline,
) -> tuple:
    """Stage 5b: the outro and finale clips, then timeline.json (the final clip order). Returns (final videos, timeline path)."""
    config_path = str(run.config_file_path)
    job_config = JobConfigManager(run.config_file_path)
    settings = job_config.get("settings", {})
    intro_path, intro_seconds, intro_cues = voice["intro_path"], voice["intro_seconds"], voice["intro_cues"]

    # Intro (built in Step 4) and outro are attached here, directly to
    # the final clip order. Prepending intro to BOTH video_paths and final_videos (rather
    # than just final_videos) keeps build_timeline's own indexing correct,
    # since it uses len(video_paths) as the boundary between "route" and
    # "attraction" clips; outro is only ever appended to the very end of
    # final_videos, where build_timeline's attraction-index lookup already
    # falls back to the clip's own filename once the index runs past
    # attraction_videos, so it needs no such adjustment.
    tracker.stage("Building intro/outro clips...")
    outro_path = render_outro_clip(config_path)
    # The last stop's photo shrinks onto its pin and the camera pulls back to the whole route, then the outro.
    finale_path = render_finale_clip(config_path, force=run.force) if outro_path else None
    final_videos = list(video_paths + attraction_videos)  # subtitles are burned once, onto the whole video, at export
    if intro_path:
        video_paths = [intro_path] + video_paths
        final_videos = [intro_path] + final_videos
    if outro_path:
        final_videos = final_videos + ([finale_path] if finale_path else []) + [outro_path]

    timeline_path = build_timeline(
        video_paths=video_paths,
        attraction_videos=attraction_videos,
        final_videos=final_videos,
        audio_paths=audio_data.get("audio_paths"),
        subtitle_paths=subtitles.legs,
        project_dir=str(run.project_dir),
        overview_audio_path=audio_data.get("overview_audio_path"),
        overview_subtitle_path=subtitles.overview,
        attraction_audio_paths=audio_data.get("attraction_audio_paths"),
        attraction_subtitle_paths=subtitles.attractions,
        leg_narration_splits=leg_narration_splits,
        # settings.attraction_fade_seconds: how long a leg's arrival photo
        # dissolves into the attraction video after it (0 = hard cut).
        attraction_fade_seconds=float(settings.get("attraction_fade_seconds", 0.8)),
        intro_text=intro_text_items(config_path, duration_sec=intro_seconds, cue_times=intro_cues) if intro_path else None,
        outro_text=outro_text_item(config_path) if outro_path else None,
        place_label_look=settings.get("place_label_look"),
        photo_credit_look=settings.get("photo_credit_look"),
        overview_voice_start=voice["voice_start"],
        intro_audio_path=(voice["intro_voice"] or {}).get("audio_path"),
        intro_subtitle_path=subtitles.intro if intro_path else None,
        overview_audio_offset=voice["overview_lead"],
        waypoints=waypoints,  # as the run started: job_config.json may be edited meanwhile
    )
    append_sub_course(timeline_path, sub_timeline, config_path)
    return final_videos, timeline_path


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
    run = _Run(
        config_file_path=config_file_path, project_dir=project_dir, job_config=job_config,
        force=force_regenerate, settings=settings, fast_render=skip_rich_media(settings),
        attractions_on=attraction_videos_enabled(settings), min_free_ram=min_free_ram,
        use_cues=bool(settings.get("use_narration_cues", True)),
    )

    audio_data = _generate_voice(run, cleaned_route, waypoints)
    waypoints = copy.deepcopy(waypoints)
    subtitles = _generate_subtitles(run, waypoints, audio_data)
    _upscale_photos(run)
    attraction_videos = _generate_attraction_clips(run, audio_data)
    voice, video_paths, leg_narration_splits, sub_timeline = _render_route_stage(
        run, cleaned_route, waypoints, audio_data, subtitles.legs, attraction_videos, route_video_dir
    )
    final_videos, timeline_path = _finish_timeline(
        run, audio_data, subtitles, voice, video_paths, attraction_videos, leg_narration_splits, waypoints, sub_timeline
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


def move_timed_narration(timeline_data: dict) -> int:
    """A track whose narration has its own timeline time (audio_start: the
    overview voice starting on the intro) is exported like the editor's
    unlinked narration: mixed in at that time, not muxed onto its clip."""
    moved = 0
    for track in timeline_data.get("video_tracks", []):
        if track.get("audio_start") is None or not track.get("audio_path"):
            continue
        if not track.get("muted"):
            timeline_data.setdefault("unlinked_audio", []).append({
                "path": track["audio_path"],
                "start": float(track["audio_start"]),
                "volume": float(track.get("volume", 1.0)),
            })
        track["audio_path"] = None
        track["audio_offset"] = 0.0
        moved += 1
    return moved


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
    timeline_data.setdefault("burn_subtitles", True)  # the Export dialog may turn it off
    if "caption_style" not in timeline_data:
        timeline_data["caption_style"] = _project_caption_style(project_dir)
    music = timeline_data.get("music") or {}
    if music.get("path") and not Path(music["path"]).is_absolute():
        music["path"] = str(project_dir / music["path"])
    for item in timeline_data.get("unlinked_audio") or []:
        if item.get("path") and not Path(item["path"]).is_absolute():
            item["path"] = str(project_dir / item["path"])
    move_timed_narration(timeline_data)

    if not output_video_path:
        export_dir = project_export_dir(project_dir)
        export_dir.mkdir(parents=True, exist_ok=True)
        output_video_path = str(export_dir / f"{project_dir.name}.mp4")

    print(f"NLE Engine: Re-rendering video from {timeline_path.name}...")
    logger.info("NLE Engine: Re-rendering video from %s...", timeline_path.name)

    last = [-1]

    def progress(pct: float) -> None:
        # Read by export_video in lib.rs, which forwards it to the app as "export-progress".
        if int(pct) != last[0]:
            last[0] = int(pct)
            print(f"EXPORT_PROGRESS {int(pct)}", file=sys.stderr, flush=True)

    final_path = VideoExporter.concat_from_timeline(
        timeline_data=timeline_data, output_path=output_video_path,
        on_progress=progress,
    )

    print(f"Fast re-render complete  {final_path}")
    logger.info("NLE Engine: Fast re-render complete  %s", final_path)
    return final_path
