"""Build a short title intro from a random waypoint image (Ken Burns
zoom-in + centered title) — needs only job_config's waypoints, so it has no
dependency on any other step's rendered output.
"""

from pathlib import Path
from typing import Optional

from services.config.job_config import JobConfigManager

from .helpers import logger


def render_intro_clip(project_config_path: str) -> Optional[str]:
    """Builds the project's intro clip: a randomly-chosen waypoint popup
    image (a fresh pick every call), animated with a gradual zoom-in and
    the project's name burned in, centered. Returns None (never raises) if
    no waypoint has a popup image or generation fails — an intro is
    optional, not something that should hard-fail a pipeline run."""
    config_path = Path(project_config_path)
    if not config_path.exists():
        logger.warning("Intro step: no project config found at %s — skipping.", config_path)
        return None

    from services.vdoprocessing.introclip import generate_intro_clip

    job_config = JobConfigManager(config_path)
    project_name = job_config.get("project_name", "")
    waypoints = job_config.get("waypoints", [])
    video_dir = Path(job_config.get("directory_path", config_path.parent)) / "video"

    logger.info("Intro step: building intro clip for project '%s'.", project_name)
    intro_path = generate_intro_clip(
        video_dir=str(video_dir), project_name=project_name, waypoints=waypoints
    )

    if intro_path:
        logger.info("Intro step complete: %s", intro_path)
    else:
        logger.info(
            "Intro step: no intro produced (no attraction clips yet, or generation failed)."
        )

    return intro_path
