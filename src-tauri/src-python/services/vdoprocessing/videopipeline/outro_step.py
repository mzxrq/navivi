"""Final step: build the end-of-video "places visited" card grid."""

from pathlib import Path
from typing import Optional

from services.config.job_config import JobConfigManager

from .helpers import logger


def render_outro_clip(project_config_path: str) -> Optional[str]:
    """Builds the project's outro clip: the project name plus a numbered
    thumbnail grid of every waypoint with a popup image, held for a fixed
    duration. Returns None (never raises) if there are no waypoints with an
    image or generation fails — an outro is optional, not something that
    should hard-fail a pipeline run."""
    config_path = Path(project_config_path)
    if not config_path.exists():
        logger.warning("Outro step: no project config found at %s — skipping.", config_path)
        return None

    from services.vdoprocessing.outrocard import generate_outro_clip

    job_config = JobConfigManager(config_path)
    project_name = job_config.get("project_name", "")
    waypoints = job_config.get("waypoints", [])
    video_dir = Path(job_config.get("directory_path", config_path.parent)) / "video"

    logger.info("Outro step: building outro clip for project '%s'.", project_name)
    outro_path = generate_outro_clip(
        video_dir=str(video_dir), project_name=project_name, waypoints=waypoints
    )

    if outro_path:
        logger.info("Outro step complete: %s", outro_path)
    else:
        logger.info(
            "Outro step: no outro produced (no waypoints with an image, or generation failed)."
        )

    return outro_path
