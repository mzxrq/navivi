"""Cut/fade and blur-out transition primitives, plus the end-of-video recap,
summary card, and higher-zoom "callback to where the journey began" highlight."""

import math
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from services.mapfetcher.mapgeometry import RouteGeometryProcessor
from services.vdoprocessing.route_inputs import stop_is_numbered
from services.vdoprocessing.vdoexporter import VideoExporter
from services import tuning
from services.mapbox_token import resolve_mapbox_token
from services.mapfetcher.maplanguage import resolve_map_style
from .base import logger

# The ending highlight's final hold stretches for leftover narration (see
# _render_ending_highlight's remaining_audio_seconds), but never past this.
_MAX_ENDING_HIGHLIGHT_HOLD_SECONDS = 15.0

# Popup keys the recap stamps on the shared popup dict that the highlight must not inherit.
_STALE_RECAP_POPUP_KEYS = (
    "card_scale", "beside_box", "leader_via", "recap_line_color",
    "is_pill_badge", "suppress_leader_line", "leader_from",
)
# The pop-in clock runs over a never-reached total so only fade_frames shapes the animation.
_ENDING_POP_TOTAL_FRAMES = 10 ** 6
# Static-tile Ken Burns: zoom reached after the wait phase, and at the end of the pip hold.
_ENDING_KEN_BURNS_ZOOM_MID = 1.18
_ENDING_KEN_BURNS_ZOOM_END = 1.35


