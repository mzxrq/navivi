"""The "course" overview (settings.overview_style "course"): the whole route is
shown at once, then traced from the start while each stop's photo card pops in
beside it and stays, a stats card slides in with the totals, and the stop-bys
appear last. Timed by the course script's cues: {route} (the trace starts),
{n} (stop n reached; with {go} cues, only {go} stops are timed, at their {go}),
{end} (trace done, stats card) and {extras} (stop-bys).
"""

import math
import tempfile
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
_EXTRAS_TAIL_SECONDS = 1.5  # the last kind's last pin is up at least this long before the end
_RIPPLE_SECONDS = 0.9  # the ring a pin sends out as it comes up
_BADGE_DIM = 0.4  # the walked stops' badges step back to this once the stop-bys come up


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


def tagline_at(taglines: List[str], t: float, hold_from: Optional[float] = None) -> Tuple[str, float]:
    """(tagline, opacity) at `t`: each held COURSE_TAGLINE_SECONDS, fading through. From `hold_from`
    the one then showing stays (once fully in), so the text stops changing over a still map."""
    if not taglines:
        return "", 0.0
    period, fade = tuning.COURSE_TAGLINE_SECONDS, tuning.COURSE_TAGLINE_FADE_SECONDS
    if hold_from is not None and len(taglines) > 1:
        k, local = divmod(max(0.0, hold_from), period)
        if local > period - fade:  # already fading out: hold the next one
            k, local = k + 1, 0.0
        t = min(t, k * period + max(local, fade))
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
    rail_recap_left: Optional[int]  # where the rail starts once the notices are up (None: no notices)


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


def _crop_zoom(frame: np.ndarray, s: float, x0: float, y0: float) -> np.ndarray:
    """The `1/s`-sized crop of `frame` from (x0, y0) scaled back up to the whole frame."""
    h, w = frame.shape[:2]
    m = np.float32([[s, 0, -x0 * s], [0, s, -y0 * s]])
    return cv2.warpAffine(frame, m, (w, h), flags=cv2.INTER_LINEAR)


def zoom_view(
    t: float, zooms: List[Tuple[float, float, float, float, float]], w: int, h: int,
) -> Optional[Tuple[float, float, float]]:
    """(zoom, crop x, crop y) of the camera at `t` in base-frame pixels, or None at the whole map. The opening
    eases out from the route's own framing (the middle 1/COURSE_OPEN_ZOOM of the wider map, see
    overview_framing._widen); later it eases in on each group of stops while the trace runs through it
    (dense_zooms). The GL map is captured at this view, or the base frame is cropped to it (_crop_zoom)."""
    if t < tuning.COURSE_OPEN_ZOOM_SECONDS:
        s = tuning.COURSE_OPEN_ZOOM + (1.0 - tuning.COURSE_OPEN_ZOOM) * _smoothstep(t / tuning.COURSE_OPEN_ZOOM_SECONDS)
        return s, (w - w / s) / 2, (h - h / s) / 2
    ease = tuning.COURSE_DENSE_EASE_SECONDS
    for t_in, t_out, s, x0, y0 in zooms:
        if t_in - ease < t < t_out + ease:
            e = _smoothstep(min((t - t_in + ease) / ease, (t_out + ease - t) / ease, 1.0))
            return 1.0 + (s - 1.0) * e, x0 * e, y0 * e
    return None


def dense_zooms(
    stop_dists: List[float], path: np.ndarray, cum: np.ndarray, anchors: List[Tuple], w: int, h: int,
    max_zoom: float = tuning.COURSE_DENSE_ZOOM_MAX,
) -> List[Tuple[float, float, float, float, float]]:
    """(time in, time out, zoom, crop x, crop y) per tight group of stops along the route: the trace reaches
    the group's first stop at `time in` and its last at `time out`.

    A group is the longest run of stops (in route order) whose stretch of route is at least
    COURSE_DENSE_ZOOM_MIN times smaller than the whole route: measured against the route, not the frame,
    since the course map leaves room around the route for the badges and the whole route would otherwise
    count as one group. Only runs of COURSE_DENSE_MIN_STOPS or more zoom. The view frames the route only:
    a photo card near the edge may be cut while zoomed (fitting the cards too left only ~1.17x, 2026-11-21)."""
    top, bottom = tuning.COURSE_TOP_BAND_FRACTION * h, tuning.COURSE_BOTTOM_BAND_FRACTION * h
    band_h, pad = h - top - bottom, 0.06 * h
    ease = tuning.COURSE_DENSE_EASE_SECONDS

    def fit(d0: float, d1: float) -> Tuple[float, float, float]:
        """(uncapped zoom that fits the stretch d0..d1 in the band; crop x, crop y at the capped zoom)."""
        pts = path[(cum >= d0 - 1e-6) & (cum <= d1 + 1e-6)]
        (x0, y0), (x1, y1) = pts.min(axis=0), pts.max(axis=0)
        s = min(w / (x1 - x0 + 2 * pad), band_h / (y1 - y0 + 2 * pad))
        z = min(s, max_zoom)
        # The group's middle lands mid-band, the crop kept inside the frame.
        cx = min(max((x0 + x1) / 2 - w / (2 * z), 0.0), w - w / z)
        cy = min(max((y0 + y1) / 2 - (top + band_h / 2) / z, 0.0), h - h / z)
        return s, cx, cy

    whole = fit(0.0, float(cum[-1]))[0]
    ds = sorted(stop_dists)
    out: List[Tuple[float, float, float, float, float]] = []
    i = 0
    while i < len(ds):
        j = i
        while j + 1 < len(ds) and fit(ds[i], ds[j + 1])[0] >= whole * tuning.COURSE_DENSE_ZOOM_MIN:
            j += 1
        s, cx, cy = fit(ds[i], ds[j])
        t_in, t_out = _reveal_time(anchors, ds[i]), _reveal_time(anchors, ds[j])
        clear = t_in - ease >= max(tuning.COURSE_OPEN_ZOOM_SECONDS, out[-1][1] + ease if out else 0.0)
        if j - i + 1 >= tuning.COURSE_DENSE_MIN_STOPS and t_out > t_in and clear and s > 1.05:
            out.append((t_in, t_out, min(s, max_zoom), cx, cy))
            i = j + 1
        else:
            i += 1
    return out


