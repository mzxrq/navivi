"""The "course" overview (settings.overview_style "course"): the whole route is
shown at once, then traced from the start while each stop's photo card pops in
beside it and stays, a stats card slides in with the totals, and the stop-bys
appear last. Timed by the course script's cues: {route} (the trace starts),
{n} (stop n reached; with {go} cues, only {go} stops are timed, at their {go}),
{end} (trace done, stats card) and {extras} (stop-bys).
"""

import math
from typing import Callable, Dict, List, NamedTuple, Optional, Set, Tuple

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
_EXTRAS_AFTER_SECONDS = 4.0  # the stop-bys come this long after the stats, the closed places after them
_TRACE_TAIL_SECONDS = 0.6  # the transport icon fades out over this once the trace is done
_NOTICE_FADE_SECONDS = 0.5
_LABEL_GAP_PX = 6  # between a stop-by's pin and the name beside it


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


def leg_banner(stops: List[Tuple[float, str, str]], dist: float) -> List[Tuple[str, str]]:
    """[(glyph, name), (glyph, name)] for the stretch the trace is drawing at `dist`: the last
    stop reached and the next one, each behind the glyph its own pin shows. `stops` is
    (distance along the route, pin glyph, name) per stop in route order, the start first."""
    reached = [s for s in stops if s[0] <= dist + 1e-6]
    ahead = [s for s in stops if s[0] > dist + 1e-6]
    if not reached or not ahead:
        return []
    return [(reached[-1][1], reached[-1][2]), (ahead[0][1], ahead[0][2])]


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


class _Timing(NamedTuple):
    """When things happen, in seconds. extras_at / closed_at are None when there is nothing of that kind."""
    anchors: List[Tuple]
    route_at: float
    trace_end: float
    stats_at: float
    extras_at: Optional[float]
    closed_at: Optional[float]
    end_at: float
    stopbys: List[Dict]
    closed: List[Dict]


class _Panels(NamedTuple):
    """The fixed furniture of the frame (cards, headline, rail) and the boxes the badges keep clear of."""
    summary_card: Optional[np.ndarray]
    taglines: List[str]
    leg_stops: List[Tuple[float, str, str]]
    headline_font: int
    margin: int
    totals: Optional[Image.Image]
    stats_y: int
    rail_marks: List[Tuple[float, str, Tuple]]
    closed_offset: int
    reserved: List[Tuple[float, float, float, float]]


class _Trace(NamedTuple):
    """The drawn route: its points, cumulative length, travel mode per point and line style."""
    path: np.ndarray
    cum: np.ndarray
    pts: List[Tuple[int, int]]
    modes: List[str]
    color: Tuple
    thick: int
    border: int


class _Scene(NamedTuple):
    """What the cards-and-pins layer is drawn from."""
    on_route: List[Dict]
    extras: List[Dict]
    laid_out: List[Dict]
    cards: Dict[int, Dict]
    returns: Set[int]
    labels: Dict[int, Optional[np.ndarray]]
    label_at: Dict[int, Tuple[int, int]]
    total_points: int
    fps: int
    draw_marker: Callable


class _Heading:
    """The transport icon's smoothed heading and the last head position it was measured from."""

    def __init__(self, angle: float):
        self.angle = angle
        self.x: Optional[int] = None
        self.y: Optional[int] = None


def _drawn_path(smooth_path) -> Tuple[np.ndarray, np.ndarray, float]:
    """(path, cumulative length per point, total length) of the drawn route."""
    path = np.asarray(smooth_path, dtype=float)
    seg = np.hypot(np.diff(path[:, 0]), np.diff(path[:, 1]))
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    return path, cum, float(cum[-1]) or 1.0


def _is_loose(ap: Dict) -> bool:
    """Every stop-by, connected or not, pops up with the others at {extras}, not on the traced route."""
    return bool(ap["data"].get("is_stopby"))


