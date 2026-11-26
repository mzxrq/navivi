"""The overview's frame-by-frame animation loop — split out of overview.py
(render_overview itself) so that file is left holding just the setup
(labels, path building, intro beat) and wrap-up (recap, summary, ending
highlight). The loop's per-frame steps are the `_walk_*` / `_arrive_*`
helpers below, passing their shared state through `_WalkState`."""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from services.mapfetcher.mapgeometry import RouteGeometryProcessor
from services.vdoprocessing.vdoexporter import VideoExporter
from services.logger.progress import tracker
from services import tuning
from .base import logger
from .overview_timing import warp_path

# Animation-loop tuning constants (not read from self.config/tuning).
_MIN_TRIGGER_GAP_FLOOR_SECONDS = 0.15  # floor effective_gap_frames shrinks to for a deep backlog
_DEFAULT_FREEZE_SECONDS = 4.0
# Longest the overview walker waits at a stop for the voice to reach its cue.
_MAX_CUE_WAIT_SECONDS = 20.0
_CARD_STAYS_SECONDS = 3600.0  # "until the end" for a card that stays (walk style)
# A walk re-timed to meet its cue runs at most this much slower / faster than planned.
_CATCH_UP_RANGE = (0.6, 2.5)  # matches overview_timing.MAX_WALK_SPEEDUP's raised cap
_MIN_RETIME_DELTA_FRAMES = 2  # a re-time (and a stretch worth re-timing) is at least this many frames
_PREVIEW_BADGE_MARGIN_PX = 24
_PREVIEW_BADGE_RISE_PX = 44  # the preview badge floats this far above its coordinate


class _NoticeWriter:
    """Passes frames to `video`, drawing the stop-by notice over them while
    it is active, so every write path (walk, holds, batches) shows it."""

    def __init__(self, video: VideoExporter, renderer):
        self._video = video
        self._renderer = renderer

    def __getattr__(self, name):
        return getattr(self._video, name)

    def write(self, frame: np.ndarray) -> None:
        frame = self._renderer._apply_hud(frame)
        self._video.write(self._renderer._apply_stopby_notice(frame))


@dataclass
class _Beat:
    """Where the walker is on one frame: path index, its dot, the dot one frame back, travel mode."""
    index: int
    cx: int
    cy: int
    px: int
    py: int
    mode: str


@dataclass
class _WalkClock:
    """The walk's own timeline. `wait` replays the current path frame that many
    more times (a cued stop's hold, its popup still fading in) so the picture
    stays in step with the voice. After a stop (its wait, card hold or
    stop-by cards) `catch_up_due` re-times the walk to the NEXT cued stop once,
    within _CATCH_UP_RANGE of its planned pace, so it never rushes or crawls
    (an unreachable cue just lands a little late/early)."""
    path: np.ndarray
    cum: Optional[np.ndarray]
    wait: int = 0
    catch_up_due: bool = False

    def frames(self):
        i = 0
        while i < len(self.path):
            yield i, self.path[i]
            while self.wait > 0:
                self.wait -= 1
                yield i, self.path[i]
            i += 1


@dataclass
class _WalkState:
    """Everything the animation loop carries from frame to frame."""
    video: _NoticeWriter
    current_bg: np.ndarray
    cap: object
    is_video: bool
    w: int
    h: int
    fps: int
    n_points: int
    smooth_path: np.ndarray
    cum: Optional[np.ndarray]
    total_dist: float
    mode_breakpoints: List[Tuple[float, str]]
    active_popups: List[Dict]
    stop_popup: Optional[Dict]
    route_obstacles: np.ndarray
    sequential_popups: List[Dict]
    smoothed_angle: float
    total_stops: int
    min_trigger_gap_frames: int
    last_trigger_frame: int
    baked_popups: List[Dict] = field(default_factory=list)
    path_history: List = field(default_factory=list)
    mode_history: List = field(default_factory=list)
    pending_popups: List[Dict] = field(default_factory=list)
    prev_cx: Optional[int] = None
    prev_cy: Optional[int] = None
    seq_ptr: int = 0
    # [NOTE] [Animation] path_history index of the most recently reached waypoint: the boundary
    # between "earlier, completed legs" (kept visible) and "the current leg" (hidden while its
    # arrival popup shows).
    last_leg_boundary: int = 0
    arrival_count: int = 0
    # [NOTE] [Animation] Last frame's pins + route with no popup card baked in, captured only on
    # the final iteration: self.last_frame can carry a card mid fade-out, which the recap would
    # bake into its background and then draw again on top (a ghosted double image).
    pre_popup_frame: Optional[np.ndarray] = None
    # Stays None if the walk has no frames at all (the card-hold tail checks it).
    frame_before_popups: Optional[np.ndarray] = None
    last_beat: Optional[_Beat] = None


def _retime_walk(
    clock: _WalkClock, index: int, active_popups: List[Dict], frames_written: int, fps: int,
) -> None:
    """Re-times the walk from `index` to the next cued stop so it arrives on
    its cue (within _CATCH_UP_RANGE); later stops' expected frames shift with it."""
    ahead = [
        ap for ap in active_popups
        if ap.get("cue_frame") is not None and ap.get("expected_frame") is not None
        and ap["expected_frame"] > index and not ap["data"].get("triggered")
    ]
    if not ahead:
        return
    nxt = min(ahead, key=lambda ap: ap["expected_frame"])
    end = int(nxt["expected_frame"])
    planned = end - index
    if planned < _MIN_RETIME_DELTA_FRAMES:
        return
    wanted = int(nxt["cue_frame"]) - frames_written
    lo, hi = _CATCH_UP_RANGE
    new_len = int(round(min(max(wanted, planned / hi), planned / lo)))
    if abs(new_len - planned) < _MIN_RETIME_DELTA_FRAMES:
        return
    path, cum = clock.path, clock.cum
    xs, ys = [0.0, float(new_len)], [0.0, float(planned)]
    seg, seg_cum = warp_path(
        path[index:end + 1], cum[index:end + 1] if cum is not None else None,
        xs, ys, out_len=new_len + 1,
    )
    clock.path = np.concatenate([path[:index], seg, path[end + 1:]])
    if cum is not None:
        clock.cum = np.concatenate([cum[:index], seg_cum, cum[end + 1:]])
    shift = new_len - planned
    for ap in active_popups:
        ef = ap.get("expected_frame")
        if ef is None or ef <= index:
            continue
        ap["expected_frame"] = (
            index + int(round((ef - index) * new_len / planned)) if ef <= end else ef + shift
        )
    logger.info(
        "Overview: walk to stop #%s re-timed %.1fs -> %.1fs to meet its cue.",
        nxt.get("order"), planned / fps, new_len / fps,
    )


