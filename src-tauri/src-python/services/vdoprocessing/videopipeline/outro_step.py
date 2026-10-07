"""Final step: build the end-of-video "places visited" outro (scrolling cards
by default, or the single-frame grid)."""

from collections import Counter
from pathlib import Path
from typing import Optional, Tuple

from services import tuning
from services.config.job_config import JobConfigManager

from .helpers import logger, project_video_dir


def _route_frame_size(video_dir: Path) -> Optional[Tuple[int, int]]:
    """The frame size most of the project's route clips have - what the
    final export sizes the whole video to (see VideoExporter._timeline_size)
    - so the outro can be drawn at that size instead of being stretched up
    to it. None when there are no route clips yet."""
    from services.vdoprocessing.vdoexporter import VideoExporter

    sizes = [VideoExporter._video_size(p) for p in sorted((video_dir / "route").glob("*.mp4"))]
    sizes = [sz for sz in sizes if sz]
    return Counter(sizes).most_common(1)[0][0] if sizes else None


def render_outro_clip(project_config_path: str) -> Optional[str]:
    """Builds the project's outro clip: the project name plus a numbered
    card for every waypoint with a popup image (scrolling, or one held grid). Returns None (never raises) if there are no waypoints with an
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
    video_dir = project_video_dir(job_config.get("directory_path", config_path.parent))

    settings = job_config.get("settings", {}) or {}
    # settings.enable_outro: false = no outro clip at all (default on, as before).
    if not settings.get("enable_outro", tuning.DEFAULT_ENABLE_OUTRO):
        logger.info("Outro step: switched off in the project settings - skipping.")
        return None

    # settings.outro_style: "scroll" (default, tuning.DEFAULT_OUTRO_STYLE) or "grid".
    style = str(settings.get("outro_style", tuning.DEFAULT_OUTRO_STYLE)).lower()

    brief = None
    if settings.get("outro_route_info", tuning.DEFAULT_OUTRO_ROUTE_INFO):
        try:
            from services.localization.route_brief import load_brief

            brief = load_brief(str(config_path))
        except Exception as exc:
            logger.warning("Outro step: no route info (%s) — cards only.", exc)

    from .intro_step import intro_heading

    heading = intro_heading(job_config)
    title = heading["title"]

    logger.info("Outro step: building %s outro clip for project '%s'.", style, project_name)
    outro_path = generate_outro_clip(
        video_dir=str(video_dir), project_name=title, waypoints=waypoints, style=style,
        size=_route_frame_size(Path(video_dir)), brief=brief, heading=heading,
    )

    if outro_path:
        logger.info("Outro step complete: %s", outro_path)
    else:
        logger.info(
            "Outro step: no outro produced (no waypoints with an image, or generation failed)."
        )

    return outro_path
