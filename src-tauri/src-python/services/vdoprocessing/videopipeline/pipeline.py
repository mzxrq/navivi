"""Orchestration entry points: the master pipeline, NLE fast re-render, and step-duration estimates."""

import json
from pathlib import Path
from typing import Optional

from services.config.job_config import JobConfigManager
from services.logger.progress import tracker
from services.vdoprocessing.vdoexporter import VideoExporter

from .attraction_step import render_attraction_videos
from .audio_step import generate_audio
from .gps_step import process_gps
from .helpers import logger
from .intro_step import render_intro_clip
from .outro_step import render_outro_clip
from .render_step import render_route_video
from .subtitle_step import burn_subtitles
from .timeline_step import build_timeline


def run_full_pipeline(
    raw_source_path: str, output_video_dir: Optional[str] = None
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
        output_video_dir = str((base_path / "video").resolve())

    # [NOTE] [Core] total=5 (the "[n/N]" denominator) is only set on this first stage() call — later stage() calls rely on the tracker remembering it rather than re-declaring it each time.
    tracker.stage("Parsing GPS track...", total=5)
    cleaned_route = process_gps(raw_source_path)

    # --- STEP 2 ---
    tracker.stage("Generating TTS narration...")
    audio_data = generate_audio(cleaned_route, str(config_file_path))

    # [NOTE] [TTS] Force-stop the TTS server now instead of leaving it to its
    # idle timeout — otherwise it stays loaded in VRAM while the renderer
    # below (and the attraction step's SDXL/ComfyUI pipeline, when enabled)
    # starts competing for the same VRAM right after, which can overcommit a
    # tight GPU budget. Mirrors combine_commands.py's test_all, which added
    # this after observing the same contention.
    tracker.stage("Stopping TTS server...")
    from services.tts.ttsengine import IrodoriTTSClient
    IrodoriTTSClient.stop_server()

    # # --- STEP 3 ---
    # tracker.stage("Generating attraction videos...")
    # attraction_videos = render_attraction_videos(
    #     str(config_file_path),
    #     audio_durations=audio_data.get("audio_durations"),
    #     audio_paths=audio_data.get("audio_paths"),
    # )
    #
    # # Same VRAM-contention reasoning as the TTS server above — the
    # # attraction step's ComfyUI/Wan pipeline would otherwise stay loaded
    # # into the renderer below via its own idle timeout.
    # from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient
    # ComfyUII2VClient.stop_server()

    # --- STEP 4 ---
    tracker.stage("Rendering overview & residential video...")
    video_paths = render_route_video(
        cleaned_route=cleaned_route,
        project_config_path=str(config_file_path),
        output_video_dir=output_video_dir,
        audio_durations=audio_data.get("audio_durations"),
        audio_pauses=audio_data.get("audio_pauses"),
        audio_paths=audio_data.get("audio_paths"),
    )

    all_videos = video_paths #+ attraction_videos

    # --- STEP 5 ---
    tracker.stage("Burning subtitles...")
    final_videos = burn_subtitles(
        video_paths=all_videos,
        subtitle_paths=audio_data.get("subtitle_paths", []),
        output_dir=output_video_dir,
    )

    timeline_path = build_timeline(
        video_paths=video_paths,
        #attraction_videos=attraction_videos,
        final_videos=final_videos,
        audio_paths=audio_data.get("audio_paths"),
        subtitle_paths=audio_data.get("subtitle_paths"),
        project_dir=str(project_dir),
    )
    tracker.clear()

    return {
        "video_paths": final_videos,
        "summary": cleaned_route.get("summary", {}),
        "timeline_path": timeline_path,
    }


def render_from_timeline(
    timeline_json_path: str, output_video_path: Optional[str] = None
) -> str:
    """Reads an existing timeline.json file and instantly re-renders the master video."""
    timeline_path = Path(timeline_json_path)
    if not timeline_path.exists():
        raise FileNotFoundError(f"Timeline JSON not found: {timeline_path}")

    with open(timeline_path, "r", encoding="utf-8") as f:
        timeline_data = json.load(f)

    if not output_video_path:
        project_dir = timeline_path.parent
        output_video_path = str(project_dir / "video" / "01_overview_rerendered.mp4")

    print(f"NLE Engine: Re-rendering video from {timeline_path.name}...")
    logger.info("NLE Engine: Re-rendering video from %s...", timeline_path.name)

    final_path = VideoExporter.concat_from_timeline(
        timeline_data=timeline_data, output_path=output_video_path, save_json_path=None
    )

    print(f"Fast re-render complete  {final_path}")
    logger.info("NLE Engine: Fast re-render complete  %s", final_path)
    return final_path


def estimate_step_durations(project_config: dict, cleaned_route: dict) -> dict:
    """Estimates the duration (in seconds) for each pipeline step."""
    waypoints = project_config.get("waypoints", [])
    num_waypoints = len(waypoints)

    # [NOTE] [Core] These are rough, hand-picked heuristics (not measured from real runs) for a progress-bar ETA — not meant to be an accurate benchmark.
    # Heuristics based on standard local rendering speeds
    est_gps = 1.0  # GPS parsing is very fast
    est_tts = max(2.0, num_waypoints * 1.5)  # ~1.5s per TTS narration

    # 3D video rendering depends on total frames (assume 30fps, 8s per leg/waypoint)
    est_video = max(5.0, num_waypoints * 8.0 * 0.4)

    est_ai = (
        num_waypoints * 10.0 if any(wp.get("popup_image") for wp in waypoints) else 2.0
    )
    est_subtitles = 1.0

    return {
        "gps": est_gps,
        "tts": est_tts,
        "video": est_video,
        "ai": est_ai,
        "subtitles": est_subtitles,
        "total": est_gps + est_tts + est_video + est_ai + est_subtitles,
    }
