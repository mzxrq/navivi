"""
Map Geometry Service (map_geometry.py)
---------------------------------------------------------------------------
Handles geometry smoothing, time pacing, and downloading map tiles.
Extracted from mapfetcher.py to improve modularity.
---------------------------------------------------------------------------
"""
# [I/O] Import libraries for map fetching and geometry processing
from typing import Any, Final, Optional, Tuple, List, Dict
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree  # type: ignore
from scipy.interpolate import make_interp_spline
import math

# [I/O] Import service dependencies for Integration
from services.logger.logger import setup_logger
from services.config.job_config import JobConfigManager

# [Utility] Log setup for debugging and monitoring
logger = setup_logger("MapEngine")

# [Final] Constants for map tile downloading and geometry processing
TARGET_ASPECT_RATIO: Final[float] = 16 / 9
MIN_MAP_WIDTH_PX: Final[int] = 800
# Standard Web Mercator (EPSG:3857) spherical Earth radius in meters, used by
# both project_latlon_to_pixel and its inverse, pixel_to_latlon.
EARTH_RADIUS_METERS: Final[float] = 6378137.0
# Consecutive raw points closer together than this (in the same units as the
# input points) are treated as redundant jitter and dropped before smoothing
# — see get_smooth_path's own docstring, step 1.
NOISE_FILTER_DISTANCE: Final[float] = 0.1

# --- Web Mercator view math -----------------------------------------------
# deck.gl (like mapbox-gl-js) tiles the world in 512px squares; together with
# the earth's circumference this is what converts between a zoom level and
# real meters-per-pixel. Kept here, alongside project_latlon_to_pixel's own
# extent math, so the framing helpers below stay free of any pydeck/browser
# dependency — the raster tile path uses them too, and it exists precisely
# for the case where that stack isn't available.
_EARTH_CIRCUMFERENCE_M: Final[float] = 2 * math.pi * EARTH_RADIUS_METERS
_TILE_SIZE_PX: Final[int] = 512


def _mercator_x(lon: float) -> float:
    return lon * (EARTH_RADIUS_METERS * math.pi / 180.0)


def _mercator_y(lat: float) -> float:
    return EARTH_RADIUS_METERS * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def _inverse_mercator_y(my: float) -> float:
    return math.degrees(2 * math.atan(math.exp(my / EARTH_RADIUS_METERS)) - math.pi / 2)


def meters_per_pixel(zoom: float) -> float:
    """Ground meters covered by one screen pixel at a given zoom level."""
    return _EARTH_CIRCUMFERENCE_M / (_TILE_SIZE_PX * (2.0 ** zoom))


def zoom_for_ground_width(width_m: float, width_px: int) -> float:
    """The zoom level at which `width_px` pixels span `width_m` meters — the
    inverse of meters_per_pixel, for callers that think in "show me about
    300m across" rather than in zoom levels."""
    return math.log2(_EARTH_CIRCUMFERENCE_M * width_px / (_TILE_SIZE_PX * max(1.0, width_m)))


def extent_for_view(
    center_lon: float, center_lat: float, zoom: float, output_size: Tuple[int, int]
) -> Tuple[float, float, float, float]:
    """The (min_x, max_x, min_y, max_y) Web Mercator meters extent a view
    state covers — the same convention project_latlon_to_pixel takes."""
    out_w, out_h = output_size
    mpp = meters_per_pixel(zoom)
    cx, cy = _mercator_x(center_lon), _mercator_y(center_lat)
    return (
        cx - (out_w / 2.0) * mpp, cx + (out_w / 2.0) * mpp,
        cy - (out_h / 2.0) * mpp, cy + (out_h / 2.0) * mpp,
    )


# --- Framing a close-up so the route through it stays visible -------------
# A close-up centred on one waypoint shows whatever the route happens to be
# doing there: on a stop at the edge of town the line runs off the frame a
# few hundred metres away and the shot reads as a map of nothing in
# particular. These pick the view instead of assuming one.

