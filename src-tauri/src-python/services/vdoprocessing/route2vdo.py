"""
Route to Video Animator (route2vdo.py)
---------------------------------------------------------------------------
Main Orchestrator. Parses CLI arguments and JSON data, then routes
the drawing commands to the Spatial renderer.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, List, NamedTuple, Optional, Tuple

from services.mapfetcher.graphicengine import GraphicsEngine
from services.logger.logger import setup_logger
from services.logger.progress import tracker
from services import runtime_paths, tuning, video_text
from services.mapbox_token import resolve_mapbox_token
from services.mapfetcher.maplanguage import resolve_map_style
from services.mapfetcher.street_photos import attach_cue_spans, clear_of, resolve_mapillary_token, street_view_landmarks, turn_photos
from services.projectfiles import meta_dir, write_json_atomic
from services.vdoprocessing.spatial_renderer import SpatialRenderer
from services.vdoprocessing.route_inputs import photo_inputs_hash, returns_to
from services.vdoprocessing.storyboard import for_config as storyboard_for

# Logging configuration
logger = setup_logger("RouteAnimator")

# Shared fallback defaults — reused both as the initial GraphicsEngine
# config value and later as the CLI --thickness/--radius/--summary-hold
# fallback when neither the CLI flag nor the route JSON's settings supply
# one. Named here so both use sites can't silently drift apart.
DEFAULT_LINE_THICKNESS = 7  # thin traced route (editorial look), not a highway (was 10)
# [NOTE] [Config] 16 is the GraphicsEngine floor (it draws max(16, r) + 3 px); a larger default was clamped to it anyway.
DEFAULT_MARKER_RADIUS = 16
DEFAULT_SUMMARY_HOLD_SECONDS = 4.0

def _output_is_valid(path, min_bytes: int = 1024) -> bool:
    """Checkpoint helper — see spatial_renderer/overview.py's identical
    copy for why this is duplicated instead of imported from
    videopipeline/helpers.py (circular import)."""
    try:
        p = Path(path)
        return p.is_file() and p.stat().st_size >= min_bytes
    except OSError:
        return False

# Bump when the leg rendering code changes what it draws (v2: stop-by
# photos always go fullscreen, image_display ignored; v3: legs open on the
# departure photo, not the destination's; v4: HUD card is the overview's
# summary card; v5: framing clears the corner banners and the caption;
# v6: the card's Total counts down the whole trip, not just the leg;
# v7: leg card numbers are the overview card's own per-leg numbers;
# v8: stop-bys are framed too, and the summary card sits lower;
# v9: the 3D leg HUD card sits as low as the 2D one).
LEG_RENDER_VERSION = 40  # v40: every leg slides on from the leg before, zooming only when needed; v39: the card's second column reads 残り (what is left), no empty banner bar at the start; v38: the direction/turn-by-turn HUD card is removed entirely -- didn't work out; v36: the direction arrow moves to bottom-left (above the elevation card's own spot), not bottom-right; v35: the badge's digit goes heavier still (900 + a thin matching text-stroke) since 700 still read thin at this small size; v34: that card sits a bit closer to the label again (108px, not 140); v31: a leg's opening/arrival photo card keeps clear of the pin's name label too, not just the pin itself; v30: the chain pill's circle badge is bigger and vertically centered against the place text; v29: the chain pill drops its 出発/到着 text prefix for a start/end circle badge (the pin's own S/E/number glyph); v28: a stop-by's photo card keeps further off its marker so it doesn't land on the marker's own name pill; v27: the carried-over photo card's leader line stops short of the marker like the others, instead of crossing its label; v26: the chain, progress and destination banners merge into one top bar, with a "stop N of total" progress segment; v25: place names keep off each other, stacking a row further out when every spot beside their point is taken; v24: at a stop with no attraction script the photo card rides along the slide (setting quiet_stop_transition); v23: photo cards keep off the route before keeping the leader short; v22: {view wait} times count from the {start} cue; v21: name tags placed with the real camera scale; v20: cards keep off the kept walked line; v19: a leg continuing the walk slides at the zoom of the leg before; v18: quicker opening/closing zoom (LEG_ZOOM_SECONDS); v17: a leg after a stop with no narration continues the walk; v16: fullscreen photo shrinks in 0.25 s, street view cards show their name; v15: legs joined at a stop with no narration continue from the same frame; v14: no automatic turn photo within 50 m of a placed street view; v13: a leg's own photo card sits off the route line (2026-11-09)
# Bumped when the heatmap legs' elevation profile card changes (only those legs re-render; v1: the card).
LEG_ELEVATION_CARD_VERSION = 2
# Bumped when the top-left stop chain's layout changes (only legs that show one re-render).
LEG_CHAIN_FIT_VERSION = 1
# Bumped when the camera move to a far stop-by changes (only legs with one re-render; v1: fly out and back,
# v2: the leg's frame no longer stops at it).
LEG_FAR_STOPBY_VERSION = 2
# A leg is reused unless its waypoints' route inputs (see route_inputs.py) or
# the render version changed, or its files are missing. Not "latlon": the app
# can save a different line for the same waypoints.
_LEG_CHECKPOINT_PARTS = ("route_inputs", "render_version", "photos", "video_text", "kw.leg_elevations", "return_stop", "closed", "quiet_stopby", "stopby_reopen", "pops_after", "join")
# The stops' names on the leg's banner and its narration timing (fix.md #9). Compared only when the leg's
# record has them, so a leg rendered before these were checked is not re-rendered for it.
_LEG_RECORDED_PARTS = ("kw.route_chain", "kw.target_duration_seconds", "kw.start_cue_seconds", "kw.arrival_wait_seconds")

def _split_stopby_chain(res_data: Dict[str, Any]) -> Tuple[List[str], List[List[Any]]]:
    """(the leg's numbered places in travel order, its stop-bys as [name, index of the chain place they come before,
    lat, lon]): the banner shows the stop-bys inline, in the order walked, and switches as the walker passes each.
    lat/lon come from the leg's per-point lats/lons (labels run parallel to them) and are None when they don't line up.
    The destination always stays in the chain."""
    labels = res_data.get("labels") or []
    flags = res_data.get("stopbys") or []
    lats, lons = res_data.get("lats"), res_data.get("lons")
    aligned = lats is not None and lons is not None and len(lats) == len(labels) == len(lons)
    rows = [(i, l) for i, l in enumerate(labels) if l]
    last = len(rows) - 1
    chain: List[str] = []
    stopbys: List[List[Any]] = []
    for k, (i, l) in enumerate(rows):
        if k != last and i < len(flags) and flags[i]:
            stopbys.append([l, len(chain), float(lats[i]) if aligned else None, float(lons[i]) if aligned else None])
        else:
            chain.append(l)
    return chain, stopbys


def _legs_join(prev: Dict[str, Any], nxt: Dict[str, Any]) -> bool:
    """Whether `nxt` can carry on from `prev`'s last frame: both are drawn by the street-level renderer and `nxt`
    starts where `prev` ended."""
    from services.vdoprocessing.pydeckrecorder.geomath import haversine_km

    ends = []
    for leg, at in ((prev, -1), (nxt, 0)):
        lats, lons = leg.get("lats"), leg.get("lons")
        mode = str(leg.get("mode") or "walking").lower()
        if lats is None or lons is None or min(len(lats), len(lons)) < 2:
            return False
        if tuning.MODE_ALIASES.get(mode, mode) in tuning.RESIDENTIAL_2D_FALLBACK_MODES:
            return False
        ends.append((float(lons[at]), float(lats[at])))
    return haversine_km(*ends[0], *ends[1]) * 1000.0 <= tuning.LEG_JOIN_MAX_GAP_METERS


def _reported_speed_kmh(mode_speed_kmh: Dict[str, float], mode: str) -> float:
    """Same speed the overview's summary card uses for this mode (render_step.py)."""
    return mode_speed_kmh.get(mode) or mode_speed_kmh.get("car") or 70.0


def _measured_leg_km(res_data: Dict[str, Any]) -> float:
    from services.vdoprocessing.pydeckrecorder.geomath import haversine_km

    lats, lons = res_data.get("lats"), res_data.get("lons")
    if lats is None or lons is None:
        return 0.0
    pts = list(zip(lats, lons))
    return sum(haversine_km(a[1], a[0], b[1], b[0]) for a, b in zip(pts, pts[1:]))


