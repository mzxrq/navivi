"""The pipeline's hand-tuned constants (speeds, colors, timings, model settings), in one place.
Per-project overrides come from job_config.json's settings; these are the fallback defaults."""

import gc
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

# --- GPU stage cooldown ------------------------------------------------------
# Pause between the attraction (ComfyUI) stage and the Chromium route stage: two GPU loads back to back hit
# thermal shutdowns on an 8 GB laptop GPU (RTX 5060). Skipped when attraction videos are off.
GPU_STAGE_COOLDOWN_SECONDS = 8.0
# Before each Wan clip (gpu_cooldown.py): at START_C or hotter, wait until RESUME_C (polled, at most MAX_WAIT).
# Still-photo clips skip it.
GPU_COOLDOWN_START_C = 70
GPU_COOLDOWN_RESUME_C = 60
GPU_COOLDOWN_POLL_SECONDS = 3.0
GPU_COOLDOWN_MAX_WAIT_SECONDS = 120.0

# --- FFmpeg resource cap -----------------------------------------------------
# Leaves two cores free so the machine stays usable during a render.
FFMPEG_THREADS: int = max(1, (os.cpu_count() or 4) - 2)


def ffmpeg_thread_args() -> List[str]:
    """The -threads args every ffmpeg subprocess call site should splice
    into its argument list, right after the ffmpeg binary path."""
    return ["-threads", str(FFMPEG_THREADS)]


def ffmpeg_log_args() -> List[str]:
    """Quiet ffmpeg output: no banner, errors only, plus a progress line."""
    return ["-hide_banner", "-loglevel", "error", "-stats"]


def ffmpeg_pipe_log_args() -> List[str]:
    """For ffmpeg fed frames over stdin with stderr piped: no -stats, whose
    progress fills the unread pipe and deadlocks the frame writes."""
    return ["-hide_banner", "-loglevel", "error"]

# --- RAM guard -----------------------------------------------------------------
# Before each heavy stage, ensure_free_ram frees memory (gc, stopping servers) or stops the run with a clear
# message instead of swapping. settings.min_free_ram_gb overrides; 0 turns the guard off.
MIN_FREE_RAM_GB: float = 1.0
RAM_WAIT_TIMEOUT_SECONDS: float = 180.0
_RAM_POLL_SECONDS = 5.0

_ram_logger = logging.getLogger("tuning.ram")


def free_ram_gb() -> Optional[float]:
    """Memory available to new work, in GB (None if it can't be read)."""
    try:
        import psutil

        return psutil.virtual_memory().available / 2**30
    except Exception:
        return None


def ensure_free_ram(
    label: str,
    min_free_gb: Optional[float] = None,
    relief: Optional[Callable[[], None]] = None,
    timeout: Optional[float] = None,
) -> None:
    """Returns once at least `min_free_gb` (default MIN_FREE_RAM_GB) is free.
    If not: runs gc, calls `relief` once (stop a server, ...), and polls until
    memory recovers. Raises MemoryError after `timeout` seconds."""
    limit = MIN_FREE_RAM_GB if min_free_gb is None else float(min_free_gb)
    if limit <= 0:
        return
    free = free_ram_gb()
    if free is None or free >= limit:
        return
    _ram_logger.warning(
        "Low RAM before %s: %.1f GB free, need %.1f GB - freeing memory.", label, free, limit
    )
    gc.collect()
    if relief is not None:
        try:
            relief()
        except Exception as exc:  # relief is best effort
            _ram_logger.warning("RAM relief before %s failed: %s", label, exc)
    deadline = time.monotonic() + (RAM_WAIT_TIMEOUT_SECONDS if timeout is None else timeout)
    while True:
        free = free_ram_gb()
        if free is None or free >= limit:
            _ram_logger.info("RAM recovered before %s: %.1f GB free.", label, free or 0.0)
            return
        if time.monotonic() >= deadline:
            raise MemoryError(
                f"Only {free:.1f} GB of RAM is free before {label} (needs {limit:.1f} GB). "
                "Close other programs and run again - finished steps are kept and skipped."
            )
        time.sleep(_RAM_POLL_SECONDS)
        gc.collect()


# --- On-video text labels ----------------------------------------------------
# Video text comes from assets/config/labels_<lang>.json (services/video_text.py); LABELS_JA and
# PIPELINE_LABELS remain for older callers.
from services.video_text import labels_for as _labels_for  # noqa: E402

LABELS_JA: Dict = _labels_for("ja")
PIPELINE_LABELS: Dict = LABELS_JA

# --- Mode aliases ------------------------------------------------------------
# Modes treated as another everywhere (speed, icon, colors): "direct" and "draw" are walking, "curve" is the
# editor's Fly choice. Apply when a mode is first read from job_config.
MODE_ALIASES: Dict[str, str] = {"direct": "walking", "draw": "walking", "curve": "airplane"}

# Modes whose legs use the flat 2D map: the chase camera shows nothing useful over open sky.
RESIDENTIAL_2D_FALLBACK_MODES: Tuple[str, ...] = ("airplane",)

# --- Mode speeds (km/h) -----------------------------------------------------
# REPORTED: real-world speeds for distance/time when there are no GPS timestamps.
# ANIMATION_SPEED_KMH: the one on-screen pace of every mode (settings.animation_speeds_kmh overrides per mode).
REPORTED_MODE_SPEED_KMH: Dict[str, float] = {
    "walking": 3.0,
    "ferry": 35.0,  # regular passenger ferry, not a high-speed jet ferry
    "car": 70.0,
    "driving": 70.0,
    "airplane": 500.0,
}
# Naismith's rule: each 600 m of climb adds an hour to a walk. Added to the flat time (km / walking speed) of a leg
# whose recorded elevation is known; a leg without elevation keeps the flat time.
WALKING_ASCENT_M_PER_HOUR = 600.0
ANIMATION_SPEED_KMH = 3.0
# The fixed "1x" pace each mode's on-screen speed-up is measured against, independent of the speeds above.
REFERENCE_SPEED_KMH = 3.0
# Walking is shown a bit slower than the shared pace; ferry gets this boost over walking's pace.
WALKING_ANIMATION_SPEED_FACTOR = 0.75
FERRY_ANIMATION_SPEED_FACTOR = 1.5

# --- Pin / line colors (BGR) ------------------------------------------------
# The map editor's NaviPin.tsx colors, as BGR.
START_PIN_COLOR: Tuple[int, int, int] = (3, 136, 19)  # #038813 green
END_PIN_COLOR: Tuple[int, int, int] = (81, 15, 217)  # #d90f51 red/pink
DRAWN_PIN_COLOR: Tuple[int, int, int] = (12, 121, 255)  # #ff790c orange — drawn-route waypoints
STOPBY_PIN_COLOR: Tuple[int, int, int] = (28, 38, 51)  # #33261c dark brown — stop-by waypoints
# Start and end this close (degrees, ~30 m) make a loop route: the E pin is drawn half green, half red.
LOOP_ROUTE_MATCH_DEGREES = 0.0003
# Base route line: modes without their own color, and the ending highlight. Grey reads as "route" on land and water.
DEFAULT_LINE_COLOR: Tuple[int, int, int] = (110, 110, 110)  # #6e6e6e grey
DEFAULT_MARKER_COLOR: Tuple[int, int, int] = (245, 135, 66)  # #4287f5 blue — every other numbered pin
DEFAULT_ARRIVED_MARKER_COLOR: Tuple[int, int, int] = (200, 110, 30)  # deeper blue once visited
PIN_NUMBER_TEXT_COLOR: Tuple[int, int, int] = (17, 17, 17)  # #111 — NaviPin's number/letter fill

# --- Route line border (outline stroke) -------------------------------------
# A wider stroke under the route line keeps it legible over busy tiles. settings.route_line_border_color (BGR)
# and route_line_border_thickness (px per side, 0 = none) override.
DEFAULT_LINE_BORDER_COLOR: Tuple[int, int, int] = (255, 255, 255)  # white
DEFAULT_LINE_BORDER_THICKNESS = 3

# --- Popup/summary card text & border --------------------------------------
# settings.card_border_color (BGR) and card_border_thickness override.
DEFAULT_CARD_BORDER_COLOR: Tuple[int, int, int] = (230, 230, 230)  # light gray
DEFAULT_CARD_BORDER_THICKNESS = 1
# Photo caption size, as a multiple of settings.map_font_size.
POPUP_LABEL_FONT_SCALE_BESIDE = 0.9  # "beside the pin" card
POPUP_LABEL_FONT_SCALE_CORNER = 0.95  # fixed HUD-corner card
# Name chip beside each pin as the route animates (prebake_landmark_sprite).
WAYPOINT_LABEL_FONT_SCALE = 0.85
# Summary-card text, px at the card's 2x render scale.
SUMMARY_CARD_LABEL_FONT_SIZE = 20
SUMMARY_CARD_VALUE_FONT_SIZE = 34
# Summary card template: "glass", "taskbar", "stacked" or "columns" (cards.py create_summary_card_*);
# settings.summary_card_style overrides.
DEFAULT_SUMMARY_CARD_STYLE = "columns"  # the user's choice (2026-09-30)
# "columns" card: every column's text area is at least as wide as these
# sample strings, so the card keeps one width whatever the values are.
SUMMARY_CARD_FIXED_DISTANCE_SAMPLE = "88.8 km"
SUMMARY_CARD_FIXED_DURATION_SAMPLE = LABELS_JA["duration_sample"]

# --- HUD/card theme (light | dark) ------------------------------------------
# Summary card, top banner, corner HUD labels and popup caption cards.
# job_config.json's settings.theme wins (top-level "theme" too, but only when
# it is exactly "light"/"dark" — that key is normally the trip's narration theme).
DEFAULT_UI_THEME = "dark"
# RGBA, PIL (RGB) channel order.
UI_THEMES: Dict[str, Dict[str, Tuple[int, int, int, int]]] = {
    "light": {
        "card_bg": (255, 255, 255, 240),
        "card_text": (35, 35, 35, 255),
        "card_label": (110, 110, 110, 255),
        "divider": (0, 0, 0, 30),
        "pill_bg": (255, 255, 255, 235),
        "pill_text": (35, 35, 35, 255),
    },
    "dark": {
        "card_bg": (30, 34, 40, 235),
        "card_text": (245, 245, 245, 255),
        "card_label": (170, 174, 180, 255),
        "divider": (255, 255, 255, 40),
        "pill_bg": (30, 34, 40, 225),
        "pill_text": (255, 255, 255, 255),
    },
}


def resolve_ui_theme(job_config_or_settings: Optional[Dict] = None) -> str:
    """'light' or 'dark' from a job_config (or its settings dict), else DEFAULT_UI_THEME."""
    cfg = job_config_or_settings or {}
    settings = cfg.get("settings") if isinstance(cfg.get("settings"), dict) else {}
    for value in (settings.get("theme"), cfg.get("theme")):
        if isinstance(value, str) and value.strip().lower() in UI_THEMES:
            return value.strip().lower()
    return DEFAULT_UI_THEME


def ui_theme(name: Optional[str]) -> Dict[str, Tuple[int, int, int, int]]:
    return UI_THEMES.get((name or "").lower(), UI_THEMES[DEFAULT_UI_THEME])
