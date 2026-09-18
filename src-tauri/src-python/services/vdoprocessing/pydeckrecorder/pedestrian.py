"""GeoJsonLayer-driven pedestrian route rendering: an OVERVIEW function
(whole-route map, numbered waypoint pins) and a RESIDENTIAL/leg function
(tilted, bearing-following chase camera with a turn-by-turn HUD banner +
distance/time card).

Both are deliberately self-contained, plain-argument functions — no
RouteAnimator/job_config coupling — so each can be called and verified in
isolation before route2vdo.py's full pipeline ever dispatches a real project
through them. See the pydeckrecorder package's recorder.py/renderer.py for
the sibling DRIVING-mode (vehicle scenegraph) pipeline this deliberately
does not touch.
"""

from __future__ import annotations

import asyncio
import bisect
import json
import math
import os
import random
import shutil
import tempfile
import urllib.parse
from typing import Dict, List, Optional, Tuple

import pandas as pd
import pydeck as pdk

from services import tuning

from .common import MAPBOX_API_KEY, logger
from .geomath import cumulative_distance_km, haversine_km
from .httpserver import start_local_server
from .popupsequence import _wait_for_paint
from .recorder import _route_linestring_feature
from .routedata import interpolate_route_data, patch_pydeck_html

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

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


_CAPTION_CSS = """
#section-caption {
    position: fixed; top: 40px; left: 50%; transform: translateX(-50%);
    background: rgba(30, 34, 40, 0.82); color: #fff;
    font-family: "Noto Sans JP", sans-serif; font-weight: 700; font-size: 28px;
    padding: 14px 36px; border-radius: 999px; box-shadow: 0 4px 14px rgba(0,0,0,0.35);
    white-space: nowrap; z-index: 1000;
}
"""


async def _capture_static(
    html_path: str, html_dir: str, output_size: Tuple[int, int], output_path: str,
    caption_text: Optional[str] = None,
) -> None:
    """`caption_text`, when given, overlays a wide centered title pill (the
    reference video's section-title caption, e.g. "友ヶ島・加太をめぐる道" --
    distinct from render_residential_leg_pydeck's per-leg destination
    banner, which names a specific stop rather than the trip/section as a
    whole) before the screenshot is taken."""
    from playwright.async_api import async_playwright

    server, port = start_local_server(html_dir)
    try:
        rel_path = os.path.relpath(html_path, html_dir).replace("\\", "/")
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(viewport={"width": output_size[0], "height": output_size[1]})
                page = await context.new_page()
                await page.goto(f"http://127.0.0.1:{port}/{rel_path}")
                try:
                    await page.wait_for_load_state("load", timeout=5000)
                except Exception:
                    pass
                await page.wait_for_timeout(2500)
                if caption_text:
                    await page.evaluate(
                        """([css, text]) => {
                            const style = document.createElement('style');
                            style.textContent = css;
                            document.head.appendChild(style);
                            const caption = document.createElement('div');
                            caption.id = 'section-caption';
                            caption.textContent = text;
                            document.body.appendChild(caption);
                        }""",
                        [_CAPTION_CSS, caption_text],
                    )
                await page.screenshot(path=output_path)
            finally:
                await browser.close()
    finally:
        server.shutdown()
        server.server_close()


def _landmark_layers(landmarks: List[Dict], id_prefix: str = "stopby") -> List[pdk.Layer]:
    """landmarks: [{"lat", "lon", ("label")}, ...] -- small unnumbered brown
    dots with a plain label beside them, matching the reference video's
    landmark markers (e.g. a named junction/torii passed along the way):
    visually distinct from, and smaller than, the numbered orange pins
    real stops get. Used both for job_config.json stop-by waypoints
    (overview) and a leg's merged-in mid_markers (residential)."""
    if not landmarks:
        return []
    dots = [{"lon": lm["lon"], "lat": lm["lat"]} for lm in landmarks]
    labels = [{"lon": lm["lon"], "lat": lm["lat"], "text": str(lm.get("label") or "")} for lm in landmarks]
    return [
        pdk.Layer(
            "ScatterplotLayer", id=f"{id_prefix}-dots", data=dots,
            get_position="[lon, lat]", get_fill_color=[120, 80, 50, 255],
            get_radius=4, radius_min_pixels=6,
            stroked=True, get_line_color=[255, 255, 255, 220], line_width_min_pixels=1,
        ),
        pdk.Layer(
            "TextLayer", id=f"{id_prefix}-labels", data=labels,
            get_position="[lon, lat]", get_text="text", get_size=13,
            get_color=[40, 30, 20, 255], background=True,
            get_background_color=[255, 255, 255, 200],
            # Backtick-wrapped (not just double-quoted) so pydeck's own
            # quote-stripping (pydeck wraps every plain string kwarg as a
            # JS expression unless it's itself quote-wrapped -- see
            # QUOTE_CHARS in pydeck/bindings/layer.py) doesn't eat the CSS
            # value's OWN double quotes around "Noto Sans JP" -- plain double
            # quotes here would both fail pydeck's v[0]==v[-1] check (this
            # string's last char is "f", not a quote) and collide with the
            # font name's own quoting even if it didn't.
            font_family='`"Noto Sans JP", sans-serif`',
            get_pixel_offset="[0, -14]",
        ),
    ]


def _pin_layers(waypoints: List[Dict]) -> List[pdk.Layer]:
    """waypoints: [{"lat", "lon", "order", ("label"), ("is_stopby")}, ...].
    A stop-by waypoint (isStopBy in job_config.json -- a place the route
    passes near but doesn't really "stop" at) is drawn via _landmark_layers
    instead of getting a numbered pin -- mirrors spatial_renderer's own
    stop-by/numbering split (see overview.py's active_popups "order"
    handling: a stop-by is excluded from the visible 1..N count)."""
    numbered = [wp for wp in waypoints if not wp.get("is_stopby")]
    stopbys = [wp for wp in waypoints if wp.get("is_stopby")]

    dots = [{"lon": wp["lon"], "lat": wp["lat"]} for wp in numbered]
    labels = [{"lon": wp["lon"], "lat": wp["lat"], "text": str(wp["order"])} for wp in numbered]
    layers = [
        pdk.Layer(
            "ScatterplotLayer", id="wp-dots", data=dots,
            get_position="[lon, lat]", get_fill_color=[230, 80, 20, 255],
            get_radius=8, radius_min_pixels=14,
            stroked=True, get_line_color=[255, 255, 255, 255], line_width_min_pixels=2,
        ),
        pdk.Layer(
            "TextLayer", id="wp-labels", data=labels,
            get_position="[lon, lat]", get_text="text", get_size=16,
            get_color=[255, 255, 255, 255], font_family='`"Noto Sans JP", sans-serif`',
            font_weight="'bold'", get_alignment_baseline="'center'",
        ),
    ]
    layers.extend(_landmark_layers(stopbys))
    return layers


# A teardrop map-pin (tip pointing straight down at its anchor point),
# colored to match the overview's own numbered waypoint pins (see
# _pin_layers' "wp-dots" above: fill [230, 80, 20], white ring) rather than
# its own separate palette -- same flat orange fill, white outline, plus a
# soft drop shadow for the raised, "sitting on the map" look a flat
# scatterplot dot doesn't have. The inner circle is cut out via
# fill-rule="evenodd" (a true hole, not a solid white disc), so the map
# shows through it exactly like a standard pin icon's punched-out center.
_TEARDROP_PIN_W, _TEARDROP_PIN_H = 384, 512
_TEARDROP_PIN_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 384 512" '
    f'width="{_TEARDROP_PIN_W}" height="{_TEARDROP_PIN_H}">'
    "<defs>"
    '<filter id="pinShadow" x="-60%" y="-60%" width="220%" height="220%">'
    '<feDropShadow dx="0" dy="6" stdDeviation="6" flood-color="#000" flood-opacity="0.4"/>'
    "</filter>"
    "</defs>"
    '<path filter="url(#pinShadow)" fill-rule="evenodd" fill="#e65014" '
    'stroke="#ffffff" stroke-width="10" '
    'd="M172.268 501.67C26.97 291.031 0 269.413 0 192 0 85.961 85.961 0 192 0s192 85.961 '
    "192 192c0 77.413-26.97 99.031-172.268 309.67-9.535 13.774-29.93 13.774-39.464 "
    "0zM192 272c44.183 0 80-35.817 80-80s-35.817-80-80-80-80 35.817-80 80 35.817 80 80 "
    '80z"/>'
    "</svg>"
)
_TEARDROP_PIN_URL = "data:image/svg+xml;charset=utf-8," + urllib.parse.quote(_TEARDROP_PIN_SVG)


# ---------------------------------------------------------------------------
# OVERVIEW: whole-route static map, GeoJsonLayer route + numbered pins
# ---------------------------------------------------------------------------

