"""Pydeck-rendered static overview background — an alternative to
TileDownloader.fetch_overview_image's contextily/Esri raster stitching,
using deck.gl's own Mapbox basemap instead.

Locked to a top-down camera (pitch=0, bearing=0) so the projection stays a
simple, non-perspective Web Mercator map — the same closed-form math
RouteGeometryProcessor.project_latlon_to_pixel already uses for every
downstream pin/popup/leader-line placement keeps working completely
unmodified. A tilted/rotated camera (as pydeckrecorder's own
residential/driving mode uses, see recorder.py's pitch=60/bearing=30) would
turn this into a full 3D perspective that simple extent-based pixel math
can't reproduce — that tradeoff is the reason this stays a SEPARATE, single
static-image capture rather than reusing recorder.py's per-frame animation
path.

Because the deck.gl camera fits the target bbox via a continuous
(fractional) zoom instead of contextily's fixed integer tile-zoom levels,
the returned image needs no post-crop at all — it's screenshotted directly
at `output_size` already framing the exact requested bbox."""

import asyncio
import math
import os
import tempfile
from typing import Dict, List, Tuple

import cv2
import numpy as np
import pydeck as pdk

from services.vdoprocessing.pydeckrecorder.common import MAPBOX_API_KEY
from services.vdoprocessing.pydeckrecorder.httpserver import start_local_server
from services.vdoprocessing.pydeckrecorder.popupsequence import _wait_for_paint
from services.vdoprocessing.pydeckrecorder.routedata import patch_pydeck_html

_R = 6378137.0
_EARTH_CIRCUMFERENCE_M = 2 * math.pi * _R
# deck.gl (like mapbox-gl-js) tiles the world in 512px squares — this and
# _EARTH_CIRCUMFERENCE_M are what convert between a zoom level and real
# Web Mercator meters-per-pixel.
_TILE_SIZE_PX = 512


def _mercator_x(lon: float) -> float:
    return lon * (_R * math.pi / 180.0)


def _mercator_y(lat: float) -> float:
    return math.log(math.tan((90.0 + lat) * math.pi / 360.0)) * _R


def _inverse_mercator_y(my: float) -> float:
    return (2.0 * math.atan(math.exp(my / _R)) - math.pi / 2.0) * 180.0 / math.pi


def _fit_bbox_to_aspect(
    bounding_box: Dict[str, float], output_size: Tuple[int, int]
) -> Tuple[float, float, float, float]:
    """Identical expansion to TileDownloader.fetch_overview_image (maptile.py)
    — grows whichever axis (lon or lat span) is too narrow for the target
    aspect ratio, centered on the existing bbox. Kept in lockstep with that
    version so the two background sources frame a route the same way."""
    w, s, e, n = (
        bounding_box["min_lon"], bounding_box["min_lat"],
        bounding_box["max_lon"], bounding_box["max_lat"],
    )
    out_w, out_h = output_size
    target_ratio = out_w / out_h
    center_lat = (s + n) / 2.0
    lon_scale = math.cos(math.radians(center_lat))
    current_ratio = ((e - w) * lon_scale) / (n - s)
    if current_ratio < target_ratio:
        expansion = (((n - s) * target_ratio) / lon_scale - (e - w)) / 2.0
        w, e = w - expansion, e + expansion
    else:
        expansion = (((e - w) * lon_scale) / target_ratio - (n - s)) / 2.0
        s, n = s - expansion, n + expansion
    return w, s, e, n


