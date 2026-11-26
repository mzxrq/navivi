"""HTML/SVG for each themed card, sizes and coordinates as on the design artboards.

Every name goes through _t(): they are the user's own text. Theme files are ours and go in as they are.
"""

from __future__ import annotations

import math
import re
import string
from html import escape
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

from services import video_text
from services.hudtheme import model
from services.localization.japanese_words import phrases
from services.mapfetcher.graphicengine.cards import _fmt_distance
from services.vdoprocessing.pydeckrecorder.leg_hud import _COMPASS_POINTS, _MODE_ICON_SVG

# Shared by every card. Before the picture is taken (see render.py), `.fit` text is shrunk to its box and a
# `.wrap` name (strip) too long for one line takes two. A `.grow` card is as big as its text, which flows in
# `.flow`, clear of the pattern strip on the right.
CSS = """
.card { position: relative; overflow: hidden; white-space: nowrap; box-sizing: border-box;
        box-shadow: 0 5px 16px rgba(16,48,78,0.28); font-family: 'Zen Maru Gothic', 'LINE Seed JP', sans-serif; }
.card > svg { position: absolute; left: 0; top: 0; }
.card div { position: absolute; }
.card .fit { overflow: hidden; text-overflow: ellipsis; }
.card .wrap { overflow: hidden; white-space: nowrap; word-break: keep-all; text-wrap-style: balance; }
.card.grow { display: flex; flex-direction: column; justify-content: center; width: max-content; }
.card .flow { position: relative; }
.card .flow div { position: static; white-space: normal; word-break: keep-all; overflow-wrap: break-word;
                  text-wrap-style: balance; }
.card .num { display: flex; align-items: baseline; font-weight: 900; }
.card .u { font-size: 12px; margin: 0 1px 0 2px; }
.card .ring { display: inline-block; box-sizing: border-box; min-width: 16px; height: 16px; padding: 0 2px;
              border: 1.5px solid #fff; border-radius: 8px; font-size: 10px; line-height: 13px; color: #fff;
              text-align: center; vertical-align: 1px; margin-right: 4px; white-space: nowrap; }
"""

STRIP_X = (48.0, 398.0)  # the progress strip's line, between its S and E discs
STRIP_Y = 36.0


class Card(NamedTuple):
    html: str
    width: int  # at least this; a `.grow` card gets bigger with long text
    height: int


def _t(text) -> str:
    return escape(str(text or ""), quote=True)


def _units(text: str) -> str:
    """"3時間23分" with everything that is not a number set small."""
    parts = re.findall(r"[\d.,]+|[^\d.,]+", text)
    return "".join(
        _t(p) if p[0] in "0123456789.," else (f'<span class="u">{_t(p.strip())}</span>' if p.strip() else "")
        for p in parts)


def _box(left, top, width, height, style: str, body: str, fit: bool = False, extra: str = "") -> str:
    attrs = (' class="fit"' if fit else "") + extra
    return (f'<div{attrs} style="left:{left:g}px;top:{top:g}px;width:{width:g}px;'
            f'height:{height:g}px;line-height:{height:g}px;{style}">{body}</div>')


def _words(text) -> str:
    """Text that may break only between words."""
    return "<wbr>".join(_t(p) for p in phrases(str(text or "")))


def _name(left, top, width, height, style: str, text, two: Tuple[float, float, float]) -> str:
    """A name on one line in this box, or when too long on two. `two` is the two-line box: (top, height, font size)."""
    return _box(left, top, width, height, style, _words(text),
                extra=f' class="wrap" data-two="{" ".join(f"{v:g}" for v in two)}"')


def _card(width: int, height: int, style: str, body: str) -> Card:
    return Card(f'<div class="card" style="width:{width}px;height:{height}px;{style}">{body}</div>', width, height)


def _grow_card(theme: Dict, name: str, width: int, height: int, radius: int, strip: int, left: int, widest: int,
               margins: Tuple[int, int], badge: str, lines: str) -> Card:
    """A dark card with a gold frame that grows with its text: `badge` at the left, `lines` beside it (from
    `left`, at most `widest` px before they wrap) and a `strip` px band of pattern that text never enters."""
    top, bottom = margins
    art = (f'<svg data-wave="1" width="{strip}" height="100%" style="left:auto;right:0">'
           + _pattern(theme, name, False, [(0, strip)], "100%") + "</svg>"
           + f'<div style="left:4px;top:4px;right:4px;bottom:4px;border:1px solid {theme["gold"]};'
             f'border-radius:{radius - 3}px"></div>')
    return Card(
        f'<div class="card grow" style="min-width:{width}px;min-height:{height}px;border-radius:{radius}px;'
        f'background:{theme["panel"]};color:#fff">{art}{badge}<div class="flow" style="margin:{top}px '
        f'{strip + 14}px {bottom}px {left}px;max-width:{widest}px">{lines}</div></div>', width, height)


