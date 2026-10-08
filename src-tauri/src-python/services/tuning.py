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

import gc
import logging
import os
import time
from typing import Callable, Dict, List, Optional, Tuple

# --- GPU stage cooldown ------------------------------------------------------
# Pause inserted in pipeline.py between the ComfyUI/Wan2.2 attraction-video
# stage and the Playwright/Chromium route-video stage right after it — two
# back-to-back GPU-heavy workloads (diffusion sampling, then forced-GPU WebGL
# compositing via --use-gl=angle) with no gap between them on an 8GB-class
# card left driver/VRAM state no time to release, and hit thermal/power
# protection shutdowns on at least one 8GB laptop GPU (RTX 5060). This isn't
# a fix for VRAM overcommit itself (neither stage has a hard cap), just a
# breather so the GPU isn't asked to jump straight from one sustained load
# into another. Skipped entirely when attraction videos are disabled for a
# project, since there's nothing to cool down from.
GPU_STAGE_COOLDOWN_SECONDS = 8.0
# Before each Wan attraction clip (services/gpu_cooldown.py): if the GPU is at
# or above GPU_COOLDOWN_START_C, wait until it is down to GPU_COOLDOWN_RESUME_C
# (checked every GPU_COOLDOWN_POLL_SECONDS), but never longer than
# GPU_COOLDOWN_MAX_WAIT_SECONDS. Back-to-back clips otherwise keep an 8GB
# laptop card near 77C for the whole attraction step. Still-photo clips
# ("none" preset) skip this - they don't use the GPU.
GPU_COOLDOWN_START_C = 70
GPU_COOLDOWN_RESUME_C = 60
GPU_COOLDOWN_POLL_SECONDS = 3.0
GPU_COOLDOWN_MAX_WAIT_SECONDS = 120.0

# --- FFmpeg resource cap -----------------------------------------------------
# No ffmpeg call anywhere in this codebase passed -threads before, so every
# encode/mux/upscale was free to claim every CPU core at once — on a render-
# heavy run (subtitle burn, upscale, concat, TTS audio processing) that can
# leave the whole machine unresponsive. Leave a couple of cores free by
# default so the OS/UI stays usable while a render is in progress.
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
# TTS, ComfyUI/Wan, Chromium (the map renderer) and Ollama each hold a lot of
# RAM, and this pipeline runs them one after another in one long process. Before
# each heavy stage/unit of work `ensure_free_ram` checks that enough memory is
# actually free, frees what it can (gc, and any servers the caller can stop),
# waits for it to come back, and stops the run with a clear message instead of
# pushing the machine into swap or a hard shutdown. Every stage is checkpointed,
# so re-running resumes where it stopped. A project can change the limit with
# job_config.json's settings.min_free_ram_gb (0 turns the guard off).
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
# Every string drawn into the video lives in a per-language catalog,
# assets/config/labels_<lang>.json, resolved by services/video_text.py
# (labels_for / current_labels; project setting video_text_language). A
# project can still override a subset via job_config.json's
# settings.pipeline_labels / settings.summary_card_labels (see cards.py's
# merge_summary_card_labels). LABELS_JA / PIPELINE_LABELS stay as the
# Japanese catalog for callers that predate the language setting.
from services.video_text import labels_for as _labels_for  # noqa: E402

LABELS_JA: Dict = _labels_for("ja")
PIPELINE_LABELS: Dict = LABELS_JA

# --- Mode aliases ------------------------------------------------------------
# Route-mode strings that should be TREATED AS another mode everywhere a mode
# drives behavior (speed lookup, animation icon, line/card color, duration
# label) — rather than being a distinct identity that then falls through to
# some generic fallback. "direct" (a straight-line routing choice, not a real
# travel mode) already aliased to "walking"; "draw" (a hand-drawn custom-route
# leg) is walking in every practical sense here too — same pace, same on-foot
# icon — so it's folded into the same alias rather than getting its own
# separate (and generic-fallback-flavored) identity. Apply via
# `MODE_ALIASES.get(mode, mode)` at the point a mode string is first read off
# job_config.json (routeMode / routing_cache), so every downstream lookup
# just sees "walking" and never has to special-case "draw" itself.
# [NOTE] [Routing] "curve" is what the editor's Fly choice saves (the leg's
# line is a bezier arc the frontend computed); the pipeline calls it airplane.
MODE_ALIASES: Dict[str, str] = {"direct": "walking", "draw": "walking", "curve": "airplane"}

# Travel modes that fall back to the flat 2D renderer for their own leg even
# when the project is otherwise on the pydeck pedestrian pipeline (see
# route2vdo._render_residential_pydeck). The chase camera is built for
# ground-level travel: it follows the route at pedestrian zoom with a tilted
# horizon, which suits walking, driving AND a ferry crossing (pedestrian.py's
# own _MODE_HUD has a dedicated "ferry" entry — icon, "乗船時間" label, 乗船中
# suffix, 30km/h default pace) but not a flight, where the "route" is a long
# featureless line over open sky and a tilted close-up of it shows nothing.
# Those legs read far better as a flat, zoomed-out 2D map showing the whole
# hop. Legs either side of one still render in 3D — the fallback is per leg,
# not per project.
RESIDENTIAL_2D_FALLBACK_MODES: Tuple[str, ...] = ("airplane",)

# --- Mode speeds (km/h) -----------------------------------------------------
# REPORTED is the real-world speed a leg's distance/time is estimated from
# when no real GPS timestamp is available (drives the summary/per-leg stat
# cards and every other real-world calculation) — unaffected by anything
# below. ANIMATION_SPEED_KMH is the single on-screen travel pace EVERY mode
# animates at by default (walking, driving, ferry, airplane — all the same),
# so a fast car/ferry/flight leg doesn't visually zip by relative to a
# walking one just because its real-world speed is so much higher; only the
# real numbers above still vary per mode. A project can still opt a specific
# mode into its own on-screen pace via job_config.json's
# settings.animation_speeds_kmh (see SpatialRenderer.__init__).
REPORTED_MODE_SPEED_KMH: Dict[str, float] = {
    "walking": 3.0,
    "ferry": 35.0,  # regular passenger ferry, not a high-speed jet ferry
    "car": 70.0,
    "driving": 70.0,
    "airplane": 500.0,
}
ANIMATION_SPEED_KMH = 3.0
# Fixed anchor "1x" pace every mode's on-screen speed-up factor is computed
# against — not whatever ANIMATION_SPEED_KMH happens to be configured as
# (see SpatialRenderer._mode_speed_factor).
# [NOTE] [Config] Kept independent of REPORTED/ANIMATION_SPEED_KMH so changing either doesn't silently rescale every mode's speed-up factor.
REFERENCE_SPEED_KMH = 3.0
# Walking and ferry are the two exceptions to "every mode shares the same
# ANIMATION_SPEED_KMH pace" above: walking is deliberately shown a bit
# slower than that shared baseline (reads as a calmer, more deliberate
# stroll rather than a brisk power-walk), and ferry gets a boost relative
# to walking's OWN (already-slowed) pace, not the base pace, so a boat
# crossing still visibly outpaces someone on foot instead of both ending up
# at the same on-screen speed. car/driving/airplane are untouched by this —
# see SpatialRendererBase.__init__ for where these apply.
WALKING_ANIMATION_SPEED_FACTOR = 0.75
FERRY_ANIMATION_SPEED_FACTOR = 1.5

# --- Pin / line colors (BGR) ------------------------------------------------
# Matched to the frontend's NaviPin.tsx (src/components/view/mapeditor/
# MapLayers/NaviPin.tsx) so backend-rendered map pins are the same colors as
# the ones shown live in the map editor — each is that component's hex fill
# converted to BGR.
START_PIN_COLOR: Tuple[int, int, int] = (3, 136, 19)  # #038813 green
END_PIN_COLOR: Tuple[int, int, int] = (81, 15, 217)  # #d90f51 red/pink
DRAWN_PIN_COLOR: Tuple[int, int, int] = (12, 121, 255)  # #ff790c orange — drawn-route waypoints
STOPBY_PIN_COLOR: Tuple[int, int, int] = (28, 38, 51)  # #33261c dark brown — stop-by waypoints
# How close start_point and end_point need to be (in degrees lat/lng) to
# count as "the same place" — a loop/out-and-back route — for the "E"
# pin's half green/red split (see pins.py's _pin_label_and_color and
# SpatialRendererBase._is_loop_route). Matches the proximity threshold
# render_step.py's own waypoint-id resolution already uses for "this is
# really the same real-world spot" (~30m at these latitudes); a genuinely
# different end point a block or two away should never trigger this.
LOOP_ROUTE_MATCH_DEGREES = 0.0003
# Base route-line color: the fallback for any travel mode without its own
# entry in MODE_LINE_COLORS, and what the end-of-video zoom-to-start
# highlight draws the whole route with. Neutral grey rather than the gold
# it used to be — now that each real mode carries its own color (walking
# blue, ferry orange, ...), the base line reads as "route" rather than
# competing with them, and grey stays legible over both the light land and
# the blue water without claiming to be a mode of its own.
DEFAULT_LINE_COLOR: Tuple[int, int, int] = (110, 110, 110)  # #6e6e6e grey
DEFAULT_MARKER_COLOR: Tuple[int, int, int] = (245, 135, 66)  # #4287f5 blue — every other numbered pin
DEFAULT_ARRIVED_MARKER_COLOR: Tuple[int, int, int] = (200, 110, 30)  # deeper blue once visited
PIN_NUMBER_TEXT_COLOR: Tuple[int, int, int] = (17, 17, 17)  # #111 — NaviPin's number/letter fill

# --- Route line border (outline stroke) -------------------------------------
# The route line is drawn as a wider "border" stroke underneath the actual
# colored line (see draw_path) so it stays legible over busy map tiles of
# any color — like the pin's white halo. Overridable per project via
# job_config.json's settings (route_line_border_color, in BGR like every
# other color constant here, and route_line_border_thickness in px added to
# EACH side of the line, so the border's total width is line_thickness +
# 2 * route_line_border_thickness). Thickness 0 draws no border at all.
DEFAULT_LINE_BORDER_COLOR: Tuple[int, int, int] = (255, 255, 255)  # white
DEFAULT_LINE_BORDER_THICKNESS = 3

