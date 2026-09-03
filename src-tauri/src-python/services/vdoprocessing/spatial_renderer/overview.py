"""The overview map render entry point: drives the traveler along the full
route, triggering pins/popups and mode-aware pacing along the way."""

import json
import math
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from services.mapfetcher.mapfetcher import MapFetcher
from services.mapfetcher.mapgeometry import RouteGeometryProcessor
from services.vdoprocessing.vdoexporter import VideoExporter

from .base import logger


class _OverviewRenderMixin:
    @staticmethod
    def _build_mode_breakpoints(points: List, point_modes: List[str]) -> List[Tuple[float, str]]:
        """Cumulative-distance fractions (0..1 along the route) at which the
        travel mode changes, so the animated trail/icon can react to
        routeMode transitions (e.g. walking -> ferry)."""
        if not points or not point_modes or len(points) != len(point_modes):
            return []

        cum = [0.0]
        for i in range(1, len(points)):
            cum.append(
                cum[-1]
                + math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1])
            )
        total = cum[-1] or 1.0

        breakpoints = [(0.0, point_modes[0])]
        for i in range(1, len(points)):
            if point_modes[i] != breakpoints[-1][1]:
                breakpoints.append((cum[i] / total, point_modes[i]))
        return breakpoints

    @staticmethod
    def _mode_at_fraction(breakpoints: List[Tuple[float, str]], frac: float) -> str:
        if not breakpoints:
            return "walking"
        mode = breakpoints[0][1]
        for bp_frac, bp_mode in breakpoints:
            if frac >= bp_frac:
                mode = bp_mode
            else:
                break
        return mode

    def render_overview(
        self,
        bg_path: str,
        points: List,
        labels: List,
        popups: List,
        fps: int,
        summary: Optional[Dict] = None,
        point_modes: Optional[List[str]] = None,
    ) -> str:
        is_video = False

        if is_video:
            cap = cv2.VideoCapture(str(bg_path))
            ret, current_bg = cap.read()
            if not ret:
                raise FileNotFoundError(f"Cannot read video frames from: {bg_path}")
        else:
            current_bg = self.graphics.read_image_safe(str(bg_path))
            if current_bg is None:
                raise FileNotFoundError(f"Cannot read background image: {bg_path}")
            cap = None

        h, w = current_bg.shape[:2]
        if h % 2 != 0 or w % 2 != 0:
            h, w = h - (h % 2), w - (w % 2)
            current_bg = cv2.resize(current_bg, (w, h))

        duration = self.config.get("duration", 30.0)
        num_frames = max(10, int(duration * fps))

        start_label, end_label = "開始", "終点"
        for p in [self.out_dir] + list(self.out_dir.parents):
            potential_path = p / "job_config.json"
            if potential_path.exists():
                try:
                    with open(potential_path, "r", encoding="utf-8") as f:
                        job_data = json.load(f)
                        start_label = job_data.get("start_point", {}).get(
                            "label", start_label
                        )
                        end_label = job_data.get("end_point", {}).get(
                            "label", end_label
                        )
                except Exception:
                    pass
                break

        cleaned_labels = []
        for i, lbl in enumerate(labels):
            if i == 0:
                cleaned_labels.append(start_label)
            elif i == len(points) - 1:
                cleaned_labels.append(end_label)
            else:
                cleaned_labels.append(
                    lbl.replace("Start: ", "")
                    .replace("Stop: ", "")
                    .replace("Start", "")
                    .replace("Stop", "")
                    .strip()
                    if lbl
                    else None
                )


        # Light dedup only — drop literal near-duplicate points so the spline
        # fit doesn't choke on zero-length segments. We deliberately do NOT
        # thin more aggressively than this by raw distance: a tight turn has
        # its points close together too, and stripping those is exactly what
        # let the smoothed path swing wide of sharp corners (cutting across
        # ground the real road never touches). get_smooth_path's own
        # Douglas-Peucker pass below reduces density based on actual
        # curvature (perpendicular deviation), which is the correct signal.
        filtered_points = [points[0]]
        for pt in points[1:]:
            if (
                math.hypot(
                    pt[0] - filtered_points[-1][0], pt[1] - filtered_points[-1][1]
                )
                > 0.5
            ):
                filtered_points.append(pt)
        # Ensure the final destination is always included
        if filtered_points[-1] != points[-1]:
            filtered_points.append(points[-1])

        mode_breakpoints = self._build_mode_breakpoints(points, point_modes) if point_modes else []

        if mode_breakpoints:
            # Faster real-world modes (ferry, car) should visually cover
            # ground quicker on screen than a walking leg of the same
            # length — sample the path densely first, then pick out
            # `num_frames` of those samples spaced by "speed-weighted"
            # distance rather than raw pixel distance. That compresses the
            # frame budget spent on fast legs and leaves more of it for
            # walking ones, instead of moving at one constant on-screen
            # speed regardless of travel mode.
            dense_n = max(num_frames * 4, 400)
            dense_arr = np.asarray(
                MapFetcher.get_smooth_path(
                    filtered_points, dense_n, ease=True, simplify_tolerance_px=2.2
                ),
                dtype=float,
            )
            seg_lens = np.hypot(np.diff(dense_arr[:, 0]), np.diff(dense_arr[:, 1]))
            cum_dense = np.concatenate([[0.0], np.cumsum(seg_lens)])
            total_dense = cum_dense[-1] or 1.0
            fracs = cum_dense / total_dense
            speeds = np.array(
                [
                    self._mode_speed_factor.get(
                        self._mode_at_fraction(mode_breakpoints, f), 1.0
                    )
                    for f in fracs
                ]
            )
            seg_speed = (speeds[:-1] + speeds[1:]) / 2.0
            virtual_seg = np.where(seg_speed > 0, seg_lens / seg_speed, seg_lens)
            virtual_cum = np.concatenate([[0.0], np.cumsum(virtual_seg)])
            total_virtual = virtual_cum[-1] or 1.0

            target = np.linspace(0.0, total_virtual, num_frames)
            idx = np.clip(np.searchsorted(virtual_cum, target), 1, len(virtual_cum) - 1)
            v0, v1 = virtual_cum[idx - 1], virtual_cum[idx]
            t = np.where(v1 > v0, (target - v0) / (v1 - v0), 0.0)
            smooth_path = dense_arr[idx - 1] + (dense_arr[idx] - dense_arr[idx - 1]) * t[:, None]

            smooth_arr = smooth_path
            final_seg_lens = np.hypot(
                np.diff(smooth_arr[:, 0]), np.diff(smooth_arr[:, 1])
            )
            total_smooth_dist = float(final_seg_lens.sum()) or 1.0
            cum_smooth_dist = np.concatenate([[0.0], np.cumsum(final_seg_lens)])
        else:
            smooth_path = MapFetcher.get_smooth_path(
                filtered_points, num_frames, ease=True, simplify_tolerance_px=2.2
            )
            cum_smooth_dist, total_smooth_dist = None, 1.0

        active_popups = [
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
        # 1-based visit order, used to number each waypoint's pin and to
        # sort concurrently-visible popups in _layout_beside_popups.
        for order, ap in enumerate(active_popups, start=1):
            ap["order"] = order
        self._declutter_pins(active_popups)

        job_waypoints = self._get_job_waypoints()
        for i, popup in enumerate(active_popups):
            if i < len(job_waypoints):
                jw = job_waypoints[i]
                if (
                    "image_display" in jw
                    and popup["data"].get("image_display", "box") == "box"
                ):
                    popup["data"]["image_display"] = jw["image_display"]
                if "popup_video" in jw and not popup["data"].get("popup_video"):
                    popup["data"]["popup_video"] = jw["popup_video"]
                # Waypoints flow through by default (the traveler never
                # stops, all the way to the end) — set "freeze_frame": true
                # on a waypoint in job_config.json to opt IT back into the
                # old held-frame arrival pause. Flow-through popup cards
                # ride along beside the pin (see _layout_beside_popups)
                # rather than holding the frame.
                if "freeze_frame" in jw:
                    popup["data"]["freeze_frame"] = bool(jw["freeze_frame"])

        # Static footprint (the full route line + every pin) used to pick a
        # HUD corner that the popup card won't sit on top of. Computed once
        # from the whole route rather than the animated path-so-far, so a
        # given waypoint's card always lands in the same corner regardless
        # of when in the animation it triggers.
        route_avoid_points = list(points) + [
            (p["x"], p["y"]) for p in active_popups
        ]

        # Same footprint, as a decimated numpy array — lets
        # _layout_beside_popups check a candidate card position against the
        # route line itself (cheaply, vectorized) so a flow-through card
        # doesn't get planted right on top of the path it's next to.
        route_obstacle_arr = np.asarray(route_avoid_points, dtype=float)
        if len(route_obstacle_arr) > 400:
            step = max(1, len(route_obstacle_arr) // 400)
            route_obstacle_arr = route_obstacle_arr[::step]

        logger.info(f"Rendering Overview Map ({duration}s)")
        overview_path = str(self.out_dir / "01_overview.mp4")
        video = VideoExporter(overview_path, w, h, fps)
        baked_popups = []

        intro_frame = current_bg.copy()
        start_popup = next((p for p in active_popups if p["index"] == 0), None)
        stop_popup = next(
            (p for p in active_popups if p["index"] == len(points) - 1), None
        )

        # A flow-through popup's display duration defaults to a fixed
        # freeze_seconds regardless of how long that leg of the route
        # actually takes to animate — so on a short leg the NEXT waypoint's
        # popup could trigger while the previous one is still showing, and
        # on a long leg it could vanish long before the traveler arrives.
        # Instead, tie it to the leg itself: find each waypoint's own
        # expected frame (nearest point along the animated path) and set
        # its popup to last exactly from there until the next waypoint's
        # expected frame — "2 to 3" shows popup 2, and the moment 3 is
        # reached popup 2 hides and popup 3 takes over.
        smooth_arr_lookup = np.asarray(smooth_path, dtype=float)

        def _expected_frame(px: float, py: float) -> int:
            dists = np.hypot(smooth_arr_lookup[:, 0] - px, smooth_arr_lookup[:, 1] - py)
            return int(np.argmin(dists))

        triggerable = [
            ap for ap in active_popups
            if ap["index"] != 0 and (not stop_popup or ap["index"] != stop_popup["index"])
        ]
        triggerable.sort(key=lambda ap: _expected_frame(ap["x"], ap["y"]))
        stop_expected_frame = (
            _expected_frame(stop_popup["x"], stop_popup["y"]) if stop_popup else None
        )
        min_leg_frames = int(fps * 1.5)
        for i, ap in enumerate(triggerable):
            this_frame = _expected_frame(ap["x"], ap["y"])
            next_frame = (
                _expected_frame(triggerable[i + 1]["x"], triggerable[i + 1]["y"])
                if i + 1 < len(triggerable)
                else stop_expected_frame
            )
            if next_frame is not None:
                ap["leg_display_seconds"] = (
                    max(min_leg_frames, next_frame - this_frame) / fps
                )

        intro_freeze_sec = 3.0
        if start_popup and "freeze_seconds" in start_popup["data"]:
            intro_freeze_sec = float(start_popup["data"]["freeze_seconds"])

        if start_popup:
            temp_sp = start_popup.copy()
            temp_sp["data"] = start_popup["data"].copy()
            temp_sp["data"]["triggered"] = True
            temp_sp["hud_corner"], temp_sp["x"], temp_sp["y"] = (
                self.graphics.pick_hud_corner(w, h, route_avoid_points),
                start_popup["x"],
                start_popup["y"],
            )
            start_popup["data"]["triggered"] = True

            if not is_video:
                # Show every waypoint marker up front on the intro frame,
                # not just the start point, so the whole route's stops are
                # visible before the animation begins.
                for order, wp in enumerate(active_popups, start=1):
                    self._draw_pin(intro_frame, wp, order, len(points))

            # The intro always opens as a plain pip card, regardless of
            # this waypoint's own image_display setting — "fullscreen"
            # is only ever honored by the end-of-video zoom-tile highlight
            # (_render_ending_highlight), not here.
            intro_frame = self.graphics.render_popup_box(intro_frame, temp_sp)
            for _ in range(int(intro_freeze_sec * fps)):
                video.write(intro_frame)
            self.last_frame = intro_frame

        path_history = []
        mode_history = []
        prev_cx, prev_cy = None, None
        smoothed_angle = 0.0
        # path_history index where the most recently reached waypoint sits —
        # marks the boundary between "earlier, completed legs" (always kept
        # visible) and "the current leg" (the only part hidden while its
        # arrival popup is showing).
        last_leg_boundary = 0
        # The last frame's state right before baked-popup cards are
        # composited that iteration — i.e. pins and route, no popup card
        # overlay. Captured only on the loop's final iteration (see below)
        # rather than using self.last_frame, which can carry a still-fading
        # popup card baked in: without this, a card mid-fade-out exactly
        # when the animation ends gets baked into the recap's background at
        # partial opacity, and then _render_recap_frame draws that SAME
        # waypoint's card again on top at full opacity — a blurry/ghosted
        # double-image for whichever popup happened to still be fading.
        pre_popup_frame = None

        for current_frame, p in enumerate(smooth_path):
            if is_video:
                ret, vid_frame = cap.read()
                if ret:
                    if vid_frame.shape[0] != h or vid_frame.shape[1] != w:
                        vid_frame = cv2.resize(vid_frame, (w, h))
                    current_bg = vid_frame

            frame = current_bg.copy()

            path_history.append((int(p[0]), int(p[1])))

            if cum_smooth_dist is not None:
                frac = cum_smooth_dist[current_frame] / total_smooth_dist
                current_mode = self._mode_at_fraction(mode_breakpoints, frac)
            else:
                current_mode = "walking"
            mode_history.append(current_mode)

            if not is_video:
                self.graphics.draw_path(frame, path_history, mode_history)

            # Detected here, BEFORE the pin/popup drawing below, so a
            # waypoint's pin and its popup card appear on the very same
            # frame it's reached — detecting it after drawing (as this used
            # to) left the just-arrived pin (and, for a frozen waypoint,
            # its popup entirely) invisible for the whole held/flowing
            # display, only catching up once the NEXT frame drew fresh.
            cx, cy = path_history[-1]
            px, py = path_history[-2] if len(path_history) > 1 else path_history[-1]

            triggered_popup = None
            for popup in active_popups:
                if popup["index"] == 0 or (
                    stop_popup and popup["index"] == stop_popup["index"]
                ):
                    continue
                if not popup["data"]["triggered"]:
                    if RouteGeometryProcessor.point_to_segment_distance(
                        popup["x"], popup["y"], px, py, cx, cy
                    ) < (
                        self.graphics.marker_radius
                        + self.trigger_radius_padding["overview"]
                    ):
                        popup["data"]["triggered"] = True
                        triggered_popup = popup
                        break

            # "Point to point" snapshot for hide_route_on_popup — every
            # earlier, already-completed leg stays drawn; only the CURRENT
            # leg (since the last waypoint reached) is left off, so arriving
            # at a stop doesn't erase the whole route travelled so far.
            # Built separately (rather than copying `frame` before the line
            # is drawn) because pins still need to render on top of the
            # route line for normal display below.
            frame_no_route = None
            if not is_video and self.hide_route_on_popup:
                frame_no_route = current_bg.copy()
                self.graphics.draw_path(
                    frame_no_route,
                    path_history[: last_leg_boundary + 1],
                    mode_history[: last_leg_boundary + 1],
                )
                for order, wp in enumerate(active_popups, start=1):
                    if wp["data"].get("triggered") or wp["index"] == 0:
                        self._draw_pin(frame_no_route, wp, order, len(points))

            if not is_video:
                # Every waypoint is shown once up front on the intro frame
                # (a preview of the whole route), but from here on a pin
                # only reappears once the traveler actually reaches it —
                # not-yet-visited stops stay hidden instead of cluttering
                # the map with numbers for places not reached yet.
                for order, wp in enumerate(active_popups, start=1):
                    if wp["data"].get("triggered") or wp["index"] == 0:
                        self._draw_pin(frame, wp, order, len(points))

            # Only the very last iteration's pre-popup frame is ever read
            # (see the recap's use of it, below) — smooth_path's length is
            # fixed and known up front (no early-exit branch in this loop),
            # so skip the per-frame copy everywhere else instead of paying
            # for a full-resolution frame copy on every single frame of
            # the animation.
            if stop_popup and current_frame == len(smooth_path) - 1:
                pre_popup_frame = frame.copy()
            frame, baked_popups = self._composite_baked_popups(
                frame, baked_popups, w, h, route_obstacle_arr
            )

            if frame_no_route is None:
                frame_no_route = frame

            if triggered_popup:
                # Everything up to (and including) this point becomes part
                # of an "earlier leg" for the NEXT popup's hide effect.
                last_leg_boundary = len(path_history) - 1

                # Pick a corner clear of the route/pins once, and keep it on
                # the popup itself so the lingering baked-popup HUD (below)
                # doesn't jump to a different corner mid-display.
                triggered_popup["hud_corner"] = self.graphics.pick_hud_corner(
                    w, h, route_avoid_points
                )

                # Shared base for BOTH the arrival-hold pause and the popup
                # itself — decluttered to only already-arrived pins when
                # requested, and with the per-leg stat card baked in up
                # front so the pause and the popup read as one continuous
                # "you arrived" beat instead of the card popping in only
                # once the popup shows.
                if self.hide_upcoming_pins_on_popup:
                    popup_base_frame = self._build_freeze_frame(
                        current_bg, path_history, mode_history,
                        last_leg_boundary, active_popups, len(points),
                    )
                else:
                    popup_base_frame = frame_no_route if self.hide_route_on_popup else frame

                # Fullscreen popups are an inherent full-screen takeover —
                # they always freeze regardless of the waypoint's
                # freeze_frame setting, since "flow through" wouldn't mean
                # anything for a shot that covers the whole frame. Every
                # other waypoint now flows through by default — the
                # traveler continues moving past each stop all the way to
                # the end; a waypoint only freezes if it opts in with
                # "freeze_frame": true in job_config.json.
                is_fullscreen = (
                    self.enable_fullscreen_popups
                    and triggered_popup["data"].get("image_display") == "fullscreen"
                )
                freeze_frame_on = (
                    triggered_popup["data"].get("freeze_frame", False) or is_fullscreen
                )

                if not freeze_frame_on:
                    # Flow-through: the traveler keeps moving — no held
                    # frame, no arrival pause. The popup card rides along as
                    # a HUD overlay beside the waypoint's own pin (with a
                    # leader line back to it, drawn in render_popup_box) for
                    # roughly the duration of this leg (see
                    # leg_display_seconds above) rather than always the
                    # fixed freeze_seconds, so it hands off to the next
                    # popup right around when that waypoint is reached
                    # instead of lingering past it or vanishing early.
                    display_seconds = float(
                        triggered_popup.get("leg_display_seconds")
                        or triggered_popup["data"].get("freeze_seconds", 4.0)
                    )
                    new_bp = self._make_baked_popup(triggered_popup, display_seconds, fps)
                    baked_popups.append(new_bp)
                    frame = popup_base_frame
                    if not is_video:
                        smoothed_angle = self._smoothed_heading(
                            smoothed_angle, cx, cy, prev_cx, prev_cy
                        )
                        self.graphics.draw_transport_icon(
                            frame, cx, cy, current_frame, smoothed_angle, mode=current_mode
                        )
                        # Render its card immediately too — otherwise the
                        # pin (already on this frame above) would show a
                        # full frame before its popup catches up on the
                        # next one. Faded in from the start (see
                        # _popup_fade_alpha), same as every later frame
                        # _composite_baked_popups draws it for.
                        self._layout_beside_popups(
                            [new_bp], w, h, route_obstacles=route_obstacle_arr
                        )
                        hud_new = triggered_popup.copy()
                        hud_new["hud_corner"] = None
                        hud_new["draw_leader_line"] = True
                        frame = self.graphics.render_popup_box(
                            frame, hud_new, alpha=self._popup_fade_alpha(new_bp)
                        )
                    self.last_frame = frame
                    video.write(frame)
                    prev_cx, prev_cy = cx, cy
                    continue

                # Hold on the traveler having just reached the pin for a
                # beat before the fullscreen/pip transition kicks in — but
                # the popup photo itself is already visible (as its small
                # pip card) through this hold, so the pause reads as "the
                # popup has arrived and is settling in" rather than a gap
                # with nothing shown yet.
                if not is_video and self.post_arrival_hold_seconds > 0:
                    pause_frame = popup_base_frame.copy()
                    smoothed_angle = self._smoothed_heading(
                        smoothed_angle, cx, cy, prev_cx, prev_cy
                    )
                    self.graphics.draw_transport_icon(
                        pause_frame, cx, cy, current_frame, smoothed_angle, mode=current_mode
                    )
                    pause_frame = self.graphics.render_popup_box(pause_frame, triggered_popup)
                    for _ in range(int(self.post_arrival_hold_seconds * fps)):
                        video.write(pause_frame)

                if is_fullscreen:
                    self.last_frame, _ = self.graphics.play_fullscreen_popup_sequence(
                        video=video,
                        base_frame=popup_base_frame,
                        popup_info=triggered_popup,
                        fps=fps,
                        transition_cfg=self.transition_cfg,
                        exit_frame=frame,
                    )
                else:
                    display_seconds = float(
                        triggered_popup["data"].get("freeze_seconds", 4.0)
                    )
                    # Kept as its own baked_popups entry so it lingers as a
                    # HUD overlay (with its own fade in/out) once the
                    # camera resumes moving — see _composite_baked_popups.
                    lingering_bp = self._make_baked_popup(
                        triggered_popup, display_seconds, fps
                    )
                    baked_popups.append(lingering_bp)
                    hud_triggered = triggered_popup.copy()

                    # The frame itself is frozen (unchanging) for this
                    # whole hold, but the card still fades in rather than
                    # snapping on at full opacity — re-rendered once per
                    # frame (instead of one frame written repeatedly) so
                    # its alpha can ramp up. Reuses the same fade_frames as
                    # the lingering entry above for a consistent ramp.
                    total_hold_frames = lingering_bp["total_frames"]
                    fade_in_frames = lingering_bp["fade_frames"]
                    temp_frame = popup_base_frame
                    for i in range(total_hold_frames):
                        alpha = min(1.0, (i + 1) / fade_in_frames)
                        temp_frame = self.graphics.render_popup_box(
                            popup_base_frame, hud_triggered, alpha=alpha
                        )
                        video.write(temp_frame)

                    self.last_frame = temp_frame

            else:
                if not is_video:
                    smoothed_angle = self._smoothed_heading(
                        smoothed_angle, cx, cy, prev_cx, prev_cy
                    )
                    self.graphics.draw_transport_icon(
                        frame, cx, cy, current_frame, smoothed_angle, mode=current_mode
                    )

                self.last_frame = frame
                video.write(frame)

            prev_cx, prev_cy = cx, cy

        # Built once, up front, so its exact footprint can be reserved
        # (see reserved_boxes below) before the recap frame lays out its
        # popup cards — otherwise a card could land right where this gets
        # composited over the video in the bottom-right corner, later.
        summary_card = None
        if summary:
            summary_card = self.graphics.create_summary_card(
                distance_km=summary.get("total_distance_km", 0.0),
                duration_seconds=summary.get("total_duration_seconds", 0.0),
                mode_breakdown=summary.get("mode_breakdown"),
                mode_duration=summary.get("mode_duration"),
            )
        summary_card_margin = 40
        reserved_boxes = (
            [
                (
                    w - summary_card.shape[1] - summary_card_margin,
                    h - summary_card.shape[0] - summary_card_margin,
                    float(w - summary_card_margin),
                    float(h - summary_card_margin),
                )
            ]
            if summary_card is not None
            else []
        )

        outro_hold_sec = self._render_recap_and_summary(
            video, stop_popup, summary_card, active_popups, w, h, fps,
            route_obstacle_arr, reserved_boxes, pre_popup_frame,
        )
        for _ in range(int(outro_hold_sec * fps)):
            video.write(self.last_frame)

        hard_ended = False
        if stop_popup and self.config.get("enable_ending_highlight", True):
            hard_ended = self._render_ending_highlight(
                video, w, h, fps, stop_popup, start_popup
            )

        for p in popups:
            if p:
                p["triggered"] = False

        # The fullscreen ending highlight, when it plays, IS the video's
        # last frame — no trailing pause on the map afterward.
        if not hard_ended:
            for _ in range(int(self.config.get("pause", 2.0) * fps)):
                video.write(self.last_frame)

        self.last_ending_hard_ended = hard_ended

        if cap:
            cap.release()
        return video.release(overview_path)
