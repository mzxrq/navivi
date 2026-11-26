"""The per-residential-leg (waypoint chunk) video render entry point."""

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

import cv2
import numpy as np

from services.logger.progress import tracker
from services.mapfetcher.mapfetcher import MapFetcher
from services.mapfetcher.mapgeometry import RouteGeometryProcessor
from services.vdoprocessing.route_inputs import returns_to
from services.vdoprocessing.vdoexporter import VideoExporter
from services import tuning, video_text

_VIDEO_EXTENSIONS = (".mp4", ".webm", ".avi", ".mov", ".mkv")

# ~30 m in degrees: a real GPS/routing match lands far closer; farther means "no match", not a wrong one.
_LOCATION_MATCH_MAX_DEGREES = 0.0003

# Faint full-route line under the traveled path (addWeighted: OpenCV can't draw a translucent polyline).
_GUIDELINE_ALPHA = 0.45
_GUIDELINE_KEEP = 0.55

# Route obstacle points handed to the popup layout are subsampled above this count.
_ROUTE_OBSTACLE_MAX_POINTS = 400

# Landmark label placement (pixels): frame margin, padding between boxes, inset of the box inside its sprite,
# and the candidate vertical nudges tried from the pin outward.
_LABEL_FRAME_MARGIN_PX = 20
_LABEL_BOX_PAD_PX = 3
_LABEL_SPRITE_INSET_PX = 4
_LABEL_PREFER_LEFT_MARGIN_PX = 260
_LABEL_FAR_SIDE_PENALTY = 50.0
_LABEL_NUDGE_WEIGHT = 10.0
_LABEL_Y_OFFSETS = [0]
for _dy_step in range(4, 64, 4):
    _LABEL_Y_OFFSETS.extend([-_dy_step, _dy_step])


def _output_is_valid(path, min_bytes: int = 1024) -> bool:
    """Checkpoint helper — see spatial_renderer/overview.py's identical
    copy for why this is duplicated instead of imported from
    videopipeline/helpers.py (circular import)."""
    try:
        p = Path(path)
        return p.is_file() and p.stat().st_size >= min_bytes
    except OSError:
        return False


def _is_stopby_entry(jw: Dict) -> bool:
    """job_config.json spells it "isStopBy" (as saved by the frontend); "is_stopby" only exists on normalized dicts."""
    return bool(jw.get("isStopBy", False) or jw.get("skipAssetGeneration"))


def _clean_leg_label(raw: Optional[str]) -> str:
    """A leg endpoint's place name without the "出発: "/"到着: " prefixes route_labels carries."""
    if not raw:
        return ""
    return video_text.strip_waypoint_prefixes(raw)


def _edge(seq, index: int):
    return seq[index] if seq is not None and len(seq) else None


class _EndpointResolver:
    """Finds a leg endpoint's real position in the WHOLE route and its visit order.

    [NOTE] job_config's "waypoints" holds only the intermediate stops (the true start/end live in
    "start_point"/"end_point"), so positions are stored as `pos + 1` to line up with
    _pin_label_and_color's index==0 ("S") / index==total-1 ("E") checks. Label text alone is not reliable
    (one place name can repeat along a route), hence id, then nearest coordinate, then fuzzy label.
    """

    def __init__(self, job_waypoints: List[Dict], job_config: Dict):
        self.job_waypoints = job_waypoints
        self.by_id: Dict[str, Tuple[int, int, bool]] = {}
        # (lat, lng, index, order, is_stopby) for every waypoint plus the true start/end.
        self.candidates: List[Tuple[float, float, int, Optional[int], bool]] = []
        # {position: the number its pin shows}, the overview's own numbering: a stop-by keeps the running
        # count (it shows a dot), a return stop repeats the number of the stop it comes back to.
        self.numbers: Dict[int, int] = {}
        start_pt = job_config.get("start_point") or {}
        end_pt = job_config.get("end_point") or {}
        if start_pt.get("lat") is not None:
            self.candidates.append((start_pt["lat"], start_pt.get("lng", start_pt.get("lon")), 0, None, False))
        self._add_waypoints()
        self.total_route_points = len(job_waypoints) + 2
        if end_pt.get("lat") is not None:
            self.candidates.append((
                end_pt["lat"], end_pt.get("lng", end_pt.get("lon")),
                self.total_route_points - 1, None, False,
            ))

    def _add_waypoints(self) -> None:
        order = 0
        for pos, jw in enumerate(self.job_waypoints):
            is_stopby = _is_stopby_entry(jw)
            back = returns_to(self.job_waypoints, pos)
            if not is_stopby and back is None:
                order += 1
            self.numbers[pos] = order if back is None else self.numbers[back]
            wp_id = jw.get("id")
            if wp_id:
                self.by_id[wp_id] = (pos + 1, self.numbers[pos], is_stopby)
            lat, lng = jw.get("lat"), jw.get("lng", jw.get("lon"))
            if lat is not None and lng is not None:
                self.candidates.append((lat, lng, pos + 1, self.numbers[pos], is_stopby))

    def resolve(
        self, waypoint_id: Optional[str], label: str,
        lat: Optional[float] = None, lng: Optional[float] = None,
    ):
        """(index, order, is_stopby) by exact id, else nearest coordinate, else fuzzy label; None if unresolved."""
        if waypoint_id and waypoint_id in self.by_id:
            return self.by_id[waypoint_id]
        if lat is not None and lng is not None and self.candidates:
            best = min(self.candidates, key=lambda c: (c[0] - lat) ** 2 + (c[1] - lng) ** 2)
            if math.hypot(best[0] - lat, best[1] - lng) <= _LOCATION_MATCH_MAX_DEGREES:
                return best[2], best[3], best[4]
        if not label:
            return None
        for pos, jw in enumerate(self.job_waypoints):
            jw_lbl = str(jw.get("label", ""))
            if jw_lbl and (jw_lbl in label or label in jw_lbl):
                return pos + 1, self.numbers[pos], _is_stopby_entry(jw)
        return None


def _leg_pin(x, y, label, data, match) -> Dict:
    """A leg endpoint as a pin dict. A resolved match carries the waypoint's position in the WHOLE route so
    S/E/stop-by/number precedence reflects the trip, not this leg; unresolved falls back to a number-less pin."""
    index, order, is_stopby = match if match else (-1, None, False)
    return {
        "x": x, "y": y, "index": index, "order": order,
        "label": label, "data": {**(data or {}), "is_stopby": is_stopby},
    }