# --- Popup/summary card text & border --------------------------------------
# Overridable per project via job_config.json's settings (card_border_color,
# card_border_thickness) — see GraphicsEngineBase.__init__. Border color is
# BGR, like every other color constant here.
DEFAULT_CARD_BORDER_COLOR: Tuple[int, int, int] = (230, 230, 230)  # light gray
DEFAULT_CARD_BORDER_THICKNESS = 1
# Popup-picture caption size, as a multiple of settings.map_font_size (kept
# relative rather than a flat pixel size so it still shrinks/grows with a
# scaled-down card, e.g. the intro overview's card_scale). Bumped up from
# the original 0.6x/1.0x (too small), then brought back down from 1.15/1.1
# (too large — competed with the photo/pin for attention, especially on
# the small "beside" card).
POPUP_LABEL_FONT_SCALE_BESIDE = 0.9  # "beside the pin" card (was 0.6x, 0.85x, then 1.15x)
POPUP_LABEL_FONT_SCALE_CORNER = 0.95  # fixed HUD-corner card (was 1.0x, 1.3x, then 1.1x)
# Waypoint name chip drawn next to each numbered/lettered pin as the route
# animates leg-to-leg (e.g. "S  大阪市") — see _SpriteMixin.prebake_landmark_sprite.
# Bumped up from 0.6x, which read as too small to make out against a busy
# map tile at video resolution.
WAYPOINT_LABEL_FONT_SCALE = 0.85
# Summary-card stat text — flat pixel sizes (at the card's internal 2x
# render scale), independent of card_size since the card is always
# resampled down to its target box afterward. Bumped up from the
# original 14/24-26px, which read as too small for an end-of-video stat.
SUMMARY_CARD_LABEL_FONT_SIZE = 20
SUMMARY_CARD_VALUE_FONT_SIZE = 34
# Which summary-card template render_summary_card picks: "glass" (the
# original wide stat pill/column card, cards.py's create_summary_card),
# "taskbar" (a narrow Windows-notification-flyout-style list,
# create_summary_card_taskbar), "stacked" (two rows, each just an icon and a
# number — walking figure + distance, clock + duration, no labels —
# create_summary_card_stacked), or "columns" (columns again, colored per
# mode like "stacked", but each column is a tall icon spanning its label +
# value stacked beside it, then a small clock+duration row underneath — the
# user's own sketch, refined over two rounds — create_summary_card_columns).
# Overridable per project via job_config.json's settings.summary_card_style.
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
# Floor on the residential-chunk zoom level computed from a leg's physical
# span (see TileDownloader.fetch_residential_chunk) — a leg whose path
# bulges or loops (e.g. a detour around a highway on-ramp) can inflate
# that span well past what the leg's start/end distance suggests, picking
# a lower zoom than the leg actually needs, which reads as street/place
# labels becoming too small to make out. This floor keeps every SHORT
# (local/residential-scale) leg at least this legible regardless of path
# shape.
#
# Only applied when the leg's two pins are within
# RESIDENTIAL_MIN_ZOOM_MAX_PIN_DISTANCE_M of each other — gated on the
# straight-line pin distance rather than the (bulge-inflated) padded span,
# since that's the one measure a detour/loop can't skew. Long car/ferry/
# driving legs must NOT get this floor: forcing e.g. a 30km leg from its
# natural zoom (~12) up to 17 multiplies the tile count roughly 4x per
# zoom level jumped, which turned one real render into a multi-thousand-
# tile download that never finished in reasonable time.
RESIDENTIAL_MIN_ZOOM = 17
RESIDENTIAL_MIN_ZOOM_MAX_PIN_DISTANCE_M = 2000
# Ceiling on the other end — independent of the tile provider's own
# MAX_ZOOM_LEVEL (19), which is a capability limit, not a "looks good"
# limit. A very short/tight leg's span-based zoom lookup could otherwise
# reach right up to that provider ceiling, framing so close the map reads
# as an abstract block-level crop rather than a recognizable street view.
RESIDENTIAL_MAX_ZOOM = 18
# How far a leg's own path (a loop, an on/off-ramp, a switchback) is
# allowed to inflate the map's framing beyond the straight-line distance
# between its two pins — see _compute_residential_bbox's own cap. 1.5x
# lets a moderate bulge still frame naturally; a bigger loop gets scaled
# back down to this multiple instead of zooming the whole leg out to fit
# it, which used to leave most of the frame as empty unused map.
RESIDENTIAL_LOOP_ZOOM_CAP = 1.5
# Absolute floor (in degrees, ~55m) on that cap's own diagonal — without
# this, a leg whose pins sit almost on top of each other (a loop that
# returns nearly to its own start) would get capped down to a near-zero,
# degenerate box.
RESIDENTIAL_LOOP_ZOOM_CAP_MIN_DEGREES = 0.0005
# Minimum fraction of the box's own span a pin must stay away from any
# edge — see _compute_residential_bbox's safety clamp. A zigzagging path
# (several switchbacks leaning the same direction, none of them one
# single dominant loop RESIDENTIAL_LOOP_ZOOM_CAP would catch) can still
# drag the path-bbox center far enough that a pin ends up almost cut off;
# this translates the box back just enough to guarantee at least this
# much breathing room, without touching its zoom/span.
RESIDENTIAL_PIN_EDGE_MARGIN = 0.10
# Fraction of the frame's own height that the bottom summary bar roughly
# occupies (create_leg_summary_bar's default bar_height + its shadow band
# is ~174px of a 1080px-tall frame) — the residential chunk tile's own
# vertical framing is biased upward by this much so the route/pins still
# read as centered in the AREA ABOVE the bar once it's composited on,
# rather than the bar visually cutting into what would otherwise be a
# frame-centered route.
RESIDENTIAL_MAP_BOTTOM_BAR_FRACTION = 0.16
# How many residential-leg map tiles MapFetcher.process_residential_sequence
# fetches concurrently (thread pool — these are network-bound calls to the
# tile provider via contextily, so they genuinely overlap instead of
# competing for CPU). Kept modest rather than "as many legs as there are"
# to stay well clear of the tile provider's own rate limiting; raise with
# caution, and only alongside TileDownloader's wait/retry backoff settings.
RESIDENTIAL_TILE_FETCH_WORKERS = 4
# Leg HUD compass under the top-right destination pill. The dial stays north-up (the
# map is always north-up); the needle turns to the walker's heading, taken
# across +/- RESIDENTIAL_COMPASS_HEADING_WINDOW_M of path so GPS wiggles
# don't make it twitch.
RESIDENTIAL_SHOW_COMPASS = True
RESIDENTIAL_COMPASS_SIZE_PX = 104
RESIDENTIAL_COMPASS_HEADING_WINDOW_M = 20.0
# Whether a stop-by waypoint (job_config.json's "isStopBy": true) merges
# into the surrounding real-to-real leg (True — just shows its pin as the
# traveler passes, no popup, no new map tile) instead of forcing its own
# full leg/tile boundary and arrival-popup sequence like a real waypoint
# (False — the old behavior). Overridable per project via job_config.json's
# settings.merge_stopby_waypoints.
DEFAULT_MERGE_STOPBY_WAYPOINTS = True
# Whether the overview map animation is rendered with pydeck (a 3D WebGL map in
# headless Chromium) instead of the flat static-tile renderer. Overridable per
# project via job_config.json's settings.use_pydeck_overview. Note: pydeck
# renders on the GPU. Off by default (the user's choice): the 2D overview has
# the photo pop-ups and follows the cues, and still ends on the 3D
# pydeck zoom (settings.enable_gl_ending_zoom, on by default).
DEFAULT_USE_PYDECK_OVERVIEW = False
# Whether a hand-written overview narration gets {n} / {go} cue tags placed
# automatically (localization/overview_cues.py), so the overview walker stops
# at each waypoint while the voice describes it, then heads on. Only tags are
# added (stored in .narration_cues.json), never words, and tags the user
# wrote win. Overridable per project via job_config.json's
# settings.auto_overview_cues.
DEFAULT_AUTO_OVERVIEW_CUES = True
# Whether a leg narration with no cue tags gets them placed automatically
# (videopipeline/narration_step.cued_script): the walker must have arrived by
# the moment the attraction text starts, since that text opens by naming the
# place ("こちらが加太の石標です", "『常行寺』に到着しました"). Without cues the
# walk only had to arrive by the END of the voice, so the place was named
# while the walker was still on its way. Tags only, never words, stored in
# .narration_cues.json; tags the user wrote win. Overridable per project via
# job_config.json's settings.auto_narration_cues.
DEFAULT_AUTO_NARRATION_CUES = True
# Whether a numbered overview stop gets its own short description (pulled
# from its attractionNarration/arrivingNarration, see overview_script.py's
# _facts) while the walker is stopped there, the same way a passed-by
# stop-by's own fact gets woven into the via_batches mention. Off used to
# mean a numbered stop was named ("{n}...{go}") but never actually
# described - just a silent pause between "heading to X" and "leaving X".
# Overridable per project via job_config.json's
# settings.overview_describe_stops.
DEFAULT_OVERVIEW_DESCRIBE_STOPS = True
# Every residential leg opens on a brief WIDE shot of the whole leg, then
# zooms — a scale+crossfade between two separately-fetched static tiles,
# not a continuous crop within one image — into the existing tight/close
# framing before the traveler animation begins.
RESIDENTIAL_WIDE_HOLD_SECONDS = 1.2
RESIDENTIAL_WIDE_ZOOM_SECONDS = 1.0
# Wide tile's bbox half-extent is the tight tile's own half-extent
# (straight-line pin distance + its 20% pad) multiplied by this — loose
# enough to read as "establishing". No RESIDENTIAL_MIN_ZOOM floor is
# applied to the wide tile.
RESIDENTIAL_WIDE_BBOX_MULTIPLIER = 2.5
# Wide-shot multiplier used instead of RESIDENTIAL_WIDE_BBOX_MULTIPLIER for
# a short/local leg (pins within RESIDENTIAL_MIN_ZOOM_MAX_PIN_DISTANCE_M of
# each other, the same "local" threshold the tight tile's own min-zoom
# floor uses) — see _compute_residential_bbox's own tapering logic. The
# full 2.5x multiplier is sized for a multi-km ferry/hike leg; applied to
# a short in-town walk it zoomed the establishing shot out far enough to
# swallow whole neighboring hills/bays that have nothing to do with the
# leg, before zooming sharply back in for the tight tile.
RESIDENTIAL_WIDE_BBOX_MULTIPLIER_LOCAL = 1.6
# A leg's wide establishing shot is only worth showing when its two pins
# are far enough apart that the zoom-in actually reads as "zooming in" —
# below this straight-line pin distance, the wide and tight tiles end up
# at nearly the same zoom level anyway, so the extra shot is just a stall
# before the traveler animation. Short legs skip straight to the tight
# framing (no wide tile fetched, no crossfade played).
RESIDENTIAL_WIDE_MIN_DISTANCE_M = 400.0
# Default leg-splitting distance (replaces the old math.inf, which disabled
# splitting entirely) — a leg longer than this becomes N sequential tight-
# tile chunks, hard-cut between them (free — see VideoExporter's existing
# per-chunk clip concatenation); the wide shot only plays before chunk 1 of
# each leg, not before every chunk.
RESIDENTIAL_DEFAULT_MAX_CHUNK_DISTANCE_M = 8000.0
# Per-travel-mode ROUTE LINE colors. Modes without an entry fall back to
# the renderer's own line_color.
# [NOTE] [Config] A mode missing here falls back to the renderer's own line_color rather than a hardcoded default.
MODE_LINE_COLORS: Dict[str, Tuple[int, int, int]] = {
    # Was unset (falling back to line_color's yellow/gold) — the same
    # color doubled as the walking-mode accent on cards.py's summary card
    # labels (see _mode_accent), where yellow text read poorly against the
    # card's light background. Explicit "Google Maps blue" instead: good
    # contrast on a light card AND distinct from every other mode below.
    "walking": (232, 115, 26),  # #1A73E8 blue
    "ferry": (0, 140, 255),  # orange — reads clearly against blue water
    "airplane": (180, 60, 220),  # magenta/purple
    "car": (60, 180, 60),  # green
    "driving": (60, 180, 60),
}

