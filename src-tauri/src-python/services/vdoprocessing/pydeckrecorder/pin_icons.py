"""Pin, landmark and place-name label icons for the pydeck route pages (overview pins, leg start/destination
pins, stop-by dots), as deck.gl layers or SVG data URLs."""

from __future__ import annotations

import math
import urllib.parse
from html import escape
from typing import Dict, List, Optional, Tuple

import pydeck as pdk

from services import tuning
from services.mapfetcher.graphicengine.pinimage import deck_icon


_CLOSED_DOT_URL = "data:image/svg+xml;charset=utf-8," + urllib.parse.quote(
    '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">'
    f'<circle cx="32" cy="32" r="28" fill="{"#%02x%02x%02x" % tuple(reversed(tuning.CLOSED_PIN_COLOR))}" '
    'stroke="#ffffff" stroke-width="5"/>'
    '<path d="M21 21 L43 43 M43 21 L21 43" stroke="#ffffff" stroke-width="7" stroke-linecap="round"/></svg>'
)


def _landmark_layers(
    landmarks: List[Dict], id_prefix: str = "stopby", white_dot: bool = False,
    avoid: Optional[List[Tuple[float, float]]] = None,
) -> List[pdk.Layer]:
    """landmarks: [{"lat", "lon", ("label")}, ...] -- small unnumbered brown
    dots with a plain label beside them, matching the reference video's
    landmark markers (e.g. a named junction/torii passed along the way):
    visually distinct from, and smaller than, the numbered orange pins
    real stops get. Used both for job_config.json stop-by waypoints
    (overview) and a leg's merged-in mid_markers (residential)."""
    if not landmarks:
        return []
    dots = [{"lon": lm["lon"], "lat": lm["lat"]} for lm in landmarks if not lm.get("inaccessible")]
    closed = [
        {"lon": lm["lon"], "lat": lm["lat"], "icon": {"url": _CLOSED_DOT_URL, "width": 64, "height": 64, "anchorY": 32}}
        for lm in landmarks if lm.get("inaccessible")
    ]
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
    if closed:  # a closed place (the editor's "Closed"): a red dot with a white ×
        layers.append(pdk.Layer(
            "IconLayer", id=f"{id_prefix}-closed", data=closed, get_icon="icon", get_position="[lon, lat]",
            get_size=22, size_units="'pixels'", pickable=False,
        ))
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
            avoid=avoid, clear_above=10, clear_side=12,
        )
    )
    return layers


# A teardrop map-pin (tip pointing straight down at its anchor point),
# colored to match the overview's own numbered waypoint pins (fill
# [230, 80, 20], white ring) rather than
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
            "icon": deck_icon(wp.get("pin_image")) or {
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
    # The user's own pin picture (same 384x512 canvas, so the layer code is unchanged).
    icon = deck_icon(pin.get("image")) if pin.get("image") else None
    if icon:
        return icon["url"]
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


def _fit_meters_per_px(path: List[Tuple[float, float]]) -> float:
    """Roughly the leg camera's scale: it frames the whole path, north-up, in 1920x1080."""
    lats, lons = [p[0] for p in path], [p[1] for p in path]
    k = math.cos(math.radians(sum(lats) / len(lats)))
    w_m, h_m = (max(lons) - min(lons)) * 111320 * k, (max(lats) - min(lats)) * 110540
    return max(w_m / 1920, h_m / 1080, 0.05) * 1.25


def label_offset(
    lat: float, lon: float, w: float, h: float, path: List[Tuple[float, float]], mpp: float,
    below: float, above: float, side: float,
) -> Tuple[float, float]:
    """Pixel offset (x right, y down) of a w x h pill's centre from its point: below, above, right or left
    of it, whichever covers the least of `path` [(lat, lon)] (ties keep that order)."""
    k = math.cos(math.radians(lat))
    pts = [((p_lon - lon) * 111320 * k / mpp, (lat - p_lat) * 110540 / mpp) for p_lat, p_lon in path]
    samples = []
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        n = max(1, int(math.hypot(bx - ax, by - ay) / 3))
        samples += [(ax + (bx - ax) * i / n, ay + (by - ay) * i / n) for i in range(n + 1)]
    boxes = [
        (-w / 2, below, w / 2, below + h), (-w / 2, -above - h, w / 2, -above),
        (side, -h / 2, side + w, h / 2), (-side - w, -h / 2, -side, h / 2),
    ]
    m = 4  # the line's own width
    hits = [sum(x0 - m <= x <= x1 + m and y0 - m <= y <= y1 + m for x, y in samples) for x0, y0, x1, y1 in boxes]
    x0, y0, x1, y1 = boxes[hits.index(min(hits))]
    return (x0 + x1) / 2, (y0 + y1) / 2


def _label_pill_layer(
    entries: List[Dict], layer_id: str, size_px: int = 34, pixel_offset_y: int = 0,
    avoid: Optional[List[Tuple[float, float]]] = None, clear_above: int = 0, clear_side: int = 0,
) -> List[pdk.Layer]:
    """One IconLayer of place-name pills. `entries`: [{"lat", "lon",
    "text"}, ...]. Without `avoid` each pill hangs just BELOW its own point
    rather than covering the pin standing above it. `pixel_offset_y`: the
    gap (pixels) between the point and the pill's top edge -- 0 is fine for a teardrop pin, whose own tip already sits
    exactly at the point, but a small round marker (e.g. a landmark dot,
    which is CENTERED on the point) needs a positive offset or the pill's
    top edge cuts straight through the dot instead of sitting below it.
    `avoid`: the route [(lat, lon)]; each pill then goes below, above
    (`clear_above` px over the point, past the pin) or beside it
    (`clear_side` px), wherever it hides the least of the route line."""
    mpp = _fit_meters_per_px(avoid) if avoid and len(avoid) > 1 else None
    data = []
    for e in entries:
        text = str(e.get("text") or "").strip()
        if not text:
            continue
        url, width = _label_pill_svg_url(text)
        w = width * size_px / _LABEL_H
        offset = (
            label_offset(e["lat"], e["lon"], w, size_px, avoid, mpp, pixel_offset_y, clear_above, clear_side)
            if mpp else (0, pixel_offset_y + size_px / 2)
        )
        data.append({
            "lon": e["lon"], "lat": e["lat"], "offset": [round(offset[0]), round(offset[1])],
            "icon": {"url": url, "width": width, "height": _LABEL_H},
        })
    if not data:
        return []
    return [
        pdk.Layer(
            "IconLayer", id=layer_id, data=data,
            get_icon="icon", get_position="[lon, lat]",
            get_size=size_px, size_units="'pixels'", size_scale=1, pickable=False,
            get_pixel_offset="offset",
        )
    ]
