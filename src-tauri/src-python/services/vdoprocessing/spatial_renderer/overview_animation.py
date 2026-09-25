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
from .base import logger

# Animation-loop tuning constants (magic numbers pulled out of the loop body
# below so their purpose has a name; not read from self.config/tuning).
_MIN_TRIGGER_GAP_FLOOR_SECONDS = 0.15  # floor effective_gap_frames shrinks to for a deep backlog
_DEFAULT_FREEZE_SECONDS = 4.0  # fallback display duration when a popup sets no freeze_seconds


class _OverviewAnimationMixin:
    def _play_stopby_batch(
        self,
        video: VideoExporter,
        base_frame: np.ndarray,
        host_popup: Dict,
        host_hud: Dict,
        stopby_group: List[Dict],
        w: int,
        h: int,
        fps: int,
        total_points: int,
        route_obstacles: Optional[np.ndarray] = None,
        draw_host_card: bool = True,
    ) -> np.ndarray:
        """Plays every unconnected stop-by attached to `host_popup` over
        the frame held at that stop, one card at a time in route order,
        each for tuning.STOPBY_BATCH_SECONDS. Returns the last frame
        written.

        These landmarks are places the route only passes NEAR — the
        traveler visibly never goes to them, so a card popping where each
        one sits read as the map claiming a visit that never happened.
        Shown here instead: the traveler stops at the previous normal
        waypoint, that stop's own card settles, and then the landmarks
        behind it appear in turn beside their own pins, with a leader line
        back to each. See _attach_stopby_groups for which stop-by belongs
        to which host, and why a CONNECTED one is never in this group.

        The host's own line, pin and card are composited into the plate
        once, at full opacity (`draw_host_card=False` for a host that just
        finished a FULLSCREEN photo transition instead — it never had a
        small map card of its own to begin with, only the pin), rather
        than re-rendered per frame: the frame is frozen for the whole
        batch, so the only thing changing is whichever stop-by card is
        currently fading in or out on top of it. The host's card REUSES
        the spot it already settled into during the arrival hold
        (`host_popup["beside_box"]`) rather than being laid out fresh here
        — recomputing independently made the card visibly jump to a new
        spot the instant the batch started, right after it had just
        settled from the arrival trigger a moment earlier. Only falls
        back to a fresh layout when there's no existing spot to reuse
        (e.g. this host never got a "beside" box of its own — the
        FULLSCREEN case, though that skips this branch entirely via
        draw_host_card=False). Reserved either way, so a landmark's card
        can never land on top of the stop it belongs to."""
        if not stopby_group:
            return base_frame

        plate = base_frame
        reserved = []
        # Every landmark's own reserved box below (after it's shown) needs
        # this regardless of whether the host itself has a card — computed
        # unconditionally so draw_host_card=False (the start pin, or a
        # host that just finished a FULLSCREEN transition) doesn't leave
        # it undefined.
        card_w, card_h = self.graphics.beside_card_footprint()
        if draw_host_card:
            existing_box = host_popup.get("beside_box")
            if existing_box:
                host_hud["beside_box"] = existing_box
            else:
                self._layout_recap_popups(
                    [{"popup": host_hud, "frames_left": 1}], w, h,
                    route_obstacles=route_obstacles,
                )
            plate = self.graphics.render_popup_box(
                plate, host_hud, alpha=1.0, line_only=True
            )
            self._draw_pin(plate, host_popup, total_points)
            plate = self.graphics.render_popup_box(
                plate, host_hud, alpha=1.0, skip_line=True
            )
            host_box = host_hud.get("beside_box")
            if host_box:
                reserved.append(
                    (host_box[0], host_box[1], host_box[0] + card_w, host_box[1] + card_h)
                )
        else:
            self._draw_pin(plate, host_popup, total_points)

        last_frame = plate
        # Pins of the stop-bys already shown in this batch. They stay on
        # the map for the rest of it (they've been "arrived" now), and are
        # redrawn ON TOP of each later card's leader line — same
        # line-then-pins-then-card ordering every other multi-card frame
        # in this renderer uses, so a line crossing an earlier landmark's
        # pin never paints over it.
        shown: List[Dict] = []
        for stopby in stopby_group:
            stopby["data"]["arrived"] = True
            stopby["data"]["triggered"] = True

            hud = stopby.copy()
            hud["hud_corner"] = None
            hud["draw_leader_line"] = True
            self._layout_recap_popups(
                [{"popup": hud, "frames_left": 1}], w, h,
                reserved_boxes=reserved, route_obstacles=route_obstacles,
            )
            base_box = hud.get("beside_box")
            if not base_box:
                # Nowhere free to put this card on this frame. Its pin is
                # still shown (it HAS been reached, as far as the map is
                # concerned) — better a landmark with no card than a card
                # dropped on top of the stop it belongs to.
                self._draw_pin(plate, stopby, total_points)
                shown.append(stopby)
                continue

            bp = self._make_baked_popup(stopby, tuning.STOPBY_BATCH_SECONDS, fps)
            total_frames = bp["total_frames"]
            for i in range(total_frames):
                # Drives _popup_fade_alpha/_popup_slide_offset_y's shared
                # envelope straight off this loop's own progress, so the
                # card fades and slides in and back out exactly the way
                # every other popup in the video does.
                bp["frames_left"] = total_frames - i - 1
                alpha = self._popup_fade_alpha(bp)
                bx, by = base_box
                hud["beside_box"] = (bx, int(by + self._popup_slide_offset_y(bp)))

                frame = self.graphics.render_popup_box(
                    plate, hud, alpha=alpha, line_only=True
                )
                for already in shown:
                    self._draw_pin(frame, already, total_points)
                self._draw_pin(frame, stopby, total_points)
                frame = self.graphics.render_popup_box(
                    frame, hud, alpha=alpha, skip_line=True
                )
                video.write(frame)
                last_frame = frame

            # Bake this landmark's pin into the plate so it stays put for
            # the rest of the batch without being re-drawn from scratch.
            self._draw_pin(plate, stopby, total_points)
            shown.append(stopby)
            reserved.append(
                (base_box[0], base_box[1], base_box[0] + card_w, base_box[1] + card_h)
            )

        return last_frame

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
        # (x, y) of the most recently triggered popup's own pin — lets the
        # gap check below tell "these two waypoints are genuinely close
        # together on the map" apart from "these two just happen to be
        # queued back to back" (see the cluster-gap override further
        # down).
        last_triggered_pin: Optional[Tuple[float, float]] = None
        pending_popups: List[Dict] = []

        # Real (non-stop-by) waypoints must pop up STRICTLY in route order —
        # expected_frame/proximity alone (see the loop below) can still let
        # a later waypoint's pin satisfy both checks while the traveler is
        # only really passing near it on an earlier, unrelated stretch of a
        # route that loops or clusters several stops close together (e.g.
        # arriving at #2 while #3/#4 sit just a few pixels away) — popping
        # #3/#4 before the traveler has actually walked the legs to reach
        # them. `sequential_popups` (in the same route-position order
        # active_popups already is) plus `seq_ptr` gate a real waypoint's
        # eligibility on every waypoint ahead of it in sequence having
        # already arrived first.
        #
        # Every stop-by (connected or not) is now grouped behind the
        # nearest preceding REAL waypoint and played as part of ITS batch
        # — see _attach_stopby_groups — so a HOSTED stop-by (stopby_host
        # is not None) never reaches this loop at all; it's excluded here
        # outright (its own "stopby_host is not None: continue" below),
        # since _play_stopby_batch triggers it directly instead, as one
        # continuous stop that doesn't resume the traveling animation
        # until the run of stop-bys ends at the next real waypoint. Only
        # a stop-by with no preceding real waypoint at all (nothing to
        # host it — the hostless fallback case) still reaches this loop,
        # keeping the old pop-on-proximity behaviour.
        #
        # Leaving a hosted stop-by in `sequential_popups` used to let
        # seq_ptr get assigned to it — and since the proximity loop never
        # checks a hosted stop-by against sequential_popups[seq_ptr]
        # (skipped outright, above), seq_ptr could never advance past it,
        # permanently blocking every real waypoint later in route order
        # from ever triggering (and so never drawing its pin) for the
        # rest of the video.
        sequential_popups = [
            ap for ap in active_popups
            if ap["index"] != 0
            and (not stop_popup or ap["index"] != stop_popup["index"])
            and ap.get("stopby_host") is None
            and not self._is_loose_stopby(ap)
        ]
        seq_ptr = 0

        # The start pin itself never "arrives" through the trigger loop
        # below (index 0 is excluded throughout, same as every other
        # place in this file) — so any stop-by batched under it (see
        # _attach_stopby_groups) is played here instead, once, right
        # before the traveler sets off. Same "stop, then show its
        # landmarks in turn" beat every other host gets via
        # _play_stopby_batch, just anchored to frame zero rather than a
        # mid-route trigger. draw_host_card=False: the start pin has no
        # "arrival card" of its own to show here (it hasn't gone anywhere
        # yet) — only its pin, which is already part of every frame from
        # the very first one.
        start_popup = active_popups[0] if active_popups else None
        if start_popup and start_popup.get("stopby_group"):
            start_frame = current_bg.copy()
            self._draw_pin(start_frame, start_popup, len(points))
            self.last_frame = self._play_stopby_batch(
                video, start_frame, start_popup, start_popup.copy(),
                start_popup["stopby_group"], w, h, fps, len(points),
                route_obstacles=route_obstacle_arr, draw_host_card=False,
            )

        for current_frame, path_point in enumerate(smooth_path):
            if is_video:
                ret, vid_frame = cap.read()
                if ret:
                    if vid_frame.shape[0] != h or vid_frame.shape[1] != w:
                        vid_frame = cv2.resize(vid_frame, (w, h))
                    current_bg = vid_frame

            frame = current_bg.copy()

            path_history.append((int(path_point[0]), int(path_point[1])))

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
                # A stop-by belonging to a host waypoint's batch (connected
                # or not) never triggers on its own — its card plays during
                # that host's one continuous stop instead (see
                # _play_stopby_batch). Without this it would ALSO pop here
                # on proximity, showing the same landmark twice.
                if popup.get("stopby_host") is not None:
                    continue
                # Only a HOSTLESS unconnected stop-by still behaves the old
                # way: exempt from the sequence gate below, and from having
                # to be near the traveler at all.
                is_stopby = self._is_loose_stopby(popup)
                # A real waypoint — and a connected stop-by, which is one
                # in all but appearance — only becomes eligible once every
                # waypoint ahead of it in route sequence has already
                # arrived; see sequential_popups/seq_ptr's own comment
                # above.
                if not is_stopby and (
                    seq_ptr >= len(sequential_popups)
                    or popup is not sequential_popups[seq_ptr]
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
                    # (see tuning.OVERVIEW_POPUP_TRIGGER_TOLERANCE_SECONDS)
                    # keeps it from being stricter than the spatial check
                    # itself needs — just enough to absorb expected_frame's
                    # own estimation jitter, not enough to visibly show a
                    # popup before the traveler has actually gotten there.
                    expected_frame = popup.get("expected_frame")
                    trigger_tolerance_frames = int(
                        fps * tuning.OVERVIEW_POPUP_TRIGGER_TOLERANCE_SECONDS
                    )
                    if (
                        expected_frame is not None
                        and current_frame < expected_frame - trigger_tolerance_frames
                    ):
                        continue
                    # A stop-by can legitimately sit off the drawn route
                    # entirely (a viewpoint a short walk from the road, a
                    # landmark the route just passes near rather than
                    # through) — requiring the traveler's on-screen dot to
                    # actually come within the marker's trigger radius, the
                    # same test real waypoints need, meant one placed just
                    # outside that radius would never trigger at all, no
                    # matter how long the animation ran. Time (expected_frame,
                    # already checked above) is enough on its own for a
                    # stop-by; only a real waypoint still needs the
                    # traveler to actually be near it on screen.
                    near_enough = is_stopby or (
                        RouteGeometryProcessor.point_to_segment_distance(
                            popup["x"], popup["y"], px, py, cx, cy
                        )
                        < (
                            self.graphics.marker_radius
                            + self.trigger_radius_padding["overview"]
                        )
                    )
                    if near_enough:
                        pending_popups.append(popup)
                        if not is_stopby:
                            # This was sequential_popups[seq_ptr] (the gate
                            # above only let it through if so) — advance so
                            # the NEXT real waypoint in sequence becomes
                            # eligible for its own proximity check.
                            seq_ptr += 1
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
                    int(fps * _MIN_TRIGGER_GAP_FLOOR_SECONDS),
                    min_trigger_gap_frames // len(pending_popups),
                )

            triggered_popup = None
            if pending_popups and current_frame - last_trigger_frame >= effective_gap_frames:
                triggered_popup = pending_popups.pop(0)
                triggered_popup["data"]["triggered"] = True
                last_trigger_frame = current_frame
                if triggered_popup.get("cue_frame") is not None:
                    logger.info(
                        "Overview stop #%s reached at %.1fs (its cue: %.1fs).",
                        triggered_popup.get("order"), video.frames_written / fps,
                        triggered_popup["cue_frame"] / fps,
                    )
                # border_color was set once in render_overview's setup,
                # before any waypoint had "arrived" — for a plain numbered
                # pin that made it permanently the pre-arrival default
                # marker color (_pin_color returns None until "arrived" is
                # set), even once this pin's own dot has since turned
                # arrived_marker_color above. Recompute fresh now that
                # "arrived" is true (set on the proximity loop above) so
                # the card's border actually matches its own pin's current
                # color, same as waypoints.py's per-leg video already does.
                _, fresh_border_color, _ = self._pin_label_and_color(
                    triggered_popup, len(points)
                )
                triggered_popup["border_color"] = (
                    fresh_border_color or self.graphics.marker_color
                )

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
            # Kept for popup_base_frame below (not mutated by the call —
            # render_popup_box always copies its input frame rather than
            # drawing in place): the clean plate BEFORE any currently-
            # flowing card is composited onto it. Without this, a new
            # waypoint arriving while an EARLIER, still-fading flow-through
            # card (e.g. a connected stop-by's) is on screen would bake
            # that stale card permanently into popup_base_frame — which
            # then gets held for the whole freeze/pause and, for a host
            # with a stop-by batch, the whole batch too — showing two
            # unrelated waypoints' cards on screen together for seconds.
            frame_before_popups = frame
            # Once every real waypoint (and every stop-by host) has already
            # been QUEUED (seq_ptr advances on proximity — see the loop
            # above — which can be a few frames before that last waypoint's
            # own cooldown-gated trigger below), nothing is left ahead but
            # the final destination itself — the "Return" stretch, which
            # should show just the line, the pins and the "... へ" banner —
            # no popup card, and no fade transition either (an instant cut
            # is exactly what was asked for here, not a graceful wrap-up).
            # `triggered_popup is None` guards the one frame the last
            # waypoint (or its stop-by host) itself triggers on, so its own
            # arrival still plays out normally; every OTHER card's own
            # POPUP_MIN_DISPLAY_SECONDS is no longer at risk from this cut
            # the way it used to be — each waypoint's own leg_display_seconds
            # (see overview.py) now already finishes before the NEXT one's
            # "まもなく" banner even appears, which is well before seq_ptr
            # can read "done" here.
            if triggered_popup is None and seq_ptr >= len(sequential_popups):
                baked_popups = []
            frame, baked_popups = self._composite_baked_popups(
                frame, baked_popups, w, h, route_obstacle_arr,
                active_popups=active_popups, total_points=len(points), fps=fps,
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
                # Every card already on screen is reserved here: this
                # lays out ONE popup, so without them its `placed` list
                # would be empty and it could be dropped straight on top
                # of a still-visible neighbour (see _active_card_boxes)
                # — and the lock window would then hold both there.
                self._layout_recap_popups(
                    [{"popup": triggered_popup, "frames_left": 1}], w, h,
                    route_obstacles=route_obstacle_arr,
                    reserved_boxes=self._active_card_boxes(
                        baked_popups, exclude=triggered_popup
                    ),
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
                    popup_base_frame = (
                        frame_no_route if self.hide_route_on_popup
                        else frame_before_popups
                    )

                # [NOTE] [Animation] Fullscreen popups are an inherent full-screen takeover —
                # they always freeze regardless of the waypoint's
                # freeze_frame setting, since "flow through" wouldn't mean
                # anything for a shot that covers the whole frame. Every
                # other waypoint now flows through by default — the
                # traveler continues moving past each stop all the way to
                # the end; a waypoint only freezes if it opts in with
                # "freeze_frame": true in job_config.json.
                is_fullscreen = False  # the overview always shows the small pip card, whatever image_display says
                # A waypoint hosting unconnected stop-bys always freezes,
                # whatever the project asked for: their cards are played
                # over its held frame (see _play_stopby_batch), and
                # "flow through" leaves nothing to play them over — the
                # traveler is meant to stop here first, then the landmarks
                # behind this stop appear in order.
                stopby_group = triggered_popup.get("stopby_group") or []
                freeze_frame_on = (
                    triggered_popup["data"].get("freeze_frame", False)
                    or is_fullscreen
                    or bool(stopby_group)
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
                        or triggered_popup["data"].get("freeze_seconds", _DEFAULT_FREEZE_SECONDS)
                    )
                    # pending_popups here is whatever's LEFT after this one
                    # was just popped off the front — i.e. how many other
                    # already-triggered popups are still queued behind it,
                    # each needing its own turn at the trigger cooldown
                    # before it can even start waiting for a display slot.
                    # An EARLIER waypoint's own flow-through card can still
                    # be mid-display right when this new one triggers —
                    # frames_left only counts down while a card is
                    # actually drawn (see _make_baked_popup's own
                    # docstring on why: so one stuck waiting for a
                    # concurrency slot isn't unfairly cut short), so a
                    # card that got a late start (behind others) could
                    # otherwise run its full nominal duration long after
                    # the traveler has clearly moved on to this next
                    # stop — reported as an earlier waypoint's card still
                    # showing well past when it should already be gone.
                    # Force every OTHER still-active, not-yet-fading
                    # flow-through card straight into its own fade-out the
                    # moment a later one arrives, instead of letting it
                    # run out its original clock — but never before it's
                    # had at least POPUP_MIN_DISPLAY_SECONDS on screen.
                    # Without that floor, a card whose trigger frame lands
                    # right before the NEXT waypoint's own trigger (e.g.
                    # two stops close together) could get wrapped up only
                    # a frame or two after it first appeared — elapsed
                    # (total_frames - frames_left) is near zero, so
                    # wrap_up_frames alone let it fade out almost as soon
                    # as it faded in, reported as the card "blinking" —
                    # gone again the instant the next waypoint arrived.
                    # This floor is a hard, unconditional
                    # POPUP_MIN_DISPLAY_SECONDS — a previous version of this
                    # code shrank it under a deep concurrency backlog (many
                    # waypoints clustered together, more than
                    # MAX_CONCURRENT_FLOW_POPUPS competing for a display
                    # slot at once) to stop a late card from waiting so long
                    # for a free slot that it ended up shown well into the
                    # FOLLOWING leg. That traded away the one guarantee this
                    # whole block exists for — reported directly as a popup
                    # sometimes not staying up for a full 2 seconds. The
                    # "still showing late into the next leg" case is now
                    # instead handled at the point the animation actually
                    # enters that next leg (see the seq_ptr-based wrap-up
                    # right before _composite_baked_popups above), which
                    # itself also respects this same floor — so a dense
                    # cluster may still take a few real seconds to fully
                    # drain, but no individual card's guaranteed 2 seconds
                    # is ever cut short to make that happen faster.
                    new_order = triggered_popup.get("order", 0)
                    min_display_frames = max(
                        1, int(tuning.POPUP_MIN_DISPLAY_SECONDS * fps)
                    )
                    for bp in baked_popups:
                        if bp["popup"]["data"].get("freeze_frame", False):
                            continue
                        if bp["popup"].get("order", 0) >= new_order:
                            continue
                        wrap_up_frames = bp.get("fade_frames") or max(
                            1, int(self._POPUP_FADE_SECONDS * fps)
                        )
                        elapsed = bp.get("total_frames", bp["frames_left"]) - bp["frames_left"]
                        remaining_for_min_display = max(0, min_display_frames - elapsed)
                        target_frames_left = max(wrap_up_frames, remaining_for_min_display)
                        bp["frames_left"] = min(bp["frames_left"], target_frames_left)

                    new_bp = self._make_baked_popup(
                        triggered_popup, display_seconds, fps,
                        queue_depth=len(pending_popups),
                    )
                    baked_popups.append(new_bp)
                    frame = popup_base_frame
                    # popup_base_frame is deliberately a clean plate with no
                    # cards baked in (see frame_before_popups' own comment
                    # above) — needed so a FREEZE hold reusing this same
                    # plate for many frames never bakes in a stale card.
                    # But this flow-through branch only ever writes ONE
                    # frame from it, right here, before the loop resumes
                    # normal per-frame compositing next iteration — without
                    # redrawing every OTHER still-active card (e.g. an
                    # earlier waypoint's own card, still lingering/fading)
                    # on this one frame too, it vanished for exactly this
                    # one frame and popped back on the next, reported as
                    # the earlier card visibly "blinking" the instant a new
                    # waypoint arrives.
                    for other_bp in baked_popups:
                        if other_bp is new_bp:
                            continue
                        other_popup = other_bp["popup"]
                        if not other_popup.get("beside_box"):
                            continue
                        other_hud = other_popup.copy()
                        other_hud["hud_corner"] = None
                        other_hud["draw_leader_line"] = True
                        other_alpha = self._popup_fade_alpha(other_bp)
                        frame = self.graphics.render_popup_box(
                            frame, other_hud, alpha=other_alpha, line_only=True
                        )
                        self._draw_pin(frame, other_popup, len(points))
                        frame = self.graphics.render_popup_box(
                            frame, other_hud, alpha=other_alpha, skip_line=True
                        )
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
                        self._layout_recap_popups(
                            [new_bp], w, h, route_obstacles=route_obstacle_arr,
                            reserved_boxes=self._active_card_boxes(
                                baked_popups, exclude=triggered_popup
                            ),
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
                    # This IS the arrival frame — always "まもなく" (never
                    # the "へ"/en-route phrasing), naming the waypoint that
                    # just triggered rather than sequential_popups[seq_ptr]
                    # (already advanced past it by this point in the loop).
                    frame = self.graphics.render_top_banner(
                        frame, f"まもなく {triggered_popup.get('label') or ''}"
                    )
                    self.last_frame = frame
                    video.write(frame)
                    prev_cx, prev_cy = cx, cy
                    continue

                # Hold on the traveler having just reached the pin for a
                # beat before the fullscreen/pip transition kicks in.
                # Pin only here, no card yet — the hold loop right after
                # this is what actually fades the card in from scratch
                # (alpha 0 -> 1 over fade_in_frames). Drawing the card here
                # too, at flat alpha=1 with no fade of its own, used to
                # mean the card snapped fully opaque for this pause, then
                # the hold loop's very next frame immediately dropped it
                # back down near-invisible to restart its own fade-in —
                # a visible dip-then-recover that read as the same card
                # popping in twice in a row. One entrance (the hold loop's
                # own fade-in), not two.
                if not is_video and self.post_arrival_hold_seconds > 0:
                    pause_frame = popup_base_frame.copy()
                    smoothed_angle = self._smoothed_heading(
                        smoothed_angle, cx, cy, prev_cx, prev_cy
                    )
                    self._draw_pin(pause_frame, triggered_popup, len(points))
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
                        triggered_popup["data"].get("freeze_seconds", _DEFAULT_FREEZE_SECONDS)
                    )
                    # Kept as its own baked_popups entry so it lingers as a
                    # HUD overlay (with its own fade in/out) once the
                    # camera resumes moving — see _composite_baked_popups.
                    # NOT appended when a stopby_group follows (below): that
                    # batch already makes this host's card vanish the
                    # instant it starts (draw_host_card=False — see its own
                    # comment), and a run of landmark cards plays in its
                    # place. Letting it linger and reappear AFTER all of
                    # that, once the batch ends and the traveler is already
                    # moving on, reads as the map re-showing a photo the
                    # viewer just watched settle and disappear moments
                    # earlier — reported directly as a stray "already shown
                    # image" flash right after a stop-by pause. A host with
                    # no stopby_group never has this problem (its card never
                    # disappears early), so it still gets the graceful
                    # lingering fade-out.
                    lingering_bp = self._make_baked_popup(
                        triggered_popup, display_seconds, fps
                    )
                    if not stopby_group:
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

                    # lingering_bp's OWN fade-in already played out, frame
                    # by frame, in the hold loop above — but that loop
                    # writes its frames directly (video.write), never
                    # through _composite_baked_popups, so lingering_bp's
                    # own "frames_left" never actually counted down and is
                    # still sitting at its starting value. Left alone,
                    # the first time _composite_baked_popups DOES pick it
                    # up — once the main loop resumes below, or after a
                    # stop-by batch here finishes playing on top of this
                    # same held frame — it reads as frame zero of a card
                    # that's never been shown, and fades/slides itself in
                    # from scratch a second time: the same card visibly
                    # re-entering right after it already settled. Jumping
                    # straight to "just past its own fade-in" here is what
                    # the hold loop actually just finished showing, so the
                    # card reappears already settled and only has its
                    # fade-OUT left to play once it resumes as a lingering
                    # HUD overlay.
                    lingering_bp["frames_left"] = lingering_bp["fade_frames"]

                # Then the landmarks behind this stop, in route order — see
                # _play_stopby_batch. Outside the freeze/fullscreen split
                # above so a host whose own photo takes over the screen
                # still plays its batch afterwards, on the map it returns
                # to. Built from popup_base_frame rather than the hold's
                # last frame: that one already has the host's card
                # mid-slide-out (its own fade envelope), which would sit
                # frozen half-departed underneath the whole batch.
                # draw_host_card=False: this host's own card already had
                # its one appearance above (the pause + hold loop, or the
                # fullscreen takeover) — it's not redrawn/persisted here
                # too, so the batch is just the landmarks behind it, not
                # the host's card sitting there the whole time as well.
                # lingering_bp (set above) still fades it out gracefully
                # once the video resumes moving after the batch — that's
                # the same one appearance finishing, not a second one.
                if stopby_group:
                    hud_settled = triggered_popup.copy()
                    hud_settled["hud_corner"] = None
                    hud_settled["draw_leader_line"] = True
                    self.last_frame = self._play_stopby_batch(
                        video, popup_base_frame, triggered_popup, hud_settled,
                        stopby_group, w, h, fps, len(points),
                        route_obstacles=route_obstacle_arr,
                        draw_host_card=False,
                    )

            else:
                if not is_video:
                    smoothed_angle = self._smoothed_heading(
                        smoothed_angle, cx, cy, prev_cx, prev_cy
                    )
                    self.graphics.draw_transport_icon(
                        frame, cx, cy, current_frame, smoothed_angle, mode=current_mode
                    )

                # Dynamic "next stop" caption — the next real waypoint still
                # ahead in route order (sequential_popups[seq_ptr]), or the
                # final destination once every other real waypoint has
                # already arrived. "まもなく" once within
                # OVERVIEW_BANNER_NEAR_SECONDS of its own expected_frame
                # (the same estimated-arrival frame the trigger logic
                # above uses), "へ" (still en route) otherwise.
                banner_target = (
                    sequential_popups[seq_ptr] if seq_ptr < len(sequential_popups) else stop_popup
                )
                if banner_target:
                    label = banner_target.get("label") or ""
                    expected_frame = banner_target.get("expected_frame")
                    near = (
                        expected_frame is not None
                        and (expected_frame - current_frame) <= int(fps * tuning.OVERVIEW_BANNER_NEAR_SECONDS)
                    )
                    banner_text = f"まもなく {label}" if near else f"{label} へ"
                    frame = self.graphics.render_top_banner(frame, banner_text)

                self.last_frame = frame
                video.write(frame)

            prev_cx, prev_cy = cx, cy

        return pre_popup_frame
