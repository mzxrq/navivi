"""The 3D whole-route overview rendered through pydeck (settings.use_pydeck_overview): a still image and the
animated video."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from typing import Dict, List, Optional, Tuple

import pydeck as pdk

from services import tuning

from .common import MAPBOX_API_KEY, logger
from .geomath import haversine_km
from .httpserver import start_local_server
from .recorder import _route_linestring_feature
from .routedata import patch_pydeck_html
from .leg_camera import _bbox_view, _nearest_index, _point_at_fraction
from .pin_icons import _OVERVIEW_PIN_SIZE_PX, _overview_pin_icons, _pin_layers

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


async def _record_overview(
    html_path, html_dir, output_size, output_path, fps, duration, hold_seconds,
    route_lonlat, cum_km, total_km, waypoints, progress_color, title_text,
):
    from playwright.async_api import async_playwright
    from services.vdoprocessing.vdoeditor import FFmpegEngine

    editor = FFmpegEngine()
    ffmpeg_cmd = [
        editor.resolve_binary(), "-y", *tuning.ffmpeg_log_args(),
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
                numbered = [wp for wp in waypoints if not wp.get("is_stopby")]
                pin_icons = {id(wp): row for wp, row in zip(numbered, _overview_pin_icons(numbered))}

                async def draw_frame(frac: float):
                    drawn = _point_at_fraction(route_lonlat, cum_km, total_km, frac)
                    progress_geojson = json.dumps(_route_linestring_feature(drawn, line_color=progress_color)) \
                        if len(drawn) >= 2 else json.dumps({"type": "FeatureCollection", "features": []})
                    revealed = [wp for wp in waypoints if wp["_reveal_frac"] <= frac]
                    pins = [pin_icons[id(wp)] for wp in revealed if not wp.get("is_stopby")]
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
                              'anim-wp-pins', 'anim-stopby-dots', 'anim-stopby-labels'].includes(l.id)
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
                        const wpPins = new deck.IconLayer({{
                            id: 'anim-wp-pins', data: {json.dumps(pins)},
                            getPosition: d => [d.lon, d.lat], getIcon: d => d.icon,
                            getSize: {_OVERVIEW_PIN_SIZE_PX}, sizeUnits: 'pixels', sizeScale: 1
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
                                      wpPins, stopbyDots, stopbyLabels]
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