def compute_pydeck_view(
    bounding_box: Dict[str, float], output_size: Tuple[int, int]
) -> Tuple[float, float, float, Tuple[float, float, float, float]]:
    """Returns (center_lon, center_lat, zoom, extent) for a top-down
    deck.gl camera that frames `bounding_box` (aspect-corrected to
    `output_size`) exactly. `extent` is in the same
    (min_x, max_x, min_y, max_y) Web Mercator meters convention
    RouteGeometryProcessor.project_latlon_to_pixel expects — derived
    directly from the SAME aspect-corrected bbox the camera is framing
    (not independently re-derived from the zoom), so the two can't drift
    apart from each other."""
    w, s, e, n = _fit_bbox_to_aspect(bounding_box, output_size)
    out_w, out_h = output_size

    min_x, max_x = _mercator_x(w), _mercator_x(e)
    min_y, max_y = _mercator_y(s), _mercator_y(n)
    extent = (min_x, max_x, min_y, max_y)

    center_lon = (w + e) / 2.0
    # Web Mercator's Y axis is nonlinear in latitude — averaging s/n
    # directly (the geographic midpoint) drifts from the true vertical
    # CENTER of the projected extent as latitude grows. Inverting the
    # mercator-meters midpoint instead keeps the deck.gl camera's actual
    # rendered center exactly aligned with `extent`'s own midpoint.
    center_lat = _inverse_mercator_y((min_y + max_y) / 2.0)

    meters_per_pixel = (max_x - min_x) / out_w
    zoom = math.log2(_EARTH_CIRCUMFERENCE_M / (_TILE_SIZE_PX * meters_per_pixel))

    return center_lon, center_lat, zoom, extent


async def _capture_static_deck(
    html_path: str, html_dir: str, output_size: Tuple[int, int], output_path: str
) -> None:
    from playwright.async_api import async_playwright

    server, port = start_local_server(html_dir)
    try:
        rel_path = os.path.relpath(html_path, html_dir).replace("\\", "/")
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    viewport={"width": output_size[0], "height": output_size[1]}
                )
                page = await context.new_page()
                await page.goto(f"http://127.0.0.1:{port}/{rel_path}")
                try:
                    await page.wait_for_load_state("load", timeout=5000)
                except Exception:
                    pass
                # Basemap tiles stream in after load — same real-time
                # margin render_leg_animation gives its 3D models before
                # the first frame, so tiles aren't still mid-fade-in when
                # the shot is taken.
                await page.wait_for_timeout(2500)
                await page.screenshot(path=output_path)
            finally:
                await browser.close()
    finally:
        server.shutdown()
        server.server_close()


def fetch_overview_image_pydeck(
    bounding_box: Dict[str, float],
    output_filename: str,
    output_size: Tuple[int, int] = (1920, 1080),
    mapbox_key: str = None,
    map_style: str = "mapbox://styles/mapbox/streets-v12",
) -> Tuple[str, Tuple[float, float, float, float], Tuple[int, int]]:
    """Pydeck/deck.gl equivalent of TileDownloader.fetch_overview_image —
    same (path, extent, size) return shape, so callers (see
    MapFetcher.fetch_image) can switch between the two sources without
    touching anything downstream. Renders one top-down deck.gl Mapbox
    basemap frame and screenshots it directly at `output_size`."""
    center_lon, center_lat, zoom, extent = compute_pydeck_view(bounding_box, output_size)

    view_state = pdk.ViewState(
        longitude=center_lon, latitude=center_lat, zoom=zoom, pitch=0, bearing=0,
    )
    # No layers — this is purely the basemap plate that pins/popups/route
    # line get drawn onto afterward by the existing OpenCV overlay code,
    # same role TileDownloader.fetch_overview_image's PNG plays today.
    deck = pdk.Deck(
        layers=[],
        initial_view_state=view_state,
        map_provider="mapbox",
        map_style=map_style,
        api_keys={"mapbox": mapbox_key or MAPBOX_API_KEY},
        views=[pdk.View(type="MapView", controller=False)],
    )

    os.makedirs(os.path.dirname(output_filename) or ".", exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="navivi_pydeck_overview_") as html_dir:
        html_path = os.path.join(html_dir, "overview.html")
        deck.to_html(html_path)
        patch_pydeck_html(html_path)
        asyncio.run(_capture_static_deck(html_path, html_dir, output_size, output_filename))

    return output_filename, extent, output_size


