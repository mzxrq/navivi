"""Final step: build the end-of-video "places visited" outro (scrolling cards
by default, or the single-frame grid)."""

from collections import Counter
from pathlib import Path
from typing import Optional, Tuple

from services import tuning
from services.config.job_config import JobConfigManager

from .helpers import logger, project_video_dir


def _outro_style(settings: dict) -> str:
    """settings.outro_style, or the scroll for one this version doesn't have ("map" moved to the overview)."""
    style = str(settings.get("outro_style", tuning.DEFAULT_OUTRO_STYLE)).lower()
    return style if style in ("scroll", "grid", "scrapbook") else "scroll"


def _route_frame_size(video_dir: Path) -> Optional[Tuple[int, int]]:
    """The frame size most of the project's route clips have - what the
    final export sizes the whole video to (see VideoExporter._timeline_size)
    - so the outro can be drawn at that size instead of being stretched up
    to it. None when there are no route clips yet."""
    from services.vdoprocessing.vdoexporter import VideoExporter

    sizes = [VideoExporter._video_size(p) for p in sorted((video_dir / "route").glob("*.mp4"))]
    sizes = [sz for sz in sizes if sz]
    return Counter(sizes).most_common(1)[0][0] if sizes else None


def _edited_heading_sizes(timeline_path: Path) -> dict:
    """{"title_size", "subtitle_size"} of the outro text item as the timeline editor left it (the scrapbook keeps
    that much room above its cards); {} when there is none."""
    import json

    try:
        texts = json.loads(timeline_path.read_text(encoding="utf-8")).get("texts") or []
    except (OSError, ValueError):
        return {}
    item = next((x for x in texts if isinstance(x, dict) and x.get("kind") == "outro"), None) or {}
    out = {}
    for line in ("title", "subtitle"):
        size = ((item.get(line) or {}).get("style") or {}).get("font_size")
        if isinstance(size, (int, float)) and not isinstance(size, bool) and size > 0:
            out[f"{line}_size"] = float(size)
    return out


def _outro_heading(job_config: JobConfigManager) -> dict:
    """The intro's words with the outro's own look: text styles settings.outro_*_style (never the intro's;
    unset = the defaults), the box behind the title settings.outro_header_height (1080-line px) / outro_header_color."""
    from .intro_step import intro_heading

    settings = job_config.get("settings", {}) or {}
    heading = intro_heading(job_config)
    for line in ("kicker", "title", "subtitle"):
        heading[f"{line}_style"] = settings.get(f"outro_{line}_style")
    heading["header_height"] = settings.get("outro_header_height")
    heading["header_color"] = settings.get("outro_header_color")
    return heading


def outro_text_item(project_config_path: str) -> Optional[dict]:
    """The scroll outro's kicker + title + subtitle as a text-track item over its pinned box, ending where
    the logo end card starts (`trim_end` seconds before the clip's end; build_timeline uses it). None when
    the outro is off or not a scroll (the grid burns its text)."""
    from services.vdoprocessing.introclip import DEFAULT_KICKER_STYLE, DEFAULT_SUBTITLE_STYLE, DEFAULT_TITLE_STYLE
    from services.vdoprocessing.outrocard import end_card_seconds, header_height_1080

    config_path = Path(project_config_path)
    if not config_path.exists():
        return None
    job_config = JobConfigManager(config_path)
    settings = job_config.get("settings", {}) or {}
    if not settings.get("enable_outro", tuning.DEFAULT_ENABLE_OUTRO):
        return None
    style_name = _outro_style(settings)
    if style_name not in ("scroll", "scrapbook"):
        return None
    h = _outro_heading(job_config)
    if not (h["title"] or h["subtitle"] or h["kicker"]):
        return None

    def line(which: str, default) -> dict:
        # Smaller than the intro's, as the burned outro title was (OUTRO_HEADING_SCALE), unless the style says a size.
        style = dict(h[f"{which}_style"]) if isinstance(h[f"{which}_style"], dict) else {}
        style.setdefault("font_size", round(default.font_size * tuning.OUTRO_HEADING_SCALE))
        return {"text": h[which], "style": style}

    item = {
        # Still: without its own animation a line takes the intro's pop/rise (line_motion).
        "kind": "outro", "animation": "none", "position": "top", "margin_v": tuning.OUTRO_TEXT_MARGIN_TOP,
        "title": line("title", DEFAULT_TITLE_STYLE), "subtitle": line("subtitle", DEFAULT_SUBTITLE_STYLE),
        "trim_end": end_card_seconds(),
    }
    if h["kicker"]:
        item["kicker"] = line("kicker", DEFAULT_KICKER_STYLE)
    if style_name == "scrapbook":
        # Ink on the paper, in the band the cards leave free (outrocard.SCRAPBOOK_HEADING_*); no box.
        from services.vdoprocessing.outrocard import SCRAPBOOK_HEADING_MARGIN, SCRAPBOOK_HEADING_SIZES

        ink = "#%02X%02X%02X" % tuning.OUTRO_SCRAPBOOK_INK
        for which, size in zip(("title", "subtitle"), SCRAPBOOK_HEADING_SIZES):
            style = dict(h[f"{which}_style"]) if isinstance(h[f"{which}_style"], dict) else {}
            for key, value in (("font_size", size), ("color", ink), ("shadow", 0.0), ("outline_width", 0.0)):
                style.setdefault(key, value)
            item[which] = {"text": h[which], "style": style}
        item["margin_v"] = SCRAPBOOK_HEADING_MARGIN
        item.pop("kicker", None)
        return item
    # The cards scroll the full frame, so the box behind the title is what hides them. It starts as tall as
    # the title block (the old pinned box); settings.outro_header_color / outro_header_height seed it and
    # the timeline editor's "Box behind" changes it.
    has_route = False
    if settings.get("outro_route_info", tuning.DEFAULT_OUTRO_ROUTE_INFO):
        try:
            from services.localization.route_brief import load_brief

            has_route = bool(load_brief(str(config_path)).get("legs"))
        except Exception:
            pass
    color = h["header_color"] or "#%02X%02X%02X" % tuning.OUTRO_BG_COLOR
    height = round(float(h["header_height"] or header_height_1080(h, has_route)))
    # `base`: the height the video was laid out with; the export pushes the content by height - base.
    item["box"] = {"color": color, "opacity": 1.0, "fade": tuning.OUTRO_TEXT_BOX_FADE, "height": height, "base": height}
    return item


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
    style = _outro_style(settings)

    brief = None
    if settings.get("outro_route_info", tuning.DEFAULT_OUTRO_ROUTE_INFO):
        try:
            from services.localization.route_brief import load_brief

            brief = load_brief(str(config_path))
        except Exception as exc:
            logger.warning("Outro step: no route info (%s) — cards only.", exc)

    heading = _outro_heading(job_config)
    title = heading["title"]
    # The scroll's title is a text-track item (outro_text_item), so the timeline editor can change it.
    heading["burn_text"] = style not in ("scroll", "scrapbook")
    heading.update(_edited_heading_sizes(config_path.parent / "timeline.json"))

    logger.info("Outro step: building %s outro clip for project '%s'.", style, project_name)
    outro_path = generate_outro_clip(
        video_dir=str(video_dir), project_name=title, waypoints=waypoints, style=style,
        size=_route_frame_size(Path(video_dir)), brief=brief, heading=heading,
        settings=settings,
    )

    if outro_path:
        logger.info("Outro step complete: %s", outro_path)
    else:
        logger.info(
            "Outro step: no outro produced (no waypoints with an image, or generation failed)."
        )

    return outro_path