# Minimum zoom of a leg's map, so a path that bulges or loops can't zoom out until labels are unreadable.
# Only when the two pins are within MAX_PIN_DISTANCE_M: forcing it on a long car/ferry leg multiplied the tile
# download ~4x per zoom level and never finished.
RESIDENTIAL_MIN_ZOOM = 17
RESIDENTIAL_MIN_ZOOM_MAX_PIN_DISTANCE_M = 2000
# Maximum zoom of a leg's map (the tile provider allows 19, which reads as an abstract block-level crop).
RESIDENTIAL_MAX_ZOOM = 18
# A leg's loop or detour may widen the framing to at most this many times the straight pin-to-pin distance.
RESIDENTIAL_LOOP_ZOOM_CAP = 1.5
# Floor (degrees, ~55 m) on that capped box, for a loop that returns to its own start.
RESIDENTIAL_LOOP_ZOOM_CAP_MIN_DEGREES = 0.0005
# Share of the box a pin stays away from its edge (the box is shifted, not zoomed).
RESIDENTIAL_PIN_EDGE_MARGIN = 0.10
# Share of the frame the bottom summary bar covers; the leg map is framed above it.
RESIDENTIAL_MAP_BOTTOM_BAR_FRACTION = 0.16
# Leg map tiles fetched at once (network-bound). Kept low for the tile provider's rate limit.
RESIDENTIAL_TILE_FETCH_WORKERS = 4
# Leg HUD compass under the destination pill: north-up dial, the needle follows the heading measured over
# +/- HEADING_WINDOW_M of path so GPS wiggles don't make it twitch.
RESIDENTIAL_SHOW_COMPASS = True
RESIDENTIAL_COMPASS_SIZE_PX = 104
# Leg HUD summary card size vs. the overview's card.
RESIDENTIAL_HUD_CARD_SCALE = 1.3
RESIDENTIAL_COMPASS_HEADING_WINDOW_M = 20.0
# A stop-by merges into the leg around it (its pin shown in passing) instead of getting its own leg.
# settings.merge_stopby_waypoints overrides.
DEFAULT_MERGE_STOPBY_WAYPOINTS = True
# 3D pydeck overview (GPU, Chromium) instead of the 2D one. Off (the user's choice): the 2D overview has the
# photo pop-ups and follows the cues, and still ends on the 3D zoom (settings.enable_gl_ending_zoom).
# settings.use_pydeck_overview overrides.
DEFAULT_USE_PYDECK_OVERVIEW = False
# {n}/{go} cue tags placed automatically in a hand-written overview narration (tags only, the user's own win).
# settings.auto_overview_cues overrides.
DEFAULT_AUTO_OVERVIEW_CUES = True
# A leg narration without cues gets them automatically, so the walker has arrived when the attraction text
# names the place. Tags only, the user's own win. settings.auto_narration_cues overrides.
DEFAULT_AUTO_NARRATION_CUES = True
# A numbered stop is described while the walk overview waits there (from its narration).
# settings.overview_describe_stops overrides.
DEFAULT_OVERVIEW_DESCRIBE_STOPS = True
# The overview video type, each with its own script (settings.overview_style):
# "walk"   - the walker travels the route and stops at each place (overview_script.build_tour_script);
# "course" - the whole route is shown first, then traced, with the stop-bys
#            last; the course-guide script (overview_script.build_course_script).
DEFAULT_OVERVIEW_STYLE = "walk"
OVERVIEW_STYLES = ("walk", "course")
# The arriving script the course style writes from the route (localization/leg_script.py):
# "brief" = one sentence, the overall direction only; "turns" = every turn on the way.
# Overridable per project via job_config.json's settings.leg_directions.
DEFAULT_LEG_DIRECTIONS = "brief"
# The "course" overview (spatial_renderer/course.py). The traced line is one
# accent over the whole planned route (settings.course_trace_color overrides).
COURSE_TRACE_COLOR: Tuple[int, int, int] = (40, 90, 240)  # BGR, #F05A28 orange
# Whole route shown this long after {start} when the script has no {route} cue.
COURSE_PIVOT_HOLD_SECONDS = 2.5
# Leg summary card margins. The card image has 14-20 px of transparent shadow, so the visible gap is about
# this + 14 px (right) and this + 20 px (bottom); a lower bottom margin moves the card down.
LEG_CARD_MARGIN_PX = 4
LEG_CARD_MARGIN_BOTTOM_PX = -10
# The leg's elevation profile (only with settings.show_route_heatmap and GPX heights): px on a 1080p frame,
# bottom-left, level with the summary card. pydeckrecorder/elevation.profile_card draws it.
LEG_ELEVATION_CARD_SIZE = (520, 190)
# A place the trace only passes may be reached up to this long after its cue (never before it),
# so the pace between cues stays natural; every cue still lands within 0..this.
COURSE_CUE_WINDOW_SECONDS = 0.75
# The trace never crawls slower than this share of its average pace: it waits at a place, then goes on.
COURSE_MIN_PACE_SHARE = 0.5
# Without cues: seconds of trace per leg (kept within MIN..MAX in total).
COURSE_SECONDS_PER_LEG = 3.0
COURSE_TRACE_MIN_SECONDS = 8.0
COURSE_TRACE_MAX_SECONDS = 40.0
COURSE_TAGLINE_SECONDS = 5.0
COURSE_TAGLINE_FADE_SECONDS = 0.5
COURSE_CARD_POP_SECONDS = 0.45
COURSE_STATS_SLIDE_SECONDS = 0.6
COURSE_STOPBY_STAGGER_SECONDS = 0.15
# Share of the frame kept clear of the route at the top (headline) and bottom (subtitles, stats card,
# stop-by notice), on top of OVERVIEW_PADDING_BY_SPAN_KM.
COURSE_TOP_BAND_FRACTION = 0.10
COURSE_BOTTOM_BAND_FRACTION = 0.17
# The "walk" overview keeps the same bottom band clear for its captions (no headline above).
OVERVIEW_BOTTOM_BAND_FRACTION = 0.17
# The stats card sits this much lower than the shared 20 px margin (its image has ~26 px of shadow).
COURSE_STATS_DROP_PX = 30
# Course legs: the walker slows (to 40% pace) over this long before each stop; arrival times stay.
COURSE_ARRIVAL_SLOW_SECONDS = 3.0
# A leg opens on a wide shot of the whole leg, then zooms into the close framing.
RESIDENTIAL_WIDE_HOLD_SECONDS = 1.2
RESIDENTIAL_WIDE_ZOOM_SECONDS = 1.0
# Wide shot box = the close box times this (no minimum-zoom floor).
RESIDENTIAL_WIDE_BBOX_MULTIPLIER = 2.5
# The same for a short in-town leg (pins within RESIDENTIAL_MIN_ZOOM_MAX_PIN_DISTANCE_M): 2.5x took in
# unrelated hills and bays.
RESIDENTIAL_WIDE_BBOX_MULTIPLIER_LOCAL = 1.6
# Legs shorter than this skip the wide shot (it would be the same zoom).
RESIDENTIAL_WIDE_MIN_DISTANCE_M = 400.0
# Legs longer than this are split into close-framed chunks, hard-cut; the wide shot only opens chunk 1.
RESIDENTIAL_DEFAULT_MAX_CHUNK_DISTANCE_M = 8000.0
# Route line color per travel mode; a mode missing here uses the renderer's line_color.
MODE_LINE_COLORS: Dict[str, Tuple[int, int, int]] = {
    # Blue reads well as the walking accent on the light summary card too.
    "walking": (232, 115, 26),  # #1A73E8 blue
    "ferry": (0, 140, 255),  # orange — reads clearly against blue water
    "airplane": (180, 60, 220),  # magenta/purple
    "car": (60, 180, 60),  # green
    "driving": (60, 180, 60),
}

# --- End-of-video "zoom to start point" highlight ---------------------------
# How long the ending's close-up is held/zoomed before the photo (also paces the GL zoom).
ENDING_HIGHLIGHT_WAIT_SECONDS = 0.9
# How long the ending holds the start point's photo card before the video ends.
ENDING_HIGHLIGHT_PIP_HOLD_SECONDS = 1.5
# On the GL ending the card pops in once the zoom has settled, within that hold.
ENDING_HIGHLIGHT_POP_SECONDS = 0.6
# Push-in on the wide map before the cut to the close-up: duration and scale.
BIG_MAP_ZOOM_LEAD_SECONDS = 0.8
BIG_MAP_ZOOM_TARGET = 2.6
# GL ending (settings.enable_gl_ending_zoom): one continuous re-rendered deck.gl zoom from the wide map in.
# Maximum zoom-in in log2 steps (7 = street names legible); choose_route_focus_view backs off from it when
# the route line would leave the frame, so raising it only allows more zoom.
ENDING_HIGHLIGHT_PYDECK_ZOOM_BOOST = 9.5

# --- Popup / transition timing ----------------------------------------------
POPUP_FADE_SECONDS = 1.5
# The overview's opening start/end cards stay fully up at least this long; a later {start} keeps them up.
OVERVIEW_INTRO_CARD_MIN_SECONDS = 2.0
# Minimum gap between two popups triggering, so a cluster of stops doesn't pop on one frame.
# Short: cards should arrive with the traveler, not queue up behind it.
OVERVIEW_POPUP_MIN_TRIGGER_GAP_SECONDS = 0.4
# Flow-through popup cards on screen at once.
MAX_CONCURRENT_FLOW_POPUPS = 4
# How much earlier than its expected frame a popup may trigger (absorbs the estimate's jitter only).
OVERVIEW_POPUP_TRIGGER_TOLERANCE_SECONDS = 0.2
# Seconds from a stop at which the overview banner switches from "{label} へ" to "まもなく {label}".
OVERVIEW_BANNER_NEAR_SECONDS = 3.0
# Px kept free at the top of the overview for the "next stop" banner.
OVERVIEW_TOP_CARD_CLEARANCE = 60
# Share of the frame height kept free at the bottom for the burned-in captions (up to two lines).
OVERVIEW_BOTTOM_CARD_CLEARANCE = 0.1
# Ending recap: every photo card fades in at once, over this long.
RECAP_GROUP_FADE_SECONDS = 0.4
# Recap leader-line/border colors, cycled around the ring so neighbouring cards differ (BGR, Tableau10-based,
# distinct from the route and pin colors).
RECAP_LINE_COLOR_PALETTE: List[Tuple[int, int, int]] = [
    (180, 119, 31),   # blue
    (189, 103, 148),  # purple
    (75, 86, 140),    # brown
    (194, 119, 227),  # pink
    (127, 127, 127),  # gray
    (34, 189, 188),   # olive
    (207, 190, 23),   # cyan
]
# A shown card's position is locked this long, so a newcomer can't push it to a new spot mid-display
# (other cards still avoid it).
POPUP_POSITION_LOCK_SECONDS = 2.0
# Longest a popup may wait for a free display slot before it is dropped (or its own duration, if longer).
POPUP_MIN_WAIT_SECONDS = 6.0
# Shortest time any popup card stays on screen, fades included (_make_baked_popup), so it can be read.
POPUP_MIN_DISPLAY_SECONDS = 2.0
# Each unconnected stop-by's card in the batch at the previous stop, per card. Below the 2 s floor on purpose:
# they are passed, not visited, and a long batch freeze pushes later cued stops late.
STOPBY_BATCH_SECONDS = 0.5
# A stop-by this close to a leg's line is walked to and pops up there; a farther one pops at the stop before it.
STOPBY_WALK_NEAR_METERS = 60.0
STOPBY_CAMERA_MOVE_SECONDS = 1.2  # a leg's camera flying out to a far stop-by, and back to the route after
# Stop-bys in one group that get a held card (the narration names at most 3); the rest get only their pin.
STOPBY_BATCH_MAX_HELD = 4
# An overview card stays fully shown (fades excluded) at least this long, even when the walker has moved on.
OVERVIEW_POPUP_MIN_HOLD_SECONDS = 2.0
# The overview walker stops this long at a "Connect to Route" stop-by (card showing); it has no cue of its own.
OVERVIEW_CONNECTED_STOPBY_HOLD_SECONDS = 2.0
# Overview map padding by route size: (span_km ceiling, padding) pairs, first that fits wins. The map is cut
# to exactly the padded box, so small routes need a tight crop to be followed.
OVERVIEW_PADDING_BY_SPAN_KM: Tuple[Tuple[float, float], ...] = (
    (1.5, 0.05),
    (5.0, 0.07),
    (15.0, 0.10),
    (40.0, 0.14),
)
# Padding above the largest span_km ceiling.
OVERVIEW_PADDING_MAX_SPAN = 0.18
# Overview: the walker takes at least this long from one numbered stop to the next, however close.
OVERVIEW_MIN_LEG_SECONDS = 2.0
# Overview: a reached pin grows from its tip with a slight overshoot over this long.
PIN_POP_SECONDS = 0.35
# Leg frames are JPEG screenshots (PNG encoding was the slowest part of each frame).
LEG_FRAME_JPEG_QUALITY = 92
# Beside-the-pin cards are tried this close around their pin first (directions, max leader px, extra px for
# the far side); only when nothing fits does the wider side-of-frame search run.
POPUP_NEAR_DIRECTIONS = 16
POPUP_NEAR_MAX_LEADER_PX = 200
POPUP_NEAR_OFF_SIDE_PX = 40
# The bottom-left notice explaining the round stop-by markers (wording in labels_<lang>.json).
STOPBY_NOTICE_TITLE = LABELS_JA["stopby_notice_title"]
# Line breaks are kept (a long line still wraps to the card).
STOPBY_NOTICE_BODY = LABELS_JA["stopby_notice_body"]
STOPBY_NOTICE_RIBBON_COLOR: Tuple[int, int, int] = (40, 110, 220)  # BGR, warm orange ribbon
STOPBY_NOTICE_FADE_SECONDS = 0.6
# A leg piece after a stop-by opens on its photo fullscreen, shrinks into its card above the marker, holds
# the card, then the walk resumes.
STOPBY_REOPEN_HOLD_SECONDS = 0.5
STOPBY_CARD_HOLD_SECONDS = 1.0
# How long the notice stays when the first stop-by isn't a batch (a batch keeps it for its own length).
STOPBY_NOTICE_SECONDS = 5.0
# Shortest time the notice is fully shown, fades excluded (a 0.5s batch was unreadable).
STOPBY_NOTICE_MIN_READ_SECONDS = 2.5
# Ceiling on a waypoint's freeze_seconds, applied where it is first read.
POPUP_FREEZE_SECONDS_MAX = 1.0
# How long a leg's arrival photo holds once fullscreen (it was already growing on screen; the clip cuts after).
RESIDENTIAL_ARRIVAL_POPUP_HOLD_SECONDS = 1.0
# A leg holds on the arrived map this long before the arrival photo pops in.
RESIDENTIAL_ARRIVAL_FREEZE_SECONDS = 1.0
# [NOTE] [Transition] Fullscreen photo transition plays as an ordered sequence: confirm (pin selected) -> scale (zoom into photo) -> blur -> fade_out; hold_ratio_of_freeze/min_hold_seconds/min_small_hold_seconds bound how long the fullscreen photo is held relative to its freeze duration before the next stage starts.
FULLSCREEN_TRANSITION_DEFAULTS: Dict[str, float] = {
    "confirm_seconds": 0.4,
    "scale_seconds": 2.5,
    "blur_seconds": 0.5,
    "fade_out_seconds": 0.5,
    "hold_ratio_of_freeze": 0.4,
    "min_hold_seconds": 0.5,
    "min_small_hold_seconds": 0.1,
}
# [NOTE] [Animation] Extra pixel padding added around a pin's hit/trigger radius (overview vs. per-waypoint map) so popups/highlights fire slightly before the cursor or route point is exactly on the pin.
TRIGGER_RADIUS_PADDING_DEFAULTS: Dict[str, float] = {"overview": 10, "waypoint": 15}