def render_overview_pydeck(
    route_latlon: List[Tuple[float, float]],
    waypoints: List[Dict],
    output_path: str,
    output_size: Tuple[int, int] = (1920, 1080),
    mapbox_key: Optional[str] = None,
    map_style: str = "mapbox://styles/mapbox/streets-v12",
    line_color: List[int] = None,
    title_text: Optional[str] = None,
) -> str:
    """Renders a single static overview image: the full route as a real
    GeoJSON LineString (via GeoJsonLayer) plus numbered waypoint pins, over
    a live Mapbox basemap — the GeoJsonLayer analogue of spatial_renderer's
    OpenCV-composited overview.render_overview, but for the whole route at
    once rather than an animated line-draw.

    `route_latlon`: [(lat, lon), ...] the full route polyline.
    `waypoints`: [{"lat", "lon", "order", ...}, ...] pins to number/draw.
    `title_text`: optional section-title caption (e.g. the trip's own
    name) overlaid as a wide centered pill, matching the reference video's
    title card -- distinct from a per-leg destination banner.
    Returns `output_path`.
    """
    if not route_latlon:
        raise ValueError("route_latlon must not be empty")

    lats = [p[0] for p in route_latlon] + [wp["lat"] for wp in waypoints]
    lons = [p[1] for p in route_latlon] + [wp["lon"] for wp in waypoints]
    center_lon, center_lat, zoom = _bbox_view(lats, lons, output_size)

    route_lonlat = [[lon, lat] for lat, lon in route_latlon]
    layers = [
        pdk.Layer(
            "GeoJsonLayer", id="overview-route",
            data=_route_linestring_feature(route_lonlat, line_color=line_color or [255, 255, 255, 230]),
            stroked=True, filled=False, get_line_color="properties.line_color",
            line_width_scale=1, line_width_min_pixels=4,
        ),
    ] + _pin_layers(waypoints)

    view_state = pdk.ViewState(longitude=center_lon, latitude=center_lat, zoom=zoom, pitch=0, bearing=0)
    deck = pdk.Deck(
        layers=layers, initial_view_state=view_state,
        map_provider="mapbox", map_style=map_style,
        api_keys={"mapbox": mapbox_key or MAPBOX_API_KEY},
        views=[pdk.View(type="MapView", controller=False)],
    )

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="navivi_pydeck_overview_") as html_dir:
        html_path = os.path.join(html_dir, "overview.html")
        deck.to_html(html_path)
        patch_pydeck_html(html_path)
        asyncio.run(_capture_static(html_path, html_dir, output_size, output_path, caption_text=title_text))

    logger.info(f"Overview rendered: {output_path}")
    return output_path


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
    padding_frac: float = 0.25,
) -> Tuple[float, float, float]:
    """Center (lon, lat) and Mapbox GL zoom that fits every point of
    `lons`/`lats` inside `output_size`, padded by `padding_frac` on each
    side -- the "locked" camera framing used for a leg's whole walking
    animation (see render_residential_leg_pydeck's locked-camera
    docstring): unlike `follow_zoom` (sized for a close, street-level
    chase-cam), this is sized to keep the ENTIRE leg's path on screen at
    once."""
    lat_min, lat_max = min(lats), max(lats)
    lon_min, lon_max = min(lons), max(lons)
    center_lat = (lat_min + lat_max) / 2.0
    center_lon = (lon_min + lon_max) / 2.0

    lon_scale = math.cos(math.radians(center_lat))
    meters_per_deg_lat = 111_320.0
    meters_per_deg_lon = 111_320.0 * lon_scale
    lat_span_m = max((lat_max - lat_min) * meters_per_deg_lat, 1.0)
    lon_span_m = max((lon_max - lon_min) * meters_per_deg_lon, 1.0)

    out_w, out_h = output_size
    pad = 1.0 + padding_frac
    zoom_for_lat = math.log2(
        _WEBMERCATOR_EARTH_CIRCUMFERENCE_M * out_h / (_WEBMERCATOR_TILE_PX * lat_span_m * pad)
    )
    zoom_for_lon = math.log2(
        _WEBMERCATOR_EARTH_CIRCUMFERENCE_M * lon_scale * out_w / (_WEBMERCATOR_TILE_PX * lon_span_m * pad)
    )
    zoom = min(zoom_for_lat, zoom_for_lon)
    return center_lon, center_lat, zoom


def _project_lonlat_to_px(
    lon: float, lat: float,
    view_lon: float, view_lat: float, zoom: float,
    output_size: Tuple[int, int],
) -> Tuple[float, float]:
    """Screen pixel a (lon, lat) point projects to under a north-up,
    zero-pitch Mapbox GL view centered on (view_lon, view_lat) at `zoom` --
    the plain Web Mercator math deck.gl itself uses, reimplemented here so a
    marker's on-screen position can be computed directly in Python (the
    LOCKED camera's viewState is already known ahead of time -- see
    render_residential_leg_pydeck's `locked_lon`/`locked_lat`/`locked_zoom`
    -- so there's no need to round-trip through the page to ask deck.gl for
    it). Only valid for pitch 0 / bearing 0, which is what the locked leg
    camera actually uses."""
    scale = _WEBMERCATOR_TILE_PX * (2.0 ** zoom)

    def merc_x(lon_: float) -> float:
        return (lon_ + 180.0) / 360.0 * scale

    def merc_y(lat_: float) -> float:
        sin_lat = max(-0.9999, min(0.9999, math.sin(math.radians(lat_))))
        return (0.5 - math.log((1.0 + sin_lat) / (1.0 - sin_lat)) / (4.0 * math.pi)) * scale

    out_w, out_h = output_size
    center_x, center_y = merc_x(view_lon), merc_y(view_lat)
    px = out_w / 2.0 + (merc_x(lon) - center_x)
    py = out_h / 2.0 + (merc_y(lat) - center_y)
    return px, py


def _nearest_index(route_latlon: List[Tuple[float, float]], lat: float, lon: float) -> int:
    best_i, best_d = 0, float("inf")
    for i, (rlat, rlon) in enumerate(route_latlon):
        d = (rlat - lat) ** 2 + (rlon - lon) ** 2  # plain squared-degree distance — only used to RANK points, never as a real distance
        if d < best_d:
            best_d, best_i = d, i
    return best_i


def render_overview_video_pydeck(
    route_latlon: List[Tuple[float, float]],
    waypoints: List[Dict],
    output_path: str,
    duration: float = 30.0,
    fps: int = 30,
    output_size: Tuple[int, int] = (1920, 1080),
    mapbox_key: Optional[str] = None,
    map_style: str = "mapbox://styles/mapbox/streets-v12",
    line_color: List[int] = None,
    progress_color: List[int] = None,
    title_text: Optional[str] = None,
    hold_seconds: float = 3.0,
) -> str:
    """An ANIMATED overview video: the route line draws itself in
    progressively (a bright `progress_color` line growing over the full
    route's own faint `line_color` backdrop) with a traveler dot leading
    it, and each waypoint's pin fades in the moment the drawn line reaches
    its nearest point on the route — the GeoJsonLayer analogue of
    spatial_renderer.render_overview's own animated line-draw, replacing
    this function's previous static-hold placeholder (one screenshot held
    for the whole clip). Ends by holding on the finished, fully-drawn frame
    for `hold_seconds` so the complete route/pins are visible before the
    clip ends, same as the old renderer's own trailing hold.
    """
    if not route_latlon:
        raise ValueError("route_latlon must not be empty")

    lats = [p[0] for p in route_latlon] + [wp["lat"] for wp in waypoints]
    lons = [p[1] for p in route_latlon] + [wp["lon"] for wp in waypoints]
    center_lon, center_lat, zoom = _bbox_view(lats, lons, output_size)

    route_lonlat = [[lon, lat] for lat, lon in route_latlon]
    line_color = line_color or [255, 255, 255, 160]
    progress_color = progress_color or [255, 140, 0, 230]

    # Each waypoint's own fractional position along the route (by real
    # cumulative distance, not point-index) — a stop-by/waypoint's pin
    # fades in once the drawn line passes the route point closest to it.
    route_lats = [p[0] for p in route_latlon]
    route_lons = [p[1] for p in route_latlon]
    cum_km = [0.0]
    for i in range(1, len(route_latlon)):
        cum_km.append(cum_km[-1] + haversine_km(route_lons[i - 1], route_lats[i - 1], route_lons[i], route_lats[i]))
    total_km = cum_km[-1] if cum_km[-1] > 0 else 1.0
    for wp in waypoints:
        idx = _nearest_index(route_latlon, wp["lat"], wp["lon"])
        wp["_reveal_frac"] = cum_km[idx] / total_km

    base_layers = [
        pdk.Layer(
            "GeoJsonLayer", id="overview-route-full",
            data=_route_linestring_feature(route_lonlat, line_color=line_color),
            stroked=True, filled=False, get_line_color="properties.line_color",
            line_width_scale=1, line_width_min_pixels=4,
        ),
    ]
    view_state = pdk.ViewState(longitude=center_lon, latitude=center_lat, zoom=zoom, pitch=0, bearing=0)
    deck = pdk.Deck(
        layers=base_layers, initial_view_state=view_state,
        map_provider="mapbox", map_style=map_style,
        api_keys={"mapbox": mapbox_key or MAPBOX_API_KEY},
        views=[pdk.View(type="MapView", controller=False)],
    )

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="navivi_pydeck_overview_anim_") as html_dir:
        html_path = os.path.join(html_dir, "overview.html")
        deck.to_html(html_path)
        patch_pydeck_html(html_path)
        asyncio.run(_record_overview(
            html_path, html_dir, output_size, output_path, fps, duration, hold_seconds,
            route_lonlat, cum_km, total_km, waypoints, progress_color, title_text,
        ))

    logger.info(f"Overview (animated) video rendered: {output_path}")
    return output_path


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


