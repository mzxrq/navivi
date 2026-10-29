"""Camera framing and screen projection for the pydeck route pages: fitting a view to a path, the leg
margins kept clear of the HUD, lon/lat -> pixel projection and where a photo card can sit."""

from __future__ import annotations

import math
from typing import List, Tuple

_R = 6378137.0
_EARTH_CIRCUMFERENCE_M = 2 * math.pi * _R
_TILE_SIZE_PX = 512


def _bbox_view(lats: List[float], lons: List[float], output_size: Tuple[int, int], pad_frac: float = 0.15):
    """A simple fit-bbox-to-viewport zoom/center — independent of (and
    deliberately simpler than) mapfetcher.pydeck_overview.compute_pydeck_view,
    since this module has no need for that function's extent-tracking
    contract (project_latlon_to_pixel reprojection isn't used anywhere
    here — every pin/route position is drawn as a real deck.gl layer, not
    OpenCV-composited onto a screenshotted raster). `pad_frac` pads the
    fitted bbox so pins/route endpoints aren't flush against frame edges.
    """
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    lat_pad = max((max_lat - min_lat) * pad_frac, 0.0005)
    lon_pad = max((max_lon - min_lon) * pad_frac, 0.0005)
    min_lat, max_lat = min_lat - lat_pad, max_lat + lat_pad
    min_lon, max_lon = min_lon - lon_pad, max_lon + lon_pad

    center_lat = (min_lat + max_lat) / 2.0
    center_lon = (min_lon + max_lon) / 2.0
    out_w, out_h = output_size

    lat_span_m = (max_lat - min_lat) * (math.pi / 180.0) * _R
    lon_span_m = (max_lon - min_lon) * (math.pi / 180.0) * _R * math.cos(math.radians(center_lat))

    meters_per_pixel = max(lat_span_m / out_h, lon_span_m / out_w)
    zoom = math.log2(_EARTH_CIRCUMFERENCE_M / (_TILE_SIZE_PX * meters_per_pixel))
    return center_lon, center_lat, zoom


def _ease_in_out_cubic(t: float) -> float:
    """Standard ease-in-out cubic (0..1 -> 0..1) -- used to shape the
    top-down/chase-cam transitions (see `topdown_transition_seconds` on
    render_residential_leg_pydeck) so they read as a smooth cinematic
    camera move rather than a linear ramp."""
    t = max(0.0, min(1.0, t))
    return 4 * t * t * t if t < 0.5 else 1 - pow(-2 * t + 2, 3) / 2


_WEBMERCATOR_EARTH_CIRCUMFERENCE_M = 2 * math.pi * 6378137.0
_WEBMERCATOR_TILE_PX = 512  # deck.gl/Mapbox GL's own zoom convention (world = 512 * 2**zoom px)