def _brief_leg_stats(res_data: Dict[str, Any], brief_legs: List[Dict[str, Any]]) -> Optional[Tuple[float, float]]:
    """(km, seconds) the overview card counts for this leg: its brief legs from
    the start waypoint to the end one (several when a connected stop-by splits it)."""
    by_from = {l.get("from_id"): l for l in brief_legs if l.get("from_id")}
    wp, end = res_data.get("start_waypoint_id"), res_data.get("end_waypoint_id")
    km = minutes = 0.0
    for _ in range(len(brief_legs)):
        leg = by_from.get(wp)
        if leg is None:
            return None
        km += leg["km"]
        minutes += leg["minutes"]
        wp = leg.get("to_id")
        if wp == end:
            return km, minutes * 60.0
    return None


def _leg_distance_and_seconds(
    res_data: Dict[str, Any], mode_speed_kmh: Dict[str, float], brief_legs: List[Dict[str, Any]],
) -> Tuple[float, float]:
    """A leg's (km, seconds) as the overview card counts them; legs it has no
    match for (a synthetic start/end leg) are measured at the same speeds."""
    stats = _brief_leg_stats(res_data, brief_legs)
    if stats:
        return stats
    km = _measured_leg_km(res_data)
    mode = str(res_data.get("mode") or "walking").lower()
    mode = tuning.MODE_ALIASES.get(mode, mode)
    return km, km / _reported_speed_kmh(mode_speed_kmh, mode) * 3600.0


def _leg_fingerprint(leg_latlon, dest_label, leg_kwargs: Dict[str, Any]) -> str:
    """Hash of everything a residential leg's clip is rendered from (its
    route piece, destination and every render argument - walk length,
    photos, cue timing)."""
    import hashlib

    def plain(obj):
        if hasattr(obj, "tolist"):  # numpy arrays/scalars
            return obj.tolist()
        return str(obj)

    fields = {"latlon": leg_latlon, "dest": dest_label, "kwargs": leg_kwargs, "render_version": LEG_RENDER_VERSION}
    if video_text.current_language() != video_text.DEFAULT_LANGUAGE:
        fields["video_text"] = video_text.current_language()  # [NOTE] absent for Japanese: old clips stay valid
    payload = json.dumps(fields, sort_keys=True, default=plain, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _leg_fingerprint_parts(
    leg_latlon, dest_label, leg_kwargs: Dict[str, Any], route_inputs: Optional[str] = None,
) -> Dict[str, str]:
    """Short hash per fingerprint input, stored beside the fingerprint so a
    mismatch can name what changed."""
    import hashlib

    def h(obj) -> str:
        blob = json.dumps(
            obj, sort_keys=True, ensure_ascii=False,
            default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o),
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:10]

    parts = {"latlon": h(leg_latlon), "dest": h(dest_label), "render_version": str(LEG_RENDER_VERSION)}
    if route_inputs:
        parts["route_inputs"] = route_inputs
    parts.update({f"kw.{k}": h(v) for k, v in leg_kwargs.items()})
    if leg_kwargs.get("route_chain"):
        # Legs with a stop chain on top re-render once when its fitting changes (v1: shrinks to clear the pill).
        parts["kw.route_chain"] = h([leg_kwargs["route_chain"], LEG_CHAIN_FIT_VERSION])
    if any(lm.get("pops_after") is not None for lm in leg_kwargs.get("landmarks") or []):
        parts["kw.landmarks"] = h([leg_kwargs["landmarks"], LEG_FAR_STOPBY_VERSION])
        # Which stop-bys pop up without walking: a leg re-renders when one of them is walked to instead.
        parts["pops_after"] = h([[lm.get("pops_after") for lm in leg_kwargs["landmarks"]], LEG_FAR_STOPBY_VERSION])
    if leg_kwargs.get("dest_image_display") == "pip" or leg_kwargs.get("opening_photo") is False:
        # A leg to or from a return stop (pin of the first visit, photo card, no fullscreen): re-rendered once for it.
        parts["return_stop"] = h(
            [leg_kwargs.get(k) for k in ("start_pin", "dest_pin", "dest_image_display", "opening_photo", "opening_view")]
            + [bool(leg_kwargs.get("end_view_path"))]
        )
    if leg_kwargs.get("opening_view") or leg_kwargs.get("end_view_path"):
        # Joined legs share a frame: re-rendered when either side of the join changes, or the join comes or goes.
        parts["join"] = h([leg_kwargs.get("opening_view"), bool(leg_kwargs.get("end_view_path"))])
    closed = [lm.get("label") for lm in leg_kwargs.get("landmarks") or [] if lm.get("inaccessible")]
    if closed:
        parts["closed"] = h([closed, 3])  # a place turned Closed re-renders the legs that pass it (v3: fullscreen photo)
    quiet = [lm.get("label") for lm in leg_kwargs.get("landmarks") or [] if lm.get("quiet")]
    if quiet:
        parts["quiet_stopby"] = h(quiet)  # a stop-by whose narration was emptied re-renders only the legs passing it
    # A connected or walked-past stop-by cuts the leg and the next piece opens on its photo and a camera move; only
    # those legs re-render when that opening changes (v3: a brief re-open and a shorter hop, which delayed the
    # narration; v4: the camera moves only when the next stretch doesn't fit the frame; v5: a glide, no zoom-out hop).
    reopen = [lm.get("label") for lm in leg_kwargs.get("landmarks") or []
              if (lm.get("connect_to_route") and lm.get("popup_image")) or lm.get("walk_seconds") is not None]
    if reopen:
        parts["stopby_reopen"] = h([reopen, 5])
    if "leg_elevations" in leg_kwargs:
        # Heatmap legs also draw the elevation profile card: re-render only them when it changes.
        parts["kw.leg_elevations"] = h([leg_kwargs["leg_elevations"], LEG_ELEVATION_CARD_VERSION])
    parts["photos"] = photo_inputs_hash(leg_kwargs)
    if video_text.current_language() != video_text.DEFAULT_LANGUAGE:
        parts["video_text"] = video_text.current_language()  # absent for Japanese: old clips stay valid
    return parts


def leg_changed_parts(leg_parts: Dict[str, str], old_parts: Dict[str, str]) -> List[str]:
    """The inputs that make a rendered leg stale: its own path (or a missing file) re-renders it."""
    changed = {k for k in set(leg_parts) | set(old_parts) if leg_parts.get(k) != old_parts.get(k)}
    if "route_inputs" not in old_parts:  # rendered before route_inputs was recorded: the line itself
        return [k for k in ("latlon", "render_version") if k in changed]
    return ([k for k in _LEG_CHECKPOINT_PARTS if k in changed]
            + [k for k in _LEG_RECORDED_PARTS if k in old_parts and k in changed]
            + [k for k in ("kw.pace_cues", "kw.at_cues", "kw.piece_start_cues") if k in changed])  # added/removed {slow}/{fast}/{stop}/{at N}/a later piece's {start} too


def cut_landmark_ids(mid_markers: List[Dict[str, Any]]) -> List[Optional[str]]:
    """The stop-bys a leg is cut at, in order: one with a photo that exists and a narration piece of its own
    (connected or not). Must match what actually cuts (stopby_pause: `walk_seconds` set, see leg_sequence's
    marker_plans) - listing one that does not cut shifts every piece onto the stop before it and drops the
    destination's narration off the end, leaving the leg silent."""
    return [
        m.get("waypoint_id")
        for m in mid_markers
        if m.get("lat") is not None
        and m.get("lng", m.get("lon")) is not None
        and m.get("walk_seconds") is not None
        and isinstance(m.get("popup_image"), str) and os.path.exists(m["popup_image"])
    ]