async def _record_overview(
    html_path, html_dir, output_size, output_path, fps, duration, hold_seconds,
    route_lonlat, cum_km, total_km, waypoints, progress_color, title_text,
):
    from playwright.async_api import async_playwright
    from services.vdoprocessing.vdoeditor import FFmpegEngine

    editor = FFmpegEngine()
    ffmpeg_cmd = [
        editor.resolve_binary(), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "image2pipe", "-vcodec", "png", "-framerate", str(fps), "-i", "-",
        "-c:v", "libx264", *tuning.ffmpeg_thread_args(),
        "-r", str(fps), "-pix_fmt", "yuv420p", output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *ffmpeg_cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL
    )

    draw_duration = max(1.0, duration - hold_seconds)
    draw_frames = max(1, int(draw_duration * fps))
    hold_frames = max(0, int(hold_seconds * fps))

    server, port = start_local_server(html_dir)
    try:
        rel_path = os.path.relpath(html_path, html_dir).replace("\\", "/")
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(viewport={"width": output_size[0], "height": output_size[1]})
                page = await context.new_page()
                page.on("pageerror", lambda exc: logger.error(f"  [PAGE ERROR] {exc}"))
                await page.goto(f"http://127.0.0.1:{port}/{rel_path}")
                try:
                    await page.wait_for_load_state("load", timeout=5000)
                except Exception:
                    pass
                await page.wait_for_timeout(2500)

                if title_text:
                    await page.evaluate(
                        """([css, text]) => {
                            const style = document.createElement('style');
                            style.textContent = css;
                            document.head.appendChild(style);
                            const caption = document.createElement('div');
                            caption.id = 'section-caption';
                            caption.textContent = text;
                            document.body.appendChild(caption);
                        }""",
                        [_CAPTION_CSS, title_text],
                    )

                c_progress = json.dumps(progress_color)

                async def draw_frame(frac: float):
                    drawn = _point_at_fraction(route_lonlat, cum_km, total_km, frac)
                    progress_geojson = json.dumps(_route_linestring_feature(drawn, line_color=progress_color)) \
                        if len(drawn) >= 2 else json.dumps({"type": "FeatureCollection", "features": []})
                    revealed = [wp for wp in waypoints if wp["_reveal_frac"] <= frac]
                    dots = [{"lon": wp["lon"], "lat": wp["lat"]} for wp in revealed if not wp.get("is_stopby")]
                    labels = [
                        {"lon": wp["lon"], "lat": wp["lat"], "text": str(wp["order"])}
                        for wp in revealed if not wp.get("is_stopby")
                    ]
                    stopby_dots = [{"lon": wp["lon"], "lat": wp["lat"]} for wp in revealed if wp.get("is_stopby")]
                    stopby_labels = [
                        {"lon": wp["lon"], "lat": wp["lat"], "text": str(wp.get("label") or "")}
                        for wp in revealed if wp.get("is_stopby")
                    ]
                    traveler = drawn[-1]
                    traveler_json = json.dumps([{"lon": traveler[0], "lat": traveler[1]}])

                    js = f"""
                    if (window.deckgl) {{
                        const currentLayers = window.deckgl.props.layers || [];
                        const staticLayers = currentLayers.filter(l =>
                            !['overview-progress', 'overview-traveler', 'overview-traveler-halo',
                              'anim-wp-dots', 'anim-wp-labels', 'anim-stopby-dots', 'anim-stopby-labels'].includes(l.id)
                        );
                        const newProgress = new deck.GeoJsonLayer({{
                            id: 'overview-progress', data: {progress_geojson},
                            stroked: true, filled: false, getLineColor: d => d.properties.line_color,
                            lineWidthScale: 1, lineWidthMinPixels: 5
                        }});
                        const newHalo = new deck.ScatterplotLayer({{
                            id: 'overview-traveler-halo', data: {traveler_json},
                            getPosition: d => [d.lon, d.lat], getFillColor: {c_progress}.slice(0,3).concat([90]),
                            getRadius: 6, radiusMinPixels: 14
                        }});
                        const newTraveler = new deck.ScatterplotLayer({{
                            id: 'overview-traveler', data: {traveler_json},
                            getPosition: d => [d.lon, d.lat], getFillColor: [255, 255, 255, 255],
                            getLineColor: {c_progress}, stroked: true, lineWidthMinPixels: 2,
                            getRadius: 2, radiusMinPixels: 6
                        }});
                        const wpDots = new deck.ScatterplotLayer({{
                            id: 'anim-wp-dots', data: {json.dumps(dots)},
                            getPosition: d => [d.lon, d.lat], getFillColor: [230, 80, 20, 255],
                            getRadius: 8, radiusMinPixels: 14,
                            stroked: true, getLineColor: [255, 255, 255, 255], lineWidthMinPixels: 2
                        }});
                        const wpLabels = new deck.TextLayer({{
                            id: 'anim-wp-labels', data: {json.dumps(labels)},
                            getPosition: d => [d.lon, d.lat], getText: d => d.text, getSize: 16,
                            getColor: [255, 255, 255, 255], fontFamily: '"Noto Sans JP", sans-serif',
                            fontWeight: 'bold', getAlignmentBaseline: 'center'
                        }});
                        const stopbyDots = new deck.ScatterplotLayer({{
                            id: 'anim-stopby-dots', data: {json.dumps(stopby_dots)},
                            getPosition: d => [d.lon, d.lat], getFillColor: [120, 80, 50, 255],
                            getRadius: 4, radiusMinPixels: 6,
                            stroked: true, getLineColor: [255, 255, 255, 220], lineWidthMinPixels: 1
                        }});
                        const stopbyLabels = new deck.TextLayer({{
                            id: 'anim-stopby-labels', data: {json.dumps(stopby_labels)},
                            getPosition: d => [d.lon, d.lat], getText: d => d.text, getSize: 13,
                            getColor: [40, 30, 20, 255], background: true,
                            getBackgroundColor: [255, 255, 255, 200],
                            fontFamily: '"Noto Sans JP", sans-serif', getPixelOffset: [0, -14]
                        }});
                        window.deckgl.setProps({{
                            layers: [...staticLayers, newProgress, newHalo, newTraveler,
                                      wpDots, wpLabels, stopbyDots, stopbyLabels]
                        }});
                    }}
                    """
                    await page.evaluate(js)
                    await page.wait_for_timeout(15)
                    return await page.screenshot()

                for i in range(draw_frames):
                    frac = (i + 1) / draw_frames
                    png_bytes = await draw_frame(frac)
                    proc.stdin.write(png_bytes)
                    await proc.stdin.drain()

                final_png = await draw_frame(1.0)
                for _ in range(hold_frames):
                    proc.stdin.write(final_png)
                    await proc.stdin.drain()
            finally:
                await browser.close()
    finally:
        server.shutdown()
        server.server_close()

    proc.stdin.close()
    await proc.wait()


# ---------------------------------------------------------------------------
# RESIDENTIAL: per-leg tilted chase camera + turn-by-turn HUD
# ---------------------------------------------------------------------------

_HUD_CSS = """
#hud-banner {
    position: fixed; top: 24px; right: 24px;
    background: rgba(30, 34, 40, 0.88); color: #fff;
    font-family: "Noto Sans JP", sans-serif; font-weight: 700; font-size: 22px;
    padding: 12px 28px; border-radius: 999px; box-shadow: 0 4px 14px rgba(0,0,0,0.35);
    white-space: nowrap; z-index: 1000;
}
#hud-card {
    position: fixed; bottom: 32px; right: 32px;
    background: #fff; border: 3px solid #e53935; border-radius: 22px;
    padding: 18px 36px; display: flex; align-items: center; gap: 28px;
    font-family: "Noto Sans JP", sans-serif; box-shadow: 0 6px 20px rgba(0,0,0,0.35);
    z-index: 1000;
}
#hud-card .metric { text-align: center; }
#hud-card .metric .label { font-size: 15px; color: #555; display: flex; align-items: center; justify-content: center; gap: 6px; }
#hud-card .metric .value { font-size: 32px; font-weight: 700; color: #111; margin-top: 2px; }
#hud-card .divider { width: 1px; height: 46px; background: #ddd; }
#hud-card .icon { width: 20px; height: 20px; line-height: 1; }
#hud-card .icon svg { display: block; width: 100%; height: 100%; }
#hud-banner .icon { font-size: 20px; line-height: 1; }
#hud-chain {
    position: fixed; top: 24px; left: 24px;
    background: rgba(30, 34, 40, 0.72); color: #fff;
    font-family: "Noto Sans JP", sans-serif; font-weight: 700; font-size: 16px;
    padding: 8px 20px; border-radius: 999px; box-shadow: 0 4px 14px rgba(0,0,0,0.35);
    white-space: nowrap; z-index: 1000;
}
#hud-chain .arrow { opacity: 0.6; margin: 0 6px; }
"""

# Per-mode distance-card icon: a plain black line-drawing SVG (currentColor
# stroke, no fill) instead of a platform emoji -- emoji glyphs are
# multicolor bitmaps that ignore CSS `color`, which is what "colored icon"
# meant here; a stroked SVG reads as a clean black/white pictogram matching
# the rest of the card's plain black-on-white styling regardless of the
# host's emoji font.
_MODE_ICON_SVG = {
    "walking": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="#111" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="13.5" cy="4.5" r="1.8"/>'
        '<path d="M13 8l-1.5 5 3 6M13 8l-3.5 2 .5 4M9.5 10L7 12l-1 4M13 8l3 1.5 2 3"/>'
        "</svg>"
    ),
    "ferry": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="#111" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M4 15l1.5 4h13L20 15"/><path d="M6 15l1-8h3v8M14 15V7h3l1 8"/>'
        '<path d="M12 3v4"/></svg>'
    ),
    "driving": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="#111" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M4 16V12l2-5h12l2 5v4"/><path d="M4 16h16"/>'
        '<circle cx="7.5" cy="16.5" r="1.5"/><circle cx="16.5" cy="16.5" r="1.5"/></svg>'
    ),
    "airplane": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="#111" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M3 13l7-2 5-9 2 1-3 8 6-1 2 2-8 3-2 5-2-1 1-5-6 2z"/></svg>'
    ),
}

# Per-mode HUD chrome: the reference video swaps both the banner's leading
# icon/suffix and the distance card's icon/time-label depending on how this
# leg is being traveled (walking vs. a ferry crossing was the confirmed
# case; driving/airplane are extrapolated the same way from
# pydeckrecorder.recorder's own _VEHICLE_PROFILES mode set, so this dict's
# keys intentionally match that one). "en_route_suffix" is appended to the
# non-arriving banner text for modes where the traveler is a passenger
# rather than on foot (e.g. "〜へ 乗船中" for a ferry) -- walking has none.
_MODE_HUD = {
    "walking": {"mode": "walking", "icon": _MODE_ICON_SVG["walking"], "banner_icon": "●", "time_label": "歩く時間", "en_route_suffix": "", "default_speed_kmh": 4.5},
    "ferry": {"mode": "ferry", "icon": _MODE_ICON_SVG["ferry"], "banner_icon": "⛴", "time_label": "乗船時間", "en_route_suffix": " 乗船中", "default_speed_kmh": 30.0},
    "driving": {"mode": "driving", "icon": _MODE_ICON_SVG["driving"], "banner_icon": "\U0001F697", "time_label": "運転時間", "en_route_suffix": "", "default_speed_kmh": 40.0},
    "airplane": {"mode": "airplane", "icon": _MODE_ICON_SVG["airplane"], "banner_icon": "✈", "time_label": "飛行時間", "en_route_suffix": " 搭乗中", "default_speed_kmh": 500.0},
}
_DEFAULT_MODE_HUD = _MODE_HUD["walking"]


def _hud_text(
    dest_label: str, remaining_m: float, remaining_min: int, arrive_threshold_m: float, mode: str = "walking",
) -> Tuple[str, str]:
    """Returns (banner_text, distance_text) for one frame's remaining
    distance -- split out from the render loop so the arrival-threshold,
    mode-suffix, and unit-formatting logic can be exercised by a plain unit
    test without spinning up a browser."""
    mode_hud = _MODE_HUD.get(mode, _DEFAULT_MODE_HUD)
    if remaining_m < arrive_threshold_m:
        banner = f"まもなく {dest_label}"
    else:
        banner = f"{dest_label} へ{mode_hud['en_route_suffix']}"
    dist_text = f"{remaining_m:.0f} m" if remaining_m < 1000 else f"{remaining_m / 1000.0:.1f} km"
    return banner, dist_text


