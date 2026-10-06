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
import base64
import bisect
import json
import math
import os
import shutil
import string
import tempfile
import urllib.parse
from html import escape
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd
import pydeck as pdk

from services import tuning
from services.logger.progress import tracker
from services.vdoprocessing.cliptiming import write_audio_offset

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


def _landmark_layers(
    landmarks: List[Dict], id_prefix: str = "stopby", white_dot: bool = False
) -> List[pdk.Layer]:
    """landmarks: [{"lat", "lon", ("label")}, ...] -- small unnumbered brown
    dots with a plain label beside them, matching the reference video's
    landmark markers (e.g. a named junction/torii passed along the way):
    visually distinct from, and smaller than, the numbered orange pins
    real stops get. Used both for job_config.json stop-by waypoints
    (overview) and a leg's merged-in mid_markers (residential)."""
    if not landmarks:
        return []
    dots = [{"lon": lm["lon"], "lat": lm["lat"]} for lm in landmarks]
    # white_dot: residential's white-with-dark-ring marker (was the callout's dot).
    dot_layer = pdk.Layer(
        "ScatterplotLayer", id=f"{id_prefix}-dots", data=dots,
        get_position="[lon, lat]", get_fill_color=[255, 255, 255, 255],
        radius_units="'pixels'", get_radius=7,
        stroked=True, get_line_color=[51, 51, 51, 255], line_width_min_pixels=2,
    ) if white_dot else None
    layers = [dot_layer] if dot_layer else [
        pdk.Layer(
            "ScatterplotLayer", id=f"{id_prefix}-dots", data=dots,
            get_position="[lon, lat]", get_fill_color=[120, 80, 50, 255],
            get_radius=4, radius_min_pixels=6,
            stroked=True, get_line_color=[255, 255, 255, 220], line_width_min_pixels=1,
        ),
    ]
    # Same stadium pill every other place label uses (see
    # _label_pill_svg_url) rather than a TextLayer's own square background,
    # so a landmark's name reads as the same kind of thing as a waypoint's.
    layers.extend(
        _label_pill_layer(
            [
                {"lon": lm["lon"], "lat": lm["lat"], "text": lm.get("label") or ""}
                for lm in landmarks
            ],
            f"{id_prefix}-labels",
            size_px=26,
            pixel_offset_y=10,
        )
    )
    return layers


def _pin_layers(waypoints: List[Dict]) -> List[pdk.Layer]:
    """waypoints: [{"lat", "lon", "order", ("label"), ("is_stopby")}, ...].
    A stop-by waypoint (isStopBy in job_config.json -- a place the route
    passes near but doesn't really "stop" at) is drawn via _landmark_layers
    instead of getting a numbered pin -- mirrors spatial_renderer's own
    stop-by/numbering split (see overview.py's active_popups "order"
    handling: a stop-by is excluded from the visible 1..N count)."""
    numbered = [wp for wp in waypoints if not wp.get("is_stopby")]
    stopbys = [wp for wp in waypoints if wp.get("is_stopby")]

    layers = [
        pdk.Layer(
            "IconLayer", id="wp-pins", data=_overview_pin_icons(numbered),
            get_icon="icon", get_position="[lon, lat]",
            get_size=_OVERVIEW_PIN_SIZE_PX, size_units="'pixels'", size_scale=1, pickable=False,
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
# Matches draw_marker's own hole_radius = radius * 0.65, against the
# 192-unit head radius this path is drawn at.
_PIN_HOLE_R = 192 * 0.65


def _bgr_to_hex(bgr) -> str:
    """tuning.py's pin colors are OpenCV BGR triples (what the overview's
    own cv2 drawing takes); SVG needs RGB hex."""
    b, g, r = (int(c) for c in bgr[:3])
    return f"#{r:02x}{g:02x}{b:02x}"


def _teardrop_pin_svg_url(fill_hex: str, glyph: str = "") -> str:
    """One pin icon as an SVG data URL: `fill_hex` teardrop body, white
    outline, a SOLID white center disc with `glyph` ("S"/"E"/a visit-order
    number) in near-black inside it, plus a drop shadow.

    Built per pin rather than as one shared constant because the overview's
    pins differ in BOTH color and glyph from stop to stop. The center disc
    is deliberately filled (the pin used to punch a real hole through to the
    map via fill-rule="evenodd") -- draw_marker fills it so the glyph reads
    against the pin's own color instead of against whatever map tile happens
    to sit underneath.
    """
    glyph_svg = (
        '<text x="192" y="192" text-anchor="middle" dominant-baseline="central" '
        'font-family="Noto Sans JP, sans-serif" font-weight="700" '
        f'font-size="{150 if len(glyph) < 2 else 110}" '
        f'fill="{_bgr_to_hex(tuning.PIN_NUMBER_TEXT_COLOR)}">{glyph}</text>'
    ) if glyph else ""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 384 512" '
        f'width="{_TEARDROP_PIN_W}" height="{_TEARDROP_PIN_H}">'
        "<defs>"
        '<filter id="pinShadow" x="-60%" y="-60%" width="220%" height="220%">'
        '<feDropShadow dx="0" dy="6" stdDeviation="6" flood-color="#000" flood-opacity="0.4"/>'
        "</filter>"
        "</defs>"
        f'<path filter="url(#pinShadow)" fill="{fill_hex}" '
        'stroke="#ffffff" stroke-width="10" '
        'd="M172.268 501.67C26.97 291.031 0 269.413 0 192 0 85.961 85.961 0 192 0s192 85.961 '
        "192 192c0 77.413-26.97 99.031-172.268 309.67-9.535 13.774-29.93 13.774-39.464 "
        '0z"/>'
        f'<circle cx="192" cy="192" r="{_PIN_HOLE_R:.0f}" fill="#ffffff"/>'
        f"{glyph_svg}"
        "</svg>"
    )
    return "data:image/svg+xml;charset=utf-8," + urllib.parse.quote(svg)


# This leg's departure ("S") and arrival ("E") pins, in the overview's own
# start-green / end-red so both videos' pins read as the same system. Used
# when the caller doesn't pass the overview's own pin for either end (see
# _leg_pin_url).
_START_PIN_URL = _teardrop_pin_svg_url(_bgr_to_hex(tuning.START_PIN_COLOR), "S")
_DEST_PIN_URL = _teardrop_pin_svg_url(_bgr_to_hex(tuning.END_PIN_COLOR), "E")


_OVERVIEW_PIN_SIZE_PX = 48
_OVERVIEW_PIN_FALLBACK_BGR = (20, 80, 230)


def _overview_pin_icons(numbered: List[Dict]) -> List[Dict]:
    """IconLayer rows for the overview's numbered pins: teardrops with each
    waypoint's pin_glyph/pin_color (set by RouteAnimator), else its order."""
    return [
        {
            "lon": wp["lon"], "lat": wp["lat"],
            "icon": {
                "url": _teardrop_pin_svg_url(
                    _bgr_to_hex(wp.get("pin_color") or _OVERVIEW_PIN_FALLBACK_BGR),
                    str(wp.get("pin_glyph") or wp.get("order", "")),
                ),
                "width": _TEARDROP_PIN_W, "height": _TEARDROP_PIN_H, "anchorY": _TEARDROP_PIN_H,
            },
        }
        for wp in numbered
    ]


def _leg_pin_url(pin: Optional[Dict], fallback: str) -> str:
    """The pin icon for one end of a leg: the overview's own glyph and color
    for that waypoint ({"glyph": "S"/"3"/"E", "color": BGR}), so a leg reads
    as "pin 1 -> pin 2" of the overview; `fallback` when not given."""
    if not pin or not pin.get("glyph") or pin.get("color") is None:
        return fallback
    return _teardrop_pin_svg_url(_bgr_to_hex(pin["color"]), str(pin["glyph"]))

# Place-name label pill geometry, in SVG units (the icon is rendered at
# whatever pixel height its layer's get_size asks for, so these only set the
# label's own proportions).
_LABEL_FONT_SIZE = 40
_LABEL_H = 72
_LABEL_PAD_X = 30


def _label_pill_svg_url(
    text: str, bg: str = "rgba(30,34,40,0.82)", fg: str = "#ffffff"
) -> Tuple[str, int]:
    """A place name in a flowchart-terminator pill (a stadium: rx = half the
    height, so the ends are true semicircles) as an SVG data URL.

    Rendered as an ICON rather than a TextLayer `background` because that
    background is strictly rectangular -- deck.gl has no corner radius for
    it -- and as an icon rather than a DOM overlay because an icon is a real
    map layer: it tracks the camera through the intro/outro zooms on its
    own, where a DOM overlay would have to be re-projected by hand every
    frame.

    Its width is ESTIMATED from the text (CJK glyphs are full-width, Latin
    roughly half) since the pill has to be sized before the browser ever
    measures the string -- a few units of slack in the padding covers the
    estimate being a little off either way. Returns (data url, width) --
    the caller needs that width for the icon's own descriptor.
    """
    def _glyph_w(ch: str) -> float:
        # CJK/kana/full-width punctuation occupy a full em; almost
        # everything else in a place name (ASCII, spaces) about half.
        return 1.0 if ord(ch) > 0x2E7F else 0.55

    text_w = sum(_glyph_w(c) for c in text) * _LABEL_FONT_SIZE
    width = int(text_w + _LABEL_PAD_X * 2)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {_LABEL_H}" '
        f'width="{width}" height="{_LABEL_H}">'
        f'<rect x="1" y="1" width="{width - 2}" height="{_LABEL_H - 2}" '
        f'rx="{(_LABEL_H - 2) / 2:.0f}" ry="{(_LABEL_H - 2) / 2:.0f}" fill="{bg}"/>'
        f'<text x="{width / 2:.0f}" y="{_LABEL_H / 2:.0f}" text-anchor="middle" '
        f'dominant-baseline="central" font-family="Noto Sans JP, sans-serif" '
        f'font-weight="700" font-size="{_LABEL_FONT_SIZE}" fill="{fg}">{escape(text)}</text>'
        "</svg>"
    )
    return "data:image/svg+xml;charset=utf-8," + urllib.parse.quote(svg), width


