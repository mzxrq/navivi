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
import json
import math
import os
import tempfile
import urllib.parse
from typing import Dict, List, Optional, Tuple

import pandas as pd
import pydeck as pdk

from services import tuning

from .common import MAPBOX_API_KEY, logger
from .geomath import calculate_bearing, cumulative_distance_km, haversine_km, offset_point, smooth_bearings
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
            font_family='"Noto Sans JP", sans-serif',
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
            get_color=[255, 255, 255, 255], font_family='"Noto Sans JP", sans-serif',
            font_weight="bold", get_alignment_baseline="'center'",
        ),
    ]
    layers.extend(_landmark_layers(stopbys))
    return layers


# A teardrop map-pin (the classic FontAwesome marker outline, tip pointing
# straight down at its anchor point) instead of a flat scatterplot dot --
# a radial gradient (bright highlight top-left, darker toward the base) and
# a soft drop shadow give it the raised, "sitting on the map" look of a real
# 3D pin marker rather than a flat circle. The inner circle is cut out via
# fill-rule="evenodd" (a true hole, not a solid white disc), so the map
# shows through it exactly like a standard pin icon's punched-out center.
_TEARDROP_PIN_W, _TEARDROP_PIN_H = 384, 512
_TEARDROP_PIN_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 384 512" '
    f'width="{_TEARDROP_PIN_W}" height="{_TEARDROP_PIN_H}">'
    "<defs>"
    '<radialGradient id="pinGrad" cx="35%" cy="28%" r="75%">'
    '<stop offset="0%" stop-color="#ffb066"/>'
    '<stop offset="55%" stop-color="#ff8a3d"/>'
    '<stop offset="100%" stop-color="#d8480f"/>'
    "</radialGradient>"
    '<filter id="pinShadow" x="-60%" y="-60%" width="220%" height="220%">'
    '<feDropShadow dx="0" dy="6" stdDeviation="6" flood-color="#000" flood-opacity="0.4"/>'
    "</filter>"
    "</defs>"
    '<path filter="url(#pinShadow)" fill-rule="evenodd" fill="url(#pinGrad)" '
    'stroke="#b83c0f" stroke-width="6" '
    'd="M172.268 501.67C26.97 291.031 0 269.413 0 192 0 85.961 85.961 0 192 0s192 85.961 '
    "192 192c0 77.413-26.97 99.031-172.268 309.67-9.535 13.774-29.93 13.774-39.464 "
    "0zM192 272c44.183 0 80-35.817 80-80s-35.817-80-80-80-80 35.817-80 80 35.817 80 80 "
    '80z"/>'
    "</svg>"
)
_TEARDROP_PIN_URL = "data:image/svg+xml;charset=utf-8," + urllib.parse.quote(_TEARDROP_PIN_SVG)