def render_residential_leg_pydeck(
    leg_latlon: List[Tuple[float, float]],
    dest_label: str,
    output_path: str,
    mode: str = "walking",
    fps: int = 24,
    travel_speed_kmh: Optional[float] = None,
    target_duration_seconds: Optional[float] = None,
    output_size: Tuple[int, int] = (1920, 1080),
    mapbox_key: Optional[str] = None,
    map_style: str = "mapbox://styles/mapbox/outdoors-v12",
    follow_zoom: float = 19.0,
    follow_pitch: float = 0.0,
    arrive_threshold_m: float = 60.0,
    line_thickness: int = 8,
    walker_color: List[int] = None,
    upcoming_color: List[int] = None,
    landmarks: Optional[List[Dict]] = None,
    arrival_hold_seconds: float = 2.0,
    route_chain: Optional[List[str]] = None,
    topdown_transition_seconds: float = 1.6,
    topdown_zoom_delta: float = 1.0,
    dest_popup_image: Optional[str] = None,
    dest_popup_freeze_seconds: Optional[float] = None,
) -> List[str]:
    """Renders one leg as a straight-down, locked-camera video with a live
    turn-by-turn HUD (destination banner + time/distance card) -- the
    GeoJsonLayer-route analogue of pydeckrecorder.recorder's driving-mode
    leg rendering, but with no vehicle scenegraph, and with actual
    on-screen HUD chrome recorder.py/renderer.py's driving path doesn't
    have. Unlike a chase camera, the view never re-centers on the walker:
    after the intro's zoom-in (see `topdown_transition_seconds` below) it
    stays fixed on a framing that fits the leg's whole path, and only the
    walker dot/trail/destination pin move within that fixed frame.

    `leg_latlon`: [(lat, lon), ...] this leg's raw route points -- drawn
    two-tone: `walker_color` (default blue) behind the walker, growing as
    the leg progresses, and `upcoming_color` (default grey, a neutral
    "guide line" for the not-yet-walked path ahead) for the remainder.

    `landmarks`: optional [{"lat", "lon", ("label"), ("connect_to_route"),
    ("popup_image"), ("freeze_seconds")}, ...] -- unnumbered brown markers
    for points the route passes near without stopping (e.g. a leg's
    merged-in stop-by waypoints), drawn statically. One with
    `connect_to_route` True AND a `popup_image` gets MORE than just the
    static dot, though -- mirroring the overview's own rule that a
    connectToRoute stop-by acts like a real waypoint rather than a silent
    pass-through pin: the moment the walker reaches it, the walk pauses,
    its own photo fades in fullscreen, holds for its (floored/capped)
    `freeze_seconds`, then shrinks back down and fades out right onto that
    marker's own on-screen position before the walk continues.

    `arrival_hold_seconds`: after the chase camera finishes traveling the
    leg, holds the final (arrived) frame on screen for this many extra
    seconds before the clip ends -- a plain freeze-frame so a viewer
    actually has time to register the destination and its marker rather
    than the clip cutting away the instant the walker arrives.

    `route_chain`: optional ["友ヶ島", "深山ノ鼻", "加太", ...] -- this leg's
    own place names in travel order (start through destination, including
    any stop-bys in between). Shown as a static breadcrumb pill in the
    top-left corner (e.g. "友ヶ島 → 深山ノ鼻 → 加太"), separate from the
    top-right destination banner, so a viewer can place this leg within
    the wider trip at a glance. Omit to leave the corner empty.

    `topdown_transition_seconds`/`topdown_zoom_delta`: each leg opens on a
    big establishing shot -- north-up bearing, zoomed out `topdown_zoom_delta`
    levels below the leg's own locked/fit-to-path zoom, centered exactly on
    the walker's starting marker -- then eases zoom/position in a bit, over
    `topdown_transition_seconds`, into that locked framing as the walker
    starts moving; the camera then stays there, unmoving, for the rest of
    the leg. It closes (after `arrival_hold_seconds`) with the reverse:
    the locked view eases back out to the same big establishing framing,
    centered on the destination marker. Since each leg is its own clip,
    cutting one leg's outro straight into the next leg's intro reads as the
    camera changing focus to a new stretch of road -- matching the
    reference video's tile-to-tile refocus beat between legs. Set
    `topdown_transition_seconds` to 0 to disable and render the leg at a
    constant locked view from the first frame, as before.

    `dest_popup_image`: this leg's destination waypoint's own popup photo
    (route2vdo.py passes it from render_step.py's `res_data["popups"][-1]`).
    When set, the clip OPENS on this photo full-bleed (covering the whole
    frame), then shrinks down to the normal small popup-card size and
    freezes there for `dest_popup_freeze_seconds` (floored/capped the same
    way every other popup's freeze_seconds is -- see tuning.
    POPUP_MIN_DISPLAY_SECONDS/POPUP_FREEZE_SECONDS_MAX) with the map's own
    marker + grey route guideline already visible behind/around the card --
    a "here's where you're headed" preview before the card fades and the
    top-down establishing shot (see `topdown_transition_seconds` above)
    zooms in toward the start marker and the walk begins. Skipped entirely
    (clip opens straight on the establishing shot) when there's no photo.

    `dest_label`: the destination waypoint's display label for the banner.
    `mode`: one of _MODE_HUD's keys ("walking", "ferry", "driving",
    "airplane") -- drives the HUD's icon/label/banner-suffix AND (when
    `travel_speed_kmh` is left as None) the default pacing speed used to
    time the leg. An unrecognized mode falls back to walking's HUD chrome
    but keeps whatever `travel_speed_kmh` was actually passed.

    `target_duration_seconds`: overrides the VIDEO's own length (how long
    the camera actually takes to travel the leg), decoupling it from
    `travel_speed_kmh`/`total_leg_km` -- real routes range from a few
    meters to several kilometers per leg, and playing every one of them
    out at literal real-world walking/ferry pace would make some clips
    seconds long and others HOURS long. `travel_speed_kmh` still drives
    the HUD's own displayed remaining-time estimate (the real-world
    "X 分" a viewer would actually take), which is deliberately left
    independent of the animation's compressed playback length. Leave this
    None to fall back to real-world pacing (fine for a short/standalone
    leg, e.g. in an isolated test) -- route2vdo.py's real pipeline always
    passes this from the leg's own already-computed target duration.

    Returns a LIST of output paths, not a single one -- normally just
    `[output_path]`, but a connected stop-by's fullscreen photo pause (see
    `landmarks` above) cuts the leg into an extra file right at its
    fullscreen beat, so a leg with one or more of those produces that many
    additional paths, all still using `output_path`'s own filename with a
    "_cont{n}" suffix so downstream (audio mux, subtitles, timeline) still
    resolves every one of them back to this SAME leg by filename.
    """
    if len(leg_latlon) < 2:
        raise ValueError("leg_latlon needs at least 2 points")

    walker_color = walker_color or [30, 136, 255]
    upcoming_color = upcoming_color or [170, 170, 170, 200]
    mode_hud = _MODE_HUD.get(mode, _DEFAULT_MODE_HUD)
    if travel_speed_kmh is None:
        travel_speed_kmh = mode_hud["default_speed_kmh"]

    df_raw = pd.DataFrame([{"lat": lat, "lon": lon} for lat, lon in leg_latlon]).drop_duplicates().reset_index(drop=True)
    if len(df_raw) < 2:
        raise ValueError("leg_latlon collapsed to <2 distinct points after de-duplication")

    leg_dist_km = cumulative_distance_km(df_raw["lon"].tolist(), df_raw["lat"].tolist())
    total_leg_km = leg_dist_km[-1]

    leg_duration = (
        max(1.0, float(target_duration_seconds)) if target_duration_seconds is not None
        else max(3.0, (total_leg_km / travel_speed_kmh) * 3600.0)
    )
    total_frames = max(10, int(leg_duration * fps))

    smooth_df = interpolate_route_data(df_raw, leg_duration, total_frames, total_leg_km, leg_dist_km)

    step_km = [0.0] + [
        haversine_km(
            smooth_df.iloc[i]["lon"], smooth_df.iloc[i]["lat"],
            smooth_df.iloc[i + 1]["lon"], smooth_df.iloc[i + 1]["lat"],
        )
        for i in range(len(smooth_df) - 1)
    ]
    cum_km = pd.Series(step_km).cumsum()
    remaining_km = cum_km.iloc[-1] - cum_km

    route_preview_path = df_raw[["lon", "lat"]].values.tolist()
    # This leg's own grey guide line -- from this leg's start waypoint to
    # its destination only. Neighboring legs' routes are deliberately never
    # drawn here (they used to be, as static blue/green "context" lines,
    # but on an out-and-back route they frequently retrace the same street
    # as this leg and just painted over/confused this leg's own guide line
    # with an irrelevant one) -- each leg's clip shows only its own path.
    base_layers = [
        pdk.Layer(
            "GeoJsonLayer", id="route-preview",
            data=_route_linestring_feature(route_preview_path, line_color=upcoming_color),
            stroked=True, filled=False, get_line_color="properties.line_color",
            line_width_scale=1, line_width_min_pixels=max(2, line_thickness // 3),
        ),
    ]
    base_layers.extend(_landmark_layers(landmarks or [], id_prefix="leg-landmark"))
    # The start pin is static (this leg's starting point never moves) so it
    # goes straight into base_layers and is visible for the whole clip --
    # unlike the destination pin below, which only appears once the walker
    # gets close (see _record_leg's main loop) so as not to spoil a
    # not-yet-reached destination during the top-down establishing shot.
    start_lat, start_lon = df_raw.iloc[0]["lat"], df_raw.iloc[0]["lon"]
    base_layers.append(
        pdk.Layer(
            "IconLayer", id="leg-start-pin",
            data=[{
                "lon": start_lon, "lat": start_lat,
                "icon": {
                    "url": _TEARDROP_PIN_URL, "width": _TEARDROP_PIN_W,
                    "height": _TEARDROP_PIN_H, "anchorY": _TEARDROP_PIN_H,
                },
            }],
            get_icon="icon", get_position="[lon, lat]",
            get_size=44, size_units="'pixels'", size_scale=1, pickable=False,
        )
    )
    # NOT added to base_layers -- the destination pin only appears once the
    # walker crosses arrive_threshold_m (see _record_leg's main loop), same
    # moment the HUD banner switches to "まもなく"; showing it from the
    # start would mark the destination in a top-down establishing shot
    # taken while the walker is still leagues away from it.
    dest_lat, dest_lon = df_raw.iloc[-1]["lat"], df_raw.iloc[-1]["lon"]

    # The whole-leg "locked" camera: fits the leg's entire path in frame
    # (not a close street-level follow) and, once the intro's zoom-in
    # finishes, stays fixed there for the rest of the leg's walking
    # animation -- see _record_leg's main loop, which no longer re-centers
    # on the walker every frame the way the old chase-cam did. Capped at
    # follow_zoom so a very short/tight leg's fit-zoom can't exceed the
    # level the rest of this module treats as "close" street level.
    locked_lon, locked_lat, locked_zoom = _fit_view_for_path(
        df_raw["lon"].tolist(), df_raw["lat"].tolist(), output_size,
    )
    locked_zoom = min(locked_zoom, follow_zoom)

    view_state = pdk.ViewState(
        longitude=locked_lon, latitude=locked_lat,
        zoom=locked_zoom, pitch=follow_pitch, bearing=0,
    )
    deck = pdk.Deck(
        layers=base_layers, initial_view_state=view_state,
        map_provider="mapbox", map_style=map_style,
        api_keys={"mapbox": mapbox_key or MAPBOX_API_KEY},
        views=[pdk.View(type="MapView", controller=False)],
    )

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="navivi_pydeck_residential_") as html_dir:
        html_path = os.path.join(html_dir, "leg.html")
        deck.to_html(html_path)
        patch_pydeck_html(html_path)

        produced_paths = asyncio.run(_record_leg(
            html_path, html_dir, output_size, output_path, fps,
            df_raw, smooth_df, remaining_km, total_frames, dest_label,
            travel_speed_kmh, arrive_threshold_m, line_thickness, walker_color,
            follow_zoom, follow_pitch, mode_hud, arrival_hold_seconds, route_chain,
            topdown_transition_seconds, topdown_zoom_delta, dest_lat, dest_lon,
            total_leg_km, leg_dist_km, locked_lon, locked_lat, locked_zoom,
            dest_popup_image, dest_popup_freeze_seconds, landmarks,
        ))

    logger.info(f"Residential leg rendered ({mode}): {produced_paths}")
    return produced_paths