# --- End-of-video "zoom to start point" highlight ---------------------------
# How long the freshly-fetched close-up tile is held/zoomed after the hard
# cut, before handing off to the fullscreen photo transition (or just
# holding). Also drives the dynamic-pydeck path's own zoom pacing (see
# ENDING_HIGHLIGHT_PYDECK_ZOOM_BOOST) — shortened together with
# BIG_MAP_ZOOM_LEAD_SECONDS below so the SAME total zoom amount plays out
# over less time, i.e. visibly faster, not just a shorter hold.
ENDING_HIGHLIGHT_WAIT_SECONDS = 0.9
# How long the ending highlight holds its pip picture (the start point's photo
# card) before the video ends. It used to be that waypoint's own
# freeze_seconds (3s by default) - a long stare at the last frame; kept short.
ENDING_HIGHLIGHT_PIP_HOLD_SECONDS = 1.5
# Lead-in: how long to push in on the CURRENT wide map (clean, no cards)
# toward the same point BEFORE that hard cut, and how far.
BIG_MAP_ZOOM_LEAD_SECONDS = 0.8
BIG_MAP_ZOOM_TARGET = 2.6
# When settings.enable_gl_ending_zoom (or overview_background: "pydeck")
# is on (see mapfetcher/pydeck_overview.py), the ending highlight's
# lead-in push AND its cut to a separate fetched close-up tile are both
# replaced by ONE continuous sequence of genuinely re-rendered deck.gl
# frames zooming from the wide map all the way in — real map detail
# revealed as it zooms, rather than a modest digital Ken Burns crop
# followed by a hard cut to a second static image. In log2 zoom units
# (each +1 doubles the visual scale) — 7.0 stops: individual city blocks
# and building outlines visible, street names clearly legible, matching
# the tight, block-level reference zoom requested directly against the
# map editor's own live view — well past plain street-label level,
# regardless of the base overview's own zoom. This is a CEILING, not a
# forced amount: when the route is being framed (route_latlon passed to
# capture_pydeck_zoom_sequence), choose_route_focus_view can still pull
# back from it to keep the route line in shot, so raising this only ever
# allows MORE zoom, never forces a tighter shot that would crop the line
# out — but note choose_route_focus_view tries the TIGHTEST (highest)
# zoom in range FIRST and only backs off if too little route stays in
# frame there, so a route that already fits fine at a lower boost will
# zoom in further now rather than staying put.
ENDING_HIGHLIGHT_PYDECK_ZOOM_BOOST = 9.5