def _label_pill_layer(
    entries: List[Dict], layer_id: str, size_px: int = 34, pixel_offset_y: int = 0
) -> List[pdk.Layer]:
    """One IconLayer of place-name pills. `entries`: [{"lat", "lon",
    "text"}, ...]. Anchored by its TOP edge (anchorY=0) so each pill hangs
    just BELOW its own point rather than covering the pin standing above
    it. `pixel_offset_y`: extra downward push (device pixels) past that
    anchor -- 0 is fine for a teardrop pin, whose own tip already sits
    exactly at the point, but a small round marker (e.g. a landmark dot,
    which is CENTERED on the point) needs a positive offset or the pill's
    top edge cuts straight through the dot instead of sitting below it."""
    data = []
    for e in entries:
        text = str(e.get("text") or "").strip()
        if not text:
            continue
        url, width = _label_pill_svg_url(text)
        data.append({
            "lon": e["lon"], "lat": e["lat"],
            "icon": {"url": url, "width": width, "height": _LABEL_H, "anchorY": 0},
        })
    if not data:
        return []
    return [
        pdk.Layer(
            "IconLayer", id=layer_id, data=data,
            get_icon="icon", get_position="[lon, lat]",
            get_size=size_px, size_units="'pixels'", size_scale=1, pickable=False,
            get_pixel_offset=f"[0, {pixel_offset_y}]",
        )
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


# Top clearance for a leg's locked framing, measured to a pin's POINT: the
# corner banners (#hud-banner/#hud-chain: 24px down, ~54px tall), a 16px gap,
# then the 60px pin standing above its point.
_LEG_TOP_MARGIN_PX = 24.0 + 54.0 + 16.0 + 60.0


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


# ---------------------------------------------------------------------------
# RESIDENTIAL: per-leg tilted chase camera + turn-by-turn HUD
# ---------------------------------------------------------------------------

_HUD_CSS_TEMPLATE = string.Template("""
#hud-banner {
    position: fixed; top: 24px; right: 24px;
    background: $pill_bg; color: $pill_text;
    font-family: "Noto Sans JP", sans-serif; font-weight: 700; font-size: 22px;
    padding: 12px 28px; border-radius: 999px; box-shadow: 0 4px 14px rgba(0,0,0,0.35);
    white-space: nowrap; z-index: 1000;
}
#hud-card {
    position: fixed; bottom: 32px; right: 32px;
    background: $card_bg; border: 3px solid $card_text; border-radius: 30px;
    padding: 28px 56px; display: flex; align-items: center; gap: 44px;
    font-family: "Noto Sans JP", sans-serif; box-shadow: 0 6px 20px rgba(0,0,0,0.35);
    z-index: 1000;
}
#hud-card .metric { text-align: center; }
#hud-card .metric .label { font-size: 20px; color: $card_label; display: flex; align-items: center; justify-content: center; gap: 6px; }
#hud-card .metric .value { font-size: 46px; font-weight: 700; color: $card_text; margin-top: 2px; }
#hud-card .divider { width: 1px; height: 64px; background: $divider; }
#hud-card .icon { width: 26px; height: 26px; line-height: 1; }
#hud-card .icon svg { display: block; width: 100%; height: 100%; }
#hud-card.hidden { display: none; }
#hud-card-img { position: fixed; bottom: 20px; right: 20px; z-index: 1000; }
/* Destination pill + compass stacked in the top-right corner, compass underneath. */
#hud-top-right {
    position: fixed; top: 24px; right: 24px; z-index: 1000;
    display: flex; flex-direction: column; align-items: flex-end; gap: 12px;
}
#hud-top-right #hud-banner { position: static; }
#hud-compass { display: block; filter: drop-shadow(0 4px 10px rgba(0,0,0,0.35)); }
#hud-compass .dial { fill: $card_bg; stroke: $card_text; stroke-width: 3; }
#hud-compass .tick { stroke: $card_label; stroke-width: 2; stroke-linecap: round; }
#hud-compass .tick.n { stroke: $card_text; stroke-width: 3; }
#hud-compass .letter { fill: $card_text; font: 700 15px "Noto Sans JP", sans-serif; }
#hud-compass .tail { fill: $card_label; }
#hud-compass-label {
    margin-top: -4px; min-width: 104px; box-sizing: border-box; text-align: center;
    background: $pill_bg; color: $pill_text;
    font-family: "Noto Sans JP", sans-serif; font-weight: 700; font-size: 16px;
    padding: 4px 12px; border-radius: 999px; box-shadow: 0 3px 10px rgba(0,0,0,0.3);
    white-space: nowrap; font-variant-numeric: tabular-nums;
}
#hud-banner .icon { font-size: 20px; line-height: 1; }
/* Sized to match #hud-banner, the pill it sits opposite in the other top
   corner -- at its old 16px against the banner's 22px the two read as
   different tiers of information rather than as a pair. */
#hud-chain {
    position: fixed; top: 24px; left: 24px;
    background: $pill_bg; color: $pill_text;
    font-family: "Noto Sans JP", sans-serif; font-weight: 700; font-size: 22px;
    padding: 12px 28px; border-radius: 999px; box-shadow: 0 4px 14px rgba(0,0,0,0.35);
    white-space: nowrap; z-index: 1000;
}
#hud-chain .arrow { opacity: 0.6; margin: 0 6px; }
""")


def _css_rgba(rgba) -> str:
    r, g, b, a = rgba
    return f"rgba({r}, {g}, {b}, {a / 255:.2f})"


def _hud_css(theme: Optional[str] = None) -> str:
    """Leg HUD CSS in the light/dark palette from tuning.UI_THEMES."""
    return _HUD_CSS_TEMPLATE.substitute(
        {k: _css_rgba(v) for k, v in tuning.ui_theme(theme).items()}
    )

# Per-mode distance-card icon: a plain black line-drawing SVG (currentColor
# stroke, no fill) instead of a platform emoji -- emoji glyphs are
# multicolor bitmaps that ignore CSS `color`, which is what "colored icon"
# meant here; a stroked SVG reads as a clean black/white pictogram matching
# the rest of the card's plain black-on-white styling regardless of the
# host's emoji font.
_MODE_ICON_SVG = {
    # Traced from assets/image/icon/walking.svg (potrace output) rather than
    # hand-drawn like the other modes below -- a solid walking-pictogram
    # silhouette instead of a thin line icon.
    "walking": (
        '<svg viewBox="0 0 757 1280" fill="#111" stroke="none">'
        '<g transform="translate(0,1280) scale(0.1,-0.1)">'
        """<path d="M4084 12786 c-416 -68 -756 -378 -860 -785 -125 -485 105 -988 553
-1210 165 -82 277 -106 478 -105 139 1 173 4 257 27 363 97 649 374 752 728
75 260 51 520 -69 764 -139 281 -387 483 -690 561 -123 31 -301 40 -421 20z"/>
<path d="M3765 10455 c-149 -24 -309 -86 -443 -172 -74 -46 -2133 -1715 -2202
-1783 -60 -59 -99 -121 -124 -197 -22 -70 -474 -2108 -482 -2173 -8 -72 15
-180 56 -260 87 -172 293 -278 483 -249 91 14 195 68 266 140 91 91 122 163
177 409 55 250 351 1598 356 1623 2 13 738 620 745 614 1 -1 -254 -1134 -567
-2518 l-568 -2516 -685 -1150 c-377 -633 -697 -1177 -710 -1209 -91 -218 -88
-412 9 -613 38 -78 60 -108 132 -181 99 -99 186 -152 304 -187 250 -72 497
-13 689 164 33 31 80 84 103 117 81 114 1517 2546 1576 2669 l59 122 178 823
c97 452 180 821 184 820 12 -6 1529 -1669 1529 -1677 0 -16 459 -2425 476
-2496 58 -253 250 -466 488 -541 330 -104 696 50 852 358 71 140 93 324 60
499 -8 41 -45 233 -81 425 -36 192 -115 608 -175 924 -60 316 -139 733 -175
925 -65 345 -95 462 -134 526 -11 18 -442 532 -958 1142 -516 609 -937 1114
-936 1120 8 44 475 2093 478 2096 2 2 96 -181 208 -406 158 -315 215 -420 251
-460 57 -63 1612 -1139 1711 -1184 189 -85 399 -46 539 100 173 182 179 463
13 647 -31 35 -269 204 -785 560 l-740 509 -145 290 c-643 1278 -931 1841
-966 1888 -257 349 -656 525 -1046 462z"/>"""
        "</g></svg>"
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


# 100x100 viewBox; only #hud-compass-needle rotates (about the centre).
_COMPASS_SVG = """<svg id="hud-compass" width="{size}" height="{size}" viewBox="0 0 100 100">
<circle class="dial" cx="50" cy="50" r="46"/>
<line class="tick n" x1="50" y1="7" x2="50" y2="15"/>
<line class="tick" x1="93" y1="50" x2="87" y2="50"/>
<line class="tick" x1="50" y1="93" x2="50" y2="87"/>
<line class="tick" x1="7" y1="50" x2="13" y2="50"/>
<text class="letter" x="50" y="31" text-anchor="middle">N</text>
<g id="hud-compass-needle">
<polygon class="tail" points="50,82 57,50 43,50"/>
<polygon fill="#d93a32" points="50,18 57,50 43,50"/>
</g>
<circle cx="50" cy="50" r="4" fill="#ffffff" stroke="#555" stroke-width="1.5"/>
</svg>"""


_COMPASS_POINTS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def _heading_label(deg: float) -> str:
    """e.g. 47.3 -> "NE 47°"."""
    deg = round(deg) % 360
    return f"{_COMPASS_POINTS[int((deg + 22.5) // 45) % 8]} {deg}°"


def _walk_headings(lons, lats, window_m: float) -> List[float]:
    """Per-frame compass heading (degrees clockwise from north) of the
    path, measured between the points `window_m` behind and ahead along it.
    Frames where the walker is standing still keep the heading around them."""
    n = len(lons)
    if n == 0:
        return []
    lat0 = math.radians(float(sum(lats)) / n)
    xs = [float(lon) * 111320.0 * math.cos(lat0) for lon in lons]
    ys = [float(lat) * 110540.0 for lat in lats]
    dist = [0.0]
    for i in range(1, n):
        dist.append(dist[-1] + math.hypot(xs[i] - xs[i - 1], ys[i] - ys[i - 1]))

    def at(d: float) -> Tuple[float, float]:
        d = min(max(d, 0.0), dist[-1])
        j = min(max(bisect.bisect_left(dist, d), 1), n - 1) if n > 1 else 0
        if n == 1 or dist[j] == dist[j - 1]:
            return xs[j], ys[j]
        t = (d - dist[j - 1]) / (dist[j] - dist[j - 1])
        return xs[j - 1] + (xs[j] - xs[j - 1]) * t, ys[j - 1] + (ys[j] - ys[j - 1]) * t

    headings: List[Optional[float]] = []
    for d in dist:
        (ax, ay), (bx, by) = at(d - window_m), at(d + window_m)
        if math.hypot(bx - ax, by - ay) < 0.5:
            headings.append(None)
        else:
            headings.append(math.degrees(math.atan2(bx - ax, by - ay)) % 360.0)
    first = next((h for h in headings if h is not None), 0.0)
    out, last = [], first
    for h in headings:
        last = h if h is not None else last
        out.append(last)
    return out


def _remaining_minutes(remaining_m: float, remaining_km: float, travel_speed_kmh: float) -> int:
    """Minutes-left for the HUD card, floored to 1 so a leg that's still
    actually in progress never displays "0 分" -- except when the distance
    itself has already rounded down to "0 m" on the card, where a floored
    "1 分" would contradict the distance sitting right next to it."""
    minutes = round((remaining_km / travel_speed_kmh) * 60.0)
    return minutes if round(remaining_m) == 0 else max(1, minutes)


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


def _segment_plan(df_raw, leg_dist_km, landmarks, total_seconds):
    """[(last raw point index, seconds)] for a leg cut at connected stop-bys, from
    each landmark's own `walk_seconds` (the last piece gets what is left of
    `total_seconds`). None when the leg has no cut, a landmark has no time, or
    the stop-bys don't come in route order - the leg then walks at one speed."""
    if not landmarks or total_seconds is None:
        return None
    stops = [
        lm for lm in landmarks
        if lm.get("connect_to_route") and lm.get("popup_image")
        and lm.get("lat") is not None and lm.get("lon") is not None
    ]
    if not stops or any(lm.get("walk_seconds") is None for lm in stops):
        return None
    plan, prev_idx, used = [], 0, 0.0
    for lm in stops:
        sq = (df_raw["lat"] - lm["lat"]) ** 2 + (df_raw["lon"] - lm["lon"]) ** 2
        idx = int(sq.idxmin())
        if idx <= prev_idx:
            return None
        plan.append((idx, float(lm["walk_seconds"])))
        prev_idx, used = idx, used + float(lm["walk_seconds"])
    last = max(1.0, float(total_seconds) - used)
    plan.append((len(df_raw) - 1, last))
    return plan


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
    start_popup_image: Optional[str] = None,
    start_popup_freeze_seconds: Optional[float] = None,
    dest_popup_narration_seconds: Optional[float] = None,
    start_popup_narration_seconds: Optional[float] = None,
    start_cue_seconds: Optional[float] = None,
    arrival_photo_hold_seconds: Optional[float] = None,
    arrival_wait_seconds: Optional[float] = None,
    dest_image_display: str = "cover",
    start_pin: Optional[Dict] = None,
    dest_pin: Optional[Dict] = None,
    hud_card_png: Optional[Callable[[float, float], bytes]] = None,
    theme: Optional[str] = None,
    bottom_reserve_px: float = 0.0,
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
    marker's own on-screen position before the walk continues. One with a
    `popup_image` but `connect_to_route` False/absent (the route only
    passes NEAR it) gets a lighter touch instead: a small pip card pops in
    beside its marker as the walker nears it, holds, and fades back out --
    no fullscreen growth, no leg cut, since the walk never actually visits
    it (see `_play_stopby_photo_pause`'s `pip_only` path).

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

    `start_popup_image`: only ever set on the trip's very first leg (its
    departure is the trip's own true first waypoint, which is never
    anyone's destination and so never otherwise gets a residential popup
    moment — every other leg's departure IS the previous leg's destination,
    already previewed there via `dest_popup_image`). Gets the exact same
    fullscreen -> shrink-to-leader-card treatment as `dest_popup_image`
    (see `_play_leg_photo_card`, the shared implementation) and plays
    FIRST, right after the warm-up frame, before the destination preview.
    Skipped entirely when there's no photo.

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

    `dest_popup_narration_seconds`/`start_popup_narration_seconds`: the
    narration length of the destination/departure waypoint, passed by
    route2vdo.py. Accepted for its callers but not used yet: the photo holds
    do not wait for narration (leg_pieces.py pads the clip's tail instead).

    `start_cue_seconds`: when the leg's narration carries a {start} cue, the
    second of the narration at which the walker should START moving. The
    narration then plays from the clip's first frame: if the opening (warm-up,
    photos, intro zoom) ends before that, its last frame is held until the
    cue; if it ends after, the narration is delayed by the difference. Left
    None, the narration is delayed by the whole opening so the voice starts
    with the walk. Either way the delay is written next to the clip as a
    `.timing.json` (see services/vdoprocessing/cliptiming.py) for the
    subtitle burn and final export to apply. Only legs that are not cut by a
    connected stop-by get one.

    `arrival_photo_hold_seconds`: how long the at-arrival photo stays fullscreen
    AFTER it has finished growing. The clip's last frames are these, so the
    caller can dissolve them into the attraction video that follows: the photo
    grows to fullscreen first, then fades - the fade never overlaps the grow.
    Defaults to tuning.RESIDENTIAL_ARRIVAL_POPUP_HOLD_SECONDS (0).

    `arrival_wait_seconds`: the walker got to the destination before its
    narration ended. It stays put on the arrived map for this long (the voice
    finishing), and only then does the at-arrival photo start to grow. Left
    None, the old fixed pauses apply (tuning.RESIDENTIAL_ARRIVAL_FREEZE_SECONDS,
    `arrival_hold_seconds`).

    `dest_image_display`: the destination waypoint's `image_display` from
    job_config.json decides how its at-arrival photo ends: "pip" keeps a small
    card (no fullscreen), anything else ("cover"/"fullscreen") grows to
    fullscreen. Either way the clip then dissolves into the attraction video.

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

    segment_plan = _segment_plan(df_raw, leg_dist_km, landmarks, target_duration_seconds)
    leg_duration = (
        max(1.0, float(target_duration_seconds)) if target_duration_seconds is not None
        else max(3.0, (total_leg_km / travel_speed_kmh) * 3600.0)
    )
    total_frames = max(10, int(leg_duration * fps))

    smooth_df = interpolate_route_data(
        df_raw, leg_duration, total_frames, total_leg_km, leg_dist_km, segment_plan=segment_plan
    )

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
            # Exactly the walked trail's own thickness (see _record_leg's
            # 'walker-trail' layer) -- the guide line is the SAME road, just
            # not yet travelled, so a thinner stroke made the trail look like
            # it was widening as it advanced rather than filling the line in.
            line_width_scale=1, line_width_min_pixels=line_thickness,
        ),
    ]
    base_layers.extend(_landmark_layers(landmarks or [], id_prefix="leg-landmark", white_dot=True))
    # The start pin is static (this leg's starting point never moves) so it
    # goes straight into base_layers and is visible for the whole clip, same
    # as the destination pin below.
    start_lat, start_lon = df_raw.iloc[0]["lat"], df_raw.iloc[0]["lon"]
    base_layers.append(
        pdk.Layer(
            "IconLayer", id="leg-start-pin",
            data=[{
                "lon": start_lon, "lat": start_lat,
                "icon": {
                    "url": _leg_pin_url(start_pin, _START_PIN_URL), "width": _TEARDROP_PIN_W,
                    "height": _TEARDROP_PIN_H, "anchorY": _TEARDROP_PIN_H,
                },
            }],
            get_icon="icon", get_position="[lon, lat]",
            get_size=60, size_units="'pixels'", size_scale=1, pickable=False,
        )
    )
    # The departure's own place name, in the same pill every other label
    # uses. route_chain is this leg's places in travel order, so its FIRST
    # entry is the waypoint this pin marks (the chain is omitted on a leg
    # that has no names at all, in which case the pin just goes unlabelled).
    start_label = (route_chain[0] if route_chain else "") or ""
    base_layers.extend(
        _label_pill_layer(
            [{"lon": start_lon, "lat": start_lat, "text": start_label}],
            "leg-start-label",
            size_px=34,
            pixel_offset_y=8,
        )
    )
    # Destination pin + name pill, shown for the whole leg (stop-by-cut
    # pieces included) so the viewer sees where the route is headed.
    dest_lat, dest_lon = df_raw.iloc[-1]["lat"], df_raw.iloc[-1]["lon"]
    base_layers.append(
        pdk.Layer(
            "IconLayer", id="leg-dest-pin",
            data=[{
                "lon": dest_lon, "lat": dest_lat,
                "icon": {
                    "url": _leg_pin_url(dest_pin, _DEST_PIN_URL), "width": _TEARDROP_PIN_W,
                    "height": _TEARDROP_PIN_H, "anchorY": _TEARDROP_PIN_H,
                },
            }],
            get_icon="icon", get_position="[lon, lat]",
            get_size=60, size_units="'pixels'", size_scale=1, pickable=False,
        )
    )
    base_layers.extend(
        _label_pill_layer(
            [{"lon": dest_lon, "lat": dest_lat, "text": dest_label or ""}],
            "leg-dest-label",
            size_px=34,
            pixel_offset_y=8,
        )
    )

    # The whole-leg "locked" camera: fits the leg's entire path in frame
    # (not a close street-level follow) and, once the intro's zoom-in
    # finishes, stays fixed there for the rest of the leg's walking
    # animation -- see _record_leg's main loop, which no longer re-centers
    # on the walker every frame the way the old chase-cam did. Capped at
    # follow_zoom so a very short/tight leg's fit-zoom can't exceed the
    # level the rest of this module treats as "close" street level.
    # The whole-leg "locked" camera: fits the leg's entire path in frame.
    # SPECIAL CASE: if the leg is interrupted by a connected stop-by photo pause,
    # compute the bounding box only up to that first stop-by so the camera
    # tightly frames the segment actually being walked in this clip, instead
    # of zooming out to fit the entire multi-segment route at once.
    fit_df = df_raw
    for lm in (landmarks or []):
        if lm.get("connect_to_route") and lm.get("popup_image") and lm.get("lat") is not None and lm.get("lon") is not None:
            sq_dist = (df_raw["lat"] - lm["lat"]) ** 2 + (df_raw["lon"] - lm["lon"]) ** 2
            closest_idx = int(sq_dist.idxmin())
            # Use only a minimal +2 buffer. The previous +10 included points
            # much further down the route, which skewed the bounding box center
            # and pushed the visible portion off-center.
            fit_df = df_raw.iloc[:closest_idx + 2]
            break

    locked_lon, locked_lat, locked_zoom = _fit_view_for_path(
        fit_df["lon"].tolist(), fit_df["lat"].tolist(), output_size,
        padding_frac=0.15, pitch=follow_pitch,
        bottom_margin_px=_leg_bottom_margin_px(bottom_reserve_px),
        top_margin_px=_LEG_TOP_MARGIN_PX,
    )
    # Lock max zoom to 17.5 to prevent extreme zoom-in for very short segments
    locked_zoom = min(locked_zoom, 17.5)

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
            start_popup_image, start_popup_freeze_seconds, start_cue_seconds,
            arrival_photo_hold_seconds, arrival_wait_seconds, dest_image_display,
            dest_pin_url=_leg_pin_url(dest_pin, _DEST_PIN_URL),
            hud_card_png=hud_card_png, theme=theme, bottom_reserve_px=bottom_reserve_px,
        ))

    logger.info(f"Residential leg rendered ({mode}): {produced_paths}")
    return produced_paths