def _fit_view_for_path(
    lons: List[float], lats: List[float],
    output_size: Tuple[int, int],
    padding_frac: float = 0.05,
    pitch: float = 0.0,
    bottom_margin_px: float = 100.0,
    top_margin_px: float = 100.0,
) -> Tuple[float, float, float]:
    """Center (lon, lat) and Mapbox GL zoom that fits every point of
    `lons`/`lats` inside `output_size`, padded by `padding_frac` on each
    side -- the "locked" camera framing used for a leg's whole walking
    animation (see render_residential_leg_pydeck's locked-camera
    docstring): unlike `follow_zoom` (sized for a close, street-level
    chase-cam), this is sized to keep the ENTIRE leg's path on screen at
    once. `top_margin_px`/`bottom_margin_px` keep taller clear bands (the
    corner banners, the burned-in caption) and center the path between them."""
    lat_min, lat_max = min(lats), max(lats)
    lon_min, lon_max = min(lons), max(lons)
    lat_span = lat_max - lat_min

    if pitch > 0:
        pitch_rad = math.radians(min(pitch, 75.0))
        # A pitched camera shrinks the horizontal field of view at the bottom
        # of the screen due to perspective. We must pad the bounding box
        # proportionately more to keep the bottom corners in frame.
        # cos(pitch) exactly models the horizontal squeeze at the target plane.
        # proportionately more to keep the bottom corners in frame, but scale
        # the effect down so it doesn't zoom out *too* far and make the path tiny.
        padding_frac += ((1.0 / math.cos(pitch_rad)) - 1.0) * 0.4

        # It also shifts the vertical center of the visible ground plane far
        # upwards. We counteract this by pulling the camera's target coordinate
        # south (downwards), so the bounding box remains centered in the
        # trapezoidal visible area instead of clinging to the bottom edge.
        lat_shift_frac = math.sin(pitch_rad) * 0.2
        lat_min -= lat_span * lat_shift_frac
        lat_max -= lat_span * lat_shift_frac

    center_lat = (lat_min + lat_max) / 2.0
    center_lon = (lon_min + lon_max) / 2.0

    lon_scale = math.cos(math.radians(center_lat))
    meters_per_deg_lat = 111_320.0
    meters_per_deg_lon = 111_320.0 * lon_scale
    lat_span_m = max((lat_max - lat_min) * meters_per_deg_lat, 1.0)
    lon_span_m = max((lon_max - lon_min) * meters_per_deg_lon, 1.0)

    out_w, out_h = output_size
    # `padding_frac` alone only pads the path's own geographic bounding box
    # by a PERCENTAGE of its span -- fine for a long leg, but the start/dest
    # pins and their name pills take up a FIXED number of screen pixels
    # (the pin extends ~80px above its point, its label pill another ~40px
    # below), so on a short/tight leg a percentage of a small span still
    # isn't enough actual pixels to keep them on screen -- the marker at
    # the bbox edge gets clipped by the frame. Subtracting this fixed pixel
    # margin from the usable width/height (on top of the existing
    # percentage padding) guarantees that much real screen space around the
    # path regardless of how small its own span is.
    _marker_margin_px = 100.0
    bottom_margin_px = max(_marker_margin_px, bottom_margin_px)
    top_margin_px = max(_marker_margin_px, top_margin_px)
    usable_h = max(1.0, out_h - top_margin_px - bottom_margin_px)
    usable_w = max(1.0, out_w - 2.0 * _marker_margin_px)
    pad = 1.0 + padding_frac
    # Web Mercator stretches north-south by 1/cos(lat), same as east-west.
    zoom_for_lat = math.log2(
        _WEBMERCATOR_EARTH_CIRCUMFERENCE_M * lon_scale * usable_h / (_WEBMERCATOR_TILE_PX * lat_span_m * pad)
    )
    zoom_for_lon = math.log2(
        _WEBMERCATOR_EARTH_CIRCUMFERENCE_M * lon_scale * usable_w / (_WEBMERCATOR_TILE_PX * lon_span_m * pad)
    )
    zoom = min(zoom_for_lat, zoom_for_lon)
    # Shift the camera so the path sits centered between the two margins
    # (south when the bottom band is taller).
    shift_px = (bottom_margin_px - top_margin_px) / 2.0
    if shift_px:
        meters_per_px = _WEBMERCATOR_EARTH_CIRCUMFERENCE_M * lon_scale / (_WEBMERCATOR_TILE_PX * 2.0 ** zoom)
        center_lat -= shift_px * meters_per_px / meters_per_deg_lat
    return center_lon, center_lat, zoom


# A stop-by farther than this from the route is left out of the camera frame: fitting it would shrink the walk.
_FRAME_STOPBY_MAX_M = 500.0


def _framed_points(df_raw, lo: int, hi: int, landmarks) -> Tuple[List[float], List[float]]:
    """(lons, lats) of the path rows `lo:hi` plus every stop-by within _FRAME_STOPBY_MAX_M of the
    route whose nearest path row falls in that stretch, so a stop-by seen from the route is inside
    the leg's camera frame too."""
    part = df_raw.iloc[lo:hi]
    lons, lats = part["lon"].tolist(), part["lat"].tolist()
    for lm in (landmarks or []):
        lat, lon = lm.get("lat"), lm.get("lon")
        if lat is None or lon is None:
            continue
        dlat = (df_raw["lat"] - lat) * 111_320.0
        dlon = (df_raw["lon"] - lon) * 111_320.0 * math.cos(math.radians(lat))
        gap = (dlat ** 2 + dlon ** 2).to_numpy()
        nearest = int(gap.argmin())
        if lo <= nearest < hi and gap[nearest] <= _FRAME_STOPBY_MAX_M ** 2:
            lons.append(float(lon))
            lats.append(float(lat))
    return lons, lats


# Top clearance for a leg's locked framing, measured to a pin's POINT: the
# corner banners (#hud-banner/#hud-chain: 24px down, ~70px tall), a 16px gap,
# then the 60px pin standing above its point.
_LEG_TOP_MARGIN_PX = 24.0 + 70.0 + 16.0 + 60.0


def _leg_bottom_margin_px(bottom_reserve_px: float) -> float:
    """Bottom margin for a leg's locked framing: the caption band plus room
    for the start pin's name pill under its point."""
    return max(100.0, float(bottom_reserve_px or 0.0) + 60.0)