# --- Popup / transition timing ----------------------------------------------
POPUP_FADE_SECONDS = 1.5
# The overview's opening start/end cards stay fully shown at least this long
# (not counting their slide in/out); a later {start} cue keeps them up until it.
OVERVIEW_INTRO_CARD_MIN_SECONDS = 2.0
# Minimum wall-clock gap between one waypoint popup triggering and the next
# one being allowed to — a cluster of waypoints placed close together on
# the map (a common case: several stops within the same block) would
# otherwise all snap in on the same frame. Kept to a brief stagger, NOT a
# readability pause: at the 2.0s it used to be, a cluster's cards queued up
# and appeared seconds after the traveler had visibly gone past their pins,
# which reads as the card belonging to somewhere the dot already left.
# Cards are meant to arrive with the traveler and then coexist (see
# MAX_CONCURRENT_FLOW_POPUPS) rather than take turns.
OVERVIEW_POPUP_MIN_TRIGGER_GAP_SECONDS = 0.4
# How many flow-through popup cards may share the screen at once. Raised
# alongside the shorter trigger gap above: with cards no longer waiting
# their turn to appear, a dense cluster needs the room to actually show
# them together, or the ones behind sit queued for a display slot and can
# still time out having never been drawn (see _make_baked_popup's
# max_wait_frames).
MAX_CONCURRENT_FLOW_POPUPS = 4
# How much earlier than a popup's own computed `expected_frame` (its
# nearest-point position along the animated path — see overview.py) the
# proximity trigger is still allowed to fire. Exists only to absorb the
# expected_frame ESTIMATE's own small margin of error (the nearest-XY
# search runs over a window, not a single point) — not to intentionally
# show a popup before the traveler has actually reached it. Used to be a
# full second, which is long enough to be visibly early (a viewer sees the
# card appear while the dot is still approaching the pin, not on it) —
# kept just wide enough to cover realistic estimation jitter instead.
OVERVIEW_POPUP_TRIGGER_TOLERANCE_SECONDS = 0.2
# How close (in seconds of animated travel time) the traveler must be to a
# waypoint's own expected_frame before the overview's dynamic top-banner
# caption (see overview_animation.py/GraphicsEngine.render_top_banner)
# switches from "{label} へ" (still en route) to "まもなく {label}"
# (arriving) — matches pydeckrecorder.pedestrian's own arrive_threshold_m,
# just expressed in time (animated-path seconds) rather than real-world
# meters, since the 2D overview has no consistent meters-per-pixel scale
# to compare against.
OVERVIEW_BANNER_NEAR_SECONDS = 3.0
# End-of-video recap: every waypoint's photo card ends up on screen at once
# (laid out around the frame's border by popups.py's _layout_recap_cards),
# all fading in together from the clean map in a single crossfade of this
# duration, rather than a few cards at a time.
RECAP_GROUP_FADE_SECONDS = 0.4
# Leader-line/card-border colors cycled by a popup's position around the
# recap reveal order (see popups.py's _layout_recap_cards) — NOT tied to the
# waypoint's own pin category. By recap time every waypoint has "arrived",
# collapsing _pin_label_and_color to just two flat colors (one shared by
# every numbered stop, one shared by every stop-by landmark), so
# same-category cards would be indistinguishable from each other; cycling a
# small distinct palette in ring order instead gives each card a color
# different from its neighbours', and puts any repeat a long way around the
# ring from the card it repeats. BGR tuples (a
# Tableau10-derived qualitative palette), picked to stay visually distinct
# from each other and from the fixed route/pin colors above (route line
# yellow, START/END green/red, DRAWN_PIN_COLOR orange — omitted here to
# avoid a near-identical duplicate).
RECAP_LINE_COLOR_PALETTE: List[Tuple[int, int, int]] = [
    (180, 119, 31),   # blue
    (189, 103, 148),  # purple
    (75, 86, 140),    # brown
    (194, 119, 227),  # pink
    (127, 127, 127),  # gray
    (34, 189, 188),   # olive
    (207, 190, 23),   # cyan
]
# How long a flow-through popup's beside-pin position (its "beside_box",
# found by _layout_beside_popups' spiral search) is locked in place once
# set, before it's allowed to be recomputed. Without this, a newly
# triggered popup with a lower visit `order` sorts ahead of an
# already-displayed one in the next frame's layout pass, forcing the
# already-visible card to suddenly spiral out to a new spot to avoid the
# newcomer — reading as the card jumping mid-display instead of holding
# still. Only blocks the CARD ITSELF from moving; it's still added to
# `placed` during the lock so other, not-yet-positioned cards correctly
# avoid overlapping it.
POPUP_POSITION_LOCK_SECONDS = 2.0
# Floor on how long a flow-through popup is willing to sit queued for one
# of MAX_CONCURRENT_FLOW_POPUPS's display slots (see
# _composite_baked_popups) before giving up and never appearing at all.
# This used to be exactly the popup's OWN display duration
# (leg_display_seconds — itself floored short for a tightly-clustered
# waypoint, since it's based on how soon the NEXT trigger follows) — for a
# real cluster of 4+ nearby waypoints, a popup could easily need to wait
# longer than its own short display time for one of only 3 concurrent
# slots to free up, and be dropped having never been shown even though
# the traveler had genuinely reached it. The wait budget is now the
# LARGER of that and this floor, so a short-duration popup still gets a
# real chance at a slot; still bounded (not infinite) so a popup doesn't
# finally appear absurdly long after the traveler has moved on.
POPUP_MIN_WAIT_SECONDS = 6.0
# Hard floor on how long any popup card stays on screen once it appears,
# whatever its own leg's pacing worked out to. A leg between two stops a
# few metres apart can compute a display time of well under a second, which
# is long enough to draw the eye but not to actually read the place name —
# the card registers only as a flicker. Enforced centrally in
# _make_baked_popup (the one place a display duration becomes frames), so
# it holds for every caller rather than each having to remember its own
# floor. Covers the whole on-screen life including the fade in/out.
POPUP_MIN_DISPLAY_SECONDS = 2.0
# How long each UNCONNECTED stop-by's card is held during the batch shown
# at the previous normal waypoint's stop (see overview_animation.py's
# _play_stopby_batch). Per-card, not split across the group: a run of four
# landmarks holds that stop for four times this, rather than flashing each
# one by in a quarter of the time. Deliberately BELOW the general
# POPUP_MIN_DISPLAY_SECONDS floor (2.0s) - the batch calls now pass
# min_display_seconds=STOPBY_BATCH_SECONDS explicitly to _make_baked_popup
# so this value actually takes effect instead of being clamped back up to
# 2.0s. A quick pop-in/pop-out per card (rather than each one settling in
# for a full 2s read) is the intended feel here - the cards are landmarks
# merely passed, not stopped at; the narration only briefly names them
# (overview_script.py's via_batches), so a snappy "these exist" beat reads
# better than a leisurely one, and it keeps the cue-timing math (this
# value is also what overview.py's _hold_frames/start_batch reserve) from
# pushing later cued stops late to compensate for a long batch freeze.
STOPBY_BATCH_SECONDS = 0.5
# At most this many stop-bys in a group get their own held card (and count
# toward the extra hold time reserved before the next cued stop — see
# overview.py's _hold_frames/start_batch and route_brief.py's plan_budget).
# The narration only ever names up to 3 of them ("や"-joined, capped at
# names[:3] in overview_script.py's via_batches line) regardless of group
# size, so a bigger group held card-by-card at STOPBY_BATCH_SECONDS each
# made the video sit frozen well past when the voice had already moved on
# (5 stop-bys = 10s held, for a single ~3s spoken clause) — the retiming
# then had to shove every later cued stop's arrival back to compensate,
# reading as "arrives late". Any stop-by beyond this cap still gets its pin
# drawn (it WAS passed, the map should say so) but no card/extra hold time,
# same fallback already used when there's no free screen space for a card
# (see _play_stopby_batch).
STOPBY_BATCH_MAX_HELD = 4
# An overview waypoint card stays FULLY shown (after its fade-in, before its
# fade-out) at least this long, even when the walker has already reached the
# next waypoint: POPUP_MIN_DISPLAY_SECONDS counts the fades, which left a card
# passed on the way readable for barely half a second.
OVERVIEW_POPUP_MIN_HOLD_SECONDS = 2.0
# The overview walker stops this long at a "Connect to Route" stop-by (its
# card showing), like at a real stop. It has no narration cue of its own.
OVERVIEW_CONNECTED_STOPBY_HOLD_SECONDS = 2.0
# Overview map padding, scaled to how physically big the route actually is
# (bounding-box diagonal, in km) - a flat percentage padding looks right at
# one scale and wrong at another: 10% margin around a route that spans 40km
# is a lot of genuinely useful breathing room, but the same 10% around a
# route that spans 800m is still a huge, mostly-empty gap with the pins
# clustered tiny in the middle. Smaller routes get a tighter (more zoomed-in)
# crop; bigger ones get more room so nearby pins/labels don't crowd the
# frame edge. (span_km ceiling, padding_factor) pairs, checked in order -
# the first ceiling the route's own span fits under wins.
# TileDownloader._optimal_zoom_for_span rounds the padded span's zoom UP to
# the nearest WHOLE level (never down), and zoom is log2-scaled - so most
# padding changes land inside the same whole level and change nothing
# visible; only enough padding to push past the NEXT level's threshold
# changes the fetched crop at all, and that jump is a big, discrete step
# (confirmed on this project's own route, span ~7.5km: 0.05-0.50 all stayed
# at zoom 13 - identical crop; 0.70 dropped to zoom 12 - roughly 2x the
# area, at which point the card layout (built for the tighter crop) started
# overlapping/crowding, so that's a real regression, not just "more
# zoomed out"). Kept modest for now, matching zoom 13 on that route -
# raise a tier past its own threshold only once the card layout can also
# handle the wider crop it produces.
OVERVIEW_PADDING_BY_SPAN_KM: Tuple[Tuple[float, float], ...] = (
    (1.5, 0.10),
    (5.0, 0.15),
    (15.0, 0.20),
    (40.0, 0.25),
)
# Above the largest span_km ceiling in OVERVIEW_PADDING_BY_SPAN_KM.
OVERVIEW_PADDING_MAX_SPAN = 0.25
# Overview: the walker takes at least this long from one numbered stop to the
# next, however close they are (stops a few hundred metres apart used to flash
# past in a fraction of a second, their cards all popping up at once). The
# overview script gives each passed leg about as long (WAY_SECONDS_PER_LEG).
OVERVIEW_MIN_LEG_SECONDS = 2.0
# Overview: a pin the walker reaches pops in - grows from its tip with a slight
# overshoot over this long - instead of appearing all at once.
PIN_POP_SECONDS = 0.35
# pydeck residential legs: every frame is a headless-Chromium screenshot piped
# into ffmpeg. JPEG at this quality instead of PNG - a 1080p PNG encode was the
# slowest part of each frame, and the video is re-encoded to H.264 anyway.
LEG_FRAME_JPEG_QUALITY = 92
# Beside-the-pin cards (overview flow-through, intro, stop-by batches) are
# placed as close round their pin as they fit, so the leader line stays short:
# candidate spots in this many directions, out to this far (px); a spot on the
# far side of the pin from its side of the frame counts this much longer. Only
# when nothing fits that close does the wider side-of-frame search run.
POPUP_NEAR_DIRECTIONS = 16
POPUP_NEAR_MAX_LEADER_PX = 200
POPUP_NEAR_OFF_SIDE_PX = 40
# Shown in the overview's bottom-left while the FIRST stop-by cards play: a
# ribbon title and a card saying those round markers are optional extras.
# Wording per language: assets/config/labels_<lang>.json (these are the Japanese ones).
STOPBY_NOTICE_TITLE = LABELS_JA["stopby_notice_title"]
# Line breaks are kept (a long line still wraps to the card).
STOPBY_NOTICE_BODY = LABELS_JA["stopby_notice_body"]
STOPBY_NOTICE_RIBBON_COLOR: Tuple[int, int, int] = (40, 110, 220)  # BGR, warm orange ribbon
STOPBY_NOTICE_FADE_SECONDS = 0.6
# How long the notice stays up when the first stop-by reached isn't a batch
# (a connected / skipped one); a batch keeps it for the batch's own length.
STOPBY_NOTICE_SECONDS = 5.0
# Shortest time the notice is fully shown, fades excluded (a 0.5s batch was unreadable).
STOPBY_NOTICE_MIN_READ_SECONDS = 2.5
# Hard ceiling on a waypoint's own "freeze_seconds" (job_config's per-stop
# override for how long its popup photo is held/displayed) — applied
# wherever that raw job_config value is first read, so every downstream
# consumer (the overview's flow-through/frozen popups, the residential
# per-leg arrival pause, the fullscreen photo transition's hold) is
# automatically bounded without each one needing its own cap. Doesn't
# touch the various built-in DEFAULT values used when a waypoint doesn't
# set freeze_seconds at all — those are already <= this ceiling.
POPUP_FREEZE_SECONDS_MAX = 1.0
# How long a residential leg's AT-ARRIVAL destination photo is held once it
# has grown to fullscreen (see pedestrian.py's _play_leg_photo_card
# cut_after path). Deliberately below POPUP_MIN_DISPLAY_SECONDS — and so
# exempt from that floor — because this one isn't a card to be read: the
# photo has already been on screen, growing, for most of a second before
# this hold begins, and the clip hard-cuts the instant the hold ends, so a
# full 2-3s freeze on a still image just stalls the cut.
RESIDENTIAL_ARRIVAL_POPUP_HOLD_SECONDS = 1.0
# How long a residential leg holds on the plain arrived map (walker gone,
# destination pin + HUD card showing the leg's own total distance/time)
# BEFORE the at-arrival photo starts its pop-in -- without this the photo
# began growing the instant the walker stopped moving, cutting straight
# from "still walking" to "photo" with no beat to actually register having
# arrived.
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
# Drives services/vdoprocessing/comfyui_i2v_client.py. Bundled ComfyUI lives
# at src-python/bin/ComfyUI with its own venv + ComfyUI-GGUF node already
# installed. Port is deliberately NOT ComfyUI's common default (8188) so this
# bundled instance never collides with a developer's own separately-running
# ComfyUI on the same machine.
COMFYUI_BASE_URL = "http://127.0.0.1:8189"
# "5b": Wan2.2-TI2V-5B-Turbo, one model (below).
# "a14b": Wan2.2-I2V-A14B high + low noise experts with the Lightx2v 4-step
#   LoRAs. Best motion, but it fills 32 GB of RAM, invented a cyclist at CFG 1,
#   and the PC hit HYPERVISOR_ERROR during its test (2026-10-01).
# "fun_camera": Wan2.1 Fun Camera 1.3B. Fits in 8 GB and moves exactly as the
#   preset says, but at 480p it smears small text (kanji signs) - rejected
#   2026-10-01. Its camera move comes from COMFYUI_FUN_CAMERA_POSES.
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
# A14B files (QuantStack GGUFs + Comfy-Org repackaged LoRAs/VAE), same
# exact-filename rule as COMFYUI_UNET_NAME. Q3_K_S (~6.5 GB each) is the
# quant most likely to stay in VRAM; Q4_K_M (~9.7 GB) always offloads.
COMFYUI_A14B_HIGH_UNET_NAME = "Wan2.2-I2V-A14B-HighNoise-Q3_K_S.gguf"
COMFYUI_A14B_LOW_UNET_NAME = "Wan2.2-I2V-A14B-LowNoise-Q3_K_S.gguf"
COMFYUI_A14B_HIGH_LORA_NAME = "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors"
COMFYUI_A14B_LOW_LORA_NAME = "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors"
# The step the high-noise expert hands over to the low-noise one (of
# COMFYUI_STEPS), as in ComfyUI's own "Wan 2.2 14B I2V" template.
COMFYUI_A14B_SPLIT_STEP = 2
# Passed to ComfyUI as --reserve-vram (GB) when set: it then loads only what
# fits and streams the rest from RAM itself, rather than overcommitting into
# Windows shared GPU memory.
COMFYUI_RESERVE_VRAM_GB: Optional[float] = None
# From huggingface.co/hum-ma/Wan2.2-TI2V-5B-Turbo-GGUF, placed in
# bin/ComfyUI/models/diffusion_models. Must be the exact filename there: a
# name ComfyUI doesn't have makes it reject every clip, and the attraction
# step then silently falls back to plain pan/zoom for all of them.
COMFYUI_UNET_NAME = "Wan2_2-TI2V-5B-Turbo-Q4_K_M.gguf"
# Attraction clips are decoded with ComfyUI's VAEDecodeTiled: frames in
# spatial tiles of this many px (with this overlap) and this many frames at a
# time. A single full-size decode doesn't fit in 8 GB of VRAM next to the Wan
# model and crawls in system RAM instead.
COMFYUI_VAE_TILE_SIZE = 512
COMFYUI_VAE_TILE_OVERLAP = 64
COMFYUI_VAE_TEMPORAL_SIZE = 32
# 16, not 8: at 8 each new frame chunk decoded brighter (steps at frames
# 24/48/72); 16 blends them away for ~+0.5 GB VRAM (peak still 7.2 GB).
COMFYUI_VAE_TEMPORAL_OVERLAP = 16
COMFYUI_CLIP_NAME = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
COMFYUI_VAE_NAME = "wan2.2_vae.safetensors"
# 1280x704 fits comfortably in an 8GB VRAM budget at this quant (see
# img2vdo.py's _TARGET_WIDTH/_TARGET_HEIGHT comment — upscaled to 1920x1080
# after generation to match the rest of the pipeline's clips).
COMFYUI_WIDTH = 1280
COMFYUI_HEIGHT = 704
# Share trimmed off each edge of the photo before Wan sees it: things cut off
# at the edge (a red banner) were "completed" into big invented signs.
COMFYUI_INPUT_EDGE_CROP = 0.05
COMFYUI_FPS = 24
# Turbo-model recommended settings (see the model card): 4 steps, euler/simple.
# CFG is 2.0, not the card's 1.0: at CFG 1 ComfyUI skips the negative prompt
# entirely, so none of COMFYUI_NEGATIVE_PROMPT applied and Wan freely added
# vehicles, people and hand-held props to scenery. Above 1 each step runs the
# model twice (~+40s per segment).
COMFYUI_STEPS = 4
COMFYUI_CFG = 2.0
COMFYUI_SAMPLER = "euler"
COMFYUI_SCHEDULER = "simple"
COMFYUI_MODEL_SHIFT = 8.0
# Wan wants frame counts of the form 4k+1; clamp generated length into a
# sane range so a very long/short narration duration can't request a
# pathological (near-zero or excessively slow) clip.
#
# Lowered from the template's own default (121, ~5s) — on an 8GB card, Wan
# already runs "loaded partially" (VRAM offloading mid-model) even at this
# resolution, and generation was crashing mid-sampling (a native runtime
# abort, not a clean Python exception) roughly 10-14 minutes in, consistent
# with VRAM exhaustion under sustained pressure across a longer sequence of
# frames. A shorter clip needs less peak VRAM for the video latent across
# the whole sampling run. If crashes persist even at this length, the next
# lever is COMFYUI_WIDTH/HEIGHT (lower resolution), not step count (the
# Turbo checkpoint is distilled specifically for 4 steps).
COMFYUI_MIN_FRAMES = 25  # ~1s @ 24fps
COMFYUI_MAX_FRAMES = 89  # ~3.7s @ 24fps (was 121 ~5s, then 65 ~2.7s — middle ground)
# The rate Wan generates at. COMFYUI_FPS is the rate its clips come out at;
# a lower one is resampled up in comfyui_i2v_client._join_segments.
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
# Sequential extension: when a narration outlasts one COMFYUI_MAX_FRAMES
# segment, the attraction clip is built from more segments, each one started
# from the previous segment's last frame (so the motion carries on instead of
# the last frame freezing) - see COMFYUI_CHAIN_LAST_FRAME below for how they
# are actually chained. 5 (the user's choice): at most 5 segments per photo
# (~18.5s of Wan, ~13 min GPU); a longer narration share is filled by
# slow_move.py's zoom-out after that. None chains to the whole narration
# (6 segments took ~17 min for one 22s narration); 1 turns extension off.
# Before last-frame chaining this drifted badly past 2 segments (segments
# only saw the previous last frame, not the photo, so changes compounded - 4
# segments turned a painted wall into a van driving in); last-frame chaining
# colour-matches the handed-on frame back to the photo every time
# (COMFYUI_CHAIN_COLOR_MATCH), which is what makes chaining to full length
# safe to leave uncapped.
COMFYUI_EXTEND_MAX_SEGMENTS: Optional[int] = 5
if COMFYUI_MODEL == "a14b":
    # A14B segments are far slower; 2 (~10s of Wan) until it's benchmarked.
    COMFYUI_EXTEND_MAX_SEGMENTS = 2