async def _play_stopby_photo_pause(
    page, write_frame, cut_to_new_clip, fps, html_dir, port, stopby,
    view_lon, view_lat, zoom, output_size, trigger_index,
):
    """Pauses the walk right where it is, for a connected stop-by (see
    `landmarks` docstring): its own photo pops in as a small leader-line
    card anchored on the marker's own on-screen position (computed from
    the LOCKED camera's known, unmoving viewState -- see
    `_project_lonlat_to_px`), holds, then the ending depends on whether
    this waypoint already has a GENERATED attraction video (the separate
    img2vdo.py/attraction_step.py pipeline stage -- `stopby["attraction_video"]`,
    set by route2vdo.py):

    - No attraction video: the card GROWS to fullscreen, then CUTS the
      leg into a new file (`cut_to_new_clip` closes the current one and
      opens a fresh one, mid-function -- the underlying page/deck.gl
      canvas never stops running, only the ffmpeg sink changes); that new
      file opens on the same fullscreen photo, holds, and shrinks back
      down to nothing right on the marker before the walk resumes.
    - Has an attraction video AND `image_display` is "pip": stays a small
      card the whole time -- no growth -- just holds, then cuts straight
      to a new file that resumes the walk directly (no fullscreen re-
      intro; the attraction video itself is meant to fill that beat when
      it's spliced in during final assembly).
    - Has an attraction video AND `image_display` is anything else
      ("fullscreen"/"cover"): grows to fullscreen like the no-attraction
      case, but ends with a cinematic blur-out (matching popupsequence.
      py's own arrival blur-out) instead of a flat cut, then cuts to a new
      file that likewise resumes the walk directly."""
    photo_path = stopby.get("popup_image")
    if not photo_path or not os.path.exists(photo_path):
        return

    has_attraction = bool(stopby.get("attraction_video"))
    image_display = str(stopby.get("image_display") or "cover").lower()

    # A per-call UNIQUE filename (not a fixed "stopby_preview.jpg" reused
    # every time this runs) -- a leg with more than one connected stop-by
    # otherwise has every one of them request the exact SAME URL, and the
    # browser's own HTTP cache happily serves back whichever photo it
    # fetched FIRST for every subsequent stop-by, regardless of the file on
    # disk having been overwritten with the next one's actual photo -- the
    # "duplicate image" this trigger index makes impossible.
    img_ext = os.path.splitext(photo_path)[1] or ".jpg"
    img_name = f"stopby_preview_{trigger_index}{img_ext}"
    shutil.copy2(photo_path, os.path.join(html_dir, img_name))
    img_url = f"http://127.0.0.1:{port}/{img_name}"

    freeze_sec = float(stopby.get("freeze_seconds") or tuning.POPUP_MIN_DISPLAY_SECONDS)
    freeze_sec = min(max(freeze_sec, tuning.POPUP_MIN_DISPLAY_SECONDS), tuning.POPUP_FREEZE_SECONDS_MAX)

    out_w, out_h = output_size
    marker_x, marker_y = _project_lonlat_to_px(
        stopby["lon"], stopby["lat"], view_lon, view_lat, zoom, output_size
    )
    full_box = (0.0, 0.0, float(out_w), float(out_h))
    # Small leader card, same aspect ratio as the frame itself (keeps the
    # object-fit:cover crop identical at every size -- see the leg-opening
    # sequence's own note on why this matters), floated just above the
    # marker with a leader line connecting its bottom edge down to it.
    card_w = 220.0
    card_h = card_w * (float(out_h) / float(out_w))
    card_gap = 26.0
    card_box = (marker_x - card_w / 2.0, marker_y - card_gap - card_h, card_w, card_h)
    anchor_x, anchor_y = marker_x, marker_y - card_gap

    await page.evaluate(
        """([url, left, top, w, h, ax, ay, mx, my]) => new Promise((resolve) => {
            const img = document.createElement('img');
            img.id = 'stopby-preview';
            img.src = url;
            Object.assign(img.style, {
                position: 'fixed', zIndex: '9998',
                left: left + 'px', top: top + 'px', width: w + 'px', height: h + 'px',
                objectFit: 'cover', opacity: '0', borderRadius: '15px',
                boxShadow: '0 15px 35px rgba(0,0,0,0.4)',
            });
            document.body.appendChild(img);

            const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            svg.id = 'stopby-leader';
            Object.assign(svg.style, {
                position: 'fixed', inset: '0', width: '100vw', height: '100vh',
                zIndex: '9997', pointerEvents: 'none',
            });
            const line = document.createElementNS(svg.namespaceURI, 'line');
            line.id = 'stopby-leader-line';
            line.setAttribute('x1', ax); line.setAttribute('y1', ay);
            line.setAttribute('x2', mx); line.setAttribute('y2', my);
            line.setAttribute('stroke', 'white'); line.setAttribute('stroke-width', '3');
            line.setAttribute('opacity', '0');
            const dot = document.createElementNS(svg.namespaceURI, 'circle');
            dot.setAttribute('cx', mx); dot.setAttribute('cy', my); dot.setAttribute('r', '7');
            dot.setAttribute('fill', 'white'); dot.setAttribute('stroke', '#333'); dot.setAttribute('stroke-width', '2');
            svg.appendChild(line);
            svg.appendChild(dot);
            document.body.appendChild(svg);

            if (img.decode) { img.decode().then(resolve).catch(resolve); }
            else { img.onload = resolve; img.onerror = resolve; }
            setTimeout(resolve, 2000);
        })""",
        [img_url, card_box[0], card_box[1], card_box[2], card_box[3], anchor_x, anchor_y, marker_x, marker_y],
    )
    await _wait_for_paint(page)

    # Pop-in: card + leader line fade/ease in together at their fixed,
    # already-final position (no motion yet -- see the growth phase below
    # for that) -- mirrors the leg-opening sequence's own pop-in beat.
    pop_frames = max(1, int(0.3 * fps))
    for i in range(pop_frames):
        alpha = _ease_in_out_cubic((i + 1) / pop_frames)
        await page.evaluate(
            """([a]) => {
                const img = document.getElementById('stopby-preview');
                if (img) img.style.opacity = a;
                const line = document.getElementById('stopby-leader-line');
                if (line) line.setAttribute('opacity', a);
            }""",
            [alpha],
        )
        await write_frame(await page.screenshot())

    hold_png = await page.screenshot()
    for _ in range(max(1, int(0.5 * fps))):
        await write_frame(hold_png)

    if has_attraction and image_display == "pip":
        # Stays a small card -- no growth, no fullscreen -- just cuts
        # straight to a new file that resumes the walk directly. The
        # attraction video itself (spliced in during final assembly, not
        # here) is what fills the "arriving here" beat this would
        # otherwise need to cover on its own.
        await page.evaluate(
            """() => {
                const svg = document.getElementById('stopby-leader'); if (svg) svg.remove();
                const img = document.getElementById('stopby-preview'); if (img) img.remove();
            }"""
        )
        await cut_to_new_clip()
        return

    # Grow: card -> fullscreen, leader line fading out as it goes (there's
    # nothing left to "point at" once the photo covers the whole frame).
    # This is the LAST beat of the CURRENT clip -- cut_to_new_clip below
    # closes it the instant this loop ends.
    grow_frames = max(1, int(0.6 * fps))
    for i in range(grow_frames):
        t = _ease_in_out_cubic((i + 1) / grow_frames)
        left = card_box[0] + (full_box[0] - card_box[0]) * t
        top = card_box[1] + (full_box[1] - card_box[1]) * t
        w = card_box[2] + (full_box[2] - card_box[2]) * t
        h = card_box[3] + (full_box[3] - card_box[3]) * t
        radius = 15.0 * (1.0 - t)
        await page.evaluate(
            """([left, top, w, h, radius, lineAlpha]) => {
                const img = document.getElementById('stopby-preview');
                if (img) {
                    img.style.left = left + 'px'; img.style.top = top + 'px';
                    img.style.width = w + 'px'; img.style.height = h + 'px';
                    img.style.borderRadius = radius + 'px';
                }
                const line = document.getElementById('stopby-leader-line');
                if (line) line.setAttribute('opacity', lineAlpha);
            }""",
            [left, top, w, h, radius, max(0.0, 1.0 - t * 2.0)],
        )
        await write_frame(await page.screenshot())

    # The leader line/dot have no further use once fullscreen -- gone
    # before the cut so the NEW clip never inherits a stray leftover node.
    await page.evaluate(
        "() => { const svg = document.getElementById('stopby-leader'); if (svg) svg.remove(); }"
    )

    # Hold at fullscreen size BEFORE cutting/blurring -- the grow animation
    # used to run straight into the cut with no pause at all, so the photo
    # was on screen at full size for a single frame before vanishing; a
    # viewer never actually got to register it fullscreen.
    grown_png = await page.screenshot()
    for _ in range(max(1, int(freeze_sec * fps))):
        await write_frame(grown_png)

    if has_attraction:
        # Cinematic blur-out (same shape as popupsequence.py's own arrival
        # blur-out: accelerating blur + fade to black) instead of a flat
        # cut -- this is the LAST beat of the CURRENT clip. The new file
        # then resumes the walk directly, same as the pip branch above.
        blur_frames = max(1, int(0.4 * fps))
        for i in range(blur_frames):
            progress = i / float(blur_frames - 1) if blur_frames > 1 else 1.0
            ease = progress ** 2
            blur_px = ease * 40.0
            alpha = 1.0 - progress
            await page.evaluate(
                """([blurPx, alphaVal]) => {
                    const img = document.getElementById('stopby-preview');
                    if (!img) return;
                    img.style.filter = `blur(${blurPx}px)`;
                    img.style.opacity = alphaVal;
                }""",
                [blur_px, alpha],
            )
            await write_frame(await page.screenshot())

        await page.evaluate(
            "() => { const img = document.getElementById('stopby-preview'); if (img) img.remove(); }"
        )
        await cut_to_new_clip()
        return

    await cut_to_new_clip()

    fullscreen_png = await page.screenshot()
    for _ in range(max(1, int(freeze_sec * fps))):
        await write_frame(fullscreen_png)

    # Shrinks back down to nothing right on the marker -- the walk's own
    # map/trail/dot are already sitting underneath, unchanged, the whole
    # time (the canvas never stopped rendering across the cut).
    vanish_size = 140.0
    vanish_box = (marker_x - vanish_size / 2.0, marker_y - vanish_size / 2.0, vanish_size, vanish_size)
    vanish_frames = max(1, int(0.5 * fps))
    for i in range(vanish_frames):
        t = _ease_in_out_cubic((i + 1) / vanish_frames)
        left = full_box[0] + (vanish_box[0] - full_box[0]) * t
        top = full_box[1] + (vanish_box[1] - full_box[1]) * t
        w = full_box[2] + (vanish_box[2] - full_box[2]) * t
        h = full_box[3] + (vanish_box[3] - full_box[3]) * t
        radius = (vanish_size / 2.0) * t
        alpha = 1.0 - t
        await page.evaluate(
            """([left, top, w, h, radius, alpha]) => {
                const img = document.getElementById('stopby-preview');
                if (!img) return;
                img.style.left = left + 'px';
                img.style.top = top + 'px';
                img.style.width = w + 'px';
                img.style.height = h + 'px';
                img.style.borderRadius = radius + 'px';
                img.style.opacity = alpha;
            }""",
            [left, top, w, h, radius, alpha],
        )
        await write_frame(await page.screenshot())

    await page.evaluate(
        "() => { const img = document.getElementById('stopby-preview'); if (img) img.remove(); }"
    )