def _marker_display_px(marker_data: Dict, extent, w: int, h: int) -> Tuple[float, float]:
    """Where a merged stop-by's pin is drawn.

    [NOTE] The nearest recorded-track pixel ("px") is wrong for a place only seen from a distance (an offshore
    island, a viewpoint), so a marker with its own lat/lng is reprojected (same fix as overview.py's stop-bys).
    """
    lat, lng = marker_data.get("lat"), marker_data.get("lng")
    if lat is None or lng is None or extent is None:
        return marker_data["px"][0], marker_data["px"][1]
    return RouteGeometryProcessor.project_latlon_to_pixel(lat, lng, extent, w, h)


def _paused_frames(pauses: List[Dict], total_frames: int, fps: int) -> List[bool]:
    return [
        (any(p["start"] <= (f / fps) <= p["end"] for p in pauses) if pauses else False)
        for f in range(total_frames)
    ]


def _overlap_with(box: Tuple[float, float, float, float], placed: List[Tuple[float, float, float, float]]):
    """(overlaps any placed box, total overlapped area)."""
    overlap = False
    overlap_area = 0.0
    for ob in placed:
        ix0 = max(box[0], ob[0])
        iy0 = max(box[1], ob[1])
        ix1 = min(box[2], ob[2])
        iy1 = min(box[3], ob[3])
        if ix0 < ix1 and iy0 < iy1:
            overlap = True
            overlap_area += (ix1 - ix0) * (iy1 - iy0)
    return overlap, overlap_area


def _place_landmark_label(item: Dict, sprites: Dict, placed: List, w: int, h: int, pin_gap: int):
    """Closest non-overlapping spot beside the pin: left/right side, minimal vertical nudges, so a label never
    drifts far from its pin. Falls back to the least-overlapping candidate when none is free."""
    base_x, base_y = item["pin_x"], item["pin_y"]
    best_placement = None
    min_overlap_area = float("inf")
    sides = ["left", "right"] if base_x > (w - _LABEL_PREFER_LEFT_MARGIN_PX) else ["right", "left"]
    margin = _LABEL_FRAME_MARGIN_PX
    for side in sides:
        sprite, anchor = sprites[side]
        sh, sw = sprite.shape[:2]
        if side == "left":
            bx1, bx2 = pin_gap, sw - pin_gap * 2
        else:
            bx1, bx2 = pin_gap * 2, sw - pin_gap
        by1, by2 = _LABEL_SPRITE_INSET_PX, sh - _LABEL_SPRITE_INSET_PX
        for dy in _LABEL_Y_OFFSETS:
            curr_y = base_y + dy
            rx0 = base_x - anchor[0] + bx1
            rx1 = base_x - anchor[0] + bx2
            ry0 = curr_y - anchor[1] + by1
            ry1 = curr_y - anchor[1] + by2
            if rx0 < margin or rx1 > (w - margin) or ry0 < margin or ry1 > (h - margin):
                continue
            pad = _LABEL_BOX_PAD_PX
            overlap, overlap_area = _overlap_with((rx0 - pad, ry0 - pad, rx1 + pad, ry1 + pad), placed)
            candidate = (side, base_x, curr_y, (rx0, ry0, rx1, ry1))
            if not overlap:
                return candidate
            dist_penalty = abs(dy) * _LABEL_NUDGE_WEIGHT + (_LABEL_FAR_SIDE_PENALTY if side != sides[0] else 0.0)
            total_score = overlap_area + dist_penalty
            if total_score < min_overlap_area:
                min_overlap_area = total_score
                best_placement = candidate
    return best_placement


class _LegTiming(NamedTuple):
    total_frames: int
    travel_duration: float
    real_duration: float
    pauses: List[Dict]
    paused_per_frame: List[bool]
    total_pause_seconds: float


class _IntroCard(NamedTuple):
    """The leg's summary card shown up front; its hold/exit are composited on the first real animation frames."""

    card: Optional[np.ndarray] = None
    hold_frames: int = 0
    exit_frames: int = 0
    slide_distance: float = 0.0


@dataclass
class _LegScene:
    """Everything about one leg that stays fixed while its frames play."""

    res_data: Dict
    res_points: List
    res_smooth_path: Any
    res_mode: str
    w: int
    h: int
    mid_marker_pins: List[Dict]
    landmark_items: List[Dict]
    landmark_sprites: Dict
    label_positions: Dict[Any, Tuple[str, int, int]]
    start_wp: Dict
    end_wp: Dict
    start_pin: Tuple[Any, Any]
    end_pin: Tuple[Any, Any]
    total_wp: int


@dataclass
class _LegPlayback:
    """Per-leg output and timing settings the frame loop needs."""

    video: VideoExporter
    fps: int
    fade_sec: float
    clip_hold_sec: float
    show_summary: bool
    real_duration: float
    arrival_hold_seconds: float


