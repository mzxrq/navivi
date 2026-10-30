"""The "course" overview (settings.overview_style "course"): the whole route is
shown at once, then traced from the start while each stop's photo card pops in
beside it and stays, a stats card slides in with the totals, and the stop-bys
appear last. Timed by the course script's cues: {route} (the trace starts),
{n} (stop n reached; with {go} cues, only {go} stops are timed, at their {go}),
{end} (trace done, stats card) and {extras} (stop-bys).
"""

import math
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw

from services import tuning
from services.vdoprocessing.route_inputs import same_place
from services.mapfetcher.graphicengine.glyphs import drawable
from services.logger.progress import tracker
from services.vdoprocessing.vdoexporter import VideoExporter

from .base import logger

_MIN_ANCHOR_GAP_SECONDS = 0.4
_LAST_LEG_MAX_SECONDS = 4.0  # the walk to the last stop never takes longer than this


def _smoothstep(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def trace_anchors(
    stop_dists: List[Tuple],
    total_dist: float,
    route_at: float,
    end_at: Optional[float],
    legs: int,
) -> List[Tuple]:
    """(seconds, distance along the route) the trace passes through, in order.
    `stop_dists` is (cue seconds or None, distance[, stops]) per place in route
    order; places without a cue are passed on the way. A cued place with
    stops=False (named mid-sentence, no {go}) becomes (seconds, distance, False):
    the trace goes through it without slowing. (seconds, distance, True, until)
    arrives at `seconds` and waits there until `until`. Without any cue the trace runs
    COURSE_SECONDS_PER_LEG per leg, within COURSE_TRACE_MIN..MAX_SECONDS."""
    anchors: List[Tuple] = [(route_at, 0.0)]
    for cue, dist, *rest in stop_dists:
        if cue is None or dist <= anchors[-1][1]:
            continue
        if cue < anchors[-1][0] + _MIN_ANCHOR_GAP_SECONDS:
            until = rest[1] if len(rest) > 1 else None
            if until is None or until < anchors[-1][0] + 3 * _MIN_ANCHOR_GAP_SECONDS:
                continue
            # "{go}{n}": named the moment the walker leaves the stop before; it still goes there and waits.
            cue = anchors[-1][0] + min(1.0, (until - anchors[-1][0]) / 2)
        anchors.append((float(cue), float(dist)) if not rest or rest[0] else (float(cue), float(dist), False))
        if len(rest) > 1 and rest[1] is not None and rest[1] > cue + _MIN_ANCHOR_GAP_SECONDS:
            anchors.append((float(rest[1]), float(dist)))
    if end_at is not None and end_at > anchors[-1][0] + _MIN_ANCHOR_GAP_SECONDS:
        arrive = float(end_at)
        if len(anchors) > 1 and anchors[-1][1] < total_dist:
            # The last stretch goes at the pace so far (2..LAST_LEG_MAX_SECONDS) and rests at the end;
            # stretching it to the end cue made a short walk crawl while the voice talked on.
            pace = anchors[-1][1] / max(1e-6, anchors[-1][0] - route_at)
            take = min(_LAST_LEG_MAX_SECONDS, max(2.0, (total_dist - anchors[-1][1]) / max(1e-6, pace)))
            arrive = min(arrive, anchors[-1][0] + take)
        anchors.append((arrive, total_dist))
    elif anchors[-1][1] < total_dist:
        if len(anchors) > 1:
            # the rest at the pace so far
            speed = anchors[-1][1] / max(1e-6, anchors[-1][0] - route_at)
            rest = (total_dist - anchors[-1][1]) / max(1e-6, speed)
        else:
            rest = min(tuning.COURSE_TRACE_MAX_SECONDS,
                       max(tuning.COURSE_TRACE_MIN_SECONDS, legs * tuning.COURSE_SECONDS_PER_LEG))
        anchors.append((anchors[-1][0] + max(2.0, rest), total_dist))
    return hold_before_slow_stretches(relax_anchors(anchors))


def hold_before_slow_stretches(anchors: List[Tuple], share: float = tuning.COURSE_MIN_PACE_SHARE) -> List[Tuple]:
    """A stretch slower than `share` of the trace's average pace (places close together, named seconds apart)
    waits where it starts and then goes at that pace, still arriving on time, instead of crawling."""
    span = anchors[-1][0] - anchors[0][0] if len(anchors) > 1 else 0.0
    if span <= 0 or share <= 0:
        return anchors
    floor = share * (anchors[-1][1] - anchors[0][1]) / span
    out = [anchors[0]]
    for b in anchors[1:]:
        a = out[-1]
        dd, dt = b[1] - a[1], b[0] - a[0]
        need = dd / floor if floor > 0 else dt
        if dd > 0 and dt - need > _MIN_ANCHOR_GAP_SECONDS:
            out[-1] = (a[0], a[1])  # it now stops there
            out.append((b[0] - need, a[1]))
        out.append(b)
    return out


def stop_distances(path: np.ndarray, cum: np.ndarray, places: List[Tuple[float, float]], tol: float = 6.0) -> List[float]:
    """Distance along `path` of each place, in route order: the first point after the previous place's where
    the path passes it (within `tol` px of its closest pass from there on)."""
    out, last = [], 0
    for x, y in places:
        rest = path[last:]
        if len(rest):
            d = np.hypot(rest[:, 0] - x, rest[:, 1] - y)
            last += int(np.flatnonzero(d <= d.min() + tol)[0])
        out.append(float(cum[last]))
    return out


def pin_reveal_time(reached: float, said: float, route_at: float, window: float = tuning.COURSE_CUE_WINDOW_SECONDS) -> float:
    """When a stop's pin shows: when the voice names it (`said`), or when the trace gets there
    if that is within `window` seconds after; never earlier than the voice, never later than the window."""
    said = max(route_at, float(said))
    return min(max(reached, said), said + window)


def relax_anchors(anchors: List[Tuple], window: float = tuning.COURSE_CUE_WINDOW_SECONDS, passes: int = 30) -> List[Tuple]:
    """Eases the pace between cues: a place the trace only passes may be reached up to
    `window` seconds AFTER its cue (never before: a pin should not show ahead of the voice),
    which evens out the speed before and after it. Settling stops, the start and the end keep
    their times, so every cue still lands within 0..window seconds."""
    times = [float(a[0]) for a in anchors]
    cues = list(times)
    for _ in range(passes):
        for i in range(1, len(anchors) - 1):
            if len(anchors[i]) == 2:
                continue  # a stop the trace settles on keeps its cue
            (_, d0), (_, d1), (_, d2) = (a[:2] for a in anchors[i - 1:i + 2])
            if d2 <= d0:
                continue
            even = times[i - 1] + (times[i + 1] - times[i - 1]) * (d1 - d0) / (d2 - d0)
            low = max(cues[i], times[i - 1] + _MIN_ANCHOR_GAP_SECONDS)
            high = min(cues[i] + window, times[i + 1] - _MIN_ANCHOR_GAP_SECONDS)
            if high >= low:
                times[i] = min(high, max(low, even))
    return [(t, *a[1:]) for t, a in zip(times, anchors)]


def _ease(s: float, settle_from: bool, settle_to: bool) -> float:
    s = min(1.0, max(0.0, s))
    if settle_from and settle_to:
        return _smoothstep(s)
    if settle_from:
        return s * s * (2 - s)  # sets off from rest, arrives at speed
    if settle_to:
        return 1 - (1 - s) * (1 - s) * (1 + s)  # arrives at speed, settles
    return s


def distance_at(anchors: List[Tuple], t: float) -> float:
    """How far the trace has got at `t` seconds: it settles on each stop and
    sets off again, and goes straight through a passed place (a 3-tuple anchor)."""
    if t <= anchors[0][0]:
        return anchors[0][1]
    for a, b in zip(anchors, anchors[1:]):
        (t0, d0), (t1, d1) = a[:2], b[:2]
        if t <= t1:
            return d0 + (d1 - d0) * _ease((t - t0) / max(1e-6, t1 - t0), len(a) == 2, len(b) == 2)
    return anchors[-1][1]


def tagline_at(taglines: List[str], t: float) -> Tuple[str, float]:
    """(tagline, opacity) at `t`: each held COURSE_TAGLINE_SECONDS, fading through."""
    if not taglines:
        return "", 0.0
    period, fade = tuning.COURSE_TAGLINE_SECONDS, tuning.COURSE_TAGLINE_FADE_SECONDS
    k, local = divmod(max(0.0, t), period)
    text = taglines[int(k) % len(taglines)]
    if len(taglines) == 1:
        return text, min(1.0, local / fade) if k == 0 else 1.0
    return text, max(0.0, min(1.0, local / fade, (period - local) / fade))


class _CourseOverviewMixin:
    def _render_course_overview(
        self,
        current_bg: np.ndarray,
        w: int,
        h: int,
        fps: int,
        points: List,
        smooth_path,
        mode_breakpoints,
        cum_smooth_dist: Optional[np.ndarray],
        total_smooth_dist: float,
        active_popups: List[Dict],
        route_obstacle_arr: np.ndarray,
        summary: Optional[Dict],
        overview_path: str,
        bounding_box: Optional[Dict[str, float]] = None,
    ) -> str:
        cues = dict(self.config.get("overview_cue_seconds") or {})
        audio_seconds = float(self.config.get("overview_audio_seconds") or 0.0)
        total_points = len(points)

        path = np.asarray(smooth_path, dtype=float)
        seg = np.hypot(np.diff(path[:, 0]), np.diff(path[:, 1]))
        cum = np.concatenate([[0.0], np.cumsum(seg)])
        total = float(cum[-1]) or 1.0

        def loose(ap: Dict) -> bool:
            # Every stop-by, connected or not, pops up with the others at {extras}, not on the traced route.
            return bool(ap["data"].get("is_stopby"))

        on_route = [ap for ap in active_popups if not loose(ap)]
        extras = [ap for ap in active_popups if loose(ap)]
        stop_popup = next((ap for ap in active_popups if ap["index"] == total_points - 1), None)

        # Each stop's distance along the drawn path: in route order, the first place after the previous stop
        # where the path passes it (within a few px of its closest pass). Estimating it from its share of the
        # raw route first put the island loop's stops (and a pier passed twice) at the wrong pass.
        for ap, dist in zip(on_route, stop_distances(path, cum, [(ap["x"], ap["y"]) for ap in on_route])):
            ap["course_dist"] = 0.0 if ap["index"] == 0 else dist
        if stop_popup is not None:
            stop_popup["course_dist"] = total

        # Travel mode along the drawn path: each stop pinned to its own place on it, the raw route's mode read in
        # between (by share of the whole route, the island walk showed the boat until the return).
        raw = np.hypot(np.diff([p[0] for p in points]), np.diff([p[1] for p in points]))
        raw_cum = np.concatenate([[0.0], np.cumsum(raw)])
        raw_total = float(raw_cum[-1]) or 1.0
        knots = sorted({(0.0, 0.0), (total, 1.0)} | {
            (ap["course_dist"], float(raw_cum[min(ap["index"], len(raw_cum) - 1)]) / raw_total) for ap in on_route
        })
        xs, fs = [k[0] for k in knots], np.maximum.accumulate([k[1] for k in knots])
        modes = [self._mode_at_fraction(mode_breakpoints, float(np.interp(c, xs, fs))) for c in cum]

        start_at = float(cues.get("start", 0.0))
        route_at = float(cues["route"]) if "route" in cues else start_at + (
            tuning.COURSE_PIVOT_HOLD_SECONDS if cues else 1.5
        )
        numbered = [ap for ap in on_route if ap["index"] != 0 and ap is not stop_popup]
        # A return stop ("Add return stop": a copy of an earlier stop, same place) is still walked to on its
        # cue, but draws no pin or card of its own over the original's.
        returns = {
            id(ap) for ap in numbered
            if any(same_place(ap["data"], b["data"]) for b in on_route[:on_route.index(ap)])
        }
        if self._is_loop_route and stop_popup is not None:
            returns.add(id(stop_popup))  # the start pin already shows a loop's end (half green, half red)
        any_go = any(str(k).startswith("go") for k in cues)

        def arrive_cue(ap: Dict) -> Tuple:
            # A {go} stop is reached when its name is said and the walker waits
            # there until {go} (arriving at {go} spread the walk over the whole
            # description: a crawl between close stops). A stop named without a
            # {go} is passed at the second its name is said.
            name = cues.get(str(ap.get("order")))
            if not any_go:
                return (name, ap["course_dist"])
            go = cues.get(f"go{ap.get('order')}")
            if go is None or ap["data"].get("pause_at_waypoint") is False:  # "Pause at Location" off: passed
                return (name, ap["course_dist"], False)
            if name is not None and float(name) < float(go):
                return (float(name), ap["course_dist"], True, float(go))
            return (float(go), ap["course_dist"])

        anchors = trace_anchors(
            [arrive_cue(ap) for ap in numbered],
            total, route_at, cues.get("end"), max(1, len(numbered) + 1),
        )
        trace_end = anchors[-1][0]
        stats_at = float(cues["end"]) if "end" in cues else trace_end + 0.5
        extras_at = float(cues["extras"]) if "extras" in cues else (stats_at + 4.0 if extras else None)
        end_at = max(
            audio_seconds + 0.3 if audio_seconds else trace_end + 6.0,
            stats_at + 2.0,
            (extras_at + 3.0) if extras_at is not None else 0.0,
        )

        # Cards: every stop with a photo, laid out once (as the recap does) clear
        # of the headline, the stats card and the stop-by notice.
        summary_card = None
        summary = self.config.get("course_summary") or summary  # the numbers the script speaks
        if summary:
            summary_card = self.graphics.render_summary_card(
                distance_km=summary.get("total_distance_km", 0.0),
                duration_seconds=summary.get("total_duration_seconds", 0.0),
                mode_breakdown=summary.get("mode_breakdown"),
                mode_duration=summary.get("mode_duration"),
            )
        taglines = [str(x) for x in (self.config.get("overview_taglines") or []) if str(x).strip()]
        # the headline, docked top left: as wide as the widest tagline
        headline_font = max(22, int(h * 0.033))
        headline_w = max((self.graphics.top_banner_width(x, headline_font) for x in taglines), default=0)
        reserved = [(0.0, 0.0, min(float(w), h * 0.03 * 2 + headline_w), h * 0.14)]
        if summary_card is not None:
            ch, cw = summary_card.shape[:2]
            drop = tuning.COURSE_STATS_DROP_PX
            reserved.append((w - cw - 20.0, h - ch - 20.0 + drop, w - 20.0, h - 20.0 + drop))
        if extras:
            reserved.append(tuple(float(v) for v in self.graphics.stopby_notice_box(w, h)))
        # Stop-bys with a photo get their card too, popping in with their pin at {extras}.
        card_popups = [ap for ap in on_route + extras if ap["data"].get("popup_image") and id(ap) not in returns]
        if self._is_loop_route and stop_popup is not None:
            card_popups = [ap for ap in card_popups if ap is not stop_popup]
        laid_out = self._layout_recap_cards(card_popups, w, h, reserved_boxes=reserved,
                                            route_obstacles=route_obstacle_arr)
        cards = {ap["index"]: ap for ap in laid_out}

        def reveal_time(dist: float) -> float:
            for (t0, _d0, *_), (t1, d1, *_) in zip(anchors, anchors[1:]):
                if dist <= d1 + 1e-6:
                    lo, hi = t0, t1
                    for _ in range(30):  # distance_at is monotonic: bisect
                        mid = (lo + hi) / 2
                        if distance_at(anchors, mid) >= dist - 1e-6:
                            hi = mid
                        else:
                            lo = mid
                    return hi
            return anchors[-1][0]

        for ap in on_route:
            ap["course_at"] = route_at if ap["index"] == 0 else reveal_time(ap["course_dist"])
            # A pin and its card appear when the voice names the stop: never before, and
            # at most COURSE_CUE_WINDOW_SECONDS after, wherever the trace is by then.
            said = cues.get(str(ap.get("order")))
            if said is not None and ap["index"] != 0 and ap is not stop_popup:
                ap["course_at"] = pin_reveal_time(ap["course_at"], said, route_at)
        for k, ap in enumerate(extras):
            ap["course_at"] = (extras_at or end_at) + k * tuning.COURSE_STOPBY_STAGGER_SECONDS
            ap["pop_frame"] = int(round(ap["course_at"] * fps))

        # The planned route under everything, drawn once.
        route_bg = current_bg.copy()
        pts = [(int(x), int(y)) for x, y in path]
        self.graphics.draw_path(route_bg, pts, modes)
        trace_color = tuple(self.config.get("course_trace_color") or tuning.COURSE_TRACE_COLOR)
        thick = max(3, int(round(self.graphics.line_thickness * 1.4)))
        border = self.graphics.line_border_thickness

        # A name beside the pin only where no card names it.
        labels = {
            id(ap): None if ap["index"] in cards else self._course_label_sprite(ap.get("label") or "")
            for ap in extras
        }
        # Each label goes on the first side of its pin clear of the cards, pins and earlier labels.
        r = int(self.graphics.marker_radius)
        taken = [
            (bx, by, bx + cw, by + ch)
            for ap in laid_out if ap.get("beside_box")
            for (bx, by), (cw, ch) in [(ap["beside_box"], self.graphics.beside_card_footprint(ap.get("card_scale", 1.0)))]
        ] + [
            (ap.get("pin_x", ap["x"]) - r, ap.get("pin_y", ap["y"]) - r,
             ap.get("pin_x", ap["x"]) + r, ap.get("pin_y", ap["y"]) + r)
            for ap in on_route + extras
        ]
        label_at = {}
        for ap in extras:
            sprite = labels[id(ap)]
            if sprite is None:
                continue
            sh, sw = sprite.shape[:2]
            px, py = int(ap.get("pin_x", ap["x"])), int(ap.get("pin_y", ap["y"]))
            sides = [(px + r + 6, py - sh // 2), (px - r - 6 - sw, py - sh // 2),
                     (px - sw // 2, py - r - 6 - sh), (px - sw // 2, py + r + 6)]
            free = [
                (x, y) for x, y in sides
                if 0 <= x and x + sw <= w and 0 <= y and y + sh <= h
                and not any(x < b[2] and b[0] < x + sw and y < b[3] and b[1] < y + sh for b in taken)
            ]
            x, y = (free or sides)[0]
            label_at[id(ap)] = (x, y)
            taken.append((x, y, x + sw, y + sh))
        pop = tuning.COURSE_CARD_POP_SECONDS

        def plate_state(t: float):
            shown, anim = [], []
            for ap in laid_out:
                age = t - ap["course_at"]
                if age >= 0:
                    shown.append(ap["index"])
                    if age < pop:
                        anim.append((ap["index"], round(age / pop, 2)))
            bumps = tuple(
                (ap["index"], round((t - ap["course_at"]) / pop, 2))
                for ap in on_route if 0 <= t - ap["course_at"] < pop
            )
            arrived = tuple(ap["index"] for ap in on_route if t >= ap["course_at"])
            extra_on = tuple(
                (ap["index"], round(self._pin_pop_scale(ap, int(round(t * fps)), fps), 2))
                for ap in extras if t >= ap["course_at"]
            )
            return tuple(shown), tuple(anim), bumps, arrived, extra_on

        def build_layer(state, base: np.ndarray) -> np.ndarray:
            shown, anim, bumps, arrived, extra_on = state
            alpha = dict(anim)
            for ap in on_route:
                ap["data"]["arrived"] = ap["index"] in arrived
            plate = base.copy()
            huds = [self._course_hud(cards[i]) for i in shown]
            for hud in huds:
                plate = self.graphics.render_popup_box(
                    plate, hud, alpha=_smoothstep(alpha.get(hud["index"], 1.0)), line_only=True)
            bump = dict(bumps)
            for ap in on_route:
                if id(ap) in returns:
                    continue
                u = bump.get(ap["index"])
                scale = 1.0 + 0.3 * math.sin(math.pi * u) if u is not None else 1.0
                self._draw_pin(plate, ap, total_points, scale=scale)
            scales = dict(extra_on)
            for ap in extras:
                if ap["index"] in scales:
                    self._draw_pin(plate, ap, total_points, scale=scales[ap["index"]])
            for hud in huds:
                a = alpha.get(hud["index"])
                if a is not None and hud.get("beside_box"):  # rises a little as it fades in
                    bx, by = hud["beside_box"]
                    hud = dict(hud, beside_box=(bx, int(by + 14 * (1 - _smoothstep(a)))))
                plate = self.graphics.render_popup_box(
                    plate, hud, alpha=_smoothstep(a if a is not None else 1.0), skip_line=True)
            for ap in extras:  # above the cards, should no side be free
                if id(ap) in label_at and scales.get(ap["index"], 0.0) >= 0.99:
                    self.graphics.blit_sprite(plate, labels[id(ap)], (0, 0), *label_at[id(ap)])
            return plate

        def build_overlay(state) -> Tuple[np.ndarray, np.ndarray]:
            """Cards and pins as their own layer: drawn over black and over white,
            whose difference is each pixel's opacity. Blended over the traced
            route, so the trace shows through their soft shadows (pasting every
            changed pixel used to bring back the untraced line around each card)."""
            on_black = build_layer(state, np.zeros_like(route_bg)).astype(np.float32)
            on_white = build_layer(state, np.full_like(route_bg, 255)).astype(np.float32)
            opacity = np.clip(1.0 - (on_white - on_black).mean(axis=2, keepdims=True) / 255.0, 0.0, 1.0)
            # 3 channels and the rounding folded in, for the per-frame cv2 blend (3.5x numpy's).
            return np.repeat(1.0 - opacity, 3, axis=2), on_black + 0.5

        total_frames = int(math.ceil(end_at * fps))
        logger.info(
            "Course overview: %.1fs (route from %.1fs, traced by %.1fs, stats at %.1fs%s); %d card(s).",
            end_at, route_at, trace_end, stats_at,
            f", stop-bys at {extras_at:.1f}s" if extras_at is not None else "", len(laid_out),
        )
        video = VideoExporter(overview_path, w, h, fps)
        tracker.begin_substeps(max(1, int(end_at)))
        state, keep, layer = None, None, None
        frame = route_bg
        prev_cx, prev_cy = None, None
        smoothed_angle = self._initial_heading(path)

        for i in range(total_frames):
            t = i / fps
            new_state = plate_state(t)
            if new_state != state:
                state = new_state
                keep, layer = build_overlay(state)
            frame = route_bg.copy()

            dist = distance_at(anchors, t)
            k = int(np.searchsorted(cum, dist))
            head = path[min(k, len(path) - 1)]
            if t >= route_at and k > 0:
                if k < len(path):
                    d0, d1 = cum[k - 1], cum[k]
                    u = (dist - d0) / max(1e-6, d1 - d0)
                    head = path[k - 1] + (path[k] - path[k - 1]) * u
                line = np.array(pts[:k] + [(int(head[0]), int(head[1]))], dtype=np.int32)
                if border:
                    cv2.polylines(frame, [line], False, self.graphics.line_border_color, thick + 2 * border, cv2.LINE_AA)
                cv2.polylines(frame, [line], False, trace_color, thick, cv2.LINE_AA)
            blended = cv2.add(cv2.multiply(frame, keep, dtype=cv2.CV_32F), layer)
            frame = np.clip(blended, 0, 255, out=blended).astype(np.uint8)

            if route_at <= t < trace_end + 0.6:
                mode = modes[min(max(0, k - 1), len(modes) - 1)]
                head = head if t < trace_end else path[-1]
                fade = 1.0 if t < trace_end else max(0.0, 1.0 - (t - trace_end) / 0.6)
                cx, cy = int(head[0]), int(head[1])
                smoothed_angle = self._smoothed_heading(smoothed_angle, cx, cy, prev_cx, prev_cy)
                prev_cx, prev_cy = cx, cy

                if fade < 1.0:
                    overlay = frame.copy()
                    self.graphics.draw_transport_icon(overlay, cx, cy, i, smoothed_angle, mode)
                    cv2.addWeighted(overlay, fade, frame, 1.0 - fade, 0, dst=frame)
                else:
                    self.graphics.draw_transport_icon(frame, cx, cy, i, smoothed_angle, mode)

            text, alpha = tagline_at(taglines, t)
            if text and alpha > 0:
                frame = self.graphics.render_top_banner(
                    frame, text, alpha=alpha, top_margin=int(h * 0.03), font_px=max(22, int(h * 0.033)),
                    align="left", left_margin=int(h * 0.03))
            if summary_card is not None and t >= stats_at:
                u = _smoothstep((t - stats_at) / tuning.COURSE_STATS_SLIDE_SECONDS)
                frame = self.graphics.composite_card_on_frame(
                    frame, summary_card, alpha=u, slide_offset_y=tuning.COURSE_STATS_DROP_PX + (1 - u) * 80)
            if extras_at is not None and t >= extras_at:
                frame = self.graphics.render_stopby_notice(frame, alpha=_smoothstep((t - extras_at) / 0.5))

            video.write(frame)
            if i % fps == 0:
                tracker.show_item(i // fps + 1, f"Rendering course overview {i // fps}/{int(end_at)}s")

        # After the voice, the walk overview's ending: the GL zoom to the start and its photo.
        self.last_frame = frame
        hard_ended = False
        if stop_popup is not None and self.config.get("enable_ending_highlight", True):
            clean = route_bg.copy()
            whole = np.array(pts, dtype=np.int32)
            if border:
                cv2.polylines(clean, [whole], False, self.graphics.line_border_color, thick + 2 * border, cv2.LINE_AA)
            cv2.polylines(clean, [whole], False, trace_color, thick, cv2.LINE_AA)
            for ap in on_route + extras:
                if id(ap) not in returns:
                    self._draw_pin(clean, ap, total_points)
            start_popup = next((ap for ap in active_popups if ap["index"] == 0), None)
            hard_ended = self._render_ending_highlight(
                video, w, h, fps, stop_popup, start_popup,
                clean_map_frame=clean, bounding_box=bounding_box,
            )

        for ap in active_popups:
            ap["data"]["triggered"] = False
            ap["data"]["arrived"] = False
        self.last_rendered_seconds = video.frames_written / fps
        self.last_ending_hard_ended = hard_ended
        return video.release(overview_path)

    def _course_hud(self, ap: Dict) -> Dict:
        """A laid-out card as the recap draws it (see _render_recap_frame)."""
        hud = ap.copy()
        hud["hud_corner"] = None
        hud["draw_leader_line"] = True
        color = ap.get("recap_line_color") or self.graphics.marker_color
        hud["leader_line_color"] = color
        hud["leader_line_width"] = self._RECAP_LEADER_WIDTH
        hud["border_color"] = color
        return hud

    def _course_label_sprite(self, text: str) -> Optional[np.ndarray]:
        """A stop-by's name beside its dot: white text with a dark outline (BGRA)."""
        text = drawable((text or "").strip())
        if not text:
            return None
        font = self.graphics._card_font(self.graphics.FONT_CANDIDATES_BOLD, 22)
        box = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox((0, 0), text, font=font, stroke_width=3)
        img = Image.new("RGBA", (box[2] - box[0] + 4, box[3] - box[1] + 4), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((2 - box[0], 2 - box[1]), text, font=font, fill=(40, 30, 25, 255),
                                 stroke_width=3, stroke_fill=(255, 255, 255, 255))
        return np.array(img)[:, :, [2, 1, 0, 3]]

