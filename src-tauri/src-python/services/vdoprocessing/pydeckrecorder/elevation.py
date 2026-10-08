"""Steepness colouring for the route line in the video.

[NOTE] [Heatmap] Mirrors src/utils/elevation.ts on purpose (same smoothing window, slope span, cap and colour
ramp) so the video's gradient matches the editor's. Pure functions, no I/O: the app writes each track point's
elevation into raw_track.gpx (GPSBabel's csv keeps it as `height`), the pipeline hands a leg's heights in and the
renderer asks for one colour per segment.
"""

import math
from typing import List, Optional, Sequence

SMOOTH_WINDOW_M = 60.0
SLOPE_SPAN_M = 60.0
SLOPE_CAP_PCT = 40.0
# GPSBabel rounds to whole metres; a leg that varies less than this has no elevation worth colouring
# (the app writes a constant 35 m when it has none).
MIN_RELIEF_M = 1.0

# percent slope -> colour (blue downhill, green flat, red uphill)
GRADIENT_STOPS = [
    (-10.0, "#2563eb"),
    (-5.0, "#06b6d4"),
    (0.0, "#10b981"),
    (5.0, "#f97316"),
    (10.0, "#ef4444"),
]

_EARTH_M = 6371008.8


def _rgb(hex_color: str) -> List[int]:
    return [int(hex_color[i:i + 2], 16) for i in (1, 3, 5)]


def distance_m(a: Sequence[float], b: Sequence[float]) -> float:
    """Haversine distance between two (lat, lon) points."""
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_M * math.asin(min(1.0, math.sqrt(h)))


def cumulative_m(latlon: Sequence[Sequence[float]]) -> List[float]:
    out = [0.0]
    for i in range(1, len(latlon)):
        out.append(out[-1] + distance_m(latlon[i - 1], latlon[i]))
    return out


def gradient_color(pct: Optional[float]) -> List[int]:
    """[r, g, b] for a percent slope; the flat colour when the slope is unknown."""
    if pct is None or not math.isfinite(pct):
        pct = 0.0
    if pct <= GRADIENT_STOPS[0][0]:
        return _rgb(GRADIENT_STOPS[0][1])
    if pct >= GRADIENT_STOPS[-1][0]:
        return _rgb(GRADIENT_STOPS[-1][1])
    for i in range(1, len(GRADIENT_STOPS)):
        hi_pct, hi_color = GRADIENT_STOPS[i]
        if pct > hi_pct:
            continue
        lo_pct, lo_color = GRADIENT_STOPS[i - 1]
        f = (pct - lo_pct) / (hi_pct - lo_pct)
        a, b = _rgb(lo_color), _rgb(hi_color)
        return [int(round(a[k] + (b[k] - a[k]) * f)) for k in range(3)]
    return _rgb(GRADIENT_STOPS[-1][1])


def fill_gaps(ele: Sequence[Optional[float]]) -> Optional[List[float]]:
    """Unknown values: linear between known neighbours, flat beyond the ends. None when nothing is known."""
    known = [
        float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None
        for v in ele
    ]
    idx = [i for i, v in enumerate(known) if v is not None]
    if not idx:
        return None
    out: List[float] = [0.0] * len(known)
    k = 0
    for i in range(len(known)):
        if known[i] is not None:
            out[i] = known[i]
            continue
        while k < len(idx) and idx[k] < i:
            k += 1
        nxt = idx[k] if k < len(idx) else None
        prv = idx[k - 1] if k > 0 else None
        if prv is None:
            out[i] = known[nxt]
        elif nxt is None:
            out[i] = known[prv]
        else:
            out[i] = known[prv] + (known[nxt] - known[prv]) * ((i - prv) / (nxt - prv))
    return out


def smooth(dist: Sequence[float], ele: Sequence[float], window_m: float = SMOOTH_WINDOW_M) -> List[float]:
    """Moving average over a distance window; the window shrinks toward the ends."""
    n = len(ele)
    if n < 3 or window_m <= 0:
        return list(ele)
    half = window_m / 2
    end = dist[n - 1]
    out = [0.0] * n
    lo = hi = 0
    total = 0.0
    for i in range(n):
        w = min(half, dist[i] - dist[0], end - dist[i])
        while hi < n and dist[hi] <= dist[i] + w:
            total += ele[hi]
            hi += 1
        while lo < n and dist[lo] < dist[i] - w:
            total -= ele[lo]
            lo += 1
        out[i] = total / (hi - lo)
    return out


def segment_gradients(dist: Sequence[float], ele: Sequence[float], span_m: float = SLOPE_SPAN_M) -> List[float]:
    """Percent slope of segment i->i+1, measured over at least `span_m` so near-duplicate points do not spike."""
    n = len(ele)
    out: List[float] = []
    for i in range(n - 1):
        a, b = i, i + 1
        while dist[b] - dist[a] < span_m and (a > 0 or b < n - 1):
            if a > 0:
                a -= 1
            if dist[b] - dist[a] >= span_m:
                break
            if b < n - 1:
                b += 1
        run = dist[b] - dist[a]
        pct = (ele[b] - ele[a]) / run * 100 if run > 0 else 0.0
        out.append(max(-SLOPE_CAP_PCT, min(SLOPE_CAP_PCT, pct)))
    return out


def usable_heights(heights: Optional[Sequence[Optional[float]]], count: int) -> Optional[List[float]]:
    """A leg's per-point heights if they line up with its `count` points and actually vary, else None."""
    if heights is None or len(heights) != count or count < 2:
        return None
    filled = fill_gaps(heights)
    if filled is None or max(filled) - min(filled) < MIN_RELIEF_M:
        return None
    return filled


def leg_segment_colors(latlon: Sequence[Sequence[float]], ele: Optional[Sequence[float]],
                       alpha: int = 255) -> Optional[List[List[int]]]:
    """[r, g, b, alpha] per segment (len(latlon) - 1 entries), or None when the leg has no usable elevation."""
    if ele is None or len(latlon) < 2 or len(ele) != len(latlon):
        return None
    dist = cumulative_m(latlon)
    pct = segment_gradients(dist, smooth(dist, ele))
    return [gradient_color(p) + [alpha] for p in pct]


def quantize(colors: Sequence[Sequence[int]], step: int = 8) -> List[List[int]]:
    """Rounds colour channels to multiples of `step` so neighbouring segments share a colour and merge into one feature."""
    return [[min(255, int(round(c / step)) * step) for c in col[:3]] + list(col[3:]) for col in colors]