def _destination_marker_layer(lat: float, lon: float, id_prefix: str = "leg-dest") -> List[pdk.Layer]:
    """A static 3D-looking teardrop pin (see _TEARDROP_PIN_SVG) at a leg's
    destination point -- render_residential_leg_pydeck's chase camera
    otherwise never marks the destination itself on the map, only the
    walker's already-traveled trail, so there was nothing to visually
    anchor "this is where I'm headed" to.

    `anchorY` is set to the icon's full height so the pin's own downward
    tip -- not its bounding box center -- sits exactly on (lat, lon),
    matching how a real map pin is planted at a location."""
    icon = {
        "url": _TEARDROP_PIN_URL,
        "width": _TEARDROP_PIN_W,
        "height": _TEARDROP_PIN_H,
        "anchorY": _TEARDROP_PIN_H,
    }
    data = [{"lon": lon, "lat": lat, "icon": icon}]
    return [
        pdk.Layer(
            "IconLayer", id=f"{id_prefix}-pin", data=data,
            get_icon="icon", get_position="[lon, lat]",
            get_size=44, size_units="pixels", size_scale=1,
            pickable=False,
        ),
    ]


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
    follow_pitch: float = 55.0,
    cam_follow_dist_m: float = 9.0,
    arrive_threshold_m: float = 60.0,
    line_thickness: int = 8,
    walker_color: List[int] = None,
    upcoming_color: List[int] = None,
    bearing_smoothing: float = 0.15,
    context_past_latlon: Optional[List[Tuple[float, float]]] = None,
    context_future_latlon: Optional[List[Tuple[float, float]]] = None,
    context_past_color: List[int] = None,
    context_future_color: List[int] = None,
    landmarks: Optional[List[Dict]] = None,
    arrival_hold_seconds: float = 2.0,
    route_chain: Optional[List[str]] = None,
) -> str:
    """Renders one leg as a tilted, bearing-following chase camera video
    with a live turn-by-turn HUD (destination banner + time/distance card)
    -- the GeoJsonLayer-route analogue of pydeckrecorder.recorder's
    driving-mode leg rendering, but with no vehicle scenegraph, and with
    actual on-screen HUD chrome recorder.py/renderer.py's driving path
    doesn't have.

    `leg_latlon`: [(lat, lon), ...] this leg's raw route points -- drawn
    two-tone: `walker_color` (default blue) behind the walker, growing as
    the leg progresses, and `upcoming_color` (default grey, a neutral
    "guide line" for the not-yet-walked path ahead) for the remainder.

    `context_past_latlon`/`context_future_latlon`: optional full polylines
    for the legs BEFORE/AFTER this one, drawn once as static background
    context (blue/green respectively, matching the reference video's
    three-way route coloring: completed legs blue, the active leg orange,
    legs still ahead green) -- neither animates or affects the HUD's
    distance/time, which is this leg's own only. Omit either (or both) to
    render just this leg, as before.

    `landmarks`: optional [{"lat", "lon", ("label")}, ...] -- unnumbered
    brown markers for points the route passes near without stopping (e.g.
    a leg's merged-in stop-by waypoints), drawn statically like the
    context routes above.

    `arrival_hold_seconds`: after the chase camera finishes traveling the
    leg, holds the final (arrived) frame on screen for this many extra
    seconds before the clip ends -- a plain freeze-frame so a viewer
    actually has time to register the destination and its marker (see
    `_destination_marker_layer`) rather than the clip cutting away the
    instant the walker arrives.

    `route_chain`: optional ["友ヶ島", "深山ノ鼻", "加太", ...] -- this leg's
    own place names in travel order (start through destination, including
    any stop-bys in between). Shown as a static breadcrumb pill in the
    top-left corner (e.g. "友ヶ島 → 深山ノ鼻 → 加太"), separate from the
    top-right destination banner, so a viewer can place this leg within
    the wider trip at a glance. Omit to leave the corner empty.

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
    Returns `output_path`.
    """
    if len(leg_latlon) < 2:
        raise ValueError("leg_latlon needs at least 2 points")

    walker_color = walker_color or [30, 136, 255]
    upcoming_color = upcoming_color or [170, 170, 170, 200]
    context_past_color = context_past_color or [50, 110, 230, 200]
    context_future_color = context_future_color or [46, 160, 67, 200]
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

    raw_bearings = [
        calculate_bearing(
            smooth_df.iloc[i]["lon"], smooth_df.iloc[i]["lat"],
            smooth_df.iloc[i + 1]["lon"], smooth_df.iloc[i + 1]["lat"],
        )
        for i in range(len(smooth_df) - 1)
    ]
    raw_bearings.append(raw_bearings[-1] if raw_bearings else 0.0)
    smooth_df["bearing"] = smooth_bearings(raw_bearings, alpha=bearing_smoothing)

    step_km = [0.0] + [
        haversine_km(
            smooth_df.iloc[i]["lon"], smooth_df.iloc[i]["lat"],
            smooth_df.iloc[i + 1]["lon"], smooth_df.iloc[i + 1]["lat"],
        )
        for i in range(len(smooth_df) - 1)
    ]
    cum_km = pd.Series(step_km).cumsum()
    remaining_km = cum_km.iloc[-1] - cum_km

    cam_coords = [
        offset_point(lon, lat, (b + 180) % 360, cam_follow_dist_m)
        for lon, lat, b in zip(smooth_df["lon"], smooth_df["lat"], smooth_df["bearing"])
    ]
    smooth_df["cam_lon"] = [c[0] for c in cam_coords]
    smooth_df["cam_lat"] = [c[1] for c in cam_coords]

    route_preview_path = df_raw[["lon", "lat"]].values.tolist()
    base_layers = [
        pdk.Layer(
            "GeoJsonLayer", id="route-preview",
            data=_route_linestring_feature(route_preview_path, line_color=upcoming_color),
            stroked=True, filled=False, get_line_color="properties.line_color",
            line_width_scale=1, line_width_min_pixels=max(2, line_thickness // 3),
        ),
    ]
    # Static neighboring-leg context, drawn once (never touched by the
    # per-frame loop) -- purely background color-coding, same reasoning as
    # this function's own docstring: completed legs blue, this leg orange
    # (already set above), legs still ahead green.
    if context_past_latlon and len(context_past_latlon) >= 2:
        base_layers.append(pdk.Layer(
            "GeoJsonLayer", id="context-past",
            data=_route_linestring_feature(
                [[lon, lat] for lat, lon in context_past_latlon], line_color=context_past_color,
            ),
            stroked=True, filled=False, get_line_color="properties.line_color",
            line_width_scale=1, line_width_min_pixels=max(2, line_thickness // 3),
        ))
    if context_future_latlon and len(context_future_latlon) >= 2:
        base_layers.append(pdk.Layer(
            "GeoJsonLayer", id="context-future",
            data=_route_linestring_feature(
                [[lon, lat] for lat, lon in context_future_latlon], line_color=context_future_color,
            ),
            stroked=True, filled=False, get_line_color="properties.line_color",
            line_width_scale=1, line_width_min_pixels=max(2, line_thickness // 3),
        ))
    base_layers.extend(_landmark_layers(landmarks or [], id_prefix="leg-landmark"))
    dest_lat, dest_lon = df_raw.iloc[-1]["lat"], df_raw.iloc[-1]["lon"]
    base_layers.extend(_destination_marker_layer(dest_lat, dest_lon))
    view_state = pdk.ViewState(
        longitude=smooth_df.iloc[0]["cam_lon"], latitude=smooth_df.iloc[0]["cam_lat"],
        zoom=follow_zoom, pitch=follow_pitch, bearing=smooth_df.iloc[0]["bearing"],
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

        asyncio.run(_record_leg(
            html_path, html_dir, output_size, output_path, fps,
            df_raw, smooth_df, remaining_km, total_frames, dest_label,
            travel_speed_kmh, arrive_threshold_m, line_thickness, walker_color,
            follow_zoom, follow_pitch, mode_hud, arrival_hold_seconds, route_chain,
        ))

    logger.info(f"Residential leg rendered ({mode}): {output_path}")
    return output_path


async def _record_leg(
    html_path, html_dir, output_size, output_path, fps,
    df_raw, smooth_df, remaining_km, total_frames, dest_label,
    travel_speed_kmh, arrive_threshold_m, line_thickness, walker_color,
    follow_zoom, follow_pitch, mode_hud, arrival_hold_seconds=2.0, route_chain=None,
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

                last_png_bytes = None
                crashed = False
                for index, row in smooth_df.iterrows():
                    frac = index / max(1, total_frames - 1)
                    n_pts = max(2, int(frac * len(all_trail_points)) + 1)
                    active_trail = all_trail_points[:n_pts]
                    trail_geojson = json.dumps(
                        _route_linestring_feature(active_trail, line_color=walker_color)
                    ) if len(active_trail) >= 2 else json.dumps({"type": "FeatureCollection", "features": []})
                    walker_json = json.dumps([{"lon": row["lon"], "lat": row["lat"]}])

                    rem_km = float(remaining_km.iloc[index])
                    rem_m = rem_km * 1000.0
                    rem_min = max(1, round((rem_km / travel_speed_kmh) * 60.0))
                    banner_text, dist_text = _hud_text(
                        dest_label, rem_m, rem_min, arrive_threshold_m, mode=mode_hud["mode"]
                    )

                    js = f"""
                    if (window.deckgl) {{
                        const currentLayers = window.deckgl.props.layers || [];
                        const staticLayers = currentLayers.filter(l => !['walker-trail', 'walker-dot', 'walker-halo'].includes(l.id));
                        const newTrail = new deck.GeoJsonLayer({{
                            id: 'walker-trail', data: {trail_geojson},
                            stroked: true, filled: false, getLineColor: d => d.properties.line_color,
                            lineWidthScale: 1, lineWidthMinPixels: {line_thickness}
                        }});
                        const newHalo = new deck.ScatterplotLayer({{
                            id: 'walker-halo', data: {walker_json},
                            getPosition: d => [d.lon, d.lat], getFillColor: {c_glow},
                            getRadius: 6, radiusMinPixels: 16
                        }});
                        const newDot = new deck.ScatterplotLayer({{
                            id: 'walker-dot', data: {walker_json},
                            getPosition: d => [d.lon, d.lat], getFillColor: [255, 255, 255, 255],
                            getLineColor: {c_trail}, stroked: true, lineWidthMinPixels: 3,
                            getRadius: 2, radiusMinPixels: 7
                        }});
                        window.deckgl.setProps({{
                            viewState: {{
                                longitude: {row["cam_lon"]}, latitude: {row["cam_lat"]},
                                zoom: {follow_zoom}, pitch: {follow_pitch}, bearing: {row["bearing"]},
                                transitionDuration: 0
                            }},
                            layers: [...staticLayers, newTrail, newHalo, newDot]
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
                        proc.stdin.write(png_bytes)
                        await proc.stdin.drain()
                        last_png_bytes = png_bytes
                    except Exception as e:
                        logger.error(f"[ERROR] FFmpeg crashed: {e}")
                        crashed = True
                        break

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
                        proc.stdin.write(last_png_bytes)
                        await proc.stdin.drain()
            finally:
                await browser.close()
    finally:
        server.shutdown()
        server.server_close()

    proc.stdin.close()
    await proc.wait()