# Safe inset kept clear on every side when judging whether a piece of route
# is "visible": a line touching the last few pixels of the frame reads as
# cut off even though it technically shows.
_FOCUS_MARGIN_FRAC = 0.08
# Zoom search granularity, in zoom levels. 0.1 is about a 7% change in
# scale — finer than anyone can see between two candidate framings, so
# there's nothing to gain from a smaller step.
_FOCUS_ZOOM_STEP = 0.1
# Candidate camera centres tried per axis at each zoom (the centre is free
# to move only as far as keeping the target point inside the safe inset
# allows, so this grid spans a small range).
_FOCUS_CENTER_GRID = 7
# How much of the best-achievable visible route length a tighter framing
# must still deliver to be preferred over a wider one. At 1.0 it would
# always pick the widest view; at 0.0, always the tightest. Lowered from
# 0.7: that value pulled the ending highlight back well short of its own
# zoom_boost ceiling (ENDING_HIGHLIGHT_PYDECK_ZOOM_BOOST) whenever the
# route swept away from the target point at all, which it usually does —
# reported as the close-up never actually reaching street/building-level
# detail even after raising the ceiling itself. 0.3 still refuses a
# framing that loses the line almost entirely, but otherwise favors
# getting genuinely close over keeping a long stretch of route in shot.
_FOCUS_VISIBLE_RATIO = 0.3
# Route samples used for the search. The route is resampled to this many
# evenly-spaced points inside the neighbourhood being considered, so
# "visible length" is just a count of consecutive samples times their
# spacing.
_FOCUS_SAMPLES = 400
# Among candidate centres at a given zoom that all show at least this
# fraction of that zoom's own BEST achievable visible length, the one
# closest to the bias point wins instead of the strict length-maximizer.
# Keeps the tie-break from trading away a meaningful amount of visible
# route just to chase the bias direction — 0.92 means "give up at most 8%
# of the route this zoom could show" in exchange for better framing.
_FOCUS_BIAS_TOLERANCE = 0.92
# Final vertical nudge applied to whichever centre wins, as a fraction of
# the safe-inset half-height at the chosen zoom: positive pushes the
# camera centre NORTH of the target, which reads as the target sitting
# LOWER in frame (more headroom above); negative pushes it the other way
# (target higher, more room below). Tried +0.35 (push target toward the
# bottom) first, but that left too much empty space above the route on a
# wide sweeping shot — reported back as "map should be upper to center".
# A small negative value instead keeps the target (and the route swinging
# away from it) sitting slightly above center rather than pushed to either
# extreme. Clamped so the target never leaves the safe inset the rest of
# the search already guarantees — this only redistributes where WITHIN
# that inset it sits.
_FOCUS_VERTICAL_BIAS_FRAC = -0.30


def _resample_local_route(
    route_latlon, target_mx: float, target_my: float, radius_m: float
):
    """The stretch of route around `target`, as evenly spaced Web Mercator
    points plus their spacing.

    Only the neighbourhood matters here: a 24km route resampled whole would
    put its samples kilometres apart, far too coarse to judge a 300m-wide
    close-up, while resampling all of it finely enough would be mostly
    wasted work on parts of the line the camera can't reach. So the walk
    starts at the vertex nearest the target and runs outward along the path
    in both directions until it has covered `radius_m`, and only that
    stretch is resampled.

    Returns (points, spacing_m, target_index) — target_index being where
    the target's own nearest sample sits, which is what makes "the run of
    route through this point" well defined below. Returns None when
    there's no usable route near the target at all."""
    pts = [(_mercator_x(lon), _mercator_y(lat)) for lat, lon in (route_latlon or [])]
    if len(pts) < 2:
        return None

    arr = np.asarray(pts, dtype=float)
    d2 = (arr[:, 0] - target_mx) ** 2 + (arr[:, 1] - target_my) ** 2
    nearest = int(np.argmin(d2))

    seg = np.hypot(np.diff(arr[:, 0]), np.diff(arr[:, 1]))
    # Along-path distance from the nearest vertex, signed by direction, so
    # the cut is by how far you'd TRAVEL from the target rather than by
    # straight-line distance — a route that doubles back near the point
    # otherwise picks up a stretch it doesn't actually reach from there.
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    along = cum - cum[nearest]
    keep = np.abs(along) <= radius_m
    if keep.sum() < 2:
        keep[max(0, nearest - 1): nearest + 2] = True
    local = arr[keep]
    if len(local) < 2:
        return None

    local_seg = np.hypot(np.diff(local[:, 0]), np.diff(local[:, 1]))
    local_cum = np.concatenate([[0.0], np.cumsum(local_seg)])
    total = float(local_cum[-1])
    if total <= 0:
        return None

    n = _FOCUS_SAMPLES
    want = np.linspace(0.0, total, n)
    sx = np.interp(want, local_cum, local[:, 0])
    sy = np.interp(want, local_cum, local[:, 1])
    samples = np.column_stack([sx, sy])

    sd2 = (sx - target_mx) ** 2 + (sy - target_my) ** 2
    return samples, total / (n - 1), int(np.argmin(sd2))


