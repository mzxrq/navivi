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
from services.logger.progress import tracker
from services import tuning


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
        # [NOTE] [Animation] path_history index where the most recently reached waypoint sits —
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

        # Live CLI substep + ETA for this (often long, frame-by-frame)
        # render — total_stops excludes the start pin (index 0), which
        # never triggers an arrival of its own. See mapfetcher.py's
        # identical begin_substeps/show_item use for the per-leg tile
        # fetch stage.
        total_stops = max(1, len(active_popups) - 1)
        tracker.begin_substeps(total_stops)
        arrival_count = 0

        # Waypoints placed close together on the map (a common case —
        # several stops within the same block) can otherwise trigger their
        # popups back-to-back within a frame or two of real animation time,
        # popping the current card back out again almost as soon as it
        # appeared. This floor guarantees at least this many seconds of
        # real time between one trigger and the next, regardless of how
        # close the pins themselves are — set far enough in the past that
        # it never blocks the very first trigger.
        min_trigger_gap_frames = int(fps * tuning.OVERVIEW_POPUP_MIN_TRIGGER_GAP_SECONDS)
        last_trigger_frame = -min_trigger_gap_frames
        pending_popups: List[Dict] = []

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

            # [NOTE] [Animation] Detected here, BEFORE the pin/popup drawing below, so a
            # waypoint's pin and its popup card appear on the very same
            # frame it's reached — detecting it after drawing (as this used
            # to) left the just-arrived pin (and, for a frozen waypoint,
            # its popup entirely) invisible for the whole held/flowing
            # display, only catching up once the NEXT frame drew fresh.
            cx, cy = path_history[-1]
            px, py = path_history[-2] if len(path_history) > 1 else path_history[-1]

            # [NOTE] [Animation] stop_popup (the destination "E" pin) is deliberately excluded
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
                # The per-frame pin-drawing loops below key off "arrived"
                # now (see the proximity loop's own comment further down),
                # not "triggered" — set both here so the "E" pin still
                # shows up on this same final frame instead of only ever
                # appearing via the separate ending-highlight's marker.
                stop_popup["data"]["arrived"] = True

            # Queue any not-yet-triggered, not-yet-queued popup the
            # traveler is passing right now — queued (not triggered)
            # immediately, so a popup is never missed just because the
            # cooldown below hasn't elapsed yet: without this, gating the
            # proximity check itself on the cooldown could let the
            # traveler move past a clustered pin entirely during the wait,
            # with no later frame ever close enough to catch it.
            for popup in active_popups:
                if popup["index"] == 0 or (
                    stop_popup and popup["index"] == stop_popup["index"]
                ):
                    continue
                # Identity check, not `in` (which is value-equality on
                # dicts) — these dicts keep mutating in place as the loop
                # runs (e.g. "triggered" itself), so an equality-based
                # membership test isn't reliable for "is this the same
                # popup already queued".
                if not popup["data"]["triggered"] and not any(
                    p is popup for p in pending_popups
                ):
                    # Raw pixel distance alone isn't enough to mean "the
                    # traveler has arrived" — a route that loops or
                    # doubles back (a real street layout near a cluster
                    # of stops) can swing physically close to a pin long
                    # before actually reaching it in the path's own
                    # sequence, popping that waypoint's card up while the
                    # traveler is really just passing through on an
                    # earlier, unrelated leg. `expected_frame` (set in
                    # overview.py) is this popup's own nearest-point
                    # position along the animated path — requiring the
                    # traveler to have actually reached near that point
                    # in time (not just in space) before it can trigger
                    # rules out that false-early case. A small tolerance
                    # keeps it from being stricter than the spatial check
                    # itself needs.
                    expected_frame = popup.get("expected_frame")
                    trigger_tolerance_frames = int(fps * 1.0)
                    if (
                        expected_frame is not None
                        and current_frame < expected_frame - trigger_tolerance_frames
                    ):
                        continue
                    if RouteGeometryProcessor.point_to_segment_distance(
                        popup["x"], popup["y"], px, py, cx, cy
                    ) < (
                        self.graphics.marker_radius
                        + self.trigger_radius_padding["overview"]
                    ):
                        pending_popups.append(popup)
                        # Mark the pin itself as reached right away, on the
                        # same frame the traveler actually gets there —
                        # "triggered" below (which the pin-drawing loops
                        # used to gate on instead) only flips once this
                        # popup's card actually clears the min-trigger-gap
                        # cooldown, which for a cluster of nearby waypoints
                        # can be a couple of seconds after the real arrival.
                        # Gating the pin on "triggered" made it (and the
                        # popup card fading in beside it) visibly pop in
                        # late, seconds after the traveler had already
                        # passed the spot on screen.
                        popup["data"]["arrived"] = True

            # A fixed cooldown between triggers is what a single popup
            # needs to be readable before the next one bumps it — but
            # applied unconditionally to a real backlog (several
            # waypoints queued at once, see the proximity loop above), it
            # became the bottleneck itself: dequeuing one every fixed
            # min_trigger_gap_frames could take longer than the
            # remaining animation had frames left for, so some queued
            # waypoints never got their turn to even be triggered before
            # the video ended. Shrinks (down to a floor) the more that's
            # backed up, so a dense cluster drains fast enough that every
            # waypoint the traveler actually reached gets shown.
            effective_gap_frames = min_trigger_gap_frames
            if len(pending_popups) > 1:
                effective_gap_frames = max(
                    int(fps * 0.4), min_trigger_gap_frames // len(pending_popups)
                )

            triggered_popup = None
            if pending_popups and current_frame - last_trigger_frame >= effective_gap_frames:
                triggered_popup = pending_popups.pop(0)
                triggered_popup["data"]["triggered"] = True
                last_trigger_frame = current_frame

            # [NOTE] [Animation] "Point to point" snapshot for hide_route_on_popup — every
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
                for wp in active_popups:
                    if wp["data"].get("arrived") or wp["index"] == 0:
                        self._draw_pin(frame_no_route, wp, len(points))

            if not is_video:
                # Every waypoint is shown once up front on the intro frame
                # (a preview of the whole route), but from here on a pin
                # only reappears once the traveler actually reaches it —
                # not-yet-visited stops stay hidden instead of cluttering
                # the map with numbers for places not reached yet.
                for wp in active_popups:
                    if wp["data"].get("arrived") or wp["index"] == 0:
                        self._draw_pin(frame, wp, len(points))

            # [NOTE] [Animation] Only the very last iteration's pre-popup frame is ever read
            # (see the recap's use of it, below) — smooth_path's length is
            # fixed and known up front (no early-exit branch in this loop),
            # so skip the per-frame copy everywhere else instead of paying
            # for a full-resolution frame copy on every single frame of
            # the animation.
            if stop_popup and current_frame == len(smooth_path) - 1:
                pre_popup_frame = frame.copy()
            frame, baked_popups = self._composite_baked_popups(
                frame, baked_popups, w, h, route_obstacle_arr,
                active_popups=active_popups, total_points=len(points),
            )

            if frame_no_route is None:
                frame_no_route = frame

            if triggered_popup:
                # Everything up to (and including) this point becomes part
                # of an "earlier leg" for the NEXT popup's hide effect.
                last_leg_boundary = len(path_history) - 1

                arrival_count += 1
                place_label = triggered_popup.get("label") or f"waypoint_{triggered_popup['index']}"
                tracker.show_item(
                    arrival_count,
                    f"Rendering overview video {arrival_count}/{total_stops}: arriving at '{place_label}'",
                )

                # Anchored beside this waypoint's own pin with a leader line
                # back to it (see render_popup_box's non-HUD-corner branch),
                # computed once and kept on the popup itself so the arrival
                # pause, the frozen hold, and the lingering baked-popup HUD
                # (below) all reuse the identical spot instead of jumping
                # around mid-display. A fixed screen corner (the old
                # pick_hud_corner behavior) looked fine whenever it happened
                # to land near the pin, but read as disconnected/"floating
                # over there" for a stop on the opposite side of the frame —
                # this ties every triggered popup, flow-through or frozen,
                # back to its own pin the same way.
                self._layout_beside_popups(
                    [{"popup": triggered_popup, "frames_left": 1}], w, h,
                    route_obstacles=route_obstacle_arr,
                )
                triggered_popup["hud_corner"] = None
                triggered_popup["draw_leader_line"] = True

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

                # [NOTE] [Animation] Fullscreen popups are an inherent full-screen takeover —
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
                    # [NOTE] [Animation] Flow-through: the traveler keeps moving — no held
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
                    # pending_popups here is whatever's LEFT after this one
                    # was just popped off the front — i.e. how many other
                    # already-triggered popups are still queued behind it,
                    # each needing its own turn at the trigger cooldown
                    # before it can even start waiting for a display slot.
                    new_bp = self._make_baked_popup(
                        triggered_popup, display_seconds, fps,
                        queue_depth=len(pending_popups),
                    )
                    baked_popups.append(new_bp)
                    frame = popup_base_frame
                    if not is_video:
                        smoothed_angle = self._smoothed_heading(
                            smoothed_angle, cx, cy, prev_cx, prev_cy
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
                        # Slide-up entrance, same as every later frame
                        # _composite_baked_popups draws this popup for —
                        # see _popup_slide_offset_y.
                        if hud_new.get("beside_box"):
                            bx, by = hud_new["beside_box"]
                            hud_new["beside_box"] = (
                                bx, int(by + self._popup_slide_offset_y(new_bp))
                            )
                        # Line, then pin, then card — the pin's already
                        # baked into `frame` (see the comment above), so
                        # without redrawing it here on top of the line,
                        # the line (drawn as part of a combined call) would
                        # land right over it.
                        frame = self.graphics.render_popup_box(
                            frame, hud_new, alpha=self._popup_fade_alpha(new_bp),
                            line_only=True,
                        )
                        self._draw_pin(frame, triggered_popup, len(points))
                        frame = self.graphics.render_popup_box(
                            frame, hud_new, alpha=self._popup_fade_alpha(new_bp),
                            skip_line=True,
                        )
                        # Drawn LAST (on top of the pin/line/card) — the
                        # traveler is right at this pin's position the
                        # instant it triggers, so drawing the icon earlier
                        # left it hidden behind the pin redraw above.
                        self.graphics.draw_transport_icon(
                            frame, cx, cy, current_frame, smoothed_angle, mode=current_mode
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
                    # Line, then pin, then card — pause_frame's own pin(s)
                    # are already baked in (see popup_base_frame above), so
                    # without redrawing triggered_popup's pin on top of the
                    # line here, the line would land right over it.
                    pause_frame = self.graphics.render_popup_box(
                        pause_frame, triggered_popup, line_only=True
                    )
                    self._draw_pin(pause_frame, triggered_popup, len(points))
                    pause_frame = self.graphics.render_popup_box(
                        pause_frame, triggered_popup, skip_line=True
                    )
                    # Drawn LAST (on top of the pin/line/card) — same
                    # reasoning as the trigger-moment frame above.
                    self.graphics.draw_transport_icon(
                        pause_frame, cx, cy, current_frame, smoothed_angle, mode=current_mode
                    )
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
                    base_beside_box = hud_triggered.get("beside_box")
                    for i in range(total_hold_frames):
                        alpha = min(1.0, (i + 1) / fade_in_frames)
                        # Same slide-up entrance as every other popup
                        # appearance (see _popup_slide_offset_y) — reuses
                        # that same helper via a throwaway bp-shaped dict
                        # matching this loop's own (i, fade_in_frames)
                        # progress, rather than re-deriving the easing
                        # curve inline.
                        if base_beside_box:
                            bx, by = base_beside_box
                            slide = self._popup_slide_offset_y(
                                {
                                    "total_frames": total_hold_frames,
                                    "frames_left": total_hold_frames - i,
                                    "fade_frames": fade_in_frames,
                                }
                            )
                            hud_triggered["beside_box"] = (bx, int(by + slide))
                        # Line, then pin, then card — same reasoning as the
                        # post-arrival pause above: popup_base_frame's own
                        # pin(s) are already baked in, so the line must be
                        # drawn first and the pin redrawn on top of it.
                        temp_frame = self.graphics.render_popup_box(
                            popup_base_frame, hud_triggered, alpha=alpha, line_only=True
                        )
                        self._draw_pin(temp_frame, triggered_popup, len(points))
                        temp_frame = self.graphics.render_popup_box(
                            temp_frame, hud_triggered, alpha=alpha, skip_line=True
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