class _OverviewAnimationMixin:
    def _apply_hud(self, frame: np.ndarray) -> np.ndarray:
        """Persistent overview HUD: the trip's name and per-mode times on the
        left, and on the right what is left of the route, the stop counter,
        the stop being walked to and a progress bar (once the walk has an
        actual position to measure progress from). Drawn through
        _NoticeWriter.write so every frame this loop writes gets it,
        regardless of which branch (walk, holds, batches) produced it —
        same reasoning as the stop-by notice it's drawn alongside."""
        total_km = getattr(self, "_hud_total_distance_km", None)
        total_s = getattr(self, "_hud_total_duration_seconds", None)
        frac = getattr(self, "_hud_progress_frac", None)
        live = {}
        if total_km is not None and total_s is not None and frac is not None:
            remaining = max(0.0, 1.0 - frac)
            live = {
                "remaining_km": total_km * remaining,
                "remaining_seconds": total_s * remaining,
                "progress": frac,
            }
        frame = self.graphics.render_overview_hud(
            frame,
            title=getattr(self, "_hud_title", None),
            mode_duration=getattr(self, "_hud_mode_duration", None),
            stops=getattr(self, "_hud_stops", None),
            next_stop=getattr(self, "_hud_next_stop", None),
            **live,
        )
        return self._apply_preview_badge(frame)

    def _apply_preview_badge(self, frame: np.ndarray) -> np.ndarray:
        """The upcoming (not yet arrived) waypoint's own pill badge — see
        _walk_one_frame, which sets self._preview_badge to it each frame (or
        None once nothing is left to preview). Placed directly above its own
        map coordinate with no leader line: it hasn't been reached yet, so
        there's no pin on screen to connect it to. Cleared instantly once
        that waypoint is itself triggered — its real full "pop up card" takes
        over from there, and only shrinks back to this same pill badge once
        it's been shown for a while (see _composite_baked_popups), at the
        very spot the end-of-video recap will keep it in."""
        popup = getattr(self, "_preview_badge", None)
        if popup is None:
            return frame
        h, w = frame.shape[:2]
        name_chars = len(str(popup.get("label") or ""))
        badge_w, badge_h = self.graphics.beside_card_footprint(
            is_pill_badge=True, pill_name_chars=name_chars
        )
        x, y = popup.get("pin_x", popup["x"]), popup.get("pin_y", popup["y"])
        margin = _PREVIEW_BADGE_MARGIN_PX
        box_x = int(max(margin, min(x - badge_w / 2, w - badge_w - margin)))
        box_y = int(max(margin, min(y - badge_h - _PREVIEW_BADGE_RISE_PX, h - badge_h - margin)))
        preview = popup.copy()
        preview["is_pill_badge"] = True
        preview["beside_box"] = (box_x, box_y)
        return self.graphics.render_popup_box(frame, preview, alpha=1.0, skip_line=True)

    def _start_stopby_notice(self, fps: int, seconds: float, kind: str = "stopby") -> None:
        """Shows the stop-by notice (or, kind "closed", the closed-place one) once per video, from the next frame."""
        shown = self.__dict__.setdefault("_notice_kinds_shown", set())
        if kind in shown:
            return
        shown.add(kind)
        if kind == "stopby":
            self._stopby_notice_shown = True
        fade = max(1, int(tuning.STOPBY_NOTICE_FADE_SECONDS * fps))
        min_total = math.ceil(tuning.STOPBY_NOTICE_MIN_READ_SECONDS * fps) + 2 * fade
        self._stopby_notice = {
            "i": 0,
            "total": max(min_total, int(seconds * fps)),
            "fade": fade,
            "kind": kind,
        }

    def _stopby_notice_reserved(self, w: int, h: int) -> List[Tuple[int, int, int, int]]:
        notice = getattr(self, "_stopby_notice", None)
        return [self.graphics.stopby_notice_box(w, h, notice.get("kind", "stopby"))] if notice else []

    def _apply_stopby_notice(self, frame: np.ndarray) -> np.ndarray:
        notice = getattr(self, "_stopby_notice", None)
        if not notice:
            return frame
        i, total, fade = notice["i"], notice["total"], notice["fade"]
        alpha = max(0.0, min(1.0, (i + 1) / fade, (total - i) / fade))
        notice["i"] += 1
        if notice["i"] >= total:
            self._stopby_notice = None
        return self.graphics.render_stopby_notice(
            frame, alpha=alpha, marker_color=self._STOPBY_PIN_COLOR, kind=notice.get("kind", "stopby"),
        )

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
        carried: Optional[List[Dict]] = None,
        animate_host: bool = False,
        total_display_seconds: Optional[float] = None,
    ) -> np.ndarray:
        """Plays every unconnected stop-by attached to `host_popup` over the
        frame held at that stop — ALL of them together (laid out and faded
        in/out as one simultaneous group), not one card at a time. The
        group's shared display lasts tuning.STOPBY_BATCH_SECONDS * (number
        shown), the total route_brief.stopby_holds's hold budget assumes.
        Returns the last frame written.

        These landmarks are places the route only passes NEAR, so a card
        popping where each one sits would claim a visit that never happened:
        the traveler stops at the previous normal waypoint, that stop's card
        settles, then every landmark behind it appears together beside its own
        pin with a leader line back to it (see _attach_stopby_groups).

        The host's line, pin and card are composited into the plate once, at
        full opacity (`draw_host_card=False` for a host that already showed
        its card elsewhere, leaving only its pin drawn here), because the
        frame is frozen for the whole batch. The host's card REUSES the spot
        it settled into during the arrival hold (`host_popup["beside_box"]`):
        a fresh layout made it visibly jump the instant the batch started.
        It is reserved either way, so no landmark card lands on its stop.

        `carried`: cards of the stops just passed, still inside their display
        time - drawn over the batch until they fade out (the list is updated
        in place), and kept clear of the landmarks' cards.

        `animate_host`: the host's card joins the simultaneous group instead
        of being composited separately (implies `draw_host_card=False`) - for
        a host that is ITSELF a stop-by: it pops together with the landmarks
        behind it. `total_display_seconds`, given, overrides the group's
        shared hold: the caller's own cue-extended hold, so the host's
        description and the batch share one timer."""
        if not stopby_group:
            return base_frame
        carried = carried if carried is not None else []

        for stopby in stopby_group:
            stopby["data"]["arrived"] = True
            stopby["data"]["triggered"] = True

        plate, reserved = self._batch_plate(
            base_frame, host_popup, host_hud, w, h, total_points,
            route_obstacles, draw_host_card, carried,
        )
        # [NOTE] [Pacing] Only the first STOPBY_BATCH_MAX_HELD get a held card (the narration never
        # names more); a longer group froze the video well past the voice. The rest still get
        # their pin baked into the plate, like a "no room for a card" landmark.
        held = stopby_group[: tuning.STOPBY_BATCH_MAX_HELD]
        overflow = stopby_group[tuning.STOPBY_BATCH_MAX_HELD:]
        for stopby in overflow:
            self._draw_pin(plate, stopby, total_points)

        # animate_host: the host joins the SAME laid-out group (not sliced by
        # STOPBY_BATCH_MAX_HELD, it's the actual stop) and holds as long as the batch.
        group = ([host_popup] if animate_host else []) + held
        huds = [(item, item.copy()) for item in group]
        for _, hud in huds:
            hud["hud_corner"] = None
            hud["draw_leader_line"] = True
        # Laid out TOGETHER in one pass so they all appear at once instead of
        # each sliding into whatever spot was free after the last settled.
        self._layout_recap_popups(
            [{"popup": hud, "frames_left": 1} for _, hud in huds], w, h,
            reserved_boxes=reserved, route_obstacles=route_obstacles,
        )

        placed = [(stopby, hud) for stopby, hud in huds if hud.get("beside_box")]
        no_room = [stopby for stopby, hud in huds if not hud.get("beside_box")]
        for stopby in no_room:
            # Better a landmark with a pin and no card than a card dropped on its own stop.
            self._draw_pin(plate, stopby, total_points)

        if not placed:
            self._start_stopby_notice(fps, tuning.STOPBY_NOTICE_SECONDS)
            return plate
        batch_seconds = (
            total_display_seconds if total_display_seconds is not None
            else tuning.STOPBY_BATCH_SECONDS * len(placed)
        )
        return self._play_batch_cards(
            video, plate, placed, carried, batch_seconds, w, h, route_obstacles, total_points, fps,
        )

    def _batch_plate(
        self, base_frame: np.ndarray, host_popup: Dict, host_hud: Dict, w: int, h: int,
        total_points: int, route_obstacles: Optional[np.ndarray], draw_host_card: bool,
        carried: List[Dict],
    ) -> Tuple[np.ndarray, List]:
        """The stop-by batch's frozen plate (host line/pin/card drawn in) and
        the boxes the landmark cards must keep off."""
        plate = base_frame
        reserved = []
        # The first stop-by of the video also explains what these round markers are
        # (bottom-left ribbon + card, see _start_stopby_notice); the cards are kept off it.
        if not getattr(self, "_stopby_notice_shown", False):
            reserved.append(self.graphics.stopby_notice_box(w, h))
        else:
            reserved.extend(self._stopby_notice_reserved(w, h))
        card_w, card_h = self.graphics.beside_card_footprint()
        reserved.extend(self._active_card_boxes(carried))
        if not draw_host_card:
            self._draw_pin(plate, host_popup, total_points)
            return plate, reserved
        existing_box = host_popup.get("beside_box")
        if existing_box:
            host_hud["beside_box"] = existing_box
        else:
            self._layout_recap_popups(
                [{"popup": host_hud, "frames_left": 1}], w, h, route_obstacles=route_obstacles,
            )
        plate = self.graphics.render_popup_box(plate, host_hud, alpha=1.0, line_only=True)
        self._draw_pin(plate, host_popup, total_points)
        plate = self.graphics.render_popup_box(plate, host_hud, alpha=1.0, skip_line=True)
        host_box = host_hud.get("beside_box")
        if host_box:
            reserved.append((host_box[0], host_box[1], host_box[0] + card_w, host_box[1] + card_h))
        return plate, reserved

    def _play_batch_cards(
        self, video, plate: np.ndarray, placed: List, carried: List[Dict], batch_seconds: float,
        w: int, h: int, route_obstacles: Optional[np.ndarray], total_points: int, fps: int,
    ) -> np.ndarray:
        """Fades the placed landmark cards in and back out TOGETHER over
        `batch_seconds`, then bakes their pins into `plate`; returns the last frame."""
        base_boxes = {id(hud): hud["beside_box"] for _, hud in placed}
        bp = self._make_baked_popup(
            placed[0][0], batch_seconds, fps, min_display_seconds=batch_seconds,
        )
        total_frames = bp["total_frames"]
        self._start_stopby_notice(fps, total_frames / fps)
        last_frame = plate
        for i in range(total_frames):
            # Drives the shared fade/slide envelope straight off this loop's progress.
            bp["frames_left"] = total_frames - i - 1
            alpha = self._popup_fade_alpha(bp)
            slide = self._popup_slide_offset_y(bp)

            frame = plate
            for _, hud in placed:
                bx, by = base_boxes[id(hud)]
                hud["beside_box"] = (bx, int(by + slide))
                frame = self.graphics.render_popup_box(frame, hud, alpha=alpha, line_only=True)
            for stopby, _ in placed:
                self._draw_pin(frame, stopby, total_points)
            for _, hud in placed:
                frame = self.graphics.render_popup_box(frame, hud, alpha=alpha, skip_line=True)
            frame = self._draw_carried(frame, carried, w, h, route_obstacles, total_points, fps)
            last_frame = frame
            video.write(frame)

        # Bake every landmark's pin into the plate so it stays put after the batch.
        for stopby, _ in placed:
            self._draw_pin(plate, stopby, total_points)
        return last_frame

    def _draw_carried(
        self, frame: np.ndarray, carried: List[Dict], w: int, h: int,
        route_obstacles: Optional[np.ndarray], total_points: int, fps: int,
    ) -> np.ndarray:
        """`frame` with the cards in `carried` drawn on it for one frame (each
        at its own place in its fade envelope, counting down); the ones done
        are dropped from `carried` in place."""
        if not carried:
            return frame
        frame, survivors = self._composite_baked_popups(
            frame, carried, w, h, route_obstacles, total_points=total_points, fps=fps,
        )
        carried[:] = survivors
        return frame

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
        # Waypoints placed close together can otherwise trigger back-to-back and pop the
        # current card out almost as soon as it appeared: this floor guarantees at least this
        # many frames between triggers, set far enough in the past not to block the first.
        min_trigger_gap_frames = int(fps * tuning.OVERVIEW_POPUP_MIN_TRIGGER_GAP_SECONDS)
        # [NOTE] [Animation] Real waypoints must pop up STRICTLY in route order: expected_frame +
        # proximity alone let a later pin satisfy both while the traveler is only passing near it
        # on a looping route. `sequential_popups` + `seq_ptr` gate each one on every waypoint
        # ahead of it having arrived. A HOSTED stop-by is excluded outright: _play_stopby_batch
        # triggers it, and leaving it here let seq_ptr stick on it forever, blocking every later
        # waypoint. Only a hostless loose stop-by still reaches the loop (pop-on-proximity).
        sequential_popups = [
            ap for ap in active_popups
            if ap["index"] != 0
            and (not stop_popup or ap["index"] != stop_popup["index"])
            and ap.get("stopby_host") is None
            and not self._is_loose_stopby(ap)
        ]
        s = _WalkState(
            video=_NoticeWriter(video, self), current_bg=current_bg, cap=cap, is_video=is_video,
            w=w, h=h, fps=fps, n_points=len(points), smooth_path=smooth_path, cum=cum_smooth_dist,
            total_dist=total_smooth_dist, mode_breakpoints=mode_breakpoints,
            active_popups=active_popups, stop_popup=stop_popup, route_obstacles=route_obstacle_arr,
            sequential_popups=sequential_popups, smoothed_angle=self._initial_heading(smooth_path),
            # excludes the start pin (index 0), which never arrives
            total_stops=max(1, len(active_popups) - 1),
            min_trigger_gap_frames=min_trigger_gap_frames,
            last_trigger_frame=-min_trigger_gap_frames,
        )
        tracker.begin_substeps(s.total_stops)
        self._play_start_batch(s)

        clock = _WalkClock(smooth_path, cum_smooth_dist)
        last_index = -1
        for current_frame, path_point in clock.frames():
            if current_frame != last_index:
                if clock.catch_up_due:
                    clock.catch_up_due = False
                    _retime_walk(clock, current_frame, active_popups, s.video.frames_written, fps)
                    path_point = clock.path[current_frame]
                s.smooth_path, s.cum = clock.path, clock.cum
                last_index = current_frame
            self._walk_one_frame(s, clock, current_frame, path_point)

        self._hold_final_cards(s)
        return s.pre_popup_frame

    def _play_start_batch(self, s: _WalkState) -> None:
        """Index 0 never "arrives" through the trigger loop, so a stop-by batch
        hosted by the start pin is played here, once, right before the walker
        sets off (draw_host_card=False: only its pin, already on every frame).
        `batch_display_seconds` (overview.py) holds until the batch's {goPreN}
        cue is spoken instead of the fixed per-card estimate."""
        start_popup = s.active_popups[0] if s.active_popups else None
        if not (start_popup and start_popup.get("stopby_group")):
            return
        start_frame = s.current_bg.copy()
        self._draw_pin(start_frame, start_popup, s.n_points)
        self.last_frame = self._play_stopby_batch(
            s.video, start_frame, start_popup, start_popup.copy(),
            start_popup["stopby_group"], s.w, s.h, s.fps, s.n_points,
            route_obstacles=s.route_obstacles, draw_host_card=False,
            total_display_seconds=start_popup.get("batch_display_seconds"),
        )

    def _walk_one_frame(
        self, s: _WalkState, clock: _WalkClock, current_frame: int, path_point,
    ) -> None:
        """One frame of the walk: move the dot, queue/trigger arrivals, draw
        pins and flowing cards, and write the frame (or, on an arrival, the
        whole hold it starts)."""
        if s.is_video:
            self._read_video_frame(s)
        frame = s.current_bg.copy()

        s.path_history.append((int(path_point[0]), int(path_point[1])))
        mode = self._track_mode(s, current_frame)
        if not s.is_video:
            self.graphics.draw_path(frame, s.path_history, s.mode_history)

        # [NOTE] [Animation] Detected BEFORE the pin/popup drawing so a waypoint's pin and card
        # appear on the very frame it's reached; detecting after left them invisible until the
        # next frame drew fresh.
        cx, cy = s.path_history[-1]
        px, py = s.path_history[-2] if len(s.path_history) > 1 else s.path_history[-1]
        beat = _Beat(current_frame, cx, cy, px, py, mode)
        s.last_beat = beat
        at_end = current_frame == len(s.smooth_path) - 1

        # [NOTE] [Animation] stop_popup (the "E" pin) is excluded from the proximity loop (the
        # recap/ending highlight handle its arrival), but the pin drawing keys off "arrived", so
        # flag it here or its pin never shows on the main map.
        if s.stop_popup and not s.stop_popup["data"]["triggered"] and at_end:
            s.stop_popup["data"]["triggered"] = True
            s.stop_popup["data"]["arrived"] = True

        for popup in s.active_popups:
            self._queue_if_reached(s, popup, beat)
        self._update_preview(s)
        triggered_popup = self._pop_trigger(s, clock, current_frame)

        # Pins reached in the last tuning.PIN_POP_SECONDS are still popping in.
        self._pop_now = s.video.frames_written
        frame_no_route = self._frame_without_current_leg(s)
        if not s.is_video:
            self._draw_walk_pins(s, frame, at_end)

        # [NOTE] [Animation] Only the last iteration's pre-popup frame is read (by the recap), so
        # skip the full-resolution copy on every other frame.
        if s.stop_popup and at_end:
            s.pre_popup_frame = frame.copy()
        # The clean plate BEFORE any flowing card goes on: a freeze/batch holds it for seconds,
        # and a stale still-fading card baked into it would show next to the new stop's card.
        s.frame_before_popups = frame
        self._trim_cards_for_return(s, triggered_popup)
        frame, s.baked_popups = self._composite_baked_popups(
            frame, s.baked_popups, s.w, s.h, s.route_obstacles,
            active_popups=s.active_popups, total_points=s.n_points, fps=s.fps,
        )
        if frame_no_route is None:
            frame_no_route = frame

        if triggered_popup:
            self._walk_arrive(s, clock, beat, triggered_popup, frame_no_route)
        else:
            if not s.is_video:
                self._walk_turn(s, beat)
                self._walk_draw_icon(s, frame, beat)
            self.last_frame = frame
            s.video.write(frame)
        s.prev_cx, s.prev_cy = cx, cy

    def _read_video_frame(self, s: _WalkState) -> None:
        ret, vid_frame = s.cap.read()
        if not ret:
            return
        if vid_frame.shape[0] != s.h or vid_frame.shape[1] != s.w:
            vid_frame = cv2.resize(vid_frame, (s.w, s.h))
        s.current_bg = vid_frame

    def _track_mode(self, s: _WalkState, current_frame: int) -> str:
        """The travel mode at this frame; records it (with the leg color, when
        the route has per-leg colors) and the HUD's progress fraction."""
        leg_color = None
        if s.cum is not None:
            frac = s.cum[current_frame] / s.total_dist
            mode = self._mode_at_fraction(s.mode_breakpoints, frac)
            color_breakpoints = getattr(self, "_color_breakpoints", None)
            if color_breakpoints:
                leg_color = self._mode_at_fraction(color_breakpoints, frac)
            self._hud_progress_frac = frac
        else:
            mode = "walking"
        s.mode_history.append((mode, leg_color) if leg_color else mode)
        return mode

    def _walk_turn(self, s: _WalkState, beat: _Beat) -> None:
        s.smoothed_angle = self._smoothed_heading(
            s.smoothed_angle, beat.cx, beat.cy, s.prev_cx, s.prev_cy
        )

    def _walk_draw_icon(self, s: _WalkState, frame: np.ndarray, beat: _Beat) -> None:
        self.graphics.draw_transport_icon(
            frame, beat.cx, beat.cy, beat.index, s.smoothed_angle, mode=beat.mode
        )

    def _queue_if_reached(self, s: _WalkState, popup: Dict, beat: _Beat) -> None:
        """Queues (not triggers) a not-yet-triggered popup the traveler is
        passing right now: queued immediately so a popup is never missed just
        because the trigger cooldown hasn't elapsed (gating the proximity check
        on it could let the traveler move past a clustered pin entirely)."""
        stop_popup = s.stop_popup
        if popup["index"] == 0 or (stop_popup and popup["index"] == stop_popup["index"]):
            return
        # A stop-by hosted by a waypoint's batch plays during that host's stop
        # (see _play_stopby_batch); triggering here too would show it twice.
        if popup.get("stopby_host") is not None:
            return
        is_stopby = self._is_loose_stopby(popup)
        seq = s.sequential_popups
        if not is_stopby and (s.seq_ptr >= len(seq) or popup is not seq[s.seq_ptr]):
            return
        # Identity check, not `in`: these dicts keep mutating in place ("triggered" itself).
        if popup["data"]["triggered"] or any(p is popup for p in s.pending_popups):
            return
        # Raw pixel distance alone isn't "arrived": a route that loops can pass close to a
        # pin long before reaching it. expected_frame (overview.py) is the pin's own position in
        # the path's time sequence; the tolerance only absorbs its estimation jitter.
        expected_frame = popup.get("expected_frame")
        trigger_tolerance_frames = int(s.fps * tuning.OVERVIEW_POPUP_TRIGGER_TOLERANCE_SECONDS)
        if (
            expected_frame is not None
            and beat.index < expected_frame - trigger_tolerance_frames
        ):
            return
        # A stop-by can sit off the drawn route entirely, so time alone is enough for it;
        # only a real waypoint must also be near the traveler on screen.
        near_enough = is_stopby or (
            RouteGeometryProcessor.point_to_segment_distance(
                popup["x"], popup["y"], beat.px, beat.py, beat.cx, beat.cy
            )
            < (
                self.graphics.marker_radius
                + self.trigger_radius_padding["overview"]
            )
        )
        if not near_enough:
            return
        s.pending_popups.append(popup)
        if not is_stopby:
            # This was sequential_popups[seq_ptr]: the next real waypoint becomes eligible.
            s.seq_ptr += 1
        # [NOTE] [Animation] Pin is "arrived" on the frame the traveler gets there; "triggered"
        # only flips after the cooldown, seconds later in a cluster, which made the pin pop late.
        popup["data"]["arrived"] = True
        popup["pop_frame"] = s.video.frames_written  # the pin pops in from here

    def _update_preview(self, s: _WalkState) -> None:
        """The next real waypoint still ahead gets a small preview badge (name,
        number, thumbnail) before arriving, so the traveler never walks toward a
        stop with nothing on screen naming it; also the HUD's stop counter and
        "next" line. The badge clears the moment that waypoint triggers."""
        self._preview_badge = None
        self._hud_stops = (s.seq_ptr, len(s.sequential_popups)) if s.sequential_popups else None
        self._hud_next_stop = None
        if s.seq_ptr < len(s.sequential_popups):
            upcoming = s.sequential_popups[s.seq_ptr]
            self._hud_next_stop = upcoming.get("label") or None
            if not upcoming["data"].get("triggered") and upcoming["data"].get("popup_image"):
                self._preview_badge = upcoming

    def _pop_trigger(self, s: _WalkState, clock: _WalkClock, current_frame: int) -> Optional[Dict]:
        """Dequeues the next popup once the trigger cooldown allows. The cooldown
        shrinks (to a floor) the more is backed up: a fixed one could outlast the
        remaining frames and leave queued waypoints never shown."""
        effective_gap_frames = s.min_trigger_gap_frames
        if len(s.pending_popups) > 1:
            effective_gap_frames = max(
                int(s.fps * _MIN_TRIGGER_GAP_FLOOR_SECONDS),
                s.min_trigger_gap_frames // len(s.pending_popups),
            )
        if not s.pending_popups or current_frame - s.last_trigger_frame < effective_gap_frames:
            return None
        popup = s.pending_popups.pop(0)
        popup["data"]["triggered"] = True
        s.last_trigger_frame = current_frame
        clock.catch_up_due = True
        if popup["data"].get("inaccessible"):
            self._start_stopby_notice(s.fps, tuning.STOPBY_NOTICE_SECONDS, kind="closed")
        elif popup["data"].get("is_stopby") and not popup.get("stopby_group"):
            self._start_stopby_notice(s.fps, tuning.STOPBY_NOTICE_SECONDS)
        if popup.get("cue_frame") is not None:
            logger.info(
                "Overview stop #%s reached at %.1fs (its cue: %.1fs).",
                popup.get("order"), s.video.frames_written / s.fps, popup["cue_frame"] / s.fps,
            )
        # border_color was set before any waypoint had "arrived", so it is the pre-arrival
        # marker color; recompute now so the card border matches its pin.
        _, fresh_border_color, _ = self._pin_label_and_color(popup, s.n_points)
        popup["border_color"] = fresh_border_color or self.graphics.marker_color
        return popup

    def _frame_without_current_leg(self, s: _WalkState) -> Optional[np.ndarray]:
        """[NOTE] [Animation] "Point to point" snapshot for hide_route_on_popup: every earlier
        leg stays drawn, only the CURRENT one (since the last waypoint) is left off, so
        arriving doesn't erase the route travelled so far. Built separately from the walk
        frame because pins must render on top of the route line there."""
        if s.is_video or not self.hide_route_on_popup:
            return None
        frame_no_route = s.current_bg.copy()
        self.graphics.draw_path(
            frame_no_route,
            s.path_history[: s.last_leg_boundary + 1],
            s.mode_history[: s.last_leg_boundary + 1],
        )
        self._draw_arrived_pins(s, frame_no_route)
        return frame_no_route

    def _draw_arrived_pins(self, s: _WalkState, frame: np.ndarray) -> None:
        """Every waypoint is shown once up front on the intro frame, but from
        here on a pin only reappears once the traveler reaches it."""
        for wp in s.active_popups:
            if wp["data"].get("arrived") or wp["index"] == 0:
                self._draw_pin(frame, wp, s.n_points, scale=self._pin_pop_scale(wp, self._pop_now, s.fps))

    def _draw_walk_pins(self, s: _WalkState, frame: np.ndarray, at_end: bool) -> None:
        # The recap draws a plain dot per stop, so it gets the plate from BEFORE the
        # teardrop pins go on (dots over pins would leave each teardrop sticking out).
        if s.stop_popup and at_end:
            # The map faded back with the route redrawn on it (see plain_recap_plate).
            self._recap_plate = self.plain_recap_plate(
                s.current_bg, s.path_history, s.mode_history
            )
        self._draw_arrived_pins(s, frame)

    def _trim_cards_for_return(self, s: _WalkState, triggered_popup: Optional[Dict]) -> None:
        """Once every real waypoint has been QUEUED, only the final destination is
        ahead (the "Return" stretch: just line, pins and banner), so every card but
        the last stop's is cleared, with no fade. `triggered_popup is None` lets
        the frame the last waypoint itself triggers play out normally."""
        if triggered_popup is None and s.seq_ptr >= len(s.sequential_popups) and not self._cards_stay():
            last_stop = s.sequential_popups[-1] if s.sequential_popups else None
            s.baked_popups = [b for b in s.baked_popups if b["popup"] is last_stop]

    def _walk_arrive(
        self, s: _WalkState, clock: _WalkClock, beat: _Beat, popup: Dict,
        frame_no_route: np.ndarray,
    ) -> None:
        """A waypoint triggered on this frame: lay its card out and play its
        arrival, either flowing (the walker keeps moving) or frozen."""
        # Everything up to here becomes an "earlier leg" for the NEXT popup's hide effect.
        s.last_leg_boundary = len(s.path_history) - 1

        s.arrival_count += 1
        place_label = popup.get("label") or f"waypoint_{popup['index']}"
        tracker.show_item(
            s.arrival_count,
            f"Rendering overview video {s.arrival_count}/{s.total_stops}: arriving at '{place_label}'",
        )

        # [NOTE] [Animation] Laid out once and kept on the popup so the arrival pause, the hold
        # and the lingering HUD all reuse the identical spot; every card already on screen is
        # reserved or this lone popup could land on a still-visible neighbour.
        self._layout_recap_popups(
            [{"popup": popup, "frames_left": 1}], s.w, s.h,
            route_obstacles=s.route_obstacles,
            reserved_boxes=self._active_card_boxes(
                s.baked_popups, exclude=popup
            ) + self._stopby_notice_reserved(s.w, s.h),
        )
        popup["hud_corner"] = None
        popup["draw_leader_line"] = True

        # Shared base for the arrival pause and the popup: only already-arrived pins when
        # requested, so the pause and the popup read as one "you arrived" beat.
        if self.hide_upcoming_pins_on_popup:
            popup_base_frame = self._build_freeze_frame(
                s.current_bg, s.path_history, s.mode_history,
                s.last_leg_boundary, s.active_popups, s.n_points,
            )
        else:
            popup_base_frame = (
                frame_no_route if self.hide_route_on_popup else s.frame_before_popups
            )

        # [NOTE] [Animation] Waypoints flow through by default (the traveler keeps moving); one
        # only freezes with "freeze_frame": true. A waypoint hosting unconnected stop-bys always
        # freezes: their cards are played over its held frame.
        stopby_group = popup.get("stopby_group") or []
        if popup["data"].get("freeze_frame", False) or bool(stopby_group):
            self._arrive_frozen(s, beat, popup, popup_base_frame, stopby_group)
        else:
            self._arrive_flowing(s, clock, beat, popup, popup_base_frame)

    def _plan_cue_wait(self, s: _WalkState, clock: _WalkClock, popup: Dict):
        """Sets clock.wait: reached before the voice gets to this stop's cue, the walker
        stops here and the picture holds (card showing) until the voice catches up. A
        cue at the start of a sentence always waits at least cue_wait_frames, and a stop
        described until its {go} waits for it (arriving late shortens the stop, never
        runs it past the {go}). Returns the map-style card scale when this is a map stop."""
        fps = s.fps
        max_wait = int(_MAX_CUE_WAIT_SECONDS * fps)
        cue_frame = popup.get("cue_frame")
        early = int(cue_frame) - s.video.frames_written - 1 if cue_frame is not None else 0
        clock.wait = max(int(popup.get("cue_wait_frames") or 0), min(max(0, early), max_wait))
        if popup.get("no_pause"):
            early = 0
            clock.wait = 0  # "Pause at Location" off: walk straight on
        map_stop = self.config.get("overview_style") == "map" and popup.get("card_scale")
        depart_frame = popup.get("depart_frame")
        if depart_frame is not None:
            clock.wait = max(
                min(max(0, early), max_wait),
                int(depart_frame) - s.video.frames_written - 1,
                0,
            )
            logger.info(
                "Overview stop #%s: describing it until %.1fs (holding %.1fs).",
                popup.get("order"), depart_frame / fps, clock.wait / fps,
            )
        if early > 0:
            logger.info(
                "Overview stop #%s reached %.1fs before its cue: waiting %.1fs.",
                popup.get("order"), early / fps, clock.wait / fps,
            )
        if map_stop and not popup.get("no_pause"):
            # Route map: stand here long enough to see the photo and read the leg card.
            clock.wait = max(clock.wait, int(tuning.OVERVIEW_MAP_MIN_STOP_SECONDS * fps))
        return map_stop

    def _flow_display_seconds(self, s: _WalkState, clock: _WalkClock, popup: Dict, map_stop) -> float:
        # The card rides along for roughly this leg (so it hands off to the next popup about
        # when that waypoint is reached) and stays up while the walker waits.
        display_seconds = float(
            popup.get("leg_display_seconds")
            or popup["data"].get("freeze_seconds", _DEFAULT_FREEZE_SECONDS)
        ) + clock.wait / s.fps
        if map_stop:
            display_seconds = clock.wait / s.fps + self._POPUP_FADE_SECONDS  # closes as the walker leaves
        if self._cards_stay():
            # Walk the route: every stop's card stays up to the end (at its summary spot and size).
            display_seconds = _CARD_STAYS_SECONDS
        return display_seconds

    def _wrap_up_earlier_cards(self, s: _WalkState, popup: Dict) -> None:
        """Forces every OTHER still-active, not-yet-fading flow-through card into
        its fade-out the moment a later stop arrives. frames_left only counts down
        while a card is drawn, so one that started late (behind others) could run
        its full duration long after the traveler moved on. Never before the card
        has had POPUP_MIN_DISPLAY_SECONDS on screen (else it "blinks": gone a frame
        or two after fading in) and OVERVIEW_POPUP_MIN_HOLD_SECONDS fully shown.
        The floor is deliberately unconditional: shrinking it under a deep backlog
        once left cards under their guaranteed 2 s."""
        fps = s.fps
        new_order = popup.get("order", 0)
        min_display_frames = max(1, int(tuning.POPUP_MIN_DISPLAY_SECONDS * fps))
        for bp in ([] if self._cards_stay() else s.baked_popups):
            if bp["popup"]["data"].get("freeze_frame", False):
                continue
            if bp["popup"].get("order", 0) >= new_order:
                continue
            wrap_up_frames = bp.get("fade_frames") or max(
                1, int(self._POPUP_FADE_SECONDS * fps)
            )
            elapsed = bp.get("total_frames", bp["frames_left"]) - bp["frames_left"]
            remaining_for_min_display = max(0, min_display_frames - elapsed)
            hold_left = max(
                0, wrap_up_frames + int(tuning.OVERVIEW_POPUP_MIN_HOLD_SECONDS * fps) - elapsed
            )
            target_frames_left = max(
                wrap_up_frames, remaining_for_min_display, hold_left + wrap_up_frames
            )
            if self.config.get("overview_style") == "map":
                target_frames_left = wrap_up_frames  # one big card at a time: the last one closes now
            bp["frames_left"] = min(bp["frames_left"], target_frames_left)

    def _arrive_flowing(
        self, s: _WalkState, clock: _WalkClock, beat: _Beat, popup: Dict, popup_base_frame: np.ndarray,
    ) -> None:
        """Flow-through: no held frame, no arrival pause. The card rides along as
        a HUD overlay beside the waypoint's pin and this one frame is written
        here before the loop resumes normal per-frame compositing."""
        map_stop = self._plan_cue_wait(s, clock, popup)
        display_seconds = self._flow_display_seconds(s, clock, popup, map_stop)
        self._wrap_up_earlier_cards(s, popup)
        new_bp = self._make_baked_popup(
            popup, display_seconds, s.fps, min_hold_seconds=tuning.OVERVIEW_POPUP_MIN_HOLD_SECONDS,
        )
        s.baked_popups.append(new_bp)
        frame = self._redraw_other_cards(s, popup_base_frame, new_bp)
        if not s.is_video:
            frame = self._draw_arriving_card(s, frame, popup, new_bp, beat)
        self.last_frame = frame
        s.video.write(frame)

    def _redraw_other_cards(self, s: _WalkState, frame: np.ndarray, new_bp: Dict) -> np.ndarray:
        """popup_base_frame is a clean plate with no cards, so every OTHER active
        card (an earlier waypoint's, still fading) is redrawn on this one frame;
        without it that card vanished for exactly this frame (a visible blink)."""
        for other_bp in s.baked_popups:
            if other_bp is new_bp:
                continue
            other_popup = other_bp["popup"]
            if not other_popup.get("beside_box"):
                continue
            other_hud = self.walk_card_hud(
                other_popup, s.w, s.h, s.route_obstacles,
                lambda popup: self._active_card_boxes(s.baked_popups, exclude=popup),
            )
            other_alpha = self._popup_fade_alpha(other_bp)
            frame = self.graphics.render_popup_box(
                frame, other_hud, alpha=other_alpha, line_only=True
            )
            self._draw_pin(frame, other_popup, s.n_points, scale=self._pin_pop_scale(other_popup, self._pop_now, s.fps))
            frame = self.graphics.render_popup_box(
                frame, other_hud, alpha=other_alpha, skip_line=True
            )
        return frame

    def _draw_arriving_card(
        self, s: _WalkState, frame: np.ndarray, popup: Dict, new_bp: Dict, beat: _Beat,
    ) -> np.ndarray:
        """The new card on its arrival frame, faded in from the start like every
        later frame _composite_baked_popups draws it for (else the pin, already on
        this frame, would show a frame before its card)."""
        self._walk_turn(s, beat)
        # A card that stays already has its badge's spot (_layout_recap_cards); looking for
        # another would show it there for one frame and jump back on the next.
        stays = popup.get("stay_box")
        if not stays:
            self._layout_recap_popups(
                [new_bp], s.w, s.h, route_obstacles=s.route_obstacles,
                reserved_boxes=self._active_card_boxes(
                    s.baked_popups, exclude=popup
                ) + self._stopby_notice_reserved(s.w, s.h),
            )
        hud_new = self.walk_card_hud(
            popup, s.w, s.h, s.route_obstacles,
            lambda other: self._active_card_boxes(s.baked_popups, exclude=other),
        )
        # Slide-up entrance (see _popup_slide_offset_y); a staying card doesn't slide.
        if hud_new.get("beside_box") and not stays:
            bx, by = hud_new["beside_box"]
            hud_new["beside_box"] = (bx, int(by + self._popup_slide_offset_y(new_bp)))
        # Line, then pin, then card: the pin is already in `frame`, so a combined call
        # would land the line over it.
        frame = self.graphics.render_popup_box(
            frame, hud_new, alpha=self._popup_fade_alpha(new_bp), line_only=True,
        )
        self._draw_pin(frame, popup, s.n_points, scale=self._pin_pop_scale(popup, self._pop_now, s.fps))
        frame = self.graphics.render_popup_box(
            frame, hud_new, alpha=self._popup_fade_alpha(new_bp), skip_line=True,
        )
        # Drawn LAST: the traveler sits on this pin the instant it triggers.
        self._walk_draw_icon(s, frame, beat)
        return frame

    def _arrive_frozen(
        self, s: _WalkState, beat: _Beat, popup: Dict, popup_base_frame: np.ndarray,
        stopby_group: List[Dict],
    ) -> None:
        """Freeze: the map holds on the stop (arrival pause, card hold, then its
        stop-by batch). Cards of the stops just passed still inside their display
        time (`carried`) stay up over the whole freeze and fade on their own clock;
        popup_base_frame is a clean plate, so they used to vanish when the map stopped."""
        carried = s.baked_popups
        s.baked_popups = []
        if not s.is_video and self.post_arrival_hold_seconds > 0:
            self._arrival_pause(s, beat, popup, popup_base_frame, carried)

        display_seconds = float(popup["data"].get("freeze_seconds", _DEFAULT_FREEZE_SECONDS))
        # The voice may still be describing this stop when the planned hold would end:
        # same {go}-cue wait the flow-through branch gives, only ever extending the hold
        # (capped at _MAX_CUE_WAIT_SECONDS) so a freezing stop never cuts its narration off.
        depart_frame = popup.get("depart_frame")
        if depart_frame is not None:
            needed = (int(depart_frame) - s.video.frames_written) / s.fps
            display_seconds = max(display_seconds, min(needed, _MAX_CUE_WAIT_SECONDS))
        # A CONNECTED stop-by hosting a batch has no settle-first beat: its card joins the
        # batch and fades in with the landmarks. A real waypoint host keeps the two-beat order.
        host_is_stopby = bool(stopby_group) and bool(popup["data"].get("is_stopby"))
        if not host_is_stopby:
            self._settle_card(s, popup, popup_base_frame, carried, display_seconds, stopby_group)

        # The landmarks behind this stop, in route order. Built from popup_base_frame (the
        # hold's last frame has the host's card mid-slide-out) with draw_host_card=False:
        # its one appearance was the settle above.
        if stopby_group:
            hud_settled = popup.copy()
            hud_settled["hud_corner"] = None
            hud_settled["draw_leader_line"] = True
            self.last_frame = self._play_stopby_batch(
                s.video, popup_base_frame, popup, hud_settled,
                stopby_group, s.w, s.h, s.fps, s.n_points,
                route_obstacles=s.route_obstacles,
                draw_host_card=False, carried=carried,
                animate_host=host_is_stopby,
                total_display_seconds=display_seconds if host_is_stopby else None,
            )
        s.baked_popups = carried + s.baked_popups

    def _arrival_pause(
        self, s: _WalkState, beat: _Beat, popup: Dict, popup_base_frame: np.ndarray,
        carried: List[Dict],
    ) -> None:
        """A beat on the traveler having just reached the pin. Pin only, no card:
        the hold loop after it fades the card in from scratch (a card at flat alpha
        here made one pop-in twice: opaque, then dipping to restart its fade)."""
        pause_frame = popup_base_frame.copy()
        self._walk_turn(s, beat)
        self._draw_pin(pause_frame, popup, s.n_points)
        self._walk_draw_icon(s, pause_frame, beat)
        for _ in range(int(self.post_arrival_hold_seconds * s.fps)):
            s.video.write(self._draw_carried(
                pause_frame, carried, s.w, s.h, s.route_obstacles, s.n_points, s.fps
            ))

    def _settle_card(
        self, s: _WalkState, popup: Dict, popup_base_frame: np.ndarray, carried: List[Dict],
        display_seconds: float, stopby_group: List[Dict],
    ) -> None:
        """The host's own card fades in over the frozen map (re-rendered each frame so its
        alpha can ramp) and, unless a stop-by batch follows, lingers as a baked popup once
        the walk resumes. With a batch it is NOT appended: the batch makes the host's card
        vanish, and reappearing after it read as a stray "already shown image" flash."""
        lingering_bp = self._make_baked_popup(popup, display_seconds, s.fps)
        if not stopby_group:
            s.baked_popups.append(lingering_bp)
        hud_triggered = popup.copy()

        total_hold_frames = lingering_bp["total_frames"]
        fade_in_frames = lingering_bp["fade_frames"]
        temp_frame = popup_base_frame
        base_beside_box = hud_triggered.get("beside_box")
        for i in range(total_hold_frames):
            alpha = min(1.0, (i + 1) / fade_in_frames)
            if base_beside_box:
                bx, by = base_beside_box
                # Reuses _popup_slide_offset_y via a throwaway bp-shaped dict of this loop's progress.
                slide = self._popup_slide_offset_y(
                    {
                        "total_frames": total_hold_frames,
                        "frames_left": total_hold_frames - i,
                        "fade_frames": fade_in_frames,
                    }
                )
                hud_triggered["beside_box"] = (bx, int(by + slide))
            # Line, then pin, then card: the base's own pin(s) are baked in already.
            temp_frame = self.graphics.render_popup_box(
                popup_base_frame, hud_triggered, alpha=alpha, line_only=True
            )
            self._draw_pin(temp_frame, popup, s.n_points)
            temp_frame = self.graphics.render_popup_box(
                temp_frame, hud_triggered, alpha=alpha, skip_line=True
            )
            temp_frame = self._draw_carried(
                temp_frame, carried, s.w, s.h, s.route_obstacles, s.n_points, s.fps
            )
            s.video.write(temp_frame)

        self.last_frame = temp_frame
        # [NOTE] [Animation] The hold loop writes straight to video, never through
        # _composite_baked_popups, so lingering_bp's frames_left never counted down; left alone
        # the card re-entered from scratch when the walk resumed. Jump to "just past its fade-in".
        lingering_bp["frames_left"] = lingering_bp["fade_frames"]

    def _hold_final_cards(self, s: _WalkState) -> None:
        """The walk is over with every stop's card still up (they stay for the whole
        walk): hold on that picture before the recap turns them into badges. Composited
        frame by frame, since the final stop's card pops as the walk ends and a frozen
        frame would hold it half faded-in."""
        if not (
            s.stop_popup and not s.is_video and self._cards_stay()
            and s.frame_before_popups is not None
        ):
            return
        beat = s.last_beat
        for _ in range(int(tuning.RECAP_CARD_HOLD_SECONDS * s.fps)):
            held = s.frame_before_popups.copy()
            held, s.baked_popups = self._composite_baked_popups(
                held, s.baked_popups, s.w, s.h, s.route_obstacles,
                active_popups=s.active_popups, total_points=s.n_points, fps=s.fps,
            )
            self._walk_draw_icon(s, held, beat)
            self.last_frame = held
            s.video.write(held)