def _visible_run_length(
    samples, spacing: float, target_index: int,
    cx: float, cy: float, half_w: float, half_h: float,
) -> float:
    """Length of the UNBROKEN run of route through the target that falls
    inside the window centred at (cx, cy).

    Unbroken through the target, rather than total length inside the
    window, is the whole point: a framing that catches two disconnected
    scraps of line in opposite corners scores well on total length while
    looking exactly like the problem being solved — a route cut in half by
    the frame edge. Measuring only the run that actually passes through
    the featured point rewards framings where the line reads as one
    continuous path arriving at it."""
    inside = (
        (np.abs(samples[:, 0] - cx) <= half_w)
        & (np.abs(samples[:, 1] - cy) <= half_h)
    )
    if not inside[target_index]:
        return 0.0
    n = len(inside)
    lo = target_index
    while lo > 0 and inside[lo - 1]:
        lo -= 1
    hi = target_index
    while hi < n - 1 and inside[hi + 1]:
        hi += 1
    return (hi - lo) * spacing


def choose_route_focus_view(
    route_latlon,
    target_lat: float,
    target_lon: float,
    output_size: Tuple[int, int],
    min_zoom: float,
    max_zoom: float,
    next_lat: Optional[float] = None,
    next_lon: Optional[float] = None,
    must_fit_latlon: Optional[List[Tuple[float, float]]] = None,
) -> Tuple[float, float, float]:
    """Picks (center_lon, center_lat, zoom) for a close-up on
    (target_lat, target_lon) that shows as much of the route through it as
    it can while staying as tight as it can.

    `route_latlon` is the route as (lat, lon) pairs — the same stash the
    renderer draws the line from, so the framing is judged against the
    exact geometry that will be drawn. The search is bounded by
    [min_zoom, max_zoom] (callers pass the zoom they'd otherwise have used
    as max_zoom, so this only ever pulls BACK from that, never past the
    wide shot it started from).

    Two knobs, in order:

    * zoom — every level from tightest to widest is scored, and the
      TIGHTEST one still showing _FOCUS_VISIBLE_RATIO of the best
      achievable run of route wins. So a stop with the route sweeping past
      it stays close in, and only a stop where the line leaves the frame
      almost immediately pulls back.
    * centre — free to move as far as keeping the target point itself
      inside the safe inset allows. That slack is what lets the camera sit
      off to one side so the line runs across the frame instead of clipping
      its corner, without ever pushing the featured waypoint out of shot.

    `next_lat`/`next_lon` — the next stop along the route from the target,
    when there is one — bias WHICH of several similarly-good centres gets
    picked: among candidates at a zoom that all show at least
    _FOCUS_BIAS_TOLERANCE of that zoom's best achievable length, the one
    closest to the midpoint between the target and this point wins. A pure
    length-maximizing centre is otherwise free to land anywhere that
    happens to catch the most route — including squarely on the target
    itself, which centres the pin dead-on but tells the viewer nothing
    about where the journey is headed next. Biasing toward the outgoing
    leg is what makes the shot read as "here's the stop, and here's the
    way from it" rather than just a pin with some road nearby. Omit it
    (e.g. the target has no next stop — it's the very end of the route)
    to fall back to pure length-maximizing centring.

    `must_fit_latlon` — other waypoints worth keeping in shot alongside
    the route line (typically every OTHER stop, e.g. nearby stop-bys —
    the scoring only ever REWARDS a candidate for including more of them,
    never requires it, so a genuinely unreachable point at the chosen zoom
    just contributes nothing rather than breaking the search). Without
    this, the search only ever judges a candidate by how much of the
    ROUTE LINE it shows — a stop-by sitting just off to one side of the
    line (the common case: it's a landmark the route passes NEAR, not
    through) had nothing keeping it in frame, and a tight enough zoom
    would happily crop it out despite the line itself looking fine.
    Candidates are compared by (how many of these points they fit, route
    length) in that order, so this can still shift which of two
    similar-length centres wins, but it never overrides the zoom level
    itself or pulls the target out of its own safe inset.

    Falls back to centring on the target at max_zoom (the old behaviour)
    when there's no route geometry to frame against."""
    out_w, out_h = output_size
    tx, ty = _mercator_x(target_lon), _mercator_y(target_lat)

    def view_at(cx: float, cy: float, zoom: float):
        return (
            cx / (EARTH_RADIUS_METERS * math.pi / 180.0), _inverse_mercator_y(cy), zoom,
        )

    if max_zoom < min_zoom:
        min_zoom, max_zoom = max_zoom, min_zoom
    widest_mpp = _EARTH_CIRCUMFERENCE_M / (_TILE_SIZE_PX * (2.0 ** min_zoom))
    radius_m = math.hypot(out_w, out_h) * widest_mpp

    def with_vertical_bias(cx: float, cy: float, zoom: float):
        mpp = _EARTH_CIRCUMFERENCE_M / (_TILE_SIZE_PX * (2.0 ** zoom))
        half_h = (out_h / 2.0) * mpp * (1.0 - 2.0 * _FOCUS_MARGIN_FRAC)
        cy = cy + _FOCUS_VERTICAL_BIAS_FRAC * half_h
        # Keep the target itself within the same safe inset the search
        # already respected — the bias only redistributes where in it the
        # target sits, it never pushes the target out of frame.
        cy = min(ty + half_h, max(ty - half_h, cy))
        return view_at(cx, cy, zoom)

    local = _resample_local_route(route_latlon, tx, ty, radius_m)
    if local is None:
        return with_vertical_bias(tx, ty, max_zoom)
    samples, spacing, target_index = local

    bias_mx = bias_my = None
    if next_lat is not None and next_lon is not None:
        nx, ny = _mercator_x(next_lon), _mercator_y(next_lat)
        # The midpoint, not the next point itself — biasing all the way to
        # the next stop would fight the "keep the target in the safe
        # inset" constraint for anything but a very close next stop, and
        # defeats the point of this being a close-up ON the target.
        bias_mx, bias_my = (tx + nx) / 2.0, (ty + ny) / 2.0

    must_fit_m = None
    if must_fit_latlon:
        must_fit_m = np.asarray(
            [(_mercator_x(lon), _mercator_y(lat)) for lat, lon in must_fit_latlon],
            dtype=float,
        )

    def best_at(zoom: float):
        mpp = _EARTH_CIRCUMFERENCE_M / (_TILE_SIZE_PX * (2.0 ** zoom))
        half_w = (out_w / 2.0) * mpp * (1.0 - 2.0 * _FOCUS_MARGIN_FRAC)
        half_h = (out_h / 2.0) * mpp * (1.0 - 2.0 * _FOCUS_MARGIN_FRAC)
        # The camera may sit anywhere that still leaves the target inside
        # the safe inset — i.e. its centre within one half-window of it.
        candidates = []
        best_length = 0.0
        for cx in np.linspace(tx - half_w, tx + half_w, _FOCUS_CENTER_GRID):
            for cy in np.linspace(ty - half_h, ty + half_h, _FOCUS_CENTER_GRID):
                length = _visible_run_length(
                    samples, spacing, target_index, cx, cy, half_w, half_h
                )
                fit_count = 0
                if must_fit_m is not None and len(must_fit_m):
                    fit_count = int(np.count_nonzero(
                        (np.abs(must_fit_m[:, 0] - cx) <= half_w)
                        & (np.abs(must_fit_m[:, 1] - cy) <= half_h)
                    ))
                candidates.append((length, cx, cy, fit_count))
                best_length = max(best_length, length)
        if best_length <= 0:
            return (0.0, tx, ty)
        if bias_mx is None:
            # Fit count first — among centres tied on it, the one showing
            # more route line wins (see the docstring on must_fit_latlon:
            # a reward, never a requirement, so this still degrades to
            # pure length-maximizing when nothing was passed in).
            best = max(candidates, key=lambda c: (c[3], c[0]))
            return best[0], best[1], best[2]
        # Among everything within tolerance of this zoom's own best route
        # length, prefer whichever fits the most extra points, then break
        # any remaining tie by closeness to the bias point — see the
        # docstring.
        threshold = best_length * _FOCUS_BIAS_TOLERANCE
        near_best = [c for c in candidates if c[0] >= threshold]
        max_fit = max(c[3] for c in near_best)
        near_best = [c for c in near_best if c[3] == max_fit]
        best = min(near_best, key=lambda c: (c[1] - bias_mx) ** 2 + (c[2] - bias_my) ** 2)
        return best[0], best[1], best[2]

    # The widest allowed view is the yardstick: nothing tighter can show
    # more route than this, so it defines what "as much as possible" is
    # worth in metres before deciding how much of it to trade for zoom.
    reference = best_at(min_zoom)[0]
    if reference <= 0:
        return with_vertical_bias(tx, ty, max_zoom)
    wanted = reference * _FOCUS_VISIBLE_RATIO

    zoom = max_zoom
    fallback = None
    while zoom >= min_zoom - 1e-9:
        length, cx, cy = best_at(zoom)
        if fallback is None or length > fallback[0]:
            fallback = (length, cx, cy, zoom)
        if length >= wanted:
            return with_vertical_bias(cx, cy, zoom)
        zoom -= _FOCUS_ZOOM_STEP

    _, cx, cy, zoom = fallback
    return with_vertical_bias(cx, cy, zoom)