class _TransitionMixin:
    # Divisor/floor used to size _blur_out's max Gaussian kernel radius
    # relative to the frame's short edge (see the comment at its call site).
    _BLUR_KSIZE_DIVISOR = 20
    _BLUR_MIN_KSIZE = 3

    # Default hold time (seconds) used when a popup's own "freeze_seconds"
    # is absent from its data.
    _DEFAULT_FREEZE_SECONDS = 3.0

    # Multiplier on marker_radius used to decide whether a nearby waypoint
    # pin would land close enough to the featured pin to be treated as
    # "the same point" and skipped in _draw_nearby_waypoints.
    _SAME_POINT_RADIUS_MULTIPLIER = 2

    # Multiplier on max(w, h) used to bound the off-screen margin route
    # points get clamped to in _draw_route_line_on_extent.
    _ROUTE_LINE_MARGIN_MULTIPLIER = 5

    @staticmethod
    def _ken_burns_hold(
        video: VideoExporter,
        frame: np.ndarray,
        fps: int,
        duration_sec: float,
        zoom_cx: float,
        zoom_cy: float,
        zoom_from: float = 1.0,
        zoom_to: float = 1.18,
    ) -> np.ndarray:
        """Slow, continuous zoom-in on `frame` itself while it's held on
        screen (the classic Ken Burns photo effect), toward (zoom_cx,
        zoom_cy), instead of holding one static frame. No second image
        involved and no cut/fade to build or align — `frame` is already
        the genuinely higher-zoom, freshly fetched tile, so this is just
        motion added to what's already on screen. Kept to a modest zoom
        range (well under 2x) so the source stays crisp — it's magnifying
        pixels that are already there, so a large zoom would soften
        visibly, but this range doesn't. Returns the final (most-zoomed)
        frame written, so a later hold can continue the zoom from there."""
        h, w = frame.shape[:2]
        total_frames = max(1, int(duration_sec * fps))
        last = frame
        for frame_idx in range(total_frames):
            progress = frame_idx / max(1, total_frames - 1)
            zoom = zoom_from + (zoom_to - zoom_from) * progress
            crop_w, crop_h = w / zoom, h / zoom
            cx = min(max(zoom_cx, crop_w / 2), w - crop_w / 2)
            cy = min(max(zoom_cy, crop_h / 2), h - crop_h / 2)
            x0, y0 = int(cx - crop_w / 2), int(cy - crop_h / 2)
            x1, y1 = int(x0 + crop_w), int(y0 + crop_h)
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(w, x1), min(h, y1)
            last = cv2.resize(
                frame[y0:y1, x0:x1], (w, h), interpolation=cv2.INTER_CUBIC
            )
            video.write(last)
        return last

    def _blur_out(
        self, video: VideoExporter, frame: np.ndarray, fps: int, duration_sec: float = 0.5
    ) -> np.ndarray:
        """Writes a progressive out-of-focus blur of `frame` (increasing
        Gaussian blur radius each frame) as a soft closing beat, and
        returns the final, most-blurred frame. Used as the video's actual
        last frames instead of a hard cut or fade-to-black — a bare cut
        would jump straight into whatever plays next, and this reads
        smoothly even when the next clip opens on this exact picture."""
        total_frames = max(1, int(duration_sec * fps))
        max_ksize = max(
            self._BLUR_MIN_KSIZE, (min(frame.shape[:2]) // self._BLUR_KSIZE_DIVISOR) | 1
        )  # odd, ~5% of the short edge
        blurred = frame
        for frame_idx in range(total_frames):
            ksize = max(1, round((frame_idx + 1) / total_frames * max_ksize)) | 1
            blurred = cv2.GaussianBlur(frame, (ksize, ksize), 0)
            video.write(blurred)
        return blurred

    def _ending_zoom_follows(self, stop_popup) -> bool:
        """The summary is followed by the zoom to the start point and its photo (not the course style)."""
        return bool(
            stop_popup and self.config.get("enable_ending_highlight", True) and self.config.get("overview_style") != "course"
        )

    def _render_recap_and_summary(
        self,
        video: VideoExporter,
        stop_popup: Optional[Dict],
        summary_card: Optional[np.ndarray],
        active_popups: List[Dict],
        w: int,
        h: int,
        fps: int,
        route_obstacle_arr: np.ndarray,
        reserved_boxes: List[Tuple[float, float, float, float]],
        pre_popup_frame: Optional[np.ndarray],
    ) -> float:
        """Builds the end-of-video recap and fades the summary stat card in
        on top of it, returning how long (seconds) the caller should hold
        on the result before moving on. Updates self.last_frame; does not
        write that final hold itself, since the highlight
        (_render_ending_highlight) may still need to run first.

        The recap shows EVERY waypoint's card at once, fading in together
        from the clean map in a single crossfade rather than trickling in a
        few at a time. The whole set is laid out up front into the frame's
        free space (see _layout_recap_cards) — disjoint slots, so no two
        cards can overlap, matched to pins by minimum total leader length,
        which leaves the lines both short and uncrossed — and every pin is
        already visible on `outro_frame` regardless. All of this is written
        directly here (not left to the caller's own trailing hold loop), so
        the returned outro_hold_sec covers only the summary card's own hold
        on top of the fully-revealed recap."""
        outro_hold_sec = 0.0
        outro_frame = None
        final_frame = None
        hold_frames = 0

        if stop_popup:
            # Clean plate (see pre_popup_frame's own comment above) rather
            # than self.last_frame, which can still have a not-yet-finished
            # popup fade-out baked into it. Preferably the walk's PIN-FREE
            # plate (_recap_plate, stashed by _animate_overview_frames):
            # the recap marks each stop with its own plain dot instead
            # (_render_recap_frame), and a dot drawn over the teardrop pin
            # the walk left behind would leave that pin sticking out
            # around it. The fullscreen photo comes later, in
            # _render_ending_highlight after the zoom — never here.
            base_plate = getattr(self, "_recap_plate", None)
            if base_plate is None or base_plate.shape[:2] != (h, w):  # not this render's
                base_plate = pre_popup_frame if pre_popup_frame is not None else self.last_frame
            outro_frame = base_plate.copy()
            all_recap_popups = self._recap_popup_set(active_popups, stop_popup)
            total_freeze = float(
                stop_popup["data"].get("freeze_seconds", self._DEFAULT_FREEZE_SECONDS)
            )
            # With the zoom next, the summary hold (ENDING_SUMMARY_HOLD_SECONDS) is the only wait.
            hold_frames = 0 if self._ending_zoom_follows(stop_popup) else max(0, int(total_freeze * fps))

            if all_recap_popups:
                # Laid out again for the recap, even when the cards stayed up
                # through the whole walk: those sat in slots pitched for a
                # full photo card, and leaving the badges there spaces them a
                # card's width apart. A badge is slim, so its own lattice
                # packs them side by side — the cross-fade below carries each
                # card into its badge.
                laid_out = self._layout_recap_cards(
                    all_recap_popups, w, h,
                    reserved_boxes=reserved_boxes,
                    route_obstacles=route_obstacle_arr,
                    background=base_plate,  # badges go where the map itself is empty
                    leaders=False,  # the badge's number and its pin's are the tie, not a line
                    total_points=1 + max((ap["index"] for ap in active_popups), default=0),
                )
                final_frame = self._render_recap_frame(
                    outro_frame, active_popups, group_popups=laid_out
                )
            else:
                final_frame = outro_frame

        # The summary card is composited onto the SAME target frame the
        # recap cards fade into, and both cross-fade in together below —
        # it used to fade in on its own, after the recap cards had already
        # settled and held, which read as two separate reveals.
        if summary_card is not None:
            base = final_frame if final_frame is not None else self.last_frame
            final_frame = self.graphics.composite_card_on_frame(base, summary_card, alpha=1.0)
            outro_hold_sec = max(
                outro_hold_sec, float(self.config.get("summary_hold", 4.0))
            )

        if final_frame is not None:
            # Cards that stayed up are already on the last frame: fading from the bare map would blink them.
            source = self.last_frame if self._cards_stay() or outro_frame is None else outro_frame
            # The beat where every stop's card is still up, before they all
            # become badges, is written by the walk itself (see
            # _animate_overview_frames' own RECAP_CARD_HOLD_SECONDS tail) —
            # there the cards are still live, so one that popped as the walk
            # ended finishes fading in instead of freezing half-drawn.
            fade_sec = max(
                tuning.RECAP_GROUP_FADE_SECONDS, float(self.config.get("summary_fade", 0.5))
            )
            fade_frames = max(1, int(fade_sec * fps))
            for i in range(fade_frames):
                alpha = (i + 1) / fade_frames
                video.write(cv2.addWeighted(final_frame, alpha, source, 1 - alpha, 0))
            for _ in range(max(0, hold_frames - fade_frames)):
                video.write(final_frame)
            self.last_frame = final_frame

        return outro_hold_sec

    # How long to hold the higher-zoom map (with its marker + leader-lined
    # popup) before handing off to the fullscreen photo transition — the
    # "switch to higher map, then wait a bit" beat.
    # Timing/zoom values below live in services/tuning.py — the shared home
    # for hand-tunable constants across spatial_renderer + graphicengine.
    _ENDING_HIGHLIGHT_WAIT_SECONDS = tuning.ENDING_HIGHLIGHT_WAIT_SECONDS

    # How long to push in on the CURRENT wide map (before cutting to the
    # freshly fetched close-up tile) so the highlight beat reads as
    # "zooming FROM the big map INTO the start point" rather than a
    # close-up simply appearing. Longer duration = smaller per-frame zoom
    # step at the same fps = a smoother push, less of a "skip" feel right
    # up to the cut.
    _BIG_MAP_ZOOM_LEAD_SECONDS = tuning.BIG_MAP_ZOOM_LEAD_SECONDS
    # How far that lead-in push zooms in, before the cut — pushed further
    # in than before (1.9x) so the map is already close to the residential
    # sequence's own zoom level by the time it cuts, rather than stopping
    # at a middling zoom and leaving a second, more noticeable jump for the
    # residential clip that follows this video.
    _BIG_MAP_ZOOM_TARGET = tuning.BIG_MAP_ZOOM_TARGET

    def _draw_route_line_on_extent(
        self,
        frame: np.ndarray,
        w: int,
        h: int,
        extent: Tuple[float, float, float, float],
    ) -> None:
        """Redraws the route line on a freshly fetched close-up tile — the
        ending highlight's own extent is a genuinely different (much more
        zoomed-in) map than the main overview render, so the pixel-space
        path drawn there doesn't carry over; this reprojects the lat/lon
        route (stashed by render_overview as self._route_latlon_path) onto
        THIS frame's extent instead. Drawn before pins/markers so it sits
        underneath them, matching the main overview's own draw order. A
        no-op when there's no stashed route (e.g. render_overview wasn't
        given an extent to reproject from in the first place)."""
        route_latlon = getattr(self, "_route_latlon_path", None)
        if not route_latlon:
            return
        pts = [
            RouteGeometryProcessor.project_latlon_to_pixel(lat, lon, extent, w, h)
            for lat, lon in route_latlon
        ]
        # Generous but bounded margin — keeps genuinely nearby off-screen
        # stretches connecting properly across the frame edge without
        # letting a wildly out-of-view point blow up into huge coordinates.
        margin = max(w, h) * self._ROUTE_LINE_MARGIN_MULTIPLIER
        pts = [
            (int(min(max(px, -margin), w + margin)), int(min(max(py, -margin), h + margin)))
            for px, py in pts
        ]
        arr = np.array(pts, dtype=np.int32)
        if self.graphics.line_border_thickness:
            cv2.polylines(
                frame, [arr], False, self.graphics.line_border_color,
                self.graphics.line_thickness + self.graphics.line_border_thickness * 2,
                cv2.LINE_AA,
            )
        cv2.polylines(
            frame, [arr], False, self.graphics.line_color,
            self.graphics.line_thickness, cv2.LINE_AA,
        )

    def _draw_nearby_waypoints(
        self,
        frame: np.ndarray,
        w: int,
        h: int,
        extent: Tuple[float, float, float, float],
        exclude_px: int,
        exclude_py: int,
    ) -> None:
        """Draws a plain color dot (see _draw_recap_dot_color — this
        highlight beat is the same "recap" family, no teardrop/numbered
        pins) for every OTHER job_config waypoint that happens to fall
        inside this freshly fetched close-up tile — the featured waypoint
        (at exclude_px/exclude_py) gets its own dedicated marker drawn
        separately by the caller, so it's skipped here. Uses the same
        S/E/stop-by/number color precedence as everywhere else (via
        _pin_label_and_color), computed from each waypoint's real
        position in job_config's own waypoints list."""
        job_waypoints = (self._get_job_config() or {}).get("waypoints", [])
        # job_config's own "waypoints" array holds only the INTERMEDIATE
        # stops — the true start/end live in separate "start_point"/
        # "end_point" keys (see _render_ending_highlight's own zoom_point
        # lookup) — so index 0 / len-1 here are just the first/last
        # intermediate stop, NOT the route's real S/E. Without the +1/+2
        # offset, _pin_label_and_color's own index==0 / index==total-1
        # checks (written assuming the FULL route's points array, where
        # those positions genuinely ARE S/E) mislabeled those two
        # intermediate waypoints as "S"/green and "E"/red.
        total_wp = len(job_waypoints)
        total_points = total_wp + 2
        # A project whose list ALSO holds its start (and end) as the first (last) waypoint: those are S/E
        # themselves, so the numbers start after them, as in the overview (they were one too high).
        from services.vdoprocessing.route_inputs import same_place

        start_point = (self._get_job_config() or {}).get("start_point") or {}
        holds_ends = bool(job_waypoints) and bool(start_point) and same_place(job_waypoints[0], start_point)
        offset = 0 if holds_ends else 1
        if holds_ends:
            total_points = total_wp
        order = 0
        for pos, jw in enumerate(job_waypoints):
            is_stopby = bool(jw.get("isStopBy", False) or jw.get("skipAssetGeneration"))
            if stop_is_numbered(job_waypoints, pos) and not (holds_ends and pos == 0):
                order += 1
            # A loop route's job_config waypoints list ends with a
            # synthetic "(Return)" entry at the SAME coordinates as the
            # route's own start/end — the real S/E pin already covers
            # that point (see _is_loop_route's half-green/half-red pin
            # elsewhere). The exclude_px/exclude_py check below is meant
            # to filter this out too (same coords as the featured point),
            # but at this highlight's high zoom, a tiny lat/lng rounding
            # difference between this entry and the true end_point can
            # put it just outside that pixel radius — showing up as an
            # extra, oddly-numbered pin sitting right next to S/E (e.g.
            # "12" for a 10-stop route). Skipped outright here instead of
            # relying on the distance check to catch it.
            if self._is_loop_route and pos == total_wp - 1:
                continue
            lat, lng = jw.get("lat"), jw.get("lng", jw.get("lon"))
            if lat is None or lng is None:
                continue
            px, py = RouteGeometryProcessor.project_latlon_to_pixel(lat, lng, extent, w, h)
            px, py = int(px), int(py)
            if not (0 <= px <= w and 0 <= py <= h):
                continue
            if (
                math.hypot(px - exclude_px, py - exclude_py)
                < self.graphics.marker_radius * self._SAME_POINT_RADIUS_MULTIPLIER
            ):
                continue  # the featured waypoint itself
            # "arrived": True — this only ever runs at the very end of
            # the video, once the whole route (every waypoint) has
            # genuinely been visited, so every pin here should show its
            # own arrived_marker_color, same as it does for the rest of
            # the video, rather than falling back to the DEFAULT
            # (not-yet-visited) marker_color — visibly wrong whenever a
            # project has customized the two to different colors.
            wp = {"index": pos + offset, "order": order, "data": {"is_stopby": is_stopby, "arrived": True,
                                                                "inaccessible": bool(jw.get("inaccessible"))}}
            _, color, _ = self._pin_label_and_color(wp, total_points)
            self._draw_recap_dot_color(frame, px, py, color)

    def _gl_ending_zoom_enabled(self, bounding_box) -> bool:
        settings = (self._get_job_config() or {}).get("settings", {}) or {}
        return bounding_box is not None and (
            bool(settings.get("enable_gl_ending_zoom", True))  # on by default; false turns the pydeck zoom off
            or str(settings.get("overview_background", "")).lower() == "pydeck"
        )

    @staticmethod
    def _ending_adjacent_latlon(job_config: Dict, is_start: bool) -> Tuple[Optional[float], Optional[float]]:
        """The neighbouring stop that biases the highlight's framing (choose_route_focus_view's
        next_lat/next_lon), so the shot shows the way the route leads. On the START that is the
        first waypoint (the leg heading away); on the END fallback it is the last waypoint
        (the leg arriving into it)."""
        job_waypoints = job_config.get("waypoints") or []
        if is_start:
            adjacent = job_waypoints[0] if job_waypoints else job_config.get("end_point")
        else:
            adjacent = job_waypoints[-1] if job_waypoints else job_config.get("start_point")
        if not isinstance(adjacent, dict):
            return None, None
        return adjacent.get("lat"), adjacent.get("lng", adjacent.get("lon"))

    @staticmethod
    def _ending_must_fit_latlon(job_waypoints: List[Dict]) -> List[Tuple[float, float]]:
        """Every waypoint (stops and stop-bys, which often sit just off the route and get
        cropped) worth keeping in shot; choose_route_focus_view treats it as a reward only."""
        return [
            (jw["lat"], jw.get("lng", jw.get("lon")))
            for jw in job_waypoints
            if jw.get("lat") is not None and jw.get("lng", jw.get("lon")) is not None
        ]

    def _ending_pip_hold_seconds(self, remaining_audio_seconds: Optional[float]) -> float:
        """The pip picture is held briefly (tuning), stretching to cover narration still left
        once the lead-in + wait have played, capped so a bad audio length can't run away."""
        highlight_hold_sec = float(tuning.ENDING_HIGHLIGHT_PIP_HOLD_SECONDS)
        if remaining_audio_seconds is not None:
            needed = remaining_audio_seconds - self._BIG_MAP_ZOOM_LEAD_SECONDS - self._ENDING_HIGHLIGHT_WAIT_SECONDS
            highlight_hold_sec = max(highlight_hold_sec, min(needed, _MAX_ENDING_HIGHLIGHT_HOLD_SECONDS))
        return highlight_hold_sec

    def _fresh_highlight_popup(self, featured_popup: Dict, x: int, y: int, w: int, h: int) -> Dict:
        """A copy of the featured popup placed fresh on the close-up as a full leader-lined
        pop up card (the one the fullscreen transition grows out of, not a pill badge)."""
        highlight_popup = featured_popup.copy()
        highlight_popup["data"] = featured_popup["data"].copy()
        highlight_popup["x"], highlight_popup["y"] = x, y
        # [NOTE] [Popup] featured_popup is the same dict the recap just stamped with its own
        # shrunk card_scale, a wide-frame beside_box and pill flags, and pin_x/pin_y is a
        # declutter position in the overview's pixel space; left in, the card would draw at
        # the recap's size and the leader line would anchor on a stale spot.
        for _stale_key in ("pin_x", "pin_y", *_STALE_RECAP_POPUP_KEYS):
            highlight_popup.pop(_stale_key, None)
        highlight_popup["hud_corner"] = None  # forces the leader-lined "beside" card style
        highlight_popup["draw_leader_line"] = True
        # Short-leader placement (starts ~55px from the pin); render_popup_box's own fallback
        # is meant for corner-avoidance and can land the card far across the frame.
        self._layout_recap_popups([{"popup": highlight_popup, "frames_left": 1}], w, h)
        # The photo sits on top of its pin (the free layout could hang it below).
        self._place_cards_above_pins([highlight_popup], w, h, *self.graphics.beside_card_footprint())
        return highlight_popup

    def _capture_ending_zoom_frames(
        self, bounding_box: Dict[str, float], w: int, h: int, lat: float, lng: float,
        zoom_n: int, settings: Dict, next_lat: Optional[float], next_lon: Optional[float],
        must_fit_latlon: List[Tuple[float, float]],
    ):
        """Real re-rendered deck.gl frames for the lead-in + wait push, or None if the capture
        raised (the caller then falls back to the static-tile path)."""
        try:
            from services.mapfetcher.pydeck_overview import capture_pydeck_zoom_sequence

            map_style = resolve_map_style(settings, "mapbox/streets-v12")
            dynamic_frames = capture_pydeck_zoom_sequence(
                bounding_box, (w, h), lat, lng, zoom_n,
                zoom_boost=tuning.ENDING_HIGHLIGHT_PYDECK_ZOOM_BOOST,
                mapbox_key=resolve_mapbox_token(settings),
                map_style=map_style,
                # The route this video drew (stashed by render_overview), so the push settles
                # on a view that keeps the line through this point in shot.
                route_latlon=getattr(self, "_route_latlon_path", None),
                next_lat=next_lat, next_lon=next_lon,
                must_fit_latlon=must_fit_latlon,
            )
            logger.info(
                "Ending highlight: dynamic pydeck capture returned %d frame(s) "
                "(requested zoom_n=%d).",
                len(dynamic_frames) if dynamic_frames else 0, zoom_n,
            )
        except Exception:
            logger.warning(
                "Dynamic pydeck ending-highlight zoom failed; falling back to "
                "the static-tile Ken Burns version.", exc_info=True,
            )
            return None
        return dynamic_frames

    def _draw_ending_card(
        self, frame: np.ndarray, highlight_popup: Dict, pop: Dict, frames_left: int,
        frame_px: int, frame_py: int, pin_color,
    ) -> np.ndarray:
        """Composites the popping-in highlight card (line, then marker, then card) on `frame`."""
        highlight_popup["x"], highlight_popup["y"] = frame_px, frame_py
        card = highlight_popup.copy()
        pop["frames_left"] = frames_left
        alpha = self._popup_fade_alpha(pop)
        if card.get("beside_box"):
            bx, by = card["beside_box"]
            by += self._popup_slide_offset_y(pop)
            grow = self._popup_enter_scale(pop)
            if grow < 0.999:
                full_w, full_h = self.graphics.beside_card_footprint(1.0)
                now_w, now_h = self.graphics.beside_card_footprint(grow)
                bx, by = bx + (full_w - now_w) / 2, by + (full_h - now_h) / 2
                card["card_scale"] = grow
            card["beside_box"] = (int(bx), int(by))
        frame = self.graphics.render_popup_box(frame, card, alpha=alpha, line_only=True)
        self._draw_recap_dot_color(frame, frame_px, frame_py, pin_color)
        return self.graphics.render_popup_box(frame, card, alpha=alpha, skip_line=True)

    def _play_dynamic_ending(
        self, video: VideoExporter, dynamic_frames: List, featured_popup: Dict,
        lat: float, lng: float, w: int, h: int, fps: int, is_start: bool, hold_n: int,
    ) -> Dict:
        """Writes the whole highlight beat (lead-in + wait + pip hold) from the captured GL
        frames, with the card popping in once the zoom settles. Returns the highlight popup."""
        px, py = RouteGeometryProcessor.project_latlon_to_pixel(
            lat, lng, dynamic_frames[-1][1], w, h
        )
        highlight_popup = self._fresh_highlight_popup(featured_popup, int(px), int(py), w, h)
        pin_color = self._START_PIN_COLOR if is_start else self._END_PIN_COLOR

        pop_start = len(dynamic_frames)
        pop_frames = max(1, int(tuning.ENDING_HIGHLIGHT_POP_SECONDS * fps))
        pop = {
            "total_frames": _ENDING_POP_TOTAL_FRAMES,
            "frames_left": _ENDING_POP_TOTAL_FRAMES,
            "fade_frames": pop_frames,
        }
        frame_out = None
        for frame_idx in range(pop_start + hold_n):
            if frame_idx - pop_start > pop_frames:
                video.write(frame_out)
                continue
            frame_bgr, extent = dynamic_frames[min(frame_idx, pop_start - 1)]
            frame_out = frame_bgr.copy()
            # [NOTE] [Popup] Re-projected against THIS frame's extent: with route_latlon the push
            # interpolates toward choose_route_focus_view's end view, which doesn't keep the
            # point on one pixel (the last frame's projection left the marker over open water).
            frame_px, frame_py = RouteGeometryProcessor.project_latlon_to_pixel(lat, lng, extent, w, h)
            frame_px, frame_py = int(frame_px), int(frame_py)
            # The featured point is excluded by _draw_nearby_waypoints, so its marker is drawn here.
            self._draw_route_line_on_extent(frame_out, w, h, extent)
            self._draw_nearby_waypoints(frame_out, w, h, extent, frame_px, frame_py)
            if frame_idx < pop_start:
                self._draw_recap_dot_color(frame_out, frame_px, frame_py, pin_color)
            else:
                frame_out = self._draw_ending_card(
                    frame_out, highlight_popup, pop,
                    _ENDING_POP_TOTAL_FRAMES - (frame_idx - pop_start),
                    frame_px, frame_py, pin_color,
                )
            video.write(frame_out)
        self.last_frame = frame_out
        return highlight_popup

    def _play_static_ending(
        self, video: VideoExporter, w: int, h: int, fps: int, lat: float, lng: float,
        next_lat: Optional[float], next_lon: Optional[float], featured_popup: Dict,
        clean_map_frame: Optional[np.ndarray], is_start: bool, highlight_hold_sec: float,
    ) -> Optional[Dict]:
        """Static-tile path: a lead-in push on the wide map, a hard cut to a freshly fetched
        higher-zoom tile, then a continuous Ken Burns zoom while held. Returns the highlight
        popup, or None when there is no tile to show."""
        fetched = self._fetch_highlight_image(lat, lng, (w, h), next_lat=next_lat, next_lon=next_lon)
        if not fetched:
            return None
        highlight_path, highlight_extent = fetched
        highlight_bg = self.graphics.read_image_safe(highlight_path)
        if highlight_bg is None:
            return None
        if highlight_bg.shape[:2] != (h, w):
            highlight_bg = cv2.resize(highlight_bg, (w, h))

        px, py = RouteGeometryProcessor.project_latlon_to_pixel(lat, lng, highlight_extent, w, h)
        px, py = int(px), int(py)

        # Nearby waypoints can fall inside the close-up; drawn with the same labeling as the overview.
        self._draw_route_line_on_extent(highlight_bg, w, h, highlight_extent)
        self._draw_nearby_waypoints(highlight_bg, w, h, highlight_extent, px, py)

        # Lead-in: push in on the clean plate (no cards) toward the point before the cut.
        lead_in_source = clean_map_frame if clean_map_frame is not None else self.last_frame
        self.last_frame = self._ken_burns_hold(
            video, lead_in_source, fps, self._BIG_MAP_ZOOM_LEAD_SECONDS,
            featured_popup["x"], featured_popup["y"],
            zoom_from=1.0, zoom_to=self._BIG_MAP_ZOOM_TARGET,
        )

        highlight_popup = self._fresh_highlight_popup(featured_popup, px, py, w, h)
        pin_color = self._START_PIN_COLOR if is_start else self._END_PIN_COLOR
        # Line, then marker, then card, so the leader line sits behind both.
        highlight_bg = self.graphics.render_popup_box(highlight_bg, highlight_popup, line_only=True)
        self._draw_recap_dot_color(highlight_bg, px, py, pin_color)
        highlight_frame = self.graphics.render_popup_box(highlight_bg, highlight_popup, skip_line=True)

        # Zoom toward the stop at px/py in the highlight image's own pixels (featured_popup's
        # x/y are overview-map pixels, a different image).
        self.last_frame = self._ken_burns_hold(
            video, highlight_frame, fps, self._ENDING_HIGHLIGHT_WAIT_SECONDS, px, py,
            zoom_from=1.0, zoom_to=_ENDING_KEN_BURNS_ZOOM_MID,
        )
        # Continue the same push through the hold: one continuous zoom, not moving-then-frozen.
        self.last_frame = self._ken_burns_hold(
            video, highlight_frame, fps, highlight_hold_sec, px, py,
            zoom_from=_ENDING_KEN_BURNS_ZOOM_MID, zoom_to=_ENDING_KEN_BURNS_ZOOM_END,
        )
        return highlight_popup

    def _play_ending_fullscreen(self, video: VideoExporter, highlight_popup: Dict, fps: int) -> bool:
        """The narration has ended by now: the photo grows to fullscreen, holds briefly and
        blurs out. True when it played (the video's hard ending)."""
        scale_sec = self.transition_cfg["scale_seconds"]
        hold_sec = self.transition_cfg["min_hold_seconds"]
        tail_start = video.frames_written
        t_frames = self.graphics.generate_fullscreen_popup_transition(
            base_frame=self.last_frame,
            popup_info=highlight_popup,
            fps=fps,
            duration_sec=scale_sec,
            hold_sec=hold_sec,
            fade_out_sec=self.transition_cfg["fade_out_seconds"],
        )
        if not t_frames:
            return False
        # Drop the trailing fade-back-to-the-map portion: this photo is the video's last frame.
        keep = max(1, int(scale_sec * fps)) + max(1, int(hold_sec * fps))
        t_frames = t_frames[:keep]
        for transition_frame in t_frames:
            video.write(transition_frame)

        # Blur out rather than cutting on the photo, which would jump straight into the next
        # clip even when it opens on this same picture.
        self.last_frame = self._blur_out(video, t_frames[-1], fps)
        # Plays after the voice, so not part of the audio/video match.
        self.ending_tail_seconds = (video.frames_written - tail_start) / fps
        return True

    def _render_ending_highlight(
        self,
        video: VideoExporter,
        w: int,
        h: int,
        fps: int,
        stop_popup: Dict,
        start_popup: Optional[Dict] = None,
        clean_map_frame: Optional[np.ndarray] = None,
        bounding_box: Optional[Dict[str, float]] = None,
        remaining_audio_seconds: Optional[float] = None,
    ) -> bool:
        """End-of-video highlight: a hard cut (no transition) from the
        recap straight to a freshly fetched, genuinely higher-zoom map
        centered on the trip's START point — with its own marker and a
        leader-lined popup, featuring the start waypoint's own photo —
        then, while it's held, a slow continuous Ken Burns zoom-in on that
        same image (rather than a static freeze), before handing off to a
        fullscreen photo transition (if that waypoint's
        image_display is "fullscreen") or just hold on the pip card. A
        "callback to where the journey began" reveal to close the video,
        rather than repeating the end waypoint's own photo (already shown
        in the recap). Falls back to the end waypoint/point if there's no
        start one available.

        The highlight beat itself opens with a lead-in push toward the same
        point on `clean_map_frame` — a plain map+route+pins plate with no
        popup cards or the summary stat card baked in (pass the recap's own
        pre-popup-card frame here; falls back to self.last_frame, cards and
        all, if not given) — before the hard cut to the freshly fetched
        close-up tile. Zooming on the clean plate rather than self.last_frame
        (which by this point has every waypoint's leader-lined photo card
        AND the summary card composited on top) keeps that lead-in a plain
        map push instead of dragging a screenful of cards along with it.

        When `bounding_box` is given AND settings.overview_background is
        "pydeck", the lead-in push and the cut-to-a-second-static-tile
        above are BOTH replaced by one continuous sequence of genuinely
        re-rendered deck.gl frames (mapfetcher.pydeck_overview.
        capture_pydeck_zoom_sequence) — the map itself gets visibly
        sharper terrain/street/building detail as it zooms in, rather
        than a digital crop of one already-fetched image. Falls back to
        the static-tile path automatically on any capture failure.

        Returns True if the fullscreen photo transition played and the
        caller should treat this as the video's hard ending (write nothing
        further) — the fullscreen photo, once reached, is meant to be the
        last thing the video shows, not fade back down to the map for a
        trailing pause. Returns False otherwise (pip hold, or this highlight
        didn't run at all — no point to zoom to, or the image fetch
        failed — never worth losing an otherwise-finished render over), in
        which case the caller's normal trailing pause still applies.

        `remaining_audio_seconds`, when given, is how much narration is
        still left to play once this highlight starts — its own final hold
        stretches to cover that (never shrinks below the tuning default),
        so the highlight stays up until the closing line (distance/stats)
        finishes, rather than the caller's own fixed floor cutting it off
        early with narration still playing over a frozen last frame."""
        job_config = self._get_job_config() or {}
        is_start = bool(job_config.get("start_point"))
        zoom_point = job_config.get("start_point") or job_config.get("end_point") or {}
        lat, lng = zoom_point.get("lat"), zoom_point.get("lng")
        if lat is None or lng is None:
            return False

        job_waypoints = job_config.get("waypoints") or []
        next_lat, next_lon = self._ending_adjacent_latlon(job_config, is_start)
        must_fit_latlon = self._ending_must_fit_latlon(job_waypoints)

        featured_popup = start_popup or stop_popup
        settings = (job_config.get("settings", {}) or {})
        # enable_gl_ending_zoom, or overview_background "pydeck" as an alternate opt-in.
        use_dynamic_pydeck = self._gl_ending_zoom_enabled(bounding_box)
        # Diagnostic: a False use_dynamic_pydeck, or a capture that returns nothing without
        # raising, otherwise leaves no trace of why the static-tile path ran.
        logger.info(
            "Ending highlight: use_dynamic_pydeck=%s (bounding_box_present=%s, "
            "enable_gl_ending_zoom=%s, overview_background=%r)",
            use_dynamic_pydeck, bounding_box is not None,
            settings.get("enable_gl_ending_zoom", True),
            settings.get("overview_background"),
        )
        highlight_hold_sec = self._ending_pip_hold_seconds(remaining_audio_seconds)

        dynamic_frames = None
        if use_dynamic_pydeck:
            # [NOTE] [Animation] The camera moves only through lead-in + wait (zoom_n real
            # frames); the pip hold reuses that final frame, a real hold that also skips
            # browser round-trips for identical frames.
            lead_in_n = max(1, int(self._BIG_MAP_ZOOM_LEAD_SECONDS * fps))
            wait_n = max(1, int(self._ENDING_HIGHLIGHT_WAIT_SECONDS * fps))
            hold_n = max(1, int(highlight_hold_sec * fps))
            dynamic_frames = self._capture_ending_zoom_frames(
                bounding_box, w, h, lat, lng, lead_in_n + wait_n, settings,
                next_lat, next_lon, must_fit_latlon,
            )

        if dynamic_frames:
            highlight_popup = self._play_dynamic_ending(
                video, dynamic_frames, featured_popup, lat, lng, w, h, fps, is_start, hold_n
            )
        else:
            highlight_popup = self._play_static_ending(
                video, w, h, fps, lat, lng, next_lat, next_lon, featured_popup,
                clean_map_frame, is_start, highlight_hold_sec,
            )
            if highlight_popup is None:
                return False

        # Always ends on the fullscreen photo; image_display is ignored.
        return self._play_ending_fullscreen(video, highlight_popup, fps)