def _split_popups(
    active_popups: List[Dict], total_points: int, path: np.ndarray, cum: np.ndarray, total: float,
) -> Tuple[List[Dict], List[Dict], Optional[Dict]]:
    """(on_route, extras, stop_popup); stamps each on-route stop's `course_dist` along the drawn path."""
    on_route = [ap for ap in active_popups if not _is_loose(ap)]
    extras = [ap for ap in active_popups if _is_loose(ap)]
    stop_popup = next((ap for ap in active_popups if ap["index"] == total_points - 1), None)

    # [NOTE] [Course] In route order, the first place after the previous stop where the path passes it (within a
    # few px of its closest pass). Estimating it from its share of the raw route first put the island loop's
    # stops (and a pier passed twice) at the wrong pass.
    for ap, dist in zip(on_route, stop_distances(path, cum, [(ap["x"], ap["y"]) for ap in on_route])):
        ap["course_dist"] = 0.0 if ap["index"] == 0 else dist
    if stop_popup is not None:
        stop_popup["course_dist"] = total
    return on_route, extras, stop_popup


def _return_stops(numbered: List[Dict], on_route: List[Dict], stop_popup: Optional[Dict], is_loop: bool) -> Set[int]:
    """ids of the stops that draw no pin or card of their own. A return stop ("Add return stop": a copy of an
    earlier stop, same place) is still walked to on its cue, but not drawn over the original."""
    returns = {
        id(ap) for ap in numbered
        if any(same_place(ap["data"], b["data"]) for b in on_route[:on_route.index(ap)])
    }
    if is_loop and stop_popup is not None:
        returns.add(id(stop_popup))  # the start pin already shows a loop's end (half green, half red)
    return returns


def _arrive_cue(ap: Dict, cues: Dict, any_go: bool) -> Tuple:
    """A {go} stop is reached when its name is said and the walker waits there until {go} (arriving at {go}
    spread the walk over the whole description: a crawl between close stops). A stop named without a {go} is
    passed at the second its name is said."""
    name = cues.get(str(ap.get("order")))
    if not any_go:
        return (name, ap["course_dist"])
    go = cues.get(f"go{ap.get('order')}")
    if go is None or ap["data"].get("pause_at_waypoint") is False:  # "Pause at Location" off: passed
        return (name, ap["course_dist"], False)
    if name is not None and float(name) < float(go):
        return (float(name), ap["course_dist"], True, float(go))
    return (float(go), ap["course_dist"])


def _course_timing(
    cues: Dict, audio_seconds: float, numbered: List[Dict], extras: List[Dict], total: float,
) -> _Timing:
    start_at = float(cues.get("start", 0.0))
    route_at = float(cues["route"]) if "route" in cues else start_at + (
        tuning.COURSE_PIVOT_HOLD_SECONDS if cues else 1.5
    )
    any_go = any(str(k).startswith("go") for k in cues)
    anchors = trace_anchors(
        [_arrive_cue(ap, cues, any_go) for ap in numbered],
        total, route_at, cues.get("end"), max(1, len(numbered) + 1),
    )
    trace_end = anchors[-1][0]
    stats_at = float(cues["end"]) if "end" in cues else trace_end + 0.5
    # Closed places (red ×) come after the stop-bys, at {closed}; drawn like them otherwise.
    stopbys = [ap for ap in extras if not ap["data"].get("inaccessible")]
    closed = [ap for ap in extras if ap["data"].get("inaccessible")]
    extras_at = float(cues["extras"]) if "extras" in cues else (stats_at + _EXTRAS_AFTER_SECONDS if stopbys else None)
    closed_at = (float(cues["closed"]) if "closed" in cues
                 else ((extras_at if extras_at is not None else stats_at) + _EXTRAS_AFTER_SECONDS if closed else None))
    end_at = max(
        audio_seconds + 0.3 if audio_seconds else trace_end + 6.0,
        stats_at + 2.0,
        (extras_at + 3.0) if extras_at is not None else 0.0,
        (closed_at + 3.0) if closed_at is not None else 0.0,
    )
    return _Timing(anchors, route_at, trace_end, stats_at, extras_at, closed_at, end_at, stopbys, closed)


def _reveal_time(anchors: List[Tuple], dist: float) -> float:
    """The first moment the trace has reached `dist`."""
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