# --- ComfyUI attraction image-to-video (Wan2.2-TI2V-5B-Turbo-GGUF) ----------
# Bundled ComfyUI (bin/ComfyUI). Not the usual 8188, so it never collides with a developer's own ComfyUI.
COMFYUI_BASE_URL = "http://127.0.0.1:8189"
# "5b": Wan2.2-TI2V-5B-Turbo (below).
# "a14b": Wan2.2-I2V-A14B + Lightx2v 4-step LoRAs. Fills 32 GB of RAM, invented a cyclist, and the PC hit
#   HYPERVISOR_ERROR during its test (2026-10-01).
# "fun_camera": Wan2.1 Fun Camera 1.3B. Fits 8 GB but smears small text (kanji signs) at 480p.
COMFYUI_MODEL = "5b"
# Fun Camera files (Comfy-Org Wan 2.1 repackaged).
COMFYUI_FUN_CAMERA_UNET_NAME = "wan2.1_fun_camera_v1.1_1.3B_bf16.safetensors"
COMFYUI_CLIP_VISION_NAME = "clip_vision_h.safetensors"
# Editor preset -> WanCameraEmbedding camera_pose.
COMFYUI_FUN_CAMERA_POSES: Dict[str, str] = {
    "panright": "Pan Right",
    "panleft": "Pan Left",
    "panup": "Pan Up",
    "pandown": "Pan Down",
    "zoomin": "Zoom In",
    "zoomout": "Zoom Out",
    "walkin": "Zoom In",
    "none": "Static",
}
# How far the camera travels per segment (1.0 = the node's default).
COMFYUI_FUN_CAMERA_SPEED = 0.5
# A14B files; same exact-filename rule as COMFYUI_UNET_NAME. Q3_K_S (~6.5 GB) is the quant most likely to
# stay in VRAM; Q4_K_M (~9.7 GB) always offloads.
COMFYUI_A14B_HIGH_UNET_NAME = "Wan2.2-I2V-A14B-HighNoise-Q3_K_S.gguf"
COMFYUI_A14B_LOW_UNET_NAME = "Wan2.2-I2V-A14B-LowNoise-Q3_K_S.gguf"
COMFYUI_A14B_HIGH_LORA_NAME = "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors"
COMFYUI_A14B_LOW_LORA_NAME = "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors"
# The step the high-noise expert hands over to the low-noise one (ComfyUI's Wan 2.2 14B template).
COMFYUI_A14B_SPLIT_STEP = 2
# --reserve-vram (GB) for ComfyUI: load only what fits and stream the rest, instead of spilling into shared
# GPU memory.
COMFYUI_RESERVE_VRAM_GB: Optional[float] = None
# Must be the exact filename in bin/ComfyUI/models/diffusion_models: a wrong name silently turns every clip
# into the plain pan/zoom fallback.
COMFYUI_UNET_NAME = "Wan2_2-TI2V-5B-Turbo-Q4_K_M.gguf"
# Tiled VAE decode (px tiles, overlap, frames per chunk): a full-size decode doesn't fit in 8 GB beside Wan.
COMFYUI_VAE_TILE_SIZE = 512
COMFYUI_VAE_TILE_OVERLAP = 64
COMFYUI_VAE_TEMPORAL_SIZE = 32
# 16, not 8: at 8 each frame chunk decoded brighter; 16 blends that away for ~+0.5 GB (peak 7.2 GB).
COMFYUI_VAE_TEMPORAL_OVERLAP = 16
COMFYUI_CLIP_NAME = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
COMFYUI_VAE_NAME = "wan2.2_vae.safetensors"
# Fits an 8 GB card at this quant; upscaled to 1920x1080 afterwards.
COMFYUI_WIDTH = 1280
COMFYUI_HEIGHT = 704
# Share trimmed off each edge before Wan sees the photo: half-cut objects were "completed" into invented signs.
COMFYUI_INPUT_EDGE_CROP = 0.05
COMFYUI_FPS = 24
# Turbo settings from the model card (4 steps, euler/simple), but CFG 2: at CFG 1 the negative prompt is
# skipped and Wan adds vehicles, people and props. Above 1 each step costs ~+40 s per segment.
COMFYUI_STEPS = 4
COMFYUI_CFG = 2.0
COMFYUI_SAMPLER = "euler"
COMFYUI_SCHEDULER = "simple"
COMFYUI_MODEL_SHIFT = 8.0
# Wan frame counts are 4k+1. The maximum is kept short: longer clips crashed mid-sampling on 8 GB (VRAM).
# If crashes come back, lower the resolution, not the steps (Turbo is distilled for 4).
COMFYUI_MIN_FRAMES = 25  # ~1s @ 24fps
COMFYUI_MAX_FRAMES = 89  # ~3.7s @ 24fps (was 121 ~5s, then 65 ~2.7s — middle ground)
# The rate Wan generates at; a lower one is resampled up to COMFYUI_FPS.
COMFYUI_GEN_FPS = COMFYUI_FPS
if COMFYUI_MODEL == "a14b":
    # A14B uses the Wan 2.1 VAE (wan2.2_vae is the 5B's own).
    COMFYUI_VAE_NAME = "wan_2.1_vae.safetensors"
    # 480p is what fits next to an offloaded 14B expert on 8 GB; 848 keeps
    # the aspect near 16:9 for the upscale to 1920x1080.
    COMFYUI_WIDTH = 848
    COMFYUI_HEIGHT = 480
    COMFYUI_GEN_FPS = 16
    COMFYUI_MAX_FRAMES = 81  # ~5s @ 16fps
    COMFYUI_MODEL_SHIFT = 5.0
    # The Lightning LoRAs are distilled for CFG 1, which skips
    # COMFYUI_NEGATIVE_PROMPT (see COMFYUI_CFG) - watch for invented
    # people/vehicles.
    COMFYUI_CFG = 1.0
    COMFYUI_RESERVE_VRAM_GB = 1.0
elif COMFYUI_MODEL == "fun_camera":
    # From ComfyUI's "Wan2.1 Fun Camera 1.3B" template.
    COMFYUI_VAE_NAME = "wan_2.1_vae.safetensors"
    COMFYUI_WIDTH = 832
    COMFYUI_HEIGHT = 480
    COMFYUI_GEN_FPS = 16
    COMFYUI_MAX_FRAMES = 81  # ~5s @ 16fps
    COMFYUI_STEPS = 20
    COMFYUI_CFG = 6.0
    COMFYUI_SAMPLER = "uni_pc"
    COMFYUI_MODEL_SHIFT = 8.0
# A narration longer than one segment chains more segments, each started from the previous last frame
# (colour-matched back to the photo, so drift can't compound). At most 5 per photo (the user's choice, ~13 min
# GPU); the rest is filled by the tail below. None = no cap, 1 = no extension.
COMFYUI_EXTEND_MAX_SEGMENTS: Optional[int] = 5
if COMFYUI_MODEL == "a14b":
    # A14B segments are far slower; 2 (~10s of Wan) until it's benchmarked.
    COMFYUI_EXTEND_MAX_SEGMENTS = 2