# HOW the segments are chained.
# True ("last frame" chaining): each segment is its own ComfyUI job, started
# from a real PNG of the previous segment's last frame - so that frame can be
# colour-matched back to the photo BEFORE it is handed on
# (COMFYUI_CHAIN_COLOR_MATCH), which stops Wan's grading compounding from one
# segment into the next, and each segment can carry its own prompt and be
# re-rolled on its own. The segments are joined with ffmpeg, each one after
# the first losing its opening frame (a re-render of the frame it started
# from).
# False: the old single graph, every segment unrolled into it, chained on the
# decoded tensor. One job (the model is never reloaded, so it is faster), but
# the drift carries straight through and every segment shares one prompt.
COMFYUI_CHAIN_LAST_FRAME = True
# Colour-match a chained frame to the photo before the next segment starts
# from it (see color_match.py, the same pass the finished clip gets).
COMFYUI_CHAIN_COLOR_MATCH = True
# With an uncapped chain (COMFYUI_EXTEND_MAX_SEGMENTS = None) the clip reaches
# the narration's end on its own, so slow_move.py's tail is skipped and a
# small gap gets the plain last-frame freeze. With a cap, a gap over 1s left
# by the cap is still filled by slow_move. False: slow_move fills any gap
# over 1s regardless.
ATTRACTION_CHAIN_TO_FULL_LENGTH = True
# After the Wan motion runs out, a moving preset's clip continues as a slow
# push-in/drift over its last frame (vdoprocessing/slow_move.py) instead of
# freezing, in a random direction per clip: the frame grows by about this
# fraction per second (0.012 = +1.2%/s, ~10% over an 8s gap; each clip
# randomises it by +/-25%). The "none" preset stays a still photo.
ATTRACTION_SLOW_MOVE_ZOOM_PER_SEC = 0.012
# How that remaining time moves, WHEN there is any left to fill this way -
# with ATTRACTION_CHAIN_TO_FULL_LENGTH on (the default), Wan chains all the
# way to the narration's end and this tail is never reached; it only applies
# with that switch off, or when COMFYUI_EXTEND_MAX_SEGMENTS caps the chain
# short of the narration. "zoomout" eases slowly back out to the full
# picture, centred, ending right as the narration ends; to have picture to
# zoom out into, the whole clip is shown zoomed in by that same amount (never
# more than ATTRACTION_SLOW_MOVE_MAX_ZOOM_OUT), so the join doesn't jump.
# "drift" is the earlier slow push-in in a random direction.
ATTRACTION_SLOW_MOVE_STYLE = "zoomout"
ATTRACTION_SLOW_MOVE_MAX_ZOOM_OUT = 0.12
# Wan grades its clips (contrast, saturation and brightness climb, and jump
# again at each extension segment), so every Wan clip gets its colours pulled
# back to its photo afterwards (vdoprocessing/color_match.py): each frame's
# LAB mean and spread matched to the photo's, at this strength (1.0 = fully),
# with the correction averaged over this many seconds so it can't flicker.
ATTRACTION_COLOR_MATCH = True
ATTRACTION_COLOR_MATCH_STRENGTH = 1.0
# 0.25, not 1.0: a 1 s window couldn't follow Wan's ~0.5 s exposure ramp or the
# VAE decode's chunk steps (every 24 frames), leaving a visible brightness wave.
ATTRACTION_COLOR_MATCH_SMOOTH_SECONDS = 0.25
# Wan2.2's standard (Chinese) negative prompt, then additions:
# - no duplicated props: duplicated/repeated objects, copy-pasted or mirrored
#   elements, the same object appearing twice, cloned people, objects
#   appearing from or vanishing into nothing, objects melting into each other,
#   extra objects, warped buildings/structures, wrong perspective, new
#   vehicles, objects entering the frame, scene content changing, fast
#   motion, camera shake;
# - scenery only: people, figures, pedestrians, crowds, tourists, passers-by,
#   walking or appearing people (attraction clips never show people);
# - scenery only: foreground objects, objects in front of the lens, first-
#   person view, hands, hand-held objects, toys, weapons, objects entering
#   from the frame edge, anything blocking the view (a toy-like gadget rose
#   into a street shot from the bottom edge), and the camera operator's
#   shadow or new shadows creeping into the frame (a dark shadow grew at the
#   bottom of a 石標 clip);
# - no colour grading: colour grading, filters, oversaturation, too much
#   contrast, colour casts, vignetting, HDR look, blown highlights,
#   brightness/colour/lighting changing, flashing (a 石標 clip went from the
#   photo's natural colours to a punchy graded look, brighter again in its
#   second segment - color_match.py also corrects this afterwards);
# - no warping: warped/garbled/morphing text, deformed or changing signs,
#   road signs and signboards, bent straight lines, wavy/rubbery surfaces,
#   jelly/rolling-shutter wobble, fisheye or lens distortion, objects changing
#   shape (the 石標 clip's road-sign arrow bent into a different symbol);
# - cinematic realism: cartoon, anime, CG/3D render look, plastic texture,
#   painting, over-sharpened, flicker, unnatural motion, morphing scenery.
# - one of Wan's anti-static terms (静止不动的画面): without it the 5B barely
#   moved; all four (静态, 静止, 画面静止 too) made it orbit wildly (2026-10-02);
# - no orbit/truck/rotation/big moves, and nothing invented at the frame edge
#   (a cut-off red banner grew into a big disc sign);
# - subtitles, watermarks;
# - body parts / POV (feet, toes, legs, shoes, fingers, arms): walk-in shots
#   invite the walker's own feet and hands into frame.
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
# Motion-first (Wan's I2V guide): the photo decides how things look, the
# prompt only says what moves - the camera, in film terms, plus gentle ambient
# motion. Nothing unwanted is named here (T5 ignores "no", so "no people"
# primes people); that all lives in COMFYUI_NEGATIVE_PROMPT. No "fixed",
# "locked" or "same throughout" either - those read as "don't move".
# Constant speed, no ease: chained segments would stutter at each seam.
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


