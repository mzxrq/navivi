"""The course overview's fixed furniture in a themed design: title, totals, travel modes, progress strip and the
app's stop-by banners, each where the project's layout puts it (services/hudtheme/layout.py)."""

from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

import numpy as np

from services import video_text
from services.hudtheme import cards, layout, model, render
from services.logger.logger import setup_logger
from services.mapfetcher.graphicengine.cards import _blend_card

logger = setup_logger(__name__)

_LINE = re.compile(r'data-line="\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*"')
_SLIDE_PX = 40  # artboard px the travel-mode bar drops in from
_BANNER_GAP_PX = 12  # artboard px kept between the banners and the strip
_MIN_STRIP_SCALE = 0.4  # of its own size, however little room the banners leave it
_NOTICE_FADE_SECONDS = 0.5
Box = Tuple[float, float, float, float]


class _Placed(NamedTuple):
    picture: np.ndarray  # BGRA, with render.PAD of margin around the card
    box: Box  # the card itself, in video px
    scale: float  # video px per card px

    def paste(self, frame: np.ndarray, alpha: float = 1.0, dy: float = 0.0) -> None:
        """Blends the picture onto `frame`, in place; whatever hangs off the frame is cut."""
        pad = render.PAD * self.scale
        x, y = int(round(self.box[0] - pad)), int(round(self.box[1] - pad + dy))
        ph, pw = self.picture.shape[:2]
        h, w = frame.shape[:2]
        left, top, right, bottom = max(0, -x), max(0, -y), min(pw, w - x), min(ph, h - y)
        if right > left and bottom > top:
            _blend_card(frame, self.picture[top:bottom, left:right], x + left, y + top, alpha)


def _overlaps(a: Box, b: Box, gap: float) -> bool:
    return a[0] < b[2] + gap and b[0] < a[2] + gap and a[1] < b[3] and b[1] < a[3]


def _render(wanted: Dict[str, Tuple[cards.Card, layout.Entry]], w: int, h: int, unit: float) -> Dict[str, _Placed]:
    """Each card's picture at its entry's size, placed on the frame. One browser pass per distinct size."""
    out: Dict[str, _Placed] = {}
    for size in sorted({entry.scale for _, entry in wanted.values()}):
        names = [name for name, (_, entry) in wanted.items() if entry.scale == size]
        k = unit * size
        for name, picture in zip(names, render.render_cards([wanted[n][0] for n in names], k)):
            card_size = (picture.width - 2 * render.PAD * k, picture.height - 2 * render.PAD * k)
            x, y = layout.place(wanted[name][1], card_size, (w, h), unit)
            out[name] = _Placed(np.array(picture)[:, :, [2, 1, 0, 3]], (x, y, x + card_size[0], y + card_size[1]), k)
    return out


