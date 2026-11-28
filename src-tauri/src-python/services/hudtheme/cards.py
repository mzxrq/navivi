"""What each themed card shows, handed to its style file (styles.py; the built-in ones are in designs/).

Names are the user's own text: the templates escape them. Theme files are ours and go in as they are (Markup).
"""

from __future__ import annotations

import math
import string
from typing import Dict, NamedTuple, Sequence, Tuple

from markupsafe import Markup

from services import video_text
from services.hudtheme import model, styles
from services.mapfetcher.graphicengine.cards import _fmt_distance
from services.vdoprocessing.pydeckrecorder.leg_hud import _COMPASS_POINTS, _MODE_ICON_SVG


class Card(NamedTuple):
    html: str
    width: int  # at least this; a `.grow` card gets bigger with long text
    height: int


def _card(kind: str, style: str, theme: Dict, width: int, height: int, **data) -> Card:
    def pattern(name: str, pale: bool, rects: Sequence[Tuple[float, float]], tall) -> Markup:
        """The theme's background pattern over the (left, right) stretches of a card."""
        ident = f"pat-{theme['id']}-{name}"
        defs = string.Template(theme["pattern"]).substitute(
            id=ident, scale=1.154 if pale else 1, color=theme["pattern_pale" if pale else "pattern_dark"])
        return Markup(f"<defs>{defs}</defs>" + "".join(
            f'<rect x="{a:g}" y="0" width="{b - a:g}" height="{tall}" fill="url(#{ident})"/>' for a, b in rects))

    shared = {"theme": theme, "scene": Markup(theme["scene"]), "pattern": pattern,
              "pin": lambda glyph: model.pin_color(theme, glyph), "width": width, "height": height}
    return Card(styles.render(kind, style, {**shared, **data}), width, height)


def _walker(colour: str) -> Markup:
    icon = _MODE_ICON_SVG["walking"].replace('fill="#111"', f'fill="{colour}"')
    return Markup(icon.replace("<svg ", '<svg x="19" y="24" width="30" height="30" ', 1))


def _mode_color(theme: Dict, mode: str) -> str:
    return theme["mode_colors"].get(mode, theme["primary"])


def title_card(theme: Dict, title: str, loop: bool, start: str, end: str, labels: Dict,
               style: str = styles.DEFAULT) -> Card:
    words = labels["themed_hud"]
    return _card("title", style, theme, 260, 68, title=str(title or ""), loop=loop, start=str(start or ""),
                 end=str(end or ""), stamp=words["loop" if loop else "one_way"],
                 route=f'{words["base"]}　{start}' if loop else f"{start} → {end}")


def totals_card(theme: Dict, distance_km: float, seconds: float, labels: Dict, remaining: bool = False,
                leg: bool = False, style: str = styles.DEFAULT) -> Card:
    """The whole route's distance and time, or (on a leg) what is left of them. `leg`: the leg video's top-right
    banner, this leg's own numbers, without the picture."""
    words, key = labels["themed_hud"], "leg" if leg else "remaining" if remaining else "total"
    angle = 2 * math.pi * min(seconds / 3600.0 / 12.0, 0.9999)  # the clock face's wedge
    return _card("totals", style, theme, 276 if leg else 372, 76, leg=leg, distance_km=distance_km,
                 distance=_fmt_distance(distance_km), time=video_text.format_duration(labels, seconds),
                 distance_label=words[f"{key}_distance"], time_label=words[f"{key}_time"],
                 clock_large=int(angle > math.pi),
                 clock_end=f"{16 + 12.5 * math.sin(angle):.2f} {16 - 12.5 * math.cos(angle):.2f}")


def mode_bar(theme: Dict, modes: Sequence[Tuple[str, float, float]], labels: Dict,
             style: str = styles.DEFAULT) -> Card:
    """Distance and time per travel mode as one slim card, two modes to a row: the recap frame needs its room for
    photo cards. `modes` is model.mode_cards(); the picture alone says which mode a group is."""
    found = []
    for mode, distance_km, seconds in modes:
        mode = model.normalize_mode(mode)
        found.append({"mode": mode, "color": _mode_color(theme, mode), "walker": _walker(theme["walker"]),
                      "distance": _fmt_distance(distance_km),
                      "time": video_text.format_duration(labels, seconds)})
    width, height = 186 * min(2, len(modes)), 32 * ((len(modes) + 1) // 2) + 8
    return _card("modes", style, theme, width, height, modes=found)


def strip_card(theme: Dict, segments: Sequence[model.Segment], start: str, end: str,
               style: str = styles.DEFAULT) -> Card:
    """The whole route as a schematic. The progress along it is drawn over this picture, frame by frame (see
    model.strip_x). Each segment's `start` and `end` are its share (0..1) of the strip's line."""
    spans = model.strip_spans(segments, 0.0, 1.0)
    found = [{"mode": s.mode, "color": _mode_color(theme, s.mode), "glyphs": s.glyphs, "place": s.place,
              "start": left, "end": right} for s, (left, right) in zip(segments, spans)]
    return _card("strip", style, theme, 447, 76, segments=found, start=str(start or ""), end=str(end or ""))


def ferry_card(theme: Dict, style: str = styles.DEFAULT) -> Card:
    return _card("ferry", style, theme, 184, 100)


def next_card(theme: Dict, glyph: str, name: str, previous_glyph: str, previous: str, labels: Dict,
              off_route: bool = False, style: str = styles.DEFAULT) -> Card:
    """The place coming up, its circle coloured as its map pin. A stop-by not connected to the route is
    announced as an extra sight instead of the next stop. A stop-by's card does not name the place before."""
    words = labels["themed_hud"]
    if str(glyph)[:1] in ("+", "・"):
        previous_glyph = previous = ""
    return _card("next", style, theme, 366, 104, glyph=str(glyph), name=str(name or ""),
                 previous_glyph=str(previous_glyph or ""), previous=str(previous or ""),
                 heading=words["extra" if off_route else "next"], previous_label=words["previous"])


def place_card(theme: Dict, glyph: str, name: str, style: str = styles.DEFAULT) -> Card:
    """An attraction clip's place name, top left: the next-stop card's little brother, the stop's number in its
    pin color."""
    return _card("place", style, theme, 220, 64, glyph=str(glyph or ""), name=str(name or ""))


def compass_card(theme: Dict, heading: float, labels: Dict, style: str = styles.DEFAULT) -> Card:
    """The leg video's compass, under the banner."""
    degrees = round(heading) % 360
    points = labels.get("compass_points") or _COMPASS_POINTS
    return _card("compass", style, theme, 84, 114, degrees=degrees, name=points[int((degrees + 22.5) // 45) % 8])


def leg_rail_card(theme: Dict, from_glyph: str, to_glyph: str, share: float,
                  vias: Sequence[Tuple[float, str]] = (), mode: str = "walking",
                  style: str = styles.DEFAULT) -> Card:
    """One leg: the stop left behind, the one ahead, the stop-bys between, and the traveller `share` of the way."""
    mode = model.normalize_mode(mode)
    icon = _MODE_ICON_SVG.get(mode, _MODE_ICON_SVG["walking"]).replace("#111", theme["icon"])
    return _card("leg_rail", style, theme, 636, 82, from_glyph=str(from_glyph), to_glyph=str(to_glyph),
                 share=min(1.0, max(0.0, share)), vias=[(s, str(g)) for s, g in vias],
                 color=_mode_color(theme, mode),
                 icon=Markup(icon.replace("<svg ", '<svg width="24" height="24" ', 1)))