# True: each segment is its own ComfyUI job from a PNG of the previous last frame (colour-matched first),
# joined with ffmpeg. False: the old single graph (faster, but drift carries through, one prompt).
COMFYUI_CHAIN_LAST_FRAME = True
# Colour-match a chained frame to the photo before the next segment starts from it (color_match.py).
COMFYUI_CHAIN_COLOR_MATCH = True
# Uncapped chain: it reaches the narration's end, so the tail is skipped. With a cap, a gap over 1 s is still
# filled by slow_move. False: slow_move fills any gap over 1 s.
ATTRACTION_CHAIN_TO_FULL_LENGTH = True
# A longer narration reuses the kept photo clips and fills the extra time on the CPU (the user's choice,
# 2026-10-08). True: generate again on the GPU.
ATTRACTION_REGENERATE_FOR_LONGER_NARRATION = False
# A finished clip whose narration changed by more than this is refitted from its kept photo clips.
ATTRACTION_REFIT_SLACK_SECONDS = 0.2
# An attraction clip runs this long past its narration, so the voice doesn't stop on the cut.
ATTRACTION_NARRATION_TAIL_SECONDS = 1.0
# "drift" tail: the frame grows by about this fraction per second (randomised +/-25% per clip).
ATTRACTION_SLOW_MOVE_ZOOM_PER_SEC = 0.012
# How time left after the animation is filled (only when the chain is capped short of the narration):
# "zoomout" eases back out to the full picture; "drift" a slow random push-in; "photo" dissolves to the
# photo and holds (the user's pick, 2026-10-30: no clip played backwards); "reverse" plays the animation back and forth.
ATTRACTION_SLOW_MOVE_STYLE = "photo"
ATTRACTION_SLOW_MOVE_MAX_ZOOM_OUT = 0.12
# The dissolve into that photo; 0 = a hard cut.
ATTRACTION_TAIL_PHOTO_FADE_SECONDS = 0.5
# Wan grades its clips, so each Wan clip's colours are pulled back to its photo (color_match.py): per-frame
# LAB mean and spread at this strength, averaged over SMOOTH_SECONDS so it can't flicker.
ATTRACTION_COLOR_MATCH = True
ATTRACTION_COLOR_MATCH_STRENGTH = 1.0
# 0.25 s: a 1 s window couldn't follow Wan's exposure ramp or the VAE chunk steps (a brightness wave).
ATTRACTION_COLOR_MATCH_SMOOTH_SECONDS = 0.25
# Wan2.2's standard negative prompt plus: duplicated/invented objects, people, foreground objects and hands
# (a gadget rose from the bottom edge), new shadows, colour grading, warped text and signs, CG looks, body
# parts (walk-ins invite feet). Only ONE of Wan's anti-static terms: without it the 5B barely moved, with all
# four it orbited wildly (2026-10-02).
COMFYUI_NEGATIVE_PROMPT = (
    "静止不动的画面, 环绕镜头, 镜头横移, 镜头旋转, 大幅度运动, "
    "新出现的招牌, 新出现的文字, 旗帜变形, 字幕, 水印, "
    "脚, 脚趾, 腿, 鞋, 手指, 手臂, 身体部位, 第一人称视角, "
    # objects moving on their own (a vending machine slid and turned to camera)
    "物体移动, 物体自行移动, 物体滑动, 物体旋转, 物体漂移, "
    # 1. Core Exclusions: People, vehicles, and unnecessary props are strictly prohibited 
    "人, 人物, 行人, 游客, 人影, 摩托车, 自行车, 汽车, 车辆, 交通工具, 机器设备, 头盔, "
    "手, 拿相机的手, 摄像机, 拍摄设备, 凭空出现的道具, 随机生成的杂物, 漂浮的物体, "
    "前景物体, 前景遮挡物, 从边缘进入画面的物体, 幻觉生成的物体, 非纯风景, "
    
    # 2. Stable shots and camera movement
    "场景突变, 结构突变, 建筑变形, 透视错误, 镜头扭曲, 快速运动, 镜头晃动, 不自然的运动, "
    "重复的物体, 重复的建筑, 复制粘贴的元素, 镜像重复, 物体凭空出现, 物体相互融合, "
    
    # 3. Lighting and Image Quality Control
    "曝光过度, 欠曝, 死白, 死黑, 频闪, 忽明忽暗, 曝光不稳定, 闪烁的光线, 光源跳动, "
    "刺目的对比, 违背物理的光线, 异常反光, 调色, 滤镜, 饱和度过高, 色偏, 整体发灰, "
    "自动曝光, 曝光渐变, 画面逐渐变亮, 画面逐渐变暗, 天空过曝, HDR效果, "
    
    # 4. Fundamental Flaws and Style
    "文字扭曲, 乱码文字, 标志变形, 路标扭曲, 细节模糊不清, JPEG压缩残留, 最差质量, 低质量, "
    "卡通, 动漫, CG渲染, 3D渲染感, 塑料质感, 绘画感, 画面闪烁"
)
# Motion-first prompts: the photo decides the look, the prompt only says how the camera moves. Unwanted things
# live in the negative prompt (T5 ignores "no"); no "fixed"/"locked" (read as don't move); constant speed
# (chained segments would stutter at each seam).
_COMFYUI_AMBIENT = (
    "Very gentle, subtle natural ambient motion in whatever the photo already shows; the light stays as it is."
)
_COMFYUI_LOOK = (
    "Smooth, steady cinematic camera move at a slow constant speed. Photorealistic travel documentary "
    "footage, the photo's own light, true-to-photo colors, crisp detail."
)
# Said as a positive fact: Wan animated a vending machine (slid, turned to camera).
_COMFYUI_RIGID = (
    "Only the camera moves; everything in the scene stays fixed in place, rooted where it stands."
)


def _motion_prompt(camera: str) -> str:
    return f"{camera} {_COMFYUI_RIGID} {_COMFYUI_AMBIENT} {_COMFYUI_LOOK}"


# Keys: the editor's presets normalised (camera_pan.py). "none" never reaches Wan (a still photo).
COMFYUI_CAMERA_PAN_PROMPTS: Dict[str, str] = {
    # No "revealing more ...": that invites Wan to invent what comes into view.
    "panright": _motion_prompt(
        "The camera pans gently to the right, a small, subtle, level move."
    ),
    "panleft": _motion_prompt(
        "The camera pans gently to the left, a small, subtle, level move."
    ),
    "panup": _motion_prompt(
        "The camera tilts gently upward, a small, subtle move."
    ),
    "pandown": _motion_prompt(
        "The camera tilts gently downward, a small, subtle move."
    ),
    "zoomin": _motion_prompt(
        "The camera pushes in gently, straight ahead and centered, a small, subtle move toward the main subject."
    ),
    "zoomout": _motion_prompt(
        "The camera pulls back gently, straight back and centered, a small, subtle move."
    ),
    "none": f"Static camera. {_COMFYUI_AMBIENT} Photorealistic travel documentary footage, the photo's own light, "
    "true-to-photo colors, crisp detail.",
    # Extra shots (ATTRACTION_SHOT_MOVES), not editor presets.
    "walkin": _motion_prompt(
        "Smooth steadicam shot gliding slowly forward at eye level toward the main subject, a small, subtle move."
    ),
    "dollyback": _motion_prompt(
        "The camera pulls straight back slowly, centered, a small, subtle move."
    ),
    # Walking pans: a gimbal carried forward at eye height while turning -
    # "gimbal", not "first-person", which invites the walker's feet and hands.
    "walkpanright": _motion_prompt(
        "Smooth gimbal shot carried forward at a slow walking pace at eye height, gently turning to the right "
        "as it moves through the scene, with a very subtle natural walking sway."
    ),
    "walkpanleft": _motion_prompt(
        "Smooth gimbal shot carried forward at a slow walking pace at eye height, gently turning to the left "
        "as it moves through the scene, with a very subtle natural walking sway."
    ),
}
COMFYUI_DEFAULT_MOTION_PROMPT = COMFYUI_CAMERA_PAN_PROMPTS["none"]