def _extent_for_view(
    center_lon: float, center_lat: float, zoom: float, output_size: Tuple[int, int]
) -> Tuple[float, float, float, float]:
    """The inverse of compute_pydeck_view's zoom derivation — given a
    view state directly (rather than a bbox to fit), returns the matching
    (min_x, max_x, min_y, max_y) Web Mercator meters extent
    RouteGeometryProcessor.project_latlon_to_pixel expects."""
    out_w, out_h = output_size
    meters_per_pixel = _EARTH_CIRCUMFERENCE_M / (_TILE_SIZE_PX * (2.0 ** zoom))
    center_mx, center_my = _mercator_x(center_lon), _mercator_y(center_lat)
    half_w_m = (out_w / 2.0) * meters_per_pixel
    half_h_m = (out_h / 2.0) * meters_per_pixel
    return (
        center_mx - half_w_m, center_mx + half_w_m,
        center_my - half_h_m, center_my + half_h_m,
    )


def _center_for_fixed_screen_point(
    target_lon: float, target_lat: float,
    target_px: float, target_py: float,
    zoom: float, output_size: Tuple[int, int],
) -> Tuple[float, float]:
    """The (longitude, latitude) the camera must center on, at `zoom`, so
    that (target_lon, target_lat) lands exactly at pixel
    (target_px, target_py) — the pan half of "zoom toward this point
    while keeping it fixed on screen", worked out algebraically from the
    same linear extent<->pixel relationship
    RouteGeometryProcessor.project_latlon_to_pixel uses (valid because the
    camera is locked top-down/pitch=0 — see this module's docstring)."""
    out_w, out_h = output_size
    meters_per_pixel = _EARTH_CIRCUMFERENCE_M / (_TILE_SIZE_PX * (2.0 ** zoom))
    tx, ty = _mercator_x(target_lon), _mercator_y(target_lat)
    center_mx = tx - (target_px - out_w / 2.0) * meters_per_pixel
    center_my = ty + (target_py - out_h / 2.0) * meters_per_pixel
    return center_mx / (_R * math.pi / 180.0), _inverse_mercator_y(center_my)


async def _capture_zoom_frames(
    html_path: str,
    html_dir: str,
    output_size: Tuple[int, int],
    view_states: List[Tuple[float, float, float]],
    out_frames: List[bytes],
) -> None:
    """Reuses a SINGLE page load across every requested (lon, lat, zoom)
    view state — driving deck.gl's camera live via `setProps` (same API
    pydeckrecorder's own per-frame driving-mode camera uses, see
    renderer.py) and screenshotting after each real repaint
    (_wait_for_paint), rather than reloading a fresh page per frame. A
    reload-per-frame approach would pay the ~2.5s tile-settle wait
    _capture_static_deck uses on every single frame — for a real
    multi-second zoom sequence that's the difference between a few
    seconds total and minutes."""
    from playwright.async_api import async_playwright

    server, port = start_local_server(html_dir)
    try:
        rel_path = os.path.relpath(html_path, html_dir).replace("\\", "/")
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    viewport={"width": output_size[0], "height": output_size[1]}
                )
                page = await context.new_page()
                await page.goto(f"http://127.0.0.1:{port}/{rel_path}")
                try:
                    await page.wait_for_load_state("load", timeout=5000)
                except Exception:
                    pass
                await page.wait_for_timeout(2500)
                for lon, lat, zoom in view_states:
                    await page.evaluate(
                        """([lon, lat, zoom]) => {
                            if (window.deckgl) {
                                window.deckgl.setProps({
                                    viewState: {
                                        longitude: lon, latitude: lat, zoom,
                                        pitch: 0, bearing: 0, transitionDuration: 0
                                    }
                                });
                            }
                        }""",
                        [lon, lat, zoom],
                    )
                    await _wait_for_paint(page)
                    # A repaint (_wait_for_paint) only guarantees the
                    # CANVAS drew a frame — it does NOT mean the new
                    # zoom's vector tiles have finished arriving or that
                    # Mapbox's label placement (asynchronous, separate
                    # from the raster draw) has settled. Without this,
                    # every frame except the very first (which gets a
                    # long initial wait in _capture_static_deck/above)
                    # rendered street/building geometry with NO text
                    # labels at all — verified empirically: a captured
                    # frame at zoom ~15.5 with only _wait_for_paint had
                    # zero road names, even though that zoom level
                    # normally shows them once tiles finish loading.
                    await page.wait_for_timeout(350)
                    out_frames.append(await page.screenshot())
            finally:
                await browser.close()
    finally:
        server.shutdown()
        server.server_close()


