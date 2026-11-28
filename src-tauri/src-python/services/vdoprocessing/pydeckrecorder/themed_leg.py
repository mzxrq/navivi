"""A walking leg's HUD in a themed design: next stop, leg banner, compass, progress rail and what is left.

The cards are drawn as pictures before the walk is recorded (in the sandboxed, script-free renderer, so a style
file never runs in the map page) and swapped into the page as <img> as the numbers change. The classic HUD is
only hidden, so the code that writes to it keeps working.
"""

from __future__ import annotations

import base64
import io
import re
from typing import Dict, List, NamedTuple, Optional, Sequence, Set, Tuple

from services import video_text
from services.hudtheme import cards, layout, model, render

CARDS = ("next", "leg_banner", "compass", "leg_rail", "remaining")
_RAIL_LAYERS = ("walked", "walker")  # pictures of their own, moved over the bar every frame
_RAIL_LINE = re.compile(r'data-rail="\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*"')  # "x0 x1 y", card px
_RAIL_STEPS = 300  # positions on a rail style without layers, each one a picture to draw
_REMAINING_STEPS = 100  # ...and of the figures left
_COMPASS_STEP_DEG = 5
_GAP_PX = 12  # artboard px kept between the rail and the remaining card
_MIN_RAIL_SCALE = 0.4
_PIN_ABOVE_PX, _NAME_BELOW_PX = 60.0, 40.0  # a map pin stands this far above its point, its name pill below
_MAX_BAND = 0.3  # of the frame height: the most the cards at one edge keep the route out of
# Artboard sizes the map's name pills keep clear of (the next-stop card grows with its name: allow for a long one).
_ROOM = {"next": (480, 104), "leg_banner": (276, 76), "compass": (84, 114), "leg_rail": (636, 82),
         "remaining": (372, 76)}
_HIDE_CLASSIC = ("#hud-banner, #hud-chain, #hud-stopcount, #hud-card, #hud-card-img, #hud-compass-wrap "
                 "{ display: none !important; }")

_SHOW_JS = """async (items) => {
    await Promise.all(items.map(async ([name, src, left, top, width, height, pad, cut]) => {
        const id = 'hud-t-' + name;  // "hud-": photo cards keep off it (stopby_pause.screen_props)
        let box = document.getElementById(id);
        if (!box) {
            box = document.createElement('div');
            box.id = id;
            box.appendChild(document.createElement('img'));
            document.body.appendChild(box);
        }
        // The traveller is moved by transform: left and top would land it on whole pixels, in visible steps.
        const moved = name === 'leg_rail_walker';
        Object.assign(box.style, { position: 'fixed', zIndex: 1000, left: moved ? '0px' : left + 'px',
                                   top: moved ? '0px' : top + 'px', width: width + 'px', height: height + 'px' });
        if (moved) Object.assign(box.style, { willChange: 'transform', transform: `translate(${left}px, ${top}px)` });
        if (cut !== undefined) box.style.clipPath = `inset(0px ${cut}px 0px 0px)`;
        const img = box.firstChild;
        Object.assign(img.style, { position: 'absolute', left: -pad + 'px', top: -pad + 'px',
                                   width: (width + 2 * pad) + 'px', height: (height + 2 * pad) + 'px' });
        if (img.getAttribute('src') !== src) {
            img.src = src;
            try { await img.decode(); } catch (e) {}
        }
    }));
}"""


def _step(share: float, steps: int) -> float:
    return round(min(1.0, max(0.0, share)) * steps) / steps


class Place(NamedTuple):
    """One entry of the leg's banner: a stop, or a stop-by passed on the way."""
    name: str
    glyph: str
    off_route: bool = False


class _Picture(NamedTuple):
    src: str
    width: float
    height: float