async def _record_leg(
    html_path, html_dir, output_size, output_path, fps,
    df_raw, smooth_df, remaining_km, total_frames, dest_label,
    travel_speed_kmh, arrive_threshold_m, line_thickness, walker_color,
    follow_zoom, follow_pitch, mode_hud, arrival_hold_seconds=2.0, route_chain=None,
    topdown_transition_seconds=1.6, topdown_zoom_delta=6.0, dest_lat=None, dest_lon=None,
    total_leg_km=None, leg_dist_km=None,
    locked_lon=None, locked_lat=None, locked_zoom=None,
    dest_popup_image=None, dest_popup_freeze_seconds=None, landmarks=None,
):
    from playwright.async_api import async_playwright
    from services.vdoprocessing.vdoeditor import FFmpegEngine

    editor = FFmpegEngine()

    async def _spawn_ffmpeg(out_path: str):
        ffmpeg_cmd = [
            editor.resolve_binary(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "image2pipe", "-vcodec", "png", "-framerate", str(fps), "-i", "-",
            "-c:v", "libx264", *tuning.ffmpeg_thread_args(),
            "-r", str(fps), "-pix_fmt", "yuv420p", out_path,
        ]
        return await asyncio.create_subprocess_exec(
            *ffmpeg_cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL
        )

    # A leg normally writes into ONE output file start to finish. A
    # connected stop-by pause (see `landmarks` docstring) can CUT the leg
    # into an extra file right at its fullscreen moment, though -- the
    # underlying `page`/deck.gl canvas keeps running unbroken across that
    # cut (only the ffmpeg SINK changes), so `proc_ref`/`produced_paths`
    # are the only mutable state needed for it: every frame write below
    # goes through `_write_frame`, which always targets whatever process
    # `proc_ref["proc"]` currently points at, so swapping it mid-function
    # (see `_cut_to_new_clip` near the main loop) is transparent to every
    # call site.
    proc_ref = {"proc": await _spawn_ffmpeg(output_path)}
    produced_paths = [output_path]

    async def _write_frame(png_bytes: bytes) -> None:
        proc_ref["proc"].stdin.write(png_bytes)
        await proc_ref["proc"].stdin.drain()

    async def _cut_to_new_clip() -> None:
        """Closes the CURRENT output file (waits for ffmpeg to actually
        finish writing it) and opens a fresh one for `_write_frame` to
        target from here on -- see `_play_stopby_photo_pause`, the only
        caller. The continuation file keeps this leg's own "02_waypoint_
        {N:02d}_" filename prefix (just with a "_cont{n}" suffix inserted)
        so render_step.py's audio mux and timeline_step.py's own filename
        parse (both match on that prefix, not the full name) still resolve
        it to this SAME leg's narration/subtitle -- see route2vdo.py's own
        note on why both files intentionally get that leg's full audio
        rather than a proportional split."""
        proc_ref["proc"].stdin.close()
        await proc_ref["proc"].wait()
        stem, ext = os.path.splitext(output_path)
        new_path = f"{stem}_cont{len(produced_paths) + 1}{ext}"
        proc_ref["proc"] = await _spawn_ffmpeg(new_path)
        produced_paths.append(new_path)

    server, port = start_local_server(html_dir)
    try:
        rel_path = os.path.relpath(html_path, html_dir).replace("\\", "/")
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(viewport={"width": output_size[0], "height": output_size[1]})
                page = await context.new_page()
                page.on("pageerror", lambda exc: logger.error(f"  [PAGE ERROR] {exc}"))
                await page.goto(f"http://127.0.0.1:{port}/{rel_path}")
                try:
                    await page.wait_for_load_state("load", timeout=5000)
                except Exception:
                    pass
                await page.wait_for_timeout(2500)

                await page.evaluate(
                    """([css, bannerIcon, timeLabel, cardIcon, chainPlaces]) => {
                        const style = document.createElement('style');
                        style.textContent = css;
                        document.head.appendChild(style);
                        const banner = document.createElement('div');
                        banner.id = 'hud-banner';
                        banner.innerHTML = `<span class="icon">${bannerIcon}</span> <span id="hud-banner-text"></span>`;
                        document.body.appendChild(banner);
                        const card = document.createElement('div');
                        card.id = 'hud-card';
                        card.innerHTML = `
                            <div class="metric"><div class="label"><span class="icon">${cardIcon}</span> ${timeLabel}</div><div class="value" id="hud-time">--</div></div>
                            <div class="divider"></div>
                            <div class="metric"><div class="label">距離</div><div class="value" id="hud-dist">--</div></div>
                        `;
                        document.body.appendChild(card);
                        if (chainPlaces && chainPlaces.length) {
                            const chain = document.createElement('div');
                            chain.id = 'hud-chain';
                            chainPlaces.forEach((p, i) => {
                                if (i > 0) {
                                    const arrow = document.createElement('span');
                                    arrow.className = 'arrow';
                                    arrow.textContent = '→';
                                    chain.appendChild(arrow);
                                }
                                const place = document.createElement('span');
                                place.className = 'place';
                                place.textContent = p;
                                chain.appendChild(place);
                            });
                            document.body.appendChild(chain);
                        }
                    }""",
                    [_HUD_CSS, mode_hud["banner_icon"], mode_hud["time_label"], mode_hud["icon"], route_chain],
                )

                all_trail_points = df_raw[["lon", "lat"]].values.tolist()
                c_trail = json.dumps(walker_color)
                c_glow = json.dumps(walker_color + [90])

                # Intro: opens on a true top-down shot (pitch 0, north-up,
                # zoomed out `topdown_zoom_delta` levels below the locked
                # whole-leg framing, centered exactly on the walker's start
                # marker -- a big establishing map) and eases zoom/position
                # in a bit into that locked framing (see `locked_lon`/
                # `locked_lat`/`locked_zoom`, computed once in
                # render_residential_leg_pydeck to fit the whole leg) before
                # the walker starts moving. Unlike the old chase-cam, the
                # camera then STAYS at this locked view for the entire main
                # loop below -- it never re-centers on the walker.
                intro_frames = max(0, int(topdown_transition_seconds * fps))
                # Floored well above a country/region-scale zoom -- locked_zoom
                # is now a per-leg fit-to-path zoom (often much lower than the
                # old fixed follow_zoom=19 baseline this delta was originally
                # tuned against), so subtracting the full delta unclamped could
                # push a short leg's establishing shot out to a whole-Japan
                # view instead of a "zoomed out a bit" local one.
                topdown_zoom = max(
                    (locked_zoom if locked_zoom is not None else follow_zoom) - topdown_zoom_delta,
                    (locked_zoom if locked_zoom is not None else follow_zoom) - 1.5,
                    13.5,
                )
                if intro_frames > 0:
                    first_row = smooth_df.iloc[0]
                    rem_km0 = float(remaining_km.iloc[0])
                    rem_m0 = rem_km0 * 1000.0
                    rem_min0 = max(1, round((rem_km0 / travel_speed_kmh) * 60.0))
                    banner_text0, dist_text0 = _hud_text(
                        dest_label, rem_m0, rem_min0, arrive_threshold_m, mode=mode_hud["mode"]
                    )
                    walker_json0 = json.dumps([{"lon": first_row["lon"], "lat": first_row["lat"]}])

                    # Warm-up: jump straight to the pure top-down frame (t=0)
                    # and give Mapbox real time to fetch tiles at that much
                    # lower zoom (`topdown_zoom` vs. the `follow_zoom` used
                    # for the whole rest of the leg) before the eased
                    # descent starts sweeping through the zoom range one
                    # frame at a time -- without this, the per-frame 15ms
                    # wait below isn't enough for new tiles to load mid-
                    # sweep, and Mapbox paints whatever coarse placeholder
                    # tile it already has (a flat, wrongly-scaled block)
                    # for part of the transition. Held for a few frames so
                    # it also reads as a brief top-down establishing shot.
                    warm_js = f"""
                    if (window.deckgl) {{
                        window.deckgl.setProps({{
                            viewState: {{
                                longitude: {first_row["lon"]}, latitude: {first_row["lat"]},
                                zoom: {topdown_zoom}, pitch: 0, bearing: 0,
                                transitionDuration: 0
                            }}
                        }});
                    }}
                    """
                    await page.evaluate(warm_js)
                    # 500ms wasn't reliably enough here -- the deck.gl
                    # canvas has ALSO just been sitting at its own INITIAL
                    # viewState (locked_zoom, a much tighter street-level
                    # framing -- see render_residential_leg_pydeck's own
                    # `view_state` construction) since page load, so this
                    # jump isn't just "one zoom step" like the per-frame
                    # sweep below worries about -- it can be several levels
                    # in one go. Too short a wait here left the destination-
                    # photo sequence right after this (which reuses this
                    # same still-settling frame as its own backdrop) reading
                    # as noticeably more zoomed-in than the establishing
                    # shot it's supposed to match once tiles finish loading.
                    await page.wait_for_timeout(1500)
                    warm_png = await page.screenshot()
                    for _ in range(max(1, int(0.3 * fps))):
                        await _write_frame(warm_png)

                    # Destination photo preview: opens full-bleed over this
                    # same top-down establishing frame (map + start marker +
                    # grey route guideline already visible underneath), then
                    # shrinks down to the normal small popup-card size and
                    # freezes there -- a "here's where you're headed" beat
                    # before the card fades and the establishing shot zooms
                    # in toward the start marker below. Skipped entirely
                    # when this leg's destination has no popup photo.
                    if dest_popup_image and os.path.exists(dest_popup_image):
                        img_ext = os.path.splitext(dest_popup_image)[1] or ".jpg"
                        dest_img_name = "leg_dest_preview" + img_ext
                        shutil.copy2(dest_popup_image, os.path.join(html_dir, dest_img_name))
                        dest_img_url = f"http://127.0.0.1:{port}/{dest_img_name}"

                        freeze_sec = float(dest_popup_freeze_seconds) if dest_popup_freeze_seconds is not None else tuning.POPUP_MIN_DISPLAY_SECONDS
                        freeze_sec = min(
                            max(freeze_sec, tuning.POPUP_MIN_DISPLAY_SECONDS),
                            tuning.POPUP_FREEZE_SECONDS_MAX,
                        )

                        out_w, out_h = output_size
                        await page.evaluate(
                            """([url, w, h]) => new Promise((resolve) => {
                                const img = document.createElement('img');
                                img.id = 'leg-dest-preview';
                                img.src = url;
                                Object.assign(img.style, {
                                    position: 'fixed', zIndex: '9998',
                                    left: '0px', top: '0px', width: w + 'px', height: h + 'px',
                                    objectFit: 'cover', opacity: '1',
                                    boxShadow: '0 15px 35px rgba(0,0,0,0.4)',
                                });
                                document.body.appendChild(img);
                                if (img.decode) { img.decode().then(resolve).catch(resolve); }
                                else { img.onload = resolve; img.onerror = resolve; }
                                setTimeout(resolve, 2000);
                            })""",
                            [dest_img_url, out_w, out_h],
                        )
                        await _wait_for_paint(page)

                        card_w = 360.0
                        # Same aspect ratio as the fullscreen frame itself
                        # (not the photo's own natural aspect ratio) -- with
                        # object-fit:cover, changing the BOX's aspect ratio
                        # mid-shrink changes which slice of the photo is
                        # visible, so the image read as swapping to a
                        # different crop/zoom partway through. Keeping the
                        # box's aspect ratio constant throughout means the
                        # same crop is shown at every size, just scaled down.
                        card_h = card_w * (float(out_h) / float(out_w))
                        full_box = (0.0, 0.0, float(out_w), float(out_h))
                        side_margin = 50.0
                        # A random corner each leg (not hard-locked to
                        # top-right) -- but each corner already has one of
                        # this leg's own fixed HUD elements sitting in it
                        # (hud-chain top-left, hud-banner top-right, hud-card
                        # bottom-right -- see _HUD_CSS), so a flat 50px
                        # margin on every corner would sit the photo right
                        # on top of whichever one is there. These clearances
                        # are each that element's own approximate footprint
                        # (position + size from _HUD_CSS) plus a gap, so the
                        # card starts clear of it instead of overlapping;
                        # bottom-left is the one genuinely empty corner and
                        # keeps the plain side_margin.
                        clearance_by_corner = {
                            "top-left": 110.0,      # clears #hud-chain
                            "top-right": 110.0,     # clears #hud-banner
                            "bottom-left": side_margin,
                            "bottom-right": 170.0,  # clears #hud-card
                        }
                        corner_name = random.choice(list(clearance_by_corner))
                        clearance = clearance_by_corner[corner_name]
                        card_left = side_margin if "left" in corner_name else out_w - side_margin - card_w
                        card_top = clearance if "top" in corner_name else out_h - clearance - card_h
                        card_box = (card_left, card_top, card_w, card_h)
                        # The camera is centered exactly on the start marker
                        # for this whole phase (see warm_js above), so its
                        # on-screen position is simply the viewport's own
                        # center -- no need to reproject lon/lat to pixels.
                        marker_px = (out_w / 2.0, out_h / 2.0)
                        # Leader line anchors at whichever of the card's 4
                        # corners sits closest to the marker (screen center)
                        # -- generalizes the callout to any corner the card
                        # ends up in, not just a hardcoded one.
                        card_corners = {
                            "top-left": (card_box[0], card_box[1]),
                            "top-right": (card_box[0] + card_w, card_box[1]),
                            "bottom-left": (card_box[0], card_box[1] + card_h),
                            "bottom-right": (card_box[0] + card_w, card_box[1] + card_h),
                        }
                        anchor_name = min(
                            card_corners,
                            key=lambda k: (card_corners[k][0] - marker_px[0]) ** 2
                            + (card_corners[k][1] - marker_px[1]) ** 2,
                        )
                        anchor_is_left = "left" in anchor_name
                        anchor_is_top = "top" in anchor_name

                        hold_full_png = await page.screenshot()
                        for _ in range(max(1, int(0.4 * fps))):
                            await _write_frame(hold_full_png)

                        # Leader line: a thin callout from the card's near
                        # (bottom-left) corner down to the start marker, with
                        # a small dot at the marker end -- an SVG overlay
                        # rather than a deck.gl layer since it needs to track
                        # the CARD's own screen-space animation, not a map
                        # coordinate. Added once here, then just updated in
                        # place through the shrink/freeze/fade phases below.
                        await page.evaluate(
                            """([x2, y2]) => {
                                const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                                svg.id = 'leg-dest-leader';
                                Object.assign(svg.style, {
                                    position: 'fixed', inset: '0', width: '100vw', height: '100vh',
                                    zIndex: '9997', pointerEvents: 'none',
                                });
                                const line = document.createElementNS(svg.namespaceURI, 'line');
                                line.id = 'leg-dest-leader-line';
                                line.setAttribute('stroke', 'white');
                                line.setAttribute('stroke-width', '3');
                                line.setAttribute('opacity', '0');
                                const dot = document.createElementNS(svg.namespaceURI, 'circle');
                                dot.id = 'leg-dest-leader-dot';
                                dot.setAttribute('r', '7');
                                dot.setAttribute('fill', 'white');
                                dot.setAttribute('stroke', '#333');
                                dot.setAttribute('stroke-width', '2');
                                dot.setAttribute('cx', x2);
                                dot.setAttribute('cy', y2);
                                svg.appendChild(line);
                                svg.appendChild(dot);
                                document.body.appendChild(svg);
                            }""",
                            [marker_px[0], marker_px[1]],
                        )

                        shrink_frames = max(1, int(0.7 * fps))
                        for i in range(shrink_frames):
                            t = _ease_in_out_cubic((i + 1) / shrink_frames)
                            left = full_box[0] + (card_box[0] - full_box[0]) * t
                            top = full_box[1] + (card_box[1] - full_box[1]) * t
                            w = full_box[2] + (card_box[2] - full_box[2]) * t
                            h = full_box[3] + (card_box[3] - full_box[3]) * t
                            radius = 15.0 * t
                            leader_x1 = left if anchor_is_left else left + w
                            leader_y1 = top if anchor_is_top else top + h
                            await page.evaluate(
                                """([left, top, w, h, radius, x1, y1]) => {
                                    const img = document.getElementById('leg-dest-preview');
                                    if (img) {
                                        img.style.left = left + 'px';
                                        img.style.top = top + 'px';
                                        img.style.width = w + 'px';
                                        img.style.height = h + 'px';
                                        img.style.borderRadius = radius + 'px';
                                    }
                                    const line = document.getElementById('leg-dest-leader-line');
                                    if (line) {
                                        line.setAttribute('x1', x1);
                                        line.setAttribute('y1', y1);
                                        line.setAttribute('x2', x1);
                                        line.setAttribute('y2', y1);
                                        line.setAttribute('opacity', '0');
                                    }
                                }""",
                                [left, top, w, h, radius, leader_x1, leader_y1],
                            )
                            png_bytes = await page.screenshot()
                            await _write_frame(png_bytes)

                        # The line only draws in once the card has settled at
                        # its final small size -- growing it DURING the
                        # shrink (card corner still moving fast) read as a
                        # flickery diagonal streak, not a deliberate callout.
                        leader_grow_frames = max(1, int(0.3 * fps))
                        anchor_x = card_box[0] if anchor_is_left else card_box[0] + card_w
                        anchor_y = card_box[1] if anchor_is_top else card_box[1] + card_h
                        for i in range(leader_grow_frames):
                            t = _ease_in_out_cubic((i + 1) / leader_grow_frames)
                            await page.evaluate(
                                """([x2, y2, alpha]) => {
                                    const line = document.getElementById('leg-dest-leader-line');
                                    if (line) {
                                        line.setAttribute('x2', x2);
                                        line.setAttribute('y2', y2);
                                        line.setAttribute('opacity', alpha);
                                    }
                                }""",
                                [
                                    anchor_x + (marker_px[0] - anchor_x) * t,
                                    anchor_y + (marker_px[1] - anchor_y) * t,
                                    t,
                                ],
                            )
                            png_bytes = await page.screenshot()
                            await _write_frame(png_bytes)

                        freeze_png = await page.screenshot()
                        for _ in range(max(1, int(freeze_sec * fps))):
                            await _write_frame(freeze_png)

                        fade_frames = max(1, int(0.4 * fps))
                        for i in range(fade_frames):
                            alpha = 1.0 - ((i + 1) / fade_frames)
                            await page.evaluate(
                                """([alphaVal]) => {
                                    const img = document.getElementById('leg-dest-preview');
                                    if (img) img.style.opacity = alphaVal;
                                    const svg = document.getElementById('leg-dest-leader');
                                    if (svg) svg.style.opacity = alphaVal;
                                }""",
                                [alpha],
                            )
                            png_bytes = await page.screenshot()
                            await _write_frame(png_bytes)

                        await page.evaluate(
                            """() => {
                                const img = document.getElementById('leg-dest-preview');
                                if (img) img.remove();
                                const svg = document.getElementById('leg-dest-leader');
                                if (svg) svg.remove();
                            }"""
                        )

                    for i in range(intro_frames):
                        t = _ease_in_out_cubic((i + 1) / intro_frames)
                        zoom = topdown_zoom + (locked_zoom - topdown_zoom) * t
                        pitch = follow_pitch * t
                        bearing = 0.0
                        lon = first_row["lon"] + (locked_lon - first_row["lon"]) * t
                        lat = first_row["lat"] + (locked_lat - first_row["lat"]) * t
                        js = f"""
                        if (window.deckgl) {{
                            const currentLayers = window.deckgl.props.layers || [];
                            const staticLayers = currentLayers.filter(l => !['walker-trail', 'walker-dot', 'walker-halo'].includes(l.id));
                            const newHalo = new deck.ScatterplotLayer({{
                                id: 'walker-halo', data: {walker_json0},
                                getPosition: d => [d.lon, d.lat], getFillColor: {c_glow},
                                getRadius: 6, radiusMinPixels: 26
                            }});
                            const newDot = new deck.ScatterplotLayer({{
                                id: 'walker-dot', data: {walker_json0},
                                getPosition: d => [d.lon, d.lat], getFillColor: [255, 255, 255, 255],
                                getLineColor: {c_trail}, stroked: true, lineWidthMinPixels: 4,
                                getRadius: 2, radiusMinPixels: 12
                            }});
                            window.deckgl.setProps({{
                                viewState: {{
                                    longitude: {lon}, latitude: {lat},
                                    zoom: {zoom}, pitch: {pitch}, bearing: {bearing},
                                    transitionDuration: 0
                                }},
                                layers: [...staticLayers, newHalo, newDot]
                            }});
                            document.getElementById('hud-banner-text').textContent = {json.dumps(banner_text0)};
                            document.getElementById('hud-time').textContent = {json.dumps(f"{rem_min0} 分")};
                            document.getElementById('hud-dist').textContent = {json.dumps(dist_text0)};
                        }}
                        """
                        await page.evaluate(js)
                        await page.wait_for_timeout(50)
                        png_bytes = await page.screenshot()
                        await _write_frame(png_bytes)

                # The destination pin only exists as JS from here on (never
                # in base_layers) -- see render_residential_leg_pydeck's
                # docstring: it's added the moment the walker first crosses
                # arrive_threshold_m, not shown for the whole leg, so it
                # doesn't mark the destination while the walker is still far
                # away. Built once and reused (only the include/exclude
                # below changes per frame).
                # Teardrop pin (see _TEARDROP_PIN_SVG), colored to match the
                # overview's own numbered waypoint pins.
                dest_pin_data_json = json.dumps([{
                    "lon": dest_lon, "lat": dest_lat,
                    "icon": {
                        "url": _TEARDROP_PIN_URL, "width": _TEARDROP_PIN_W,
                        "height": _TEARDROP_PIN_H, "anchorY": _TEARDROP_PIN_H,
                    },
                }]) if dest_lat is not None and dest_lon is not None else None
                dest_pin_ctor_js = f"""
                    const newDestPin = new deck.IconLayer({{
                        id: 'leg-dest-pin', data: {dest_pin_data_json},
                        getIcon: d => d.icon, getPosition: d => [d.lon, d.lat],
                        getSize: 44, sizeUnits: 'pixels', sizeScale: 1, pickable: false
                    }});
                """ if dest_pin_data_json else ""

                # Connected stop-by photo pauses (see render_residential_leg_
                # pydeck's `landmarks` docstring): a merged-in stop-by with
                # "connectToRoute" true AND its own photo gets a full
                # fullscreen-pause moment the instant the walker reaches it,
                # not just the plain static dot every other landmark gets.
                # Triggered on whichever walking-loop frame's own position
                # lands closest to that stop-by's coordinates.
                stopby_triggers: Dict[int, Dict] = {}
                for lm in (landmarks or []):
                    if not (lm.get("connect_to_route") and lm.get("popup_image")):
                        continue
                    lm_lat, lm_lon = lm.get("lat"), lm.get("lon")
                    if lm_lat is None or lm_lon is None:
                        continue
                    sq_dist = (smooth_df["lat"] - lm_lat) ** 2 + (smooth_df["lon"] - lm_lon) ** 2
                    stopby_triggers[int(sq_dist.idxmin())] = lm

                last_png_bytes = None
                crashed = False
                for index, row in smooth_df.iterrows():
                    rem_km = float(remaining_km.iloc[index])
                    # Trail must end exactly where the walker dot actually is
                    # -- picking raw points by ANIMATION-FRAME fraction (the
                    # old `index / total_frames` approach) assumes frames and
                    # raw route points advance in lockstep, which they don't
                    # (smooth_df is a separately time-based resampling), so
                    # the blue trail could visibly run ahead of or behind the
                    # dot. Selecting raw points by actual DISTANCE traveled
                    # so far, then appending the dot's own real position as
                    # the trail's final vertex, keeps the two in exact sync.
                    traveled_km = max(0.0, (total_leg_km or 0.0) - rem_km)
                    n_pts = bisect.bisect_right(leg_dist_km, traveled_km) if leg_dist_km else 0
                    active_trail = all_trail_points[:n_pts] + [[row["lon"], row["lat"]]]
                    trail_geojson = json.dumps(
                        _route_linestring_feature(active_trail, line_color=walker_color)
                    ) if len(active_trail) >= 2 else json.dumps({"type": "FeatureCollection", "features": []})
                    walker_json = json.dumps([{"lon": row["lon"], "lat": row["lat"]}])

                    rem_m = rem_km * 1000.0
                    rem_min = max(1, round((rem_km / travel_speed_kmh) * 60.0))
                    banner_text, dist_text = _hud_text(
                        dest_label, rem_m, rem_min, arrive_threshold_m, mode=mode_hud["mode"]
                    )
                    show_dest_pin = dest_pin_ctor_js and rem_m < arrive_threshold_m

                    js = f"""
                    if (window.deckgl) {{
                        const currentLayers = window.deckgl.props.layers || [];
                        const staticLayers = currentLayers.filter(l => !['walker-trail', 'walker-dot', 'walker-halo', 'leg-dest-pin'].includes(l.id));
                        const newTrail = new deck.GeoJsonLayer({{
                            id: 'walker-trail', data: {trail_geojson},
                            stroked: true, filled: false, getLineColor: d => d.properties.line_color,
                            lineWidthScale: 1, lineWidthMinPixels: {line_thickness}
                        }});
                        const newHalo = new deck.ScatterplotLayer({{
                            id: 'walker-halo', data: {walker_json},
                            getPosition: d => [d.lon, d.lat], getFillColor: {c_glow},
                            getRadius: 6, radiusMinPixels: 26
                        }});
                        const newDot = new deck.ScatterplotLayer({{
                            id: 'walker-dot', data: {walker_json},
                            getPosition: d => [d.lon, d.lat], getFillColor: [255, 255, 255, 255],
                            getLineColor: {c_trail}, stroked: true, lineWidthMinPixels: 4,
                            getRadius: 2, radiusMinPixels: 12
                        }});
                        {dest_pin_ctor_js if show_dest_pin else ""}
                        // Camera is locked for the whole leg (see the intro's
                        // zoom-in above) -- no viewState here, so deck.gl just
                        // keeps whatever view the intro left it at instead of
                        // re-centering on the walker every frame.
                        window.deckgl.setProps({{
                            layers: [...staticLayers, newTrail, newHalo, newDot{", newDestPin" if show_dest_pin else ""}]
                        }});
                        document.getElementById('hud-banner-text').textContent = {json.dumps(banner_text)};
                        document.getElementById('hud-time').textContent = {json.dumps(f"{rem_min} 分")};
                        document.getElementById('hud-dist').textContent = {json.dumps(dist_text)};
                    }}
                    """
                    await page.evaluate(js)
                    await page.wait_for_timeout(20)
                    png_bytes = await page.screenshot()
                    try:
                        await _write_frame(png_bytes)
                        last_png_bytes = png_bytes
                    except Exception as e:
                        logger.error(f"[ERROR] FFmpeg crashed: {e}")
                        crashed = True
                        break

                    stopby_lm = stopby_triggers.get(index)
                    if stopby_lm is not None:
                        await _play_stopby_photo_pause(
                            page, _write_frame, _cut_to_new_clip, fps, html_dir, port,
                            stopby_lm, locked_lon, locked_lat, locked_zoom, output_size, index,
                        )

                # Freeze-frame on arrival: holds the final (arrived) frame
                # -- destination banner + marker already on screen -- for a
                # few extra seconds instead of cutting away the instant the
                # walker reaches the destination, so a viewer actually has
                # time to register where this is.
                #
                # The walker's own halo+dot (drawn on TOP of every static
                # layer each frame) lands exactly on the destination pin at
                # this final frame and is bigger than it, so it completely
                # hides the teardrop underneath -- clearing those two
                # layers first lets the actual pin read clearly in the held
                # frame instead of looking like an oversized blurry circle.
                if not crashed and last_png_bytes is not None:
                    await page.evaluate(
                        """() => {
                            if (window.deckgl) {
                                const staticLayers = (window.deckgl.props.layers || [])
                                    .filter(l => !['walker-halo', 'walker-dot'].includes(l.id));
                                window.deckgl.setProps({ layers: staticLayers });
                            }
                        }"""
                    )
                    await page.wait_for_timeout(20)
                    last_png_bytes = await page.screenshot()

                    hold_frames = max(0, int(arrival_hold_seconds * fps))
                    for _ in range(hold_frames):
                        await _write_frame(last_png_bytes)

                    # Outro: the reverse of the intro above -- eases the
                    # locked whole-leg framing back OUT to the same top-down
                    # establishing shot (pitch 0, north-up, zoomed out,
                    # centered exactly on the destination marker) so this
                    # clip ENDS on an overview shot, and the next leg's clip
                    # (see intro block) starts on its own overview shot and
                    # descends back in -- cutting the two together reads as
                    # the camera changing focus to a new stretch of road.
                    outro_frames = max(0, int(topdown_transition_seconds * fps))
                    if outro_frames > 0:
                        last_row = smooth_df.iloc[-1]
                        for i in range(outro_frames):
                            t = _ease_in_out_cubic((i + 1) / outro_frames)
                            zoom = locked_zoom + (topdown_zoom - locked_zoom) * t
                            pitch = follow_pitch * (1.0 - t)
                            bearing = 0.0
                            lon = locked_lon + (last_row["lon"] - locked_lon) * t
                            lat = locked_lat + (last_row["lat"] - locked_lat) * t
                            js = f"""
                            if (window.deckgl) {{
                                window.deckgl.setProps({{
                                    viewState: {{
                                        longitude: {lon}, latitude: {lat},
                                        zoom: {zoom}, pitch: {pitch}, bearing: {bearing},
                                        transitionDuration: 0
                                    }}
                                }});
                            }}
                            """
                            await page.evaluate(js)
                            await page.wait_for_timeout(50)
                            png_bytes = await page.screenshot()
                            await _write_frame(png_bytes)

                        # Same tile warm-up problem as the intro's, mirrored:
                        # the outro just swept zoom all the way down to
                        # `topdown_zoom` in <2s, so give Mapbox a real beat
                        # to finish loading those low-zoom tiles before the
                        # clip ends on this frame (it's also what the NEXT
                        # leg's own intro warm-up starts from, visually).
                        await page.wait_for_timeout(400)
                        final_topdown_png = await page.screenshot()
                        for _ in range(max(1, int(0.3 * fps))):
                            await _write_frame(final_topdown_png)
            finally:
                await browser.close()
    finally:
        server.shutdown()
        server.server_close()

    proc_ref["proc"].stdin.close()
    await proc_ref["proc"].wait()
    return produced_paths