def _set_reveal_times(
    on_route: List[Dict], stop_popup: Optional[Dict], cues: Dict, timing: _Timing, fps: int,
) -> None:
    """Stamps `course_at` on every stop (and `pop_frame` on the stop-bys and closed places)."""
    for ap in on_route:
        ap["course_at"] = timing.route_at if ap["index"] == 0 else _reveal_time(timing.anchors, ap["course_dist"])
        # A pin and its card appear when the voice names the stop: never before, and
        # at most COURSE_CUE_WINDOW_SECONDS after, wherever the trace is by then.
        said = cues.get(str(ap.get("order")))
        if said is not None and ap["index"] != 0 and ap is not stop_popup:
            ap["course_at"] = pin_reveal_time(ap["course_at"], said, timing.route_at)
    for group, at in ((timing.stopbys, timing.extras_at), (timing.closed, timing.closed_at)):
        for k, ap in enumerate(group):
            ap["course_at"] = (at if at is not None else timing.end_at) + k * tuning.COURSE_STOPBY_STAGGER_SECONDS
            ap["pop_frame"] = int(round(ap["course_at"] * fps))


def _log_timing(timing: _Timing, cards: int) -> None:
    logger.info(
        "Course overview: %.1fs (route from %.1fs, traced by %.1fs, stats at %.1fs%s); %d card(s).",
        timing.end_at, timing.route_at, timing.trace_end, timing.stats_at,
        f", stop-bys at {timing.extras_at:.1f}s" if timing.extras_at is not None else "", cards,
    )