class ThemedPanels:
    def __init__(
        self, graphics, hud: Dict, theme_id: str, w: int, h: int, summary: Optional[Dict],
        stops: Sequence[model.Stop], cum: Sequence[float], modes: Sequence[str], loop: bool,
        has_stopbys: bool, has_closed: bool,
    ):
        theme = model.load_theme(theme_id, bool(hud.get("dark")), hud.get("scene"))
        entries = layout.merge(theme["layout"], hud.get("layout"))
        unit = h / layout.OVERVIEW_HEIGHT
        labels = video_text.current_labels()
        self.graphics, self.theme, self.unit = graphics, theme, unit
        self.notice_colors = model.notice_colors(theme)

        # The banners first: the strip gives way to them.
        self.show_notices = entries["notices"].show and (has_stopbys or has_closed)
        self.closed_offset, self.notice_dx, self.notice_dy = 0, 0, 0
        banners: List[Box] = []
        if self.show_notices:
            with self.banners():
                if has_stopbys:
                    banners.append(graphics.stopby_notice_box(w, h))
                    self.closed_offset = banners[0][2] - banners[0][0] + int(24 * h / 1080)
                if has_closed:
                    banners.append(graphics.stopby_notice_box(w, h, "closed", self.closed_offset))
            group = (min(b[0] for b in banners), min(b[1] for b in banners),
                     max(b[2] for b in banners), max(b[3] for b in banners))
            x, y = layout.place(entries["notices"], (group[2] - group[0], group[3] - group[1]), (w, h), unit)
            self.notice_dx, self.notice_dy = int(round(x - group[0])), int(round(y - group[1]))
            banners = [(b[0] + self.notice_dx, b[1] + self.notice_dy, b[2] + self.notice_dx,
                        b[3] + self.notice_dy) for b in banners]
        reach = (min(b[0] for b in banners), min(b[1] for b in banners), max(b[2] for b in banners),
                 max(b[3] for b in banners)) if banners else None

        self.segments = model.route_segments(cum, modes, stops)
        start = stops[0][2] if stops else ""
        end = start if loop else stops[-1][2] if stops else ""
        title = str(hud.get("title") or "")
        summary = summary or {}
        km, seconds = summary.get("total_distance_km"), summary.get("total_duration_seconds")
        used = model.mode_cards(summary.get("mode_breakdown"), summary.get("mode_duration"))

        wanted: Dict[str, Tuple[cards.Card, layout.Entry]] = {}

        def want(name: str, build) -> None:
            entry = entries[name]
            if entry.show:
                wanted[name] = (build(entry.style), entry)

        if title:
            want("title", lambda s: cards.title_card(theme, title, loop, start, end, labels, style=s))
        if km is not None and seconds is not None:
            want("totals", lambda s: cards.totals_card(theme, km, seconds, labels, style=s))
        if used:
            want("modes", lambda s: cards.mode_bar(theme, used, labels, style=s))
        if self.segments:
            want("strip", lambda s: cards.strip_card(theme, self.segments, start, end, style=s))
        self.cards = _render(wanted, w, h, unit)

        strip, gap = self.cards.get("strip"), _BANNER_GAP_PX * unit
        if strip is not None and reach is not None and _overlaps(strip.box, reach, gap):
            room = max(strip.box[2] - (reach[2] + gap), (reach[0] - gap) - strip.box[0])
            factor = max(_MIN_STRIP_SCALE, min(1.0, room / (strip.box[2] - strip.box[0])))
            card, entry = wanted["strip"]
            self.cards.update(_render({"strip": (card, entry._replace(scale=entry.scale * factor))}, w, h, unit))

        self.line = None
        if "strip" in self.cards:
            found = _LINE.search(wanted["strip"][0].html)
            if found:
                self.line = tuple(float(v) for v in found.groups())
                self.spans = model.strip_spans(self.segments, self.line[0], self.line[1])
            else:
                logger.warning("The strip style's data-line is not \"x0 x1 y\": no progress is drawn on it.")
        # Badges and photo cards are laid out clear of wherever the cards ended up.
        self.reserved: List[Box] = [tuple(float(v) for v in c.box) for c in self.cards.values()]
        self.reserved += [tuple(float(v) for v in b) for b in banners]

    @contextmanager
    def banners(self):
        """The app's stop-by / closed banners as the themed design wants them; restored afterwards."""
        graphics = self.graphics
        saved = (getattr(graphics, "equal_stopby_notices", False), getattr(graphics, "stopby_notice_colors", None))
        graphics.equal_stopby_notices, graphics.stopby_notice_colors = True, self.notice_colors
        try:
            yield
        finally:
            graphics.equal_stopby_notices, graphics.stopby_notice_colors = saved

    def compose(
        self, frame: np.ndarray, i: int, t: float, dist: float, mode: Optional[str], timing, slide_seconds: float,
    ) -> np.ndarray:
        """The panels over `frame` at time `t`, the trace at `dist` travelling by `mode` (None: not yet moving).
        The travel-mode bar takes `slide_seconds` to drop in."""
        for name in ("title", "totals"):
            if name in self.cards:
                self.cards[name].paste(frame)
        if "modes" in self.cards and t >= timing.stats_at:
            u = min(1.0, (t - timing.stats_at) / slide_seconds)
            u = u * u * (3 - 2 * u)
            self.cards["modes"].paste(frame, alpha=u, dy=-(1 - u) * _SLIDE_PX * self.unit)
        if "strip" in self.cards:
            self.cards["strip"].paste(frame)
            self._progress(frame, i, dist, mode, arrived=t >= timing.trace_end)
        if self.show_notices:
            with self.banners():
                for at, kind, offset in ((timing.extras_at if timing.stopbys else None, "stopby", 0),
                                         (timing.closed_at if timing.closed else None, "closed", self.closed_offset)):
                    if at is not None and t >= at:
                        u = min(1.0, (t - at) / _NOTICE_FADE_SECONDS)
                        frame = self.graphics.render_stopby_notice(
                            frame, alpha=u * u * (3 - 2 * u), kind=kind, x_offset=offset + self.notice_dx,
                            y_offset=self.notice_dy)
        return frame

    def _progress(self, frame: np.ndarray, i: int, dist: float, mode: Optional[str], arrived: bool) -> None:
        """A see-through band over the part of the strip already travelled, and the traveller at its head
        until it has arrived (it would hide the E)."""
        if self.line is None or mode is None:
            return
        strip, (x0, _, line_y) = self.cards["strip"], self.line
        k = strip.scale
        start = int(round(strip.box[0] + x0 * k))
        end = int(round(strip.box[0] + model.strip_x(self.segments, self.spans, dist) * k))
        y = int(round(strip.box[1] + line_y * k))
        half = max(2, int(round(5 * k)))
        band = frame[max(0, y - half):y + half, start:max(start, end)]
        if band.size:
            colour = np.array([int(self.theme["accent"][j:j + 2], 16) for j in (5, 3, 1)], dtype=np.float32)
            band[:] = np.clip(band * 0.55 + colour * 0.45, 0, 255).astype(np.uint8)
        icon = None if arrived else self.graphics.transport_icon_sprite(i, 0.0, mode, max(4, int(round(30 * k))))
        if icon is not None:
            self.graphics.blit_sprite(frame, icon, (icon.shape[1] // 2, icon.shape[0]), end, y + half)


def themed_panels(
    graphics, hud: Optional[Dict], w: int, h: int, summary: Optional[Dict], stops: Sequence[model.Stop],
    cum: Sequence[float], modes: Sequence[str], loop: bool, has_stopbys: bool, has_closed: bool,
) -> Optional[ThemedPanels]:
    """The themed furniture for a project with a `hud` config, else None (the classic look)."""
    if not hud:
        return None
    theme_id = model.resolve_theme(hud.get("theme"), modes, 0.0)  # shortcut: climb unread; "auto" only has sea yet
    if theme_id is None:
        return None
    return ThemedPanels(graphics, hud, theme_id, w, h, summary, stops, cum, modes, loop, has_stopbys, has_closed)
