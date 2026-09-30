"""Isolated CLI commands for pipeline Step 5 (subtitle generation from
matching TTS audio) — thin wrappers over
services/vdoprocessing/videopipeline/subtitle_step.py, the subtitle
domain's core module."""

from pathlib import Path
from typing import Any, Dict

from services.logger.progress import tracker as _tracker
from services.vdoprocessing.videopipeline.helpers import (
    project_audio_dir,
    project_subtitle_dir,
    waypoint_audio_filename,
)
from services.vdoprocessing.videopipeline.audio_step import apply_cued_scripts, existing_audio_data
from services.vdoprocessing.videopipeline.subtitle_step import (
    build_attraction_subtitles,
    build_overview_subtitle,
    build_subtitles,
    build_waypoint_subtitle,
)
from .helpers import _apply_pipeline_settings, _load_tts_waypoints


def _subtitle_audio_path(config_path: Path, waypoint_index: int, label: Any) -> Path:
    return project_audio_dir(config_path.parent) / waypoint_audio_filename(waypoint_index, label)


def test_subtitle(
    job_config_path: str,
    output_subtitle_dir: str = None,
    waypoint_index: int = 0,
    force: bool = False,
) -> Dict[str, Any]:
    """Generate subtitles for one waypoint from its matching TTS audio."""
    _apply_pipeline_settings(job_config_path)
    config_path, waypoints = _load_tts_waypoints(job_config_path)
    apply_cued_scripts(waypoints, config_path.parent)
    if waypoint_index < 0 or waypoint_index >= len(waypoints):
        raise IndexError(
            f"waypoint_index must be between 0 and {len(waypoints) - 1}, "
            f"got {waypoint_index}"
        )
    waypoint = waypoints[waypoint_index]
    label = waypoint.get("label", f"Waypoint {waypoint_index + 1}") if isinstance(waypoint, dict) else f"Waypoint {waypoint_index + 1}"
    audio_path = _subtitle_audio_path(config_path, waypoint_index, label)
    output_dir = Path(output_subtitle_dir) if output_subtitle_dir else project_subtitle_dir(config_path.parent)

    result = build_waypoint_subtitle(
        waypoint, waypoint_index, str(audio_path), output_dir, force=force
    )
    return {"success": True, **result}


def test_subtitles(
    job_config_path: str,
    output_subtitle_dir: str = None,
    force: bool = False,
) -> Dict[str, Any]:
    """The pipeline's Step 2b: leg, overview and attraction subtitles from
    the narration audio already on disk."""
    import json

    _apply_pipeline_settings(job_config_path)
    config_path, waypoints = _load_tts_waypoints(job_config_path)
    apply_cued_scripts(waypoints, config_path.parent)
    output_dir = Path(output_subtitle_dir) if output_subtitle_dir else project_subtitle_dir(config_path.parent)
    audio = existing_audio_data(str(config_path))

    subtitle_paths = build_subtitles(waypoints, audio["audio_paths"], str(output_dir), force=force)
    overview_path = build_overview_subtitle(
        json.loads(config_path.read_text(encoding="utf-8")),
        audio.get("overview_audio_path"), str(output_dir), force=force,
    )
    attraction_paths = build_attraction_subtitles(
        waypoints, audio["attraction_audio_paths"], str(output_dir), force=force
    )
    _tracker.clear()
    return {
        "success": True,
        "subtitle_dir": str(output_dir),
        "subtitle_paths": subtitle_paths,
        "overview_subtitle_path": overview_path,
        "attraction_subtitle_paths": attraction_paths,
    }