# Keys: the editor's presets normalised (vdoprocessing/camera_pan.py). "none"
# never reaches Wan (a still photo, img2vdo._generate_single_clip); it is the
# default for a waypoint with no preset.
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
# Presets listed here are made by LTXV-13B 0.9.8 distilled (Q3_K_M GGUF) between
# two real crops of the photo - first and last frame pinned, so it can't wander
# or invent - instead of ATTRACTION_GENERATOR. "panright" is the user's approved
# test 13 on 西ノ庄駅 (2026-10-02): smooth level pan, sign readable, ~2 min.
# How the editor's Dolly In / Dolly Out (zoomin/zoomout) are made:
# "ltxv" (2026-10-07, user's choice) = LTXV dolly between pinned crops like the pans;
# "dolly" = 3D-photo dolly over the real photo (parallax_generator, CPU);
# "jumpcut" = vdoprocessing/jump_cut.py (its AI wide invented a second vending
# machine, a watermark and a gate roof, 2026-10-07).
ATTRACTION_ZOOM_STYLE = "ltxv"
_ZOOM_PRESETS: Tuple[str, ...] = ("zoomin", "zoomout")
ATTRACTION_LTX_PRESETS: Tuple[str, ...] = ("panright", "panleft", "panup", "pandown", "walkin") + (
    _ZOOM_PRESETS if ATTRACTION_ZOOM_STYLE == "ltxv" else ()
)
# Jump cut: wide, then a hard cut to a centred punch-in showing JUMP_CUT_TIGHT of
# the frame, at JUMP_CUT_AT of the clip (reversed for zoomout). Held, never drifted.
ATTRACTION_JUMP_CUT_PRESETS: Tuple[str, ...] = () if ATTRACTION_ZOOM_STYLE == "ltxv" else _ZOOM_PRESETS
ATTRACTION_JUMP_CUT_TIGHT = 0.65
ATTRACTION_JUMP_CUT_AT = 0.5
# AI wide shot (jump cut, and the "walkai" walk's first frame): the real photo at
# JUMP_CUT_TIGHT in the middle, the ring around it outpainted by SDXL (GPU).
# False, or any outpaint failure = a crop of the photo itself.
ATTRACTION_AI_SURROUNDINGS = True
ATTRACTION_JUMP_CUT_AI_SIZE = (1344, 768)
ATTRACTION_JUMP_CUT_AI_STRENGTH = 0.9
ATTRACTION_JUMP_CUT_AI_FEATHER = 16
# After the chosen move, a second, closer shot of the same photo joined by a
# dissolve - like the Tomogashima reference (one photo, several angles).
# "random": a move from ATTRACTION_SECOND_SHOT_MOVES, picked per photo (seeded
# by its content, so a rerun picks the same) and never the first shot's
# direction. "auto": picked from the same list by what the photo shows
# (move_picker: depth + saliency on the CPU; seascape -> pan along the
# horizon, path/gate -> walk in, central subject -> close in), random if the
# photo can't be measured. A move name fixes it; None = the chosen move only.
ATTRACTION_SECOND_SHOT: Optional[str] = "auto"
# No walkthrough: unpinned, it invented a whole plaza at 札立山 (2026-10-06).
ATTRACTION_SECOND_SHOT_MOVES: Tuple[str, ...] = (
    "closein", "closeout", "closepanleft", "closepanright", "closepanup", "closepandown",
)
# The second shot is skipped when its close crop spans fewer real pixels of the
# original (pre-upscale) photo than this: 2026-10-06, 485 px was sharp, <=352 smeared.
ATTRACTION_SECOND_SHOT_MIN_SOURCE_PX = 400
# Moves with no pinned last frame: LTXV starts from the whole photo and
# generates the walk into the place itself (it may show what the photo doesn't).
# The editor's "Walk In" preset is one of them. "walkai" starts from the AI wide
# shot instead (2026-10-06: pinned to the photo as last frame, it didn't walk).
LTXV_FREE_MOVES: Tuple[str, ...] = ("walkthrough", "walkthroughleft", "walkthroughright", "walkin", "walkai")
# A free move chosen in the editor is rendered as this pinned move instead
# (2026-10-06: unpinned walks invented scenery; "zoomin" read as no walk at all).
# None = the free walk. None again 2026-10-07: the pinned walk only zoomed; the
# user wants the free POV walk of test23 (0:04-0:07), slower.
LTXV_FREE_MOVE_FALLBACK: Optional[str] = None
# The pinned walk becomes this when its tight crop spans fewer original-photo
# pixels than ATTRACTION_SECOND_SHOT_MIN_SOURCE_PX. "walkai" = from the AI wide
# shot into the real photo full frame (free walk from the whole photo if the outpaint fails);
# "walkshort" = zoomin's crops
# with the walking prompt (no softer than the zoom).
LTXV_SMALL_PHOTO_WALK_FALLBACK = "walkai"
# How "walkai" is rendered: "parallax" = a 3D-photo POV walk over the AI wide
# shot (CPU, always moves forward); "ltxv" = LTXV unpinned (2026-10-06: it
# only tilted and drifted, never really walked).
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
LTXV_FRAMES = 97  # 8k+1, ~4 s
LTXV_FPS = 24
LTXV_SIGMAS = "1.0, 0.9937, 0.9875, 0.9812, 0.975, 0.9094, 0.725, 0.4219, 0.0"  # distilled, CFG 1
# Decode in time chunks of this many frames: one chunk for the whole clip.
# 32 (overlap 8) left a visible hitch at every seam - each second, frames
# 24/48/72 (test 13, 2026-10-02). The decode runs alone in a fresh server.
LTXV_DECODE_TEMPORAL_SIZE = 128
LTXV_DECODE_TEMPORAL_OVERLAP = 8
# How firmly the last frame is pinned (1.0 = exact copy).
LTXV_GUIDE_STRENGTH = 0.8
# Keyframe crops (shares of the widest 16:9 window that fits the photo). Pans
# slide a CROP_WIDTH window from one edge to the other; zooms go from ZOOM_WIDE
# to ZOOM_TIGHT around the middle; the second shot pushes in from CLOSE_WIDE to
# CLOSE_TIGHT around the middle (55% -> 46% of a 1920 px photo in test 16).
LTXV_CROP_WIDTH = 0.85
LTXV_ZOOM_WIDE = 1.0
LTXV_ZOOM_TIGHT = 0.8
LTXV_CLOSE_WIDE = 0.55
LTXV_CLOSE_TIGHT = 0.46
# Close pans: a CLOSE_WIDE window moved this share of the widest window's
# width (or height, for tilts) across the middle.
LTXV_CLOSE_PAN = 0.18
# Walk-in second shots: CLOSE_WIDE at the middle -> WALK_TIGHT, its end moved
# WALK_TURN of the widest window's width sideways for walkfwdleft/right.
LTXV_WALK_TIGHT = 0.38
LTXV_WALK_TURN = 0.12
# The pinned walk ends framed on the photo's largest sign (OCR) instead of the middle.
LTXV_WALK_TO_SIGN = True
# Moves whose two pinned keyframes are 3D-photo views (parallax_generator) rather
# than flat crops: two crops of one photo are a flat slide, so LTXV made the
# walk-and-pan prompts a flat slide too (depth score 0.01 vs 0.56, 2026-10-07).
# Pans: the camera steps DEPTH_TRUCK sideways (nearest things; far ones
# PARALLAX_FAR_WEIGHT of it) while turning DEPTH_PAN; dollies travel DEPTH_DOLLY.
LTXV_DEPTH_KEYFRAMES: Tuple[str, ...] = ("panleft", "panright", "zoomin", "zoomout")
# Walk In, if added to LTXV_DEPTH_KEYFRAMES: a free POV walk softly pinned
# (ANCHOR_STRENGTH) to a 3D view ANCHOR_DOLLY forward. Tried 2026-10-07 after the
# unanchored 八王子峠 walk invented a corridor: LTXV then held still ~3 s and
# jumped to the anchor (西ノ庄駅) - no walk. Off; the corridor came from the
# "entrance ... passes inside" wording, now gone from the walk prompt.
LTXV_WALK_ANCHOR_DOLLY = 0.5
LTXV_WALK_ANCHOR_STRENGTH = 0.5
LTXV_DEPTH_TRUCK = 0.10
LTXV_DEPTH_PAN = 0.06
LTXV_DEPTH_DOLLY = 0.30
# In-between 3D views pinned at even spacing: with only the two ends pinned
# LTXV covered the whole pan in the first half, then stood still (2026-10-07).
LTXV_DEPTH_MID_GUIDES = 2
LTXV_MID_GUIDE_STRENGTH = 0.6
# A job takes ~15 GB of RAM on top of what's in use: below this much free it
# waits (tuning.ensure_free_ram), then falls back to the 3D photo.
LTXV_MIN_FREE_RAM_GB = 15.0
# Each attraction photo (and its sign lock) is made in its own child process
# (vdoprocessing/clip_worker.py): all it loaded goes back to Windows when it ends.
ATTRACTION_CLIP_IN_CHILD = True
# How long a shot waits for that RAM (the server is stopped first) before
# giving up; generous, since giving up means a non-LTX clip.
LTXV_RAM_WAIT_SECONDS = 900.0
# A failed LTXV clip is tried this many times (fresh server each) before the
# CPU 3D photo, the last resort so a stop is never left without a clip.
LTXV_CLIP_ATTEMPTS = 2
# CFG 1: the negative is ignored, so everything is said positively.
_LTXV_STILL = (
    "The scene is still and solid and only the camera moves, steadily and slowly. The light, weather and colours stay "
    "exactly as in the photo; realistic travel documentary footage, sharp detail."
)
# "Gimbal carried", never "first-person": that invites the walker's feet/hands.
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
    # 2026-10-07: walk-and-pan, the camera travelling the way it turns.
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
    # Camera-only words: "walks" drew a person into frame (test 22, 2026-10-05).
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
# test23's walkthrough said "toward the entrance ... passes inside": fine at a
# station, an invented building in a forest.
LTXV_PROMPTS["walkin"] = (
    "Point-of-view camera at eye height moving continuously straight forward through {place}, "
    "steadily ahead along the way in front, getting closer and closer to what lies ahead." + _LTXV_POV_END
)
# The free walk is played up to this many times slower (only as much as its
# narration share needs), frames in between made by
# motion interpolation: test23 (the user's reference) pushed in ~29% scale a
# second, 1.6x gives ~20%. A "slowly" prompt instead barely moved (2026-10-07).
LTXV_WALK_SLOWDOWN = 1.6
# A free walk is cut where it leaves the photo (clip_qc.scene_lost_frame: fewer
# epipolar inliers than max(MIN_INLIERS, MIN_SHARE of the first frame's)). Less
# than MIN_SECONDS kept: rendered again with a new seed, up to ATTEMPTS times,
# then the 3D-photo move.
LTXV_WALK_QC_MIN_INLIERS = 10
LTXV_WALK_QC_MIN_SHARE = 0.03
# ... or where over this share of the frame lies past the photo's edge on two
# checks running (a walk only ever sees less of the photo).
LTXV_WALK_QC_MAX_OUTSIDE = 0.20
# ... and a walk that pushes forward less than this (clip_qc.forward_push, %)
# is rendered again: unpinned, LTXV sometimes just stands still (猿坂峠 ~2).
LTXV_WALK_MIN_PUSH = 20.0
LTXV_WALK_MIN_SECONDS = 2.0
LTXV_WALK_ATTEMPTS = 2
# After every attempt fails: this LTXV move instead (3D keyframes, stays in the
# photo), never the CPU 3D photo - the user wants every picture made by LTX.
LTXV_WALK_FAILED_FALLBACK = "zoomin"
LTXV_PROMPTS["walkshort"] = LTXV_PROMPTS["walkfwd"]
# Unpinned, the gentle walkfwd wording only drifted (2026-10-06, 孝子駅).
LTXV_PROMPTS["walkai"] = (
    "Point-of-view camera at eye height moving continuously straight forward through {place}, "
    "walking steadily ahead and getting closer and closer to what lies in front." + _LTXV_POV_END
)
# Second shot as a walk inside the place: "walk" = a prompt from
# LTXV_WALK_PROMPTS (picked per photo, seeded like the move); None = LTXV_PROMPTS.
# None since 2026-10-06: the walk prompts zoomed during pans and added a visitor at 高仙寺.
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
# Video models redraw kanji as kanji-like shapes, so the photo's own sign
# pixels are tracked into every LTXV frame and pasted back.
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
# "shots": Wan shots from the original photo, each cut where QC finds it going
#   bad, then a depth-parallax move over the real photo for the rest.
# "parallax": the parallax move only (no Wan, no GPU).
# "chain": the old last-frame chained Wan segments.
ATTRACTION_GENERATOR = "shots"
# Moves for shots 1..N, each from the original photo; "preset" = the editor's.
ATTRACTION_SHOT_MOVES: List[str] = ["preset", "walkin", "dollyback"]
ATTRACTION_MAX_WAN_SHOTS = 3
# A shot with less clean footage than this is dropped.
ATTRACTION_MIN_SHOT_SECONDS = 1.0
# Before each hard cut the last this-many seconds of the shot ease to a stop
# (played over twice as long), then the frame holds briefly.
ATTRACTION_SHOT_SETTLE_SECONDS = 0.5
ATTRACTION_SHOT_HOLD_SECONDS = 0.25
# Cut this many frames before the first bad one (QC lags the eye slightly).
ATTRACTION_QC_BACKOFF_FRAMES = 3
# QC (vdoprocessing/clip_qc.py): 32 px patches (frame at 640 wide) looked up in
# the photo near where the camera model puts them. Calibrated 2026-10-02 on two
# 西ノ庄駅 clips whose cut-off red banner grew into an invented sign from the
# frame edge (visibly by frame 6-9, 3-4 bad patches) against a clean digital
# push-in and real depth parallax (0 bad patches).
ATTRACTION_QC_MAX_BAD_FRACTION = 0.12
ATTRACTION_QC_MAX_BAD_CLUSTER = 3
# Share of the frame showing what's outside the photo (necessarily invented);
# moves that reveal (pans, pull-backs) get the looser cap.
ATTRACTION_QC_MAX_OUTSIDE = 0.15
ATTRACTION_QC_MAX_OUTSIDE_REVEAL = 0.35
# Cinematic 3D photo (vdoprocessing/parallax_generator.py): Depth-Anything-V2
# Small on this device ("cpu" keeps the GPU out of it), the photo split into
# LAYERS by depth. Motion is given for the nearest things; the farthest move
# FAR_WEIGHT of that. Pans truck PAN of the frame (plus a PAN_PUSH dolly-in),
# zooms dolly ZOOM with an ARC sideways drift.
PARALLAX_DEPTH_MODEL = "depth-anything/Depth-Anything-V2-Small-hf"
PARALLAX_DEVICE = "cpu"
# What a moving foreground uncovers is filled by LaMa (big-lama TorchScript, CPU,
# ~5 s per photo; continues the surrounding texture rather than inventing
# objects), saved in bin/ComfyUI/models/inpaint and downloaded on first use.
# Without it (offline, bad checksum) OpenCV's Telea fill is used, which smears.
PARALLAX_LAMA = {
    "file": "big-lama.pt",
    "url": "https://github.com/enesmsahin/simple-lama-inpainting/releases/download/v0.1.0/big-lama.pt",
    "sha256": "7ba7aa7ac37a4d41fdbbeba3a2af7ead18058552997e3a3cd1a3b2210c9e6b4c",
}
PARALLAX_LAMA_MAX_SIDE = 1824
# 2 layers split at the foreground/background break: 3 quantile layers tore a
# pole between layers and ghosted it (2026-10-02).
PARALLAX_LAYERS = 2
PARALLAX_PAN = 0.08
PARALLAX_PAN_PUSH = 0.04
PARALLAX_ZOOM = 0.16
PARALLAX_ARC = 0.015
# POV walk ("walk"): dolly forward as extra scale for the nearest things, a
# step dip (share of frame height), a sway every two steps (share of width),
# and a head roll in degrees.
PARALLAX_WALK_DOLLY = 0.6
PARALLAX_WALK_STEPS_PER_SEC = 1.8
PARALLAX_WALK_BOB = 0.008
PARALLAX_WALK_SWAY = 0.006
PARALLAX_WALK_ROLL_DEG = 0.5
PARALLAX_FAR_WEIGHT = 0.3
# Film finish: motion blur sub-frames per frame, focus-pull blur (px sigma at
# 1080p for things far from focus; 0 = off - starting on the foreground left
# the station soft for the first second), corner darkening, grain (0-255 std).
PARALLAX_MOTION_BLUR_SAMPLES = 2
PARALLAX_DOF_SIGMA = 0.0
PARALLAX_VIGNETTE = 0.18
PARALLAX_GRAIN = 2.5
# How long the bundled server can sit unused before idle_watchdog.py shuts
# it down — mirrors IrodoriTTSClient's reasoning (10 min covers gaps between
# waypoints in one run without wasting VRAM/RAM long after the job ends).
COMFYUI_IDLE_TIMEOUT_SECONDS = 600.0
# Generous: first call after a cold start pays for node/import startup, and
# a Q6_K/8GB-class generation at up to 121 frames has taken up to ~15
# minutes in testing.
COMFYUI_SERVER_START_TIMEOUT_SECONDS = 180.0
COMFYUI_GENERATION_TIMEOUT_SECONDS = 1200.0

