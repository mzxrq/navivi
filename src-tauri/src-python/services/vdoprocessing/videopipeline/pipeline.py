"""Orchestration entry points: the master pipeline, NLE fast re-render, and step-duration estimates."""

import json
from pathlib import Path
from typing import Optional

from tqdm import tqdm

from services.config.job_config import JobConfigManager
from services.vdoprocessing.vdoexporter import VideoExporter

from .attraction_step import render_attraction_videos
from .audio_step import generate_audio
from .gps_step import process_gps
from .helpers import logger
from .render_step import render_route_video
from .subtitle_step import burn_subtitles
from .timeline_step import build_timeline


def run_full_pipeline(
    raw_source_path: str, output_video_dir: Optional[str] = None
) -> dict:
    """Executes all steps sequentially with a single progress bar at the bottom."""
    # Clear the console screen for a fresh, clean view
    print("\033[H\033[J", end="")

    print("Starting Automated Video Rendering Pipeline\n")

    source_path = Path(raw_source_path)
    project_dir = source_path.parent
    config_file_path = project_dir / "job_config.json"
    job_config = JobConfigManager(config_file_path)

    if not output_video_dir:
        base_path = Path(job_config.get("directory_path", project_dir))
        output_video_dir = str((base_path / "video").resolve())

    # Initialize a single progress bar for the 4 main steps
    with tqdm(
        total=100,
        desc="Progress",
        bar_format="{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [Time: {elapsed}<{remaining}]",
    ) as pbar:

        # --- STEP 1 ---
        cleaned_route = process_gps(raw_source_path)
        pbar.update(2)

        # --- STEP 2 ---
        audio_data = generate_audio(cleaned_route, str(config_file_path))
        pbar.update(8)

        # --- STEP 3 ---
        attraction_videos = render_attraction_videos(
            str(config_file_path),
            audio_durations=audio_data.get("audio_durations"),
            audio_paths=audio_data.get("audio_paths"),
        )
        pbar.update(60)

        # --- STEP 4 ---
        video_paths = render_route_video(
            cleaned_route=cleaned_route,
            project_config_path=str(config_file_path),
            output_video_dir=output_video_dir,
            audio_durations=audio_data.get("audio_durations"),
            audio_pauses=audio_data.get("audio_pauses"),
            audio_paths=audio_data.get("audio_paths"),
        )
        pbar.update(85)

        all_videos = video_paths + attraction_videos

        # --- STEP 5 ---
        final_videos = burn_subtitles(
            video_paths=all_videos,
            subtitle_paths=audio_data.get("subtitle_paths", []),
            output_dir=output_video_dir,
        )
        pbar.update(5)

        # --- STEP 6 ---
        timeline_path = build_timeline(
            video_paths=video_paths,
            attraction_videos=attraction_videos,
            final_videos=final_videos,
            audio_paths=audio_data.get("audio_paths"),
            subtitle_paths=audio_data.get("subtitle_paths"),
            project_dir=str(project_dir),
        )

    print("\nProject Rendering Successfully Completed!")
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
