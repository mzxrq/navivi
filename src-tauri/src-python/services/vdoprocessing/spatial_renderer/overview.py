"""The overview map render entry point: sets up the route (labels, speed-
weighted path, intro beat), delegates the frame-by-frame animation to
_OverviewAnimationMixin, then closes out with the recap/summary/ending
highlight. The mode-breakpoint/path-pacing helpers live in
overview_pacing.py and the animation loop itself in overview_animation.py —
both split out of this file to keep it to the setup/wrap-up orchestration."""

import functools
import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

import cv2
import numpy as np

from services import tuning, video_text
from services.mapfetcher.mapgeometry import RouteGeometryProcessor
from services.vdoprocessing.route_inputs import photo_inputs_hash, returns_to, route_inputs_hash
from services.vdoprocessing.storyboard import for_config as storyboard_for
from services.vdoprocessing.vdoexporter import VideoExporter

from .base import logger
from .card_circles import densify
from .cluster_zoom import WalkCamera, cluster_views, pin_width
from .overview_timing import (
    AUDIO_MATCH_TOLERANCE_SECONDS,
    MAX_WALK_SPEEDUP,
    MIN_STOP_GAP_FRAMES,
    animation_frames,
    ending_seconds,
    fit_ending,
    intro_card_hold_frames,
    intro_frame_count,
    cap_segments,
    stop_targets,
    warp_controls,
    warp_path,
)


def _output_is_valid(path, min_bytes: int = 1024) -> bool:
    """Local copy of videopipeline/helpers.py's output_is_valid — this
    package can't import that module (videopipeline/__init__.py eagerly
    imports render_step.py, which imports spatial_renderer, so the reverse
    import would be circular; see helpers.py's own PIPELINE_LABELS note)."""
    try:
        p = Path(path)
        return p.is_file() and p.stat().st_size >= min_bytes
    except OSError:
        return False


# Bump when the overview's rendering code changes what it draws, so
# checkpointed overviews made by older code are re-rendered.
# v72: a badge resting on the route by its own stop costs less (_ROUTE_COVER_PULL_PX 260 -> 180): stop 1 stays with 2, 3.
# v71: the walker / ferry passes behind the badges and cards, not over them.
# v70: all of one zoom's photo cards share one size (the largest at which every one fits).
# v69: zoomed photo cards ring the group (out from the middle of the pins through their own), clear of pins and route;
# cards popping during a zoom-out are cut, as before v67.
# v68: zoomed photo cards shrink in a crowd (to half) until each fits right beside its own pin, clear of the rest.
# v67: a photo card popping once a zoom-out has begun is shown, not cut before it ever appeared.
# v66: course badges use the walk recap's clutter pull, numbered stops take their nearest cells, and a band of
# columns slides its row off the route and pins (Tomogashima: 4-7 left of the island, 8-11 right of it).
# v65: zoomed photo cards keep off the route line (nearest clear spot, still beside the pin).
# v64: pill badges of a cluster of numbered stops take the cells nearest their own pins (no one-block lock).
# v63: the trace no longer waits at a zoom (it rushed to catch up): a card still up at the zoom-out is cut there;
# a closed place the route loops around (神島) gets its badge beside its pin, on the line if need be.
# v62: zoomed cards stay near their pin; numbered recap badges are no longer pulled out of their S, 1, 2 … order.
# v61: zoomed photo cards also try the rings further out, so a crowd of them no longer covers one another.
# v60: a course zoom's card hold stops at the trace head's exit from the view (it ran the zoom-out late, the ferry left frame).
# v59: a badge across the route from its pin comes back beside it, a course zoom waits for its last card, and a pin
# nudged apart from its neighbours slides along the route instead of off it; v58: no white
# halo on the ferry sprite, and zoomed-in course cards keep off each other; v57: the course style arranges its pill badges the way the recap does (no leader lines, packed tight, over the map's
# clear space), a reserved box over the TOP of the badge band shortens its columns instead of wiping them out, and its
# stops are plain colour dots; v56: top HUD panels 1.5x bigger; v55: the recap sits on a plain plate and arranges its
# badges on one lattice in walked order (see CLAUDE.md "overview recap's pill badges"); v54: a return stop takes no
# number of its own. Older history: git log.
OVERVIEW_RENDER_VERSION = 83  # v83: 3D map background, cluster zoom in every style; v82: course sub course
# The overview is reused unless one of these changed (or the file is missing).
# route_waypoints, not the drawn line: see services/vdoprocessing/route_inputs.py.
# The narration timings too: the walk stops at the voice's cues, so new cue seconds need a new video.
_OVERVIEW_CHECKPOINT_PARTS = (
    "render_version", "route_waypoints", "photos", "config.overview_cue_seconds", "config.overview_audio_seconds",
    "job_config.map_language", "video_text", "config.sub_course_overview",
)
# Rendered before route_waypoints was recorded: fall back to the drawn line.
_LEGACY_CHECKPOINT_PARTS = ("render_version", "arg.points", "arg.point_modes")
# Config flags about the checkpoint itself, not the picture.
_FINGERPRINT_SKIP_CONFIG = {"checkpoint_enabled", "overview_rerender"}
# Waypoint fields only the walking legs/audio use; the overview never reads them.
_FINGERPRINT_SKIP_WAYPOINT = {"narration", "arrivingNarration", "attractionNarration", "audioUrl"}
_OBJECT_ADDRESS_RE = re.compile(r" at 0x[0-9a-fA-F]+")


def _fingerprint_plain(obj):
    if isinstance(obj, np.ndarray):
        return "ndarray:" + hashlib.sha256(np.ascontiguousarray(obj).tobytes()).hexdigest()
    if hasattr(obj, "tolist"):
        return obj.tolist()
    return _OBJECT_ADDRESS_RE.sub("", str(obj))


def _fingerprint_hash(obj) -> str:
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=_fingerprint_plain)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _overview_fingerprint_parts(config: Dict, job_config: Optional[Dict], bg_path, render_args: Dict) -> Dict[str, str]:
    """Short hash per overview input, so a re-render can say what changed."""
    parts: Dict[str, str] = {"render_version": str(OVERVIEW_RENDER_VERSION)}
    parts["storyboard"] = _fingerprint_hash(repr(storyboard_for(config or {})))[:16]  # an edited file renders again
    try:
        parts["background_image"] = hashlib.sha256(Path(bg_path).read_bytes()).hexdigest()[:16]
    except OSError:
        parts["background_image"] = "missing"
    for key, value in render_args.items():
        parts[f"arg.{key}"] = _fingerprint_hash(value)[:16]
    parts["photos"] = photo_inputs_hash(render_args.get("popups"))
    if video_text.current_language() != video_text.DEFAULT_LANGUAGE:
        parts["video_text"] = video_text.current_language()  # absent for Japanese: old overviews stay valid
    for key, value in (config or {}).items():
        if key not in _FINGERPRINT_SKIP_CONFIG:
            parts[f"config.{key}"] = _fingerprint_hash(value)[:16]
    for key, value in (job_config or {}).items():
        if key == "updated_at":
            continue
        if key == "waypoints" and isinstance(value, list):
            parts["route_waypoints"] = route_inputs_hash(value)
            for i, wp in enumerate(value):
                if isinstance(wp, dict):
                    wp = {k: v for k, v in wp.items() if k not in _FINGERPRINT_SKIP_WAYPOINT}
                parts[f"job_config.waypoints[{i}]"] = _fingerprint_hash(wp)[:16]
        else:
            parts[f"job_config.{key}"] = _fingerprint_hash(value)[:16]
    return parts

