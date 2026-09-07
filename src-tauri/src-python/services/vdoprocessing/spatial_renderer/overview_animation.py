"""The overview's frame-by-frame animation loop — split out of overview.py
(render_overview itself) so that file is left holding just the setup
(labels, path building, intro beat) and wrap-up (recap, summary, ending
highlight), with this, the largest single piece, isolated on its own.
Behavior-identical extraction: this is the same loop body render_overview
used to run inline, now parameterized instead of closing over render_overview's
locals directly."""

from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from services.mapfetcher.mapgeometry import RouteGeometryProcessor
from services.vdoprocessing.vdoexporter import VideoExporter


class _OverviewAnimationMixin:
    def _animate_overview_frames(
        self,
        video: VideoExporter,
        current_bg: np.ndarray,
        cap,
        is_video: bool,
        w: int,
        h: int,
        fps: int,
        smooth_path: np.ndarray,
        mode_breakpoints: List[Tuple[float, str]],
        cum_smooth_dist: Optional[np.ndarray],
        total_smooth_dist: float,
        active_popups: List[Dict],
        stop_popup: Optional[Dict],
        points: List,
        route_avoid_points: List,
        route_obstacle_arr: np.ndarray,
    ) -> Optional[np.ndarray]:
        """Drives the traveler along `smooth_path`, triggering pins/popups
        as it goes, and writes every frame to `video`. Mutates `self.last_frame`
        and each popup dict's own "triggered" state in place (active_popups
        is a list of dicts shared with the caller) rather than returning
        them. Returns pre_popup_frame — the last frame's plain map+pins
        plate (no popup cards baked in), captured right before the final
        frame if there's a stop_popup to arrive at, used afterward by the
        recap and the ending highlight's own lead-in zoom. None if there's
        no stop_popup."""
        baked_popups: List[Dict] = []
        path_history = []
        mode_history = []
        prev_cx, prev_cy = None, None
        smoothed_angle = self._initial_heading(smooth_path)
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

            # stop_popup (the destination "E" pin) is deliberately excluded
            # from the proximity-trigger loop below — its arrival is
            # handled separately, by _render_recap_and_summary /
            # _render_ending_highlight — but the per-frame pin-drawing
            # below piggybacks on that same "triggered" flag, so without
            # this its pin was NEVER drawn on the main map at all (not
            # even once the traveler had actually reached it), only ever
            # appearing via the separate ending-highlight's own marker.
            if (
                stop_popup
                and not stop_popup["data"]["triggered"]
                and current_frame == len(smooth_path) - 1
            ):
                stop_popup["data"]["triggered"] = True

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

        return pre_popup_frame