class ThemedLegHud:
    def __init__(
        self, hud: Dict, theme_id: str, mode: str, leg: Tuple[float, float], after: Tuple[float, float],
        stopby_glyphs: Sequence[str] = (),
    ):
        """`leg` and `after`: (km, seconds) of this leg and of every later one. `stopby_glyphs`: what the map pin
        of each of the banner's stop-bys shows ("+n"), in banner order."""
        self.theme = model.load_theme(theme_id, bool(hud.get("dark")), hud.get("scene"))
        self.entries = layout.merge(self.theme["layout"], hud.get("layout"))
        self.mode, self.leg, self.after, self.stopby_glyphs = mode, leg, after, list(stopby_glyphs)
        figures = ",".join(f"{km:.2f}/{round(seconds / 60)}" for km, seconds in (leg, after))
        self.fingerprint = f"{hud.get('fingerprint')}-{','.join(self.stopby_glyphs)}-{figures}"
        self.labels: Dict = {}
        self.places: List[Place] = []
        self.vias: List[Tuple[float, str]] = []
        self.unit = 1.0
        self.frame = (1920, 1080)
        self.compass = True
        self._pictures: Dict[str, _Picture] = {}  # by card html
        self._shown: Dict[str, Tuple] = {}
        self._rail: Optional[Tuple[float, ...]] = None  # a layered rail's line; None: drawn step by step
        self._layers: Dict[str, cards.Card] = {}

    # --- what each card says -------------------------------------------------

    def places_of(self, banner_items: Sequence[Tuple], dest: str, badges: Sequence, off_route: Set[str]) -> List[Place]:
        """The leg's banner items (text, badge, is stop-by) with the glyph each card shows. `badges`: the start's
        and the destination's."""
        found, glyphs = [], iter(self.stopby_glyphs)
        numbered = [i for i, item in enumerate(banner_items) if not item[2]]
        for i, (text, badge, is_stopby) in enumerate(banner_items):
            if is_stopby:
                found.append(Place(str(text), next(glyphs, "・"), str(text) in off_route))
                continue
            if not badge and numbered and i in (numbered[0], numbered[-1]):
                badge = badges[0] if i == numbered[0] else badges[1]
            found.append(Place(str(text), str(badge or "")))
        if not found:
            found = [Place(str(dest), str(badges[1] or ""))]
        return found

    def _next(self, window: Tuple[int, int]) -> cards.Card:
        first, last = (max(0, min(i, len(self.places) - 1)) for i in window)
        coming = self.places[last]
        before = self.places[first] if first != last else Place("", "")
        return cards.next_card(self.theme, coming.glyph, coming.name, before.glyph, before.name, self.labels,
                               off_route=coming.off_route, style=self.entries["next"].style)

    def _card(self, name: str, share: float, heading: float, window) -> Optional[cards.Card]:
        """The card `name` with `share` of the leg walked."""
        style = self.entries[name].style
        if not self.entries[name].show or (name == "compass" and not self.compass):
            return None
        if name == "next":
            return self._next(window)
        if name == "leg_banner":
            return cards.totals_card(self.theme, *self.leg, self.labels, leg=True, style=style)
        if name == "compass":
            degrees = round(heading / _COMPASS_STEP_DEG) * _COMPASS_STEP_DEG
            return cards.compass_card(self.theme, degrees, self.labels, style=style)
        if name == "leg_rail":
            return self._rail_card("bar", 0.0 if self._rail else _step(share, _RAIL_STEPS))
        left = 1.0 - _step(share, _REMAINING_STEPS)
        return cards.totals_card(self.theme, left * self.leg[0] + self.after[0],
                                 left * self.leg[1] + self.after[1], self.labels, remaining=True, style=style,
                                 most=(self.leg[0] + self.after[0], self.leg[1] + self.after[1]))

    def _rail_card(self, layer: str, share: float = 0.0) -> cards.Card:
        first = self.places[0].glyph if len(self.places) > 1 else ""
        return cards.leg_rail_card(self.theme, first or "S", self.places[-1].glyph or "E", share, self.vias,
                                   self.mode, style=self.entries["leg_rail"].style, layer=layer)

    # --- pictures and places -------------------------------------------------

    def margins(self, frame: Tuple[int, int], top: float, bottom: float) -> Tuple[float, float]:
        """`top` and `bottom`, the camera's usual clear bands (video px), grown so the route and its pins stay out
        from under the wide cards. The compass, narrow and at the side, does not count, nor does a card hud.json puts
        in the middle; one put far from its edge takes at most _MAX_BAND of the frame."""
        most = frame[1] * _MAX_BAND
        for name in CARDS:
            edge = self.entries[name].anchor.split("-")[0]
            for _, y0, _, y1 in self.room(frame, [name]) if name != "compass" else []:
                if edge == "top":
                    top = max(top, min(y1 + _PIN_ABOVE_PX, most))
                elif edge == "bottom":
                    bottom = max(bottom, min(frame[1] - y0 + _NAME_BELOW_PX, most))
        return top, bottom

    def room(self, frame: Tuple[int, int], names: Sequence[str] = CARDS) -> List[Tuple[float, float, float, float]]:
        """The boxes (video px) the map's name pills keep clear of."""
        unit = frame[1] / layout.LEG_HEIGHT
        out = []
        for name in names:
            entry = self.entries[name]
            if entry.show:
                size = tuple(v * unit * entry.scale for v in _ROOM[name])
                x, y = layout.place(entry, size, frame, unit)
                out.append((x, y, x + size[0], y + size[1]))
        return out

    def prepare(
        self, frame: Tuple[int, int], places: List[Place], vias: Sequence[Tuple[float, str]],
        shares: Sequence[float], headings: Sequence[float], windows: Sequence[Tuple[int, int]],
        compass: bool = True,
    ) -> None:
        """Draws every picture the walk can show, in one browser pass per size. Blocking: call it off the
        event loop."""
        self.labels = video_text.current_labels()
        self.frame, self.unit = frame, frame[1] / layout.LEG_HEIGHT
        self.places, self.vias, self.compass = places, list(vias), compass
        self._shown = {}
        self._rail, self._layers = None, {}
        if self.entries["leg_rail"].show:
            line = _RAIL_LINE.search(self._rail_card("bar").html)
            if line:
                self._rail = tuple(float(v) for v in line.groups())
                self._layers = {layer: self._rail_card(layer) for layer in _RAIL_LAYERS}
        wanted: Dict[str, Dict[str, cards.Card]] = {name: {} for name in CARDS}

        def add(name, *state) -> None:
            card = self._card(name, *state)
            if card is not None:
                wanted[name][card.html] = card

        usual = windows[0]
        for share in list(shares) + [0.0, 1.0]:
            add("leg_rail", share, 0.0, usual)
            add("remaining", share, 0.0, usual)
        for heading in headings or [0.0]:
            add("compass", 0.0, heading, usual)
        add("leg_banner", 0.0, 0.0, usual)
        for window in windows:
            add("next", 0.0, 0.0, window)
        for card in self._layers.values():
            wanted["leg_rail"][card.html] = card
        for name, found in wanted.items():
            scale = self.unit * self.entries[name].scale
            new = [card for html, card in found.items() if html not in self._pictures]
            for card, picture in zip(new, render.render_cards(new, scale)):
                buffer = io.BytesIO()
                picture.save(buffer, "PNG")
                pad = 2 * render.PAD * scale
                self._pictures[card.html] = _Picture(
                    "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"),
                    picture.width - pad, picture.height - pad)

    def items(self, share: float, heading: float, window: Tuple[int, int]) -> List[List]:
        """[name, src, left, top, width, height, pad] of every card whose picture or place changed; the rail's
        walked layer adds how much of its right side is cut off."""
        placed = {}
        for name in CARDS:
            card = self._card(name, share, heading, window)
            if card is None:
                continue
            picture, entry = self._pictures[card.html], self.entries[name]
            scale = self.unit * entry.scale
            width, height = picture.width, picture.height
            for beside in ("leg_banner", "remaining") if name == "leg_rail" else ():
                # The rail gives way to a figures card when they share the foot of a narrow frame.
                other = self.entries[beside]
                if not other.show:
                    continue
                ow, oh = (v * self.unit * other.scale for v in _ROOM[beside])
                ox, oy = layout.place(other, (ow, oh), self.frame, self.unit)
                x, y = layout.place(entry, (width, height), self.frame, self.unit)
                gap = _GAP_PX * self.unit
                if x < ox + ow and ox < x + width + gap and y < oy + oh and oy < y + height:
                    factor = max(_MIN_RAIL_SCALE, min(1.0, max(ox - gap - x, x + width - ox - ow - gap) / width))
                    width, height, scale = width * factor, height * factor, scale * factor
            x, y = layout.place(entry, (width, height), self.frame, self.unit)
            placed[name] = [name, picture.src, round(x, 1), round(y, 1), round(width, 1), round(height, 1),
                            round(render.PAD * scale, 1)]
            if name == "leg_rail" and self._rail:
                x0, x1, line_y = self._rail
                at = (x0 + (x1 - x0) * min(1.0, max(0.0, share))) * scale
                walked, walker = (self._pictures[self._layers[layer].html] for layer in _RAIL_LAYERS)
                shrunk = scale / (self.unit * entry.scale)
                own = (walker.width * shrunk, walker.height * shrunk)
                placed["leg_rail_walked"] = ["leg_rail_walked", walked.src, *placed[name][2:], round(width - at, 2)]
                placed["leg_rail_walker"] = [
                    "leg_rail_walker", walker.src, round(x + at - own[0] / 2, 2),
                    round(y + line_y * scale - own[1] / 2, 2), round(own[0], 1), round(own[1], 1),
                    placed[name][6]]
        changed = [item for name, item in placed.items() if self._shown.get(name) != tuple(item)]
        self._shown.update({item[0]: tuple(item) for item in changed})
        return changed

    def rail_top(self) -> Optional[float]:
        """Where the rail starts from the top, once shown: the elevation card sits above it."""
        shown = self._shown.get("leg_rail")
        return shown[3] if shown and self.entries["leg_rail"].anchor.startswith("bottom") else None

    async def start(self, page) -> None:
        """Hides the classic HUD."""
        await page.add_style_tag(content=_HIDE_CLASSIC)

    async def show(self, page, share: float, heading: float, window) -> None:
        items = self.items(share, heading, window)
        if items:
            await page.evaluate(_SHOW_JS, items)