def hold_zooms_for_cards(
    zooms: List[Tuple[float, float, float, float, float]], cards: List[Tuple[float, float]],
) -> List[Tuple[float, float, float, float, float]]:
    """`zooms` with each one held until the last photo card popped inside it has been shown in full (`cards` =
    (popped at, shown until)), so the camera zooms out after the card, not while it collapses. Never into the
    next zoom's own ease."""
    ease = tuning.COURSE_DENSE_EASE_SECONDS
    out = []
    for n, (t_in, t_out, *rest) in enumerate(zooms):
        t_end = max([t_out] + [until for at, until in cards if t_in <= at <= t_out + ease])
        if n + 1 < len(zooms):
            t_end = min(t_end, zooms[n + 1][0] - 2 * ease)
        out.append((t_in, max(t_out, t_end), *rest))
    return out


def release_zooms_before_exit(
    zooms: List[Tuple[float, float, float, float, float]], path: np.ndarray, cum: np.ndarray, anchors: List[Tuple],
    w: int, h: int, margin: float = 90.0,
) -> List[Tuple[float, float, float, float, float]]:
    """`zooms` with each one let go early enough that its zoom-out is done before the trace head (a ferry
    leaving the pier) leaves the zoomed view, but never before the group's last stop is reached."""
    ease = tuning.COURSE_DENSE_EASE_SECONDS
    out = []
    for t_in, t_out, s, x0, y0 in zooms:
        t, t_exit = t_out, None
        while t < anchors[-1][0]:
            d = distance_at(anchors, t)
            x, y = np.interp(d, cum, path[:, 0]), np.interp(d, cum, path[:, 1])
            if not (x0 + margin <= x <= x0 + w / s - margin and y0 + margin <= y <= y0 + h / s - margin):
                t_exit = t
                break
            t += 1 / 30
        out.append((t_in, t_out if t_exit is None else min(t_out, max(t_in, t_exit - ease)), s, x0, y0))
    return out


def pass_crowd_scales(spans: List[Tuple[float, float]], full: float) -> List[float]:
    """One card scale per (shown from, shown until) span, in time order: cards whose spans chain into each other
    are one crowd, all the same size, `full` shrunk by the square root of the most of them up at once (at least
    COURSE_PASS_CARD_CROWD_MIN_SCALE of it). A card on its own keeps `full`."""
    out: List[float] = []
    i = 0
    while i < len(spans):
        j, end = i, spans[i][1]
        while j + 1 < len(spans) and spans[j + 1][0] < end:
            j += 1
            end = max(end, spans[j][1])
        crowd = spans[i:j + 1]
        most = max(sum(1 for a, b in crowd if a <= at < b) for at, _ in crowd)
        out += [full * max(tuning.COURSE_PASS_CARD_CROWD_MIN_SCALE, most ** -0.5)] * len(crowd)
        i = j + 1
    return out