def _svg(width, height, body: str, extra: str = "") -> str:
    return f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" {extra}>{body}</svg>'


def _pattern(theme: Dict, name: str, pale: bool, rects: Sequence[Tuple[float, float]], height) -> str:
    """The theme's background pattern over the (left, right) stretches of a card."""
    ident = f"pat-{theme['id']}-{name}"
    defs = string.Template(theme["pattern"]).substitute(
        id=ident, scale=1.154 if pale else 1, color=theme["pattern_pale" if pale else "pattern_dark"])
    return f"<defs>{defs}</defs>" + "".join(
        f'<rect x="{a:g}" y="0" width="{b - a:g}" height="{height}" fill="url(#{ident})"/>' for a, b in rects)


# --- Vehicles --------------------------------------------------------------

def _boat(theme: Dict) -> str:
    ink = theme["line"]
    return (f'<path d="M0 12H46L39 22H8Z" fill="#fff" stroke="{ink}" stroke-width="1.5" stroke-linejoin="round"/>'
            f'<path d="M3 16H43" stroke="{theme["accent"]}" stroke-width="3"/>'
            f'<path d="M10 12V4H31L35 12Z" fill="#fff" stroke="{ink}" stroke-width="1.5" stroke-linejoin="round"/>'
            f'<path d="M15 8H18M22 8H25M29 8H30" stroke="{ink}" stroke-width="2.5"/>'
            f'<rect x="19" y="-3" width="6" height="7" fill="{theme["accent"]}"/>')


def _car(theme: Dict) -> str:
    ink = theme["line"]
    return (f'<path d="M2 18V12L8 10L13 2H31L38 10L45 12V18Z" fill="#fff" stroke="{ink}" stroke-width="1.5" '
            f'stroke-linejoin="round"/><path d="M15 5H21V10H12ZM24 5H30L35 10H24Z" fill="{ink}"/>'
            f'<path d="M3 14H44" stroke="{theme["accent"]}" stroke-width="2"/>'
            f'<g fill="{ink}" stroke="#fff" stroke-width="1.5"><circle cx="12" cy="18" r="4.5"/>'
            f'<circle cx="35" cy="18" r="4.5"/></g>')


def _plane(theme: Dict) -> str:
    return (f'<path d="M1 11L8 9L12 12H19L15 1H20L30 12H41Q46 13 46 15T41 18H12Q5 17 1 11ZM21 17L15 25H20L30 17Z" '
            f'fill="#fff" stroke="{theme["line"]}" stroke-width="1.5" stroke-linejoin="round"/>')


_VEHICLES = {"ferry": _boat, "driving": _car, "airplane": _plane}


def _walker(colour: str) -> str:
    return _MODE_ICON_SVG["walking"].replace('fill="#111"', f'fill="{colour}"')


def _medallion(theme: Dict, mode: str) -> str:
    """The round picture at the left of a mode card (circle of radius 27 at 34, 42)."""
    hill, water, sky = theme["hill"], theme["water"], theme["sky"]
    if mode == "walking":
        ground = f'<path d="M8.5 51Q22 38 36 48Q48 40 59.5 51A27 27 0 0 1 8.5 51Z" fill="{hill}"/>'
        walker = _walker(theme["walker"]).replace("<svg ", '<svg x="19" y="24" width="30" height="30" ', 1)
        return f'<circle cx="34" cy="42" r="27" fill="{sky}"/>{ground}{walker}'
    if mode == "ferry":
        return (f'<circle cx="34" cy="42" r="27" fill="{theme["sunset"]}"/>'
                f'<path d="M7.5 47Q14 42 21 47T34 47T47 47T60.5 47A27 27 0 0 1 7.5 47Z" fill="{water}"/>'
                f'<g transform="translate(13.5 28) scale(0.9)">{_boat(theme)}</g>')
    if mode == "driving":
        return (f'<circle cx="34" cy="42" r="27" fill="{sky}"/>'
                f'<path d="M8 50H60A27 27 0 0 1 8 50Z" fill="{theme["road"]}"/>'
                f'<path d="M14 58H22M30 58H38M46 58H54" stroke="#fff" stroke-width="2"/>'
                f'<g transform="translate(13.5 32) scale(0.88)">{_car(theme)}</g>')
    return (f'<circle cx="34" cy="42" r="27" fill="{sky}"/>'
            f'<g fill="#fff"><circle cx="22" cy="56" r="6"/><circle cx="31" cy="58" r="7"/>'
            f'<circle cx="49" cy="30" r="4"/><circle cx="43" cy="31" r="3"/></g>'
            f'<g transform="translate(13.5 31) scale(0.88) rotate(-10 23 13)">{_plane(theme)}</g>')