# --- LTXV-13B keyframed moves (vdoprocessing/ltx_keyframed.py) ---------------
# Presets made by LTXV-13B 0.9.8 distilled (Q3_K_M) between two real crops of the photo (first and last frame
# pinned, so it can't wander). Dolly In/Out: "ltxv" (the user's choice, 2026-10-07), "dolly" = 3D-photo dolly
# on the CPU, "jumpcut" = jump_cut.py (its AI wide invented objects).
ATTRACTION_ZOOM_STYLE = "ltxv"
_ZOOM_PRESETS: Tuple[str, ...] = ("zoomin", "zoomout")
ATTRACTION_LTX_PRESETS: Tuple[str, ...] = ("panright", "panleft", "panup", "pandown", "walkin", "walkback") + (
    _ZOOM_PRESETS if ATTRACTION_ZOOM_STYLE == "ltxv" else ()
)
# Jump cut: wide, then a hard cut to a centred punch-in of JUMP_CUT_TIGHT of the frame at JUMP_CUT_AT.
ATTRACTION_JUMP_CUT_PRESETS: Tuple[str, ...] = () if ATTRACTION_ZOOM_STYLE == "ltxv" else _ZOOM_PRESETS
ATTRACTION_JUMP_CUT_TIGHT = 0.65
ATTRACTION_JUMP_CUT_AT = 0.5
# AI wide shot (jump cut, "walkai"): the photo in the middle, the ring around it outpainted by SDXL (GPU).
# False or a failed outpaint = a crop of the photo.
ATTRACTION_AI_SURROUNDINGS = True
ATTRACTION_JUMP_CUT_AI_SIZE = (1344, 768)
ATTRACTION_JUMP_CUT_AI_STRENGTH = 0.9
ATTRACTION_JUMP_CUT_AI_FEATHER = 16
# A second, closer shot of the same photo after the chosen move, joined by a dissolve. "auto": picked from
# ATTRACTION_SECOND_SHOT_MOVES by what the photo shows (depth + saliency, CPU); "random": seeded per photo;
# a move name fixes it; None = the chosen move only.
ATTRACTION_SECOND_SHOT: Optional[str] = "auto"
# One ~8 s move rendered as two halves. Off (2026-10-23): the halves never met cleanly; LTXV_FRAMES = 161
# renders the move in one pass.
LTXV_CONTINUE = False
# A two-half clip travels this many times the single clip's path. Dollies stop at DEPTH_MAX_DOLLY (the 3D
# photo stretches past it).
LTXV_HALVES_TRAVEL = 1.8
LTXV_DEPTH_MAX_DOLLY = 0.6
# Frames dissolved where the halves meet.
LTXV_JOIN_FADE_FRAMES = 6
# No walkthrough: unpinned, it invented a whole plaza (2026-10-06).
ATTRACTION_SECOND_SHOT_MOVES: Tuple[str, ...] = (
    "closein", "closeout", "closepanleft", "closepanright", "closepanup", "closepandown",
)
# The second shot is skipped when its crop spans fewer original-photo pixels than this (<=352 px smeared).
ATTRACTION_SECOND_SHOT_MIN_SOURCE_PX = 400
# Moves with no pinned last frame: LTXV walks into the place from the whole photo (it may show what the
# photo doesn't). "walkai" starts from the AI wide shot instead.
LTXV_FREE_MOVES: Tuple[str, ...] = ("walkthrough", "walkthroughleft", "walkthroughright", "walkin", "walkai")
# A free move chosen in the editor is rendered as this pinned move instead. None = the free POV walk the
# user wants (test23).
LTXV_FREE_MOVE_FALLBACK: Optional[str] = None
# The pinned walk becomes this when its tight crop is too small (ATTRACTION_SECOND_SHOT_MIN_SOURCE_PX):
# "walkai" = from the AI wide shot into the photo, "walkshort" = zoomin's crops with the walking prompt.
LTXV_SMALL_PHOTO_WALK_FALLBACK = "walkai"
# "walkai": "parallax" = a 3D-photo POV walk over the AI wide shot (CPU); "ltxv" only tilted and drifted.
WALKAI_STYLE = "parallax"
LTXV_CROSSFADE_SECONDS = 0.5
# Files (downloaded on first use into bin/ComfyUI/models/<folder>, sha256-checked).
LTXV_FILES: Dict[str, Dict[str, str]] = {
    "unet": {
        "folder": "unet", "file": "LTXV-13B-0.9.8-distilled-Q3_K_M.gguf",
        "url": "https://huggingface.co/QuantStack/LTXV-13B-0.9.8-distilled-GGUF/resolve/main/LTXV-13B-0.9.8-distilled-Q3_K_M.gguf",
        "sha256": "1301695484240e3423df052825eabb836302e43b68fc04111cc25076f5c64b24",
    },
    "vae": {
        "folder": "vae", "file": "LTXV-13B-0.9.8-distilled-VAE.safetensors",
        "url": "https://huggingface.co/QuantStack/LTXV-13B-0.9.8-distilled-GGUF/resolve/main/vae/LTXV-13B-0.9.8-distilled-VAE.safetensors",
        "sha256": "5bbe6f857ede5e9b262e4a294c26a1df5dc33a817f229a777cbf3adfab5ba61e",
    },
    "text_encoder": {
        "folder": "text_encoders", "file": "t5xxl_fp8_e4m3fn_scaled.safetensors",
        "url": "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp8_e4m3fn_scaled.safetensors",
        "sha256": "a498f0485dc9536735258018417c3fd7758dc3bccc0a645feaa472b34955557a",
    },
}
LTXV_WIDTH, LTXV_HEIGHT = 960, 544  # 540p 16:9 (32 px grid); finalize upscales
LTXV_FRAMES = 161  # 8k+1, ~6.7 s in one pass (no seam); was 97 (~4 s)
LTXV_FPS = 24
LTXV_SIGMAS = "1.0, 0.9937, 0.9875, 0.9812, 0.975, 0.9094, 0.725, 0.4219, 0.0"  # distilled, CFG 1
# Decode the whole clip as one time chunk: chunk seams left visible hitches.
LTXV_DECODE_TEMPORAL_SIZE = 168  # >= LTXV_FRAMES: the whole clip in one tile (128 left a hitch at frame 120 of 161)
LTXV_DECODE_TEMPORAL_OVERLAP = 8
# How firmly the last frame is pinned (1.0 = exact copy).
LTXV_GUIDE_STRENGTH = 0.8
# Keyframe crops, as shares of the widest 16:9 window: pans slide CROP_WIDTH edge to edge, zooms go
# ZOOM_WIDE -> ZOOM_TIGHT, the second shot CLOSE_WIDE -> CLOSE_TIGHT, all around the middle.
LTXV_CROP_WIDTH = 0.85
LTXV_ZOOM_WIDE = 1.0
LTXV_ZOOM_TIGHT = 0.8
LTXV_CLOSE_WIDE = 0.55
LTXV_CLOSE_TIGHT = 0.46
# Close pans move a CLOSE_WIDE window this share of the widest window across the middle.
LTXV_CLOSE_PAN = 0.18
# Walk-in second shots: CLOSE_WIDE -> WALK_TIGHT, ending WALK_TURN sideways for walkfwdleft/right.
LTXV_WALK_TIGHT = 0.38
LTXV_WALK_TURN = 0.12
# The pinned walk ends framed on the photo's largest sign (OCR) instead of the middle.
LTXV_WALK_TO_SIGN = True
# Moves pinned to 3D-photo views (parallax_generator) instead of flat crops, which LTXV turned into a flat
# slide. Pans step DEPTH_TRUCK sideways while turning DEPTH_PAN; dollies travel DEPTH_DOLLY.
LTXV_DEPTH_KEYFRAMES: Tuple[str, ...] = ("panleft", "panright", "zoomin", "zoomout")
# Walk In softly pinned to a 3D view ahead, if added to LTXV_DEPTH_KEYFRAMES. Off: LTXV held still, then
# jumped to the anchor.
LTXV_WALK_ANCHOR_DOLLY = 0.5
LTXV_WALK_ANCHOR_STRENGTH = 0.5
LTXV_DEPTH_TRUCK = 0.10
LTXV_DEPTH_PAN = 0.06
LTXV_DEPTH_DOLLY = 0.30
# Evenly spaced 3D views pinned in between: with only the ends pinned the pan finished halfway and stood still.
LTXV_DEPTH_MID_GUIDES = 2
LTXV_MID_GUIDE_STRENGTH = 0.6
# An LTXV job needs ~15 GB of free RAM: below it, wait (ensure_free_ram), then fall back to the 3D photo.
LTXV_MIN_FREE_RAM_GB = 15.0
# Each attraction photo is made in its own child process (clip_worker.py), so its memory goes back to Windows.
ATTRACTION_CLIP_IN_CHILD = True
# How long a shot waits for that RAM (the server stopped first) before giving up.
LTXV_RAM_WAIT_SECONDS = 900.0
# Attempts at an LTXV clip (fresh server each) before the CPU 3D photo.
LTXV_CLIP_ATTEMPTS = 2
# CFG 1: the negative is ignored, so everything is said positively.
_LTXV_STILL = (
    "The scene is still and solid and only the camera moves, steadily and slowly. The light, weather and colours stay "
    "exactly as in the photo; realistic travel documentary footage, sharp detail."
)
# "Gimbal carried", never "first-person" (invites the walker's feet and hands).
_LTXV_WALK_END = (
    " The place is quiet and empty of people; the scene is still and solid and only the camera moves, with a "
    "very subtle natural walking sway. The light, weather and colours stay exactly as in the photo; realistic "
    "travel documentary footage, sharp detail."
)
# CFG 1 ignores the negative, so the empty, unobstructed view is said positively.
_LTXV_POV_END = (
    " The view bobs gently up and down with each footstep, like the eyes of someone walking in. The place is "
    "completely deserted and still; the view is clean and unobstructed, only the place itself fills the "
    "frame. The light, weather and colours stay exactly as in the photo; realistic travel documentary "
    "footage, sharp detail."
)
LTXV_PROMPTS: Dict[str, str] = {
    # Walk-and-pan: the camera travels the way it turns.
    "panright": (
        "A smooth gimbal shot carried at eye height moves at a slow walking pace to the right past {place}, "
        "travelling sideways while the view pans to the right with it. Nearby things slide past faster than "
        "the distant background. The camera stays level." + _LTXV_WALK_END
    ),
    "panleft": (
        "A smooth gimbal shot carried at eye height moves at a slow walking pace to the left past {place}, "
        "travelling sideways while the view pans to the left with it. Nearby things slide past faster than "
        "the distant background. The camera stays level." + _LTXV_WALK_END
    ),
    "panup": (
        "A slow, calm gimbal shot tilts smoothly upward across {place}. " + _LTXV_STILL
    ),
    "pandown": (
        "A slow, calm gimbal shot tilts smoothly downward across {place}. "
        + _LTXV_STILL
    ),
    # Dolly, not a lens zoom: the camera itself travels, so depth shifts.
    "zoomin": (
        "A slow, smooth dolly shot: the camera on a track glides straight forward at eye height toward the "
        "middle of {place}. Nearby things grow and move outward faster than the "
        "background, and the perspective shifts with the camera's travel. The camera stays perfectly level. "
        + _LTXV_STILL
    ),
    "zoomout": (
        "A slow, smooth dolly shot: the camera on a track glides straight backward at eye height away from the "
        "middle of {place}, revealing more of it. Nearby things shrink and move "
        "inward faster than the background, and the perspective shifts with the camera's travel. The camera "
        "stays perfectly level. " + _LTXV_STILL
    ),
    "closein": (
        "A slow, calm close-up gimbal shot pushes gently in toward the main subject of {place}, moving "
        "straight ahead at eye height. The camera stays perfectly level. " + _LTXV_STILL
    ),
    "closeout": (
        "A slow, calm close-up gimbal shot pulls gently back from the main subject of {place}, moving "
        "straight back at eye height. The camera stays perfectly level. " + _LTXV_STILL
    ),
    "closepanleft": (
        "A slow, calm close-up gimbal shot pans smoothly to the left across the main subject of {place}. "
        "The camera stays perfectly level. " + _LTXV_STILL
    ),
    "closepanright": (
        "A slow, calm close-up gimbal shot pans smoothly to the right across the main subject of {place}. "
        "The camera stays perfectly level. " + _LTXV_STILL
    ),
    "closepanup": (
        "A slow, calm close-up gimbal shot tilts smoothly upward across the main subject of {place}. " + _LTXV_STILL
    ),
    "closepandown": (
        "A slow, calm close-up gimbal shot tilts smoothly downward across the main subject of {place}. " + _LTXV_STILL
    ),
    # Camera-only words: "walks" drew a person into frame.
    "walkthrough": (
        "Point-of-view camera at eye height moving continuously straight forward into {place}, steadily "
        "ahead, getting closer and closer to what lies in front." + _LTXV_POV_END
    ),
    "walkthroughleft": (
        "Point-of-view camera at eye height moving continuously straight forward into {place}, steadily "
        "ahead, getting closer and closer, then slowly turning its view to the left." + _LTXV_POV_END
    ),
    "walkthroughright": (
        "Point-of-view camera at eye height moving continuously straight forward into {place}, steadily "
        "ahead, getting closer and closer, then slowly turning its view to the right." + _LTXV_POV_END
    ),
    "walkfwd": (
        "A smooth gimbal shot carried at eye height walks slowly forward into {place}. The camera stays "
        "perfectly level. " + _LTXV_STILL
    ),
    "walkfwdleft": (
        "A smooth gimbal shot carried at eye height walks slowly forward into {place}, turning gently to the "
        "left. " + _LTXV_STILL
    ),
    "walkfwdright": (
        "A smooth gimbal shot carried at eye height walks slowly forward into {place}, turning gently to the "
        "right. " + _LTXV_STILL
    ),
}
# No "toward the entrance ... passes inside": it invented a building in a forest.
LTXV_PROMPTS["walkin"] = (
    "Point-of-view camera at eye height moving continuously straight forward through {place}, "
    "steadily ahead along the way in front, getting closer and closer to what lies ahead." + _LTXV_POV_END
)
# The free walk plays up to this many times slower (motion-interpolated), only as much as its narration needs.
LTXV_WALK_SLOWDOWN = 1.6
# A free walk is cut where it leaves the photo (clip_qc.scene_lost_frame: too few epipolar inliers). Under
# MIN_SECONDS kept: rendered again with a new seed, up to ATTEMPTS times.
LTXV_WALK_QC_MIN_INLIERS = 10
LTXV_WALK_QC_MIN_SHARE = 0.03
# ... or where over this share of the frame lies past the photo's edge on two checks running.
LTXV_WALK_QC_MAX_OUTSIDE = 0.20
# ... and a walk that pushes forward less than this (%) is rendered again (unpinned LTXV may stand still).
LTXV_WALK_MIN_PUSH = 20.0
LTXV_WALK_MIN_SECONDS = 2.0
LTXV_WALK_ATTEMPTS = 2
# After every attempt fails: this LTXV move instead (the user wants every picture made by LTX).
LTXV_WALK_FAILED_FALLBACK = "zoomin"
LTXV_PROMPTS["walkshort"] = LTXV_PROMPTS["walkfwd"]
# "walkback" has no recipe: it is "walkin" played backwards, ending on the real photo.
# "walkai" walks from the AI wide shot (the gentle walkfwd wording only drifted).
LTXV_PROMPTS["walkai"] = (
    "Point-of-view camera at eye height moving continuously straight forward through {place}, "
    "walking steadily ahead and getting closer and closer to what lies in front." + _LTXV_POV_END
)
# Second shot as a walk inside the place: "walk" = from LTXV_WALK_PROMPTS; None = LTXV_PROMPTS (the walk
# prompts zoomed during pans and added a visitor).
ATTRACTION_SECOND_SHOT_STYLE: Optional[str] = None
LTXV_WALK_PROMPTS: Dict[str, Tuple[str, ...]] = {
    "walkfwd": (
        "A smooth gimbal shot carried at eye height walks slowly forward into {place}, several unhurried steps "
        "drawing closer to its main subject." + _LTXV_WALK_END,
        "A calm walking shot at eye height strolls slowly deeper into {place}, as if a visitor has just "
        "arrived and is walking up to the heart of it." + _LTXV_WALK_END,
    ),
    "walkfwdleft": (
        "A smooth gimbal shot carried at eye height walks slowly forward into {place} while turning gently to "
        "the left to look around." + _LTXV_WALK_END,
        "A calm walking shot at eye height strolls slowly deeper into {place}, the gaze drifting to the left "
        "as it goes." + _LTXV_WALK_END,
    ),
    "walkfwdright": (
        "A smooth gimbal shot carried at eye height walks slowly forward into {place} while turning gently to "
        "the right to look around." + _LTXV_WALK_END,
        "A calm walking shot at eye height strolls slowly deeper into {place}, the gaze drifting to the right "
        "as it goes." + _LTXV_WALK_END,
    ),
    "closein": (
        "A smooth gimbal shot carried at eye height walks slowly forward through {place}, drawing closer to its "
        "main subject step by step." + _LTXV_WALK_END,
        "A calm walking shot at eye height moves slowly deeper into {place}, as if a visitor has just arrived "
        "and is strolling toward the heart of it." + _LTXV_WALK_END,
    ),
    "closeout": (
        "A smooth gimbal shot carried at eye height walks slowly backward through {place}, the view opening up "
        "around the main subject." + _LTXV_WALK_END,
        "A calm walking shot at eye height eases slowly back through {place}, taking in more of it with each "
        "step." + _LTXV_WALK_END,
    ),
    "closepanleft": (
        "A smooth gimbal shot carried at eye height strolls slowly through {place} while turning gently to the "
        "left to look around." + _LTXV_WALK_END,
        "A calm walking shot at eye height wanders slowly through {place}, the gaze drifting to the left across "
        "the main subject." + _LTXV_WALK_END,
    ),
    "closepanright": (
        "A smooth gimbal shot carried at eye height strolls slowly through {place} while turning gently to the "
        "right to look around." + _LTXV_WALK_END,
        "A calm walking shot at eye height wanders slowly through {place}, the gaze drifting to the right across "
        "the main subject." + _LTXV_WALK_END,
    ),
    "closepanup": (
        "A smooth gimbal shot carried at eye height walks slowly through {place} and looks gently upward, "
        "taking in its height." + _LTXV_WALK_END,
        "A calm walking shot at eye height stops beneath the main subject of {place} and tilts slowly up to "
        "admire it." + _LTXV_WALK_END,
    ),
    "closepandown": (
        "A smooth gimbal shot carried at eye height walks slowly through {place} and looks gently downward "
        "across the main subject." + _LTXV_WALK_END,
        "A calm walking shot at eye height moves slowly through {place}, the view tilting gently down over "
        "its details." + _LTXV_WALK_END,
    ),
}
# --- Sign lock (vdoprocessing/sign_lock.py) ---------------------------------
# Video models redraw kanji as kanji-like shapes, so the photo's own sign pixels are tracked into every LTXV
# frame and pasted back.
SIGN_LOCK = True
SIGN_LOCK_MIN_TEXT_PX = 12  # text lines shorter than this (photo px) are left alone
SIGN_LOCK_MAX_SIGNS = 6  # largest signs per photo (each costs ~10 s of CPU per clip)
SIGN_LOCK_PAD = 0.35  # padding around each text line, in line heights
SIGN_LOCK_CONTEXT = 1.5  # SIFT area around the sign, in sign sizes each side
SIGN_LOCK_MIN_INLIERS = 15
SIGN_LOCK_FOLLOW_MIN_POINTS = 6  # frame-to-frame fallback once the photo match fails
SIGN_LOCK_MIN_CORR = 0.6  # ECC fit of the photo's sign to the frame, else no paste
SIGN_LOCK_FADE_FRAMES = 6  # paste fades in/out where tracking starts or stops
SIGN_LOCK_MIN_SCALE, SIGN_LOCK_MAX_SCALE = 0.1, 8.0  # sanity bounds on the tracked size
SIGN_LOCK_MAX_GAP = 4  # untracked frames bridged between tracked ones
SIGN_LOCK_SMOOTH = 2  # corner averaging radius, frames
SIGN_LOCK_FEATHER = 0.12  # soft edge, share of the padded box's short side
SIGN_LOCK_COLOR_STRENGTH = 0.8