def _largest(panels: List) -> Optional[object]:
    return max(panels, key=lambda c: (c.size[0] * c.size[1]) if c is not None else -1, default=None)


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

        path, cum, total = _drawn_path(smooth_path)
        on_route, extras, stop_popup = _split_popups(active_popups, total_points, path, cum, total)
        modes = self._course_modes(points, on_route, total, cum, mode_breakpoints)
        numbered = [ap for ap in on_route if ap["index"] != 0 and ap is not stop_popup]
        returns = _return_stops(numbered, on_route, stop_popup, self._is_loop_route)
        timing = _course_timing(cues, audio_seconds, numbered, extras, total)
        panels = self._course_panels(
            summary, w, h, on_route, timing, total_points, total_smooth_dist)
        pill_recap, laid_out, cards = self._course_cards(
            on_route, extras, returns, stop_popup, panels.reserved, route_obstacle_arr, current_bg, w, h)
        _set_reveal_times(on_route, stop_popup, cues, timing, fps)

        route_bg, trace = self._course_route_plate(current_bg, path, cum, modes)
        labels, label_at = self._course_extra_labels(extras, cards, laid_out, on_route, w, h)
        # A pill badge already shows its stop's number, so the map under it only needs the
        # color: a plain dot, as the walk's recap draws (_draw_recap_dot), not a numbered
        # teardrop repeating it.
        draw_marker = self._draw_recap_dot if pill_recap else self._draw_pin
        scene = _Scene(on_route, extras, laid_out, cards, returns, labels, label_at, total_points, fps, draw_marker)

        _log_timing(timing, len(laid_out))
        video = VideoExporter(overview_path, w, h, fps)
        tracker.begin_substeps(max(1, int(timing.end_at)))
        self._course_play(video, scene, route_bg, trace, timing, panels, total_smooth_dist)

        # After the voice, the walk overview's ending: the GL zoom to the start and its photo.
        hard_ended = False
        if stop_popup is not None and self.config.get("enable_ending_highlight", True):
            hard_ended = self._course_ending(
                video, w, h, fps, route_bg, trace, scene, stop_popup, active_popups, bounding_box)

        for ap in active_popups:
            ap["data"]["triggered"] = False
            ap["data"]["arrived"] = False
        self.last_rendered_seconds = video.frames_written / fps
        self.last_ending_hard_ended = hard_ended
        return video.release(overview_path)

    def _course_route_plate(
        self, current_bg: np.ndarray, path: np.ndarray, cum: np.ndarray, modes: List[str],
    ) -> Tuple[np.ndarray, _Trace]:
        """The planned route under everything, drawn once, and the style the trace is drawn over it in."""
        route_bg = current_bg.copy()
        pts = [(int(x), int(y)) for x, y in path]
        self.graphics.draw_path(route_bg, pts, modes)
        return route_bg, _Trace(
            path, cum, pts, modes,
            tuple(self.config.get("course_trace_color") or tuning.COURSE_TRACE_COLOR),
            max(3, int(round(self.graphics.line_thickness * 1.4))),
            self.graphics.line_border_thickness,
        )

    def _course_modes(
        self, points: List, on_route: List[Dict], total: float, cum: np.ndarray, mode_breakpoints,
    ) -> List[str]:
        """Travel mode along the drawn path: each stop pinned to its own place on it, the raw route's mode read in
        between (by share of the whole route; the island walk showed the boat until the return)."""
        raw = np.hypot(np.diff([p[0] for p in points]), np.diff([p[1] for p in points]))
        raw_cum = np.concatenate([[0.0], np.cumsum(raw)])
        raw_total = float(raw_cum[-1]) or 1.0
        knots = sorted({(0.0, 0.0), (total, 1.0)} | {
            (ap["course_dist"], float(raw_cum[min(ap["index"], len(raw_cum) - 1)]) / raw_total) for ap in on_route
        })
        xs, fs = [k[0] for k in knots], np.maximum.accumulate([k[1] for k in knots])
        return [self._mode_at_fraction(mode_breakpoints, float(np.interp(c, xs, fs))) for c in cum]

    def _course_panels(
        self, summary: Optional[Dict], w: int, h: int, on_route: List[Dict], timing: _Timing,
        total_points: int, total_smooth_dist: float,
    ) -> _Panels:
        """Everything fixed on the frame, and `reserved`: the boxes the cards are laid out clear of (the
        headline, the totals, the stats card, the progress rail and the stop-by notices)."""
        summary = self.config.get("course_summary") or summary  # the numbers the script speaks
        summary_card = None
        if summary:
            summary_card = self.graphics.render_summary_card(
                distance_km=summary.get("total_distance_km", 0.0),
                duration_seconds=summary.get("total_duration_seconds", 0.0),
                mode_breakdown=summary.get("mode_breakdown"),
                mode_duration=summary.get("mode_duration"),
                banner_theme=True,  # it sits under the totals chip now, not alone on the map
            )
        taglines = [str(x) for x in (self.config.get("overview_taglines") or []) if str(x).strip()]
        leg_stops = self._course_leg_stops(on_route, total_points)
        headline_font = max(22, int(h * 0.033))
        margin = int(h * 0.03)
        reserved: List[Tuple[float, float, float, float]] = []

        # Reserved at the widest the headline ever gets, so no badge sits where a later stretch's own
        # (longer) names will be drawn.
        banners = [leg_banner(leg_stops, d) for d, _, _ in leg_stops]
        headline = _largest([
            self.graphics.route_headline_panel(title, steps, headline_font)
            for title in (taglines or [""]) for steps in (banners or [[]])
        ])
        if headline is not None:
            reserved.append((0.0, 0.0, float(margin * 2 + headline.size[0]),
                             float(margin * 2 + headline.size[1])))
        totals = self.graphics.route_totals_panel(
            (summary or {}).get("total_distance_km"), (summary or {}).get("total_duration_seconds"),
        ) if summary else None
        if totals is not None:
            reserved.append((float(w - margin - totals.size[0]), 0.0, float(w), float(margin * 2 + totals.size[1])))
        # The stats card hangs under the totals chip, top right: the foot of the frame is the progress rail's.
        stats_y = margin + ((totals.size[1] + 12) if totals is not None else 0)
        if summary_card is not None:
            ch, cw = summary_card.shape[:2]
            reserved.append((w - cw - float(margin), float(stats_y), float(w), float(stats_y + ch)))
        rail_marks = self._course_rail_marks(on_route, total_points, total_smooth_dist)
        rail_h = self.graphics.route_progress_rail_height(h) if rail_marks else 0
        if rail_h:
            reserved.append((0.0, float(h - margin - rail_h), float(w), float(h)))
        closed_offset = self._reserve_notices(reserved, timing, w, h)
        return _Panels(summary_card, taglines, leg_stops, headline_font, margin, totals, stats_y,
                       rail_marks, closed_offset, reserved)

    def _course_leg_stops(self, on_route: List[Dict], total_points: int) -> List[Tuple[float, str, str]]:
        """(distance, glyph, name) per named stop: the headline names the stretch being drawn ("A → B"),
        in sync with the trace."""
        leg_stops: List[Tuple[float, str, str]] = []
        for ap in on_route:
            name = str(ap.get("label") or "").strip()
            if name and (not leg_stops or ap["course_dist"] > leg_stops[-1][0]):
                glyph, _, _ = self._pin_label_and_color(ap, total_points)
                leg_stops.append((float(ap["course_dist"]), str(glyph or ""), name))
        return leg_stops

    def _course_rail_marks(
        self, on_route: List[Dict], total_points: int, total_smooth_dist: float,
    ) -> List[Tuple[float, str, Tuple]]:
        """The progress rail's ticks: the whole route as one line across the foot, a tick per stop."""
        rail_marks = []
        for ap in on_route:
            glyph, color, _ = self._pin_label_and_color(ap, total_points)
            # _pin_color returns None for a stop not yet reached, meaning "the default".
            rail_marks.append((
                float(ap["course_dist"]) / max(1e-6, total_smooth_dist),
                str(glyph if glyph is not None else ""),
                tuple(color or self.graphics.marker_color)[:3],
            ))
        return rail_marks

    def _reserve_notices(self, reserved: List, timing: _Timing, w: int, h: int) -> int:
        """Adds the stop-by notice (bottom left) and the closed-place one beside it to `reserved`;
        returns the closed notice's x offset."""
        closed_offset = 0
        if timing.stopbys:
            box = self.graphics.stopby_notice_box(w, h)
            reserved.append(tuple(float(v) for v in box))
            closed_offset = box[2] - box[0] + int(24 * h / 1080)
        if timing.closed:
            reserved.append(tuple(float(v) for v in self.graphics.stopby_notice_box(
                w, h, "closed", closed_offset)))
        return closed_offset

    def _course_cards(
        self, on_route: List[Dict], extras: List[Dict], returns: Set[int], stop_popup: Optional[Dict],
        reserved: List, route_obstacle_arr: np.ndarray, current_bg: np.ndarray, w: int, h: int,
    ) -> Tuple[bool, List[Dict], Dict[int, Dict]]:
        """(pill_recap, laid_out, cards by index): every stop with a photo, laid out once (as the recap does)
        clear of the headline, the stats card and the stop-by notice. Stop-bys with a photo get their card
        too, popping in with their pin at {extras}."""
        card_popups = [ap for ap in on_route + extras if ap["data"].get("popup_image") and id(ap) not in returns]
        if self._is_loop_route and stop_popup is not None:
            card_popups = [ap for ap in card_popups if ap is not stop_popup]
        # Pill badges are laid out exactly as the walk/map recap lays them out: no leader lines
        # (the badge's number and its pin's are the tie). A pop_up_card recap keeps its leaders: a wide
        # photo card carries no number, so the line is the only thing tying it to a pin.
        pill_recap = self.config.get("overview_recap_style", "pill_badge") != "pop_up_card"
        laid_out = self._layout_recap_cards(card_popups, w, h, reserved_boxes=reserved,
                                            route_obstacles=route_obstacle_arr,
                                            background=current_bg if pill_recap else None,
                                            leaders=not pill_recap,
                                            clutter_pull=self._CLUTTER_PULL_COURSE_PX)
        return pill_recap, laid_out, {ap["index"]: ap for ap in laid_out}

    def _course_extra_labels(
        self, extras: List[Dict], cards: Dict[int, Dict], laid_out: List[Dict], on_route: List[Dict],
        w: int, h: int,
    ) -> Tuple[Dict[int, Optional[np.ndarray]], Dict[int, Tuple[int, int]]]:
        """(sprites, positions) of the names beside the stop-by pins. A name goes beside the pin only where
        no card names it, on the first side clear of the cards, pins and earlier labels."""
        labels = {
            id(ap): None if ap["index"] in cards else self._course_label_sprite(ap.get("label") or "")
            for ap in extras
        }
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
        gap = r + _LABEL_GAP_PX
        for ap in extras:
            sprite = labels[id(ap)]
            if sprite is None:
                continue
            sh, sw = sprite.shape[:2]
            px, py = int(ap.get("pin_x", ap["x"])), int(ap.get("pin_y", ap["y"]))
            sides = [(px + gap, py - sh // 2), (px - gap - sw, py - sh // 2),
                     (px - sw // 2, py - gap - sh), (px - sw // 2, py + gap)]
            free = [
                (x, y) for x, y in sides
                if 0 <= x and x + sw <= w and 0 <= y and y + sh <= h
                and not any(x < b[2] and b[0] < x + sw and y < b[3] and b[1] < y + sh for b in taken)
            ]
            x, y = (free or sides)[0]
            label_at[id(ap)] = (x, y)
            taken.append((x, y, x + sw, y + sh))
        return labels, label_at

    def _course_plate_state(self, scene: _Scene, t: float):
        """What is on the cards-and-pins layer at `t`; the layer is only rebuilt when this changes."""
        pop = tuning.COURSE_CARD_POP_SECONDS
        shown, anim = [], []
        for ap in scene.laid_out:
            age = t - ap["course_at"]
            if age >= 0:
                shown.append(ap["index"])
                if age < pop:
                    anim.append((ap["index"], round(age / pop, 2)))
        bumps = tuple(
            (ap["index"], round((t - ap["course_at"]) / pop, 2))
            for ap in scene.on_route if 0 <= t - ap["course_at"] < pop
        )
        arrived = tuple(ap["index"] for ap in scene.on_route if t >= ap["course_at"])
        extra_on = tuple(
            (ap["index"], round(self._pin_pop_scale(ap, int(round(t * scene.fps)), scene.fps), 2))
            for ap in scene.extras if t >= ap["course_at"]
        )
        return tuple(shown), tuple(anim), bumps, arrived, extra_on

    def _course_layer(self, scene: _Scene, state, base: np.ndarray) -> np.ndarray:
        """The cards and pins drawn over `base`."""
        shown, anim, bumps, arrived, extra_on = state
        alpha = dict(anim)
        for ap in scene.on_route:
            ap["data"]["arrived"] = ap["index"] in arrived
        plate = base.copy()
        huds = [self._course_hud(scene.cards[i]) for i in shown]
        for hud in huds:
            plate = self.graphics.render_popup_box(
                plate, hud, alpha=_smoothstep(alpha.get(hud["index"], 1.0)), line_only=True)
        bump = dict(bumps)
        for ap in scene.on_route:
            if id(ap) in scene.returns:
                continue
            u = bump.get(ap["index"])
            scale = 1.0 + 0.3 * math.sin(math.pi * u) if u is not None else 1.0
            scene.draw_marker(plate, ap, scene.total_points, scale=scale)
        scales = dict(extra_on)
        for ap in scene.extras:
            if ap["index"] in scales:
                scene.draw_marker(plate, ap, scene.total_points, scale=scales[ap["index"]])
        for hud in huds:
            a = alpha.get(hud["index"])
            if a is not None and hud.get("beside_box"):  # rises a little as it fades in
                bx, by = hud["beside_box"]
                hud = dict(hud, beside_box=(bx, int(by + 14 * (1 - _smoothstep(a)))))
            plate = self.graphics.render_popup_box(
                plate, hud, alpha=_smoothstep(a if a is not None else 1.0), skip_line=True)
        for ap in scene.extras:  # above the cards, should no side be free
            if id(ap) in scene.label_at and scales.get(ap["index"], 0.0) >= 0.99:
                self.graphics.blit_sprite(plate, scene.labels[id(ap)], (0, 0), *scene.label_at[id(ap)])
        return plate

    def _course_overlay(self, scene: _Scene, state, route_bg: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Cards and pins as their own layer: drawn over black and over white,
        whose difference is each pixel's opacity. Blended over the traced
        route, so the trace shows through their soft shadows (pasting every
        changed pixel used to bring back the untraced line around each card)."""
        on_black = self._course_layer(scene, state, np.zeros_like(route_bg)).astype(np.float32)
        on_white = self._course_layer(scene, state, np.full_like(route_bg, 255)).astype(np.float32)
        opacity = np.clip(1.0 - (on_white - on_black).mean(axis=2, keepdims=True) / 255.0, 0.0, 1.0)
        # 3 channels and the rounding folded in, for the per-frame cv2 blend (3.5x numpy's).
        return np.repeat(1.0 - opacity, 3, axis=2), on_black + 0.5

    def _course_play(
        self, video: VideoExporter, scene: _Scene, route_bg: np.ndarray, trace: _Trace, timing: _Timing,
        panels: _Panels, total_smooth_dist: float,
    ) -> None:
        """Writes every frame of the overview; leaves the last one in `self.last_frame`."""
        fps = scene.fps
        total_frames = int(math.ceil(timing.end_at * fps))
        state, keep, layer = None, None, None
        frame = route_bg
        heading = _Heading(self._initial_heading(trace.path))

        for i in range(total_frames):
            t = i / fps
            new_state = self._course_plate_state(scene, t)
            if new_state != state:
                state = new_state
                keep, layer = self._course_overlay(scene, state, route_bg)
            frame = self._course_frame(i, t, route_bg, keep, layer, trace, timing, panels, heading, total_smooth_dist)
            video.write(frame)
            if i % fps == 0:
                tracker.show_item(i // fps + 1, f"Rendering course overview {i // fps}/{int(timing.end_at)}s")
        self.last_frame = frame

    def _course_frame(
        self, i: int, t: float, route_bg: np.ndarray, keep: np.ndarray, layer: np.ndarray, trace: _Trace,
        timing: _Timing, panels: _Panels, heading: _Heading, total_smooth_dist: float,
    ) -> np.ndarray:
        frame = route_bg.copy()
        path = trace.path
        dist = distance_at(timing.anchors, t)
        k = int(np.searchsorted(trace.cum, dist))
        head = path[min(k, len(path) - 1)]
        if t >= timing.route_at and k > 0:
            if k < len(path):
                d0, d1 = trace.cum[k - 1], trace.cum[k]
                u = (dist - d0) / max(1e-6, d1 - d0)
                head = path[k - 1] + (path[k] - path[k - 1]) * u
            self._draw_trace_line(frame, trace, k, head)
        blended = cv2.add(cv2.multiply(frame, keep, dtype=cv2.CV_32F), layer)
        frame = np.clip(blended, 0, 255, out=blended).astype(np.uint8)

        tracing = timing.route_at <= t < timing.trace_end + _TRACE_TAIL_SECONDS
        if tracing:
            self._draw_walker(frame, i, t, k, head, trace, timing, heading)
        return self._composite_course_panels(
            frame, i, t, dist, k, timing.route_at <= t < timing.trace_end, trace, timing, panels, total_smooth_dist)

    def _draw_trace_line(self, frame: np.ndarray, trace: _Trace, k: int, head) -> None:
        """The traced part of the route, up to `head`."""
        line = np.array(trace.pts[:k] + [(int(head[0]), int(head[1]))], dtype=np.int32)
        if trace.border:
            cv2.polylines(frame, [line], False, self.graphics.line_border_color,
                          trace.thick + 2 * trace.border, cv2.LINE_AA)
        cv2.polylines(frame, [line], False, trace.color, trace.thick, cv2.LINE_AA)

    def _draw_walker(
        self, frame: np.ndarray, i: int, t: float, k: int, head, trace: _Trace, timing: _Timing,
        heading: _Heading,
    ) -> None:
        """The transport icon at the trace's head; it fades out after the trace is done."""
        modes = trace.modes
        mode = modes[min(max(0, k - 1), len(modes) - 1)]
        head = head if t < timing.trace_end else trace.path[-1]
        fade = 1.0 if t < timing.trace_end else max(0.0, 1.0 - (t - timing.trace_end) / _TRACE_TAIL_SECONDS)
        cx, cy = int(head[0]), int(head[1])
        heading.angle = self._smoothed_heading(heading.angle, cx, cy, heading.x, heading.y)
        heading.x, heading.y = cx, cy

        if fade >= 1.0:
            self.graphics.draw_transport_icon(frame, cx, cy, i, heading.angle, mode)
            return
        overlay = frame.copy()
        self.graphics.draw_transport_icon(overlay, cx, cy, i, heading.angle, mode)
        cv2.addWeighted(overlay, fade, frame, 1.0 - fade, 0, dst=frame)

    def _composite_course_panels(
        self, frame: np.ndarray, i: int, t: float, dist: float, k: int, in_trace: bool, trace: _Trace,
        timing: _Timing, panels: _Panels, total_smooth_dist: float,
    ) -> np.ndarray:
        """Headline, totals, progress rail, stats card and stop-by notices over the frame."""
        margin = panels.margin
        steps = leg_banner(panels.leg_stops, dist) if in_trace else []
        title, title_alpha = tagline_at(panels.taglines, t)
        # The strip holds the tagline whole while a stretch is under it (one swaps for the
        # next rather than dissolving through: the stretch must stay legible), and fades
        # on its own once the trace is done and the card is the strip alone.
        panel = self.graphics.route_headline_panel(title, steps, panels.headline_font)
        if panel is not None:
            frame = self.graphics._composite_pill(
                frame, panel, 1.0 if steps else title_alpha,
                x_from_left=margin, y_from_top=margin)
        if panels.totals is not None:
            frame = self.graphics._composite_pill(
                frame, panels.totals, 1.0, x_from_right=margin, y_from_top=margin)
        if panels.rail_marks:
            frame = self.graphics.render_route_progress_rail(
                frame, dist / max(1e-6, total_smooth_dist), panels.rail_marks, margin=margin,
                mode=trace.modes[min(max(0, k - 1), len(trace.modes) - 1)] if t >= timing.route_at else None,
                frame_count=i)
        if panels.summary_card is not None and t >= timing.stats_at:
            u = _smoothstep((t - timing.stats_at) / tuning.COURSE_STATS_SLIDE_SECONDS)
            frame = self.graphics.composite_card_on_frame(
                frame, panels.summary_card, alpha=u, margin=margin, corner="top_right",
                margin_y=panels.stats_y, slide_offset_y=-(1 - u) * 80)
        if timing.extras_at is not None and t >= timing.extras_at:
            frame = self.graphics.render_stopby_notice(
                frame, alpha=_smoothstep((t - timing.extras_at) / _NOTICE_FADE_SECONDS))
        if timing.closed and timing.closed_at is not None and t >= timing.closed_at:
            frame = self.graphics.render_stopby_notice(
                frame, alpha=_smoothstep((t - timing.closed_at) / _NOTICE_FADE_SECONDS), kind="closed",
                x_offset=panels.closed_offset)
        return frame

    def _course_ending(
        self, video: VideoExporter, w: int, h: int, fps: int, route_bg: np.ndarray, trace: _Trace,
        scene: _Scene, stop_popup: Dict, active_popups: List[Dict], bounding_box: Optional[Dict[str, float]],
    ) -> bool:
        """The walk overview's ending: the GL zoom to the start and its photo. True if it hard-cut out."""
        clean = route_bg.copy()
        whole = np.array(trace.pts, dtype=np.int32)
        if trace.border:
            cv2.polylines(clean, [whole], False, self.graphics.line_border_color,
                          trace.thick + 2 * trace.border, cv2.LINE_AA)
        cv2.polylines(clean, [whole], False, trace.color, trace.thick, cv2.LINE_AA)
        for ap in scene.on_route + scene.extras:
            if id(ap) not in scene.returns:
                scene.draw_marker(clean, ap, scene.total_points)  # the same markers the video just held on
        start_popup = next((ap for ap in active_popups if ap["index"] == 0), None)
        return self._render_ending_highlight(
            video, w, h, fps, stop_popup, start_popup,
            clean_map_frame=clean, bounding_box=bounding_box,
        )

    def _course_hud(self, ap: Dict) -> Dict:
        """A laid-out card as the recap draws it (see _render_recap_frame)."""
        hud = ap.copy()
        hud["hud_corner"] = None
        hud["draw_leader_line"] = not ap.get("suppress_leader_line")
        color = ap.get("recap_line_color") or self.graphics.marker_color
        hud["leader_line_color"] = color
        hud["leader_line_width"] = self._RECAP_LEADER_WIDTH
        hud["border_color"] = color
        return hud

    def _closed_obstacle_points(self, step: float = 8.0) -> np.ndarray:
        """Layout obstacles over each closed place's pin and its name (drawn right of the pin at the end)."""
        closed = getattr(self, "_closed_popups", None) or []
        points = [self._pin_obstacle_points(closed)] if closed else []
        r = int(self.graphics.marker_radius)
        for ap in closed:
            sprite = self._course_label_sprite(ap.get("label") or "")
            if sprite is None:
                continue
            x0, y0 = float(ap["x"]) + r + 6, float(ap["y"]) - sprite.shape[0] / 2
            xs = np.arange(x0, x0 + sprite.shape[1] + step, step)
            ys = np.arange(y0, y0 + sprite.shape[0] + step, step)
            points.append(np.array([(x, y) for x in xs for y in ys], dtype=float))
        return np.vstack(points) if points else np.empty((0, 2), dtype=float)

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
