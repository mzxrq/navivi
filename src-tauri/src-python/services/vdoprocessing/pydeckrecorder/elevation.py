"""Steepness colouring for the route line in the video.

[NOTE] [Heatmap] Mirrors src/utils/elevation.ts on purpose (same smoothing window, slope span, cap and colour
ramp) so the video's gradient matches the editor's. Pure functions, no I/O: the app writes each track point's
elevation into raw_track.gpx (GPSBabel's csv keeps it as `height`), the pipeline hands a leg's heights in and the
renderer asks for one colour per segment.
"""

import math
from typing import Callable, Dict, List, Optional, Sequence, Tuple

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


def climb(ele: Sequence[float]) -> Tuple[float, float]:
    """(metres up, metres down) over a smoothed profile."""
    up = sum(max(0.0, b - a) for a, b in zip(ele, ele[1:]))
    down = sum(max(0.0, a - b) for a, b in zip(ele, ele[1:]))
    return up, down


def profile_card(
    latlon: Sequence[Sequence[float]], ele: Optional[Sequence[float]], size: Tuple[int, int], title: str,
    colors: Dict[str, str], max_points: int = 240,
) -> Optional[Tuple[str, Callable[[float], Tuple[float, float]]]]:
    """The leg's elevation profile as an SVG card (title, "1.2 km · +61 m · −29 m", the curve in the heatmap's
    colours over a soft fill, and a marker <g id="elev-marker"> drawn at the start), plus a function from the
    share of the leg walked (0..1) to the marker's (x, y) in the card. None without usable elevation.
    `colors`: CSS colours for "text", "label", "fill"."""
    seg_colors = leg_segment_colors(latlon, ele)
    if seg_colors is None:
        return None
    dist = cumulative_m(latlon)
    total = dist[-1]
    if total <= 0:
        return None
    prof = smooth(dist, ele)
    w, h = size
    pad, top, bottom = 22.0, 58.0, 18.0
    lo, hi = min(prof), max(prof)
    span = max(hi - lo, 10.0)  # a nearly flat leg stays nearly flat instead of filling the card

    def xy(d: float, e: float) -> Tuple[float, float]:
        return pad + d / total * (w - 2 * pad), top + (1 - (e - lo) / span) * (h - top - bottom)

    step = max(1, len(dist) // max_points)
    keep = list(range(0, len(dist), step))
    if keep[-1] != len(dist) - 1:
        keep.append(len(dist) - 1)
    pts = [xy(dist[i], prof[i]) for i in keep]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    base_y = h - bottom
    area = f"M{pts[0][0]:.1f},{base_y:.1f} L{line.replace(' ', ' L')} L{pts[-1][0]:.1f},{base_y:.1f} Z"
    segs = []
    for a, b in zip(keep, keep[1:]):
        r, g, bl = seg_colors[a][:3]
        (x1, y1), (x2, y2) = xy(dist[a], prof[a]), xy(dist[b], prof[b])
        segs.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="rgb({r},{g},{bl})"/>')
    up, down = climb(prof)
    stats = f"{total / 1000:.1f} km · +{up:.0f} m · −{down:.0f} m"
    x0, y0 = pts[0]
    svg = (
        f'<svg id="hud-elev" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
        f'<text x="{pad}" y="36" fill="{colors["text"]}" font-size="22" font-weight="700">{title}</text>'
        f'<text x="{w - pad}" y="36" fill="{colors["label"]}" font-size="20" text-anchor="end">{stats}</text>'
        f'<path d="{area}" fill="{colors["fill"]}"/>'
        f'<g stroke-width="5" stroke-linecap="round">{"".join(segs)}</g>'
        f'<g id="elev-marker" transform="translate({x0:.1f},{y0:.1f})">'
        f'<line x1="0" y1="0" x2="0" y2="{base_y - y0:.1f}" stroke="{colors["text"]}" stroke-width="2" stroke-dasharray="4 4"/>'
        f'<circle r="10" fill="#ffffff" stroke="{colors["text"]}" stroke-width="4"/></g>'
        "</svg>"
    )

    def marker(share: float) -> Tuple[float, float]:
        d = min(1.0, max(0.0, share)) * total
        i = max(1, min(len(dist) - 1, next((k for k, v in enumerate(dist) if v >= d), len(dist) - 1)))
        f = (d - dist[i - 1]) / (dist[i] - dist[i - 1]) if dist[i] > dist[i - 1] else 0.0
        return xy(d, prof[i - 1] + (prof[i] - prof[i - 1]) * f)

    return svg, marker