def _read_overview_inputs(path: Path) -> Dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_overview_fingerprint(inputs_path: Path, fingerprint: str, fingerprint_parts: Dict[str, str]) -> None:
    try:
        inputs_path.write_text(
            json.dumps({"fingerprint": fingerprint, "parts": fingerprint_parts}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning("Could not write overview fingerprint: %s", e)


def _checkpoint_reusable(
    enabled: bool, overview_path: str, inputs_path: Path, fingerprint_parts: Dict[str, str]
) -> bool:
    """True when the finished overview file's route inputs are unchanged since it was rendered."""
    if not (enabled and _output_is_valid(overview_path)):
        return False
    old_parts = _read_overview_inputs(inputs_path).get("parts") or {}
    changed = sorted(
        k for k in set(old_parts) | set(fingerprint_parts)
        if old_parts.get(k) != fingerprint_parts.get(k)
    )
    keys = _OVERVIEW_CHECKPOINT_PARTS if "route_waypoints" in old_parts else _LEGACY_CHECKPOINT_PARTS
    route_changed = [k for k in keys if k in changed] if old_parts else [
        "no per-input record from the earlier render"
    ]
    if not route_changed:
        logger.info(
            "Overview route unchanged — reusing %s%s", overview_path,
            f" (ignored changes: {', '.join(changed[:25])})" if changed else "",
        )
        return True
    logger.info(
        "Overview route changed since it was rendered (%s) — re-rendering.",
        ", ".join(route_changed),
    )
    return False


# Overview render tuning constants (none are read from self.config/tuning, they're fixed constants of this render).
_MIN_OVERVIEW_FRAMES = 10  # floor on num_frames even for a very short duration
_ROUTE_LATLON_SAMPLE_STRIDE = 500  # decimation stride for self._route_latlon_path
_ROUTE_OBSTACLE_MAX_POINTS = 400  # cap on the decimated obstacle array's size
_MIN_LEG_DISPLAY_SECONDS = 1.5  # floor on a flow-through popup's own leg_display_seconds
_EXPECTED_FRAME_SEARCH_MARGIN_MIN_FRAMES = 20  # floor on the expected-frame search window
_EXPECTED_FRAME_SEARCH_FRACTION = 0.05  # window size as a fraction of the path's frame count
_DEFAULT_INTRO_FREEZE_SECONDS = 3.0  # used when the start popup sets no freeze_seconds
_INTRO_CLEAN_HOLD_FRACTION_OF_FREEZE = 0.5  # clean-beat hold, as a fraction of intro_freeze_sec
_SUMMARY_CARD_MARGIN_PX = 20  # gap between the summary card and the frame's bottom-right corner
_HUD_TOP, _HUD_SIDE = 20, 32  # where render_overview_hud puts the top bar's panels
# [NOTE] The walk never waits past this for the narration's {start} cue: a long opening line would otherwise hold
# the walker on the clean map well past the intro card's own freeze; the voice finishes it over the moving map.
_MAX_INTRO_WALK_START_SECONDS = 3.0


class _PathScale(NamedTuple):
    """What _estimate_frame searches: the raw waypoint polyline's cumulative distance and the animated path's own."""

    raw_cum: np.ndarray
    raw_total: float
    cum_smooth_dist: Optional[np.ndarray]
    total_smooth_dist: float
    num_frames: int


class _Walk(NamedTuple):
    """The animated path with its distance bookkeeping; leg capping and cue retiming each return a new one."""

    path: object  # smooth_path as _build_overview_path returned it (later: the capped/warped one)
    arr: np.ndarray
    scale: _PathScale

    def with_path(self, path, cum_smooth_dist) -> "_Walk":
        arr = np.asarray(path, dtype=float)
        return _Walk(path, arr, self.scale._replace(cum_smooth_dist=cum_smooth_dist, num_frames=len(arr)))


class _Ending(NamedTuple):
    outro_hold_sec: float
    end_pause_sec: float
    audio_seconds: float
    zoom_follows: bool


class _OverviewJob(NamedTuple):
    """Everything render_overview resolved before the walk video starts (inputs, frame size, cue timing, path)."""

    current_bg: np.ndarray
    w: int
    h: int
    fps: int
    points: List
    popups: List
    summary: Optional[Dict]
    bounding_box: Optional[Dict[str, float]]
    preview_recap_only: bool
    overview_path: str
    audio_cues: Dict
    walk_start_frames: int
    num_frames: int
    mode_breakpoints: object
    smooth_path: object
    cum_smooth_dist: object
    total_smooth_dist: float


class _IntroCards(NamedTuple):
    """The start/stop preview cards of the intro and what is needed to redraw them."""

    cards: List[Dict]
    base_boxes: List
    active_popups: List[Dict]
    n_points: int


def _estimate_frame(scale: _PathScale, point_index: int) -> int:
    """Frame at which the walker has travelled this waypoint's share of the route.

    [NOTE] A pure 1D lookup of "how far travelled" on the speed-weighted path (cum_smooth_dist), with no notion of
    XY position, so a curve passing physically close to some OTHER point earlier can't fool it. Falls back to a
    frame-count fraction when there is no mode data to have produced cum_smooth_dist."""
    frac = scale.raw_cum[point_index] / scale.raw_total
    if scale.cum_smooth_dist is not None:
        target_dist = frac * scale.total_smooth_dist
        return int(np.searchsorted(scale.cum_smooth_dist, target_dist))
    return int(frac * (scale.num_frames - 1))


def _initial_walk(points, smooth_path, cum_smooth_dist, total_smooth_dist) -> _Walk:
    """Each waypoint's fraction of the route's physical length is taken over the raw polyline, so a route that
    loops or self-crosses doesn't affect it."""
    arr = np.asarray(smooth_path, dtype=float)
    raw_seg = np.hypot(
        np.diff([p[0] for p in points]), np.diff([p[1] for p in points])
    )
    raw_cum = np.concatenate([[0.0], np.cumsum(raw_seg)])
    raw_total = raw_cum[-1] if raw_cum[-1] > 0 else 1.0
    return _Walk(smooth_path, arr, _PathScale(raw_cum, raw_total, cum_smooth_dist, total_smooth_dist, len(arr)))


def _is_numbered_stop(ap: Dict, stop_popup: Optional[Dict]) -> bool:
    return (
        ap["index"] != 0 and not ap["data"].get("is_stopby") and not ap.get("is_return")
        and (not stop_popup or ap["index"] != stop_popup["index"])
    )


def _timing(config: Dict, name: str) -> float:
    """settings.overview_<name>, else the style's storyboard timing."""
    return float(config.get(f"overview_{name}", storyboard_for(config).timings[name]))


def _intro_cue_walk_frames(popups: List, audio_cues: Dict, config: Dict, fps: int) -> int:
    """Frames before the walk sets off when the narration has cues: the intro's length, or the {start} cue."""
    first = popups[0] if popups else None
    if first:
        intro_freeze = _DEFAULT_INTRO_FREEZE_SECONDS
        if "freeze_seconds" in first:
            intro_freeze = max(float(first["freeze_seconds"]), tuning.POPUP_MIN_DISPLAY_SECONDS)
        clean_hold = min(
            intro_freeze * _INTRO_CLEAN_HOLD_FRACTION_OF_FREEZE,
            _timing(config, "intro_clean_hold_seconds"),
        )
        return intro_frame_count(
            intro_freeze, clean_hold, max(1, int(tuning.POPUP_FADE_SECONDS * fps)), fps,
            start_cue_sec=audio_cues.get("start"),
        )
    if audio_cues.get("start") is not None:
        cue_frames = int(round(audio_cues["start"] * fps))
        cap_frames = int(round(_MAX_INTRO_WALK_START_SECONDS * fps))
        return max(0, min(cue_frames, cap_frames))
    return 0


def _cue_walk_timing(popups: List, audio_cues: Dict, config: Dict, fps: int, num_frames: int) -> Tuple[int, int]:
    """(walk_start_frames, num_frames) once the narration's {start}/{n}/{end} cues (seconds of the real audio, see
    overview_timing.py) are taken in. Nothing is sped up to make the video match the length of the voice."""
    walk_start_frames = _intro_cue_walk_frames(popups, audio_cues, config, fps)
    needed = animation_frames(audio_cues, walk_start_frames, fps)
    if needed and "end" in audio_cues and not any(str(k).isdigit() for k in audio_cues):
        # No stop cues (a one-line script): the whole walk fits {start}…{end}, as in the course style.
        num_frames = max(_MIN_OVERVIEW_FRAMES, needed)
    else:
        num_frames = max(num_frames, needed)
    logger.info(
        "Overview follows its narration cues %s: walk starts at %.1fs and takes %.1fs.",
        sorted(audio_cues), walk_start_frames / fps, num_frames / fps,
    )
    return walk_start_frames, num_frames


def _overview_endpoint_labels(out_dir: Path) -> Tuple[str, str]:
    """The start/end names: the nearest job_config.json's own start_point/end_point labels, else the localized ones."""
    _vt = video_text.current_labels()
    start_label, end_label = _vt["overview_start"], _vt["overview_end"]
    for ancestor_dir in [out_dir] + list(out_dir.parents):
        potential_path = ancestor_dir / "job_config.json"
        if potential_path.exists():
            try:
                with open(potential_path, "r", encoding="utf-8") as f:
                    job_data = json.load(f)
                    start_label = job_data.get("start_point", {}).get("label", start_label)
                    end_label = job_data.get("end_point", {}).get("label", end_label)
            except Exception:
                pass
            break
    return start_label, end_label


def _clean_labels(labels: List, points: List, start_label, end_label) -> List:
    cleaned_labels = []
    for i, lbl in enumerate(labels):
        if i == 0:
            cleaned_labels.append(start_label)
        elif i == len(points) - 1:
            cleaned_labels.append(end_label)
        else:
            cleaned_labels.append(video_text.strip_waypoint_prefixes(lbl) if lbl else None)
    return cleaned_labels


def _route_latlon_samples(smooth_path, extent, w: int, h: int):
    """[NOTE] Stashed for _render_ending_highlight, which redraws the route on its own close-up tile (another
    extent): reprojected from this animated path's pixels via THIS render's extent, the only one they mean anything
    against. None without an extent (the highlight then draws no line)."""
    if extent is None:
        return None
    return [
        RouteGeometryProcessor.pixel_to_latlon(p[0], p[1], extent, w, h)
        for p in smooth_path[:: max(1, len(smooth_path) // _ROUTE_LATLON_SAMPLE_STRIDE)]
    ]


def _build_active_popups(points: List, popups: List, cleaned_labels: List) -> List[Dict]:
    return [
        {
            "x": points[i][0],
            "y": points[i][1],
            "data": popups[i],
            "label": cleaned_labels[i],
            "index": i,
        }
        for i in range(len(points))
        if popups and popups[i] is not None
    ]


def _reproject_popups(active_popups: List[Dict], extent, w: int, h: int) -> None:
    """[NOTE] points[i] is the nearest point on the RECORDED TRACK, which is visibly off for a stop-by seen from a
    distance and measurably off even for a visited waypoint (sparse or road-snapped track). Each waypoint's own
    lat/lng (render_step.py's route_popups) is reprojected onto this same background so it sits where it really is."""
    for ap in active_popups:
        lat, lng = ap["data"].get("lat"), ap["data"].get("lng")
        if lat is None or lng is None:
            continue
        px, py = RouteGeometryProcessor.project_latlon_to_pixel(lat, lng, extent, w, h)
        ap["x"], ap["y"] = px, py


def _number_popups(active_popups: List[Dict], points: List) -> None:
    """1-based visit order for each pin; the start (index 0) and stop-bys take no number (they show "S" / "+1"), and
    a return stop shows the number of the stop it comes back to — so it also has no {n} cue (is_return).
    Matches the map editor's own MapArea.tsx normalIndex."""
    order = 0
    popup_places = [ap["data"] for ap in active_popups]
    for seq, ap in enumerate(active_popups):
        # The walker passes every stop-by, connected or not (route_inputs.stop_is_numbered is the same rule).
        if ap["data"].get("is_stopby") or ap["index"] == 0:
            ap["order"] = order  # not incremented, but never missing for a generic ap["order"] read
            continue
        back = returns_to(popup_places, seq) if ap["index"] != len(points) - 1 else None
        if back is not None:
            ap["is_return"] = True
            ap["order"] = active_popups[back]["order"]
            continue
        order += 1
        ap["order"] = order


def _apply_job_overrides(active_popups: List[Dict], job_waypoints: List[Dict]) -> None:
    """[NOTE] job_config's "waypoints" lines up 1:1, in order, with active_popups (both include start and end), so
    they are zipped by enumerate() position — NOT by popup["index"], which is a position in the animated path."""
    for i, popup in enumerate(active_popups):
        if i >= len(job_waypoints):
            continue
        jw = job_waypoints[i]
        if "image_display" in jw and popup["data"].get("image_display", "box") == "box":
            popup["data"]["image_display"] = jw["image_display"]
        if "popup_video" in jw and not popup["data"].get("popup_video"):
            popup["data"]["popup_video"] = jw["popup_video"]
        # Waypoints flow through by default; "freeze_frame": true opts one back into the held-frame arrival pause.
        if "freeze_frame" in jw:
            popup["data"]["freeze_frame"] = bool(jw["freeze_frame"])


def _route_obstacle_array(route_avoid_points: List) -> np.ndarray:
    """The route footprint as a decimated array, so _layout_beside_popups can cheaply keep a card off the route."""
    arr = np.asarray(route_avoid_points, dtype=float)
    if len(arr) > _ROUTE_OBSTACLE_MAX_POINTS:
        step = max(1, len(arr) // _ROUTE_OBSTACLE_MAX_POINTS)
        arr = arr[::step]
    return arr


def _set_cue_waits(active_popups: List[Dict], stop_popup: Optional[Dict], audio_cues: Dict, config: Dict, fps: int) -> None:
    # A cue at the start of a sentence: the walker waits at that stop a moment (popup fading in) to stay in step.
    wait_tags = {str(t) for t in (config.get("overview_cue_wait_tags") or [])}
    wait_frames = int(fps * _timing(config, "cue_wait_seconds"))
    for ap in active_popups:
        numbered = _is_numbered_stop(ap, stop_popup)
        ap["cue_wait_frames"] = (
            wait_frames if audio_cues and numbered and str(ap.get("order")) in wait_tags
            and str(ap.get("order")) in audio_cues else 0
        )
        # A {go} after the stop's cue: the walker stops for the whole description ({n} to {go}), then heads on.
        arrive_at = audio_cues.get(str(ap.get("order")))
        depart_at = audio_cues.get(f"go{ap.get('order')}")
        if numbered and arrive_at is not None and depart_at is not None and depart_at > arrive_at:
            ap["cue_wait_frames"] = int(round((depart_at - arrive_at) * fps))
        # "Pause at Location" off: the walker walks on while the voice keeps talking.
        ap["no_pause"] = not ap["data"].get("pause_at_waypoint", True)
        if ap["no_pause"]:
            ap["cue_wait_frames"] = 0


def _cap_legs(walk: _Walk, active_popups: List[Dict], cap_frames: int, fps: int) -> _Walk:
    """No leg between two waypoints (start and end included) animates for longer than cap_frames: a longer one is
    played faster."""
    if cap_frames <= 0:
        return walk
    n = walk.scale.num_frames
    marks = [0, n - 1] + [
        min(n - 1, _estimate_frame(walk.scale, ap["index"]))
        for ap in active_popups
        if ap["index"] != 0 and not ap["data"].get("is_stopby")
    ]
    capped, capped_cum = cap_segments(walk.arr, walk.scale.cum_smooth_dist, marks, cap_frames)
    if len(capped) == n:
        return walk
    logger.info(
        "Overview legs capped at %.0fs: walk %.1fs -> %.1fs.",
        cap_frames / fps, n / fps, len(capped) / fps,
    )
    return walk.with_path(capped, capped_cum)


def _hold_frames(ap: Dict, fps: int, post_arrival_hold_seconds: float) -> int:
    """Frames a popup that freezes the map (or a stop-by batch) adds ahead of the stops after it."""
    group = ap.get("stopby_group") or []
    if not (ap["data"].get("freeze_frame", False) or group):
        return ap.get("cue_wait_frames", 0)  # the wait at a cued stop
    held = min(len(group), tuning.STOPBY_BATCH_MAX_HELD)
    return int(fps * (
        float(post_arrival_hold_seconds)
        + max(float(ap["data"].get("freeze_seconds", 4.0)), tuning.POPUP_MIN_DISPLAY_SECONDS)
        + held * tuning.STOPBY_BATCH_SECONDS
    ))


def _start_batch_frames(start_popup: Optional[Dict], fps: int) -> int:
    """Frames the start popup's stop-by batch holds before the walk."""
    if not start_popup:
        return 0
    return int(
        fps * min(len(start_popup.get("stopby_group") or []), tuning.STOPBY_BATCH_MAX_HELD)
        * tuning.STOPBY_BATCH_SECONDS
    )


def _warped_total_frames(
    walk: _Walk, natural_frames: Dict, target_frames: Dict, audio_cues: Dict, fps: int, cap_frames: int,
    room: int, lead_frames: int,
) -> int:
    """Length of the retimed walk; lead_frames is everything written before it that the {end} cue counts."""
    # The last leg (after the last stop) is capped too: the walk ends at most one cap after it.
    total_out = min(room, max(target_frames.values()) + (cap_frames or room) + 1)
    if audio_cues.get("end") is not None:
        # The way back ends when the voice gets there (the ending then plays over the closing line).
        end_in_walk = int(round(audio_cues["end"] * fps)) - lead_frames
        total_out = max(max(target_frames.values()) + MIN_STOP_GAP_FRAMES, min(room, end_in_walk))
    # The way back is never cut shorter than its natural pace sped up MAX_WALK_SPEEDUP times (and one leg cap): a
    # voice that got there early leaves the ending to absorb it, not a walker that jumps home in a few frames.
    last_n = max(target_frames, key=target_frames.get)
    natural_back = len(walk.arr) - 1 - natural_frames[last_n]
    min_back = int(natural_back / MAX_WALK_SPEEDUP)
    if cap_frames:
        min_back = min(min_back, cap_frames)
    return max(total_out, target_frames[last_n] + min_back)


def _retime_to_cues(
    walk: _Walk, active_popups: List[Dict], start_popup: Optional[Dict], stop_popup: Optional[Dict],
    audio_cues: Dict, walk_start_frames: int, num_frames: int, fps: int, cap_frames: int,
    post_arrival_hold_seconds: float,
) -> _Walk:
    """Retime the walk so each stop is reached when its cue is spoken: the traveler speeds up / slows down between
    stops (route shape kept)."""
    natural_frames = {
        ap["order"]: _estimate_frame(walk.scale, ap["index"])
        for ap in active_popups
        if _is_numbered_stop(ap, stop_popup)
    }
    hosts = [
        (_estimate_frame(walk.scale, ap["index"]), _hold_frames(ap, fps, post_arrival_hold_seconds))
        for ap in active_popups
        if ap["index"] != 0 and (not stop_popup or ap["index"] != stop_popup["index"])
        and ap.get("stopby_host") is None
    ]
    hold_before = {n: sum(h for f, h in hosts if f < frame) for n, frame in natural_frames.items()}
    start_batch = _start_batch_frames(start_popup, fps)
    # The leg cap shortened the natural path, but each cued stop still has its own time (and is itself no more
    # than one cap after the last): the walk may be stretched back out to the length the cues need.
    room = max(len(walk.arr), num_frames)
    target_frames = stop_targets(
        natural_frames, audio_cues, walk_start_frames + start_batch, fps,
        room, holds=hold_before, cap_frames=cap_frames or None,
        min_leg_frames=int(fps * tuning.OVERVIEW_MIN_LEG_SECONDS),
    )
    if not target_frames:
        return walk
    total_out = _warped_total_frames(
        walk, natural_frames, target_frames, audio_cues, fps, cap_frames, room,
        walk_start_frames + start_batch + sum(h for _, h in hosts),
    )
    xs, ys = warp_controls(natural_frames, target_frames, total_out, len(walk.arr))
    smooth_path, cum_smooth_dist = warp_path(walk.arr, walk.scale.cum_smooth_dist, xs, ys, out_len=total_out)
    logger.info(
        "Overview stops retimed to cues: %s.",
        ", ".join(f"#{n} {natural_frames[n] / fps:.1f}s->{t / fps:.1f}s" for n, t in target_frames.items()),
    )
    return walk.with_path(smooth_path, cum_smooth_dist)


def _expected_frame(arr: np.ndarray, px: float, py: float, search_from: int, search_to: int) -> int:
    window = arr[search_from:search_to + 1]
    if len(window) == 0:
        return search_from
    dists = np.hypot(window[:, 0] - px, window[:, 1] - py)
    return search_from + int(np.argmin(dists))


def _match_expected_frames(active_popups: List[Dict], walk: _Walk) -> None:
    """Each waypoint's own true position in the path's time-sequence ("expected_frame"), not just "is the dot
    pixel-close to this pin now", which a route that loops back near a pin before reaching it would satisfy far too
    early. _estimate_frame (distance-based, immune to self-crossing) picks the anchor; the nearest-XY search only
    fine-tunes within a small window around it — an open-ended forward search grabbed a closer-but-wrong later
    crossing (waypoint 7's card showing while the traveler passed the END pin first). Never before the previous
    waypoint's own match."""
    n = walk.scale.num_frames
    last_matched_frame = 0
    search_margin = max(
        _EXPECTED_FRAME_SEARCH_MARGIN_MIN_FRAMES,
        int(n * _EXPECTED_FRAME_SEARCH_FRACTION),
    )
    for ap in active_popups:
        if ap["index"] == 0:
            ap["expected_frame"] = 0
            continue
        est = max(last_matched_frame, min(n - 1, _estimate_frame(walk.scale, ap["index"])))
        window_from = max(last_matched_frame, est - search_margin)
        window_to = min(n - 1, est + search_margin)
        ef = _expected_frame(walk.arr, ap["x"], ap["y"], window_from, window_to)
        ap["expected_frame"] = ef
        last_matched_frame = ef


def _set_leg_display_seconds(active_popups: List[Dict], stop_popup: Optional[Dict], fps: int) -> None:
    """A flow-through popup lasts from its own expected frame to the next waypoint's (not a fixed freeze_seconds
    regardless of the leg), so "2 to 3" shows popup 2 until 3 is reached."""
    triggerable = [
        ap for ap in active_popups
        if ap["index"] != 0 and (not stop_popup or ap["index"] != stop_popup["index"])
    ]
    triggerable.sort(key=lambda ap: ap["expected_frame"])
    stop_expected_frame = stop_popup["expected_frame"] if stop_popup else None
    min_leg_frames = int(fps * max(_MIN_LEG_DISPLAY_SECONDS, tuning.POPUP_MIN_DISPLAY_SECONDS))
    # Capped at POPUP_FREEZE_SECONDS_MAX like every other popup duration: the last stop before a long return leg
    # would otherwise show its card across that whole stretch.
    max_leg_frames = int(fps * tuning.POPUP_FREEZE_SECONDS_MAX)
    for i, ap in enumerate(triggerable):
        this_frame = ap["expected_frame"]
        next_frame = (
            triggerable[i + 1]["expected_frame"]
            if i + 1 < len(triggerable)
            else stop_expected_frame
        )
        if next_frame is not None:
            raw_gap = next_frame - this_frame
            ap["leg_display_seconds"] = (
                min(max_leg_frames, max(min_leg_frames, raw_gap)) / fps
            )


def _set_cue_frames(active_popups: List[Dict], stop_popup: Optional[Dict], audio_cues: Dict, fps: int) -> None:
    for ap in active_popups:
        seconds = audio_cues.get(str(ap.get("order")))
        numbered = _is_numbered_stop(ap, stop_popup)
        ap["cue_frame"] = int(round(seconds * fps)) if numbered and seconds is not None else None
        depart = audio_cues.get(f"go{ap.get('order')}")
        ap["depart_frame"] = (
            int(round(depart * fps)) if ap["cue_frame"] is not None and depart is not None
            and depart > seconds else None
        )
        if ap.get("no_pause") and not ap.get("stopby_group"):
            ap["depart_frame"] = None  # "Pause at Location" off: no hold until {go}


def _standing_cards(start_popup: Optional[Dict], stop_popup: Optional[Dict]) -> List[Dict]:
    """The intro's cards that stay on screen when the walk starts: the start's and the end's, at their spots."""
    return [p for p in (start_popup, stop_popup) if p and p.get("stay_box")]


def _spots_decided(popup: Dict) -> bool:
    """_ov_layout_stay_cards has been over this popup: it has a card spot, or shows its pin only."""
    return bool(popup.get("stay_box") or popup.get("no_card"))


def _intro_freeze_seconds(start_popup: Dict) -> float:
    if "freeze_seconds" not in start_popup["data"]:
        return _DEFAULT_INTRO_FREEZE_SECONDS
    # Floored like every other freeze_seconds read (popups.py), which this raw job_config value bypasses.
    return max(float(start_popup["data"]["freeze_seconds"]), tuning.POPUP_MIN_DISPLAY_SECONDS)


class _OverviewRenderMixin:
    def _sub_course_frames(self, fps: int) -> int:
        """How many frames _render_sub_course_part writes: 0 with no sub course."""
        if len((self.config.get("sub_course_overview") or {}).get("points") or []) < 2:
            return 0
        walk = max(2, int(storyboard_for(self.config).timings["sub_course_seconds"] * fps))
        return walk + max(1, int(tuning.POPUP_FADE_SECONDS * fps))

    def _render_sub_course_part(self, video, fps: int, clean_bg: np.ndarray, route_frame: np.ndarray) -> None:
        """After the main course's summary: the main route stays, faded, the marker sets off again from the branch
        stop along the sub course (config "sub_course_overview", render_step._sub_overview_frame), then its own
        summary card (main start -> sub course end)."""
        sub = self.config.get("sub_course_overview")
        if not sub or len(sub.get("points") or []) < 2:
            return
        h, w = route_frame.shape[:2]
        fade = tuning.SUB_COURSE_MAIN_FADE
        base = cv2.addWeighted(route_frame, 1 - fade, cv2.resize(clean_bg, (w, h)), fade, 0)
        color = tuning.SUB_COURSE_LINE_BGR
        pts = np.asarray(sub["points"], dtype=float)
        step = np.r_[0.0, np.cumsum(np.hypot(*np.diff(pts, axis=0).T))]
        frames = max(2, int(storyboard_for(self.config).timings["sub_course_seconds"] * fps))
        at = np.linspace(0.0, step[-1], frames)
        path = [(int(x), int(y)) for x, y in zip(np.interp(at, step, pts[:, 0]), np.interp(at, step, pts[:, 1]))]
        # Each stop's pin appears when the marker reaches it; anchors (main stops) are already on the map.
        stops = [s for s in sub.get("stops") or [] if not s.get("anchor")]
        reach = [int(np.argmin([(px - s["x"]) ** 2 + (py - s["y"]) ** 2 for px, py in path])) for s in stops]
        title = sub.get("name") or ""
        heading, prev = 0.0, None
        for i, (cx, cy) in enumerate(path):
            frame = base.copy()
            self.graphics.draw_path(frame, path[: i + 1], [(sub.get("mode") or "walking", color)] * (i + 1))
            for n, (s, r) in enumerate(zip(stops, reach), start=1):
                if r <= i:
                    self.graphics.draw_marker(frame, s["x"], s["y"], number=f"B{n}", color=color)
            heading = self._smoothed_heading(heading, cx, cy, *(prev or (None, None)))
            self.graphics.draw_transport_icon(frame, cx, cy, i, heading, mode=sub.get("mode") or "walking")
            if title:
                frame = self.graphics.render_top_banner(frame, title)
            video.write(frame)
            prev = (cx, cy)
        end = frame
        summary = sub.get("summary") or {}
        card = self.graphics.render_summary_card(
            distance_km=summary.get("total_distance_km", 0.0),
            duration_seconds=summary.get("total_duration_seconds", 0.0),
            mode_breakdown=summary.get("mode_breakdown"),
            mode_duration=summary.get("mode_duration"),
        )
        final = self.graphics.composite_card_on_frame(end, card, alpha=1.0)
        fade_frames = max(1, int(tuning.POPUP_FADE_SECONDS * fps))
        for i in range(fade_frames):
            video.write(cv2.addWeighted(final, (i + 1) / fade_frames, end, 1 - (i + 1) / fade_frames, 0))
        for _ in range(int(tuning.SUB_COURSE_SUMMARY_HOLD_SECONDS * fps)):
            video.write(final)
        self.last_frame = final

    def _ov_load_background(self, bg_path: str) -> Tuple[np.ndarray, int, int]:
        """The background image, with an even width and height (the encoder needs both)."""
        current_bg = self.graphics.read_image_safe(str(bg_path))
        if current_bg is None:
            raise FileNotFoundError(f"Cannot read background image: {bg_path}")
        h, w = current_bg.shape[:2]
        if h % 2 != 0 or w % 2 != 0:
            h, w = h - (h % 2), w - (w % 2)
            current_bg = cv2.resize(current_bg, (w, h))
        return current_bg, w, h

    def _ov_reset_hud(self, summary: Optional[Dict]) -> None:
        """The persistent top bar (title; what is left over the whole route), drawn per frame by
        overview_animation.py's _NoticeWriter; each piece is skipped when its value is missing."""
        self._hud_total_distance_km = (summary or {}).get("total_distance_km")
        self._hud_total_duration_seconds = (summary or {}).get("total_duration_seconds")
        self._hud_title = self.config.get("overview_title") or (
            self._get_job_config() or {}
        ).get("project_name")
        self._hud_progress_frac = 0.0  # the intro, before any walking: the whole trip is still ahead

    def _ov_prepare_popups(self, points: List, popups: List, labels: List, extent, w: int, h: int, fps: int) -> List[Dict]:
        """active_popups: one entry per waypoint with a popup, numbered, grouped, decluttered and styled."""
        start_label, end_label = _overview_endpoint_labels(self.out_dir)
        cleaned_labels = _clean_labels(labels, points, start_label, end_label)
        active_popups = _build_active_popups(points, popups, cleaned_labels)
        if extent is not None:
            _reproject_popups(active_popups, extent, w, h)
        _number_popups(active_popups, points)
        self._ov_attach_groups(active_popups, fps)
        self._declutter_pins(active_popups, route=points)
        self._ov_style_badges(active_popups, len(points))
        _apply_job_overrides(active_popups, self._get_job_waypoints())
        return active_popups

    def _ov_attach_groups(self, active_popups: List[Dict], fps: int) -> None:
        """Which stop-bys ride along with which stop (see _attach_stopby_groups). Closed places (red ×) never stop
        the walk: they pop up as it passes, then all come in together at {closed} at the end."""
        sb = storyboard_for(self.config)
        self._closed_popups = []
        if sb.passby_closed:
            self._closed_popups = [ap for ap in active_popups if ap["data"].get("inaccessible")]
        self._attach_stopby_groups(active_popups, pass_by=sb.passby_stopbys)
        if sb.leg_cards:
            from .map_style import attach_leg_cards

            attach_leg_cards(active_popups, self.config.get("res_route_path"), self.graphics, fps)

    def _ov_style_badges(self, active_popups: List[Dict], total_points: int) -> None:
        """Card border = the waypoint's own pin color, and its badge shows the glyph its pin does ("S", "E", "+1" or
        its visit number). Set once here: nearly every card downstream starts from a .copy() of these entries."""
        for ap in active_popups:
            pin_label, pin_color_for_border, _ = self._pin_label_and_color(ap, total_points)
            # None for a plain numbered pin not yet "arrived" (see _pin_color): fall back to the base color.
            ap["border_color"] = pin_color_for_border or self.graphics.marker_color
            ap["badge_label"] = pin_label
            ap["leader_straight"] = True  # every style's overview cards (popup_box._draw_leader_line)

    def _ov_obstacle_arrays(self, points: List, active_popups: List[Dict]):
        """(route_avoid_points, route_obstacle_arr, recap_obstacle_arr): the static footprint (full route line + every
        pin), computed once from the whole route so a waypoint's card lands in the same corner whenever it triggers."""
        # pin_x/pin_y (set by _declutter_pins) are the lookup key, so this stays right if pins get nudged apart.
        route_avoid_points = list(points) + [
            (p.get("pin_x", p["x"]), p.get("pin_y", p["y"])) for p in active_popups
        ]
        route_obstacle_arr = _route_obstacle_array(route_avoid_points)
        # Pin centers alone under-protect a pin's drawn silhouette (cards composite after pins and would erase it).
        pin_obstacles = self._pin_obstacle_points(active_popups)
        # Pins alone, for the "photo straight above its pin" check in _layout_beside_popups.
        self._layout_pin_obstacles = pin_obstacles
        if len(pin_obstacles):
            route_obstacle_arr = np.vstack([route_obstacle_arr, pin_obstacles])
        # A closed place's name shows at the end: the ending's cards keep off it.
        closed_obstacles = self._closed_obstacle_points()
        recap_obstacle_arr = (
            np.vstack([route_obstacle_arr, closed_obstacles]) if len(closed_obstacles) else route_obstacle_arr
        )
        return route_avoid_points, route_obstacle_arr, recap_obstacle_arr

    def _ov_make_intro_cards(
        self, start_popup: Dict, stop_popup: Optional[Dict], w: int, h: int, route_obstacle_arr: np.ndarray
    ) -> List[Dict]:
        """The start (and, with a photo, the stop) preview cards, laid out beside their own pins and moved above
        them where there is room."""
        if _spots_decided(start_popup):  # the cards stand where they stay, at the video's one size
            return [self.walk_card_hud(p, 0, 0, None, None) for p in _standing_cards(start_popup, stop_popup)]
        intro_card_scale = self.config.get("overview_intro_card_scale", 1.3)
        footprint_w, footprint_h = self.graphics.beside_card_footprint(intro_card_scale)

        def _make_intro_card(popup: Dict) -> Dict:
            card = popup.copy()
            card["data"] = popup["data"].copy()
            card["card_scale"] = intro_card_scale
            # card_scale alone grew the caption with the photo; scaled back down independently.
            card["label_font_scale"] = self.config.get("overview_intro_label_font_scale", 0.7)
            return card

        temp_sp = _make_intro_card(start_popup)
        # A loop route's "E" is the same place as "S": a second preview would only duplicate the start's photo.
        temp_ep = (
            _make_intro_card(stop_popup)
            if stop_popup
            and stop_popup["data"].get("popup_image")
            and not self._is_loop_route
            else None
        )
        intro_cards = [temp_sp] + ([temp_ep] if temp_ep else [])
        # Laid out together so they can't overlap, with a wide search radius (the default ~260px settled on spots
        # overlapping another pin: there is no "stay near the traveler" need on this one-off intro).
        self._layout_recap_popups(
            [{"popup": c, "frames_left": 1} for c in intro_cards], w, h,
            card_w=footprint_w, card_h=footprint_h,
            route_obstacles=route_obstacle_arr)
        self._place_cards_above_pins(intro_cards, w, h, footprint_w, footprint_h)
        for c in intro_cards:
            c["hud_corner"] = None
            c["draw_leader_line"] = True
        return intro_cards

    def _ov_draw_intro_cards(self, base: np.ndarray, alpha: float, intro: _IntroCards) -> np.ndarray:
        """Line, then pin, then card (as waypoints.py's leg intro), so each leader line sits BEHIND every pin."""
        out = base
        for c in intro.cards:
            out = self.graphics.render_popup_box(out, c, alpha=alpha, line_only=True)
        for wp in intro.active_popups:
            self._draw_pin(out, wp, intro.n_points)
        for c in intro.cards:
            out = self.graphics.render_popup_box(out, c, alpha=alpha, skip_line=True)
        return out

    def _ov_write_slide_frame(
        self, video, base: np.ndarray, alpha: float, frames_left: int, bounce_frames: int, intro: _IntroCards
    ) -> None:
        """One frame of the intro cards sliding (_popup_slide_offset_y, as every other card) while they fade."""
        slide = self._popup_slide_offset_y(
            {"total_frames": bounce_frames, "frames_left": frames_left, "fade_frames": bounce_frames}
        )
        for c, box in zip(intro.cards, intro.base_boxes):
            if box and not c.get("stay_box"):  # a card with a fixed spot only fades
                c["beside_box"] = (box[0], int(box[1] + slide))
        video.write(self._apply_hud(self._ov_draw_intro_cards(base, alpha, intro)))

    def _ov_play_intro(
        self, video, intro_frame: np.ndarray, active_popups: List[Dict], start_popup: Dict,
        stop_popup: Optional[Dict], n_points: int, route_obstacle_arr: np.ndarray, w: int, h: int, fps: int,
        preview_recap_only: bool,
    ) -> np.ndarray:
        """The intro beats: the map and every pin alone, then the start/stop cards. Returns the frame the walk picks
        up from: with cards that stay, the cards faded in at their spots; otherwise they slide in, hold and slide
        out onto the clean map. The intro always shows plain pip cards: "fullscreen" is only honored by the
        end-of-video zoom (_render_ending_highlight)."""
        intro_freeze_sec = _intro_freeze_seconds(start_popup)
        intro_cards = self._ov_make_intro_cards(start_popup, stop_popup, w, h, route_obstacle_arr)
        start_popup["data"]["triggered"] = True
        # Pin drawing keys off "arrived" (set the instant a waypoint is reached), not "triggered" (which for other
        # waypoints only flips after the popup clears the min-trigger-gap cooldown): the start is reached from
        # frame one. stop_popup is left untouched: temp_ep is only a preview COPY.
        start_popup["data"]["arrived"] = True
        # Every marker up front, so the whole route's stops are visible before the animation begins.
        for wp in active_popups:
            self._draw_pin(intro_frame, wp, n_points)
        clean_frame = intro_frame
        # Clean beat first, so the video opens on the route itself rather than cutting straight to a photo.
        clean_hold_sec = min(
            intro_freeze_sec * _INTRO_CLEAN_HOLD_FRACTION_OF_FREEZE,
            _timing(self.config, "intro_clean_hold_seconds"),
        )
        if not preview_recap_only:
            for _ in range(int(clean_hold_sec * fps)):
                video.write(self._apply_hud(clean_frame))

        intro = _IntroCards(intro_cards, [c.get("beside_box") for c in intro_cards], active_popups, n_points)
        bounce_frames = max(1, int(tuning.POPUP_FADE_SECONDS * fps))
        for i in range(bounce_frames):
            # Straight 0->1 ramp: this entrance never fades back out, and finishes with the slide at the last frame.
            self._ov_write_slide_frame(
                video, intro_frame, min(1.0, (i + 1) / bounce_frames), bounce_frames - i, bounce_frames, intro
            )
        for c, box in zip(intro.cards, intro.base_boxes):
            if box:
                c["beside_box"] = box
        intro_frame = self._ov_draw_intro_cards(intro_frame, 1.0, intro)
        remaining_frames = intro_card_hold_frames(
            intro_freeze_sec, clean_hold_sec, bounce_frames, fps,
            start_cue_sec=(self.config.get("overview_cue_seconds") or {}).get("start"),
        )
        for _ in range(remaining_frames):
            video.write(self._apply_hud(intro_frame))
        if self._cards_stay() and _spots_decided(start_popup):
            self.last_frame = intro_frame
            return intro_frame
        # Mirror of the entrance, so the cards don't cut straight to "traveler moving".
        if not preview_recap_only:
            for i in range(bounce_frames):
                self._ov_write_slide_frame(
                    video, clean_frame, max(0.0, 1.0 - (i + 1) / bounce_frames), i + 1, bounce_frames, intro
                )
        # No zoom at the very start: the only zoom-toward-the-start beat is the one at the END (_render_ending_highlight).
        self.last_frame = clean_frame
        return clean_frame

    def _ov_reserved_boxes(self, summary: Optional[Dict], w: int, h: int):
        """(summary_card, reserved_boxes): built up front so the cards laid out later keep off the summary card's
        bottom-right corner and the fixed spot of the "passing a stop-by" / "closed place" notice."""
        summary_card = None
        if summary:
            summary_card = self.graphics.render_summary_card(
                distance_km=summary.get("total_distance_km", 0.0),
                duration_seconds=summary.get("total_duration_seconds", 0.0),
                mode_breakdown=summary.get("mode_breakdown"),
                mode_duration=summary.get("mode_duration"),
            )
        margin = _SUMMARY_CARD_MARGIN_PX
        reserved_boxes = (
            [
                (
                    w - summary_card.shape[1] - margin,
                    h - summary_card.shape[0] - margin,
                    float(w - margin),
                    float(h - margin),
                )
            ]
            if summary_card is not None
            else []
        )
        reserved_boxes += [
            tuple(float(v) for v in self.graphics.stopby_notice_box(w, h, kind))
            for kind in ("stopby", "closed")
        ]
        first = reserved_boxes[-2]  # ...and the closed one beside the stop-by one
        beside = int(first[2] - first[0] + tuning.NOTICE_RAIL_GAP * h / 1080)
        reserved_boxes.append(tuple(float(v) for v in self.graphics.stopby_notice_box(w, h, "closed", beside)))
        rail = self.graphics.route_progress_rail_height(h) + int(h * 0.03)  # the progress rail's band
        reserved_boxes.append((0.0, float(h - rail), float(w), float(h)))
        # The top bar's two panels, at their widest (nothing of the route walked yet).
        km, seconds = (summary or {}).get("total_distance_km"), (summary or {}).get("total_duration_seconds")
        left, right = self.graphics.overview_hud_panels(
            w, getattr(self, "_hud_title", None), km, seconds, km, seconds)
        if left is not None:
            reserved_boxes.append((0.0, 0.0, float(_HUD_SIDE + left.size[0] + 12), float(_HUD_TOP + left.size[1] + 12)))
        if right is not None:
            reserved_boxes.append(
                (float(w - _HUD_SIDE - right.size[0] - 12), 0.0, float(w), float(_HUD_TOP + right.size[1] + 12)))
        return summary_card, reserved_boxes

    def _walk_rail_marks(self, active_popups: List[Dict], walk: _Walk, n_points: int) -> List[Tuple]:
        """The progress rail's ticks for the walk: the course's, one per stop on the route, at the share of the walk
        where the walker reaches it. Stop-bys it only passes get none."""
        cum = walk.scale.cum_smooth_dist
        if cum is None:
            return []
        stops = []
        for ap in active_popups:
            at = 0 if ap["index"] == 0 else len(cum) - 1 if ap["index"] == n_points - 1 else ap.get("expected_frame")
            if at is not None and not ap["data"].get("is_stopby") and not ap["data"].get("inaccessible"):
                stops.append({**ap, "course_dist": float(cum[min(int(at), len(cum) - 1)])})
        stops.sort(key=lambda ap: ap["course_dist"])
        return self._course_rail_marks(stops, n_points, walk.scale.total_smooth_dist)

    def _ov_layout_stay_cards(
        self, active_popups: List[Dict], stop_popup: Optional[Dict], w: int, h: int,
        reserved_boxes: List, route_obstacle_arr: np.ndarray, route_path=None,
    ) -> None:
        """One spot and size per place, for the whole video (storyboards with cards_stay): stamps "stay_box" and
        "stay_scale" on one popup per place that has a photo, round the groups of pins and off the route
        (`route_path`, the drawn line) and the HUD. Every other popup gets "no_card" and shows its pin only.
        "card_scale" is left alone."""
        if not storyboard_for(self.config).cards_stay:
            return
        if route_path is not None:
            line = densify(route_path)
            route_obstacle_arr = line if route_obstacle_arr is None else np.vstack([line, route_obstacle_arr])
        places = [ap for ap in self._recap_popup_set(active_popups, stop_popup) if ap["data"].get("popup_image")]
        copies = [dict(ap) for ap in places]  # the layout stamps its own keys on what it is given
        originals = {id(copy): ap for copy, ap in zip(copies, places)}
        for copy in self._layout_ring_cards(copies, w, h, reserved_boxes=reserved_boxes,
                                            route_obstacles=route_obstacle_arr):
            originals[id(copy)].update(stay_box=copy["beside_box"], stay_scale=copy["card_scale"])
        for ap in active_popups:
            if "stay_box" not in ap:
                ap["no_card"] = True

    def _ov_walk_camera(
        self, job: "_OverviewJob", walk: _Walk, active_popups: List[Dict], reserved_boxes: List,
    ) -> Optional[WalkCamera]:
        """The camera that zooms in on the clusters of stops the walker passes, or None when there are none."""
        cum = walk.scale.cum_smooth_dist
        if cum is None:  # shortcut: no travel modes, no distances along the path, no zoom; the pipeline always has them
            return None
        within = pin_width(self.graphics)
        stops = []
        for ap in active_popups:
            at = ap.get("expected_frame")
            if at is None or ap.get("is_return"):
                continue
            if np.hypot(walk.arr[:, 0] - ap["x"], walk.arr[:, 1] - ap["y"]).min() <= within:  # the walk reaches it
                stops.append((float(cum[min(int(at), len(cum) - 1)]), ap["x"], ap["y"]))
        from services.mapbox_token import resolve_mapbox_token

        gl = job.bounding_box is not None and bool(
            resolve_mapbox_token((self._get_job_config() or {}).get("settings")))
        clusters = cluster_views(
            stops, walk.arr, cum, job.w, job.h, within, storyboard_for(self.config).cluster_min_stops,
            tuning.COURSE_DENSE_ZOOM_MAX_GL if gl else tuning.COURSE_DENSE_ZOOM_MAX)
        if not clusters:
            return None
        return WalkCamera(clusters, job.fps, within, densify(walk.path), reserved_boxes)

    def _ov_recap_preview_plate(self, current_bg, walk: _Walk, mode_breakpoints):
        """The plate the walk stashes at its last frame, built straight from the background since no walk ran, with
        each point's own travel mode so ferry and car legs are colored as in the real render."""
        cum_smooth_dist, total_smooth_dist = walk.scale.cum_smooth_dist, walk.scale.total_smooth_dist
        modes = (
            [
                self._mode_at_fraction(mode_breakpoints, cum_smooth_dist[i] / total_smooth_dist)
                for i in range(len(walk.path))
            ]
            if total_smooth_dist else None
        )
        return self.plain_recap_plate(current_bg, walk.path, modes)

    def _ov_write_recap_preview(
        self, pre_popup_frame, active_popups: List[Dict], stop_popup: Optional[Dict], w: int, h: int,
        reserved_boxes: List, recap_obstacle_arr: np.ndarray,
    ) -> str:
        """Just the final recap frame as an image, laid out exactly as _render_recap_and_summary does."""
        out_img = str(self.out_dir / "01_overview_recap_preview.png")
        if storyboard_for(self.config).cards_stay:
            laid_out = self._recap_cards(active_popups)
        else:
            laid_out = self._layout_recap_cards(
                self._recap_popup_set(active_popups, stop_popup), w, h,
                reserved_boxes=reserved_boxes, route_obstacles=recap_obstacle_arr,
                background=pre_popup_frame, leaders=False,
                total_points=1 + max((ap["index"] for ap in active_popups), default=0),
            )
        final_frame = self._render_recap_frame(pre_popup_frame, active_popups, group_popups=laid_out)
        cv2.imwrite(out_img, final_frame)
        return out_img

    def _ov_fit_ending(
        self, video, audio_cues: Dict, start_popup: Optional[Dict], stop_popup: Optional[Dict],
        outro_hold_sec: float, fps: int,
    ) -> _Ending:
        """With narration the ending lasts as long as its closing line: the summary hold and the last pause stretch
        or shrink so the video ends with the voice (overview_timing.fit_ending)."""
        end_pause_sec = float(self.config.get("pause", 2.0))
        audio_seconds = float(self.config.get("overview_audio_seconds") or 0.0)
        zoom_follows = self._ending_zoom_follows(stop_popup)
        if zoom_follows:
            # The photo after the zoom stays up for the rest of the voice, so the summary only holds briefly.
            return _Ending(tuning.ENDING_SUMMARY_HOLD_SECONDS, end_pause_sec, audio_seconds, zoom_follows)
        if audio_seconds and audio_cues:
            highlight_on = bool(stop_popup and self.config.get("enable_ending_highlight", True))
            featured = start_popup or stop_popup
            # Only the pip hold is timed to the voice: the fullscreen transition plays after the narration ended.
            highlight_hold = tuning.ENDING_HIGHLIGHT_PIP_HOLD_SECONDS if featured else 0.0
            remaining = audio_seconds - video.frames_written / fps
            planned = (outro_hold_sec, end_pause_sec)
            outro_hold_sec, end_pause_sec = fit_ending(
                remaining, ending_seconds(0.0, 0.0, 0.0, highlight_hold, 0.0, highlight_on),
                outro_hold_sec, end_pause_sec,
            )
            logger.info(
                "Overview ending fitted to the closing line (%.1fs of voice left): "
                "summary hold %.1fs -> %.1fs, last pause %.1fs -> %.1fs.",
                remaining, planned[0], outro_hold_sec, planned[1], end_pause_sec,
            )
        return _Ending(outro_hold_sec, end_pause_sec, audio_seconds, zoom_follows)

    def _ov_wait_for_distance(self, video, audio_cues: Dict, fps: int) -> None:
        """Holds the walk's last frame until the {distance} cue, so the totals card comes in on those words."""
        cue = (audio_cues or {}).get("distance")
        if cue is not None:
            for _ in range(int(round(cue * fps)) - video.frames_written):
                video.write(self.last_frame)

    def _ov_hold_summary(
        self, video, summary_card, audio_cues: Dict, outro_hold_sec: float, zoom_follows: bool, fps: int
    ) -> None:
        """Write the held summary frame, long enough after the {distance} cue to be read, and to the {closed} cue."""
        distance_cue = audio_cues.get("distance") if audio_cues else None
        if summary_card is not None and distance_cue is not None:
            hold = float(self.config.get("overview_recap_hold_seconds", tuning.OVERVIEW_RECAP_HOLD_SECONDS))
            until = distance_cue + hold - video.frames_written / fps
            if until > outro_hold_sec:
                logger.info(
                    "Summary hold %.1fs -> %.1fs: the totals stay %.1fs after the {distance} cue at %.1fs.",
                    outro_hold_sec, until, hold, distance_cue,
                )
                outro_hold_sec = until
        # The {closed} cue holds the summary frame while the voice names the closed places.
        closed_cue = audio_cues.get("closed") if audio_cues and getattr(self, "_closed_popups", None) else None
        if getattr(self, "_closed_popups", None) and (closed_cue is None or zoom_follows):
            # No {closed} in the script, or the zoom comes next: they come in with the summary.
            closed_cue = video.frames_written / fps
        if closed_cue is not None and not zoom_follows:
            outro_hold_sec = max(outro_hold_sec, closed_cue + tuning.CLOSED_HOLD_SECONDS - video.frames_written / fps)
        closed_frame = None
        for _ in range(int(outro_hold_sec * fps)):
            if closed_cue is not None and video.frames_written / fps >= closed_cue:
                if closed_frame is None:
                    # Nothing to draw: the recap already shows each closed place as a dot and pill badge.
                    closed_frame = self.last_frame.copy()
                video.write(closed_frame)
            else:
                video.write(self.last_frame)

    def _ov_play_ending_highlight(
        self, video, w: int, h: int, fps: int, stop_popup, start_popup, pre_popup_frame, bounding_box,
        audio_cues: Dict, audio_seconds: float,
    ) -> bool:
        # However fit_ending split the remaining voice, what's STILL left after the summary hold is what the
        # highlight needs to stay up for.
        remaining_for_highlight = (
            audio_seconds - video.frames_written / fps if audio_seconds and audio_cues else None
        )
        # The {distance} cue is a direct audio measurement: a floor, so the highlight can't let go before that
        # line is spoken even if the whole-duration estimate drifted.
        distance_cue = audio_cues.get("distance") if audio_cues else None
        if distance_cue is not None:
            distance_remaining = distance_cue - video.frames_written / fps
            remaining_for_highlight = max(remaining_for_highlight or 0.0, distance_remaining)
        return self._render_ending_highlight(
            video, w, h, fps, stop_popup, start_popup,
            clean_map_frame=pre_popup_frame,
            bounding_box=bounding_box,
            remaining_audio_seconds=remaining_for_highlight,
        )

    def _ov_finish_video(
        self, video, popups: List, hard_ended: bool, end_pause_sec: float, audio_seconds: float,
        audio_cues: Dict, fps: int, overview_path: str,
    ) -> str:
        for p in popups:
            if p:
                p["triggered"] = False
                p["arrived"] = False
        # The fullscreen ending highlight, when it plays, IS the video's last frame: no trailing pause.
        if not hard_ended:
            for _ in range(int(end_pause_sec * fps)):
                video.write(self.last_frame)
        self.last_rendered_seconds = video.frames_written / fps
        if audio_seconds and audio_cues:
            tail = getattr(self, "ending_tail_seconds", 0.0) if hard_ended else 0.0
            gap = video.frames_written / fps - tail - audio_seconds
            (logger.warning if abs(gap) > AUDIO_MATCH_TOLERANCE_SECONDS else logger.info)(
                "Overview video %.1fs (+%.1fs fullscreen photo after the voice), narration %.1fs "
                "(%+.1fs; allowed ±%.0fs).",
                video.frames_written / fps - tail, tail, audio_seconds, gap, AUDIO_MATCH_TOLERANCE_SECONDS,
            )
        self.last_ending_hard_ended = hard_ended
        return video.release(overview_path)

    def render_overview(
        self,
        bg_path: str,
        points: List,
        labels: List,
        popups: List,
        fps: int,
        summary: Optional[Dict] = None,
        point_modes: Optional[List[str]] = None,
        bounding_box: Optional[Dict[str, float]] = None,
        extent: Optional[Tuple[float, float, float, float]] = None,
        preview_recap_only: bool = False,
        point_colors: Optional[List] = None,
    ) -> str:
        overview_path = str(self.out_dir / "01_overview.mp4")
        render_args = dict(
            points=points, labels=labels, popups=popups, fps=fps, summary=summary, point_modes=point_modes,
            point_colors=point_colors, bounding_box=bounding_box, extent=extent, preview_recap_only=preview_recap_only,
        )
        save_fingerprint = self._ov_begin_checkpoint(bg_path, overview_path, render_args)
        if self.last_overview_reused:
            return overview_path
        current_bg, w, h = self._ov_load_background(bg_path)
        self._ov_reset_hud(summary)
        num_frames, audio_cues, walk_start_frames = self._ov_plan_frames(popups, fps)
        smooth_path, mode_breakpoints, cum_smooth_dist, total_smooth_dist = self._ov_plan_path(
            points, point_modes, point_colors, extent, w, h, num_frames
        )
        active_popups = self._ov_prepare_popups(points, popups, labels, extent, w, h, fps)
        route_avoid_points, route_obstacle_arr, recap_obstacle_arr = self._ov_obstacle_arrays(points, active_popups)
        job = _OverviewJob(
            current_bg, w, h, fps, points, popups, summary, bounding_box, preview_recap_only, overview_path,
            audio_cues, walk_start_frames, num_frames, mode_breakpoints, smooth_path, cum_smooth_dist,
            total_smooth_dist,
        )
        if storyboard_for(self.config).traced_route:
            result = self._render_course_overview(
                current_bg, w, h, fps, points, smooth_path, mode_breakpoints, cum_smooth_dist,
                total_smooth_dist, active_popups, route_obstacle_arr, summary, overview_path,
                bounding_box=bounding_box, preview_only=preview_recap_only,
            )
        else:
            result = self._ov_render_walk_video(
                job, active_popups, route_avoid_points, route_obstacle_arr, recap_obstacle_arr
            )
        if not preview_recap_only:
            # Saved by the caller once the file is final (after its end hold).
            self.pending_overview_checkpoint = save_fingerprint
        return result

    def _ov_begin_checkpoint(self, bg_path: str, overview_path: str, render_args: Dict):
        """Fingerprint the inputs and decide whether the finished file is reused (last_overview_reused: a reused
        file already has its end hold, so the caller must not add another). Returns the callable that records the
        fingerprint once the file is final. Reused only while its own inputs are unchanged, so an edit to one leg's
        narration no longer re-renders the whole overview."""
        inputs_path = self.out_dir / "01_overview.inputs.json"
        fingerprint_parts = _overview_fingerprint_parts(
            self.config, self._get_job_config(), bg_path, render_args
        )
        save_fingerprint = functools.partial(
            _save_overview_fingerprint, inputs_path, _fingerprint_hash(fingerprint_parts), fingerprint_parts
        )
        self.last_overview_reused = False
        self.pending_overview_checkpoint = None
        self.last_overview_reused = _checkpoint_reusable(
            self.config.get("checkpoint_enabled", False), overview_path, inputs_path, fingerprint_parts
        )
        return save_fingerprint

    def _ov_plan_frames(self, popups: List, fps: int) -> Tuple[int, Dict, int]:
        """(num_frames, audio_cues, walk_start_frames), and the stop-by notice state reset for this video."""
        num_frames = max(_MIN_OVERVIEW_FRAMES, int(self.config.get("duration", 30.0) * fps))
        # the stop-by notice plays at the first stop-by of each video
        self._stopby_notice_shown = False
        self._notice_kinds_shown = set()
        self._stopby_notices, self._notice_edges = {}, []
        self._rail_marks, self._rail_mode = None, None
        audio_cues = dict(self.config.get("overview_cue_seconds") or {})
        walk_start_frames = 0
        if audio_cues:
            walk_start_frames, num_frames = _cue_walk_timing(popups, audio_cues, self.config, fps, num_frames)
        return num_frames, audio_cues, walk_start_frames

    def _ov_plan_path(self, points: List, point_modes, point_colors, extent, w: int, h: int, num_frames: int):
        """(smooth_path, mode_breakpoints, cum_smooth_dist, total_smooth_dist); also stashes the color breakpoints
        and the lat/lon route the ending highlight redraws."""
        smooth_path, mode_breakpoints, cum_smooth_dist, total_smooth_dist = (
            self._build_overview_path(points, point_modes, num_frames)
        )
        self._color_breakpoints = (
            self._build_mode_breakpoints(points, point_colors)
            if point_colors and any(point_colors)
            else []
        )
        self._route_latlon_path = _route_latlon_samples(smooth_path, extent, w, h)
        return smooth_path, mode_breakpoints, cum_smooth_dist, total_smooth_dist

    def _ov_time_walk(
        self, job: "_OverviewJob", active_popups: List[Dict], start_popup: Optional[Dict], stop_popup: Optional[Dict]
    ) -> _Walk:
        """The animated path with leg caps and narration cues applied, and each popup's frames and cue timing set."""
        fps, audio_cues = job.fps, job.audio_cues
        walk = _initial_walk(job.points, job.smooth_path, job.cum_smooth_dist, job.total_smooth_dist)
        _set_cue_waits(active_popups, stop_popup, audio_cues, self.config, fps)
        cap_frames = int(fps * _timing(self.config, "max_leg_seconds"))
        walk = _cap_legs(walk, active_popups, cap_frames, fps)
        if audio_cues:
            walk = _retime_to_cues(
                walk, active_popups, start_popup, stop_popup, audio_cues, job.walk_start_frames, job.num_frames,
                fps, cap_frames, self.post_arrival_hold_seconds,
            )
        _match_expected_frames(active_popups, walk)
        _set_leg_display_seconds(active_popups, stop_popup, fps)
        return walk

    def _ov_render_walk_video(
        self, job: "_OverviewJob", active_popups: List[Dict], route_avoid_points: List,
        route_obstacle_arr: np.ndarray, recap_obstacle_arr: np.ndarray,
    ) -> str:
        """The intro, the walk, then (unless only the recap preview was asked for) the recap and ending."""
        w, h, fps, audio_cues = job.w, job.h, job.fps, job.audio_cues
        logger.info(f"Rendering Overview Map ({self.config.get('duration', 30.0)}s)")
        video = VideoExporter(job.overview_path, w, h, fps)
        intro_frame = job.current_bg.copy()
        start_popup = next((p for p in active_popups if p["index"] == 0), None)
        stop_popup = next(
            (p for p in active_popups if p["index"] == len(job.points) - 1), None
        )
        walk = self._ov_time_walk(job, active_popups, start_popup, stop_popup)

        # Every card's one spot and size, decided before the first frame: the intro, walk and recap read it.
        summary_card, reserved_boxes = self._ov_reserved_boxes(job.summary, w, h)
        self._ov_layout_stay_cards(
            active_popups, stop_popup, w, h, reserved_boxes, route_obstacle_arr, route_path=walk.path)
        self._rail_marks = self._walk_rail_marks(active_popups, walk, len(job.points))

        if start_popup:
            waiting_frame = self._ov_play_intro(
                video, intro_frame, active_popups, start_popup, stop_popup, len(job.points), route_obstacle_arr,
                w, h, fps, job.preview_recap_only,
            )
            if audio_cues:
                # The voice's {start} (or a short intro) leaves the map waiting until the route sets off.
                for _ in range(max(0, job.walk_start_frames - video.frames_written)):
                    video.write(self._apply_hud(waiting_frame))

        _set_cue_frames(active_popups, stop_popup, audio_cues, fps)
        if job.preview_recap_only:
            pre_popup_frame = self._ov_recap_preview_plate(job.current_bg, walk, job.mode_breakpoints)
            return self._ov_write_recap_preview(
                pre_popup_frame, active_popups, stop_popup, w, h, reserved_boxes, recap_obstacle_arr
            )
        camera = self._ov_walk_camera(job, walk, active_popups, reserved_boxes)
        with tempfile.TemporaryDirectory(prefix="navivi_walk_zoom_") as gl_dir:
            if camera:
                camera.frames = self._gl_view_frames(camera.views(), job.bounding_box, w, h, gl_dir)
            # [NOTE] Background video is not supported here: no capture, is_video False.
            pre_popup_frame = self._animate_overview_frames(
                video, job.current_bg, None, False, w, h, fps,
                walk.path, job.mode_breakpoints, walk.scale.cum_smooth_dist, job.total_smooth_dist,
                active_popups, stop_popup, job.points, route_avoid_points, route_obstacle_arr,
                standing_cards=_standing_cards(start_popup, stop_popup) if self._cards_stay() else (),
                camera=camera,
            )
        return self._ov_write_ending(
            job, video, active_popups, start_popup, stop_popup, summary_card, reserved_boxes,
            recap_obstacle_arr, pre_popup_frame,
        )

    def _ov_write_ending(
        self, job: "_OverviewJob", video, active_popups: List[Dict], start_popup: Optional[Dict],
        stop_popup: Optional[Dict], summary_card, reserved_boxes: List, recap_obstacle_arr: np.ndarray,
        pre_popup_frame: np.ndarray,
    ) -> str:
        w, h, fps, audio_cues = job.w, job.h, job.fps, job.audio_cues
        if summary_card is not None:
            self._ov_wait_for_distance(video, audio_cues, fps)
        outro_hold_sec = self._render_recap_and_summary(
            video, stop_popup, summary_card, active_popups, w, h, fps,
            recap_obstacle_arr, reserved_boxes, pre_popup_frame,
        )
        ending = self._ov_fit_ending(video, audio_cues, start_popup, stop_popup, outro_hold_sec, fps)
        self._ov_hold_summary(video, summary_card, audio_cues, ending.outro_hold_sec, ending.zoom_follows, fps)
        self._render_sub_course_part(video, fps, job.current_bg, pre_popup_frame)

        hard_ended = False
        if ending.zoom_follows:
            hard_ended = self._ov_play_ending_highlight(
                video, w, h, fps, stop_popup, start_popup, pre_popup_frame, job.bounding_box,
                audio_cues, ending.audio_seconds,
            )
        return self._ov_finish_video(
            video, job.popups, hard_ended, ending.end_pause_sec, ending.audio_seconds, audio_cues, fps,
            job.overview_path,
        )
