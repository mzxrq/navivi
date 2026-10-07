"""Shared helpers for the CLI command modules: output-dir resolution,
filename sanitization, and job_config.json waypoint loading."""

import json
from pathlib import Path

from services.vdoprocessing.videopipeline.helpers import project_video_dir
from services.vdoprocessing.videopipeline.helpers import safe_label as _video_safe_label  # noqa: F401  (re-exported by services/cli)


def _output_dir_from_config(job_config_path: str) -> str:
    """Every job_config.json carries its own project folder as
    "directory_path" (set once, at project creation) — so the video/audio/
    subtitle output dirs never need to be passed on the command line
    separately from the config path itself. Falls back to the config
    file's own parent directory for a job_config.json that predates the
    "directory_path" field."""
    config_path = Path(job_config_path)
    directory_path = None
    try:
        with config_path.open("r", encoding="utf-8") as config_file:
            directory_path = json.load(config_file).get("directory_path")
    except (OSError, json.JSONDecodeError):
        pass
    base_dir = Path(directory_path) if directory_path else config_path.parent
    return str(project_video_dir(base_dir))


def _load_settings(job_config_path) -> dict:
    with Path(job_config_path).open("r", encoding="utf-8") as config_file:
        return json.load(config_file).get("settings", {}) or {}


def _apply_pipeline_settings(job_config_path) -> dict:
    """Sets the same per-project switches run_full_pipeline sets before its
    stages, so a single CLI mode speaks, cues and renders like the app."""
    from services.vdoprocessing.videopipeline.audio_step import set_route_only_legs
    from services.vdoprocessing.videopipeline.helpers import attraction_videos_enabled

    settings = _load_settings(job_config_path)
    set_route_only_legs(attraction_videos_enabled(settings))
    return settings


def _load_tts_waypoints(job_config_path: str) -> tuple[Path, list]:
    config_path = Path(job_config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"job_config.json not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as config_file:
        project_config = json.load(config_file)

    waypoints = project_config.get("waypoints", [])
    if not isinstance(waypoints, list):
        raise ValueError("job_config.json 'waypoints' must be a list")

    return config_path, waypoints