def capture_pydeck_zoom_sequence(
    bounding_box: Dict[str, float],
    output_size: Tuple[int, int],
    target_lat: float,
    target_lon: float,
    num_frames: int,
    zoom_boost: float = 1.6,
    mapbox_key: str = None,
    map_style: str = "mapbox://styles/mapbox/streets-v12",
) -> List[Tuple[np.ndarray, Tuple[float, float, float, float]]]:
    """A GENUINE dynamic zoom — `num_frames` real deck.gl re-renders as
    the camera pushes in from the base overview view toward
    (target_lat, target_lon), panned each frame so that point stays fixed
    at the exact pixel it sits at in the base (zoomed-out) frame — rather
    than fetch_overview_image_pydeck's single static screenshot digitally
    cropped/upscaled afterward (the Ken Burns approach used elsewhere in
    this codebase, see transitions.py's _ken_burns_hold). The tradeoff for
    the extra render cost (num_frames real captures instead of one) is
    that the map itself gets visibly sharper/more detailed as it zooms in
    — actual higher-resolution tiles, not upscaled pixels.

    Returns a list of (frame_bgr, extent) pairs, one per frame — extent
    changes with zoom, so the caller re-projects (via
    RouteGeometryProcessor.project_latlon_to_pixel) whatever pins/props
    need to be drawn on each frame fresh, rather than reusing one fixed
    pixel position throughout — that per-frame re-projection is what
    keeps a prop's position correct as the deck.gl camera's own actual
    view genuinely changes underneath it, as opposed to Ken Burns, where
    the same guarantee comes for free from cropping one already-composited
    image. The base (frame 0, most-zoomed-out) view exactly matches
    fetch_overview_image_pydeck's own output for the same bounding_box/
    output_size, so a sequence started here picks up seamlessly from an
    already-displayed static pydeck overview background."""
    base_lon, base_lat, base_zoom, base_extent = compute_pydeck_view(bounding_box, output_size)
    out_w, out_h = output_size

    from services.mapfetcher.mapgeometry import RouteGeometryProcessor

    target_px, target_py = RouteGeometryProcessor.project_latlon_to_pixel(
        target_lat, target_lon, base_extent, out_w, out_h
    )
    target_zoom = base_zoom + zoom_boost

    view_states: List[Tuple[float, float, float]] = []
    extents: List[Tuple[float, float, float, float]] = []
    for i in range(max(1, num_frames)):
        t = i / max(1, num_frames - 1)
        zoom = base_zoom + (target_zoom - base_zoom) * t
        c_lon, c_lat = _center_for_fixed_screen_point(
            target_lon, target_lat, target_px, target_py, zoom, output_size
        )
        view_states.append((c_lon, c_lat, zoom))
        extents.append(_extent_for_view(c_lon, c_lat, zoom, output_size))

    view_state = pdk.ViewState(
        longitude=base_lon, latitude=base_lat, zoom=base_zoom, pitch=0, bearing=0,
    )
    deck = pdk.Deck(
        layers=[],
        initial_view_state=view_state,
        map_provider="mapbox",
        map_style=map_style,
        api_keys={"mapbox": mapbox_key or MAPBOX_API_KEY},
        views=[pdk.View(type="MapView", controller=False)],
    )

    raw_frames: List[bytes] = []
    with tempfile.TemporaryDirectory(prefix="navivi_pydeck_zoom_") as html_dir:
        html_path = os.path.join(html_dir, "zoom.html")
        deck.to_html(html_path)
        patch_pydeck_html(html_path)
        asyncio.run(_capture_zoom_frames(html_path, html_dir, output_size, view_states, raw_frames))

    frames: List[Tuple[np.ndarray, Tuple[float, float, float, float]]] = []
    for data, ext in zip(raw_frames, extents):
        arr = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        frames.append((arr, ext))
    return frames