# --- Waypoint photo upscale (pipeline stage before attraction videos) -------
# Photos smaller than MIN_W x MIN_H get an ESRGAN pass in the bundled ComfyUI
# so fullscreen pop-ups and Wan's input aren't soft. Off per project with
# settings.upscale_popup_images=false; never runs under skip_rich_media.
DEFAULT_UPSCALE_POPUP_IMAGES = True
# The model in use: a key of IMAGE_UPSCALE_MODELS, saved under that exact
# filename in bin/ComfyUI/models/upscale_models. Downloaded on first use if
# missing (sha256-checked); without it the stage resizes on the CPU.
# UltraMix Balanced: the UltraSharp author's milder blend; chosen over
# UltraSharp after comparing on a real 515 px web photo.
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
# The model's output is shrunk to this many times the input before the final
# fit to the frame (Lanczos does the rest). 2 keeps the model's sharpening
# but tones down the detail a 4x model invents. None keeps its full scale.
IMAGE_UPSCALE_KEEP_SCALE = 2
IMAGE_UPSCALE_DOWNLOAD_TIMEOUT_SECONDS = 600.0
IMAGE_UPSCALE_MIN_W = 1920
IMAGE_UPSCALE_MIN_H = 1080
# Input is shrunk to MAX_SIDE / scale first: bounds tiles, time and CPU RAM.
IMAGE_UPSCALE_MAX_SIDE = 3840
# ComfyUI reserves ~4.8 GB for a 4x model (512 px tiles); below this much
# free VRAM the photo is resized on the CPU instead, so an 8 GB card never
# spills into shared memory.
IMAGE_UPSCALE_MIN_FREE_VRAM_MB = 5500
IMAGE_UPSCALE_TIMEOUT_SECONDS = 300.0

# --- Intro clip (multi-image slideshow + centered project title) -----------
# A slideshow of INTRO_IMAGE_COUNT random waypoint images (a fresh pick
# every call), each with its own slow zoom-in, crossfaded into the next —
# see services/vdoprocessing/introclip.py.
INTRO_IMAGE_COUNT = 3
# Each picture's own on-screen time INCLUDING the crossfade overlap into/out
# of it — total intro length = COUNT*PER_IMAGE - (COUNT-1)*CROSSFADE.
INTRO_PER_IMAGE_SECONDS = 3.5
INTRO_CROSSFADE_SECONDS = 0.8
# The overview narration starts on the intro (settings.overview_voice_over_intro):
# its opening (up to {start}) plays over the photos, so the intro lasts
# INTRO_VOICE_LEAD_SECONDS (the fade from black) + the {start} cue, within
# MIN..MAX, using up to INTRO_MAX_IMAGE_COUNT photos.
DEFAULT_OVERVIEW_VOICE_OVER_INTRO = True
INTRO_VOICE_LEAD_SECONDS = 0.5
INTRO_MIN_SECONDS = 4.0
INTRO_MAX_SECONDS = 26.0
INTRO_MAX_IMAGE_COUNT = 5
# Font/outline are in intro pixels; scaled x1080/704 from the old 1280x704 intro to look the same.
# These are defaults; settings.intro_title_style / intro_subtitle_style override per project.
INTRO_TITLE_FONT_FAMILY = "Yu Gothic UI"
INTRO_TITLE_FONT_SIZE = 74
INTRO_TITLE_OUTLINE = 2
INTRO_TITLE_BOLD = True
INTRO_TITLE_COLOR: Tuple[int, int, int] = (255, 255, 255)
# Second line under the title (only drawn when a subtitle is set).
INTRO_SUBTITLE_FONT_FAMILY = "Yu Gothic UI"
INTRO_SUBTITLE_FONT_SIZE = 36
INTRO_SUBTITLE_OUTLINE = 0
INTRO_SUBTITLE_BOLD = True
INTRO_SUBTITLE_COLOR: Tuple[int, int, int] = (255, 255, 255)
# Small line above the title: where the walk is (settings.intro_location, e.g. "和歌山県 和歌山市").
INTRO_KICKER_FONT_FAMILY = "Yu Gothic UI"
INTRO_KICKER_FONT_SIZE = 30
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
# Ken Burns zoom-in: 1.0 = the widest cover-fit crop (whole frame), smaller
# = a tighter/more zoomed-in crop — see local_pan_generator.py's identical
# zoom<1-means-zoomed-in convention (_CAMERA_PAN_PRESETS' "zoomin"). Slower
# than a single-image intro would use, since each picture now gets more
# on-screen time before crossfading away.
INTRO_ZOOM_START = 1.0
INTRO_ZOOM_END = 0.88
# Fade to/from black at the very start/end of the WHOLE slideshow, so the
# intro doesn't hard-cut into the rest of the video.
INTRO_FADE_SECONDS = 0.5
# Darkens each source picture before the title is burned on top — plain
# multiply on pixel values (1.0 = untouched, 0.0 = black) so the white
# centered title stays readable over a bright/busy photo.
INTRO_IMAGE_DIM_FACTOR = 0.55
# The title text gets its OWN transition — a combined scale-up + fade-in
# (and the reverse on the way out), via ASS `\fad`/`\t`/`\fscx`/`\fscy`
# override tags — separate from the whole-frame fade above, and deliberately
# slower/more pronounced so it reads as a distinct "reveal", not just the
# background's own fade bleeding through the text.
INTRO_LABEL_FADE_SECONDS = 1.1
# Starting/ending scale (percent of normal size) the title pops in from /
# shrinks back to — 100 would be a plain fade with no scale motion.
INTRO_LABEL_SCALE_START_PCT = 65
# Subtitle enters this long after the title and leaves this long before it,
# with its own fade + rise instead of the title's scale pop.
INTRO_SUBTITLE_DELAY_SECONDS = 0.8
INTRO_SUBTITLE_FADE_SECONDS = 0.7
INTRO_SUBTITLE_RISE_PX = 28

# Spoken (and subtitled) after the last visited waypoint's attraction
# narration, so the video winds down before the outro instead of cutting
# off mid-thought. "" turns it off.
CLOSING_NARRATION = "お疲れ様でした。"

# --- Outro card grid (end-of-video "places visited" summary) ---------------
# A single composited frame (project title + a thumbnail grid of every
# waypoint with a popup image) held for a fixed duration as the closing
# clip — see services/vdoprocessing/outrocard.py.
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
# [HACK] [Config] BGR DEFAULT_MARKER_COLOR flipped to RGB for PIL compositing — keeps
# the outro's numbered badges the same blue as every other numbered pin (map pins,
# popup cards) instead of introducing a fourth color.
OUTRO_BADGE_COLOR: Tuple[int, int, int] = tuple(reversed(DEFAULT_MARKER_COLOR))
# Caps how many waypoint cards can appear before the grid gets illegibly
# small — a project with more attractions than this just shows the first
# OUTRO_MAX_CARDS in route order.
OUTRO_MAX_CARDS = 20
OUTRO_GRID_COLS_MAX = 5
OUTRO_CARD_MARGIN = 18
OUTRO_CARD_ASPECT = 4 / 3  # thumbnail width:height

# Outro style: "scroll" (the default) lays every waypoint card out three to a
# row under the title and slowly scrolls down the page, credits-style, until
# the last row; "grid" is the single held frame above. Overridable per project
# via job_config.json's settings.outro_style.
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
# Scroll speed in px per second, given for the 704-high outro canvas (scaled
# with the real frame size, then rounded to a whole number of px per frame),
# and the holds on the first screen and at the end. The page scrolls until
# every card has left the top of the screen, so the end hold is on the empty
# background.
OUTRO_SCROLL_SPEED_PX = 100
OUTRO_SCROLL_START_HOLD_SECONDS = 1.0
OUTRO_SCROLL_END_HOLD_SECONDS = 0.5
# Longest the scroll itself may take; a very long page scrolls faster instead.
OUTRO_SCROLL_MAX_SECONDS = 30.0
# Height of the soft fade at the top and bottom screen edges, so cards ease
# in and out of view instead of being cut by the frame edge.
OUTRO_SCROLL_EDGE_FADE_PX = 56
# With route info the scroll is a timeline instead of the photo grid: the
# title and a trip summary (held OUTRO_SUMMARY_HOLD_SECONDS to be read), then
# one card per leg (the destination's photo, its name, where the leg started,
# and mode/distance/time chips; route_brief's numbers, the same ones the
# narration speaks), ending on the last card.
# Off per project via settings.outro_route_info: false (back to the grid).
DEFAULT_OUTRO_ROUTE_INFO = True
OUTRO_ROUTE_FROM_TEMPLATE = LABELS_JA["outro_route_from"]
OUTRO_ROUTE_ROW_HEIGHT = 128
OUTRO_ROUTE_ROW_GAP = 16
OUTRO_ROUTE_NAME_FONT_SIZE = 24
OUTRO_ROUTE_FROM_FONT_SIZE = 15
OUTRO_ROUTE_DISTANCE_FONT_SIZE = 22
# Leg cards per row (together as wide as the summary), the gap between them,
# and the photo's width:height.
# The route page's title + subtitle use the intro's text and styles, at this
# fraction of the intro's size (the intro's title fills a whole screen).
OUTRO_HEADING_SCALE = 0.7
OUTRO_HEADING_LINE_GAP = 10  # px between title and subtitle
OUTRO_ROUTE_COLS = 2
OUTRO_ROUTE_COL_GAP = 16
OUTRO_ROUTE_THUMB_ASPECT = 1.0
OUTRO_LEG_FONT_SIZE = 16
OUTRO_SUMMARY_VALUE_FONT_SIZE = 30
OUTRO_PANEL_COLOR: Tuple[int, int, int] = (31, 42, 64)
OUTRO_CHIP_COLOR: Tuple[int, int, int] = (45, 58, 86)
OUTRO_ARROW_COLOR: Tuple[int, int, int] = (110, 120, 140)
OUTRO_SUMMARY_HOLD_SECONDS = 4.0
OUTRO_ROUTE_END_HOLD_SECONDS = 2.0
OUTRO_SUMMARY_LABELS: Dict[str, str] = LABELS_JA["outro_summary"]
# The number on each leg card's photo: a white pill with a soft shadow and a
# dark number, readable on light and dark photos alike.
OUTRO_PHOTO_BADGE_HEIGHT = 26
OUTRO_PHOTO_BADGE_FILL: Tuple[int, int, int, int] = (255, 255, 255, 240)
OUTRO_PHOTO_BADGE_TEXT: Tuple[int, int, int, int] = (19, 28, 46, 255)

