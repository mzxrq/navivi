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

import json
import os
from typing import Dict, Tuple

# --- On-video text labels (Japanese) -----------------------------------------
# services/ -> up to src-python/ -> assets/config/ — same bundled-relative-
# to-module convention graphicengine/base.py's _BUNDLED_FONTS_DIR uses. Every
# piece of Japanese text drawn onto the rendered video lives in this one file
# (assets/config/labels_ja.json) instead of scattered across modules:
# - waypoint_fallback/start_prefix/stop_prefix: render_step.py's on-screen
#   waypoint label chip (also outrocard.py's end-card grid fallback).
# - mode_name/mode_duration_label/total_label/distance_label/
#   taskbar_card_title: cards.py's summary cards (create_summary_card /
#   create_summary_card_taskbar) — see cards.py's merge_summary_card_labels
#   for how a project's job_config.json settings.summary_card_labels can
#   still override a subset of just those keys.
# A project can override any of these via job_config.json's
# settings.pipeline_labels / settings.summary_card_labels without touching
# this bundled file at all.
_LABELS_JA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "assets", "config", "labels_ja.json",
)
_DEFAULT_LABELS_JA: Dict = {
    "waypoint_fallback": "ウェイポイント",
    "start_prefix": "出発: ",
    "stop_prefix": "到着: ",
    "mode_name": {
        "walking": "歩く", "driving": "運転", "car": "運転",
        "ferry": "乗船", "airplane": "飛行機",
    },
    "mode_duration_label": {
        "walking": "歩く時間", "driving": "運転時間", "car": "運転時間",
        "ferry": "乗船時間", "airplane": "飛行時間",
    },
    "total_label": "合計",
    "distance_label": "距離",
    "taskbar_card_title": "旅の概要",
}