# --- Cards -----------------------------------------------------------------

def title_card(theme: Dict, title: str, loop: bool, start: str, end: str, labels: Dict) -> Card:
    words = labels["themed_hud"]
    stamp = words["loop" if loop else "one_way"]
    route = f'{words["base"]}　{start}' if loop else f"{start} → {end}"
    badge = (f'<div style="left:14px;top:50%;margin-top:-22px;width:42px;height:44px;border-radius:8px;'
             f'background:{theme["accent"]};border:2px solid #fff;box-sizing:border-box;transform:rotate(-5deg)">'
             + _box(2, 0, 34, 40, f"font-size:{13 if len(stamp) < 3 else 11}px;font-weight:900;color:#fff;"
                                  "text-align:center", _t(stamp), fit=True) + "</div>")
    lines = (f'<div style="font-size:21px;font-weight:900;line-height:28px">{_words(title)}</div>'
             f'<div style="margin-top:3px;font-size:11px;font-weight:700;line-height:16px;color:{theme["gold"]}">'
             f'{_words(route)}</div>')
    return _grow_card(theme, "title", 326, 68, 14, 63, 68, 370, (11, 10), badge, lines)


def totals_card(theme: Dict, distance_km: float, seconds: float, labels: Dict, remaining: bool = False,
                leg: bool = False) -> Card:
    """The whole route's distance and time, or (on a leg) what is left of them. `leg`: the leg video's top-right
    banner, this leg's own numbers, without the picture."""
    words, key, ink = labels["themed_hud"], "leg" if leg else "remaining" if remaining else "total", theme["line"]
    width = 276 if leg else 372
    dx = width - 372  # the banner is the same card with the picture's room taken off the left
    hours = seconds / 3600.0
    angle = 2 * math.pi * min(hours / 12.0, 0.9999)
    end = f"{16 + 12.5 * math.sin(angle):.2f} {16 - 12.5 * math.cos(angle):.2f}"
    if leg:
        art = _svg(width, 76, f'<rect width="{width}" height="76" fill="{theme["panel"]}"/>')
    else:
        art = _svg(372, 76, theme["scene"]
                   + f'<path d="M96 0Q110 9.5 96 19T96 38T96 57T96 76H372V0Z" fill="{theme["panel"]}"/>'
                   + f'<path d="M96 0Q110 9.5 96 19T96 38T96 57T96 76" fill="none" stroke="{theme["edge"]}" '
                     'stroke-width="3"/>')
    road = _svg(32, 32, f'<circle cx="16" cy="16" r="16" fill="#fff"/><path d="M9 22C17 25 11 14 17 15S19 19 23 10" '
                f'fill="none" stroke="{ink}" stroke-width="2" stroke-linecap="round" stroke-dasharray="2 3.5"/>'
                f'<circle cx="8" cy="22" r="3.5" fill="{theme["start"]}"/>'
                f'<circle cx="23.5" cy="9.5" r="3.5" fill="{theme["accent"]}"/>',
                f'style="left:{110 + dx}px;top:22px"')
    clock = _svg(32, 32, f'<circle cx="16" cy="16" r="16" fill="#fff"/>'
                 f'<path d="M16 16V3.5A12.5 12.5 0 {int(angle > math.pi)} 1 {end}Z" fill="{theme["clock"]}"/>'
                 f'<path d="M16 2V5M30 16H27M16 30V27M2 16H5" stroke="{ink}" stroke-width="1.6" stroke-linecap="round"/>'
                 f'<path d="M16 16V7M16 16L{end}" stroke="{ink}" stroke-width="1.8" stroke-linecap="round"/>',
                 f'style="left:{242 + dx}px;top:22px"')
    label = f"font-size:11px;font-weight:900;color:{theme['gold']}"

    def number(left, size, text):
        return (f'<div class="num fit" style="left:{left + dx}px;top:27px;width:80px;height:40px;line-height:40px;'
                f'font-size:{size}px">{_units(text)}</div>')

    body = (art + road
            + _box(148 + dx, 10, 82, 16, label, _t(words[f"{key}_distance"]), fit=True)
            + number(148, 30 if distance_km < 100 else 24, _fmt_distance(distance_km))
            + f'<div style="left:{232 + dx}px;top:16px;width:1px;height:44px;background:{theme["pattern_dark"]}"></div>'
            + clock
            + _box(280 + dx, 10, 86, 16, label, _t(words[f"{key}_time"]), fit=True)
            + number(280, 24, video_text.format_duration(labels, seconds)))
    corners = "16px" if leg else "41px 16px 16px 41px"
    return _card(width, 76, f"border:3px solid {theme['edge']};border-radius:{corners};color:#fff", body)


