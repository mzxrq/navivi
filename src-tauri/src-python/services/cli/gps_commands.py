"""Isolated CLI commands for pipeline Step 1 (GPS parsing) and the
overview/residential video rendering steps."""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from services.logger.progress import tracker as _tracker
from services.vdoprocessing.videopipeline.helpers import project_route_video_dir


def test_gps(job_config_path: str) -> Dict[str, Any]:
    """Runs GPS parsing only (pipeline Step 1) — isolated so editing just
    raw_track.gpx/job_config.json's GPS-related settings can be checked
    without paying for TTS/attraction/video/subtitle stages. Every other
    test_* function across services/cli/ is this same one-step-only shape
    for its own pipeline step — together they cover all 5 of
    run_full_pipeline's steps individually, so a change scoped to one
    step/file doesn't require re-running the whole pipeline to check it."""
    from services.vdoprocessing.videopipeline import process_gps

    config_path = Path(job_config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"job_config.json not found: {config_path}")

    _tracker.show("Parsing GPS track...")
    cleaned_route = process_gps(str(config_path))
    _tracker.clear()
    return {
        "success": True,
        "summary": cleaned_route.get("summary", {}),
    }


def test_overview_video(
    job_config_path: str, output_video_dir: str = None, force: bool = False
) -> Dict[str, Any]:
    """Runs GPS parsing + route video rendering only, to sanity-check the
    overview map animation without paying for TTS/attraction/subtitle
    stages. render_mode="overview" also skips residential entirely (no
    per-leg residential map tile fetches, no residential clips rendered) —
    this really is overview-only now, not both bundled together."""
    from services.vdoprocessing.videopipeline import process_gps, render_route_video

    config_path = Path(job_config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"job_config.json not found: {config_path}")

    output_video_dir = output_video_dir or str(project_route_video_dir(config_path.parent))

    _tracker.show("Parsing GPS track...")
    cleaned_route = process_gps(str(config_path))
    _tracker.clear()

    _tracker.show("Rendering overview video...")
    video_paths = render_route_video(
        cleaned_route=cleaned_route,
        project_config_path=str(config_path),
        output_video_dir=output_video_dir,
        force=force,
        render_mode="overview",
    )
    _tracker.clear()

    return {
        "success": True,
        "video_paths": video_paths,
        "summary": cleaned_route.get("summary", {}),
    }


def test_residential_video(
    job_config_path: str,
    output_video_dir: str = None,
    fps: Optional[int] = None,
    speed_kmh: Optional[float] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Runs the per-waypoint leg-by-leg render only, to sanity-check the
    residential animation without paying for the overview, TTS, or subtitle
    stages. Honors job_config.json's settings.use_3d_res (default False):
    2D (SpatialRenderer.render_waypoints, via the same render_route_video
    path test_overview_video uses, but with render_mode="residential" so
    the overview animation itself is never rendered) unless the project
    has explicitly opted into the 3D pydeck/Playwright renderer (which
    never touches render_route_video/the overview path at all).
    """
    config_path = Path(job_config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"job_config.json not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as config_file:
        project_config = json.load(config_file)
    use_3d_res = bool(project_config.get("settings", {}).get("use_3d_res", False))

    output_video_dir = Path(output_video_dir) if output_video_dir else project_route_video_dir(config_path.parent)
    output_video_dir.mkdir(parents=True, exist_ok=True)

    if use_3d_res:
        output_video_path = str(output_video_dir / "02_residential_map.mp4")

        from services.vdoprocessing.pydeckrecorder import record_headless_video

        _tracker.show("Rendering residential video (3D)...")
        video_paths = record_headless_video(
            str(config_path),
            output_video_path,
            fps=fps,
            speed_kmh=speed_kmh,
        )
        _tracker.clear()
    else:
        from services.vdoprocessing.videopipeline import process_gps, render_route_video

        _tracker.show("Parsing GPS track...")
        cleaned_route = process_gps(str(config_path))
        _tracker.clear()

        _tracker.show("Rendering residential video (2D)...")
        video_paths = render_route_video(
            cleaned_route=cleaned_route,
            project_config_path=str(config_path),
            output_video_dir=str(output_video_dir),
            force=force,
            render_mode="residential",
        )
        _tracker.clear()

    return {
        "success": bool(video_paths),
        "video_paths": video_paths,
    }