# When a clip's narration outlasts its video, the export holds the video's last
# frame until the narration ends plus this many seconds (so the picture never
# ends while the voice is still speaking).
AUDIO_END_HOLD_SECONDS = 0.5

# --- TTS narration (Irodori-TTS) --------------------------------------------
# Fallback defaults for services.tts.ttsengine.TTSConfig — job_config.json
# can still override per-project via settings.tts, same pattern as
# settings.mode_speeds_kmh above.
TTS_MODEL = "irodori-tts"
# Device the Irodori TTS server runs its model and codec on: "cpu", "cuda" or
# "auto" (the GPU when there is one). The environment variable
# NAVIVI_TTS_DEVICE overrides it. A long text in one request drove the GPU to
# ~98% load / ~7.8 GB VRAM and hard-shut the PC (hypervisor error) more than
# once - splitting text into short chunks (below), spoken one at a time and
# joined, made each individual request safer, but "auto" still puts every
# one of those chunks on the GPU when there is one, so the same crash was
# still reachable given enough chunks back to back. Defaulting to "cpu"
# instead trades TTS speed for not crashing the machine, on this project and
# every other real one - NAVIVI_TTS_DEVICE=cuda opts back into GPU when
# that tradeoff is wanted (the server reads its device at spawn time only;
# an already-running server needs restarting to pick up a changed value).
TTS_DEVICE = "cpu"
# Longest text sent to the TTS server in one request, in characters: about 15
# seconds of speech at the project's measured ~4.4 characters per second.
TTS_MAX_CHUNK_CHARS = 60
# Shortest a standalone TTS request should be, in characters. A leftover
# trailing chunk under this (e.g. just the closing line, "今日の旅は、ここま
# でです。" at 13 chars, once nothing else is left to pack it with) has too
# little real content to anchor the model's stopping point, and the Irodori
# TTS server has been observed to "coast" past the end of such a short
# request and synthesize a trailing phrase nobody wrote ("ghost sentence"
# heard right after the narration should have finished). split_text_for_tts
# merges a too-short trailing chunk into the one before it instead, even
# past TTS_MAX_CHUNK_CHARS - a slightly long chunk is far safer than an
# isolated short one that invents its own ending.
TTS_MIN_CHUNK_CHARS = 20
# generate_speech now always splits multi-sentence text at sentence
# boundaries (never packing two sentences into one TTS request, unlike the
# old chunking that only split when TTS_MAX_CHUNK_CHARS was exceeded) and
# inserts a short procedural silence between each sentence's own audio -
# butt-joining separately-synthesized sentences with zero gap reads as
# rushed/robotic; a real speaker breathes between them. Randomized per gap
# (uniform in this range) rather than fixed, so a long narration doesn't
# have a metronome-regular click between every sentence.
# A take whose end is louder than this against its speech (artifacts.cut_off_ratio)
# stopped mid-word: it is retaken, then spoken in halves.
TTS_CUTOFF_RATIO = 0.25
TTS_CUTOFF_RETAKES = 2
# Engines whose new narration goes through artifacts.remove_stray_bursts, once, when it is made.
# Written for Irodori's stray "あ"; on Qwen3 it silenced real syllables (じゅ in じゅっぷん, と in あるくと).
TTS_STRAY_BURST_ENGINES = ("irodori",)
# Each take is heard back (services/tts/name_check.py) and retaken when a spelled-out place name isn't in it (サルサカ峠 spoken as
# さらさか). Off, or without faster-whisper installed, takes are not checked. The fewest-misses take is kept after the retakes.
TTS_NAME_CHECK = True
TTS_NAME_RETAKES = 2
TTS_NAME_CHECK_MIN_CHARS = 3  # kana, not counting ー: shorter runs (ゴール) are left alone unless a plain ending follows (ミワ神社)
TTS_NAME_CHECK_MODEL = "kotoba-tech/kotoba-whisper-v2.0-faster"  # Japanese Whisper for faster-whisper, ~1.5 GB, downloaded on first use
TTS_SENTENCE_GAP_MIN_SECONDS = 0.25
TTS_SENTENCE_GAP_MAX_SECONDS = 0.5
TTS_VOICE = "jvs004"  # Irodori's only bundled voice preset as of writing
# [Config] Playback speed multiplier sent to the Irodori TTS server; 1.0 = the
# model's natural pace. The server itself clamps to [0.25, 4.0], but TTSConfig
# validates this too so a bad value fails fast with a readable message
# instead of a 422 from the API after a network round-trip.
TTS_SPEED = 1
TTS_MIN_SPEED = 0.25
TTS_MAX_SPEED = 4.0
TTS_RESPONSE_FORMAT = None  # None = let the server use its own default (wav)
# Speaking-style caption sent as the request's "caption"; None/"" = omit.
# Per-project override: settings.tts.caption.
TTS_CAPTION = "落ち着いた、親しみやすい語り口。"

# --- Attraction clip place-name label (top-left, for the whole clip) -------
# See services/vdoprocessing/img2vdo.py's AttractionVideoGenerator._fit_and_finalize.
# True: the label is a text item on the editor's text track (place_label.py),
# not burned into the clip. Clips finalized earlier keep their burned label.
ATTRACTION_LABEL_ON_TEXT_TRACK = True
ATTRACTION_LABEL_FONT_SIZE = 26
ATTRACTION_LABEL_OUTLINE = 0.8
# Distance from the top / left edge (libass units, scaled with the video like
# the font size).
ATTRACTION_LABEL_MARGIN_TOP = 4
ATTRACTION_LABEL_MARGIN_LEFT = 4
# [Config] Attraction clips render below the map/waypoint clips' resolution to fit
# VRAM (see VideoExporter.finalize_clip), then get lanczos-upscaled to match — a
# mild unsharp pass right after that upscale claws back some of the softness the
# resize itself introduces. Off by default elsewhere since it's tuned for exactly
# this upscale ratio, not a general-purpose sharpen.
ATTRACTION_UPSCALE_SHARPEN = True

# --- Burned-in captions (timeline export and the per-clip subtitle burn) -----
# A translucent dark box with the text on it, narrow and centred at the bottom so
# it stays clear of the walk-time/distance card in the bottom-right corner of
# route clips. Mirrored in the editor preview and the Settings sample
# (src/utils/subtitleLook.ts) so what is seen there is what is burned in.
# libass sizes everything against a 288-line frame (384 wide for the SRT that
# FFmpeg converts), so these are in those units, not pixels.
CAPTION_DEFAULT_SIZE = 16
CAPTION_MAX_WIDTH = 0.5  # share of the frame width the box may use
CAPTION_MARGIN_V = 20  # gap above the bottom edge
CAPTION_BOX_PADDING = 2.0  # libass pads a box by its outline width
CAPTION_BOX_COLOR = "&H66000000"  # ASS alpha 66 = 60% opaque black
CAPTION_PLAY_RES_X = 384

# --- Narration speed presets and cache (Irodori) -------------------------------
# On a CPU a request costs ~22 s of fixed work plus sampling that scales with the number of steps, so fewer steps is the one big
# knob (measured on a Ryzen 5 5600GE: 40 steps = 26.6 s of sampling for a 1.6 s line). Sent as the request's `irodori` options;
# settings.tts.quality picks one. Not part of the voice fingerprint: finished audio stays valid when the preset changes.
TTS_QUALITY_PRESETS: Dict[str, Dict[str, object]] = {
    "fast": {"num_steps": 16},
    "balanced": {"num_steps": 24},
    "best": {"num_steps": 40},
}
TTS_QUALITY_DEFAULT = "best"
# Lines already spoken are kept here (shared by every project) so a repeated line, or a regenerate after "delete assets", is instant.
TTS_CACHE_MAX_MB = 500

# Narration cost on a CPU (Irodori), used for the first estimate of a project before real timings exist. Seconds, a straight-line fit of
# measured requests (Ryzen 5 5600GE, saved reference latent; 6/14/31 characters took 40/45/77 s at 40 steps, 26/31/51 s at 24, 20/25/42 s
# at 16): every request pays a fixed part, plus the reference-voice encode until its latent is saved; the sampling parts scale with the
# number of steps.
TTS_CPU_COST = {
    "request_fixed": 3.0,  # duration prediction, watermark
    "reference_encode": 5.0,  # only until the reference latent is saved
    "request_sampling": 28.3,  # per request, at 40 steps
    "char_sampling": 0.96,  # per character, at 40 steps
    "char_decode": 0.5,  # per character
}
TTS_BASE_STEPS = 40

# --- Narration engines -----------------------------------------------------------
# "irodori": natural, clones a voice from a recording, slow on a CPU (see TTS_CPU_COST). "kokoro": a small model with a few fixed Japanese
# voices and no cloning, 1-4 s per line on the same CPU. settings.tts.engine picks one; the project's voice fingerprint includes it, so
# switching marks finished narration as made with another voice.
TTS_ENGINES = ("irodori", "qwen3", "kokoro")
TTS_ENGINE_DEFAULT = "irodori"
KOKORO_PORT = 8089
KOKORO_VOICE = "jf_tebukuro"
# id -> label. The model's own ids: jf_ = Japanese female, jm_ = Japanese male.
KOKORO_VOICES: Dict[str, str] = {
    "jf_tebukuro": "Tebukuro (female)",
    "jf_alpha": "Alpha (female)",
    "jf_gongitsune": "Gongitsune (female)",
    "jf_nezumi": "Nezumi (female)",
    "jm_kumo": "Kumo (male)",
}
# Measured on a Ryzen 5 5600GE: ~1 s per request plus ~0.09 s per character once loaded; the model takes ~35 s to import and load, once
# per process (the server stays up between lines).
KOKORO_COST = {"request": 1.0, "char": 0.09, "startup": 35.0}

# "qwen3": Qwen3-TTS 0.6B Base, clones a voice from a recording like Irodori but at ~6.5 s of compute per second of audio on a CPU (Irodori at
# 40 steps: ~15-25). Uses the same voice library as Irodori; ~3 GB of RAM while loaded. Measured (Ryzen 5 5600GE): 10/13/31 s for lines of
# 6/14/31 characters, a fit of ~5 s per request + 0.85 s per character, and ~40 s to import and load once per process.
QWEN3_PORT = 8090
# Qwen3 guesses kanji readings and slurs some (漂う as "tadao"): send each kanji word as its UniDic pronunciation in katakana instead.
QWEN3_SPELL_OUT_KANJI = True
QWEN3_MODEL = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
# "cuda" or "cpu"; NAVIVI_TTS_DEVICE overrides. On cuda the model loads in bfloat16 (~2 GB), capped to
# QWEN3_VRAM_FRACTION of the card, and the server falls back to the CPU when CUDA is missing or fails.
# Each request first waits out a hot GPU (gpu_cooldown). This PC has hard-crashed during GPU work.
QWEN3_DEVICE = "cpu"
QWEN3_VRAM_FRACTION = 0.4
QWEN3_COST = {"request": 5.0, "char": 0.85, "startup": 40.0}