def mode_bar(theme: Dict, modes: Sequence[Tuple[str, float, float]], labels: Dict) -> Card:
    """Distance and time per travel mode as one slim card, two modes to a row: the recap frame needs its room for
    photo cards. `modes` is model.mode_cards(); the picture alone says which mode a group is. Icon, distance
    and time (on the mode's colour) stand close together so each reads as one group, each in a fixed column so
    the rows line up."""
    cell, row = 186, 32
    width, height = cell * min(2, len(modes)), row * ((len(modes) + 1) // 2) + 8
    body = (f'<div class="split" style="left:{cell}px;top:9px;width:1px;height:{height - 18}px;'
            f'background:{theme["pattern_pale"]}"></div>') if len(modes) > 1 else ""
    for i, (mode, distance_km, seconds) in enumerate(modes):
        mode = model.normalize_mode(mode)
        colour = theme["mode_colors"].get(mode, theme["primary"])
        x, y = cell * (i % 2), 4 + row * (i // 2)
        icon = (f'<svg data-part="icon" width="28" height="28" viewBox="5 13 58 58" style="left:{x + 7}px;'
                f'top:{y + 2}px;width:28px">{_medallion(theme, mode)}<circle cx="34" cy="42" r="27" fill="none" '
                f'stroke="{colour}" stroke-width="4"/></svg>')
        # Distances end where the pills start; "safe" keeps a too-long one overflowing rightwards, so it is shrunk.
        distance = (f'<div class="num fit" data-part="distance" style="left:{x + 39}px;top:{y}px;width:64px;'
                    f'height:{row}px;line-height:{row}px;font-size:17px;justify-content:safe flex-end">'
                    f'{_units(_fmt_distance(distance_km))}</div>')
        time = _box(x + 108, y + 5.5, 72, 21, f"border-radius:11px;background:{colour};color:#fff;font-size:12px;"
                    "font-weight:900;text-align:center", _t(video_text.format_duration(labels, seconds)), fit=True,
                    extra=' data-part="time"')
        body += icon + distance + time
    return _card(width, height, f"border-radius:20px;background:{theme['paper']};color:{theme['ink']}", body)


def _segment_art(theme: Dict, mode: str, left: float, right: float) -> str:
    colour, width, mid, y = theme["mode_colors"].get(mode, theme["primary"]), right - left, (left + right) / 2, STRIP_Y
    if mode == "walking":
        n = max(1, round(width / 28))
        step = width / n
        tail = "".join(f"T{left + step * i:.1f} {y:g}" for i in range(2, n + 1))
        return (f'<path d="M{left:.1f} {y:g}Q{left + step / 2:.1f} {y - 8:g} {left + step:.1f} {y:g}{tail}" '
                f'fill="none" stroke="{colour}" stroke-width="4" stroke-linecap="round"/>')
    arc = f"Q{mid:.1f} {2 if width > 90 else 10} " if mode != "driving" else "L"
    line = (f'<path d="M{left:.1f} {y:g}{arc}{right:.1f} {y:g}" fill="none" stroke="{colour}" stroke-width="3" '
            f'stroke-linecap="round" stroke-dasharray="3 7"/>')
    vehicle = _VEHICLES.get(mode)
    if vehicle is None or width < 44:
        return line
    top = 3 if mode != "driving" else 14
    return f'{line}<g transform="translate({mid - 19.5:.1f} {top}) scale(0.85)">{vehicle(theme)}</g>'


def _disc(theme: Dict, x: float, y: float, r: float, glyph: str, size: int) -> str:
    return (f'<circle cx="{x:g}" cy="{y:g}" r="{r:g}" fill="{model.pin_color(theme, glyph)}" stroke="#fff" '
            f'stroke-width="3"/><text x="{x:g}" y="{y + size * 0.36:.1f}" text-anchor="middle" font-size="{size}" '
            f'font-weight="900" fill="#fff">{_t(glyph)}</text>')


def strip_card(theme: Dict, segments: Sequence[model.Segment], start: str, end: str) -> Card:
    """The whole route as a schematic: S, each stretch drawn by its mode with its stops, E. The progress along
    it is drawn over this picture, frame by frame (see model.strip_x)."""
    spans = model.strip_spans(segments, *STRIP_X)
    water = [span for s, span in zip(segments, spans) if s.mode != "walking"] or [(151, 281)]
    art = (f'<rect width="447" height="76" fill="{theme["pale"]}"/>'
           + _pattern(theme, "strip", True, water, 50)  # stops above the names
           + "".join(_segment_art(theme, s.mode, *span) for s, span in zip(segments, spans)))
    chips, places = [], [(34.0, start)]
    for segment, (left, right) in zip(segments, spans):
        if not segment.glyphs:
            continue
        mid = (left + right) / 2
        wide = max(26, 16 + 8 * len(segment.glyphs))
        chips.append(f'<div style="left:{mid - wide / 2 - 2:.1f}px;top:23px;width:{wide}px;height:22px;'
                     f'line-height:22px;border:2px solid #fff;border-radius:13px;background:{theme["pins"]["stop"]};'
                     f'color:#fff;font-size:12px;font-weight:900;text-align:center">{_t(segment.glyphs)}</div>')
        places.append((mid, segment.place))
    places.append((412.0, end))
    art += _disc(theme, 34, STRIP_Y, 14, "S", 13) + _disc(theme, 412, STRIP_Y, 14, "E", 13)
    labels = []
    for i, (x, name) in enumerate(places):
        # Each name gets half the way to its neighbours, so two can never run into each other.
        room = [abs(x - places[j][0]) for j in (i - 1, i + 1) if 0 <= j < len(places)]
        wide = max(20.0, min([110.0, *(r - 4 for r in room), 2 * min(x, 447 - x)]))
        labels.append(_name(x - wide / 2, 54, wide, 16, "font-size:11px;font-weight:900;text-align:center",
                            name, two=(51, 24, 10)))
    return _card(447, 76, f"border-radius:22px;color:{theme['ink']}",
                 _svg(447, 76, art) + "".join(chips) + "".join(labels))


def next_card(theme: Dict, glyph: str, name: str, previous_glyph: str, previous: str, labels: Dict,
              off_route: bool = False) -> Card:
    """The place coming up, its circle coloured as its map pin. A stop-by not connected to the route is
    announced as an extra sight instead of the next stop."""
    words = labels["themed_hud"]
    disc = (f'<div style="left:16px;top:50%;margin-top:-28px;width:56px;height:56px;box-sizing:border-box;'
            f'border:3px solid #fff;border-radius:50%;background:{model.pin_color(theme, glyph)};color:#fff;'
            f'font-size:{28 if len(str(glyph)) < 3 else 22}px;font-weight:900;line-height:50px;'
            f'text-align:center">{_t(glyph)}</div>')
    ring = (f'<span class="ring" style="background:{model.pin_color(theme, previous_glyph)}">'
            f'{_t(previous_glyph)}</span>') if previous_glyph else ""
    before = f'{_t(words["previous"])}　{ring}{_words(previous)}' if previous else ""
    lines =(f'<div style="font-size:14px;font-weight:900;line-height:18px;color:{theme["gold"]}">'
             f'{_t(words["extra" if off_route else "next"])}</div>'
             f'<div style="margin-top:4px;font-size:28px;font-weight:900;line-height:36px">'
             f'{_words(name)}</div>'
             + (f'<div style="margin-top:4px;font-size:12px;font-weight:700;line-height:16px;color:{theme["soft"]}">'
                f'{before}</div>' if before else ""))
    return _grow_card(theme, "next", 366, 104, 16, 61, 86, 430, (14, 12), disc, lines)


def place_card(theme: Dict, glyph: str, name: str) -> Card:
    """An attraction clip's place name, top left: the next-stop card's little brother, the stop's number in its
    pin color."""
    disc = (f'<div style="left:14px;top:50%;margin-top:-22px;width:44px;height:44px;box-sizing:border-box;'
            f'border:3px solid #fff;border-radius:50%;background:{model.pin_color(theme, glyph)};color:#fff;'
            f'font-size:{22 if len(str(glyph)) < 3 else 17}px;font-weight:900;line-height:38px;text-align:center">'
            f'{_t(glyph)}</div>') if glyph else ""
    line = f'<div style="font-size:30px;font-weight:900;line-height:38px">{_words(name)}</div>'
    return _grow_card(theme, "place", 220, 64, 16, 44, 70 if glyph else 22, 520, (13, 13), disc, line)


def compass_card(theme: Dict, heading: float, labels: Dict) -> Card:
    """The leg video's compass, under the banner: the pointer turned to the heading, its name in the dial and
    with the degrees below. The ids are the ones the leg page updates frame by frame."""
    deg = round(heading) % 360
    points = labels.get("compass_points") or _COMPASS_POINTS
    name = points[int((deg + 22.5) // 45) % 8]
    # The pointer stays between 22 and 35 px from the centre: outside the letters, inside the dial.
    art = _svg(84, 114, f'<circle cx="42" cy="42" r="37" fill="{theme["panel"]}" stroke="{theme["edge"]}" stroke-width="3"/>'
               f'<circle cx="42" cy="42" r="31" fill="none" stroke="{theme["gold"]}"/>'
               f'<polygon id="hud-compass-pointer" points="42,7 49,20 35,20" fill="{theme["gold"]}" stroke="#fff" '
               f'stroke-width="1.5" stroke-linejoin="round" transform="rotate({deg} 42 42)"/>'
               f'<text id="hud-compass-letter" x="42" y="48" text-anchor="middle" font-size="17" font-weight="900" '
               f'fill="#fff">{_t(name)}</text>')
    label = (f'<div id="hud-compass-label" style="left:6px;top:90px;width:72px;height:20px;line-height:20px;'
             f'box-sizing:border-box;border-radius:10px;background:{theme["label"]};color:{theme["ink"]};font-size:11px;'
             f'font-weight:900;text-align:center">{_t(name)} {deg}°</div>')
    # No box shadow: the card's box is square, the compass is not.
    return _card(84, 114, "box-shadow:none;filter:drop-shadow(0 4px 8px rgba(16,48,78,0.28))", art + label)


def leg_rail_card(theme: Dict, from_glyph: str, to_glyph: str, share: float,
                  vias: Sequence[Tuple[float, str]] = (), mode: str = "walking") -> Card:
    """One leg: the stop left behind, the one ahead, the stop-bys between, and the traveller `share` of the way."""
    x0, x1, y = 50.0, 586.0, 41.0
    at = x0 + (x1 - x0) * min(1.0, max(0.0, share))
    colour = theme["mode_colors"].get(model.normalize_mode(mode), theme["primary"])
    art = (f'<rect width="636" height="82" fill="{theme["pale"]}"/>'
           + _pattern(theme, "leg", True, [(175, 400)], 82)
           + f'<path d="M{x0:g} {y:g}H{x1:g}" stroke="{colour}" stroke-width="5" stroke-linecap="round" '
             f'stroke-dasharray="1 11"/>'
           + f'<path d="M{x0:g} {y:g}H{at:.1f}" stroke="{colour}" stroke-width="7" stroke-linecap="round"/>'
           + _disc(theme, 30, y, 17, from_glyph, 16) + _disc(theme, 606, y, 17, to_glyph, 16)
           + "".join(_disc(theme, x0 + (x1 - x0) * s, y, 12, g, 11) for s, g in vias)
           + f'<circle cx="{at:.1f}" cy="{y:g}" r="20" fill="{theme["label"]}" stroke="{colour}" stroke-width="3"/>')
    icon = _MODE_ICON_SVG.get(model.normalize_mode(mode), _MODE_ICON_SVG["walking"]).replace("#111", theme["icon"])
    traveller = (f'<div style="left:{at - 12:.1f}px;top:29px;width:24px;height:24px;line-height:0">'
                 + icon.replace("<svg ", '<svg width="24" height="24" ', 1) + "</div>")
    return _card(636, 82, f"border-radius:26px;color:{theme['ink']}", _svg(636, 82, art) + traveller)