def _stored_leg_inputs(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def stash_leg(files: List[Path], variant_dir: Path) -> None:
    """Copies a leg's finished files (clips, sidecars, inputs.json) aside, replacing the variant kept there."""
    tmp = variant_dir.with_name(variant_dir.name + ".part")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    for f in files:
        if f.exists():
            shutil.copy2(f, tmp / f.name)
    shutil.rmtree(variant_dir, ignore_errors=True)
    tmp.rename(variant_dir)


def leg_clips(folder: Path, pattern: str = "*.mp4") -> List[Path]:
    """A leg's finished pieces in play order (X, X_cont2, ..., X_cont10): leg_pieces.py's "_padded" copies left
    out, and sorted by piece number (as text, _cont10 came before _cont2 and got the wrong narration)."""
    def piece(p: Path) -> int:
        m = re.search(r"_cont(\d+)$", p.stem)
        return int(m.group(1)) if m else 1

    return sorted(
        (p for p in folder.glob(pattern) if _output_is_valid(p) and "_padded" not in p.stem),
        key=lambda p: (piece(p), p.name),
    )


def pieces_complete(files: List[Path]) -> bool:
    """A leg's pieces with none missing: X, X_cont2, ... X_contN (a piece deleted to remake it leaves a gap)."""
    nums = sorted(int(m.group(1)) if (m := re.search(r"_cont(\d+)$", Path(f).stem)) else 1 for f in files)
    return nums == list(range(1, len(nums) + 1))


def restore_leg(variant_dir: Path, inputs_name: str, leg_parts: Dict[str, str], current: List[Path], out_dir: Path) -> List[Path]:
    """When the leg's kept variant was rendered from these inputs (a setting switched off and back on), swaps it in:
    the current files become the kept variant. Returns the restored clips; [] when there is nothing to restore."""
    kept = _stored_leg_inputs(variant_dir / inputs_name).get("parts") or {}
    clips = leg_clips(variant_dir)
    if not kept or not clips or leg_changed_parts(leg_parts, kept):
        return []
    swap = variant_dir.with_name(variant_dir.name + ".swap")
    stash_leg(current, swap)
    for f in current:
        f.unlink(missing_ok=True)
    for f in variant_dir.iterdir():
        shutil.copy2(f, out_dir / f.name)
    shutil.rmtree(variant_dir, ignore_errors=True)
    swap.rename(variant_dir)
    return [out_dir / p.name for p in clips]


class _ResContext(NamedTuple):
    """What every leg of one residential render shares."""

    wp_by_id: Dict[Any, Dict[str, Any]]
    waypoint_id_to_idx: Dict[str, int]
    attraction_dir: Optional[Path]
    context_path: Optional[list]
    mode_speed_kmh: Dict[str, float]
    street_views: List[List[Dict[str, Any]]]
    leg_totals: List[Tuple[float, float]]


class _LegPhotos(NamedTuple):
    dest_image: Optional[str]
    dest_freeze: Optional[float]
    dest_narration: Optional[float]
    dest_display: str
    dest_quiet: bool
    start_image: Optional[str]
    start_freeze: Optional[float]
    start_narration: Optional[float]


class _LegPlan(NamedTuple):
    kwargs: Dict[str, Any]
    num: int
    prefix: str
    output_path: str
    connected_ids: List[Optional[str]]
    dest_id: Optional[str]


class _LegReuse(NamedTuple):
    files: List[Path]
    stale: List[Path]
    changed: List[str]
    parts: Dict[str, str]


class RouteAnimator:
    """Orchestrates the animation pipeline by bridging configurations with Renderers."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config

        # NOTE: `self.config` here is already the flattened settings dict
        # render_route_video builds (animator_config) — it has no nested
        # "settings" key of its own, so a `self.config.get("settings", {})`
        # lookup (the old code) always fell through to `{}` and silently
        # discarded whatever settings.map_font_size/card_border_* a project
        # actually configured. Read the keys directly off self.config.
        map_font_size = self.config.get("map_font_size", 24) if self.config else 24

        # 1. Initialize the Core Graphics Engine
        self.graphics = GraphicsEngine(
            line_color=self.config.get("line_color", (243, 150, 33)),  # BGR blue
            line_thickness=self.config.get("line_thickness", DEFAULT_LINE_THICKNESS),
            # Was hardcoded to (0, 0, 255)/(0, 0, 220) here — both pure red
            # in BGR — completely independent of (and inconsistent with)
            # tuning.DEFAULT_MARKER_COLOR's own blue default. Since a
            # project's job_config.json rarely sets "marker_color"
            # explicitly, every not-yet-arrived numbered pin (and every
            # popup card border, which falls back to this same color —
            # see pins.py's _pin_color/_pin_label_and_color) rendered red
            # instead of the intended blue in every real render. Falling
            # back to the SAME tuning.py defaults GraphicsEngineBase
            # itself already uses keeps this consistent regardless of
            # which one actually ends up supplying the color.
            marker_color=self.config.get("marker_color", tuning.DEFAULT_MARKER_COLOR),
            arrived_marker_color=self.config.get(
                "arrived_marker_color", tuning.DEFAULT_ARRIVED_MARKER_COLOR
            ),
            marker_radius=self.config.get("marker_radius", DEFAULT_MARKER_RADIUS),
            font_size=map_font_size,
            card_border_color=tuple(
                self.config.get("card_border_color", tuning.DEFAULT_CARD_BORDER_COLOR)
            ),
            card_border_thickness=self.config.get(
                "card_border_thickness", tuning.DEFAULT_CARD_BORDER_THICKNESS
            ),
            line_border_color=tuple(
                self.config.get("route_line_border_color", tuning.DEFAULT_LINE_BORDER_COLOR)
            ),
            line_border_thickness=self.config.get(
                "route_line_border_thickness", tuning.DEFAULT_LINE_BORDER_THICKNESS
            ),
            summary_card_style=self.config.get(
                "summary_card_style", tuning.DEFAULT_SUMMARY_CARD_STYLE
            ),
            summary_card_labels=self.config.get("summary_card_labels"),
            # Per-mode line colors: the pipeline puts {"walking": <the
            # project's own Route Line color>} here when the project
            # picked one, so the ordinary leg follows the map-appearance
            # panel instead of tuning.py's walking blue — see
            # render_step.py's _mode_line_color_overrides.
            mode_line_colors=self.config.get("mode_line_colors"),
            theme=tuning.resolve_ui_theme(self.config),
        )

        self.out_dir = Path(config.get("output_dir", ""))
        self.out_dir.mkdir(parents=True, exist_ok=True)

        # 2. Initialize the isolated Render Engines
        self.spatial_renderer = SpatialRenderer(
            self.config, self.graphics, self.out_dir
        )

    def load_route_data(self, json_path: str) -> Tuple[List, List, List, Dict]:
        """Loads and parses the waypoints into memory."""
        with open(json_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        if isinstance(raw_data, list):
            route_data, settings = raw_data, {}
        else:
            route_data = raw_data.get("route", raw_data.get("points", []))
            settings = raw_data.get("settings", {})

        points, labels, popups = [], [], []
        for item in route_data:
            if isinstance(item, (list, tuple)):
                points.append([float(item[0]), float(item[1])])
                labels.append(None)
                popups.append(None)
            elif isinstance(item, dict):
                points.append([float(item["x"]), float(item["y"])])
                labels.append(item.get("label"))
                # ADDED: Check for 'transition' key in the JSON configuration
                if (
                    "freeze_seconds" in item
                    or "popup_image" in item
                    or "popup_video" in item
                    or "transition" in item
                ):
                    popups.append(
                        {
                            "freeze_seconds": min(
                                float(item.get("freeze_seconds", 2.0)),
                                tuning.POPUP_FREEZE_SECONDS_MAX,
                            ),
                            "popup_image": item.get("popup_image"),
                            "popup_video": item.get("popup_video"),
                            "image_display": item.get(
                                "image_display", item.get("image display", "box")
                            ),
                            # ADDED: Store the transition type (e.g., 'pop up', 'fullscreen')
                            "transition": item.get("transition", "popup"),
                            "triggered": False,
                        }
                    )
                else:
                    popups.append(None)
            else:
                raise ValueError(f"Unknown point format: {item}")

        return points, labels, popups, settings

    def _commit_overview_checkpoint(self) -> None:
        commit = getattr(self.spatial_renderer, "pending_overview_checkpoint", None)
        if commit:
            commit()
            self.spatial_renderer.pending_overview_checkpoint = None

    def _freeze_video_end(self, video_path: str, hold_seconds: float):
        """Uses FFmpeg tpad filter to seamlessly clone and hold the final frame."""
        if hold_seconds <= 0:
            return

        logger.info(
            f"❄️ Freezing the final overview frame for {hold_seconds} seconds..."
        )
        temp_out = str(
            Path(video_path).with_name(f"temp_frozen_{Path(video_path).name}")
        )

        # [HACK] [Editor] FFmpeg has no native "hold last frame" operation on
        # an already-encoded clip, so tpad's clone mode re-encodes the whole
        # file just to duplicate the final frame for hold_seconds.
        cmd = [
            runtime_paths.ffmpeg_exe() or "ffmpeg",
            "-y", *tuning.ffmpeg_log_args(),
            "-i",
            video_path,
            "-vf",
            f"tpad=stop_mode=clone:stop_duration={hold_seconds}",
            "-c:v",
            "libx264",
            *tuning.ffmpeg_thread_args(),
            "-pix_fmt",
            "yuv420p",
            temp_out,
        ]

        result = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        if result.returncode == 0 and os.path.exists(temp_out):
            os.replace(temp_out, video_path)
        else:
            logger.warning("Failed to freeze video end. Skipping freeze frame.")

    def _mapbox_token(self) -> Optional[str]:
        """The app's token (NAVIVI_MAPBOX_TOKEN), else what a project saved by an older version still carries in its
        job_config.json settings (this animator's own config is a curated subset without it), else the old env names."""
        try:
            settings = (self.spatial_renderer._get_job_config() or {}).get("settings")
        except Exception:
            settings = None
        return resolve_mapbox_token(settings if isinstance(settings, dict) else None)

    @staticmethod
    def _overview_waypoints(points: List, labels: List, popups: List, extent, w: int, h: int) -> List[Dict[str, Any]]:
        from services.mapfetcher.mapgeometry import RouteGeometryProcessor

        waypoints = []
        order = 0
        for i, popup in enumerate(popups):
            if popup is None:
                continue
            is_stopby = bool(popup.get("is_stopby"))
            lat, lon = RouteGeometryProcessor.pixel_to_latlon(points[i][0], points[i][1], extent, w, h)
            # [NOTE] A stop-by isn't part of the visible 1..N numbering (see _pin_layers/overview.py's own matching
            # rule) - order still gets set (the pre-increment count) so it's never missing, just not incremented.
            entry = {"lat": lat, "lon": lon, "order": order, "label": labels[i], "is_stopby": is_stopby}
            if popup.get("pin_image"):
                entry["pin_image"] = popup["pin_image"]
            if not is_stopby:
                order += 1
                entry["order"] = order
            waypoints.append(entry)
        return waypoints

    def _assign_overview_pins(self, waypoints: List[Dict[str, Any]], popups: List) -> None:
        """Same glyphs/colors as the 2D overview and the leg clips: S green, E red, numbered stops in the marker
        color. A return stop shows the pin of the stop it comes back to, and takes no number of its own."""
        places = [p for p in popups if p is not None]
        back_of = {j: returns_to(places, j) for j in range(len(waypoints))}
        numbered = [wp for j, wp in enumerate(waypoints) if not wp["is_stopby"] and back_of[j] is None]
        for k, wp in enumerate(numbered):
            if k == 0:
                wp["pin_glyph"], wp["pin_color"] = "S", tuning.START_PIN_COLOR
            elif k == len(numbered) - 1 and k != 1:
                wp["pin_glyph"], wp["pin_color"] = "E", tuning.END_PIN_COLOR
            else:
                wp["pin_glyph"], wp["pin_color"] = str(k), self.graphics.marker_color
        for j, back in back_of.items():
            if back is not None:
                waypoints[j]["pin_glyph"] = waypoints[back].get("pin_glyph")
                waypoints[j]["pin_color"] = waypoints[back].get("pin_color")

    def _render_overview_pydeck(
        self, img_path: str, points: List, labels: List, popups: List,
        extent: Optional[Tuple[float, float, float, float]], fps: int,
    ) -> Optional[str]:
        """GeoJsonLayer-driven alternative to SpatialRenderer.render_overview
        — a static overview image (full route + numbered pins) instead of
        an animated OpenCV line-draw. `points` are still in the PIXEL space
        of `img_path` (see load_route_data/_project_route_to_pixels
        upstream); reprojected back to lat/lon via `extent`, same mechanism
        overview.py's own `_route_latlon_path` already relies on — this
        module never needed its own fetched background raster to begin
        with, only real coordinates to hand to a live pydeck/Mapbox basemap.
        """
        if extent is None:
            logger.warning(
                "use_pydeck_pedestrian overview requested but no extent was "
                "supplied — cannot reproject pixel points to lat/lon. "
                "Skipping overview render."
            )
            return None

        from services.mapfetcher.mapgeometry import RouteGeometryProcessor
        from services.vdoprocessing.pydeckrecorder.overview_pydeck import render_overview_video_pydeck

        bg = self.graphics.read_image_safe(str(img_path))
        if bg is None:
            raise FileNotFoundError(f"Cannot read background image: {img_path}")
        h, w = bg.shape[:2]

        route_latlon = [
            RouteGeometryProcessor.pixel_to_latlon(p[0], p[1], extent, w, h) for p in points
        ]

        waypoints = self._overview_waypoints(points, labels, popups, extent, w, h)
        self._assign_overview_pins(waypoints, popups)

        # The reference video's wide section-title caption (e.g.
        # "友ヶ島・加太をめぐる道") reads as the trip's own name — reusing
        # job_config.json's project_name is the closest real data source
        # for that, same file _get_job_config already walks up to find.
        job_config = self.spatial_renderer._get_job_config() or {}
        title_text = self.config.get("overview_title") or job_config.get("project_name")

        output_path = str(self.out_dir / "01_overview.mp4")
        if self.config.get("checkpoint_enabled", False) and _output_is_valid(output_path):
            logger.info("Overview video already exists — skipping render: %s", output_path)
            return output_path
        duration = self.config.get("duration", 30.0)
        return render_overview_video_pydeck(
            route_latlon, waypoints, output_path, duration=duration, fps=fps, title_text=title_text,
            mapbox_key=self._mapbox_token(),
            map_style=resolve_map_style(self.config, "mapbox/streets-v12"),
        )

    def _leg_hud_card_png(self, mode: str, leg: Tuple[float, float], after: Tuple[float, float]):
        """PNG renderer for the pydeck leg's distance/time card, drawn with
        the same summary card the overview uses. The walker's remaining share
        of the line is shown as that share of `leg` (km, seconds), the
        overview card's own numbers for this leg. Total = what is left of
        this leg plus every later leg (`after`), so it counts down over the trip."""
        import cv2

        def render(distance_km: float, duration_seconds: float, arrived: bool = False, share: float = 1.0) -> bytes:
            if arrived:
                share = 0.0  # the countdown ends on 0 (see pedestrian's arrival hold)
            distance_km, duration_seconds = share * leg[0], share * leg[1]
            left_km, left_s = distance_km, duration_seconds
            card = self.graphics.render_summary_card(
                distance_km=distance_km,
                duration_seconds=duration_seconds,
                mode_breakdown={mode: distance_km},
                mode_duration={mode: duration_seconds},
                out_scale=tuning.RESIDENTIAL_HUD_CARD_SCALE,
                total_km=left_km + after[0],
                total_seconds=left_s + after[1],
            )
            ok, buf = cv2.imencode(".png", card)
            if not ok:
                raise RuntimeError("Failed to encode leg HUD card")
            return buf.tobytes()

        return render

    def _render_residential_pydeck(self, res_sequence: List[Dict], fps: int) -> List[str]:
        """GeoJsonLayer-driven alternative to SpatialRenderer.render_waypoints (flat top-down): a pedestrian-scale
        chase camera, one clip per leg.

        Reuses each res_sequence entry's own real `lats`/`lons` (already resolved by render_step.py, including
        ferry-leg cached geometry and stop-by-merged legs) and mirrors waypoints.py's
        `02_waypoint_{start_pos+1:02d}_{safe_suffix}.mp4` filename convention so downstream audio-muxing/timeline
        lookups (which parse that number back out of the filename) keep working unmodified.

        Mixed per leg: a leg whose mode is in tuning.RESIDENTIAL_2D_FALLBACK_MODES (currently just airplane) is handed
        to the flat 2D renderer for that leg alone; render_waypoints names its output from the leg's own `start_pos`,
        so it gets the same filename it would have had in a full-sequence run.
        """
        raw_job_config, wp_by_id, waypoint_id_to_idx, attraction_dir = self._read_res_job_config()
        from services.config.sub_course import main_route_lonlat

        context_path = main_route_lonlat(raw_job_config)  # a sub course's legs show the main course faint under them
        mode_speed_kmh = self.spatial_renderer.mode_speed_kmh
        brief_legs = self._course_brief_legs()
        leg_totals = [_leg_distance_and_seconds(r, mode_speed_kmh, brief_legs) for r in res_sequence]
        output_paths = []
        # Street view waypoints: a pop-up photo card on the leg passing nearest, timed by its {view} cues.
        # shortcut: a one-leg re-render only weighs that leg, so a street view near its ends can land on it; fine for now.
        job_config_path = self.config.get("res_route_path")
        street_views = street_view_landmarks(
            raw_job_config.get("street_views") or [],
            [list(zip(r.get("lats"), r.get("lons"))) if r.get("lats") is not None else [] for r in res_sequence],
            Path(job_config_path).parent if job_config_path else Path("."),
            [r.get("street_view_cues") or [] for r in res_sequence],
        )
        ctx = _ResContext(wp_by_id, waypoint_id_to_idx, attraction_dir, context_path, mode_speed_kmh, street_views, leg_totals)
        # begin_substeps/show_item give a live per-leg "[i/N] rendering leg -> label" line for the whole render.
        tracker.begin_substeps(len(res_sequence))
        prev_end_view = None
        for i, res_data in enumerate(res_sequence):
            # Each leg launches its own Chromium; don't start one with no RAM left.
            tuning.ensure_free_ram(f"residential leg {i + 1}", self.config.get("min_free_ram_gb"))
            lats, lons = res_data.get("lats"), res_data.get("lons")
            leg_latlon = list(zip(lats, lons)) if lats is not None and lons is not None else []
            if len(leg_latlon) < 2:
                logger.warning(f"Skipping residential leg {i}: no usable lat/lon track.")
                continue

            leg_labels = [l for l in res_data.get("labels", []) if l]
            dest_label = leg_labels[-1] if leg_labels else video_text.current_labels()["destination_fallback"]
            tracker.show_item(i + 1, f"Rendering residential leg {i + 1}/{len(res_sequence)} -> {dest_label}")
            leg_mode = res_data.get("mode") or "walking"
            leg_mode = tuning.MODE_ALIASES.get(str(leg_mode).lower(), str(leg_mode).lower())

            if leg_mode in tuning.RESIDENTIAL_2D_FALLBACK_MODES:
                logger.info(
                    f"Residential leg {i} is '{leg_mode}' — rendering it with the "
                    "2D SpatialRenderer instead of the chase camera."
                )
                output_paths.extend(
                    self.spatial_renderer.render_waypoints([res_data], fps)
                )
                continue
            plan = self._plan_leg(ctx, i, res_data, res_sequence, leg_latlon, dest_label, leg_mode, prev_end_view)
            prev_end_view = plan.kwargs.get("end_view_path")
            if self.config.get("only_leg_file") is not None and plan.num != self.config["only_leg_file"]:
                continue  # "Make again" for one leg: the others were only needed for what this one takes from them
            output_paths.extend(self._run_leg(ctx, i, plan, res_data, leg_latlon, dest_label))

        return output_paths

    def _read_res_job_config(self) -> Tuple[Dict[str, Any], Dict[Any, Dict[str, Any]], Dict[str, int], Optional[Path]]:
        """(raw job_config, waypoints by id, id -> RAW 0-based index in job_config's "waypoints", attraction dir).
        [NOTE] The index is the one helpers.attraction_output_filename names a waypoint's attraction video with. It is
        built here, not from render_step's res_waypoints (which can have a synthetic start/end PREPENDED and shift every
        position by one), so a connected stop-by's attraction lookup matches the file the pipeline produced."""
        waypoint_id_to_idx: Dict[str, int] = {}
        attraction_dir = None
        raw_job_config: Dict[str, Any] = {}
        wp_by_id: Dict[Any, Dict[str, Any]] = {}
        job_config_path = self.config.get("res_route_path")
        if job_config_path and os.path.exists(job_config_path):
            try:
                with open(job_config_path, "r", encoding="utf-8") as f:
                    raw_job_config = json.load(f)
                wp_by_id = {w.get("id"): w for w in raw_job_config.get("waypoints", []) if isinstance(w, dict)}
                for _idx, _wp in enumerate(raw_job_config.get("waypoints", [])):
                    if _wp.get("id"):
                        waypoint_id_to_idx[_wp["id"]] = _idx
                # Route and attraction outputs are sibling folders under assets/video/; out_dir is the route one.
                attraction_dir = self.out_dir.parent / "attraction"
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"Could not read job_config for attraction-video lookup: {e}")
        return raw_job_config, wp_by_id, waypoint_id_to_idx, attraction_dir

    def _course_brief_legs(self) -> List[Dict[str, Any]]:
        """The course overview's card adds up the brief's legs, not the GPS track."""
        if not (storyboard_for(self.config).course_brief_legs and self.config.get("res_route_path")):
            return []
        from services.localization.route_brief import load_brief
        try:
            return load_brief(self.config["res_route_path"])["legs"]
        except (OSError, ValueError, KeyError) as e:
            logger.warning(f"Could not load the route brief for the leg cards: {e}")
            return []

    @staticmethod
    def _attraction_video_for(ctx: "_ResContext", waypoint_id: Optional[str], label: Optional[str]) -> Optional[str]:
        from services.vdoprocessing.videopipeline.helpers import attraction_output_filename

        if not waypoint_id or waypoint_id not in ctx.waypoint_id_to_idx or ctx.attraction_dir is None:
            return None
        idx = ctx.waypoint_id_to_idx[waypoint_id]
        candidate = ctx.attraction_dir / attraction_output_filename(idx, label or f"waypoint_{idx}")
        return str(candidate) if candidate.exists() else None

    def _landmark_entry(self, ctx: "_ResContext", m: Dict[str, Any]) -> Dict[str, Any]:
        from services.vdoprocessing.videopipeline.audio_step import no_narration_stop

        return {
            "lat": m["lat"], "lon": m.get("lng", m.get("lon")), "label": m.get("label"),
            # A "connectToRoute" stop-by gets the full fullscreen photo-pause as the walker passes it.
            "connect_to_route": bool(m.get("connect_to_route", False)),
            # Only when set: other legs' landmarks (and fingerprints) stay as they were.
            **({"inaccessible": True} if m.get("inaccessible") else {}),
            # Nothing to tell here: its photo only pops up as a card, never fullscreen (as a normal stop with
            # no_narration_stop / `quiet_stop_transition`).
            **({"quiet": True} if no_narration_stop(ctx.wp_by_id.get(m.get("waypoint_id")) or {}) else {}),
            "popup_image": m.get("popup_image"),
            "freeze_seconds": m.get("freeze_seconds"),
            "image_display": "fullscreen",  # residential legs are always fullscreen
            # Its own narration length: pedestrian holds the fullscreen pause at least this long.
            "narration_audio_seconds": m.get("narration_audio_seconds"),
            # Set only when this stop-by already has a GENERATED attraction video: the photo pause then cuts the
            # leg clip instead of shrinking back to resume the walk in place.
            "attraction_video": self._attraction_video_for(ctx, m.get("waypoint_id"), m.get("label")),
            # The photo ends fullscreen and the attraction video dissolves in from it.
            "dissolve_into_attraction": bool(self.config.get("dissolve_into_attraction", False)),
            # Audio-first timing of the walk TOWARD this stop and how long it waits here for the voice.
            "walk_seconds": m.get("walk_seconds"),
            "wait_seconds": m.get("wait_seconds"),
            "pops_after": m.get("pops_after"),
            "waypoint_id": m.get("waypoint_id"),
        }

    def _leg_landmarks(
        self, ctx: "_ResContext", i: int, res_data: Dict[str, Any], leg_mode: str, leg_latlon: List,
    ) -> List[Dict[str, Any]]:
        landmarks = [
            self._landmark_entry(ctx, m)
            for m in res_data.get("mid_markers", [])
            if m.get("lat") is not None and m.get("lng", m.get("lon")) is not None
        ]
        mapillary_token = resolve_mapillary_token()
        if (leg_mode == "walking" and mapillary_token and self.config.get("res_route_path")
                and self.config.get("street_photos_at_turns", tuning.STREET_PHOTOS_AT_TURNS)):
            photo_dir = meta_dir(Path(self.config["res_route_path"]).parent) / "streetview"
            landmarks += attach_cue_spans(clear_of(
                turn_photos([list(p) for p in leg_latlon], photo_dir, mapillary_token),
                ctx.street_views[i], tuning.STREET_VIEW_REPLACES_TURN_PHOTO_M,
            ), res_data.get("turn_cues") or [])
        landmarks += ctx.street_views[i]
        return landmarks

    def _leg_photos(self, ctx: "_ResContext", res_data: Dict[str, Any]) -> "_LegPhotos":
        """The photos that open and close a leg. render_step stashes the destination's popup as the LAST entry of the
        leg's "popups" (a clip only ever ends its route on the arrival stop)."""
        from services.vdoprocessing.videopipeline.audio_step import no_narration_stop

        dest_popup = next((p for p in (res_data.get("popups") or []) if p), None) or {}
        # The leg ends on this photo and the destination's attraction video (dissolve) opens on the waypoint's FIRST
        # image: with attraction videos on the leg shows the first image too, else the last one.
        dest_popup_image = (
            dest_popup.get("popup_image")
            if self.config.get("enable_attraction_videos", True)
            else dest_popup.get("popup_image_last")
        ) or dest_popup.get("popup_image_last") or dest_popup.get("popup_image")
        dest_freeze_seconds = dest_popup.get("freeze_seconds")
        dest_narration_seconds = dest_popup.get("audio_duration")
        # A return stop only pops its photo up as a card (its place had its fullscreen visit already); so does a
        # place with nothing to tell (no attraction clip follows): the walk goes on.
        dest_wp = ctx.wp_by_id.get(res_data.get("end_waypoint_id"))
        dest_quiet = dest_wp is not None and no_narration_stop(dest_wp)
        dest_image_display = "pip" if res_data.get("dest_is_return") or dest_quiet else "fullscreen"
        if not dest_popup_image:
            # A trailing synthetic end_point leg has no popup of its own: fall back to the last REAL waypoint's photo.
            end_popup = res_data.get("trip_end_popup") or {}
            dest_popup_image = end_popup.get("popup_image_last") or end_popup.get("popup_image")
            dest_freeze_seconds = end_popup.get("freeze_seconds")
            dest_narration_seconds = end_popup.get("audio_duration")
        # The departure waypoint's popup (render_step's "leg_start_popup"), shown at this leg's own opening.
        start_popup = res_data.get("leg_start_popup") or {}
        return _LegPhotos(
            dest_image=dest_popup_image, dest_freeze=dest_freeze_seconds, dest_narration=dest_narration_seconds,
            dest_display=dest_image_display, dest_quiet=dest_quiet,
            start_image=start_popup.get("popup_image_last") or start_popup.get("popup_image"),
            start_freeze=start_popup.get("freeze_seconds"), start_narration=start_popup.get("audio_duration"),
        )

    def _leg_base_kwargs(
        self, ctx: "_ResContext", res_data: Dict[str, Any], leg_mode: str,
        landmarks: List[Dict[str, Any]], photos: "_LegPhotos",
    ) -> Dict[str, Any]:
        chain, stopbys = _split_stopby_chain(res_data)
        # Narration-synced video length (else a paced distance fallback, see render_step's res_sequence build); real
        # legs run from meters to kilometers, so literal walking pace would make clips seconds to HOURS long. The HUD's
        # remaining-time estimate stays real-world.
        target_duration = res_data.get("travel_duration") or res_data.get("segment_duration")
        return dict(
            mode=leg_mode,
            travel_speed_kmh=_reported_speed_kmh(ctx.mode_speed_kmh, leg_mode),
            # No reserve for the burned caption's band: it squeezed tall/vertical legs for little benefit
            # (LEG_FRAME_BOTTOM_PIN_PX already keeps the start pin's own label clear).
            bottom_reserve_px=0,
            walker_color=res_data.get("line_color"),
            target_duration_seconds=target_duration,
            landmarks=landmarks, route_chain=chain or None, context_path=ctx.context_path,
            **({"stopby_chain": stopbys} if stopbys else {}),
            # Straight-down chase cam (still follows/rotates, never tilts); settings.res_follow_pitch opts into a tilt.
            follow_pitch=self.config.get("res_follow_pitch", 0.0),
            dest_popup_image=photos.dest_image,
            dest_popup_freeze_seconds=photos.dest_freeze,
            dest_popup_narration_seconds=photos.dest_narration,
            start_popup_image=photos.start_image,
            start_popup_freeze_seconds=photos.start_freeze,
            start_popup_narration_seconds=photos.start_narration,
            start_cue_seconds=res_data.get("start_cue_seconds"),
            arrival_photo_hold_seconds=self.config.get("arrival_photo_hold_seconds"),
            arrival_wait_seconds=res_data.get("arrival_wait_seconds"),
            dest_image_display=photos.dest_display,
            start_pin=res_data.get("start_pin"),
            dest_pin=res_data.get("dest_pin"),
            total_stops=res_data.get("total_stops"),
            stop_number=res_data.get("stop_number"),
            theme=self.graphics.theme,
        )

    def _add_optional_leg_kwargs(self, leg_kwargs: Dict[str, Any], res_data: Dict[str, Any]) -> None:
        """Each only when set, so the other legs keep their fingerprint."""
        if res_data.get("pace_cues"):
            leg_kwargs["pace_cues"] = {
                "spans": res_data["pace_cues"],
                "slow": float(self.config.get("pace_slow_factor") or tuning.PACE_SLOW_FACTOR),
                "fast": float(self.config.get("pace_fast_factor") or tuning.PACE_FAST_FACTOR),
            }
        if res_data.get("at_cues"):
            leg_kwargs["at_cues"] = res_data["at_cues"]
        if res_data.get("piece_start_cues"):
            leg_kwargs["piece_start_cues"] = res_data["piece_start_cues"]
        if self.config.get("mapbox_style_id"):
            leg_kwargs["map_style"] = resolve_map_style(self.config, "mapbox/outdoors-v12")
        if res_data.get("elevations"):  # the heatmap is on
            leg_kwargs["leg_elevations"] = res_data["elevations"]
        slow = storyboard_for(self.config).arrival_slow_seconds
        if slow is not None:  # the walker slows down before each stop
            leg_kwargs["arrival_slow_seconds"] = slow

    def _add_leg_joins(
        self, leg_kwargs: Dict[str, Any], ctx: "_ResContext", i: int, res_data: Dict[str, Any],
        res_sequence: List[Dict], photos: "_LegPhotos", prev_end_view: Optional[str], leg_glob_prefix: str,
    ) -> None:
        """How this leg opens and closes against its neighbours: it carries on from the leg before's last camera
        (setting quiet_stop_transition "zoom" turns that off, except at return stops)."""
        from services.vdoprocessing.videopipeline.audio_step import no_narration_stop

        # A return stop's photo never opens a leg fullscreen.
        start_wp = ctx.wp_by_id.get(res_data.get("start_waypoint_id"))
        start_quiet = start_wp is not None and no_narration_stop(start_wp)  # no fullscreen came before this leg
        if (res_data.get("start_is_return") or (res_data.get("dest_is_return") and not photos.start_image)
                or start_quiet):
            leg_kwargs["opening_photo"] = False
        # Joined legs: this leg's last frame is the next one's first.
        next_leg = res_sequence[i + 1] if i + 1 < len(res_sequence) else {}
        # "zoom": legs open and close on their own (no slide, no carried card).
        slide = self.config.get("quiet_stop_transition", "slide") != "zoom"
        # Return stops keep their own joins: the pair, or a stop with nothing to tell.
        return_pair = bool(res_data.get("dest_is_return") and next_leg.get("start_is_return"))
        slides_on = slide and _legs_join(res_data, next_leg) and (
            photos.dest_quiet or not next_leg.get("start_is_return"))
        if return_pair or slides_on:
            leg_kwargs["end_view_path"] = str(self.out_dir / f"{leg_glob_prefix}endview.json")
        # Marks a join the timeline cuts (the same frame on both sides, and between this leg's own pieces): only a
        # return pair dissolves, to swap the route lines.
        no_fade = self.out_dir / f"{leg_glob_prefix}nofade"
        if slide and (photos.dest_quiet or (slides_on and not return_pair)):
            no_fade.touch()
        else:
            no_fade.unlink(missing_ok=True)
        if photos.dest_quiet and slide and photos.dest_image:
            leg_kwargs["hold_end_card"] = True
        prev = res_sequence[i - 1] if i > 0 else {}
        joined = slide and _legs_join(prev, res_data) and (start_quiet or not res_data.get("start_is_return"))
        if (res_data.get("start_is_return") or joined) and prev_end_view:
            try:
                leg_kwargs["opening_view"] = json.loads(Path(prev_end_view).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        if joined and "opening_view" in leg_kwargs:
            # The walk goes on: the leg before stays drawn as walked while the camera moves into this leg's framing.
            leg_kwargs["prior_trail"] = [[float(a), float(b)] for a, b in zip(prev["lats"], prev["lons"])]

    def _plan_leg(
        self, ctx: "_ResContext", i: int, res_data: Dict[str, Any], res_sequence: List[Dict],
        leg_latlon: List, dest_label: str, leg_mode: str, prev_end_view: Optional[str],
    ) -> "_LegPlan":
        landmarks = self._leg_landmarks(ctx, i, res_data, leg_mode, leg_latlon)
        # Each connectToRoute landmark cuts the leg into one more piece, piece[k] being the walk TOWARD landmark[k] (the
        # last piece targets the leg's destination). Written as a sidecar JSON so leg_pieces.py's narration split knows
        # which waypoint's narration belongs to which piece.
        connected_landmark_ids = cut_landmark_ids(res_data.get("mid_markers", []))
        photos = self._leg_photos(ctx, res_data)
        safe_suffix = (
            "".join(c for c in str(dest_label) if c.isalnum() or c in (" ", "_", "-"))
            .strip()
            .replace(" ", "_")
            or f"leg{i + 1}"
        )
        leg_file_num = res_data.get("start_pos")
        leg_file_num = (leg_file_num + 1) if leg_file_num is not None else (i + 1)
        # A connected stop-by can split ONE leg into several files sharing this "02_waypoint_{N:02d}_" prefix, so
        # "already rendered" is checked by the whole prefix.
        leg_glob_prefix = f"02_waypoint_{leg_file_num:02d}_"
        leg_kwargs = self._leg_base_kwargs(ctx, res_data, leg_mode, landmarks, photos)
        self._add_optional_leg_kwargs(leg_kwargs, res_data)
        self._add_leg_joins(leg_kwargs, ctx, i, res_data, res_sequence, photos, prev_end_view, leg_glob_prefix)
        return _LegPlan(
            kwargs=leg_kwargs, num=leg_file_num, prefix=leg_glob_prefix,
            output_path=str(self.out_dir / f"{leg_glob_prefix}{safe_suffix}.mp4"),
            connected_ids=connected_landmark_ids, dest_id=res_data.get("end_waypoint_id"),
        )

    def _write_piece_plan(self, plan: "_LegPlan", piece_paths) -> None:
        pieces = {
            "pieces": [
                {
                    "file": Path(p).name,
                    "target_waypoint_id": (
                        plan.connected_ids[idx] if idx < len(plan.connected_ids) else plan.dest_id
                    ),
                }
                for idx, p in enumerate(piece_paths)
            ]
        }
        plan_path = self.out_dir / f"02_waypoint_{plan.num:02d}_pieces.json"
        try:
            write_json_atomic(plan_path, pieces, indent=None)
        except OSError:
            pass

    def _reusable_leg_files(
        self, plan: "_LegPlan", leg_latlon: List, dest_label: str, res_data: Dict[str, Any], leg_fingerprint: str,
    ) -> "_LegReuse":
        """Files to reuse, stale files to remove after a re-render, ignored changes and the leg's parts. Existing files are only reused
        when they match what they were rendered from: a bare existence check kept legs rendered with an old walk
        timing forever."""
        leg_kwargs, leg_file_num, leg_glob_prefix = plan.kwargs, plan.num, plan.prefix
        fingerprint_path = self.out_dir / f"{leg_glob_prefix}inputs.json"
        existing_leg_files = (
            leg_clips(self.out_dir, f"{leg_glob_prefix}*.mp4") if self.config.get("checkpoint_enabled", False) else []
        )
        if existing_leg_files and not pieces_complete(existing_leg_files):
            logger.info("Residential leg %d is missing a piece — rendering it again.", leg_file_num)
            existing_leg_files = []
        leg_parts = _leg_fingerprint_parts(
            leg_latlon, dest_label, leg_kwargs, route_inputs=res_data.get("route_inputs"),
        )
        stored_inputs = _stored_leg_inputs(fingerprint_path)
        old_parts = stored_inputs.get("parts") or {}
        changed = sorted(k for k in set(leg_parts) | set(old_parts) if leg_parts.get(k) != old_parts.get(k))
        if old_parts:
            path_changed = leg_changed_parts(leg_parts, old_parts)
        elif stored_inputs.get("fingerprint") != leg_fingerprint:
            path_changed = ["no per-input record from the earlier render"]
        else:
            path_changed = []
        stale_leg_files: List[Path] = []
        if existing_leg_files and path_changed:
            logger.info(
                "Residential leg %d path changed since it was rendered (%s) — re-rendering.",
                leg_file_num, ", ".join(path_changed),
            )
            # Old pieces are removed only after the re-render succeeds, so a killed run keeps the previous clip.
            stale_leg_files = [
                old for old in self.out_dir.glob(f"{leg_glob_prefix}*")
                if old.suffix in (".mp4", ".json") and old.name != fingerprint_path.name
            ]
            # One earlier variant per leg is kept: switching a setting back (the heatmap off and on again) restores it.
            variant_dir = self.out_dir / ".variants" / leg_glob_prefix.rstrip("_")
            existing_leg_files = restore_leg(
                variant_dir, fingerprint_path.name, leg_parts, stale_leg_files + [fingerprint_path], self.out_dir,
            )
            if existing_leg_files:
                logger.info("Residential leg %d: restored the version rendered from these inputs.", leg_file_num)
                stale_leg_files, changed = [], []
            else:
                stash_leg(stale_leg_files + [fingerprint_path], variant_dir)
        return _LegReuse(existing_leg_files, stale_leg_files, changed, leg_parts)

    def _run_leg(
        self, ctx: "_ResContext", i: int, plan: "_LegPlan", res_data: Dict[str, Any], leg_latlon: List,
        dest_label: str,
    ) -> List[str]:
        from services.vdoprocessing.pydeckrecorder.pedestrian import render_residential_leg_pydeck

        leg_kwargs = plan.kwargs
        leg_fingerprint = _leg_fingerprint(leg_latlon, dest_label, leg_kwargs)
        fingerprint_path = self.out_dir / f"{plan.prefix}inputs.json"
        reuse = self._reusable_leg_files(plan, leg_latlon, dest_label, res_data, leg_fingerprint)
        existing_leg_files, stale_leg_files, changed = reuse.files, reuse.stale, reuse.changed
        if existing_leg_files:
            logger.info(
                "Residential leg %d already rendered (%d file(s)) — skipping.%s",
                plan.num, len(existing_leg_files),
                f" Ignored changes: {', '.join(changed)}" if changed else "",
            )
            # Rewritten even on a skip (cheap, no ffmpeg): keeps it in sync with job_config's CURRENT landmark data.
            self._write_piece_plan(plan, [str(p) for p in existing_leg_files])
            return [str(p) for p in existing_leg_files]

        # render_residential_leg_pydeck always returns a LIST: a connected stop-by's pause can cut one leg into
        # several files sharing this prefix ("_cont{n}" per cut); leg_pieces.py splits the leg's narration across them.
        leg_paths = render_residential_leg_pydeck(
            leg_latlon, dest_label, plan.output_path,
            hud_card_png=self._leg_hud_card_png(
                leg_kwargs["mode"], ctx.leg_totals[i],
                after=(sum(km for km, _ in ctx.leg_totals[i + 1:]), sum(s for _, s in ctx.leg_totals[i + 1:])),
            ),
            # Not in leg_kwargs: a token change must not re-render finished legs (see the fingerprint).
            mapbox_key=self._mapbox_token(), **leg_kwargs,
        )
        if leg_paths:
            keep = {Path(p).resolve() for p in leg_paths}
            keep |= {Path(p).with_suffix(".timing.json").resolve() for p in leg_paths}
            if leg_kwargs.get("end_view_path"):
                keep.add(Path(leg_kwargs["end_view_path"]).resolve())  # just written for the next leg: not stale
            for old in stale_leg_files:
                if old.resolve() not in keep:
                    old.unlink(missing_ok=True)
            if not leg_kwargs.get("end_view_path"):
                # The timeline dissolves into the next leg wherever an end view is left.
                (self.out_dir / f"{plan.prefix}endview.json").unlink(missing_ok=True)
            write_json_atomic(fingerprint_path, {"fingerprint": leg_fingerprint, "parts": reuse.parts}, indent=None)
        self._write_piece_plan(plan, leg_paths)
        return leg_paths

    def _overview_clip(
        self, img_path: str, points: List, labels: List, popups: List, fps: int, summary: Optional[Dict],
        point_modes: Optional[List[str]], point_colors: Optional[List], kwargs: Dict[str, Any],
    ) -> Optional[str]:
        """[NOTE] [Core] The GeoJsonLayer pydeck overview (_render_overview_pydeck) renders on the GPU and does not
        follow the narration's cues (stop holds, stop-by timing, ending fitted to the voice) - the 2D spatial_renderer
        path does; settings.use_pydeck_overview selects it (tuning.DEFAULT_USE_PYDECK_OVERVIEW). The "course"
        overview exists only in the 2D renderer."""
        if (
            self.config.get("use_pydeck_overview", tuning.DEFAULT_USE_PYDECK_OVERVIEW)
            and storyboard_for(self.config).pydeck_allowed
        ):
            logger.info("Rendering Overview using GeoJsonLayer PyDeck...")
            return self._render_overview_pydeck(
                img_path, points, labels, popups,
                extent=kwargs.get("overview_extent"), fps=fps,
            )
        return self.spatial_renderer.render_overview(
            img_path, points, labels, popups, fps, summary=summary, point_modes=point_modes,
            point_colors=point_colors,
            bounding_box=kwargs.get("overview_bounding_box"),
            extent=kwargs.get("overview_extent"),
        )

    def _hold_overview_end(self, overview_path: str) -> None:
        """Skips the extra hold when the clip already ended itself on a blur-out (that blur is its last frame) or
        was reused."""
        hold_seconds = self.config.get("summary_hold", DEFAULT_SUMMARY_HOLD_SECONDS)
        if self.config.get("overview_audio_seconds") and self.config.get("overview_cue_seconds"):
            # Narrated: the renderer already fitted the ending to the voice (overview_timing.fit_ending); a fixed
            # hold would run past it. Only an unspoken gap left (the voice still going) is held - the mux holds that too.
            rendered = getattr(self.spatial_renderer, "last_rendered_seconds", None)
            hold_seconds = max(
                0.0, float(self.config["overview_audio_seconds"]) - float(rendered or 0.0)
            ) if rendered else 0.0
            if hold_seconds < 0.1:  # a rounding remainder, not worth a re-encode
                hold_seconds = 0.0
        reused = getattr(self.spatial_renderer, "last_overview_reused", False)
        if not reused and not self.spatial_renderer.last_ending_hard_ended:
            self._freeze_video_end(overview_path, hold_seconds=hold_seconds)

    def render(
        self,
        img_path: str,
        points: List,
        labels: List,
        popups: List,
        fps: int = 30,
        res_sequence: Optional[List] = None,
        summary: Optional[Dict] = None,
        wp_indices: Optional[List[int]] = None,
        point_modes: Optional[List[str]] = None,
        point_colors: Optional[List] = None,
        render_mode: str = "both",
        **kwargs,
    ) -> List[str]:
        """Main rendering orchestrator. Decides which rendering engine to use.

        render_mode ("both"/"overview"/"residential") gates which of the
        two output videos actually gets rendered — "residential" skips the
        overview animation entirely (render_overview is never even called,
        so none of its compute is paid for); "overview" relies on
        render_step.py having already left res_sequence empty, but is also
        checked explicitly here so a caller that passes render_mode
        without also gating res_sequence itself still gets isolated
        output."""
        if not os.path.exists(img_path):
            logger.error(f"Background path does not exist: {img_path}")
            raise FileNotFoundError(f"Background path does not exist: {img_path}")

        output_paths = []

        if render_mode == "recap_frame":
            overview_path = self.spatial_renderer.render_overview(
                img_path, points, labels, popups, fps, summary=summary, point_modes=point_modes,
                point_colors=point_colors,
                bounding_box=kwargs.get("overview_bounding_box"),
                extent=kwargs.get("overview_extent"),
                preview_recap_only=True
            )
            self._commit_overview_checkpoint()
            output_paths.append(overview_path)

        elif render_mode != "residential":
            tracker.show("Rendering overview video...")
            overview_path = self._overview_clip(
                img_path, points, labels, popups, fps, summary, point_modes, point_colors, kwargs,
            )
            tracker.clear()
            if overview_path:
                self._hold_overview_end(overview_path)
                self._commit_overview_checkpoint()
                output_paths.append(overview_path)

        # [NOTE] [Core] Render each waypoint-to-waypoint leg. The GeoJsonLayer
        # PyDeck chase camera (top-down overview -> tilted follow, per leg)
        # is now the DEFAULT residential engine — set use_pydeck_pedestrian
        # to false in a project's settings to opt back into the flat 2D
        # SpatialRenderer.
        if res_sequence and render_mode != "overview":
            if self.config.get("use_pydeck_pedestrian", True):
                logger.info(
                    "Rendering Residential Sequence using GeoJsonLayer PyDeck (chase camera)..."
                )
                output_paths.extend(self._render_residential_pydeck(res_sequence, fps))
            else:
                logger.info(
                    "Rendering Residential Sequence using 2D SpatialRenderer..."
                )
                output_paths.extend(self.spatial_renderer.render_waypoints(res_sequence, fps))

        return output_paths


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--map", required=True)
    parser.add_argument("--route", required=True)
    parser.add_argument("--output", default="data\\outputs\\video")
    parser.add_argument("--duration", type=float, default=None)
    parser.add_argument("--fps", type=int, default=None)
    parser.add_argument("--thickness", type=int, default=None)
    parser.add_argument("--radius", type=int, default=None)
    parser.add_argument("--res-map", default=None)
    parser.add_argument("--res-route", default=None)
    parser.add_argument("--res-duration", type=float, default=12.0)
    parser.add_argument("--pause", type=float, default=2.0)
    parser.add_argument("--summary-json", default=None)
    parser.add_argument("--summary-hold", type=float, default=4.0)
    parser.add_argument("--summary-fade", type=float, default=0.5)
    return parser.parse_args()


def _apply_job_config_labels(output: str, res_labels: List) -> None:
    """[HACK] [IO] Walks up from the output dir looking for job_config.json since this CLI has no direct reference
    to the job — swallows any read failure and just falls back to the raw route labels."""
    try:
        out_path = Path(output)
        job_paths = [
            out_path / "job_config.json",
            out_path.parent / "job_config.json",
        ]

        for job_config_path in job_paths:
            if job_config_path.exists():
                with open(job_config_path, "r", encoding="utf-8") as f:
                    job_data = json.load(f)
                    start_lbl = job_data.get("start_point", {}).get("label")
                    end_lbl = job_data.get("end_point", {}).get("label")

                    if start_lbl and len(res_labels) > 0:
                        res_labels[0] = start_lbl
                    if end_lbl and len(res_labels) > 1:
                        res_labels[-1] = end_lbl
                break
    except Exception as e:
        logger.warning(
            f"Could not read labels from job_config.json for residential map: {e}"
        )


def _cli_res_sequence(animator: RouteAnimator, args: argparse.Namespace) -> Optional[List[Dict[str, Any]]]:
    if not (args.res_route and args.res_map):
        return None
    res_points, res_labels, res_popups, _ = animator.load_route_data(args.res_route)
    _apply_job_config_labels(args.output, res_labels)
    return [
        {
            "img_path": args.res_map,
            "points": res_points,
            "labels": res_labels,
            "popups": res_popups,
        }
    ]


def main():
    args = _parse_args()

    config = {
        "output_dir": args.output,
        "pause": args.pause,
        "summary_hold": args.summary_hold,
        "summary_fade": args.summary_fade,
        "res_duration": args.res_duration,
    }

    animator = RouteAnimator(config)
    points, labels, popups, settings = animator.load_route_data(args.route)

    animator.config["fps"] = args.fps or settings.get("fps", 30)
    animator.config["duration"] = args.duration or settings.get("duration_seconds", 8)
    animator.graphics.line_thickness = args.thickness or settings.get(
        "line_thickness", DEFAULT_LINE_THICKNESS
    )
    animator.graphics.marker_radius = args.radius or settings.get(
        "marker_radius", DEFAULT_MARKER_RADIUS
    )

    res_sequence = _cli_res_sequence(animator, args)

    summary = (
        json.load(open(args.summary_json, "r", encoding="utf-8"))
        if args.summary_json
        else None
    )

    # [NOTE] [Core] Forces the route's first/last points into wp_indices even without a popup so storyboard slicing always has a defined start/end leg.
    wp_indices = [i for i, pop in enumerate(popups) if pop is not None]

    if 0 not in wp_indices:
        wp_indices.insert(0, 0)
    if len(points) - 1 not in wp_indices:
        wp_indices.append(len(points) - 1)

    output_files = animator.render(
        img_path=args.map,
        points=points,
        labels=labels,
        popups=popups,
        res_sequence=res_sequence,
        summary=summary,
        wp_indices=wp_indices,
    )

    logger.info(f"Rendered {len(output_files)} file(s):")
    for f in output_files:
        logger.info(f"   {f}")


if __name__ == "__main__":
    main()