LTXV_NEGATIVE = "low quality, worst quality, deformed, distorted, motion smear, motion artifacts, morphing, people, hands, feet"

# --- Attraction clips: multi-shot + QC + parallax fill ------------------------
# "shots": Wan shots from the photo, each cut where QC finds it going bad, then a parallax move for the rest.
# "parallax": the parallax move only (no GPU). "chain": the old last-frame chained Wan segments.
ATTRACTION_GENERATOR = "shots"
# Moves for shots 1..N, each from the original photo; "preset" = the editor's.
ATTRACTION_SHOT_MOVES: List[str] = ["preset", "walkin", "dollyback"]
ATTRACTION_MAX_WAN_SHOTS = 3
# A shot with less clean footage than this is dropped.
ATTRACTION_MIN_SHOT_SECONDS = 1.0
# Before each hard cut the last this-many seconds ease to a stop, then the frame holds briefly.
ATTRACTION_SHOT_SETTLE_SECONDS = 0.5
ATTRACTION_SHOT_HOLD_SECONDS = 0.25
# Cut this many frames before the first bad one (QC lags the eye slightly).
ATTRACTION_QC_BACKOFF_FRAMES = 3
# QC (clip_qc.py): 32 px patches looked up in the photo where the camera model puts them. Calibrated on clips
# where a cut-off banner grew into an invented sign (3-4 bad patches) vs clean moves (0).
ATTRACTION_QC_MAX_BAD_FRACTION = 0.12
ATTRACTION_QC_MAX_BAD_CLUSTER = 3
# Share of the frame showing what's outside the photo (invented); pans and pull-backs get the looser cap.
ATTRACTION_QC_MAX_OUTSIDE = 0.15
ATTRACTION_QC_MAX_OUTSIDE_REVEAL = 0.35
# 3D photo (parallax_generator.py): Depth-Anything-V2 Small on the CPU, the photo split into depth LAYERS.
# The nearest things get the full motion, the farthest FAR_WEIGHT of it. Pans truck PAN (+ a PAN_PUSH dolly),
# zooms dolly ZOOM with an ARC sideways drift.
PARALLAX_DEPTH_MODEL = "depth-anything/Depth-Anything-V2-Small-hf"
PARALLAX_DEVICE = "cpu"
# What a moving foreground uncovers is filled by LaMa (CPU, ~5 s a photo, downloaded on first use);
# without it OpenCV's Telea fill smears.
PARALLAX_LAMA = {
    "file": "big-lama.pt",
    "url": "https://github.com/enesmsahin/simple-lama-inpainting/releases/download/v0.1.0/big-lama.pt",
    "sha256": "7ba7aa7ac37a4d41fdbbeba3a2af7ead18058552997e3a3cd1a3b2210c9e6b4c",
}
PARALLAX_LAMA_MAX_SIDE = 1824
# 2 layers split at the foreground/background break: 3 tore a pole between layers.
PARALLAX_LAYERS = 2
PARALLAX_PAN = 0.08
PARALLAX_PAN_PUSH = 0.04
PARALLAX_ZOOM = 0.16
PARALLAX_ARC = 0.015
# POV walk: dolly forward (extra scale for the nearest things), step dip and sway (shares of the frame), head
# roll in degrees.
PARALLAX_WALK_DOLLY = 0.6
PARALLAX_WALK_STEPS_PER_SEC = 1.8
PARALLAX_WALK_BOB = 0.008
PARALLAX_WALK_SWAY = 0.006
PARALLAX_WALK_ROLL_DEG = 0.5
PARALLAX_FAR_WEIGHT = 0.3
# Film finish: motion-blur sub-frames, focus-pull blur (px sigma; 0 = off, it left the subject soft),
# vignette, grain (0-255 std).
PARALLAX_MOTION_BLUR_SAMPLES = 2
PARALLAX_DOF_SIGMA = 0.0
PARALLAX_VIGNETTE = 0.18
PARALLAX_GRAIN = 2.5
# The bundled ComfyUI is stopped after this long unused (idle_watchdog.py).
COMFYUI_IDLE_TIMEOUT_SECONDS = 600.0
# Generous: a cold start pays for node imports, and a long generation took up to ~15 min.
COMFYUI_SERVER_START_TIMEOUT_SECONDS = 180.0
COMFYUI_GENERATION_TIMEOUT_SECONDS = 1200.0

# --- Waypoint photo upscale (pipeline stage before attraction videos) -------
# Photos smaller than MIN_W x MIN_H get an ESRGAN pass in ComfyUI, so fullscreen photos and Wan's input aren't
# soft. settings.upscale_popup_images=false turns it off; never under skip_rich_media.
DEFAULT_UPSCALE_POPUP_IMAGES = True
# A key of IMAGE_UPSCALE_MODELS, under that filename in bin/ComfyUI/models/upscale_models (downloaded on first
# use; without it the stage resizes on the CPU). UltraMix Balanced won over UltraSharp on a real web photo.
IMAGE_UPSCALE_MODEL = "4x-UltraMix_Balanced.pth"
IMAGE_UPSCALE_MODELS = {
    "4x-UltraSharp.pth": {
        "url": "https://huggingface.co/Kim2091/UltraSharp/resolve/920fe218c211f831b43cb30327f203e2b59f5dab/4x-UltraSharp.pth",
        "sha256": "a5812231fc936b42af08a5edba784195495d303d5b3248c24489ef0c4021fe01",
        "scale": 4,
    },
    "4x-UltraMix_Balanced.pth": {
        "url": "https://huggingface.co/Kim2091/UltraSharp/resolve/920fe218c211f831b43cb30327f203e2b59f5dab/Interpolations/4x-UltraMix_Balanced.pth",
        "sha256": "e23ca000107aae95ec9b8d7d1bf150f7884f1361cd9d669bdf824d72529f0e26",
        "scale": 4,
    },
}
# The model's 4x output is shrunk to this scale before the final fit: keeps the sharpening, drops invented
# detail. None = full scale.
IMAGE_UPSCALE_KEEP_SCALE = 2
IMAGE_UPSCALE_DOWNLOAD_TIMEOUT_SECONDS = 600.0
IMAGE_UPSCALE_MIN_W = 1920
IMAGE_UPSCALE_MIN_H = 1080
# Input is shrunk to MAX_SIDE / scale first (bounds tiles, time and RAM).
IMAGE_UPSCALE_MAX_SIDE = 3840
# A 4x model needs ~4.8 GB of VRAM; below this much free the photo is resized on the CPU instead.
IMAGE_UPSCALE_MIN_FREE_VRAM_MB = 5500
IMAGE_UPSCALE_TIMEOUT_SECONDS = 300.0
# "Sharpen photos" also sharpens a photo big enough to skip the upscale (photo_sharpen.py): shrunk to this
# long side, then an unsharp mask of this radius / strength.
PHOTO_SHARPEN_MAX_SIDE = 1920
PHOTO_SHARPEN_RADIUS = 1.2
PHOTO_SHARPEN_PERCENT = 80