def _view_key(view: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """A view rounded finer than a pixel: frames holding one view share one capture."""
    return round(view[0], 4), round(view[1], 1), round(view[2], 1)


def gl_view_state(
    view: Tuple[float, float, float], extent: Tuple[float, float, float, float], base_zoom: float, w: int, h: int,
) -> Tuple[float, float, float]:
    """The deck.gl (longitude, latitude, zoom) that shows the crop `view` of the base frame, whose Web
    Mercator `extent` (min_x, max_x, min_y, max_y) is drawn at `base_zoom` (pydeck_overview.compute_pydeck_view)."""
    from services.mapfetcher.mapgeometry import EARTH_RADIUS_METERS, _inverse_mercator_y

    s, x0, y0 = view
    min_x, max_x, min_y, max_y = extent
    cx, cy = x0 + w / (2 * s), y0 + h / (2 * s)
    mx = min_x + cx / w * (max_x - min_x)
    my = max_y - cy / h * (max_y - min_y)
    return math.degrees(mx / EARTH_RADIUS_METERS), _inverse_mercator_y(my), base_zoom + math.log2(s)


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
    # Each kind's pins come one at a time across their own sentence (to the next kind's cue, or the end),
    # so the still map after the trace keeps moving with the voice instead of popping all at once.
    spans = ((timing.stopbys, timing.extras_at, timing.closed_at), (timing.closed, timing.closed_at, None))
    for group, at, until in spans:
        start = at if at is not None else timing.end_at
        room = max(0.0, (until if until is not None else timing.end_at - _EXTRAS_TAIL_SECONDS) - start)
        step = min(tuning.COURSE_STOPBY_MAX_STEP_SECONDS,
                   max(tuning.COURSE_STOPBY_STAGGER_SECONDS, room * 0.8 / max(1, len(group))))
        for k, ap in enumerate(group):
            ap["course_at"] = start + k * step
            ap["pop_frame"] = int(round(ap["course_at"] * fps))


def _log_timing(timing: _Timing, cards: int) -> None:
    logger.info(
        "Course overview: %.1fs (route from %.1fs, traced by %.1fs, stats at %.1fs%s); %d card(s).",
        timing.end_at, timing.route_at, timing.trace_end, timing.stats_at,
        f", stop-bys at {timing.extras_at:.1f}s" if timing.extras_at is not None else "", cards,
    )


def _pin_head_box(graphics, px: float, py: float) -> Tuple[float, float, float, float]:
    """The box a stop's teardrop covers: its head stands above the point (as popups._recap_cards_pin_cover)."""
    r = float(graphics.marker_radius)
    return px - 1.2 * r, py - 3.0 * r, px + 1.2 * r, py + 0.5 * r


def _badge_box(graphics, ap: Dict) -> Tuple[float, float, float, float]:
    """The box a laid-out pill badge covers."""
    bx, by = ap["beside_box"]
    bw, bh = graphics.beside_card_footprint(is_pill_badge=True, pill_name_chars=len(str(ap.get("label") or "")))
    return (bx, by, bx + bw, by + bh)


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
        # The drawn path resampled every few px: a ferry leg is one long segment whose raw points are
        # only its ends, so a badge or card on the middle of it counted as covering no route.
        dense = np.column_stack([np.interp(np.arange(0.0, total, 6.0), cum, path[:, i]) for i in (0, 1)])
        obstacles = dense if route_obstacle_arr is None or not len(route_obstacle_arr) else np.vstack(
            [dense, route_obstacle_arr])
        pill_recap, laid_out, cards = self._course_cards(
            on_route, extras, returns, stop_popup, panels.reserved, obstacles, current_bg, w, h)
        _set_reveal_times(on_route, stop_popup, cues, timing, fps)
        if pill_recap:
            self._course_pass_cards(laid_out, on_route, panels.reserved, obstacles, w, h)
        from services.mapbox_token import resolve_mapbox_token

        gl = bounding_box is not None and bool(resolve_mapbox_token((self._get_job_config() or {}).get("settings")))
        self._course_zooms = dense_zooms(
            [ap["course_dist"] for ap in on_route], path, cum, timing.anchors, w, h,
            tuning.COURSE_DENSE_ZOOM_MAX_GL if gl else tuning.COURSE_DENSE_ZOOM_MAX)
        self._course_zooms = hold_zooms_for_cards(
            self._course_zooms, [(ap["course_at"], ap["pass_until"]) for ap in laid_out if "pass_until" in ap])
        self._course_zooms = release_zooms_before_exit(self._course_zooms, path, cum, timing.anchors, w, h)

        route_bg, trace = self._course_route_plate(current_bg, path, cum, modes)
        labels, label_at = self._course_extra_labels(extras, cards, laid_out, on_route, w, h)
        # Every stop its numbered teardrop: most badges sit away from their pins here (badge_far), and
        # a plain dot for the few beside theirs (the start, a lone stop) read as a missing pin.
        draw_marker = self._draw_pin
        scene = _Scene(on_route, extras, laid_out, cards, returns, labels, label_at, total_points, fps, draw_marker)

        _log_timing(timing, len(laid_out))
        views = [v for i in range(int(math.ceil(timing.end_at * fps)))
                 if (v := zoom_view(i / fps, self._course_zooms, w, h)) is not None]
        with tempfile.TemporaryDirectory(prefix="navivi_course_zoom_") as gl_dir:
            self._course_gl = self._course_gl_frames(views, bounding_box, w, h, gl_dir)
            self._zoom_card_sides = {}
            video = VideoExporter(overview_path, w, h, fps)
            tracker.begin_substeps(max(1, int(timing.end_at)))
            self._course_play(video, scene, route_bg, trace, timing, panels, total_smooth_dist)
            self._course_gl = {}

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
            # Always the discs-and-chips template: the corners already hold the headline and the totals
            # chip, and a third accent panel there was one too many (summary_card_style is the walk's).
            summary_card = self.graphics.create_summary_card_circles(
                distance_km=summary.get("total_distance_km", 0.0),
                duration_seconds=summary.get("total_duration_seconds", 0.0),
                mode_breakdown=summary.get("mode_breakdown"),
                mode_duration=summary.get("mode_duration"),
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
        before = len(reserved)
        closed_offset = self._reserve_notices(reserved, timing, w, h)
        notices = reserved[before:]
        rail_recap_left = int(max(b[2] for b in notices) + 24 * h / 1080) if notices else None
        return _Panels(summary_card, taglines, leg_stops, headline_font, margin, totals, stats_y,
                       rail_marks, closed_offset, reserved, rail_recap_left)

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
                                            total_points=stop_popup["index"] + 1 if stop_popup else None,
                                            clutter_pull=self._CLUTTER_PULL_COURSE_PX)
        return pill_recap, laid_out, {ap["index"]: ap for ap in laid_out}

    def _course_pass_cards(
        self, laid_out: List[Dict], on_route: List[Dict], reserved: List, route_obstacle_arr: np.ndarray,
        w: int, h: int,
    ) -> None:
        """Stamps `pass_box`, `pass_scale` and `pass_until` on each on-route stop's badge: its photo card
        pops up as the trace passes the stop, right beside its pin (clear of the frame's panels and any card
        still showing first, then of every stop's pin, its own included, then as near its pin as it can, then of
        as much route as it can, then of the badges already up - it only covers one for a moment), and shrinks
        into the badge at `pass_until`. A card gives way early to the next stop's, though it stays up at least
        COURSE_PASS_CARD_MIN_SECONDS; where stops come faster than that, the cards up together are one crowd,
        all one size (pass_crowd_scales) so they fit side by side."""
        on_route_ids = {id(ap) for ap in on_route}
        passing = sorted((ap for ap in laid_out if id(ap) in on_route_ids), key=lambda ap: ap["course_at"])
        untils = []
        for k, ap in enumerate(passing):
            until = ap["course_at"] + tuning.COURSE_PASS_CARD_SECONDS
            if k + 1 < len(passing):
                until = min(until, passing[k + 1]["course_at"])
            untils.append(max(until, ap["course_at"] + tuning.COURSE_PASS_CARD_MIN_SECONDS))
        scales = pass_crowd_scales(
            [(ap["course_at"], u + tuning.COURSE_PASS_CARD_SHRINK_SECONDS) for ap, u in zip(passing, untils)],
            tuning.COURSE_PASS_CARD_SCALE * h / 1080)
        gap = int(self.graphics.marker_radius) + 8
        route = route_obstacle_arr if route_obstacle_arr is not None and len(route_obstacle_arr) else None
        pins = [_pin_head_box(self.graphics, s.get("pin_x", s["x"]), s.get("pin_y", s["y"])) for s in on_route]
        up: List[Tuple[float, Tuple[float, float, float, float]]] = []
        for ap, until, scale in zip(passing, untils, scales):
            at = ap["course_at"]
            up = [(end, box) for end, box in up if end > at]
            card_w, card_h = self.graphics.beside_card_footprint(scale)
            hard = list(reserved) + [box for _, box in up]
            badges = [_badge_box(self.graphics, b) for b in laid_out
                      if b is not ap and b.get("beside_box") and b.get("course_at", 0.0) < at]
            px, py = ap.get("pin_x", ap["x"]), ap.get("pin_y", ap["y"])
            near = self._pass_card_spots(px, py, card_w, card_h, w, h)
            corners = len(self._CARD_SPILL_CORNERS)
            further = list(self._card_box_candidates(px - gap, py - gap, 2 * gap, 2 * gap, card_w, card_h, w, h))[corners:]
            best = None
            for n, (x, y) in enumerate(near + further):
                def hits(boxes):
                    return sum(1 for b in boxes if x < b[2] and b[0] < x + card_w and y < b[3] and b[1] < y + card_h)
                covered = 0 if route is None else int(np.count_nonzero(
                    (route[:, 0] >= x) & (route[:, 0] <= x + card_w) & (route[:, 1] >= y) & (route[:, 1] <= y + card_h)))
                # Every pin stays in sight (its own included: the old corner spots all sat on it); then a spot
                # beside its pin beats any further out (a card across the water read as no stop's); then the least
                # route covered (the trace runs under it only briefly).
                ring = 0 if n < len(near) else 1 + (n - len(near)) // self._CARD_SPILL_PER_RING
                score = (hits(hard), hits(pins), ring, covered, hits(badges))
                if best is None or score < best[0]:
                    best = (score, x, y)
            _, x, y = best
            ap.update(pass_box=(int(x), int(y)), pass_scale=scale, pass_until=until)
            up.append((until + tuning.COURSE_PASS_CARD_SHRINK_SECONDS, (x, y, x + card_w, y + card_h)))

    def _pass_card_spots(self, px: float, py: float, card_w: int, card_h: int, w: int, h: int) -> List[Tuple[int, int]]:
        """The eight spots right around a pin's teardrop for a card of card_w x card_h: beside, above, below and
        at the diagonals, each just clear of the teardrop, kept in the frame."""
        from .popups import _card_bottom_limit

        x0, y0, x1, y1 = _pin_head_box(self.graphics, px, py)
        g, margin = 8, self._RECAP_CARD_MARGIN
        max_x, max_y = max(margin, w - card_w - margin), max(margin, _card_bottom_limit(h, margin) - card_h)
        xs = {"right": x1 + g, "left": x0 - g - card_w, "mid": px - card_w / 2}
        ys = {"above": y0 - g - card_h, "below": y1 + g, "mid": py - card_h / 2}
        order = [("right", "mid"), ("left", "mid"), ("mid", "above"), ("mid", "below"),
                 ("right", "above"), ("left", "above"), ("right", "below"), ("left", "below")]
        return [(int(min(max(xs[a], margin), max_x)), int(min(max(ys[b], margin), max_y))) for a, b in order]

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

    def _course_plate_state(self, scene: _Scene, t: float, extras_at: Optional[float] = None):
        """What is on the cards-and-pins layer at `t`; the layer is only rebuilt when this changes.
        A badge with a passing card (`pass_until`) shows the card first and fades in as it shrinks.
        From `extras_at` the walked stops' badges fade back to _BADGE_DIM."""
        pop, shrink = tuning.COURSE_CARD_POP_SECONDS, tuning.COURSE_PASS_CARD_SHRINK_SECONDS
        shown, anim, passing = [], [], []
        for ap in scene.laid_out:
            age = t - ap["course_at"]
            until = ap.get("pass_until")
            if age < 0:
                continue
            if until is None:
                shown.append(ap["index"])
                if age < pop:
                    anim.append((ap["index"], round(age / pop, 2)))
            elif t < until:
                passing.append((ap["index"], 0, round(min(1.0, age / pop), 2)))
            else:
                shown.append(ap["index"])
                if t < until + shrink:
                    v = round((t - until) / shrink, 2)
                    passing.append((ap["index"], 1, v))
                    anim.append((ap["index"], v))
        bumps = tuple(
            (ap["index"], round((t - ap["course_at"]) / pop, 2))
            for ap in scene.on_route if 0 <= t - ap["course_at"] < pop
        )
        arrived = tuple(ap["index"] for ap in scene.on_route if t >= ap["course_at"])
        extra_on = tuple(
            (ap["index"], round(self._pin_pop_scale(ap, int(round(t * scene.fps)), scene.fps), 2))
            for ap in scene.extras if t >= ap["course_at"]
        )
        dim = 1.0 if extras_at is None or t < extras_at else round(
            1.0 - (1.0 - _BADGE_DIM) * _smoothstep((t - extras_at) / _NOTICE_FADE_SECONDS), 2)
        return tuple(shown), tuple(anim), bumps, arrived, extra_on, tuple(passing), dim

    def _course_pass_hud(self, ap: Dict, shrinking: bool, u: float) -> Tuple[Dict, float]:
        """(hud, alpha) of a stop's passing photo card: growing in at its spot (u 0..1), or shrinking
        from there into its badge's (u 0..1, fading as it goes)."""
        hud = self._course_hud(ap)
        hud.update(is_pill_badge=False, draw_leader_line=False)
        scale = float(ap["pass_scale"])
        (cx, cy), e = ap["pass_box"], _smoothstep(u)
        if shrinking:
            bx, by = ap["beside_box"]
            now = scale * (1 - 0.6 * e)
            hud.update(card_scale=now, beside_box=(int(cx + (bx - cx) * e), int(cy + (by - cy) * e)))
            return hud, 1 - e
        grow = 0.88 + 0.12 * e
        full_w, full_h = self.graphics.beside_card_footprint(scale)
        now_w, now_h = self.graphics.beside_card_footprint(scale * grow)
        hud.update(card_scale=scale * grow,
                   beside_box=(int(cx + (full_w - now_w) / 2), int(cy + (full_h - now_h) / 2 + 14 * (1 - e))))
        return hud, e

    def _course_layer(self, scene: _Scene, state, base: np.ndarray) -> np.ndarray:
        """The cards and pins drawn over `base`."""
        shown, anim, bumps, arrived, extra_on, passing, dim = state
        alpha = dict(anim)
        walked = {ap["index"] for ap in scene.on_route}
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
            fade = dim if hud["index"] in walked else 1.0
            plate = self.graphics.render_popup_box(
                plate, hud, alpha=_smoothstep(a if a is not None else 1.0) * fade, skip_line=True)
        for ap in scene.extras:  # above the cards, should no side be free
            if id(ap) in scene.label_at and scales.get(ap["index"], 0.0) >= 0.99:
                self.graphics.blit_sprite(plate, scene.labels[id(ap)], (0, 0), *scene.label_at[id(ap)])
        for index, shrinking, u in passing:  # the passing photo cards, over everything
            hud, a = self._course_pass_hud(scene.cards[index], bool(shrinking), u)
            plate = self.graphics.render_popup_box(plate, hud, alpha=a, skip_line=True)
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

    def _course_ripples(self, scene: _Scene, timing: _Timing) -> List[Tuple[float, int, int, Tuple]]:
        """(time, x, y, color) of each ring: every stop-by and closed place as it comes up, and the start as
        the stats come in (the voice says there the course ends where it began)."""
        out = []
        starts = [ap for ap in scene.on_route if ap["index"] == 0]
        for at, ap in [(timing.stats_at, ap) for ap in starts] + [(ap["course_at"], ap) for ap in scene.extras]:
            _, color, _ = self._pin_label_and_color(ap, scene.total_points)
            out.append((float(at), int(ap.get("pin_x", ap["x"])), int(ap.get("pin_y", ap["y"])),
                        tuple(color or self.graphics.marker_color)[:3]))
        return out

    def _draw_ripple(self, frame: np.ndarray, x: int, y: int, color: Tuple, u: float) -> None:
        """One ring growing out of a pin and fading, `u` 0..1 through it."""
        r = int(self.graphics.marker_radius * (0.6 + 2.4 * _smoothstep(u)))
        pad = r + 4
        x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(frame.shape[1], x + pad), min(frame.shape[0], y + pad)
        if x1 <= x0 or y1 <= y0:
            return
        patch = frame[y0:y1, x0:x1]
        ring = patch.copy()
        cv2.circle(ring, (x - x0, y - y0), r, color, 3, cv2.LINE_AA)
        cv2.addWeighted(ring, 1.0 - u, patch, u, 0, dst=patch)

    def _course_gl_frames(
        self, views: List[Tuple[float, float, float]], bounding_box: Optional[Dict[str, float]],
        w: int, h: int, out_dir: str,
    ) -> Dict[Tuple[float, float, float], str]:
        """The GL map (no route, no pins) captured at each zoomed view, saved under `out_dir`: {view key: file}.
        Empty with no Mapbox key or when the capture fails; the zoom then crops the base frame instead."""
        import os

        from services.mapbox_token import resolve_mapbox_token
        from services.mapfetcher.maplanguage import resolve_map_style
        from services.mapfetcher.pydeck_overview import _capture_zoom_raw, compute_pydeck_view

        settings = (self._get_job_config() or {}).get("settings", {}) or {}
        key = resolve_mapbox_token(settings)
        keys = sorted({_view_key(v) for v in views})
        if not keys or not key or bounding_box is None:
            return {}
        lon, lat, zoom, extent = compute_pydeck_view(bounding_box, (w, h))
        states = [gl_view_state(k, extent, zoom, w, h) for k in keys]

        class _ToDisk:
            """Each 2x capture shrunk to the frame and saved as it arrives (all of them in memory ran to GBs)."""
            def __init__(self):
                self.paths: List[str] = []

            def append(self, png: bytes) -> None:
                img = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_COLOR)
                path = os.path.join(out_dir, f"{len(self.paths):04d}.jpg")
                cv2.imwrite(path, cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA), [cv2.IMWRITE_JPEG_QUALITY, 95])
                self.paths.append(path)

        sink = _ToDisk()
        tracker.show(f"Capturing the zoomed map ({len(keys)} views)...")
        try:
            _capture_zoom_raw((lon, lat, zoom), (w, h), states, resolve_map_style(settings, "mapbox/streets-v12"),
                              key, sink=sink)
        except Exception as exc:
            logger.warning("Course overview: the GL zoom could not be captured (%s); cropping the map instead.", exc)
            return {}
        return dict(zip(keys, sink.paths)) if len(sink.paths) == len(keys) else {}

    def _zoom_card_side(
        self, card: Dict, scene: _Scene, t: float, view: Tuple[float, float, float], reserved,
        cw: int, ch: int, w: int, h: int,
    ) -> int:
        """Which of _pass_card_spots a card takes while zoomed: the first clear of the panels, then of every pin,
        at the zoom's closest view (kept for the whole zoom, so the card follows its pin without jumping)."""
        ease = tuning.COURSE_DENSE_EASE_SECONDS
        hold = next(((s, x0, y0) for t_in, t_out, s, x0, y0 in getattr(self, "_course_zooms", ())
                     if t_in - ease < t < t_out + ease), view)
        cache = self.__dict__.setdefault("_zoom_card_sides", {})
        key = (card["index"], hold)
        if key not in cache:
            s, x0, y0 = hold

            def at(x: float, y: float) -> Tuple[float, float]:
                return (x - x0) * s, (y - y0) * s

            pins = [_pin_head_box(self.graphics, *at(p.get("pin_x", p["x"]), p.get("pin_y", p["y"])))
                    for p in scene.on_route]
            spots = self._pass_card_spots(*at(card.get("pin_x", card["x"]), card.get("pin_y", card["y"])), cw, ch, w, h)

            def hits(boxes, x, y):
                return sum(1 for b in boxes if x < b[2] and b[0] < x + cw and y < b[3] and b[1] < y + ch)

            # [NOTE] [Course] Cards up together must not overlap: each keeps off the earlier ones still showing when it
            # pops up (they were placed first, so this never loops), the way _course_pass_cards does on the whole map.
            shrink = tuning.COURSE_PASS_CARD_SHRINK_SECONDS
            start = card.get("course_at", 0.0)
            cards = []
            for other in scene.cards.values():
                if other is card or not other.get("pass_box"):
                    continue
                if not (other.get("course_at", 0.0) < start < other["pass_until"] + shrink):
                    continue
                ow, oh = self.graphics.beside_card_footprint(float(other["pass_scale"]))
                side = self._zoom_card_side(other, scene, t, view, reserved, ow, oh, w, h)
                ox, oy = self._pass_card_spots(*at(other.get("pin_x", other["x"]), other.get("pin_y", other["y"])), ow, oh, w, h)[side]
                cards.append((ox, oy, ox + ow, oy + oh))

            cache[key] = min(
                range(len(spots)), key=lambda n: (hits(reserved, *spots[n]), hits(cards, *spots[n]), hits(pins, *spots[n]), n)
            )
        return cache[key]

    def _course_zoomed_map(
        self, i: int, t: float, view: Tuple[float, float, float], gl_bg: np.ndarray, scene: _Scene, state,
        trace: _Trace, timing: _Timing, heading: _Heading, k: int, head, reserved=(),
    ) -> np.ndarray:
        """The map layer of a zoomed frame, drawn on the GL map at `view` instead of cropped from the base frame:
        the route, trace, pins and walker at their zoomed places but their own size, the photo cards their usual
        size beside their pin and kept on screen, and the badges (laid out for the whole map) faded out."""
        s, x0, y0 = view
        h, w = gl_bg.shape[:2]

        def at(x: float, y: float) -> Tuple[int, int]:
            return int(round((x - x0) * s)), int(round((y - y0) * s))

        def moved(ap: Dict) -> Dict:
            out = dict(ap)
            out["x"], out["y"] = at(ap["x"], ap["y"])
            if "pin_x" in ap:
                out["pin_x"], out["pin_y"] = at(ap["pin_x"], ap["pin_y"])
            return out

        frame = gl_bg.copy()
        path = (trace.path - np.array([x0, y0])) * s
        zoomed = trace._replace(path=path, pts=[(int(x), int(y)) for x, y in path])
        self.graphics.draw_path(frame, zoomed.pts, trace.modes)
        head_at = np.array(at(*head), dtype=float)
        if t >= timing.route_at and k > 0:
            self._draw_trace_line(frame, zoomed, k, head_at)

        shown, _anim, bumps, arrived, extra_on, passing, dim = state
        badge_alpha = max(0.0, 1.0 - (s - 1.0) / 0.15) * dim
        if badge_alpha > 0:
            for index in shown:
                frame = self.graphics.render_popup_box(frame, self._course_hud(scene.cards[index]), alpha=badge_alpha)
        bump = dict(bumps)
        for ap in scene.on_route:
            ap["data"]["arrived"] = ap["index"] in arrived
            if id(ap) not in scene.returns:
                u = bump.get(ap["index"])
                scene.draw_marker(frame, moved(ap), scene.total_points,
                                  scale=1.0 + 0.3 * math.sin(math.pi * u) if u is not None else 1.0)
        for index, scale in extra_on:
            ap = next(a for a in scene.extras if a["index"] == index)
            scene.draw_marker(frame, moved(ap), scene.total_points, scale=scale)
        for index, shrinking, u in passing:
            card = scene.cards[index]
            hud, a = self._course_pass_hud(card, bool(shrinking), u)
            # Its usual size, on the side of its pin that is clear in the ZOOMED layout (the whole-map spot
            # landed on other pins once they spread apart), moved as it grows in or shrinks away as usual.
            px, py = card.get("pin_x", card["x"]), card.get("pin_y", card["y"])
            cw, ch = self.graphics.beside_card_footprint(float(card["pass_scale"]))
            side = self._zoom_card_side(card, scene, t, view, reserved, cw, ch, w, h)
            sx, sy = self._pass_card_spots(*at(px, py), cw, ch, w, h)[side]
            (bx, by), (cx0, cy0) = hud["beside_box"], card["pass_box"]
            frame = self.graphics.render_popup_box(
                frame, dict(hud, beside_box=(int(sx + bx - cx0), int(sy + by - cy0))), alpha=a, skip_line=True)

        if timing.route_at <= t < timing.trace_end + _TRACE_TAIL_SECONDS:
            self._draw_walker(frame, i, t, k, head_at, zoomed, timing, heading)
        return frame

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
        ripples = self._course_ripples(scene, timing)
        gl_last = (None, None)  # (path, image) of the GL map view last read

        for i in range(total_frames):
            t = i / fps
            new_state = self._course_plate_state(scene, t, timing.extras_at)
            if new_state != state:
                state = new_state
                keep, layer = self._course_overlay(scene, state, route_bg)
            view = zoom_view(t, getattr(self, "_course_zooms", ()), *route_bg.shape[1::-1])
            gl_path = getattr(self, "_course_gl", {}).get(_view_key(view)) if view else None
            if gl_path and gl_path != gl_last[0]:  # frames holding one view share its image
                gl_last = (gl_path, cv2.imread(gl_path))
            zoomed = (view, gl_last[1], scene, state, panels.reserved) if gl_path else None
            frame = self._course_frame(
                i, t, route_bg, keep, layer, trace, timing, panels, heading, total_smooth_dist, view, zoomed)
            for at, x, y, color in ripples:
                if 0 <= t - at < _RIPPLE_SECONDS:
                    self._draw_ripple(frame, x, y, color, (t - at) / _RIPPLE_SECONDS)
            video.write(frame)
            if i % fps == 0:
                tracker.show_item(i // fps + 1, f"Rendering course overview {i // fps}/{int(timing.end_at)}s")
        self.last_frame = frame

    def _course_frame(
        self, i: int, t: float, route_bg: np.ndarray, keep: np.ndarray, layer: np.ndarray, trace: _Trace,
        timing: _Timing, panels: _Panels, heading: _Heading, total_smooth_dist: float,
        view: Optional[Tuple[float, float, float]] = None, zoomed=None,
    ) -> np.ndarray:
        """One frame: the map layer, then the panels. At a zoomed `view`, `zoomed` (view, GL map, scene, plate
        state) redraws the map layer on the real map there; without it the whole-map layer is cropped to `view`."""
        path = trace.path
        dist = distance_at(timing.anchors, t)
        k = int(np.searchsorted(trace.cum, dist))
        head = path[min(k, len(path) - 1)]
        if t >= timing.route_at and 0 < k < len(path):
            d0, d1 = trace.cum[k - 1], trace.cum[k]
            u = (dist - d0) / max(1e-6, d1 - d0)
            head = path[k - 1] + (path[k] - path[k - 1]) * u
        if zoomed is not None:
            gl_view, gl_bg, scene, state, reserved = zoomed
            frame = self._course_zoomed_map(
                i, t, gl_view, gl_bg, scene, state, trace, timing, heading, k, head, reserved)
        else:
            frame = route_bg.copy()
            if t >= timing.route_at and k > 0:
                self._draw_trace_line(frame, trace, k, head)
            blended = cv2.add(cv2.multiply(frame, keep, dtype=cv2.CV_32F), layer)
            frame = np.clip(blended, 0, 255, out=blended).astype(np.uint8)
            if timing.route_at <= t < timing.trace_end + _TRACE_TAIL_SECONDS:
                self._draw_walker(frame, i, t, k, head, trace, timing, heading)
            if view is not None:
                frame = _crop_zoom(frame, *view)
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
        title, title_alpha = tagline_at(panels.taglines, t, hold_from=timing.trace_end)
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
                frame_count=i, left=self._course_rail_left(t, timing, panels))
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

    @staticmethod
    def _course_rail_left(t: float, timing: _Timing, panels: _Panels) -> Optional[int]:
        """Where the rail starts at `t`: the margin, until the stop-by / closed notices come up at the
        bottom left; then it shrinks, as they fade in, to the room right of them."""
        if panels.rail_recap_left is None:
            return None
        starts = [at for at in (timing.extras_at, timing.closed_at if timing.closed else None) if at is not None]
        if not starts or t < min(starts):
            return None
        u = _smoothstep((t - min(starts)) / _NOTICE_FADE_SECONDS)
        return int(round(panels.margin + (panels.rail_recap_left - panels.margin) * u))

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
