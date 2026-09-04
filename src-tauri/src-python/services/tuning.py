"""Central place for the hand-tunable constants used by the video-rendering
pipeline (spatial_renderer + graphicengine) — mode speeds, pin/line colors,
and the end-of-video highlight/transition timing. These are exactly the
values that get adjusted most often when tuning how a render looks or
feels (durations, zoom targets, speeds, colors) — collected here instead of
scattered as class attributes across a dozen files, so there's one place to
check instead of hunting through spatial_renderer/*.py and
graphicengine/*.py. Per-project overrides still go through job_config.json's
settings (e.g. settings.mode_speeds_kmh) — these are only the fallback
defaults.
"""

from typing import Dict, Tuple

# --- Mode speeds (km/h) -----------------------------------------------------
# REPORTED is the real-world speed a leg's distance/time is estimated from
# when no real GPS timestamp is available (drives the summary/per-leg
# stat cards). ANIMATION is a separate, usually faster set of speeds that
# drives the on-screen travel pace instead — kept apart so a realistic
# (and often much slower) reported walking speed doesn't also drag the
# walking leg's on-screen animation out longer. Modes not listed in
# ANIMATION_MODE_SPEED_KMH reuse their REPORTED speed for animation too.
REPORTED_MODE_SPEED_KMH: Dict[str, float] = {
    "walking": 3.0,
    "ferry": 35.0,  # regular passenger ferry, not a high-speed jet ferry
    "car": 70.0,
    "driving": 70.0,
    "airplane": 500.0,
}
ANIMATION_MODE_SPEED_KMH: Dict[str, float] = {
    "walking": 8.0,
}
# Fixed anchor "1x" pace every mode's on-screen speed-up factor is computed
# against — not whatever "walking" happens to be configured as (see
# SpatialRenderer._mode_speed_factor).
REFERENCE_SPEED_KMH = 3.0

# --- Pin / line colors (BGR) ------------------------------------------------
START_PIN_COLOR: Tuple[int, int, int] = (60, 180, 60)  # green
END_PIN_COLOR: Tuple[int, int, int] = (0, 0, 220)  # red
DEFAULT_MARKER_COLOR: Tuple[int, int, int] = (235, 150, 60)  # blue — every pin except S/E
DEFAULT_ARRIVED_MARKER_COLOR: Tuple[int, int, int] = (200, 110, 30)  # deeper blue once visited
# Per-travel-mode ROUTE LINE colors. Modes without an entry (e.g. walking)
# fall back to the renderer's own line_color.
MODE_LINE_COLORS: Dict[str, Tuple[int, int, int]] = {
    "ferry": (0, 140, 255),  # orange — reads clearly against blue water
    "airplane": (180, 60, 220),  # magenta/purple
    "car": (60, 180, 60),  # green
    "driving": (60, 180, 60),
}

# --- End-of-video "zoom to start point" highlight ---------------------------
# How long the freshly-fetched close-up tile is held/zoomed after the hard
# cut, before handing off to the fullscreen photo transition (or just
# holding).
ENDING_HIGHLIGHT_WAIT_SECONDS = 2.2
# Lead-in: how long to push in on the CURRENT wide map (clean, no cards)
# toward the same point BEFORE that hard cut, and how far.
BIG_MAP_ZOOM_LEAD_SECONDS = 2.0
BIG_MAP_ZOOM_TARGET = 2.6

# --- Popup / transition timing ----------------------------------------------
POPUP_FADE_SECONDS = 1.5
FULLSCREEN_TRANSITION_DEFAULTS: Dict[str, float] = {
    "confirm_seconds": 0.4,
    "scale_seconds": 2.5,
    "blur_seconds": 0.5,
    "fade_out_seconds": 0.5,
    "hold_ratio_of_freeze": 0.4,
    "min_hold_seconds": 0.5,
    "min_small_hold_seconds": 0.1,
}
TRIGGER_RADIUS_PADDING_DEFAULTS: Dict[str, float] = {"overview": 10, "waypoint": 15}
