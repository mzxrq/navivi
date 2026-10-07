"""Build a short title intro from a random waypoint image (Ken Burns
zoom-in + centered title) — needs only job_config's waypoints, so it has no
dependency on any other step's rendered output.
"""

from pathlib import Path
from typing import Optional

from services import tuning, video_text
from services.config.job_config import JobConfigManager

from .helpers import logger, project_video_dir


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
    if job_config.get("enable_intro") is False:
        logger.info("Intro step: skipped because enable_intro is False.")
        return None

    project_name = job_config.get("project_name", "")
    video_title = job_config.get("video_title")
    if not video_title:
        video_title = project_name
    video_subtitle = job_config.get("video_subtitle", "")

    waypoints = job_config.get("waypoints", [])
    video_dir = project_video_dir(job_config.get("directory_path", config_path.parent))

    logger.info("Intro step: building intro clip for project '%s'.", project_name)
    # The title and subtitle are a text item on the timeline (intro_text_item), not burned in.
    intro_path = generate_intro_clip(
        video_dir=str(video_dir), title=video_title, subtitle=video_subtitle, waypoints=waypoints,
        burn_text=False,
    )

    if intro_path:
        logger.info("Intro step complete: %s", intro_path)
    else:
        logger.info(
            "Intro step: no intro produced (no attraction clips yet, or generation failed)."
        )

    return intro_path


def place_count(waypoints) -> int:
    """Places the walk goes to: every waypoint but unconnected stop-bys."""
    from services.localization.route_brief import on_route

    return sum(1 for w in waypoints or [] if isinstance(w, dict) and on_route(w))


def intro_heading(job_config: JobConfigManager) -> dict:
    """Kicker (settings.intro_location), title and subtitle shared by the intro
    and the outro. The subtitle gets " · N places" (か所 in Japanese) unless settings.intro_place_count
    is false."""
    settings = job_config.get_settings() or {}
    title = job_config.get("video_title") or job_config.get("project_name", "") or ""
    subtitle = (job_config.get("video_subtitle", "") or "").strip()
    n = place_count(job_config.get("waypoints", []))
    if n and settings.get("intro_place_count", tuning.DEFAULT_INTRO_PLACE_COUNT) is not False:
        count = video_text.plural(video_text.current_labels(), "place_count", n, n=n)
        subtitle = tuning.INTRO_PLACE_COUNT_SEPARATOR.join(p for p in (subtitle, count) if p)
    return {
        "kicker": str(settings.get("intro_location") or "").strip(),
        "title": title,
        "subtitle": subtitle,
        "kicker_style": settings.get("intro_kicker_style"),
        "title_style": settings.get("intro_title_style"),
        "subtitle_style": settings.get("intro_subtitle_style"),
    }


def intro_text_item(project_config_path: str) -> Optional[dict]:
    """The intro's kicker + title + subtitle as a text-track item: each line's
    text and its style (settings.intro_*_style). Times are filled in by
    build_timeline, which spans it over the intro clip."""
    config_path = Path(project_config_path)
    if not config_path.exists():
        return None
    h = intro_heading(JobConfigManager(config_path))
    if not (h["title"] or h["subtitle"] or h["kicker"]):
        return None

    def line(which: str) -> dict:
        style = h[f"{which}_style"]
        return {"text": h[which], **({"style": style} if isinstance(style, dict) else {})}

    item = {"kind": "intro", "title": line("title"), "subtitle": line("subtitle")}
    if h["kicker"]:
        item["kicker"] = line("kicker")
    return item