# Screenshot options for every frame a residential leg pipes into ffmpeg
# (read as mjpeg - see _record_leg's _spawn_ffmpeg). All frames of one pipe
# must share this format.
_FRAME_SHOT = {"type": "jpeg", "quality": tuning.LEG_FRAME_JPEG_QUALITY}


async def _play_stopby_photo_pause(
    page, write_frame, cut_to_new_clip, fps, html_dir, port, stopby,
    view_lon, view_lat, zoom, output_size, trigger_index, pitch,
    pip_only: bool = False,
    advance_frame=None, frame_index: int = 0, frame_total: int = 0,
    small_hold_seconds: Optional[float] = None,
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
    - Has an attraction video (`image_display` is ignored - always
      fullscreen): grows to fullscreen like the no-attraction
      case, but ends with a cinematic blur-out (matching popupsequence.
      py's own arrival blur-out) instead of a flat cut, then cuts to a new
      file that likewise resumes the walk directly.

    `pip_only`: for an UNCONNECTED landmark with its own photo -- the
    route only passes NEAR it, so unlike a connected stop-by the walk
    never actually stops there, has no attraction video, and never cuts
    the leg into an extra file. The walker keeps moving along the route
    for the whole pop-in/hold/fade-out beat (via `advance_frame`, the
    caller's own per-frame walker-draw callback) instead of freezing --
    a "look, passing this" aside, not an arrival. Returns the next
    unconsumed frame index so the caller's own loop can resume exactly
    where this left off."""
    photo_path = stopby.get("popup_image")
    if not photo_path or not os.path.exists(photo_path):
        return

    has_attraction = bool(stopby.get("attraction_video"))

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
        stopby["lon"], stopby["lat"], view_lon, view_lat, zoom, output_size, pitch=pitch
    )
    full_box = (0.0, 0.0, float(out_w), float(out_h))
    # Small leader card, same aspect ratio as the frame itself (keeps the
    # object-fit:cover crop identical at every size -- see the leg-opening
    # sequence's own note on why this matters), floated just above the
    # marker with a leader line connecting its bottom edge down to it. Same
    # size for every card regardless of pip_only -- a pip stays this size
    # the whole time, a connected stop-by's card only starts here before
    # growing to fullscreen, but there's no reason for the two to look
    # like different card sizes in the moment before that growth.
    card_w = 200.0
    card_h = card_w * (float(out_h) / float(out_w))
    card_gap = 26.0
    card_margin = 16.0
    # Clamped to stay fully inside the frame -- a marker near an edge (see
    # the screenshot that prompted this: 石標 sitting right near the top
    # edge) used to float this card straight off-screen, floating it
    # centered/above the marker unconditionally with no bounds check at
    # all. The leader line's own anchor point is recomputed from the
    # CLAMPED box below (its bottom-center), not the marker's raw
    # position, so it still visibly connects to wherever the card actually
    # ended up instead of pointing at empty space.
    card_left = min(
        max(marker_x - card_w / 2.0, card_margin), out_w - card_w - card_margin
    )
    card_top = min(
        max(marker_y - card_gap - card_h, card_margin), out_h - card_h - card_margin
    )
    card_box = (card_left, card_top, card_w, card_h)
    anchor_x, anchor_y = card_left + card_w / 2.0, card_top + card_h

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
            // No dot of its own: the landmark layer already marks the stop-by.
            svg.appendChild(line);
            document.body.appendChild(svg);

            if (img.decode) { img.decode().then(resolve).catch(resolve); }
            else { img.onload = resolve; img.onerror = resolve; }
            setTimeout(resolve, 2000);
        })""",
        [img_url, card_box[0], card_box[1], card_box[2], card_box[3], anchor_x, anchor_y, marker_x, marker_y],
    )
    await _wait_for_paint(page)

    if pip_only:
        # Unconnected landmark: no growth, no attraction video, no leg
        # cut, and (unlike the shared pop-in/hold below) no freeze either
        # -- each rendered step also advances the walker one frame via
        # the caller's own `advance_frame`, so the dot/trail keep moving
        # under the card for the whole pop-in/hold/fade-out beat instead
        # of stalling. Falls back to a plain repeated screenshot (the old
        # frozen behavior) if the caller didn't wire up `advance_frame`.
        idx = frame_index
        pop_frames = max(1, int(0.3 * fps))
        hold_frames = max(1, int(0.5 * fps))
        fade_frames = max(1, int(0.4 * fps))
        for i in range(pop_frames + hold_frames + fade_frames):
            if i < pop_frames:
                alpha = _ease_in_out_cubic((i + 1) / pop_frames)
            elif i < pop_frames + hold_frames:
                alpha = 1.0
            else:
                fade_i = i - (pop_frames + hold_frames)
                alpha = 1.0 - ((fade_i + 1) / fade_frames)
            await page.evaluate(
                """([a]) => {
                    const img = document.getElementById('stopby-preview');
                    if (img) img.style.opacity = a;
                    const line = document.getElementById('stopby-leader-line');
                    if (line) line.setAttribute('opacity', a);
                }""",
                [alpha],
            )
            if advance_frame is not None and idx < frame_total:
                png_bytes = await advance_frame(idx)
                idx += 1
                if png_bytes is None:
                    break
            else:
                await write_frame(await page.screenshot(**_FRAME_SHOT))
        await page.evaluate(
            """() => {
                const svg = document.getElementById('stopby-leader'); if (svg) svg.remove();
                const img = document.getElementById('stopby-preview'); if (img) img.remove();
            }"""
        )
        return idx

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
        await write_frame(await page.screenshot(**_FRAME_SHOT))

    # The small card stays up for `small_hold_seconds` when the walker got here
    # early and is waiting for the narration to finish; only then does it grow.
    hold_png = await page.screenshot(**_FRAME_SHOT)
    for _ in range(max(1, int((0.5 if small_hold_seconds is None else small_hold_seconds) * fps))):
        await write_frame(hold_png)

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
        await write_frame(await page.screenshot(**_FRAME_SHOT))

    # The leader line/dot have no further use once fullscreen -- gone
    # before the cut so the NEW clip never inherits a stray leftover node.
    await page.evaluate(
        "() => { const svg = document.getElementById('stopby-leader'); if (svg) svg.remove(); }"
    )

    # Hold at fullscreen size BEFORE cutting/blurring -- the grow animation
    # used to run straight into the cut with no pause at all, so the photo
    # was on screen at full size for a single frame before vanishing; a
    # viewer never actually got to register it fullscreen.
    grown_png = await page.screenshot(**_FRAME_SHOT)
    dissolve = has_attraction and bool(stopby.get("dissolve_into_attraction"))
    # With a dissolve into the attraction video the photo is not held: the clip
    # ends as it reaches fullscreen and the dissolve starts right from there.
    for _ in range(1 if dissolve else max(1, int(freeze_sec * fps))):
        await write_frame(grown_png)

    if has_attraction and dissolve:
        await page.evaluate(
            "() => { const img = document.getElementById('stopby-preview'); if (img) img.remove(); }"
        )
        await cut_to_new_clip()
        return

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
            await write_frame(await page.screenshot(**_FRAME_SHOT))

        await page.evaluate(
            "() => { const img = document.getElementById('stopby-preview'); if (img) img.remove(); }"
        )
        await cut_to_new_clip()
        return

    await cut_to_new_clip()

    fullscreen_png = await page.screenshot(**_FRAME_SHOT)
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
        await write_frame(await page.screenshot(**_FRAME_SHOT))

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
    start_popup_image=None, start_popup_freeze_seconds=None, start_cue_seconds=None,
    arrival_photo_hold_seconds=None, arrival_wait_seconds=None, dest_image_display="cover",
    dest_pin_url=_DEST_PIN_URL,
    hud_card_png: Optional[Callable[[float, float], bytes]] = None,
    theme: Optional[str] = None,
    bottom_reserve_px: float = 0.0,
):
    from pathlib import Path

    from playwright.async_api import async_playwright
    from services.vdoprocessing.vdoeditor import FFmpegEngine
    from services.vdoprocessing.vdoexporter import VideoExporter, _replace_with_retry

    editor = FFmpegEngine()

    async def _spawn_ffmpeg(out_path: str):
        # Encodes into a private temp file in out_path's own directory
        # (same convention as VideoExporter, which the overview/waypoints
        # renderers already use), not out_path itself -- see
        # `_finalize_clip`, the only place that ever touches out_path, so
        # a render killed mid-stream leaves only that throwaway temp file
        # behind instead of a half-written/corrupted final video.
        temp_path = VideoExporter._make_temp_path(out_path)
        ffmpeg_cmd = [
            editor.resolve_binary(), "-y", *tuning.ffmpeg_log_args(),
            "-f", "image2pipe", "-vcodec", "mjpeg", "-framerate", str(fps), "-i", "-",
            "-c:v", "libx264", *tuning.ffmpeg_thread_args(),
            "-r", str(fps), "-pix_fmt", "yuv420p", temp_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL
        )
        return proc, temp_path

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
    _first_proc, _first_temp = await _spawn_ffmpeg(output_path)
    proc_ref = {"proc": _first_proc, "temp_path": _first_temp, "real_path": output_path}
    produced_paths = [output_path]

    # Frames written so far and the latest one: the opening's length (see
    # start_cue_seconds) is measured from this, not predicted.
    frame_state = {"count": 0, "last": None, "cuts": 0, "clip_start": 0}

    async def _write_frame(png_bytes: bytes) -> None:
        proc_ref["proc"].stdin.write(png_bytes)
        await proc_ref["proc"].stdin.drain()
        frame_state["count"] += 1
        frame_state["last"] = png_bytes

    async def _finalize_clip() -> None:
        """Closes the CURRENT clip's ffmpeg process and, only once it's
        confirmed a clean exit, atomically renames its temp file onto its
        real target path -- the one moment that real path is ever touched.
        A crash/nonzero exit instead deletes the temp file and leaves
        whatever was already at the real path (if anything) untouched."""
        proc_ref["proc"].stdin.close()
        await proc_ref["proc"].wait()
        if proc_ref["proc"].returncode == 0:
            _replace_with_retry(proc_ref["temp_path"], proc_ref["real_path"])
        else:
            logger.error(
                f"[ERROR] FFmpeg exited {proc_ref['proc'].returncode} while "
                f"producing '{proc_ref['real_path']}' -- leaving it untouched."
            )
            Path(proc_ref["temp_path"]).unlink(missing_ok=True)

    async def _cut_to_new_clip() -> None:
        """Finalizes the CURRENT output file (see `_finalize_clip`) and
        opens a fresh one for `_write_frame` to target from here on -- see
        `_play_stopby_photo_pause`, the only caller. The continuation file
        keeps this leg's own "02_waypoint_{N:02d}_" filename prefix (just
        with a "_cont{n}" suffix inserted) so timeline_step.py's filename
        parse still resolves it to this SAME leg's narration/subtitle --
        see route2vdo.py's own note and timeline_step.py's
        _split_leg_narration_for_pieces for how the leg's one narration
        track gets split proportionally across however many pieces this
        produces."""
        await _finalize_clip()
        stem, ext = os.path.splitext(output_path)
        new_path = f"{stem}_cont{len(produced_paths) + 1}{ext}"
        new_proc, new_temp = await _spawn_ffmpeg(new_path)
        proc_ref["proc"], proc_ref["temp_path"], proc_ref["real_path"] = new_proc, new_temp, new_path
        produced_paths.append(new_path)
        frame_state["cuts"] += 1
        frame_state["clip_start"] = frame_state["count"]

    async def _play_leg_photo_card(
        image_path, freeze_seconds_raw, card_key: str, marker_px=None, grow: bool = False,
        cut_after: bool = False, hold_seconds: Optional[float] = None,
        quick: bool = False, small_hold_seconds: Optional[float] = None,
        pip_end: bool = False,
    ) -> bool:
        """Shared by every one of this leg's photo beats -- the opening
        departure preview (`start_popup_image`, only ever set on the trip's
        very first leg), the opening destination preview
        (`dest_popup_image`), and the at-arrival destination preview (see
        this function's own arrival caller) -- called one after another
        (never concurrently) on this leg's single page/DOM, so all three
        safely reuse the same element ids; `card_key` only needs to keep
        their COPIED IMAGE FILEs distinct (see pedestrian.py's own stop-by
        trigger_index comment on why a shared filename risks serving the
        wrong cached photo).

        `marker_px`: where the card's leader line points -- defaults to the
        viewport's own center (correct for the two OPENING previews, whose
        camera is centered exactly on the start marker for that whole warm
        phase -- see the warm_js call). The at-arrival call passes the
        destination pin's own actual on-screen position instead (projected
        via `_project_lonlat_to_px`), since the locked camera does NOT
        recenter on it.

        `grow` (default False): fullscreen photo -> shrink to a small
        leader-line card -> freeze -> fade out -- used for the two OPENING
        previews. True reverses the direction -- pops in AT the small card
        size (leader line already drawn) -> holds -> GROWS to fullscreen ->
        freeze -> fade out -- mirroring `_play_stopby_photo_pause`'s own
        card-then-fullscreen treatment, so the at-arrival preview reads
        consistently with every other in-route popup instead of standing
        out as the only fullscreen-first one.

        `cut_after` (grow only): skips the fade-out -- holds at fullscreen
        for `freeze_sec` then returns immediately, leaving the fullscreen
        photo as the last frame written. The caller is expected to end the
        clip right there (no outro afterward) rather than write anything
        more after this returns.

        `hold_seconds`: overrides how long the photo is held at its final
        size, replacing both the waypoint's own `freeze_seconds_raw` AND the
        POPUP_MIN_DISPLAY_SECONDS floor it would otherwise be clamped to --
        the at-arrival caller uses it for a hold deliberately shorter than
        that floor.

        Returns True if it actually played something (a caller that also
        wants to skip its own post-photo steps, like the outro, checks
        this instead of re-deriving "did this leg have a photo" itself)."""
        if not image_path or not os.path.exists(image_path):
            return False
        img_ext = os.path.splitext(image_path)[1] or ".jpg"
        img_name = f"leg_photo_card_{card_key}{img_ext}"
        shutil.copy2(image_path, os.path.join(html_dir, img_name))
        img_url = f"http://127.0.0.1:{port}/{img_name}"

        # quick (the at-arrival photo): a brief pop-in and an immediate grow
        # to fullscreen - a transition, not a beat to sit on.
        fade_in_s, small_hold_s, grow_s = (0.2, 0.0, 0.6) if quick else (0.3, 0.4, 0.7)
        if small_hold_seconds is not None:
            small_hold_s = float(small_hold_seconds)  # arrived early: the small card waits for the voice
        if hold_seconds is not None:
            # Explicit override -- NOT run through the POPUP_MIN_DISPLAY_
            # SECONDS floor below, since the only caller that passes it
            # deliberately wants a hold shorter than that floor (see
            # tuning.RESIDENTIAL_ARRIVAL_POPUP_HOLD_SECONDS).
            freeze_sec = float(hold_seconds)
        else:
            freeze_sec = (
                float(freeze_seconds_raw)
                if freeze_seconds_raw is not None
                else tuning.POPUP_MIN_DISPLAY_SECONDS
            )
            freeze_sec = min(
                max(freeze_sec, tuning.POPUP_MIN_DISPLAY_SECONDS),
                tuning.POPUP_FREEZE_SECONDS_MAX,
            )

        out_w, out_h = output_size

        card_w = 360.0
        # Same aspect ratio as the fullscreen frame itself (not the photo's
        # own natural aspect ratio) -- with object-fit:cover, changing the
        # BOX's aspect ratio mid-shrink/grow changes which slice of the
        # photo is visible, so the image read as swapping to a different
        # crop/zoom partway through. Keeping the box's aspect ratio
        # constant throughout means the same crop is shown at every size,
        # just scaled.
        card_h = card_w * (float(out_h) / float(out_w))
        full_box = (0.0, 0.0, float(out_w), float(out_h))
        if marker_px is None:
            # The camera is centered exactly on the start marker for this
            # whole phase (see warm_js in the caller), so its on-screen
            # position is simply the viewport's own center -- no need to
            # reproject lon/lat to pixels.
            marker_px = (out_w / 2.0, out_h / 2.0)

        # Place the popup image floating directly above the marker, instead
        # of shoving it into a random corner. Target the top of the
        # teardrop pin (which is 44px tall).
        leader_target_y = marker_px[1] - 44.0
        card_gap = 30.0
        card_left = marker_px[0] - card_w / 2.0
        card_top = leader_target_y - card_gap - card_h
        # Clamped to stay fully on screen -- the shrink path's marker_px is
        # always the viewport center so this never kicks in there, but the
        # at-arrival grow path's marker_px is the destination pin's REAL
        # position, which can sit close enough to an edge that the
        # marker-relative placement above would push the card partway off
        # frame. The leader line still points at marker_px itself
        # (unclamped) -- only the card's own box is kept in bounds.
        edge_margin = 20.0
        card_left = min(max(card_left, edge_margin), out_w - card_w - edge_margin)
        card_top = min(max(card_top, edge_margin), out_h - card_h - edge_margin)
        card_box = (card_left, card_top, card_w, card_h)
        anchor_x = card_box[0] + card_w / 2.0
        anchor_y = card_box[1] + card_h

        if grow:
            # Pop in AT the small card size with the leader line already
            # drawn (mirrors _play_stopby_photo_pause's own card-then-
            # fullscreen treatment) -- then grows to fullscreen below,
            # instead of opening fullscreen and shrinking down.
            await page.evaluate(
                """([url, left, top, w, h, x1, y1, x2, y2]) => new Promise((resolve) => {
                    const img = document.createElement('img');
                    img.id = 'leg-dest-preview';
                    img.src = url;
                    Object.assign(img.style, {
                        position: 'fixed', zIndex: '9998',
                        left: left + 'px', top: top + 'px', width: w + 'px', height: h + 'px',
                        objectFit: 'cover', opacity: '0', borderRadius: '15px',
                        boxShadow: '0 15px 35px rgba(0,0,0,0.4)',
                    });
                    document.body.appendChild(img);

                    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                    svg.id = 'leg-dest-leader';
                    Object.assign(svg.style, {
                        position: 'fixed', inset: '0', width: '100vw', height: '100vh',
                        zIndex: '9997', pointerEvents: 'none',
                    });
                    const line = document.createElementNS(svg.namespaceURI, 'line');
                    line.id = 'leg-dest-leader-line';
                    line.setAttribute('x1', x1); line.setAttribute('y1', y1);
                    line.setAttribute('x2', x2); line.setAttribute('y2', y2);
                    line.setAttribute('stroke', 'white');
                    line.setAttribute('stroke-width', '3');
                    line.setAttribute('opacity', '0');
                    svg.appendChild(line);
                    document.body.appendChild(svg);

                    if (img.decode) { img.decode().then(resolve).catch(resolve); }
                    else { img.onload = resolve; img.onerror = resolve; }
                    setTimeout(resolve, 2000);
                })""",
                [
                    img_url, card_box[0], card_box[1], card_box[2], card_box[3],
                    anchor_x, anchor_y, marker_px[0], leader_target_y,
                ],
            )
            await _wait_for_paint(page)

            fade_in_frames = max(1, int(fade_in_s * fps))
            for i in range(fade_in_frames):
                alpha = (i + 1) / fade_in_frames
                await page.evaluate(
                    """(alpha) => {
                        const img = document.getElementById('leg-dest-preview');
                        if (img) img.style.opacity = alpha;
                        const line = document.getElementById('leg-dest-leader-line');
                        if (line) line.setAttribute('opacity', alpha);
                    }""",
                    alpha,
                )
                await _write_frame(await page.screenshot(**_FRAME_SHOT))

            hold_small_png = await page.screenshot(**_FRAME_SHOT)
            if pip_end:
                # image_display "pip": the photo stays a small card - it never
                # grows. It holds (at least a beat, longer if the walker is
                # waiting for the voice) and the clip ends on it.
                for _ in range(max(1, int(max(0.5, small_hold_s) * fps))):
                    await _write_frame(hold_small_png)
                return True
            for _ in range(int(small_hold_s * fps) if quick else max(1, int(small_hold_s * fps))):
                await _write_frame(hold_small_png)

            grow_frames = max(1, int(grow_s * fps))
            for i in range(grow_frames):
                t = _ease_in_out_cubic((i + 1) / grow_frames)
                left = card_box[0] + (full_box[0] - card_box[0]) * t
                top = card_box[1] + (full_box[1] - card_box[1]) * t
                w = card_box[2] + (full_box[2] - card_box[2]) * t
                h = card_box[3] + (full_box[3] - card_box[3]) * t
                radius = 15.0 * (1.0 - t)
                # Leader line fades out over the first ~2/3 of the grow so
                # it's gone well before the card fills the frame (a line
                # still pointing at a full-bleed image reads as a stray
                # mark, not a callout).
                line_alpha = max(0.0, 1.0 - t * 1.5)
                await page.evaluate(
                    """([left, top, w, h, radius, alpha]) => {
                        const img = document.getElementById('leg-dest-preview');
                        if (img) {
                            img.style.left = left + 'px';
                            img.style.top = top + 'px';
                            img.style.width = w + 'px';
                            img.style.height = h + 'px';
                            img.style.borderRadius = radius + 'px';
                        }
                        const line = document.getElementById('leg-dest-leader-line');
                        if (line) line.setAttribute('opacity', alpha);
                    }""",
                    [left, top, w, h, radius, line_alpha],
                )
                await _write_frame(await page.screenshot(**_FRAME_SHOT))

            full_hold_png = await page.screenshot(**_FRAME_SHOT)
            for _ in range(max(1, int(freeze_sec * fps))):
                await _write_frame(full_hold_png)

            if cut_after:
                # No fade-out, no cleanup evaluate -- the fullscreen photo
                # is meant to be the LAST frame this clip ever writes; the
                # caller ends the clip right after this returns instead of
                # continuing on to an outro.
                return True

            fade_frames = max(1, int(0.4 * fps))
            for i in range(fade_frames):
                alpha = 1.0 - ((i + 1) / fade_frames)
                await page.evaluate(
                    """(alpha) => {
                        const img = document.getElementById('leg-dest-preview');
                        if (img) img.style.opacity = alpha;
                    }""",
                    alpha,
                )
                await _write_frame(await page.screenshot(**_FRAME_SHOT))

            await page.evaluate(
                """() => {
                    const img = document.getElementById('leg-dest-preview');
                    if (img) img.remove();
                    const svg = document.getElementById('leg-dest-leader');
                    if (svg) svg.remove();
                }"""
            )
            return True

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
            [img_url, out_w, out_h],
        )
        await _wait_for_paint(page)

        hold_full_png = await page.screenshot(**_FRAME_SHOT)
        for _ in range(max(1, int(0.4 * fps))):
            await _write_frame(hold_full_png)

        # Leader line: a thin callout from the card's near (bottom-left)
        # corner down to the start marker, with a small dot at the marker
        # end -- an SVG overlay rather than a deck.gl layer since it needs
        # to track the CARD's own screen-space animation, not a map
        # coordinate. Added once here, then just updated in place through
        # the shrink/freeze/fade phases below.
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
                svg.appendChild(line);
                document.body.appendChild(svg);
            }""",
            [marker_px[0], leader_target_y],
        )

        shrink_frames = max(1, int(0.7 * fps))
        for i in range(shrink_frames):
            t = _ease_in_out_cubic((i + 1) / shrink_frames)
            left = full_box[0] + (card_box[0] - full_box[0]) * t
            top = full_box[1] + (card_box[1] - full_box[1]) * t
            w = full_box[2] + (card_box[2] - full_box[2]) * t
            h = full_box[3] + (card_box[3] - full_box[3]) * t
            radius = 15.0 * t
            leader_x1 = left + w / 2.0
            leader_y1 = top + h
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
            png_bytes = await page.screenshot(**_FRAME_SHOT)
            await _write_frame(png_bytes)

        # The line only draws in once the card has settled at its final
        # small size -- growing it DURING the shrink (card corner still
        # moving fast) read as a flickery diagonal streak, not a deliberate
        # callout.
        leader_grow_frames = max(1, int(0.3 * fps))
        anchor_x = card_box[0] + card_w / 2.0
        anchor_y = card_box[1] + card_h
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
                    anchor_y + (leader_target_y - anchor_y) * t,
                    t,
                ],
            )
            png_bytes = await page.screenshot(**_FRAME_SHOT)
            await _write_frame(png_bytes)

        freeze_png = await page.screenshot(**_FRAME_SHOT)
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
            png_bytes = await page.screenshot(**_FRAME_SHOT)
            await _write_frame(png_bytes)

        await page.evaluate(
            """() => {
                const img = document.getElementById('leg-dest-preview');
                if (img) img.remove();
                const svg = document.getElementById('leg-dest-leader');
                if (svg) svg.remove();
            }"""
        )
        return True

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
                    """([css, bannerIcon, timeLabel, cardIcon, chainPlaces, useImgCard, compassSvg]) => {
                        const style = document.createElement('style');
                        style.textContent = css;
                        document.head.appendChild(style);
                        const topRight = document.createElement('div');
                        topRight.id = 'hud-top-right';
                        document.body.appendChild(topRight);
                        const banner = document.createElement('div');
                        banner.id = 'hud-banner';
                        banner.innerHTML = `<span class="icon">${bannerIcon}</span> <span id="hud-banner-text"></span>`;
                        topRight.appendChild(banner);
                        if (compassSvg) {
                            topRight.insertAdjacentHTML('beforeend', compassSvg);
                            const lbl = document.createElement('div');
                            lbl.id = 'hud-compass-label';
                            topRight.appendChild(lbl);
                        }
                        const card = document.createElement('div');
                        card.id = 'hud-card';
                        card.innerHTML = `
                            <div class="metric"><div class="label"><span class="icon">${cardIcon}</span> ${timeLabel}</div><div class="value" id="hud-time">--</div></div>
                            <div class="divider"></div>
                            <div class="metric"><div class="label">距離</div><div class="value" id="hud-dist">--</div></div>
                        `;
                        document.body.appendChild(card);
                        if (useImgCard) {
                            card.classList.add('hidden');
                            const img = document.createElement('img');
                            img.id = 'hud-card-img';
                            document.body.appendChild(img);
                        }
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
                    [_hud_css(theme), mode_hud["banner_icon"], mode_hud["time_label"], mode_hud["icon"], route_chain,
                     hud_card_png is not None,
                     _COMPASS_SVG.format(size=int(tuning.RESIDENTIAL_COMPASS_SIZE_PX))
                     if tuning.RESIDENTIAL_SHOW_COMPASS else ""],
                )

                hud_card_cache: Dict[Tuple[int, int], str] = {}
                hud_card_shown: List[Optional[str]] = [None]

                async def _set_hud_card(rem_m: float, rem_min: int) -> None:
                    """Swaps in the summary-card image for these numbers (rendered
                    once per distinct value) and waits for it to decode."""
                    if hud_card_png is None:
                        return
                    key = (int(round(rem_m)), int(rem_min))
                    src = hud_card_cache.get(key)
                    if src is None:
                        png = hud_card_png(key[0] / 1000.0, key[1] * 60.0)
                        src = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
                        hud_card_cache[key] = src
                    if hud_card_shown[0] == src:
                        return
                    hud_card_shown[0] = src
                    await page.evaluate(
                        """async (src) => {
                            const img = document.getElementById('hud-card-img');
                            if (!img) return;
                            img.src = src;
                            try { await img.decode(); } catch (e) {}
                        }""",
                        src,
                    )

                all_trail_points = df_raw[["lon", "lat"]].values.tolist()
                headings = _walk_headings(
                    smooth_df["lon"].tolist(), smooth_df["lat"].tolist(),
                    float(tuning.RESIDENTIAL_COMPASS_HEADING_WINDOW_M),
                )

                def _needle_js(index: int) -> str:
                    deg = headings[min(index, len(headings) - 1)] if headings else 0.0
                    return (
                        "const nd = document.getElementById('hud-compass-needle');"
                        f" if (nd) nd.setAttribute('transform', 'rotate({deg:.1f} 50 50)');"
                        " const nl = document.getElementById('hud-compass-label');"
                        f" if (nl) nl.textContent = {json.dumps(_heading_label(deg))};"
                    )

                await page.evaluate(f"() => {{ {_needle_js(0)} }}")

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
                    rem_min0 = _remaining_minutes(rem_m0, rem_km0, travel_speed_kmh)
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
                    warm_png = await page.screenshot(**_FRAME_SHOT)
                    # The brief establishing hold only when the leg opens on
                    # the map. A leg that opens on its departure photo goes
                    # straight to that fullscreen photo: the hold showed as a
                    # blink of bare map between the previous clip (the
                    # attraction photo) and the photo shrinking into place.
                    # The voice delay below is counted from the frames
                    # actually written, so it stays in sync either way.
                    # The leg opens on its DEPARTURE photo (fullscreen, shrinking
                    # onto the start pin); the destination photo only when the
                    # departure has none.
                    if not dest_popup_image and not start_popup_image:
                        for _ in range(max(1, int(0.3 * fps))):
                            await _write_frame(warm_png)

                    if start_popup_image:
                        await _play_leg_photo_card(
                            start_popup_image, start_popup_freeze_seconds, "start"
                        )
                    elif dest_popup_image:
                        await _play_leg_photo_card(
                            dest_popup_image, dest_popup_freeze_seconds, "dest_opening"
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
                            // Pins/dots redrawn above the route line, and name
                            // pills above THOSE -- otherwise whichever line/dot
                            // layer happens to be re-appended after them each
                            // frame would paint straight over them.
                            const labelLayers = currentLayers.filter(l => l.id.includes('label'));
                            const pinLayers = currentLayers.filter(l => !l.id.includes('label') && (l.id.includes('pin') || l.id.includes('dots')));
                            const staticLayers = currentLayers.filter(l => !['walker-trail', 'walker-dot', 'walker-halo'].includes(l.id) && !l.id.includes('label') && !l.id.includes('pin') && !l.id.includes('dots'));
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
                                layers: [...staticLayers, newHalo, newDot, ...pinLayers, ...labelLayers]
                            }});
                            document.getElementById('hud-banner-text').textContent = {json.dumps(banner_text0)};
                            document.getElementById('hud-time').textContent = {json.dumps(f"{rem_min0} 分")};
                            document.getElementById('hud-dist').textContent = {json.dumps(dist_text0)};
                            {_needle_js(0)}
                        }}
                        """
                        await page.evaluate(js)
                        await _set_hud_card(rem_m0, rem_min0)
                        await page.wait_for_timeout(50)
                        png_bytes = await page.screenshot(**_FRAME_SHOT)
                        await _write_frame(png_bytes)

                # Connected stop-by photo pauses (see render_residential_leg_
                # pydeck's `landmarks` docstring): a merged-in stop-by with
                # "connectToRoute" true AND its own photo gets a full
                # fullscreen-pause moment the instant the walker reaches it,
                # not just the plain static dot every other landmark gets.
                # Triggered on whichever walking-loop frame's own position
                # lands closest to that stop-by's coordinates.
                stopby_triggers: Dict[int, Dict] = {}
                _stopby_candidates = []
                for lm in (landmarks or []):
                    if not (lm.get("connect_to_route") and lm.get("popup_image")):
                        continue
                    lm_lat, lm_lon = lm.get("lat"), lm.get("lon")
                    if lm_lat is None or lm_lon is None:
                        continue
                    sq_dist = (smooth_df["lat"] - lm_lat) ** 2 + (smooth_df["lon"] - lm_lon) ** 2
                    _stopby_candidates.append((lm, sq_dist))
                # Assigned nearest-landmark-first, each claiming the closest
                # frame index not already taken -- two connected stop-bys
                # close enough together to share the same idxmin() used to
                # both just get `stopby_triggers[idx] = lm`, so the second
                # one's write silently clobbered the first: that waypoint's
                # photo pause never fired at all, only the other one's did
                # (at ITS OWN, different marker position) -- looking exactly
                # like "the popup shown isn't for this waypoint".
                for lm, sq_dist in sorted(_stopby_candidates, key=lambda pair: pair[1].min()):
                    for idx in sq_dist.to_numpy().argsort():
                        idx = int(idx)
                        if idx not in stopby_triggers:
                            stopby_triggers[idx] = lm
                            break

                # Unconnected landmarks with their own photo (the route only
                # passes NEAR these -- see `landmarks` docstring): a small
                # pip card pops in beside the marker as the walker nears it
                # and fades back out, via `_play_stopby_photo_pause`'s own
                # `pip_only` path -- brief, no fullscreen growth, no leg
                # cut, unlike a connected stop-by's arrival. Shares the same
                # nearest-index assignment as stopby_triggers above (and the
                # same taken-index set, so a landmark sitting right beside a
                # connected stop-by's own trigger point never clobbers it).
                pip_triggers: Dict[int, Dict] = {}
                _pip_candidates = []
                for lm in (landmarks or []):
                    if lm.get("connect_to_route") or not lm.get("popup_image"):
                        continue
                    lm_lat, lm_lon = lm.get("lat"), lm.get("lon")
                    if lm_lat is None or lm_lon is None:
                        continue
                    sq_dist = (smooth_df["lat"] - lm_lat) ** 2 + (smooth_df["lon"] - lm_lon) ** 2
                    _pip_candidates.append((lm, sq_dist))
                _taken_indices = set(stopby_triggers.keys())
                for lm, sq_dist in sorted(_pip_candidates, key=lambda pair: pair[1].min()):
                    for idx in sq_dist.to_numpy().argsort():
                        idx = int(idx)
                        if idx not in _taken_indices:
                            pip_triggers[idx] = lm
                            _taken_indices.add(idx)
                            break

                # Every trigger index on this leg, connected or not, in
                # order. A pip popup now keeps the walker moving through
                # real path frames while its card is up (see
                # `_play_stopby_photo_pause`'s pip_only branch) -- with two
                # trigger points close together (an unconnected landmark
                # sitting right before a connected stop-by, say), that walk-
                # through could otherwise land PAST the next trigger's own
                # index before the outer loop ever checks it, silently
                # skipping that stop-by's pause/cut entirely. Passed to the
                # pip call below as a hard ceiling so it never advances past
                # whatever comes next.
                all_trigger_indices = sorted(set(stopby_triggers.keys()) | set(pip_triggers.keys()))

                # remaining_km's own total (its value at frame 0, before any
                # distance has been walked) -- the SMOOTH path's cumulative
                # length, which is not necessarily equal to total_leg_km (the
                # RAW polyline's length): linearly resampling lon/lat between
                # sparse raw points cuts corners on any sharp turn or loop,
                # shortening (or occasionally lengthening) the smooth path
                # relative to the raw one. On a leg with a tight loop (like a
                # small-island stop-by circuit) that gap can be large enough
                # that subtracting a SMOOTH remaining-distance from the RAW
                # total below would land on the wrong raw point entirely --
                # exactly where bisect crosses the loop's densely-packed raw
                # points, a small km error jumps `n_pts` by a visible chunk,
                # reading as the blue trail blinking ahead of (or behind) the
                # walker dot right at the loop.
                smooth_total_km = float(remaining_km.iloc[0]) if len(remaining_km) else 0.0

                frame_total = len(smooth_df)
                last_png_bytes = None
                crashed = False

                async def _draw_walker_frame(index: int):
                    """Draws/writes exactly one walking frame at `index` and
                    returns its PNG bytes, or None if ffmpeg crashed (sets
                    the enclosing `crashed` flag too). Pulled out of the
                    main loop below so a pip popup's own advance-while-
                    showing-the-card beat (see `_play_stopby_photo_pause`)
                    can call this too, instead of freezing the walker."""
                    nonlocal crashed
                    row = smooth_df.iloc[index]
                    rem_km = float(remaining_km.iloc[index])
                    # Trail must end exactly where the walker dot actually is
                    # -- picking raw points by ANIMATION-FRAME fraction (the
                    # old `index / total_frames` approach) assumes frames and
                    # raw route points advance in lockstep, which they don't
                    # (smooth_df is a separately time-based resampling), so
                    # the blue trail could visibly run ahead of or behind the
                    # dot. Selecting raw points by actual DISTANCE traveled
                    # so far, then appending the dot's own real position as
                    # the trail's final vertex, keeps the two in exact sync --
                    # but only once that traveled distance is expressed as a
                    # FRACTION of the smooth path's own total and rescaled
                    # onto the raw path's total (see smooth_total_km above),
                    # rather than mixed directly across the two different
                    # length scales.
                    traveled_frac = max(0.0, min(1.0, 1.0 - rem_km / smooth_total_km)) if smooth_total_km > 0 else 0.0
                    traveled_km = traveled_frac * (total_leg_km or 0.0)
                    n_pts = bisect.bisect_right(leg_dist_km, traveled_km) if leg_dist_km else 0
                    active_trail = all_trail_points[:n_pts] + [[row["lon"], row["lat"]]]
                    trail_geojson = json.dumps(
                        _route_linestring_feature(active_trail, line_color=walker_color)
                    ) if len(active_trail) >= 2 else json.dumps({"type": "FeatureCollection", "features": []})
                    walker_json = json.dumps([{"lon": row["lon"], "lat": row["lat"]}])

                    rem_m = rem_km * 1000.0
                    rem_min = _remaining_minutes(rem_m, rem_km, travel_speed_kmh)
                    banner_text, dist_text = _hud_text(
                        dest_label, rem_m, rem_min, arrive_threshold_m, mode=mode_hud["mode"]
                    )
                    js = f"""
                    if (window.deckgl) {{
                        const currentLayers = window.deckgl.props.layers || [];
                        const afterRemoval = currentLayers.filter(l => !['walker-trail', 'walker-dot', 'walker-halo'].includes(l.id));
                        // Pins/dots redrawn above the route line, and name
                        // pills above THOSE -- otherwise whichever line/dot
                        // layer happens to be re-appended after them each
                        // frame would paint straight over them.
                        const labelLayers = afterRemoval.filter(l => l.id.includes('label'));
                        const pinLayers = afterRemoval.filter(l => !l.id.includes('label') && (l.id.includes('pin') || l.id.includes('dots')));
                        const staticLayers = afterRemoval.filter(l => !l.id.includes('label') && !l.id.includes('pin') && !l.id.includes('dots'));
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
                        // Camera is locked for the whole leg (see the intro's
                        // zoom-in above) -- no viewState here, so deck.gl just
                        // keeps whatever view the intro left it at instead of
                        // re-centering on the walker every frame.
                        window.deckgl.setProps({{
                            layers: [...staticLayers, newTrail, newHalo, newDot, ...pinLayers, ...labelLayers]
                        }});
                        document.getElementById('hud-banner-text').textContent = {json.dumps(banner_text)};
                        document.getElementById('hud-time').textContent = {json.dumps(f"{rem_min} 分")};
                        document.getElementById('hud-dist').textContent = {json.dumps(dist_text)};
                        {_needle_js(index)}
                    }}
                    """
                    await page.evaluate(js)
                    await _set_hud_card(rem_m, rem_min)
                    await _wait_for_paint(page)
                    png_bytes = await page.screenshot(**_FRAME_SHOT)
                    try:
                        await _write_frame(png_bytes)
                    except Exception as e:
                        logger.error(f"[ERROR] FFmpeg crashed: {e}")
                        crashed = True
                        return None
                    return png_bytes

                # The opening is over: the walker starts moving on the next
                # frame. Line the narration up with that moment (see
                # start_cue_seconds) and record the delay beside the clip.
                lead_in = frame_state["count"] / fps
                cue = float(start_cue_seconds) if start_cue_seconds is not None else 0.0
                if lead_in < cue and frame_state["last"] is not None:
                    for _ in range(int(round((cue - lead_in) * fps))):
                        await _write_frame(frame_state["last"])
                write_audio_offset(output_path, max(0.0, lead_in - cue))
                logger.info(
                    "Leg opening %.2fs, {start} cue %s -> narration delayed %.2fs.",
                    lead_in, f"{cue:.2f}s" if start_cue_seconds is not None else "none",
                    max(0.0, lead_in - cue),
                )

                index = 0
                while index < frame_total and not crashed:
                    png_bytes = await _draw_walker_frame(index)
                    if png_bytes is None:
                        break
                    last_png_bytes = png_bytes
                    # Throttled (every 5 frames, not every single one) so
                    # the CLI's live status line actually moves DURING a
                    # leg's render instead of sitting frozen on whatever
                    # static "rendering leg N" text route2vdo.py's own
                    # per-leg tracker call left it on for the whole
                    # multi-minute walk.
                    if index % 5 == 0 or index == frame_total - 1:
                        pct = int(100 * (index + 1) / frame_total) if frame_total else 100
                        tracker.show(f"{dest_label}: walking frame {index + 1}/{frame_total} ({pct}%)")
                    row = smooth_df.iloc[index]

                    stopby_lm = stopby_triggers.get(index)
                    if stopby_lm is not None:
                        # Arrived early: the walker stands here, with the small
                        # photo card up, until this piece's narration is done;
                        # then the card grows to fullscreen.
                        # (the small photo card is up while it waits)
                        wait_s = float(stopby_lm.get("wait_seconds") or 0.0)
                        cuts_before = frame_state["cuts"]
                        await _play_stopby_photo_pause(
                            page, _write_frame, _cut_to_new_clip, fps, html_dir, port,
                            stopby_lm, locked_lon, locked_lat, locked_zoom, output_size, index,
                            pitch=follow_pitch,
                            small_hold_seconds=wait_s if wait_s > 0 else None,
                        )

                        # Dynamic hop to the NEXT segment's framing for the new clip!
                        # (the piece's opening - photo beat and hop - is measured
                        # below, once the hop is done, as this piece's voice delay)
                        future_indices = [k for k in stopby_triggers.keys() if k > index]
                        if future_indices:
                            next_index = min(future_indices)
                            next_lm = stopby_triggers[next_index]
                            n_lat, n_lon = next_lm.get("lat"), next_lm.get("lon")
                        else:
                            n_lat, n_lon = dest_lat, dest_lon
                            
                        if n_lat is not None and n_lon is not None:
                            sq_dist_curr = (df_raw["lat"] - row["lat"]) ** 2 + (df_raw["lon"] - row["lon"]) ** 2
                            curr_df_idx = int(sq_dist_curr.idxmin())
                            sq_dist_next = (df_raw["lat"] - n_lat) ** 2 + (df_raw["lon"] - n_lon) ** 2
                            next_df_idx = int(sq_dist_next.idxmin())
                            
                            next_fit_df = df_raw.iloc[curr_df_idx : next_df_idx + 2]
                            if not next_fit_df.empty:
                                new_lon, new_lat, new_zoom = _fit_view_for_path(
                                    next_fit_df["lon"].tolist(), next_fit_df["lat"].tolist(), output_size,
                                    padding_frac=0.15, pitch=follow_pitch,
                                    bottom_margin_px=_leg_bottom_margin_px(bottom_reserve_px),
                                    top_margin_px=_LEG_TOP_MARGIN_PX,
                                )
                                # Lock max zoom to prevent zooming in too much on short segments
                                new_zoom = min(new_zoom, 17.5)
                                
                                hop_frames = max(1, int(1.5 * fps))
                                for i in range(hop_frames):
                                    t = _ease_in_out_cubic((i + 1) / hop_frames)
                                    pan_lon = locked_lon + (new_lon - locked_lon) * t
                                    pan_lat = locked_lat + (new_lat - locked_lat) * t
                                    dip = math.sin(t * math.pi) * 1.5
                                    base_zoom = locked_zoom + (new_zoom - locked_zoom) * t
                                    pan_zoom = base_zoom - dip
                                    
                                    js_hop = f"""
                                    if (window.deckgl) {{
                                        window.deckgl.setProps({{
                                            viewState: {{
                                                longitude: {pan_lon}, latitude: {pan_lat},
                                                zoom: {pan_zoom}, pitch: {follow_pitch}, bearing: 0.0,
                                                transitionDuration: 0
                                            }}
                                        }});
                                    }}"""
                                    await page.evaluate(js_hop)
                                    await _wait_for_paint(page)
                                    png_bytes = await page.screenshot(**_FRAME_SHOT)
                                    await _write_frame(png_bytes)
                                
                                locked_lon, locked_lat, locked_zoom = new_lon, new_lat, new_zoom

                        if frame_state["cuts"] > cuts_before:
                            piece_lead = (frame_state["count"] - frame_state["clip_start"]) / fps
                            write_audio_offset(proc_ref["real_path"], piece_lead)
                            logger.info("Piece opening %.2fs -> its narration delayed %.2fs.", piece_lead, piece_lead)

                    pip_lm = pip_triggers.get(index)
                    if pip_lm is not None:
                        # Unconnected landmark: no camera hop, no leg cut --
                        # the walker keeps moving under the pip card itself
                        # (see `_play_stopby_photo_pause`'s pip_only branch),
                        # so it hands back whichever frame index it actually
                        # got to instead of the one it started on. Capped at
                        # the NEXT trigger's own index (see
                        # `all_trigger_indices`) so a nearby stop-by right
                        # after this pip never gets walked straight past.
                        next_trigger = next(
                            (k for k in all_trigger_indices if k > index), frame_total
                        )
                        index = await _play_stopby_photo_pause(
                            page, _write_frame, _cut_to_new_clip, fps, html_dir, port,
                            pip_lm, locked_lon, locked_lat, locked_zoom, output_size, index,
                            pitch=follow_pitch, pip_only=True,
                            advance_frame=_draw_walker_frame, frame_index=index + 1, frame_total=next_trigger,
                        )
                        continue

                    index += 1

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
                    # The HUD card's own remaining-distance/time reads "0 m
                    # / 0 分" the instant the walker arrives (see
                    # _remaining_minutes) -- correct while still walking,
                    # but meaningless as a held arrival frame. Swapped here
                    # for the LEG'S OWN total distance/time instead, so the
                    # freeze below reads as "here's the walk you just did"
                    # rather than a nonsense zero.
                    total_m = (total_leg_km or 0.0) * 1000.0
                    total_min = _remaining_minutes(total_m, total_leg_km or 0.0, travel_speed_kmh)
                    total_dist_text = f"{total_m:.0f} m" if total_m < 1000 else f"{total_m / 1000.0:.1f} km"
                    await page.evaluate(
                        """([distText, minText]) => {
                            if (window.deckgl) {
                                const staticLayers = (window.deckgl.props.layers || [])
                                    .filter(l => !['walker-halo', 'walker-dot'].includes(l.id));
                                window.deckgl.setProps({ layers: staticLayers });
                            }
                            const timeEl = document.getElementById('hud-time');
                            if (timeEl) timeEl.textContent = minText;
                            const distEl = document.getElementById('hud-dist');
                            if (distEl) distEl.textContent = distText;
                        }""",
                        [total_dist_text, f"{total_min} 分"],
                    )
                    await _set_hud_card(total_m, total_min)
                    await _wait_for_paint(page)
                    last_png_bytes = await page.screenshot(**_FRAME_SHOT)

                    # Brief hold on this plain arrived frame before the
                    # photo takes over -- without it, the clip cuts straight
                    # from "still walking" to "photo popping in" the instant
                    # the walker stops, with no beat to register arrival.
                    if dest_popup_image:
                        # The arrived map holds for the freeze, then the small
                        # photo card pops up and waits for the rest of the voice
                        # (small_hold_seconds below, shortened by the freeze so
                        # the clip's length doesn't change).
                        pre_popup_hold_frames = int(tuning.RESIDENTIAL_ARRIVAL_FREEZE_SECONDS * fps)
                        for _ in range(pre_popup_hold_frames):
                            await _write_frame(last_png_bytes)

                    # EVERY leg's own destination photo plays here, RIGHT as
                    # the walker arrives (before the plain hold below),
                    # anchoring its leader line to the destination pin's real
                    # on-screen position under the now-locked camera (unlike
                    # at the opening, where the topdown-to-locked transition
                    # is still animating) -- not just leg 0's. cut_after=True:
                    # no fade-out, no outro
                    # afterward -- the clip ends right on the fullscreen
                    # arrival photo, a hard cut instead of fading back to
                    # the map first. Skipped (falls back to a plain hold +
                    # the normal outro) only when this leg's destination has
                    # no popup photo at all.
                    cut_on_arrival = False
                    if dest_popup_image:
                        arrival_marker_px = _project_lonlat_to_px(
                            dest_lon, dest_lat, locked_lon, locked_lat, locked_zoom,
                            output_size, pitch=follow_pitch,
                        )
                        cut_on_arrival = await _play_leg_photo_card(
                            dest_popup_image, dest_popup_freeze_seconds,
                            "dest_arrival", marker_px=arrival_marker_px, grow=True,
                            cut_after=True, quick=True,
                            small_hold_seconds=(
                                None if arrival_wait_seconds is None
                                else max(0.0, arrival_wait_seconds - tuning.RESIDENTIAL_ARRIVAL_FREEZE_SECONDS)
                            ),
                            pip_end=False,  # image_display is ignored: arrivals always go fullscreen
                            hold_seconds=(
                                arrival_photo_hold_seconds
                                if arrival_photo_hold_seconds is not None
                                else tuning.RESIDENTIAL_ARRIVAL_POPUP_HOLD_SECONDS
                            ),
                        )
                    else:
                        hold_frames = max(0, int(
                            (arrival_wait_seconds if arrival_wait_seconds is not None
                             else arrival_hold_seconds) * fps
                        ))
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
                    # Skipped entirely when the arrival photo just cut the
                    # clip -- there's nothing left to ease back out FROM,
                    # the fullscreen photo was already the last frame.
                    outro_frames = 0 if cut_on_arrival else max(0, int(topdown_transition_seconds * fps))
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
                            png_bytes = await page.screenshot(**_FRAME_SHOT)
                            await _write_frame(png_bytes)

                        # Same tile warm-up problem as the intro's, mirrored:
                        # the outro just swept zoom all the way down to
                        # `topdown_zoom` in <2s, so give Mapbox a real beat
                        # to finish loading those low-zoom tiles before the
                        # clip ends on this frame (it's also what the NEXT
                        # leg's own intro warm-up starts from, visually).
                        await page.wait_for_timeout(400)
                        final_topdown_png = await page.screenshot(**_FRAME_SHOT)
                        for _ in range(max(1, int(0.3 * fps))):
                            await _write_frame(final_topdown_png)
            finally:
                await browser.close()
    finally:
        server.shutdown()
        server.server_close()

    await _finalize_clip()
    return produced_paths
