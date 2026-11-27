"""The overview camera's zoom in on a cluster of stops, shared by every overview style (course.py times it by its
trace, overview_animation.py by its walker): which stops make a cluster, the view that frames it, the GL map
captured at each view, and the cards placed in it (docs/OVERVIEW_RULES.md 8.9, 8.18)."""

import math
import os
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from services import tuning
from services.logger.progress import tracker

from .base import logger
from .card_spots import place_cards


def smoothstep(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def pin_width(graphics) -> float:
    return tuning.CLUSTER_PIN_WIDTH_RADII * float(graphics.marker_radius)


def cluster_views(
    stops: List[Tuple[float, float, float]], path: np.ndarray, cum: np.ndarray, w: int, h: int, within: float,
    min_stops: int, max_zoom: float,
) -> List[Tuple[float, float, float, float, float]]:
    """(first distance, last distance, zoom, crop x, crop y) per cluster along the route. `stops` is (distance along
    `path`, screen x, y) of each; a cluster is `min_stops` or more of them in route order, each `within` px of the
    next on screen. The view frames the stretch of route between the cluster's first and last stop (framing the cards
    too left only ~1.17x, 2026-11-21): the cards move inside it while zoomed (_place_zoom_cards)."""
    top, bottom = tuning.COURSE_TOP_BAND_FRACTION * h, tuning.COURSE_BOTTOM_BAND_FRACTION * h
    band_h, pad = h - top - bottom, 0.06 * h
    ordered = sorted(stops)
    out: List[Tuple[float, float, float, float, float]] = []
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and math.dist(ordered[j][1:], ordered[j + 1][1:]) <= within:
            j += 1
        if j - i + 1 >= min_stops:
            d0, d1 = ordered[i][0], ordered[j][0]
            pts = np.vstack([path[(cum >= d0 - 1e-6) & (cum <= d1 + 1e-6)], [s[1:] for s in ordered[i:j + 1]]])
            (x0, y0), (x1, y1) = pts.min(axis=0), pts.max(axis=0)
            fits = min(w / (x1 - x0 + 2 * pad), band_h / (y1 - y0 + 2 * pad))
            z = min(fits, max_zoom)
            if fits > 1.05:  # a stretch that loops far away between two close stops would barely zoom
                # The cluster's middle lands mid-band, the crop kept inside the frame.
                cx = min(max((x0 + x1) / 2 - w / (2 * z), 0.0), w - w / z)
                cy = min(max((y0 + y1) / 2 - (top + band_h / 2) / z, 0.0), h - h / z)
                out.append((d0, d1, z, cx, cy))
        i = j + 1
    return out


def crop_zoom(frame: np.ndarray, s: float, x0: float, y0: float) -> np.ndarray:
    """The `1/s`-sized crop of `frame` from (x0, y0) scaled back up to the whole frame."""
    h, w = frame.shape[:2]
    m = np.float32([[s, 0, -x0 * s], [0, s, -y0 * s]])
    return cv2.warpAffine(frame, m, (w, h), flags=cv2.INTER_LINEAR)


def zoomed_pin(ap: Dict, view: Tuple[float, float, float]) -> Tuple[float, float]:
    """Where a stop's pin is in the zoomed frame of `view` (zoom, crop x, crop y)."""
    s, x0, y0 = view
    return (ap.get("pin_x", ap["x"]) - x0) * s, (ap.get("pin_y", ap["y"]) - y0) * s


def pin_in_view(ap: Dict, view: Tuple[float, float, float], w: int, h: int) -> bool:
    x, y = zoomed_pin(ap, view)
    return 0 <= x <= w and 0 <= y <= h


def view_key(view: Tuple[float, float, float]) -> Tuple[float, float, float]:
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


def moved_to(ap: Dict, view: Tuple[float, float, float]) -> Dict:
    """A copy of a popup where the zoomed frame of `view` shows it."""
    s, x0, y0 = view
    out = dict(ap)
    out["x"], out["y"] = int(round((ap["x"] - x0) * s)), int(round((ap["y"] - y0) * s))
    if "pin_x" in ap:
        # The declutter nudge keeps its own pixel size: scaled with the zoom, a pin pushed off its stop read as
        # detached from the route line it sits on.
        out["pin_x"], out["pin_y"] = out["x"] + ap["pin_x"] - ap["x"], out["y"] + ap["pin_y"] - ap["y"]
    return out


def pin_head_box(graphics, px: float, py: float) -> Tuple[float, float, float, float]:
    """The box a stop's teardrop covers: its head stands above the point (as popups._recap_cards_pin_cover)."""
    r = float(graphics.marker_radius)
    return px - 1.2 * r, py - 3.0 * r, px + 1.2 * r, py + 0.5 * r


class WalkCamera:
    """The walk's camera: it eases in on a cluster (cluster_views) as the walker comes up to it, holds while the
    walker passes it or waits there, and eases back out once it has left. Counted in written frames, so a hold
    on the voice keeps it in."""

    def __init__(self, clusters: List[Tuple], fps: int, within: float, route: Optional[np.ndarray] = None,
                 reserved=()):
        self.clusters, self.within = clusters, within
        self.route, self.reserved = route, reserved  # what the zoomed cards keep off
        self.steps = max(1, int(round(tuning.COURSE_DENSE_EASE_SECONDS * fps)))
        self.k = 0  # how many frames into the ease
        self.zoom: Optional[Tuple] = None
        self.released = False  # the walk is over: back to the whole map
        self.frames: Dict[Tuple, str] = {}  # view key: its GL map file
        self.image: Tuple[Optional[str], Optional[np.ndarray]] = (None, None)  # the GL map last read
        self.spots: Dict[Tuple, Tuple] = {}  # (zoom, popup index): its card's zoomed spot

    def view(self, zoom: Tuple, k: int) -> Tuple[float, float, float]:
        _d0, _d1, s, x0, y0 = zoom
        e = smoothstep(k / self.steps)
        return 1.0 + (s - 1.0) * e, x0 * e, y0 * e

    def views(self) -> List[Tuple[float, float, float]]:
        """Every view the walk can show, to capture before the first frame."""
        return [self.view(zoom, k) for zoom in self.clusters for k in range(1, self.steps + 1)]

    def step(self, cum: np.ndarray, index: int) -> Optional[Tuple[Tuple, Tuple[float, float, float], float]]:
        """(cluster, view, ease 0..1) for the next frame, the walker at `cum[index]` along its path; None on the
        whole map."""
        here, ahead = cum[index], cum[min(index + self.steps, len(cum) - 1)]  # `ahead`: where it is an ease from now

        def passing(zoom: Tuple) -> bool:
            return ahead >= zoom[0] - 1e-6 and here <= zoom[1] + self.within

        if self.k == 0:
            self.zoom = next((z for z in self.clusters if passing(z)), None)
        inside = not self.released and self.zoom is not None and passing(self.zoom)
        self.k = min(self.steps, self.k + 1) if inside else max(0, self.k - 1)
        if self.k == 0:
            return None
        return self.zoom, self.view(self.zoom, self.k), smoothstep(self.k / self.steps)


class _ClusterZoomMixin:
    def _gl_view_frames(
        self, views: List[Tuple[float, float, float]], bounding_box: Optional[Dict[str, float]],
        w: int, h: int, out_dir: str,
    ) -> Dict[Tuple[float, float, float], str]:
        """The GL map (no route, no pins) captured at each zoomed view, saved under `out_dir`: {view key: file}.
        Empty with no Mapbox key or when the capture fails; the zoom then crops the base frame instead."""
        from services.mapbox_token import resolve_mapbox_token
        from services.mapfetcher.maplanguage import resolve_map_style
        from services.mapfetcher.pydeck_overview import _capture_zoom_raw, compute_pydeck_view

        settings = (self._get_job_config() or {}).get("settings", {}) or {}
        key = resolve_mapbox_token(settings)
        keys = sorted({view_key(v) for v in views})
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
            logger.warning("Overview: the GL zoom could not be captured (%s); cropping the map instead.", exc)
            return {}
        return dict(zip(keys, sink.paths)) if len(sink.paths) == len(keys) else {}

    def _place_zoom_cards(
        self, group: List[Dict], order: List[int], pins_shown: List[Dict], hold: Tuple[float, float, float],
        route: Optional[np.ndarray], reserved, w: int, h: int,
    ) -> Dict[int, Tuple[int, int, float]]:
        """{popup index: (x, y, scale)} of a zoom's cards at their own size in the zoomed view `hold`, as on the
        whole map: round their pins (card_spots), clear of the panels, every pin in `pins_shown`, the route and
        each other; where no free layout works, each at the nearest clear spot to its pin (the ring search), in `order`
        (the order they pop)."""
        s, x0, y0 = hold

        def at(p: Dict) -> Tuple[float, float]:
            return zoomed_pin(p, hold)

        pins = [at(c) for c in group]
        if route is not None:
            route = (route - np.array([x0, y0])) * s
            route = route[((route >= 0) & (route < (w, h))).all(axis=1)]  # off view it would block the edge cells
        keep_off = list(reserved) + [pin_head_box(self.graphics, *at(p)) for p in pins_shown]
        scale = group[0]["stay_scale"]  # every card has the video's one size
        card_w, card_h = self.graphics.beside_card_footprint(scale)
        grouped = {id(c) for c in group}
        boxes = place_cards(
            pins, w, h, keep_off, route, float(self.graphics.marker_radius), card_w, card_h,
            others=[at(p) for p in pins_shown if id(p) not in grouped])
        if boxes is not None:
            spots = [(i, box[0], box[1]) for i, box in enumerate(boxes)]
        else:
            fixed, route_layer = self._ring_grids(w, h, keep_off, route)
            steps = int(math.hypot(w, h) // self._RING_STEP_PX)
            spots = self._ring_untangle(
                pins, self._ring_attempt(scale, False, w, h, pins, order, fixed, route_layer, steps),
                card_w, card_h)[0]
        placed = {group[i]["index"]: (int(x), int(y), scale) for i, x, y in spots}
        for c in group:  # no room anywhere: it keeps its whole-map spot
            placed.setdefault(c["index"], (*c["stay_box"], scale))
        return placed