def bbox_for_view(
    center_lon: float, center_lat: float, zoom: float, output_size: Tuple[int, int]
) -> Dict[str, float]:
    """The lat/lon bounding box a view state covers — the bridge from
    choose_route_focus_view's answer back to the {min_lat, max_lat,
    min_lon, max_lon} dict the raster tile fetcher takes."""
    min_x, max_x, min_y, max_y = extent_for_view(
        center_lon, center_lat, zoom, output_size
    )
    deg = EARTH_RADIUS_METERS * math.pi / 180.0
    return {
        "min_lat": _inverse_mercator_y(min_y),
        "max_lat": _inverse_mercator_y(max_y),
        "min_lon": min_x / deg,
        "max_lon": max_x / deg,
    }

# [Map] Map routing geometry smoothing and time pacing parameters
class RouteGeometryProcessor:
    """Processes route geometry for smoothing and time pacing."""

    # [Utility] Get bounding box for a set of lat/lon points
    @staticmethod
    def get_bounding_box(route_df : pd.DataFrame, padding_factor : float = 0.15, **kwargs) -> Dict[str, float]:
        """Calculate the bounding box with optional padding."""

        min_lat, max_lat = route_df["latitude"].min(), route_df["latitude"].max()
        min_lon, max_lon = route_df["longitude"].min(), route_df["longitude"].max()

        lat_padding = (max_lat - min_lat) * padding_factor
        lon_padding = (max_lon - min_lon) * padding_factor

        return {
            "min_lat": min_lat - lat_padding,
            "max_lat": max_lat + lat_padding,
            "min_lon": min_lon - lon_padding,
            "max_lon": max_lon + lon_padding,
        }

    # [Map] Project a list of lat/lon points to pixel coordinates based on map extent and image size
    @staticmethod
    def project_to_pixels(
       route_df: pd.DataFrame, waypoints: List[Dict]
    ) -> List[int]:
        """Project lat/lon points to pixel coordinates based on map extent and image size."""

        if route_df.empty or not waypoints:
            return []
        tree = cKDTree(route_df[["latitude", "longitude"]].to_numpy())
        _, indices = tree.query([[wp["lat"], wp["lng"]] for wp in waypoints])
        return np.atleast_1d(indices).tolist()

    # [Map] Find the nearest route_df row index for each waypoint (nearest-neighbor match)
    @staticmethod
    def build_waypoint_index(
        route_df: pd.DataFrame, waypoints: List[Dict]
    ) -> List[int]:
        """For each waypoint, in order, finds the index of the closest point
        in `route_df` — searched only from the PREVIOUS waypoint's own match
        onward, never earlier. A plain global nearest-neighbor query (the
        old behavior) breaks on any route that revisits the same spot —
        most commonly an out-and-back/loop trip whose first and last
        waypoint share (near-)identical coordinates — since the true last
        point and the true first point are then equally "nearest" to the
        last waypoint, and cKDTree has no notion of which one is actually
        meant. That let the LAST waypoint's match collide with the FIRST
        waypoint's (both landing on index 0), silently overwriting the
        start waypoint's popup and leaving nothing matched at the route's
        real final index — which is what the overview's end-of-video
        highlight (stop_popup) needs to ever trigger. Restricting each
        search to start where the previous waypoint left off guarantees a
        monotonically non-decreasing match by construction, resolving the
        ambiguity the same way a human reading the track chronologically
        would: each waypoint is visited in sequence, never before the one
        before it."""
        if route_df.empty or not waypoints:
            return []
        coords = route_df[["latitude", "longitude"]].to_numpy()
        num_points = len(coords)
        indices: List[int] = []
        search_start = 0
        for wp in waypoints:
            lat, lng = wp["lat"], wp.get("lng", wp.get("lon"))
            window = coords[search_start:]
            if len(window) == 0:
                indices.append(num_points - 1)
                continue
            dist_sq = (window[:, 0] - lat) ** 2 + (window[:, 1] - lng) ** 2
            local_idx = int(np.argmin(dist_sq))
            global_idx = search_start + local_idx
            indices.append(global_idx)
            search_start = global_idx

        # Two real, distinct waypoints placed close together on the map
        # (several stops on the same block, or a lookout point revisited
        # later in the trip) can still both land on the SAME nearest GPS
        # index above — forward-only search prevents them going backward,
        # but says nothing about ties. A caller downstream (route_popups in
        # render_step.py) keys its per-waypoint data by this exact index,
        # so a collision isn't cosmetic: the second waypoint's popup
        # silently OVERWRITES the first's at that shared index, and when
        # the animation later reaches that single point, whichever
        # waypoint won the overwrite is the only one that ever pops up —
        # which can visibly be the wrong one (e.g. a stop from later in the
        # trip appearing at a spot the traveler is only passing for the
        # first time). Bumping every duplicate forward by the smallest
        # possible step keeps each waypoint's own popup at its own index,
        # in the same visit order already established above, instead of
        # letting two genuinely different stops fight over one slot.
        for i in range(1, len(indices)):
            if indices[i] <= indices[i - 1]:
                indices[i] = min(num_points - 1, indices[i - 1] + 1)
        return indices

    # [Map] Douglas-Peucker algorithm for path simplification
    @staticmethod
    def douglas_peucker(points: List[Tuple[float, float]], tolerance: float, **kwargs) -> List[int]:
        if len(points) < 3:
            return list(range(len(points)))

        pts = np.array(points)
        keep = {0, len(points) - 1}

        # [NOTE] [Map] Recursively keeps only the point farthest from the start-end chord when it exceeds tolerance, discarding the rest of the segment as redundant.
        def _dp(start, end):
            if end - start <= 1:
                return
            line = pts[end] - pts[start]
            line_len = np.hypot(*line)
            if line_len == 0:
                dists = np.hypot(*(pts[start + 1 : end] - pts[start]).T)
            else:
                # Perpendicular distance from each point to the chord via
                # the 2D cross product (dot with the chord's unit normal),
                # not a full point-to-segment distance — points can project
                # outside [start, end] and still get a meaningful distance.
                norm = np.array([-line[1], line[0]]) / line_len
                dists = np.abs((pts[start + 1 : end] - pts[start]) @ norm)

            max_idx = np.argmax(dists)
            max_dist = dists[max_idx]
            mid = start + 1 + max_idx

            if max_dist > tolerance:
                keep.add(mid)
                _dp(start, mid)
                _dp(mid, end)

        _dp(0, len(points) - 1)
        return sorted(keep)

    # [Map] Easing function for smooth animations
    @staticmethod
    def ease_in_out_cubic(t: np.ndarray) -> np.ndarray:
        return np.where(t < 0.5, 4 * t**3, 1 - ((-2 * t + 2) ** 3) / 2)

    # [Map] Make a cubic B-spline interpolation for smooth path generation
    @staticmethod
    def make_cubic_b_spline(t: np.ndarray, values: np.ndarray, k: int = 3) -> np.ndarray:
        return make_interp_spline(t, values, k=k)

    # [Map] Generate an animated path between waypoints
    @staticmethod
    def get_smooth_path(
        points: List[Tuple[float, float]],
        num_frames: int,
        simplify_tolerance_px: float = 3.0,
        ease: bool = True,
        curve: bool = False,
        **kwargs,
    ) -> np.ndarray:
        """
        Process Description & Calculation Logic:
        1. Noise Reduction: Filters out redundant consecutive points where the Euclidean
           distance is less than 0.1 units to eliminate jitter.
        2. Geometry Simplification: Applies the Douglas-Peucker algorithm to reduce
           unnecessary vertex density along straight segments based on the tolerance threshold.
        3. Edge Case Handling: Returns a static array or zero-matrix if the resulting
           points fall below the minimum threshold required for interpolation.
        4. Cumulative Distance Parameterization: Computes point-to-point Euclidean distances
           via `np.hypot` and builds a cumulative distance array (cum_dists) to map
           out the true spatial length of the route.
        5. Temporal Pacing & Easing: Normalizes path progress into a progress domain ($t$),
           generates linear frame markers across the requested `num_frames`, and optionally
           applies a cubic easing function (`ease_in_out_cubic`) to simulate natural
           acceleration and deceleration curves.
        6. Position Evaluation: By default (`curve=False`) walks the eased frame timestamps
           along the piecewise-STRAIGHT polyline through the simplified points via linear
           interpolation, so the animated position always sits exactly on the real route —
           never bulging outside a sharp turn the way a curve fit through sparse points can.
           Pass `curve=True` to fit a cubic B-spline through the points instead for a
           rounded, cinematic path (at the cost of sometimes cutting corners).
        """

        filtered_pts = [points[0]]
        for p in points[1:]:
            if np.hypot(p[0] - filtered_pts[-1][0], p[1] - filtered_pts[-1][1]) > NOISE_FILTER_DISTANCE:
                filtered_pts.append(p)

        if len(filtered_pts) > 2:
            keep_idx = RouteGeometryProcessor.douglas_peucker(
                filtered_pts, tolerance=simplify_tolerance_px
            )
            filtered_pts = [filtered_pts[i] for i in keep_idx]

        pts = np.array(filtered_pts, dtype=float)
        n = len(pts)
        if n < 2:
            if len(points) > 0:
                return np.array([points[0]] * num_frames)
            return np.zeros((num_frames, 2))

        diffs = np.diff(pts, axis=0)
        dists = np.hypot(diffs[:, 0], diffs[:, 1])
        cum_dists = np.concatenate(([0], np.cumsum(dists)))

        total_dist = cum_dists[-1]
        t = cum_dists / total_dist if total_dist > 0 else np.linspace(0, 1, n)
        t_linear = np.linspace(0, 1, num_frames)
        t_fine = RouteGeometryProcessor.ease_in_out_cubic(t_linear) if ease else t_linear

        if curve:
            k = min(3, n - 1)
            sx = RouteGeometryProcessor.make_cubic_b_spline(t, pts[:, 0], k=k)
            sy = RouteGeometryProcessor.make_cubic_b_spline(t, pts[:, 1], k=k)
            return np.vstack([sx(t_fine), sy(t_fine)]).T

        x = np.interp(t_fine, t, pts[:, 0])
        y = np.interp(t_fine, t, pts[:, 1])
        return np.vstack([x, y]).T

    # [Map] Project a single lat/lon coordinate to pixel coordinates based on map extent and image size
    @staticmethod
    def project_latlon_to_pixel(lat: float, lon: float,extent: Tuple[float, float, float, float],img_w: int,img_h: int) -> List[float]:
        """
        Projects a real-world coordinate to a specific pixel location on a map image.
        
        Calculation Process:
        1. Geographic Projection (Web Mercator EPSG:3857):
           - Flattens the Earth's curved surface onto a 2D plane using a standard radius (6,378,137m).
           - X-axis ($m_x$): Converts longitude to radians and multiplies by the Earth radius.
           - Y-axis ($m_y$): Applies the Mercator logarithm tangent formula to latitude.
        2. Pixel Scaling:
           - X-axis ($p_x$): Finds the horizontal percentage of $m_x$ within the map's bounding box 
             (`extent`) and multiplies by the image width (`img_w`).
           - Y-axis ($p_y$): Finds the vertical percentage of $m_y$, but inverts the axis 
             (subtracting from `max_y`) because computer graphic pixels increment downwards, 
             while geographic coordinates increment upwards (North).
        """

        min_x, max_x, min_y, max_y = extent
        r = EARTH_RADIUS_METERS
        mx = lon * (r * np.pi / 180.0)
        my = np.log(np.tan((90.0 + lat) * np.pi / 360.0)) * r
        px = (mx - min_x) / (max_x - min_x) * img_w
        py = (max_y - my) / (max_y - min_y) * img_h

        return [float(px), float(py)]

    # [Map] Inverse of project_latlon_to_pixel — recovers the real-world
    # coordinate a pixel on a map image of the given extent corresponds to.
    @staticmethod
    def pixel_to_latlon(px: float, py: float, extent: Tuple[float, float, float, float], img_w: int, img_h: int) -> List[float]:
        min_x, max_x, min_y, max_y = extent
        r = EARTH_RADIUS_METERS
        mx = min_x + (px / img_w) * (max_x - min_x)
        my = max_y - (py / img_h) * (max_y - min_y)
        lon = mx / (r * np.pi / 180.0)
        lat = (2 * np.arctan(np.exp(my / r)) - np.pi / 2) * (180.0 / np.pi)
        return [float(lat), float(lon)]

    # [NOTE] [Map] Projects point P onto segment AB, clamping t to [0, 1] so the closest point stays within the segment's endpoints rather than the infinite line through them.
    @staticmethod
    def point_to_segment_distance(
        px: float, py: float, ax: float, ay: float, bx: float, by: float
    ) -> float:
        abx, aby = bx - ax, by - ay
        seg_len_sq = abx * abx + aby * aby
        if seg_len_sq < 1e-9:
            return float(np.hypot(px - ax, py - ay))
        t = max(0.0, min(1.0, ((px - ax) * abx + (py - ay) * aby) / seg_len_sq))
        closest_x, closest_y = ax + t * abx, ay + t * aby
        return float(np.hypot(px - closest_x, py - closest_y))

    @staticmethod
    def is_real_label(label: Any) -> bool:
        if label is None:
            return False
        if isinstance(label, float) and math.isnan(label):
            return False
        return str(label).strip() != ""