# --- Intro clip (multi-image slideshow + centered project title) -----------
# Slideshow of INTRO_IMAGE_COUNT random waypoint photos, each slowly zooming, crossfaded (introclip.py).
INTRO_IMAGE_COUNT = 3
# Each photo's time including its crossfades: total = COUNT*PER_IMAGE - (COUNT-1)*CROSSFADE.
INTRO_PER_IMAGE_SECONDS = 3.5
INTRO_CROSSFADE_SECONDS = 0.8
# The overview narration starts on the intro (settings.overview_voice_over_intro): its opening (up to
# {start}) plays over the photos, the intro lasting the fade from black + that, within MIN..MAX.
DEFAULT_OVERVIEW_VOICE_OVER_INTRO = True
INTRO_VOICE_LEAD_SECONDS = 0.5
# The intro ends this long before the voice reaches {start}, so the map is already up when that line starts.
INTRO_MAP_LEAD_SECONDS = 1.2
# With the opening as its own file, the intro runs this long past its last word.
INTRO_VOICE_TAIL_SECONDS = 0.4
INTRO_MIN_SECONDS = 4.0
INTRO_MAX_SECONDS = 26.0
INTRO_MAX_IMAGE_COUNT = 5
# Intro text defaults, in intro px; settings.intro_title_style / intro_subtitle_style override.
INTRO_TITLE_FONT_FAMILY = "Yu Gothic UI"
INTRO_TITLE_FONT_SIZE = 150
INTRO_TITLE_OUTLINE = 2
INTRO_TITLE_BOLD = True
INTRO_TITLE_COLOR: Tuple[int, int, int] = (255, 255, 255)
# Second line under the title (only drawn when a subtitle is set).
INTRO_SUBTITLE_FONT_FAMILY = "Yu Gothic UI"
INTRO_SUBTITLE_FONT_SIZE = 70
INTRO_SUBTITLE_OUTLINE = 0
INTRO_SUBTITLE_BOLD = True
INTRO_SUBTITLE_COLOR: Tuple[int, int, int] = (255, 255, 255)
# Small line above the title: where the walk is (settings.intro_location, e.g. "和歌山県 和歌山市").
INTRO_KICKER_FONT_FAMILY = "Yu Gothic UI"
INTRO_KICKER_FONT_SIZE = 90
INTRO_KICKER_OUTLINE = 0
INTRO_KICKER_BOLD = False
INTRO_KICKER_COLOR: Tuple[int, int, int] = (205, 210, 220)
INTRO_KICKER_LETTER_SPACING = 4
# Appended to the intro subtitle as "<subtitle> · 18 か所" (settings.intro_place_count turns it off).
INTRO_PLACE_COUNT_FORMAT = LABELS_JA["place_count"]  # Japanese; other languages: video_text catalogs
INTRO_PLACE_COUNT_SEPARATOR = " · "
DEFAULT_INTRO_PLACE_COUNT = True
INTRO_OUTPUT_FILENAME = "00_intro.mp4"
# Same frame size as every other clip, or the timeline preview draws it smaller.
INTRO_WIDTH = 1920
INTRO_HEIGHT = 1080
INTRO_FPS = 30
# Ken Burns zoom: 1.0 = the whole frame, smaller = tighter.
INTRO_ZOOM_START = 1.0
INTRO_ZOOM_END = 0.88
# Fade to/from black at the start/end of the whole slideshow.
INTRO_FADE_SECONDS = 0.5
# White "Powered by" badge bottom-right (this file from assets/image/logo, label outro_logo_title; None = no
# badge). px on the 1920x1080 intro.
INTRO_LOGO_FILE: Optional[str] = "NDR.png"
INTRO_LOGO_HEIGHT = 42
INTRO_LOGO_TITLE_FONT_SIZE = 17
INTRO_LOGO_PADDING = 12
INTRO_LOGO_MARGIN = 20
INTRO_LOGO_TITLE_COLOR: Tuple[int, int, int] = (70, 76, 90)
# Darkens each photo (multiply) so the white title stays readable.
INTRO_IMAGE_DIM_FACTOR = 0.55
# The title's own scale-up + fade (ASS tags), slower than the frame's fade so it reads as a reveal.
INTRO_LABEL_FADE_SECONDS = 1.1
# Scale (%) the title pops in from and shrinks back to.
INTRO_LABEL_SCALE_START_PCT = 65
# The subtitle enters this long after the title and leaves this long before it, fading and rising.
INTRO_SUBTITLE_DELAY_SECONDS = 0.8
INTRO_SUBTITLE_FADE_SECONDS = 0.7
INTRO_SUBTITLE_RISE_PX = 28

# settings.intro_style: "slideshow" or a silent, text-led style showing settings.intro_lines. Scene 1 = the
# most detailed footage, scene 2 = the plainest; every photo move ends on the whole photo, centred (a push-in
# crops what sits at its edges). zoom 1.0 = whole frame; pan = centre drift (-1..1); dim = brightness
# multiply; sat = saturation; text = the line's look on the timeline.
DEFAULT_INTRO_STYLE = "slideshow"
INTRO_STYLES = ("slideshow", "cinematic", "documentary")
INTRO_STYLE_SCENES: Dict[str, List[Dict[str, Any]]] = {
    # Japanese-cinema minimalism: dark, quiet, small type with lots of empty space.
    "cinematic": [
        {"seconds": 5.5, "zoom": (0.94, 1.0), "pan": (0.0, 0.0), "dim": 0.40, "sat": 0.6,
         "text": {"position": "middle", "style": {"font_size": 46, "bold": False, "letter_spacing": 6, "outline_width": 0, "shadow": 2}}},
        {"seconds": 6.0, "zoom": (0.90, 1.0), "pan": (0.0, 0.0), "dim": 0.60, "sat": 0.85,
         "text": {"position": "middle", "align": "left", "margin_h": 160,
                  "style": {"font_size": 46, "bold": False, "letter_spacing": 6, "outline_width": 0, "shadow": 2}}},
        # "title": the route's name (intro_heading: location kicker, title, subtitle) closes the intro.
        {"seconds": 5.5, "zoom": (0.92, 1.0), "pan": (0.0, 0.0), "dim": 0.45, "sat": 0.8, "title": True,
         "text": {"position": "middle",
                  "kicker": {"font_size": 34, "bold": False, "letter_spacing": 10, "outline_width": 0, "shadow": 2},
                  "style": {"font_size": 110, "bold": False, "letter_spacing": 14, "outline_width": 0, "shadow": 3},
                  "subtitle": {"font_size": 38, "bold": False, "letter_spacing": 6, "outline_width": 0, "shadow": 2}}},
    ],
    # NHK-style documentary: a close-up easing back, then a wide shot pulling out under a bold line.
    "documentary": [
        {"seconds": 5.0, "zoom": (0.86, 1.0), "pan": (0.0, 0.0), "dim": 0.70, "sat": 1.0,
         "text": {"position": "bottom", "align": "right", "margin_h": 120, "margin_v": 180,
                  "style": {"font_size": 54, "bold": False, "letter_spacing": 3, "outline_width": 0, "shadow": 3}}},
        {"seconds": 5.5, "zoom": (0.80, 1.0), "pan": (0.0, 0.0), "dim": 0.60, "sat": 1.0,
         "text": {"position": "middle", "style": {"font_size": 80, "bold": True, "letter_spacing": 4, "outline_width": 0, "shadow": 3}}},
        {"seconds": 5.5, "zoom": (0.85, 1.0), "pan": (0.0, 0.0), "dim": 0.50, "sat": 1.0, "title": True,
         "text": {"position": "middle",
                  "kicker": {"font_size": 40, "bold": False, "letter_spacing": 6, "outline_width": 0, "shadow": 2},
                  "style": {"font_size": 130, "bold": True, "letter_spacing": 6, "outline_width": 0, "shadow": 4},
                  "subtitle": {"font_size": 46, "bold": False, "letter_spacing": 3, "outline_width": 0, "shadow": 2}}},
    ],
}
# The lines' own fade, and how far inside its scene each line starts/ends (it waits out the crossfade).
INTRO_LINE_INSET_SECONDS = 0.4
# A clip whose frames at 20% and 80% differ less than this (mean grey, 0-255) is a held photo: it gets the
# photo zoom/pan instead of freezing.
INTRO_STILL_DIFF = 1.0
# Stops whose name matches this are transport, not intro scenery (with the first and last stop).
INTRO_TRANSPORT_PATTERN = r"駅|バス停|停留所|桟橋|港|汽船|フェリー|乗り場|station|bus stop|pier|port|ferry|terminal"

# --- Outro card grid (end-of-video "places visited" summary) ---------------
# "grid" outro: one held frame, the title over a thumbnail grid of every waypoint photo (outrocard.py).
OUTRO_DURATION_SECONDS = 5.0
OUTRO_OUTPUT_FILENAME = "99_outro.mp4"
# {count} is substituted with the number of waypoint cards shown.
OUTRO_SUBTITLE_TEMPLATE = LABELS_JA["outro_subtitle"]
OUTRO_BG_COLOR: Tuple[int, int, int] = (19, 28, 46)  # RGB dark navy
OUTRO_TITLE_COLOR: Tuple[int, int, int] = (255, 255, 255)
OUTRO_SUBTITLE_COLOR: Tuple[int, int, int] = (150, 158, 173)
OUTRO_LABEL_COLOR: Tuple[int, int, int] = (225, 228, 235)
OUTRO_TITLE_FONT_SIZE = 34
OUTRO_SUBTITLE_FONT_SIZE = 15
OUTRO_LABEL_FONT_SIZE = 14
OUTRO_BADGE_FONT_SIZE = 15
# [HACK] [Config] DEFAULT_MARKER_COLOR flipped to RGB for PIL: the outro badges match every numbered pin.
OUTRO_BADGE_COLOR: Tuple[int, int, int] = tuple(reversed(DEFAULT_MARKER_COLOR))
# More waypoints than this: the first ones in route order (the grid would get illegibly small).
OUTRO_MAX_CARDS = 20
OUTRO_GRID_COLS_MAX = 5
OUTRO_CARD_MARGIN = 18
OUTRO_CARD_ASPECT = 4 / 3  # thumbnail width:height

# "scroll" (default): cards three to a row, scrolled credits-style; "grid": the held frame above.
# settings.outro_style overrides.
DEFAULT_OUTRO_STYLE = "scroll"
# settings.enable_outro: false drops the outro clip from the video.
DEFAULT_ENABLE_OUTRO = True
OUTRO_SCROLL_COLS = 3
OUTRO_SCROLL_MARGIN = 40  # px between cards
# Empty space left and right of the cards, like a centred container's padding.
OUTRO_SCROLL_SIDE_PADDING = 170
OUTRO_SCROLL_LABEL_FONT_SIZE = 20
OUTRO_SCROLL_LABEL_MIN_FONT_SIZE = 15  # a long name shrinks to this before "…"
OUTRO_SCROLL_BADGE_FONT_SIZE = 18
OUTRO_SCROLL_BADGE_RADIUS = 18
# Scroll speed (px/s on the 704-high canvas, scaled, whole px per frame) and the holds at the start and end.
# The title stays pinned at the top while the cards scroll away under it; the logo card follows.
OUTRO_SCROLL_SPEED_PX = 100
OUTRO_SCROLL_START_HOLD_SECONDS = 1.0
OUTRO_SCROLL_END_HOLD_SECONDS = 0.5
# Longest the scroll itself may take; a very long page scrolls faster instead.
OUTRO_SCROLL_MAX_SECONDS = 30.0
# Soft fade under the title box and at the bottom edge, so cards ease in and out of view.
OUTRO_SCROLL_EDGE_FADE_PX = 56
# With route info the scroll is a timeline: title and trip summary, then one card per leg (photo, name,
# start, mode/distance/time chips from route_brief). settings.outro_route_info: false = the grid.
DEFAULT_OUTRO_ROUTE_INFO = True
OUTRO_ROUTE_FROM_TEMPLATE = LABELS_JA["outro_route_from"]
OUTRO_ROUTE_ROW_HEIGHT = 128
OUTRO_ROUTE_ROW_GAP = 16
OUTRO_ROUTE_NAME_FONT_SIZE = 24
OUTRO_ROUTE_FROM_FONT_SIZE = 15
OUTRO_ROUTE_DISTANCE_FONT_SIZE = 22
# The route page's title + subtitle use the intro's text and styles at this fraction of its size.
OUTRO_HEADING_SCALE = 0.7
# The scroll outro's title (a text-track item) sits this many px (1080 line) from the top.
OUTRO_TEXT_MARGIN_TOP = 40
OUTRO_TEXT_BOX_FADE = 56  # soft edge (1080 line px) under the title box
OUTRO_HEADING_LINE_GAP = 10  # px between title and subtitle
OUTRO_ROUTE_COLS = 2
OUTRO_ROUTE_COL_GAP = 16
OUTRO_ROUTE_THUMB_ASPECT = 1.0
# After the last leg card: a title, then every stop-by as a leg-sized card (photo numbered +1, +2 ...).
OUTRO_STOPBY_TITLE_FONT_SIZE = 22
OUTRO_LEG_FONT_SIZE = 16
OUTRO_SUMMARY_VALUE_FONT_SIZE = 30
OUTRO_PANEL_COLOR: Tuple[int, int, int] = (31, 42, 64)
OUTRO_CHIP_COLOR: Tuple[int, int, int] = (45, 58, 86)
OUTRO_ARROW_COLOR: Tuple[int, int, int] = (110, 120, 140)
OUTRO_SUMMARY_HOLD_SECONDS = 4.0
# The end card: every image in assets/image/logo side by side, each on its own white plate (PLATE_COLOR None =
# no plates), scaled down to MAX_WIDTH of the frame if needed.
OUTRO_LOGO_HEIGHT = 80
OUTRO_LOGO_MAX_WIDTH = 0.8
OUTRO_LOGO_FADE_SECONDS = 0.8
OUTRO_TITLE_WIPE_SECONDS = 1.0  # the title + box wipe away top -> bottom as the last cards go under them
OUTRO_LOGO_HOLD_SECONDS = 3.0
OUTRO_LOGO_GAP = 40
OUTRO_LOGO_TITLE_FONT_SIZE = 26  # the "Powered by" line above the plates
OUTRO_LOGO_TITLE_GAP = 22
OUTRO_LOGO_PLATE_PADDING = 28
OUTRO_LOGO_PLATE_COLOR: Optional[Tuple[int, int, int]] = (255, 255, 255)
OUTRO_SUMMARY_LABELS: Dict[str, str] = LABELS_JA["outro_summary"]
# The number on each leg card's photo: a white pill with a dark number.
OUTRO_PHOTO_BADGE_HEIGHT = 26
OUTRO_PHOTO_BADGE_FILL: Tuple[int, int, int, int] = (255, 255, 255, 240)
OUTRO_PHOTO_BADGE_TEXT: Tuple[int, int, int, int] = (19, 28, 46, 255)