class _WaypointRenderMixin:
    # Extra pixels below the frame a sliding summary card starts from, on
    # top of its own height, so it genuinely starts off-screen rather than
    # just below its resting spot. Shared by _play_leg_summary_card's own
    # entrance and the intro card's hold/exit compositing further down.
    _CARD_SLIDE_MARGIN_PX = 40

    # See tuning.LEG_CARD_MARGIN_PX / LEG_CARD_MARGIN_BOTTOM_PX (the card image has transparent padding).
    _LEG_CARD_MARGIN_PX = tuning.LEG_CARD_MARGIN_PX
    _LEG_CARD_MARGIN_BOTTOM_PX = tuning.LEG_CARD_MARGIN_BOTTOM_PX

    # Default hold time (seconds) for a merged-in mid-route stop-by's
    # pass-by popup card when it doesn't specify its own freeze_seconds.
    _DEFAULT_PASSBY_FREEZE_SECONDS = 2.0

    # Minimum spacing (px) enforced between consecutive residential-map
    # points before smoothing/animating the path.
    _MIN_RESIDENTIAL_POINT_SPACING_PX = 3.0

    # [NOTE] [Animation] Looser than the library's 3px default: real routed geometry carries GPS/routing
    # jitter the default barely touches; this smooths it without cutting real turns.
    _ROUTE_SIMPLIFY_TOLERANCE_PX = 6.0

    # Floor on total_frames so a very short/near-zero-duration leg still
    # produces a playable clip instead of 0-1 frames.
    _MIN_LEG_TOTAL_FRAMES = 10

    # Clamp bounds (seconds) applied to the configured post-arrival hold.
    _ARRIVAL_HOLD_MIN_SECONDS = 1.0
    _ARRIVAL_HOLD_MAX_SECONDS = 2.0

    @staticmethod
    def _ease_in_out(t: float) -> float:
        """Same easing curve local_pan_generator.py uses for its Ken-Burns
        pans — kept as its own copy rather than imported since that module
        is coupled to its own photo pipeline/VideoWriter."""
        return 0.5 - 0.5 * math.cos(math.pi * t)

    def _leg_summary_card(self, res_data: Dict, duration_seconds: float, mode: str) -> np.ndarray:
        """This leg's summary card, in the same template as the overview's."""
        distance_km = res_data.get("distance_km", 0.0)
        return self.graphics.render_summary_card(
            distance_km=distance_km,
            duration_seconds=duration_seconds,
            mode_breakdown={mode: distance_km},
            mode_duration={mode: duration_seconds},
        )

    def _play_leg_summary_card(
        self,
        video: VideoExporter,
        base_frame: np.ndarray,
        seg_card: np.ndarray,
        fps: int,
        fade_sec: float,
        clip_hold_sec: float,
        play_exit: bool = True,
        play_hold: bool = True,
        margin: int = 20,
        corner: str = "bottom_right",
        margin_y: Optional[int] = None,
    ) -> None:
        """Slides this leg's summary card/bar up from off-screen at the
        bottom (rather than just fading it in in place), holds it, then
        (when `play_exit`) slides it back down and out — same ease-out-
        cubic shape _popup_slide_offset_y uses elsewhere for the
        overview's own popup cards, just with a distance sized to the
        card's own height so it starts genuinely below the frame instead
        of a few px below its resting spot. `play_exit=False` for a leg
        whose clip ends right here (no next frame for a slide-out to play
        into) — it just holds until the clip cuts. `play_hold=False`
        skips the static hold entirely (entrance only) — used when the
        caller wants to composite the hold/exit itself on top of OTHER,
        already-moving frames instead of a static one (see
        render_waypoints' own intro_card_hold_frames/
        intro_card_exit_frames) so the card stays visible while the route
        animation is already playing, not just before it starts.
        `margin`/`corner` forward to composite_card_on_frame."""
        card_h = seg_card.shape[0]
        slide_distance = card_h + self._CARD_SLIDE_MARGIN_PX
        fade_frames = max(1, int(fade_sec * fps))

        for frame_idx in range(fade_frames):
            t = (frame_idx + 1) / fade_frames
            eased = 1 - (1 - t) ** 3
            video.write(
                self.graphics.composite_card_on_frame(
                    base_frame, seg_card, alpha=t, margin=margin, corner=corner, margin_y=margin_y,
                    slide_offset_y=slide_distance * (1 - eased),
                )
            )

        if play_hold:
            held_frame = self.graphics.composite_card_on_frame(
                base_frame, seg_card, alpha=1.0, margin=margin, corner=corner, margin_y=margin_y,
            )
            for _ in range(max(0, int(clip_hold_sec * fps) - fade_frames)):
                video.write(held_frame)

        if play_exit:
            for frame_idx in range(fade_frames):
                t = (frame_idx + 1) / fade_frames
                eased = 1 - (1 - t) ** 3
                video.write(
                    self.graphics.composite_card_on_frame(
                        base_frame, seg_card, alpha=1.0 - t, margin=margin, corner=corner, margin_y=margin_y,
                        slide_offset_y=slide_distance * eased,
                    )
                )

    def _play_leg_wide_intro(
        self, video: VideoExporter, res_data: Dict, current_bg: np.ndarray, fps: int
    ) -> None:
        """Holds this leg's wide establishing shot, then crossfades (scale-
        free — both tiles already share the same canvas size) into the
        close/tight tile the rest of this leg's clip will animate on top
        of. A no-op when this res_data has no wide tile (only a leg's
        first chunk ever does — see mapfetcher.py's is_first_chunk_of_leg)
        or the wide tile can't be read/doesn't match current_bg's size."""
        wide_path = res_data.get("wide_img_path")
        if not wide_path:
            return
        wide_bg = self.graphics.read_image_safe(str(wide_path))
        if wide_bg is None:
            return
        if wide_bg.shape[:2] != current_bg.shape[:2]:
            # Both tiles are fetched at the same output_size, but
            # current_bg may have been snapped to even dimensions after
            # the wide tile was already saved — resize rather than skip
            # the whole intro over a 1px mismatch.
            wide_bg = cv2.resize(wide_bg, (current_bg.shape[1], current_bg.shape[0]))

        hold_frames = max(1, int(tuning.RESIDENTIAL_WIDE_HOLD_SECONDS * fps))
        zoom_frames = max(1, int(tuning.RESIDENTIAL_WIDE_ZOOM_SECONDS * fps))
        for _ in range(hold_frames):
            video.write(wide_bg)
        for frame_i in range(zoom_frames):
            t = self._ease_in_out(frame_i / max(1, zoom_frames - 1))
            blended = cv2.addWeighted(wide_bg, 1.0 - t, current_bg, t, 0.0)
            video.write(blended)
        self.last_frame = current_bg

    def render_waypoints(self, res_sequence: List[Dict], fps: int) -> List[str]:
        """Renders one clip per residential leg; returns the clip paths (a leg whose background can't be read is skipped)."""
        output_paths = []
        job_waypoints = self._get_job_waypoints()
        resolver = _EndpointResolver(job_waypoints, self._get_job_config() or {})
        for i, res_data in enumerate(res_sequence):
            path = self._render_leg(i, res_data, len(res_sequence), fps, job_waypoints, resolver)
            if path is not None:
                output_paths.append(path)
        tracker.clear()
        return output_paths

    def _render_leg(
        self, i: int, res_data: Dict, leg_count: int, fps: int,
        job_waypoints: List[Dict], resolver: _EndpointResolver,
    ) -> Optional[str]:
        opened = self._open_leg_background(res_data["img_path"])
        if opened is None:
            return None
        cap, current_bg, h, w = opened

        res_points = res_data["points"]
        res_labels = res_data["labels"]
        res_popups = res_data.get("popups", [None] * len(res_points))
        res_mode = str(res_data.get("mode", "walking")).lower()
        leg_to_label = _clean_leg_label(res_labels[-1] if res_labels else None)

        timing = self._leg_timing(res_data, res_mode, fps)
        res_smooth_path = self._leg_smooth_path(res_points, timing, fps)
        leg_label = leg_to_label if leg_to_label else (res_labels[-1] if res_labels else f"Leg {i + 1}")
        tracker.show(f"Rendering waypoint leg {i + 1}/{leg_count}: {leg_label}")
        active_res_popups = self._leg_popups(res_points, res_popups, res_labels, job_waypoints)

        chunk_output_path = self._leg_chunk_path(res_data, leg_label, i)
        # [NOTE] [Checkpoint] Existence check only (no content hash), so an interrupted run resumes after the finished legs.
        if self.config.get("checkpoint_enabled", False) and _output_is_valid(chunk_output_path):
            return chunk_output_path

        video = VideoExporter(chunk_output_path, w, h, fps)
        # Off by default (settings.show_leg_wide_intro): the clip opens straight on the waypoint-level map.
        if self.config.get("show_leg_wide_intro", False):
            self._play_leg_wide_intro(video, res_data, current_bg, fps)

        scene = self._build_leg_scene(
            res_data, res_points, res_popups, res_labels, res_smooth_path, leg_to_label, res_mode, w, h, resolver,
        )
        pb = self._leg_playback(video, fps, timing.real_duration)
        show_segment_summary = pb.show_summary

        route_preview_frame = self._route_preview_frame(scene, current_bg)
        waypoint_intro_freeze = float(self.config.get("waypoint_intro_freeze", 2.0))
        if waypoint_intro_freeze > 0 and len(res_points) >= 2:
            route_preview_frame = self._play_intro_popups(pb, scene, route_preview_frame, waypoint_intro_freeze)
        intro_card = _IntroCard()
        if show_segment_summary:
            intro_card = self._play_intro_summary(pb, scene, route_preview_frame, timing)

        ended_at_destination, summary_shown_inline = self._animate_leg(
            pb, scene, cap, current_bg, timing, intro_card, active_res_popups,
        )
        self._play_leg_tail(pb, scene, ended_at_destination, summary_shown_inline)

        output_path = video.release(chunk_output_path)
        if cap:
            cap.release()
        return output_path

    def _play_leg_tail(self, pb: _LegPlayback, scene: _LegScene, ended_at_destination: bool, summary_shown: bool) -> None:
        if not ended_at_destination:
            for _ in range(int(pb.arrival_hold_seconds * pb.fps)):
                pb.video.write(self.last_frame)
        # Fallback for a leg whose destination has no popup at all: the summary shows once at the very end.
        if pb.show_summary and not summary_shown:
            seg_card = self._leg_summary_card(scene.res_data, pb.real_duration, scene.res_mode)
            self._play_leg_summary_card(
                pb.video, self.last_frame, seg_card, pb.fps, pb.fade_sec, pb.clip_hold_sec,
                play_exit=False, margin=self._LEG_CARD_MARGIN_PX, margin_y=self._LEG_CARD_MARGIN_BOTTOM_PX,
            )

    def _leg_playback(self, video: VideoExporter, fps: int, real_duration: float) -> _LegPlayback:
        return _LegPlayback(
            video, fps, self.config.get("summary_fade", 0.5), self.config.get("clip_summary_hold", 2.0),
            self.config.get("show_segment_summary", True), real_duration,
            max(
                self._ARRIVAL_HOLD_MIN_SECONDS,
                min(self._ARRIVAL_HOLD_MAX_SECONDS, float(self.post_arrival_hold_seconds)),
            ),
        )

    def _draw_map_chrome(self, bg: np.ndarray) -> None:
        if self.config.get("waypoint_map_border", True):
            self.graphics.draw_frame_border(bg)
        if self.config.get("show_compass", True):
            self.graphics.draw_compass(bg)

    def _open_leg_background(self, bg_path):
        """(cap or None, first frame, h, w) with even dimensions and map chrome drawn, or None if unreadable."""
        if str(bg_path).lower().endswith(_VIDEO_EXTENSIONS):
            cap = cv2.VideoCapture(str(bg_path))
            ret, current_bg = cap.read()
            if not ret:
                # [NOTE] [IO] Release the handle before skipping this leg — otherwise it leaks for the rest of the render.
                cap.release()
                return None
        else:
            current_bg = self.graphics.read_image_safe(str(bg_path))
            if current_bg is None:
                return None
            cap = None

        h, w = current_bg.shape[:2]
        if h % 2 != 0 or w % 2 != 0:
            h, w = h - (h % 2), w - (w % 2)
            current_bg = cv2.resize(current_bg, (w, h))
        self._draw_map_chrome(current_bg)
        return cap, current_bg, h, w

    def _estimated_real_duration(self, res_data: Dict, res_mode: str, total_duration: float) -> float:
        """Real-world travel time from this leg's distance and its mode's configured speed.

        [NOTE] total_duration/travel_duration are the animation's length in video-seconds, not a real travel
        time, so they are no fallback here (a 6 s ferry ride would read as 6 s); only a leg with no distance
        falls back to them.
        """
        distance_km = res_data.get("distance_km", 0.0)
        if distance_km <= 0:
            return total_duration
        fallback_speed = self.mode_speed_kmh.get("walking", 5.0) or 5.0
        speed_kmh = self.mode_speed_kmh.get(res_mode, fallback_speed) or fallback_speed
        return (distance_km / speed_kmh) * 3600.0

    def _leg_timing(self, res_data: Dict, res_mode: str, fps: int) -> _LegTiming:
        total_duration = res_data.get("segment_duration", self.config.get("res_duration", 12.0))
        travel_duration = res_data.get("travel_duration", total_duration)
        # "real_duration_seconds" is explicitly 0.0 (not absent) when the chunk has no timestamp data.
        real_duration = res_data.get("real_duration_seconds") or 0.0
        if real_duration <= 0:
            real_duration = self._estimated_real_duration(res_data, res_mode, total_duration)
        pauses = res_data.get("pauses", [])
        # [NOTE] [Animation] Floors total_frames at _MIN_LEG_TOTAL_FRAMES so a very short/near-zero-duration leg still produces a playable clip instead of 0-1 frames.
        total_frames = max(self._MIN_LEG_TOTAL_FRAMES, int(total_duration * fps))
        return _LegTiming(
            total_frames, travel_duration, real_duration, pauses,
            _paused_frames(pauses, total_frames, fps),
            sum(p["duration"] for p in pauses) if pauses else 0.0,
        )

    def _leg_smooth_path(self, res_points: List, timing: _LegTiming, fps: int):
        """Spacing-filtered points smoothed into one position per travel frame."""
        filtered_res = [res_points[0]]
        for pt in res_points[1:]:
            if (
                math.hypot(pt[0] - filtered_res[-1][0], pt[1] - filtered_res[-1][1])
                > self._MIN_RESIDENTIAL_POINT_SPACING_PX
            ):
                filtered_res.append(pt)
        if filtered_res[-1] != res_points[-1]:
            filtered_res.append(res_points[-1])

        actual_travel_seconds = max(1.0, timing.travel_duration - timing.total_pause_seconds)
        return MapFetcher.get_smooth_path(
            filtered_res,
            max(2, int(actual_travel_seconds * fps)),
            ease=True,
            simplify_tolerance_px=self._ROUTE_SIMPLIFY_TOLERANCE_PX,
        )

    @staticmethod
    def _leg_popups(res_points, res_popups, res_labels, job_waypoints) -> List[Dict]:
        """The leg's photo popups, with the job's per-waypoint image_display/popup_video merged in by label."""
        popups = [
            {
                "x": res_points[point_idx][0],
                "y": res_points[point_idx][1],
                "data": res_popups[point_idx],
                "label": res_labels[point_idx],
                "index": point_idx,
                # Residential popup cards show just the photo, no caption.
                "show_label": False,
            }
            for point_idx in range(len(res_points))
            if res_popups[point_idx] is not None
        ]
        for popup in popups:
            lbl = str(popup.get("label") or "")
            for jw in job_waypoints if lbl else ():  # "" is in every label
                jw_lbl = str(jw.get("label", ""))
                if jw_lbl and (jw_lbl in lbl or lbl in jw_lbl):
                    if "image_display" in jw and popup["data"].get("image_display", "box") == "box":
                        popup["data"]["image_display"] = jw["image_display"]
                    if "popup_video" in jw and not popup["data"].get("popup_video"):
                        popup["data"]["popup_video"] = jw["popup_video"]
                    break
        return popups

    def _leg_chunk_path(self, res_data: Dict, leg_label: str, i: int) -> str:
        safe_suffix = (
            "".join(c for c in str(leg_label) if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
            or f"leg{i+1}"
        )
        # [NOTE] The number is the 1-based departure waypoint's RAW position (render_step.py's "start_pos"):
        # render_step's audio-mux loop and timeline_step parse it back out (RESIDENTIAL_LEG_RE) to find this
        # leg's narration, which stop-by leg-merging would throw off a purely sequential `i`.
        leg_file_num = res_data.get("start_pos")
        leg_file_num = (leg_file_num + 1) if leg_file_num is not None else (i + 1)
        return str(self.out_dir / f"02_waypoint_{leg_file_num:02d}_{safe_suffix}.mp4")

    def _mid_marker_pins(self, res_data: Dict, w: int, h: int) -> List[Dict]:
        """Merged-in stop-bys along this leg, drawn as plain pins for the whole clip (not gated on the traveler
        having reached them). One with a photo can still show a brief pass-by card."""
        pins = []
        extent = res_data.get("extent")
        for marker_data in res_data.get("mid_markers", []):
            x, y = _marker_display_px(marker_data, extent, w, h)
            pins.append({
                "x": x, "y": y,
                # [NOTE] The pass-by trigger tests the recorded-track pixel, not the display position: a stop-by
                # reprojected onto its real coordinate can sit far from the walked path and would never fire.
                "trigger_x": marker_data["px"][0], "trigger_y": marker_data["px"][1],
                "index": -1, "order": None,
                "label": marker_data.get("label"),
                "data": {
                    "is_stopby": True,
                    "stopby_label": marker_data.get("stopby_label"),
                    "popup_image": marker_data.get("popup_image"),
                    "freeze_seconds": marker_data.get("freeze_seconds") or self._DEFAULT_PASSBY_FREEZE_SECONDS,
                    "image_display": marker_data.get("image_display", "cover"),
                    "triggered": False,
                },
            })
        return pins

    def _landmark_labels(self, mid_marker_pins, leg_to_label, res_points, w, h):
        """Label chips for every stop-by plus the destination: (items, sprites, resolved positions).

        [NOTE] A stop-by pin only carries its "+N", so its name would come from the base map tile, which is
        inconsistent (OSM may not tag it at this zoom); every stop-by gets the same chip as a numbered stop.
        """
        landmark_items = []
        for marker_pin in mid_marker_pins:
            lbl = marker_pin.get("label")
            if RouteGeometryProcessor.is_real_label(lbl):
                landmark_items.append({
                    "id": id(marker_pin),
                    "pin_x": int(marker_pin["x"]),
                    "pin_y": int(marker_pin["y"]),
                    "label": lbl,
                })
        if RouteGeometryProcessor.is_real_label(leg_to_label) and res_points:
            landmark_items.append({
                "id": "end_wp",
                "pin_x": int(res_points[-1][0]),
                "pin_y": int(res_points[-1][1]),
                "label": leg_to_label,
            })

        landmark_sprites = {}
        for item in landmark_items:
            lbl = item["label"]
            if lbl not in landmark_sprites:
                landmark_sprites[lbl] = {
                    "right": self.graphics.prebake_landmark_sprite(lbl, side="right"),
                    "left": self.graphics.prebake_landmark_sprite(lbl, side="left"),
                }

        resolved: Dict[Any, Tuple[str, int, int]] = {}
        placed: List[Tuple[float, float, float, float]] = []
        sorted_items = sorted(
            landmark_items,
            key=lambda it: (0 if it["id"] == "end_wp" else 1, it["pin_y"], it["pin_x"]),
        )
        pin_gap = int(self.graphics.marker_radius + 4)
        for item in sorted_items:
            best_placement = _place_landmark_label(item, landmark_sprites[item["label"]], placed, w, h, pin_gap)
            if best_placement:
                side, bx, by, final_box = best_placement
                placed.append(final_box)
                resolved[item["id"]] = (side, bx, by)
        return landmark_items, landmark_sprites, resolved

    def _build_leg_scene(
        self, res_data, res_points, res_popups, res_labels, res_smooth_path, leg_to_label, res_mode, w, h,
        resolver: _EndpointResolver,
    ) -> _LegScene:
        # [NOTE] Resolved once and shared by the intro beat and the animation's own start/end markers, so a leg
        # through a repeated place name shows the same S/E/stop-by/number in both.
        start_label = res_labels[0] if res_labels else ""
        end_label = res_labels[-1] if res_labels else ""
        res_lats, res_lons = res_data.get("lats"), res_data.get("lons")
        start_match = resolver.resolve(
            res_data.get("start_waypoint_id"), start_label, lat=_edge(res_lats, 0), lng=_edge(res_lons, 0),
        )
        end_match = resolver.resolve(
            res_data.get("end_waypoint_id"), end_label, lat=_edge(res_lats, -1), lng=_edge(res_lons, -1),
        )
        # +2 for the true start/end, which live outside job_waypoints (matches the +1 on every resolved index).
        total_wp = resolver.total_route_points

        mid_marker_pins = self._mid_marker_pins(res_data, w, h)
        landmark_items, landmark_sprites, label_positions = self._landmark_labels(
            mid_marker_pins, leg_to_label, res_points, w, h,
        )
        start_wp = _leg_pin(res_points[0][0], res_points[0][1], start_label, res_popups[0], start_match)
        end_wp = _leg_pin(res_points[-1][0], res_points[-1][1], end_label, res_popups[-1], end_match)
        # The loop route's half green/red split is only drawn by the overview/recap, so split_color is dropped.
        start_pin_label, start_pin_color, _ = self._pin_label_and_color(start_wp, total_wp)
        end_pin_label, end_pin_color, _ = self._pin_label_and_color(end_wp, total_wp)
        return _LegScene(
            res_data, res_points, res_smooth_path, res_mode, w, h, mid_marker_pins, landmark_items,
            landmark_sprites, label_positions, start_wp, end_wp,
            (start_pin_label, start_pin_color), (end_pin_label, end_pin_color), total_wp,
        )

    def _draw_route_guideline(self, target: np.ndarray, res_smooth_path) -> None:
        """Faint full-route line (a preview of where the leg is headed) under the bold traveled path."""
        if len(res_smooth_path) > 1:
            overlay = target.copy()
            cv2.polylines(
                overlay,
                [np.asarray(res_smooth_path, dtype=np.int32)],
                False, self.graphics.line_color, self.graphics.line_thickness,
                cv2.LINE_AA,
            )
            cv2.addWeighted(overlay, _GUIDELINE_ALPHA, target, _GUIDELINE_KEEP, 0, target)

    def _blit_landmarks(self, frame: np.ndarray, scene: _LegScene) -> None:
        for item in scene.landmark_items:
            pos_info = scene.label_positions.get(item["id"])
            if pos_info:
                side, lx, ly = pos_info
                sprite, anchor = scene.landmark_sprites[item["label"]][side]
                self.graphics.blit_sprite(frame, sprite, anchor, lx, ly)

    def _route_preview_frame(self, scene: _LegScene, current_bg: np.ndarray) -> np.ndarray:
        """The route line at reduced opacity plus every pin: the base for the popup intro and the summary slide-in."""
        frame = current_bg.copy()
        self._draw_route_guideline(frame, scene.res_smooth_path)
        for marker_pin in scene.mid_marker_pins:
            self._draw_pin(frame, marker_pin, scene.total_wp)
        self._draw_pin(frame, scene.start_wp, scene.total_wp)
        self._draw_pin(frame, scene.end_wp, scene.total_wp)
        self._blit_landmarks(frame, scene)
        return frame

    def _intro_popup_cards(self, scene: _LegScene) -> List[Dict]:
        cards = []
        for wp, wp_color in ((scene.start_wp, scene.start_pin[1]), (scene.end_wp, scene.end_pin[1])):
            if wp["data"].get("popup_image"):
                card = dict(wp)
                card["hud_corner"] = None
                card["draw_leader_line"] = True
                # Card border matches this waypoint's own pin color (S=green, E=red, stop-by=brown, etc).
                card["border_color"] = wp_color or self.graphics.marker_color
                cards.append(card)
        return cards

    def _layout_intro_cards(self, scene: _LegScene, popup_cards: List[Dict]) -> None:
        """Places the cards with the overview's collision-avoiding search so they stay off the route and the pins."""
        route_obstacle_arr = None
        if len(scene.res_smooth_path) > 1:
            route_obstacle_arr = np.asarray(scene.res_smooth_path, dtype=float)
            if len(route_obstacle_arr) > _ROUTE_OBSTACLE_MAX_POINTS:
                step = max(1, len(route_obstacle_arr) // _ROUTE_OBSTACLE_MAX_POINTS)
                route_obstacle_arr = route_obstacle_arr[::step]
        # A card just above a waypoint would sit on the pin (drawn upward from its anchor), so pins count too.
        pin_obstacles = self._pin_obstacle_points([*scene.mid_marker_pins, scene.start_wp, scene.end_wp])
        if len(pin_obstacles):
            route_obstacle_arr = (
                pin_obstacles if route_obstacle_arr is None else np.vstack([route_obstacle_arr, pin_obstacles])
            )
        footprint_w, footprint_h = self.graphics.beside_card_footprint()
        self._layout_beside_popups(
            [{"popup": c, "frames_left": 1} for c in popup_cards], scene.w, scene.h,
            card_w=footprint_w, card_h=footprint_h,
            route_obstacles=route_obstacle_arr,
            max_radius=float(max(scene.w, scene.h)),
        )

    def _play_intro_popups(
        self, pb: _LegPlayback, scene: _LegScene, route_preview_frame: np.ndarray, freeze: float,
    ) -> np.ndarray:
        """Holds the departure and arrival pins (each with a leader-lined photo card) on the still map before the
        route animates; returns the frame as the new preview base."""
        intro_frame = route_preview_frame.copy()
        popup_cards = self._intro_popup_cards(scene)
        if popup_cards:
            self._layout_intro_cards(scene, popup_cards)
        # Line, then pin, then card, so each leader line sits behind both its pin and its card.
        for popup_card in popup_cards:
            intro_frame = self.graphics.render_popup_box(intro_frame, popup_card, line_only=True)
        self._draw_pin(intro_frame, scene.start_wp, scene.total_wp)
        self._draw_pin(intro_frame, scene.end_wp, scene.total_wp)
        for popup_card in popup_cards:
            intro_frame = self.graphics.render_popup_box(intro_frame, popup_card, skip_line=True)
        for _ in range(int(freeze * pb.fps)):
            pb.video.write(intro_frame)
        self.last_frame = intro_frame
        return intro_frame

    def _play_intro_summary(
        self, pb: _LegPlayback, scene: _LegScene, route_preview_frame: np.ndarray, timing: _LegTiming,
    ) -> _IntroCard:
        """Slides this leg's summary card up before the traveler moves, so the viewer knows where it is headed.

        [NOTE] Only the entrance plays here; hold and exit are composited onto the real animation's first
        frames (_composite_intro_card). The hold covers the whole animation, so the exit frames are reserved
        but never reached: the arrival cuts to its own fresh summary.
        """
        card = self._leg_summary_card(scene.res_data, pb.real_duration, scene.res_mode)
        self._play_leg_summary_card(
            pb.video, route_preview_frame, card, pb.fps, pb.fade_sec, pb.clip_hold_sec,
            margin=self._LEG_CARD_MARGIN_PX, margin_y=self._LEG_CARD_MARGIN_BOTTOM_PX, play_exit=False, play_hold=False,
        )
        self.last_frame = route_preview_frame
        return _IntroCard(
            card, timing.total_frames, max(1, int(pb.fade_sec * pb.fps)),
            card.shape[0] + self._CARD_SLIDE_MARGIN_PX,
        )

    def _composite_intro_card(self, frame: np.ndarray, current_frame: int, ic: _IntroCard) -> np.ndarray:
        """Intro card hold, then exit, over the real animation frames."""
        if ic.card is None or current_frame >= ic.hold_frames + ic.exit_frames:
            return frame
        if current_frame < ic.hold_frames:
            alpha, slide = 1.0, 0.0
        else:
            t = (current_frame - ic.hold_frames + 1) / ic.exit_frames
            eased = 1 - (1 - t) ** 3
            alpha, slide = 1.0 - t, ic.slide_distance * eased
        return self.graphics.composite_card_on_frame(
            frame, ic.card, alpha=alpha, margin=self._LEG_CARD_MARGIN_PX, margin_y=self._LEG_CARD_MARGIN_BOTTOM_PX,
            slide_offset_y=slide,
        )

    def _within_trigger_radius(self, px, py, prev_cx, prev_cy, cx, cy) -> bool:
        """Has the traveler's path segment come within the pin's trigger radius (stop-by pass-by and popup arrival)."""
        return (
            prev_cx is not None
            and prev_cy is not None
            and RouteGeometryProcessor.point_to_segment_distance(px, py, prev_cx, prev_cy, cx, cy)
            < (self.graphics.marker_radius + self.trigger_radius_padding["waypoint"])
        )

    def _draw_travel_layers(
        self, frame: np.ndarray, scene: _LegScene, current_chunk_px, cx: int, cy: int,
        current_frame: int, smoothed_angle: float, prev_cx, prev_cy,
    ) -> float:
        """Guideline, traveled path, pins, landmark chips, S/E markers and (last) the mode icon; returns the heading."""
        # Redrawn per frame (not the cached preview) so it stays right over a video background.
        self._draw_route_guideline(frame, scene.res_smooth_path)
        if len(current_chunk_px) > 1:
            cv2.polylines(
                frame,
                [current_chunk_px.astype(np.int32)],
                False,
                self.graphics.line_color,
                self.graphics.line_thickness,
                cv2.LINE_AA,
            )
        for marker_pin in scene.mid_marker_pins:
            self._draw_pin(frame, marker_pin, scene.total_wp)
        self._blit_landmarks(frame, scene)
        smoothed_angle = self._smoothed_heading(smoothed_angle, cx, cy, prev_cx, prev_cy)

        if scene.res_points:
            # Same resolved label/color as the intro beat: this leg's endpoints aren't necessarily the trip's.
            for (px, py), (pin_label, pin_color), wp in (
                (scene.res_points[0], scene.start_pin, scene.start_wp),
                (scene.res_points[-1], scene.end_pin, scene.end_wp),
            ):
                self.graphics.draw_marker(
                    frame, int(px), int(py), number=pin_label, color=pin_color,
                    is_circle=bool(wp.get("data", {}).get("is_stopby")),
                )
        # Drawn LAST so the mode icon isn't hidden behind a pin the traveler is at.
        self.graphics.draw_transport_icon(frame, cx, cy, current_frame, smoothed_angle, mode=scene.res_mode)
        return smoothed_angle

    def _play_passby_card(self, pb: _LegPlayback, marker_pin: Dict, frame: np.ndarray) -> None:
        """A brief pip card for a stop-by the traveler passes: fades in over the live frame, holds, fades out
        while the leg keeps animating (not a real stop: no fullscreen, doesn't end the clip)."""
        pass_card = dict(marker_pin)
        pass_card["hud_corner"] = None
        pass_card["draw_leader_line"] = True
        pass_card["border_color"] = self._STOPBY_PIN_COLOR
        fade_frames = max(1, int(pb.fade_sec * pb.fps))
        hold_frames = max(1, int(
            float(marker_pin["data"].get("freeze_seconds", self._DEFAULT_PASSBY_FREEZE_SECONDS)) * pb.fps
        ))
        for frame_idx in range(fade_frames):
            pb.video.write(
                self.graphics.render_popup_box(frame, pass_card, alpha=(frame_idx + 1) / fade_frames)
            )
        held_pass_frame = self.graphics.render_popup_box(frame, pass_card, alpha=1.0)
        for _ in range(max(0, hold_frames - fade_frames)):
            pb.video.write(held_pass_frame)
        for frame_idx in range(fade_frames):
            pb.video.write(
                self.graphics.render_popup_box(frame, pass_card, alpha=1.0 - (frame_idx + 1) / fade_frames)
            )
        self.last_frame = frame

    def _play_arrival(self, pb: _LegPlayback, scene: _LegScene, popup: Dict, frame: np.ndarray) -> bool:
        """The arrival sequence: plain hold, the leg's summary card, then scale-up-with-blur to fullscreen.
        Returns whether the summary card was shown."""
        # [NOTE] [Popup] end_pin_color can be None (not-yet-"arrived" pin) and popup_box.py's border_color
        # lookup only defaults on a missing key, so None would crash it: fall back to marker_color.
        popup["border_color"] = (
            scene.end_pin[1]
            if popup["index"] == len(scene.res_points) - 1
            else self.graphics.arrived_marker_color
        ) or self.graphics.marker_color
        # Hold plain first so the transition doesn't read as an abrupt cut the instant the pin is reached.
        for _ in range(max(1, int(pb.arrival_hold_seconds * pb.fps))):
            pb.video.write(frame)

        # The summary plays on the plain arrival frame BEFORE the popup transition, not over the photo.
        if pb.show_summary:
            seg_card = self._leg_summary_card(scene.res_data, pb.real_duration, scene.res_mode)
            self._play_leg_summary_card(
                pb.video, frame, seg_card, pb.fps, pb.fade_sec, pb.clip_hold_sec,
                margin=self._LEG_CARD_MARGIN_PX, margin_y=self._LEG_CARD_MARGIN_BOTTOM_PX,
            )

        # Every arrival uses the scale-up-with-blur-to-fullscreen transition whatever its image_display.
        arrival_popup = {**popup, "data": {**popup["data"], "freeze_seconds": pb.arrival_hold_seconds}}
        end_frame, _ = self.graphics.play_fullscreen_popup_sequence(
            video=pb.video,
            base_frame=frame,
            popup_info=arrival_popup,
            fps=pb.fps,
            transition_cfg=self.transition_cfg,
            exit_frame=frame,
        )
        self.last_frame = end_frame
        return pb.show_summary

    def _next_video_background(self, cap, current_bg: np.ndarray, scene: _LegScene) -> np.ndarray:
        """The next frame of a video background (the previous one when the video has run out)."""
        ret, vid_frame = cap.read()
        if not ret:
            return current_bg
        if vid_frame.shape[0] != scene.h or vid_frame.shape[1] != scene.w:
            vid_frame = cv2.resize(vid_frame, (scene.w, scene.h))
        self._draw_map_chrome(vid_frame)
        return vid_frame

    def _play_passbys(self, pb: _LegPlayback, scene: _LegScene, frame: np.ndarray, prev, cur) -> None:
        for marker_pin in scene.mid_marker_pins:
            if marker_pin["data"]["triggered"] or not marker_pin["data"].get("popup_image"):
                continue
            if self._within_trigger_radius(
                marker_pin.get("trigger_x", marker_pin["x"]), marker_pin.get("trigger_y", marker_pin["y"]),
                *prev, *cur,
            ):
                marker_pin["data"]["triggered"] = True
                self._play_passby_card(pb, marker_pin, frame)

    def _play_arrivals(
        self, pb: _LegPlayback, scene: _LegScene, active_res_popups: List[Dict], frame: np.ndarray,
        just_arrived: bool, prev, cur,
    ) -> Tuple[bool, bool]:
        """Plays the arrival for every popup the path just reached; returns (any played, summary shown)."""
        arrived = shown = False
        for popup in active_res_popups:
            if popup["data"]["triggered"]:
                continue
            # The departure popup already played in the intro; without this the traveler starting on top of
            # it would trigger it again within the first frames and end the clip almost immediately.
            if popup["index"] == 0:
                continue
            near_segment = self._within_trigger_radius(popup["x"], popup["y"], *prev, *cur)
            if near_segment or just_arrived:
                popup["data"]["triggered"] = True
                if self._play_arrival(pb, scene, popup, frame):
                    shown = True
                arrived = True
        return arrived, shown

    def _animate_leg(
        self, pb: _LegPlayback, scene: _LegScene, cap, current_bg: np.ndarray, timing: _LegTiming,
        intro_card: _IntroCard, active_res_popups: List[Dict],
    ) -> Tuple[bool, bool]:
        """Plays the travel frames; returns (ended at the destination popup, summary already shown inline)."""
        res_smooth_path = scene.res_smooth_path
        path_idx = 0
        prev_cx, prev_cy = None, None
        smoothed_angle = self._initial_heading(res_smooth_path)
        ended_at_destination = False
        summary_shown_inline = False

        for current_frame in range(timing.total_frames):
            is_paused = timing.paused_per_frame[current_frame]
            just_arrived = False
            if not is_paused and path_idx < len(res_smooth_path) - 1:
                path_idx += 1
                if path_idx == len(res_smooth_path) - 1:
                    just_arrived = True

            if cap is not None and not is_paused:
                current_bg = self._next_video_background(cap, current_bg, scene)

            current_point = res_smooth_path[path_idx]
            frame = current_bg.copy()
            current_chunk_px = res_smooth_path[: path_idx + 1]
            if len(current_chunk_px) > 1:
                cx, cy = int(current_chunk_px[-1][0]), int(current_chunk_px[-1][1])
            else:
                cx, cy = int(current_point[0]), int(current_point[1])

            if cap is None:
                smoothed_angle = self._draw_travel_layers(
                    frame, scene, current_chunk_px, cx, cy, current_frame, smoothed_angle, prev_cx, prev_cy,
                )

            self._play_passbys(pb, scene, frame, (prev_cx, prev_cy), (cx, cy))
            arrived, shown = self._play_arrivals(
                pb, scene, active_res_popups, frame, just_arrived, (prev_cx, prev_cy), (cx, cy),
            )
            if arrived:
                ended_at_destination = True
            if shown:
                summary_shown_inline = True

            if not ended_at_destination:
                frame = self._composite_intro_card(frame, current_frame, intro_card)
                pb.video.write(frame)
                self.last_frame = frame
            prev_cx, prev_cy = cx, cy
            if ended_at_destination:
                break
        return ended_at_destination, summary_shown_inline