def _load_labels_ja() -> Dict:
    try:
        with open(_LABELS_JA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return _DEFAULT_LABELS_JA


# Loaded once at import time — these are static display strings, not
# something a render needs to re-read per frame/per card.
LABELS_JA: Dict = _load_labels_ja()
# Alias kept for the pipeline-label (waypoint_fallback/start_prefix/
# stop_prefix) call sites that only ever needed those three keys —
# render_step.py, overview.py, outrocard.py, and helpers.py's re-export.
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
MODE_ALIASES: Dict[str, str] = {"direct": "walking", "draw": "walking"}

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
ANIMATION_SPEED_KMH = 8.0
# Fixed anchor "1x" pace every mode's on-screen speed-up factor is computed
# against — not whatever ANIMATION_SPEED_KMH happens to be configured as
# (see SpatialRenderer._mode_speed_factor).
# [NOTE] [Config] Kept independent of REPORTED/ANIMATION_SPEED_KMH so changing either doesn't silently rescale every mode's speed-up factor.
REFERENCE_SPEED_KMH = 3.0

# --- Pin / line colors (BGR) ------------------------------------------------
# Matched to the frontend's NaviPin.tsx (src/components/view/mapeditor/
# MapLayers/NaviPin.tsx) so backend-rendered map pins are the same colors as
# the ones shown live in the map editor — each is that component's hex fill
# converted to BGR.
START_PIN_COLOR: Tuple[int, int, int] = (3, 136, 19)  # #038813 green
END_PIN_COLOR: Tuple[int, int, int] = (81, 15, 217)  # #d90f51 red/pink
DRAWN_PIN_COLOR: Tuple[int, int, int] = (12, 121, 255)  # #ff790c orange — drawn-route waypoints
STOPBY_PIN_COLOR: Tuple[int, int, int] = (28, 38, 51)  # #33261c dark brown — stop-by waypoints
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
# the original 0.6x/1.0x, which read as too small next to the photo/pin
# they're labeling.
POPUP_LABEL_FONT_SCALE_BESIDE = 1.15  # "beside the pin" card (was 0.6x, then 0.85x)
POPUP_LABEL_FONT_SCALE_CORNER = 1.1  # fixed HUD-corner card (was 1.0x, then 1.3x)
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
# original wide stat pill/column card, cards.py's create_summary_card) or
# "taskbar" (a narrow Windows-notification-flyout-style list,
# create_summary_card_taskbar). Overridable per project via
# job_config.json's settings.summary_card_style.
DEFAULT_SUMMARY_CARD_STYLE = "glass"
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
# Whether a stop-by waypoint (job_config.json's "isStopBy": true) merges
# into the surrounding real-to-real leg (True — just shows its pin as the
# traveler passes, no popup, no new map tile) instead of forcing its own
# full leg/tile boundary and arrival-popup sequence like a real waypoint
# (False — the old behavior). Overridable per project via job_config.json's
# settings.merge_stopby_waypoints.
DEFAULT_MERGE_STOPBY_WAYPOINTS = True
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
# Per-travel-mode ROUTE LINE colors. Modes without an entry (e.g. walking)
# fall back to the renderer's own line_color.
# [NOTE] [Config] Modes missing here (e.g. walking) fall back to the renderer's own line_color rather than a hardcoded default.
MODE_LINE_COLORS: Dict[str, Tuple[int, int, int]] = {
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
ENDING_HIGHLIGHT_WAIT_SECONDS = 1.4
# Lead-in: how long to push in on the CURRENT wide map (clean, no cards)
# toward the same point BEFORE that hard cut, and how far.
BIG_MAP_ZOOM_LEAD_SECONDS = 1.3
BIG_MAP_ZOOM_TARGET = 2.6
# When settings.enable_gl_ending_zoom (or overview_background: "pydeck")
# is on (see mapfetcher/pydeck_overview.py), the ending highlight's
# lead-in push AND its cut to a separate fetched close-up tile are both
# replaced by ONE continuous sequence of genuinely re-rendered deck.gl
# frames zooming from the wide map all the way in — real map detail
# revealed as it zooms, rather than a modest digital Ken Burns crop
# followed by a hard cut to a second static image. In log2 zoom units
# (each +1 doubles the visual scale) — 3.2 stops around street-label
# level (road names legible) regardless of the base overview's own zoom,
# rather than zooming in past that to individual-building/terrain detail.
ENDING_HIGHLIGHT_PYDECK_ZOOM_BOOST = 3.2

# --- Popup / transition timing ----------------------------------------------
POPUP_FADE_SECONDS = 1.5
# Minimum wall-clock gap between one waypoint popup triggering and the next
# one being allowed to — a cluster of waypoints placed close together on
# the map (a common case: several stops within the same block) could
# otherwise trigger back-to-back within a frame or two of each other,
# popping the current card out again almost as soon as it appeared, well
# before it was actually readable. Applies regardless of how close the
# pins are, on top of (not instead of) each popup's own display duration.
OVERVIEW_POPUP_MIN_TRIGGER_GAP_SECONDS = 2.0
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
COMFYUI_UNET_NAME = "Wan2_2-TI2V-5B-Turbo-Q6_K.gguf"
COMFYUI_CLIP_NAME = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
COMFYUI_VAE_NAME = "wan2.2_vae.safetensors"
# 1280x704 fits comfortably in an 8GB VRAM budget at this quant (see
# img2vdo.py's _TARGET_WIDTH/_TARGET_HEIGHT comment — upscaled to 1920x1080
# after generation to match the rest of the pipeline's clips).
COMFYUI_WIDTH = 1280
COMFYUI_HEIGHT = 704
COMFYUI_FPS = 24
# Turbo-model recommended settings (see the model card): 4 steps is enough
# at CFG 1, euler/simple is a safe default sampler+scheduler pair.
COMFYUI_STEPS = 4
COMFYUI_CFG = 1.0
COMFYUI_SAMPLER = "euler"
COMFYUI_SCHEDULER = "simple"
COMFYUI_MODEL_SHIFT = 8.0
# Wan wants frame counts of the form 4k+1; clamp generated length into a
# sane range so a very long/short narration duration can't request a
# pathological (near-zero or excessively slow) clip.
COMFYUI_MIN_FRAMES = 25   # ~1s @ 24fps
COMFYUI_MAX_FRAMES = 121  # ~5s @ 24fps — the template's own default length
COMFYUI_NEGATIVE_PROMPT = (
    "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，"
    "整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，"
    "画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，"
    "静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走"
)
# Maps attraction_step.py's camera_pans vocabulary (also used by
# local_pan_generator.py's _CAMERA_PAN_PRESETS) to an English motion prompt
# Wan responds to — camera_pans entries are otherwise just short keywords,
# not descriptive prose.
COMFYUI_CAMERA_PAN_PROMPTS: Dict[str, str] = {
    "panright": "smooth cinematic camera pan to the right across the scene, natural motion",
    "panleft": "smooth cinematic camera pan to the left across the scene, natural motion",
    "zoomin": "slow cinematic zoom in on the scene, natural motion",
    "zoomout": "slow cinematic zoom out from the scene, natural motion",
    "none": "subtle natural ambient motion, gentle cinematic movement",
}
COMFYUI_DEFAULT_MOTION_PROMPT = "subtle natural ambient motion, gentle cinematic movement"
# How long the bundled server can sit unused before idle_watchdog.py shuts
# it down — mirrors IrodoriTTSClient's reasoning (10 min covers gaps between
# waypoints in one run without wasting VRAM/RAM long after the job ends).
COMFYUI_IDLE_TIMEOUT_SECONDS = 600.0
# Generous: first call after a cold start pays for node/import startup, and
# a Q6_K/8GB-class generation at up to 121 frames has taken up to ~15
# minutes in testing.
COMFYUI_SERVER_START_TIMEOUT_SECONDS = 180.0
COMFYUI_GENERATION_TIMEOUT_SECONDS = 1200.0

# --- Intro clip (multi-image slideshow + centered project title) -----------
# A slideshow of INTRO_IMAGE_COUNT random waypoint images (a fresh pick
# every call), each with its own slow zoom-in, crossfaded into the next —
# see services/vdoprocessing/introclip.py.
INTRO_IMAGE_COUNT = 3
# Each picture's own on-screen time INCLUDING the crossfade overlap into/out
# of it — total intro length = COUNT*PER_IMAGE - (COUNT-1)*CROSSFADE.
INTRO_PER_IMAGE_SECONDS = 3.5
INTRO_CROSSFADE_SECONDS = 0.8
INTRO_TITLE_FONT_SIZE = 48
INTRO_TITLE_OUTLINE = 3.0
INTRO_OUTPUT_FILENAME = "00_intro.mp4"
INTRO_WIDTH = 1280
INTRO_HEIGHT = 704
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

# --- Outro card grid (end-of-video "places visited" summary) ---------------
# A single composited frame (project title + a thumbnail grid of every
# waypoint with a popup image) held for a fixed duration as the closing
# clip — see services/vdoprocessing/outrocard.py.
OUTRO_DURATION_SECONDS = 5.0
OUTRO_OUTPUT_FILENAME = "99_outro.mp4"
# {count} is substituted with the number of waypoint cards shown.
OUTRO_SUBTITLE_TEMPLATE = "訪れた{count}か所"
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

# --- TTS narration (Irodori-TTS) --------------------------------------------
# Fallback defaults for services.tts.ttsengine.TTSConfig — job_config.json
# can still override per-project via settings.tts, same pattern as
# settings.mode_speeds_kmh above.
TTS_MODEL = "irodori-tts"
TTS_VOICE = "string"  # Irodori's only bundled voice preset as of writing
# [Config] Playback speed multiplier sent to the Irodori TTS server; 1.0 = the
# model's natural pace. The server itself clamps to [0.25, 4.0], but TTSConfig
# validates this too so a bad value fails fast with a readable message
# instead of a 422 from the API after a network round-trip.
TTS_SPEED = 1.0
TTS_MIN_SPEED = 0.25
TTS_MAX_SPEED = 4.0
TTS_RESPONSE_FORMAT = None  # None = let the server use its own default (wav)

# --- Attraction clip place-name label (top-left, burned for the whole clip) -
# See services/vdoprocessing/img2vdo.py's AttractionVideoGenerator._fit_and_finalize.
ATTRACTION_LABEL_FONT_SIZE = 26
ATTRACTION_LABEL_OUTLINE = 2.5
ATTRACTION_LABEL_MARGIN = 20
# [Config] Attraction clips render below the map/waypoint clips' resolution to fit
# VRAM (see VideoExporter.finalize_clip), then get lanczos-upscaled to match — a
# mild unsharp pass right after that upscale claws back some of the softness the
# resize itself introduces. Off by default elsewhere since it's tuned for exactly
# this upscale ratio, not a general-purpose sharpen.
ATTRACTION_UPSCALE_SHARPEN = True