# A clip whose narration outlasts it holds its last frame until the voice ends plus this.
AUDIO_END_HOLD_SECONDS = 0.5

# [NOTE] [Ending] The last spoken clip (お疲れさまでした) holds its last frame this
# much longer at export, then dissolves into the outro card instead of cutting;
# the very last clip of the video fades to black, its sound with it.
ENDING_HOLD_SECONDS = 1.0
ENDING_FADE_SECONDS = 1.0
VIDEO_END_FADE_SECONDS = 1.0

# --- TTS narration (Irodori-TTS) --------------------------------------------
# Fallback defaults for ttsengine.TTSConfig; settings.tts overrides.
TTS_MODEL = "irodori-tts"
# "cpu", "cuda" or "auto"; NAVIVI_TTS_DEVICE overrides (read when the server starts). CPU on purpose: GPU TTS
# drove the card to ~7.8 GB and hard-shut the PC (HYPERVISOR_ERROR) more than once, even with short chunks.
TTS_DEVICE = "cpu"
# Longest text per TTS request: about 15 s of speech (~4.4 characters a second).
TTS_MAX_CHUNK_CHARS = 60
# Shortest request: a short trailing chunk is merged into the one before (Irodori "coasts" past the end of a
# very short request and invents a ghost sentence).
TTS_MIN_CHUNK_CHARS = 20
# The same ~15 s for text with no Japanese (~14 characters a second); at 60, sentences were cut mid-phrase.
TTS_MAX_CHUNK_CHARS_LATIN = 200
TTS_MIN_CHUNK_CHARS_LATIN = 60
# A take whose end is louder than this against its speech stopped mid-word: retaken, then spoken in halves.
TTS_CUTOFF_RATIO = 0.25
TTS_CUTOFF_RETAKES = 2
# Engines whose narration goes through artifacts.remove_stray_bursts (for Irodori's stray "あ"; on Qwen3 it
# silenced real syllables).
TTS_STRAY_BURST_ENGINES = ("irodori",)
# Each take is heard back (name_check.py) and retaken when a spelled-out place name is missing from it; the
# fewest-misses take is kept. Needs faster-whisper.
TTS_NAME_CHECK = True
# Cue times are measured by listening to the take (cue_alignment.py, CPU) instead of estimated from
# character counts (up to ~5 s off); falls back to the estimate.
ALIGN_CUES_TO_VOICE = True
TTS_NAME_RETAKES = 2
# Kanji-first: send dictionary words in kanji and rely on the name check. Off: Whisper can write the right kanji
# for a misread take (慈眼院 said じがんいん), so every dictionary word is spelled out (ジゲン院).
TTS_KANJI_FIRST = False
TTS_NAME_CHECK_MIN_CHARS = 3  # kana, not counting ー: shorter runs (ゴール) are left alone unless a plain ending follows (ミワ神社)
TTS_NAME_CHECK_MODEL = "kotoba-tech/kotoba-whisper-v2.0-faster"  # Japanese Whisper for faster-whisper, ~1.5 GB, downloaded on first use
# Each sentence is its own request; the silence between them is random in this range (no metronome clicks).
TTS_SENTENCE_GAP_MIN_SECONDS = 0.25
TTS_SENTENCE_GAP_MAX_SECONDS = 0.5
TTS_VOICE = "jvs004"  # Irodori's only bundled voice preset as of writing
# Playback speed sent to Irodori (1.0 = natural); validated against MIN/MAX before the request.
TTS_SPEED = 1
TTS_MIN_SPEED = 0.25
TTS_MAX_SPEED = 4.0
TTS_RESPONSE_FORMAT = None  # None = let the server use its own default (wav)
# Speaking-style caption sent with each request (None/"" = omit); settings.tts.caption overrides.
TTS_CAPTION = "落ち着いた、親しみやすい語り口。"

# --- Attraction clip place-name label (top-left, for the whole clip) -------
# The place name is a text item on the editor's text track (place_label.py); older clips keep a burned label.
ATTRACTION_LABEL_ON_TEXT_TRACK = True
ATTRACTION_LABEL_FONT_SIZE = 26
ATTRACTION_LABEL_OUTLINE = 0.8
# Distance from the top / left edge (libass units).
ATTRACTION_LABEL_MARGIN_TOP = 4
ATTRACTION_LABEL_MARGIN_LEFT = 4
# Unsharp pass after the attraction clip's upscale. Off (2026-10-22): it sharpened LTX's grain. A light
# temporal denoise (ATTRACTION_DENOISE, CPU) runs on generated clips before the upscale instead.
ATTRACTION_UPSCALE_SHARPEN = False
ATTRACTION_DENOISE: Optional[str] = "hqdn3d=1.5:1.5:6:6"

# --- Burned-in captions (timeline export and the per-clip subtitle burn) -----
# A translucent dark box, narrow and centred at the bottom, clear of the route clips' card. Mirrored in
# src/utils/subtitleLook.ts. Units are libass's 288-line frame (384 wide), not pixels.
CAPTION_DEFAULT_SIZE = 16
CAPTION_MAX_WIDTH = 0.5  # share of the frame width the box may use
CAPTION_MARGIN_V = 20  # gap above the bottom edge
CAPTION_BOX_PADDING = 2.0  # libass pads a box by its outline width
CAPTION_BOX_COLOR = "&H66000000"  # ASS alpha 66 = 60% opaque black
CAPTION_PLAY_RES_X = 384
# Generated subtitles: characters per line when caption_style.max_chars_per_line is 0, and how a longer clause
# is shown (settings.subtitle_long_lines): "split" = one-line captions in turn, "wrap" = up to 2 lines.
SUBTITLE_MAX_CHARS_PER_LINE = 20
SUBTITLE_LONG_LINES = "split"

# --- Narration speed presets and cache (Irodori) -------------------------------
# Irodori steps per preset (settings.tts.quality): on a CPU, steps are the one big cost. Not part of the voice
# fingerprint, so finished audio stays valid when the preset changes.
TTS_QUALITY_PRESETS: Dict[str, Dict[str, object]] = {
    "fast": {"num_steps": 16},
    "balanced": {"num_steps": 24},
    "best": {"num_steps": 40},
}
TTS_QUALITY_DEFAULT = "best"
# Spoken lines are cached (shared by every project), so a repeated line or a regenerate is instant.
TTS_CACHE_MAX_MB = 500

# Irodori CPU cost (seconds) for the first estimate of a project: a straight-line fit of measured requests
# (Ryzen 5 5600GE); the sampling parts scale with the number of steps.
TTS_CPU_COST = {
    "request_fixed": 3.0,  # duration prediction, watermark
    "reference_encode": 5.0,  # only until the reference latent is saved
    "request_sampling": 28.3,  # per request, at 40 steps
    "char_sampling": 0.96,  # per character, at 40 steps
    "char_decode": 0.5,  # per character
}
TTS_BASE_STEPS = 40

# --- Narration engines -----------------------------------------------------------
# "irodori": natural, clones a voice, slow on a CPU. "qwen3": clones too, ~6.5 s compute per second of audio.
# "kokoro": fixed voices, 1-4 s a line. settings.tts.engine picks one (part of the voice fingerprint).
TTS_ENGINES = ("irodori", "qwen3", "kokoro")
TTS_ENGINE_DEFAULT = "irodori"
KOKORO_PORT = 8089
KOKORO_VOICE = "jf_tebukuro"
# id -> label (jf_/jm_ Japanese, af_/am_ US English, bf_/bm_ UK English).
KOKORO_VOICES: Dict[str, str] = {
    "jf_tebukuro": "Tebukuro (female)",
    "jf_alpha": "Alpha (female)",
    "jf_gongitsune": "Gongitsune (female)",
    "jf_nezumi": "Nezumi (female)",
    "jm_kumo": "Kumo (male)",
    "af_heart": "Heart (US, female)",
    "af_bella": "Bella (US, female)",
    "am_michael": "Michael (US, male)",
    "bf_emma": "Emma (UK, female)",
}
KOKORO_ENGLISH_VOICE = "af_heart"


def kokoro_language(voice: str) -> str:
    """The Kokoro language code a voice speaks (its id's first letter): "j" Japanese, "a" American, "b" British English."""
    return voice[:1] if voice[:1] in ("j", "a", "b") else "j"
# Measured: ~1 s per request + ~0.09 s per character, ~35 s to load once per process.
KOKORO_COST = {"request": 1.0, "char": 0.09, "startup": 35.0}

# Qwen3-TTS 0.6B Base: same voice library as Irodori, ~3 GB of RAM. Measured ~5 s per request + 0.85 s per
# character, ~40 s to load once per process.
QWEN3_PORT = 8090
# Qwen3 slurs some kanji readings: each kanji word is sent as its UniDic katakana.
QWEN3_SPELL_OUT_KANJI = True
QWEN3_MODEL = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
# "cuda" or "cpu" (NAVIVI_TTS_DEVICE overrides). On cuda: bfloat16, capped to VRAM_FRACTION, CPU fallback, and
# each request waits out a hot GPU. This PC has hard-crashed during GPU work.
QWEN3_DEVICE = "cpu"
QWEN3_VRAM_FRACTION = 0.4
QWEN3_COST = {"request": 5.0, "char": 0.85, "startup": 40.0}

# [NOTE] [Legs] A Mapillary street photo pops up as a small card at each turn of a walking leg (settings.street_photos_at_turns).
# Needs the app-wide Mapillary token; turns without coverage just show no card.
STREET_PHOTOS_AT_TURNS = False

# [NOTE] [Attraction] Hand-held finish (vdoprocessing/handheld.py) on every generated attraction clip: a slow seeded
# drift and roll, plus the PARALLAX_WALK_* footsteps on walking moves. After generation, never in the prompt
# ("hand-held" made LTX draw hands). Part of the tail signature, so a change refits kept clips on the CPU.
HANDHELD = False  # 2026-10-22: the user preferred the steady camera
HANDHELD_DRIFT = 0.004  # share of the frame
HANDHELD_ROLL_DEG = 0.3
HANDHELD_WALK_MOVES: Tuple[str, ...] = ("walkin", "walkback", "walkfwd", "walkfwdleft", "walkfwdright", "walkshort", "walkai")
