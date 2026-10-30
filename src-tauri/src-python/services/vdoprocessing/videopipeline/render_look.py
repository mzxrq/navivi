"""The route video's look from the project's settings: pin glyphs and colors, line colors per mode,
and the look options handed to the renderer."""

from typing import Optional

from services import tuning

from .helpers import logger


def _project_color(
    settings: dict, key: str, default_bgr: tuple
) -> tuple:
    """Reads one color setting out of job_config.json, as BGR.

    The app writes colors as RGB triples (it stores exactly what the color
    picker produced — settings.marker_color [59, 130, 246] is #3B82F6, the
    blue shown in the editor), while every renderer downstream draws in
    OpenCV's BGR. Handing the value straight through — which is what this
    used to do — rendered a project's chosen blue as #F6823B orange, i.e.
    a configured color came out as its own channel-reversed twin. The
    channels are swapped here, at the single point where a project's
    settings become renderer config, so there is exactly one place that
    knows about the difference.

    `default_bgr` is used unchanged when the project didn't set the key:
    the defaults live in tuning.py and are already authored in BGR.
    """
    raw = settings.get(key)
    if raw is None:
        return tuple(default_bgr)
    try:
        r, g, b = (int(v) for v in list(raw)[:3])
    except (TypeError, ValueError):
        logger.warning(
            "Step 4: settings.%s is not an [r, g, b] triple (%r) — using the default.",
            key, raw,
        )
        return tuple(default_bgr)
    return (b, g, r)


# How much darker a pin goes once its waypoint has been reached, when the
# project sets marker_color but no arrived_marker_color of its own: the
# two defaults in tuning.py sit about this far apart, so one configured
# color still yields the same "deepens on arrival" pairing rather than
# leaving every arrived pin on an unrelated stock blue.
_ARRIVED_COLOR_DARKEN = 0.78


def overview_pin_glyphs(waypoints: list) -> dict:
    """{waypoint position: the glyph its pin shows on the overview}: "S" for
    the first, "E" for the last, "・" for a stop-by, and 1, 2, 3... for the
    rest in visit order - the same numbering as spatial_renderer's
    _pin_label_and_color (S and stop-bys don't take a number), so a leg's
    map can show "pin 1 -> pin 2" exactly as the overview does."""
    glyphs = {}
    order = 0
    last = len(waypoints) - 1
    for pos, wp in enumerate(waypoints):
        # A waypoint skipped in video export is drawn like a stop-by too.
        if wp.get("isStopBy") or (wp.get("skipAssetGeneration") and 0 < pos < last):
            glyphs[pos] = "・"
            continue
        if pos == 0:
            glyphs[pos] = "S"
            continue
        order += 1
        glyphs[pos] = "E" if pos == last and order != 1 else str(order)
    return glyphs


def _returns_to(waypoints: list, pos: int) -> Optional[dict]:
    """The earlier stop a return stop ("Add return stop": a copy at the same spot) comes back to, else None."""
    # A stop-by beside an earlier stop is its own place; the trip's last stop ends the video like any finish.
    if not 0 < pos < len(waypoints) - 1 or waypoints[pos].get("isStopBy"):
        return None
    from services.vdoprocessing.route_inputs import same_place

    return next((w for w in waypoints[:pos] if not w.get("isStopBy") and same_place(waypoints[pos], w)), None)


def _is_return_stop(waypoints: list, pos: int) -> bool:
    return _returns_to(waypoints, pos) is not None


def _leg_pin(glyph, settings: dict, arrived: bool, image: Optional[str] = None) -> Optional[dict]:
    """One end of a leg's pin, in the overview's colors: S green, E red, a
    stop-by brown, a numbered stop the marker color (the darker "arrived"
    shade for the pin the leg departs from, which is already visited)."""
    if not glyph:
        return None
    if glyph == "S":
        color = _project_color(settings, "start_pin_color", tuning.START_PIN_COLOR)
    elif glyph == "E":
        color = _project_color(settings, "end_pin_color", tuning.END_PIN_COLOR)
    elif glyph == "・":
        color = _project_color(settings, "stopby_pin_color", tuning.STOPBY_PIN_COLOR)
    else:
        marker = _project_color(settings, "marker_color", (235, 150, 60))
        color = _arrived_marker_color(settings, marker) if arrived else marker
    pin = {"glyph": glyph, "color": tuple(int(c) for c in color)}
    if image and glyph != "・":  # a stop-by stays a dot
        pin["image"] = image
    return pin


def _arrived_marker_color(settings: dict, marker_bgr: tuple) -> tuple:
    """The color a pin turns once its waypoint has been reached: the
    project's own arrived_marker_color if it set one, else a darker shade
    of its marker_color, else the stock default."""
    if settings.get("arrived_marker_color") is not None:
        return _project_color(
            settings, "arrived_marker_color", tuning.DEFAULT_ARRIVED_MARKER_COLOR
        )
    if settings.get("marker_color") is not None:
        return tuple(max(0, min(255, int(c * _ARRIVED_COLOR_DARKEN))) for c in marker_bgr)
    return tuple(tuning.DEFAULT_ARRIVED_MARKER_COLOR)


def _project_rgb(settings: dict, key: str) -> Optional[list]:
    """A project colour setting as an RGB list (pydeck's order), or None."""
    value = settings.get(key)
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return [int(c) for c in value[:3]]
    return None


# Modes drawn with the project's Route Line color, matching the editor.
# Flights keep their own accent. "direct"/"draw" alias to walking.
_LINE_COLOR_MODES = ("walking", "driving", "car", "ferry")


def _mode_line_color_overrides(settings: dict) -> dict:
    """Per-mode route-line colors as BGR: settings.line_color for every
    ordinary mode, then settings.mode_line_colors per mode on top."""
    overrides = {}
    if settings.get("line_color") is not None:
        for mode in _LINE_COLOR_MODES:
            overrides[mode] = _project_color(settings, "line_color", tuning.MODE_LINE_COLORS[mode])
    per_mode = settings.get("mode_line_colors") or {}
    if isinstance(per_mode, dict):
        for mode, value in per_mode.items():
            key = str(mode).strip().lower()
            key = tuning.MODE_ALIASES.get(key, key)
            overrides[key] = _project_color(
                {key: value}, key, tuning.MODE_LINE_COLORS.get(key, (110, 110, 110))
            )
    return overrides


# [NOTE] [Config] Renderer options the "Look of the video" settings reach. Each default equals what the
# reader downstream (spatial_renderer/*, route2vdo.py) falls back to, so a project that never sets one
# renders as before. They used to be read downstream but never forwarded, so even a hand edit did nothing.
_LOOK_OPTION_DEFAULTS = (
    ("show_compass", True),
    ("waypoint_map_border", True),
    ("waypoint_intro_freeze", 2.0),
    ("show_leg_wide_intro", False),
    ("res_follow_pitch", 0.0),
    ("street_photos_at_turns", tuning.STREET_PHOTOS_AT_TURNS),
    ("overview_max_leg_seconds", 10.0),
    ("overview_intro_card_scale", 1.3),
    ("overview_intro_clean_hold_seconds", 1.5),
    ("overview_title", None),
    # overview_script.py reads the same key off the raw settings (default on): both now agree.
    ("enable_ending_highlight", True),
)


def look_options(settings: dict) -> dict:
    """The renderer options of _LOOK_OPTION_DEFAULTS, read off the project's settings."""
    return {key: settings.get(key, default) for key, default in _LOOK_OPTION_DEFAULTS}