def _project_lonlat_to_px(
    lon: float, lat: float,
    view_lon: float, view_lat: float, zoom: float,
    output_size: Tuple[int, int],
    pitch: float = 0.0,
) -> Tuple[float, float]:
    """Screen pixel a (lon, lat) point projects to under a north-up
    Mapbox GL view centered on (view_lon, view_lat) at `zoom`, with an
    optional camera `pitch` (tilt).
    
    This matches the Web Mercator projection and 3D camera model deck.gl
    uses, allowing a marker's on-screen position to be accurately computed
    in Python (so HTML overlays can be perfectly anchored to it)."""
    scale = _WEBMERCATOR_TILE_PX * (2.0 ** zoom)

    def merc_x(lon_: float) -> float:
        return (lon_ + 180.0) / 360.0 * scale

    def merc_y(lat_: float) -> float:
        sin_lat = max(-0.9999, min(0.9999, math.sin(math.radians(lat_))))
        return (0.5 - math.log((1.0 + sin_lat) / (1.0 - sin_lat)) / (4.0 * math.pi)) * scale

    out_w, out_h = output_size
    center_x, center_y = merc_x(view_lon), merc_y(view_lat)
    
    # World point relative to target
    dx = merc_x(lon) - center_x
    dy = center_y - merc_y(lat)  # Mapbox world Y is positive North (up)

    if pitch > 0:
        # Camera distance to target (deck.gl default altitude is 1.5 viewport heights)
        d = 1.5 * out_h
        pitch_rad = math.radians(pitch)
        sin_p = math.sin(pitch_rad)
        cos_p = math.cos(pitch_rad)
        
        # 3D projection mapping
        depth = d + dy * sin_p
        if depth <= 0:
            depth = 0.0001  # Prevent division by zero behind camera
            
        px = out_w / 2.0 + (dx * d / depth)
        py = out_h / 2.0 - (dy * cos_p * d / depth)
    else:
        px = out_w / 2.0 + dx
        py = out_h / 2.0 - dy

    return px, py


def _nearest_index(route_latlon: List[Tuple[float, float]], lat: float, lon: float) -> int:
    best_i, best_d = 0, float("inf")
    for i, (rlat, rlon) in enumerate(route_latlon):
        d = (rlat - lat) ** 2 + (rlon - lon) ** 2  # plain squared-degree distance — only used to RANK points, never as a real distance
        if d < best_d:
            best_d, best_i = d, i
    return best_i


def _point_at_fraction(route_lonlat: List[List[float]], cum_km: List[float], total_km: float, frac: float) -> List[List[float]]:
    """The route polyline truncated (with the final partial segment
    linearly interpolated) at real fractional distance `frac` (0..1) along
    the route -- what a "the line has drawn this far" frame actually
    needs, not just a truncated point INDEX (which would visibly jump in
    steps between original GPS points instead of animating smoothly)."""
    if frac <= 0:
        return [route_lonlat[0]]
    if frac >= 1:
        return route_lonlat
    target = frac * total_km
    for i in range(1, len(cum_km)):
        if cum_km[i] >= target:
            seg_km = cum_km[i] - cum_km[i - 1]
            t = (target - cum_km[i - 1]) / seg_km if seg_km > 0 else 0.0
            lon0, lat0 = route_lonlat[i - 1]
            lon1, lat1 = route_lonlat[i]
            interp = [lon0 + (lon1 - lon0) * t, lat0 + (lat1 - lat0) * t]
            return route_lonlat[:i] + [interp]
    return route_lonlat


def _clear_card_spot(route_px, mx, my, w, h, gap, margin, out_w, out_h) -> Tuple[float, float]:
    """(left, top) of a w x h card beside the marker at (mx, my) that covers the
    fewest route points: above first (the old spot), then below, right, left, diagonals."""
    pad = 10.0  # the route line's own width
    spots = [
        (mx - w / 2, my - gap - h), (mx - w / 2, my + gap), (mx + gap, my - h / 2), (mx - gap - w, my - h / 2),
        (mx + gap, my - gap - h), (mx - gap - w, my - gap - h), (mx + gap, my + gap), (mx - gap - w, my + gap),
    ]

    def clamp(left, top):
        return min(max(left, margin), out_w - w - margin), min(max(top, margin), out_h - h - margin)

    def covered(spot):
        left, top = spot
        return sum(left - pad <= x <= left + w + pad and top - pad <= y <= top + h + pad for x, y in route_px)

    return min((clamp(*s) for s in spots), key=covered)
