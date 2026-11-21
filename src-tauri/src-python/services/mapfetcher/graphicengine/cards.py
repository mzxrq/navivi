"""End-of-video summary stat card and generic card compositing."""

from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from services import tuning, video_text

from .glyphs import drawable

# The card-relevant labels (mode names, "distance"/"total", the taskbar
# card's title) are a subset of tuning.LABELS_JA — the single combined
# assets/config/labels_ja.json every on-video Japanese string lives in
# (also used directly by render_step.py/overview.py/outrocard.py for their
# own waypoint_fallback/start_prefix/stop_prefix keys).

# The only two keys that are themselves dicts (mode -> label) — every other
# key is a flat string, so a shallow "override replaces the whole value"
# merge would let a project's settings.summary_card_labels override ONE
# mode's name/duration label but silently drop every other mode's, unless
# those two are merged one level deeper instead.
_NESTED_LABEL_KEYS = ("mode_name", "mode_duration_label")

# Light-theme palette, kept for callers outside the engine; card methods
# read the active theme from self.ui (tuning.UI_THEMES).
_CARD_BG_COLOR: Tuple[int, int, int, int] = tuning.UI_THEMES["light"]["card_bg"]
_CARD_TEXT_COLOR: Tuple[int, int, int, int] = tuning.UI_THEMES["light"]["card_text"]
_CARD_LABEL_COLOR: Tuple[int, int, int, int] = tuning.UI_THEMES["light"]["card_label"]
# Total column/row uses the neutral text color, never a vivid mode accent.
_TOTAL_ACCENT_COLOR: Tuple[int, int, int, int] = _CARD_TEXT_COLOR


def merge_summary_card_labels(overrides: Optional[Dict]) -> Dict:
    """Merges a job_config.json settings.summary_card_labels override (any
    subset of keys, including a partial mode_name/mode_duration_label) over
    the current project's language catalog (services/video_text.py) —
    never mutates either input."""
    merged = video_text.current_labels()
    if not overrides:
        return merged
    for key, value in overrides.items():
        if key in _NESTED_LABEL_KEYS and isinstance(value, dict):
            merged[key] = {**merged.get(key, {}), **value}
        else:
            merged[key] = value
    return merged


def _fmt_distance(km: float) -> str:
    """A distance for a card: metres under a kilometre, else kilometres."""
    return f"{km * 1000:.0f} m" if km < 1 else f"{km:.1f} km"


def _blend_card(out: np.ndarray, card_bgra: np.ndarray, x0: int, y0: int, alpha: float) -> None:
    """Alpha-blends `card_bgra` onto `out` at (x0, y0) in place: the card's own per-pixel alpha channel
    together with the caller-supplied fade-in/out `alpha`, so the card can both have soft edges and fade as a whole."""
    ch, cw = card_bgra.shape[:2]
    card_bgr, card_alpha = (
        card_bgra[:, :, :3].astype(np.float32),
        (card_bgra[:, :, 3].astype(np.float32) / 255.0) * alpha,
    )
    roi = out[y0 : y0 + ch, x0 : x0 + cw].astype(np.float32)
    out[y0 : y0 + ch, x0 : x0 + cw] = (
        card_bgr * card_alpha[..., None] + roi * (1 - card_alpha[..., None])
    ).astype(np.uint8)


class _CardMixin:
    @staticmethod
    def _draw_clock_icon(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color: Tuple):
        r = size / 2
        width = max(2, round(size * 0.12))
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=width)
        draw.line([(cx, cy), (cx, cy - r * 0.55)], fill=color, width=width)
        draw.line([(cx, cy), (cx + r * 0.4, cy + r * 0.1)], fill=color, width=width)

    @staticmethod
    def _draw_stat_group(
        draw: ImageDraw.ImageDraw,
        x0: float,
        center_y: float,
        icon_size: float,
        icon_fn,
        icon_color: Tuple,
        label: str,
        font_label,
        label_color: Tuple,
        value: str,
        font_value,
        value_color: Tuple,
        icon_text_gap: float,
        line_gap: float,
    ) -> float:
        """One stat group in the "icon on the left, label/value stacked to
        its right" style (matches the reference walking-time/distance pill
        card): the icon sits centered on the vertical midline of its two
        text lines, rather than the icon+label sharing a row with the value
        centered separately underneath. Returns the group's total width so
        callers can lay out multiple groups left-to-right."""
        label_w = draw.textlength(label, font=font_label)
        value_w = draw.textlength(value, font=font_value)
        label_ascent, _ = font_label.getmetrics()
        value_ascent, _ = font_value.getmetrics()
        text_h = label_ascent + line_gap + value_ascent
        top_y = center_y - text_h / 2
        icon_fn(draw, x0 + icon_size / 2, center_y, icon_size, icon_color)
        text_x = x0 + icon_size + icon_text_gap
        draw.text((text_x, top_y), label, font=font_label, fill=label_color)
        draw.text(
            (text_x, top_y + label_ascent + line_gap), value, font=font_value, fill=value_color
        )
        return icon_size + icon_text_gap + max(label_w, value_w)

    # Every summary-card display string (mode names, "distance"/"total"
    # labels, the taskbar card's title) lives in assets/config/labels_ja.json
    # by default, layered with this project's own job_config.json
    # settings.summary_card_labels override (see self.summary_card_labels,
    # set in GraphicsEngineBase.__init__) — instance methods, not static, so
    # they can actually see that per-project override.
    def _mode_duration_label(self, mode: str) -> str:
        labels = getattr(self, "summary_card_labels", None) or video_text.current_labels()
        return labels["mode_duration_label"].get((mode or "").lower(), labels["duration_fallback"])

    def _mode_name_ja(self, mode: str) -> str:
        labels = getattr(self, "summary_card_labels", None) or video_text.current_labels()
        return labels["mode_name"].get((mode or "").lower(), (mode or "").capitalize())

    def _format_duration_ja(self, seconds: float) -> str:
        """Name kept from when the text was Japanese only; the wording is the project's language."""
        labels = getattr(self, "summary_card_labels", None) or video_text.current_labels()
        if seconds < 60:
            return labels["duration_seconds"].format(n=max(1, int(round(seconds))))
        hrs, mins = divmod(int(round(seconds / 60)), 60)
        if hrs:
            return labels["duration_hours_minutes"].format(h=hrs, m=mins)
        return labels["duration_minutes"].format(m=mins)

    def _mode_accent(self, mode: str) -> Tuple:
        """Same color the route line itself uses for this mode
        (MODE_COLORS), pre-reversed so it comes out correct after the
        canvas-wide BGR swap at the end — ties each mode's stat
        column/row back to its own line color on the map instead of
        every one sharing one generic accent. "total" isn't a real
        travel mode with a line color of its own, so it always gets the
        same neutral dark color instead (self.ui["card_text"]) — never one
        of the vivid per-mode accents, so it can't end up looking like
        whichever mode happens to also be that hue (walking's blue, say)."""
        if mode == "total":
            return self.ui["card_text"]
        return tuple(reversed(self.MODE_COLORS.get(mode, self.line_color))) + (255,)

    @staticmethod
    def _add_card_shadow(
        canvas: Image.Image, radius_px: float, tint_rgb: Tuple[int, int, int], scale: int,
    ) -> Image.Image:
        """Wraps a finished card canvas in the same soft, color-tinted
        "elevated card" drop shadow every popup card already gets (see
        popup_box.py's render_popup_box) — the summary card was the one
        card in the whole video with no shadow of its own, so next to a
        popup card on screen it read as pasted flat rather than floating
        above the map the same way. Grows the canvas by the shadow's own
        padding (matching popup_box's blur radius/offset, scaled to this
        card's own 2x supersampling) rather than shadowing in place, so
        the blur has room to fall off past the card's edge instead of
        being clipped by the original canvas bounds."""
        pad = 16 * scale
        offset_y = 8 * scale
        blur = 10 * scale
        w, h = canvas.size
        out = Image.new("RGBA", (w + pad * 2, h + pad * 2 + offset_y), (0, 0, 0, 0))
        shadow = Image.new("RGBA", out.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            [pad, pad + offset_y, pad + w, pad + offset_y + h],
            radius=radius_px, fill=tint_rgb + (70,),
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=blur))
        out.paste(shadow, (0, 0), shadow)
        out.paste(canvas, (pad, pad), canvas)
        return out

    def _stopby_notice_layout(self, w: int, h: int, kind: str = "stopby"):
        """Fonts, wrapped body lines and every box of the stop-by notice for
        a w x h frame: (scale, title_font, body_font, lines, ribbon box,
        body box). Shared by the drawing and by `stopby_notice_box`."""
        s = h / 1080.0
        margin = int(28 * s)
        title_font = self._card_font(self.FONT_CANDIDATES_BOLD, int(26 * s))
        body_font = self._card_font(self.FONT_CANDIDATES_REGULAR, int(21 * s))
        probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
        icon_d = int(26 * s)
        text_x0 = int(22 * s) + icon_d + int(14 * s)
        # As wide as its longest line (so the given line breaks hold), within
        # a sensible range; anything longer still wraps.
        notice = video_text.current_labels()
        notice_title, notice_body = notice[f"{kind}_notice_title"], notice[f"{kind}_notice_body"]
        longest = max(
            (probe.textlength(p, font=body_font) for p in notice_body.split(chr(10))),
            default=0,
        )
        body_w = int(min(0.45 * w, max(360 * s, text_x0 + longest + 24 * s)))
        text_w = body_w - text_x0 - int(20 * s)
        lines: List[str] = []
        for paragraph in notice_body.split(chr(10)):
            line = ""
            # Words where the text has spaces, single characters for Japanese.
            units = [w + " " for w in paragraph.split(" ")] if " " in paragraph else list(paragraph)
            for ch in units:
                if line and probe.textlength((line + ch).rstrip(), font=body_font) > text_w:
                    lines.append(line.rstrip())
                    line = ""
                line += ch
            if line:
                lines.append(line.rstrip())
        line_h = int(body_font.size * 1.45)
        body_h = int(18 * s) * 2 + line_h * len(lines)
        body_x0 = margin
        body_y1 = h - margin
        body_y0 = body_y1 - body_h
        title_w = int(probe.textlength(notice_title, font=title_font))
        ribbon_h = int(50 * s)
        ribbon_x0 = body_x0 - int(10 * s)
        ribbon_y1 = body_y0 + int(12 * s)  # overlaps the body card's top edge
        ribbon = (ribbon_x0, ribbon_y1 - ribbon_h, ribbon_x0 + title_w + int(44 * s), ribbon_y1)
        body = (body_x0, body_y0, body_x0 + body_w, body_y1)
        return s, title_font, body_font, lines, ribbon, body

    def stopby_notice_box(
        self, w: int, h: int, kind: str = "stopby", x_offset: int = 0,
    ) -> Tuple[int, int, int, int]:
        """(x0, y0, x1, y1) the notice covers, so cards can be kept off it. `x_offset` slides
        it right of the bottom-left corner, for a second notice beside the first."""
        _, _, _, _, ribbon, body = self._stopby_notice_layout(w, h, kind)
        return (min(ribbon[0], body[0]) + x_offset, ribbon[1],
                max(ribbon[2], body[2]) + x_offset, body[3])

    def render_stopby_notice(
        self, frame: np.ndarray, alpha: float = 1.0,
        marker_color: Tuple[int, int, int] = tuning.STOPBY_PIN_COLOR, kind: str = "stopby",
        x_offset: int = 0,
    ) -> np.ndarray:
        """Bottom-left notice for the round stop-by markers: a ribbon with
        tuning.STOPBY_NOTICE_TITLE over a white rounded card with the marker
        itself and tuning.STOPBY_NOTICE_BODY (they are optional extras).
        `alpha` fades it as one unit. Colors are BGR, like the frame."""
        if alpha <= 0:
            return frame
        h, w = frame.shape[:2]
        # The notice is the same on every frame: drawn (with its blurred shadow) once, then only blended.
        key = (w, h, tuple(marker_color), kind, video_text.current_labels()[f"{kind}_notice_title"])
        cache = self.__dict__.setdefault("_stopby_notice_cache", {})
        if key not in cache:
            cache[key] = self._stopby_notice_sprite(w, h, marker_color, kind)
        (x0, y0), color, cover = cache[key]
        x0 = max(0, min(x0 + x_offset, w - cover.shape[1]))
        out = frame.copy()
        roi = out[y0:y0 + cover.shape[0], x0:x0 + cover.shape[1]].astype(np.float32)
        blended = color * float(alpha) + roi * (1.0 - cover * float(alpha))
        out[y0:y0 + cover.shape[0], x0:x0 + cover.shape[1]] = np.clip(blended + 0.5, 0, 255).astype(np.uint8)
        return out

    def _stopby_notice_layer(self, w: int, h: int, kind: str):
        """The notice's RGBA layer (soft shadow, body card with its text, titled ribbon) and where its marker goes:
        (layer, marker x, marker y, marker icon diameter, layout scale)."""
        s, title_font, body_font, lines, ribbon, body = self._stopby_notice_layout(w, h, kind)
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))

        # soft shadow under both cards
        shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle([body[0] - 4, body[1] + 2, body[2] + 4, body[3] + 10],
                             radius=int(20 * s), fill=(0, 0, 0, 70))
        sd.rounded_rectangle([ribbon[0], ribbon[1] + 4, ribbon[2], ribbon[3] + 6],
                             radius=int(12 * s), fill=(0, 0, 0, 60))
        layer.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(radius=10 * s)))
        d = ImageDraw.Draw(layer)

        # body card
        d.rounded_rectangle(body, radius=int(16 * s), fill=(255, 255, 255, 245))
        icon_d = int(26 * s)
        ix = body[0] + int(22 * s)
        iy = body[1] + int(18 * s) + int(body_font.size * 1.45 - icon_d) // 2 + int(4 * s)
        # The pin will be drawn via self.draw_marker on the BGR frame afterwards
        cx, cy = ix + icon_d / 2, iy + icon_d / 2
        tx = ix + icon_d + int(14 * s)
        ty = body[1] + int(18 * s) + int(4 * s)
        for line in lines:
            d.text((tx, ty), line, font=body_font, fill=(45, 45, 45, 255))
            ty += int(body_font.size * 1.45)

        # ribbon: a banded title with a folded tail under its left end
        notice_title = video_text.current_labels()[f"{kind}_notice_title"]
        rgb = tuple(reversed(tuning.CLOSED_PIN_COLOR if kind == "closed" else tuning.STOPBY_NOTICE_RIBBON_COLOR))
        dark = tuple(int(c * 0.6) for c in rgb)
        fold = int(10 * s)
        d.polygon([(ribbon[0], ribbon[3]), (ribbon[0] + fold, ribbon[3]),
                   (ribbon[0] + fold, ribbon[3] + fold)], fill=dark + (255,))
        d.rounded_rectangle(ribbon, radius=int(10 * s), fill=rgb + (255,))
        tb = d.textbbox((0, 0), notice_title, font=title_font)
        d.text((ribbon[0] + int(22 * s), (ribbon[1] + ribbon[3]) // 2 - (tb[1] + tb[3]) // 2),
               notice_title, font=title_font, fill=(255, 255, 255, 255))
        return layer, cx, cy, icon_d, s

    def _stopby_notice_sprite(self, w: int, h: int, marker_color: Tuple[int, int, int], kind: str = "stopby"):
        """((x, y), premultiplied BGR, coverage 0..1) of the notice with its marker, cropped to what it covers."""
        layer, cx, cy, icon_d, s = self._stopby_notice_layer(w, h, kind)
        x0, y0, x1, y1 = layer.getbbox()
        rgba = np.asarray(layer.crop((x0, y0, x1, y1))).astype(np.float32)
        card_cover = rgba[:, :, 3:4] / 255.0
        card = rgba[:, :, 2::-1] * card_cover
        # The marker is opaque drawing on the BGR frame: drawn on black and on white, the difference is its coverage.
        marks = []
        for bg in (0, 255):
            plate = np.full((y1 - y0, x1 - x0, 3), bg, np.uint8)
            self.draw_marker(plate, int(cx) - x0, int(cy + icon_d / 2 - 2 * s) - y0,
                             number="×" if kind == "closed" else "・",
                             color=tuning.CLOSED_PIN_COLOR if kind == "closed" else marker_color,
                             is_circle=False, scale=s * 0.7)
            marks.append(plate.astype(np.float32))
        mark_cover = np.clip(1.0 - (marks[1] - marks[0]).mean(axis=2, keepdims=True) / 255.0, 0.0, 1.0)
        color = marks[0] + card * (1.0 - mark_cover)
        cover = 1.0 - (1.0 - card_cover) * (1.0 - mark_cover)
        return (x0, y0), color, cover

    def _fmt_duration(self, seconds: float) -> str:
        """A duration for a card ("--" when there is none)."""
        return self._format_duration_ja(seconds) if seconds > 0 else "--"

    def _summary_columns(
        self, distance_km: float, duration_seconds: float, mode_breakdown: Optional[Dict[str, float]],
        mode_duration: Optional[Dict[str, float]],
    ) -> List[Tuple[str, str, float, float]]:
        """(label, mode, distance, duration) per travel mode actually used, longest first, plus a Total column."""
        mode_duration = mode_duration or {}
        columns: List[Tuple[str, str, float, float]] = []
        if mode_breakdown:
            for mode, dist in sorted(mode_breakdown.items(), key=lambda kv: -kv[1]):
                columns.append(
                    (self._mode_name_ja(mode), mode.lower(), dist, mode_duration.get(mode, 0.0))
                )
        # A single mode's own column already IS the total (same distance,
        # same time) — appending "Total" too would just repeat it. Only
        # add it when there's more than one mode to actually total up, or
        # none at all (nothing else to show).
        if not mode_breakdown or len(mode_breakdown) > 1:
            columns.append((self.summary_card_labels["total_label"], "total", distance_km, duration_seconds))
        return columns

    def _summary_pill(self, column: Tuple[str, str, float, float], border_rgba: tuple, scale: int):
        """The single-mode card: a light, fully-rounded "pill" — icon on the left of each stat, its
        label/value stacked to the right. Returns (canvas, corner radius px)."""
        bg_color = self.ui["card_bg"]
        text_color, label_color = self.ui["card_text"], self.ui["card_label"]
        icon_color = self.ui["card_text"]

        # Bold, not regular — Noto Sans's regular weight read as too
        # thin for this small a caption; size/color still separate it
        # from the (also bold) value below it.
        font_label = self._load_font(
            self.FONT_CANDIDATES_BOLD, tuning.SUMMARY_CARD_LABEL_FONT_SIZE * scale
        )
        font_value = self._load_font(
            self.FONT_CANDIDATES_BOLD, tuning.SUMMARY_CARD_VALUE_FONT_SIZE * scale
        )

        tiles = self._pill_tiles(column)

        icon_size = 36 * scale
        icon_text_gap = 14 * scale
        line_gap = 12 * scale
        group_gap = 46 * scale
        # Margin around the content — was a fixed 560x150 box regardless
        # of how little a 2-tile pill actually needs, reading as mostly
        # empty padding. Sized to the content instead, with just enough
        # margin to keep the rounded corners/border from crowding it.
        margin_x, margin_y = 34 * scale, 22 * scale

        # Measured on a throwaway canvas (real canvas doesn't exist yet
        # — its size depends on this measurement) so the whole row can
        # be centered once the actual card is created at content size.
        probe_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        label_ascent, _ = font_label.getmetrics()
        value_ascent, _ = font_value.getmetrics()
        content_h = max(icon_size, label_ascent + line_gap + value_ascent)
        widths = [
            self._draw_stat_group(
                probe_draw, 0, content_h / 2, icon_size, icon_fn, icon_color,
                tile_label, font_label, label_color, tile_value, font_value,
                text_color, icon_text_gap, line_gap,
            )
            for icon_fn, tile_label, tile_value in tiles
        ]
        content_w = sum(widths) + group_gap * (len(tiles) - 1)

        card_w_px = int(content_w + margin_x * 2)
        card_h_px = int(content_h + margin_y * 2)
        card_radius_px = 22 * scale
        canvas, draw = self._rounded_card(
            card_w_px, card_h_px, card_radius_px, bg_color,
            border_rgba if self.card_border_thickness else None, self.card_border_thickness * scale,
        )

        center_y = card_h_px / 2
        x = (card_w_px - content_w) / 2
        for (icon_fn, tile_label, tile_value), group_w in zip(tiles, widths):
            self._draw_stat_group(
                draw, x, center_y, icon_size, icon_fn, icon_color,
                tile_label, font_label, label_color, tile_value, font_value,
                text_color, icon_text_gap, line_gap,
            )
            x += group_w + group_gap
        return canvas, card_radius_px

    def _pill_tiles(self, column: Tuple[str, str, float, float]) -> list:
        """The pill's two stats as (icon_fn, label, value): the mode's time, then the distance."""
        label, mode, dist, dur = column
        distance_str = f"{dist * 1000:.0f} m" if dist < 1 else f"{dist:.1f} km"
        dur_str = self._format_duration_ja(dur) if dur > 0 else "--"
        time_icon = lambda d, cx, cy, sz, col: self._draw_mode_icon(d, mode, cx, cy, sz, col)

        return [
            (time_icon, self._mode_duration_label(mode), dur_str),
            (self._draw_ruler_icon, self.summary_card_labels["distance_label"], distance_str),
        ]

    @staticmethod
    def _rounded_card(card_w_px: int, card_h_px: int, radius: int, fill, outline, width: int):
        """A transparent canvas with the card's rounded, filled (and optionally outlined) body; returns (canvas, draw)."""
        canvas = Image.new("RGBA", (int(card_w_px), card_h_px), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle(
            [0, 0, card_w_px - 1, card_h_px - 1], radius=radius, fill=fill, outline=outline, width=width,
        )
        return canvas, draw

    def _mode_column_width(
        self, columns: list, font_label, font_label_time, font_value, stat_icon_d: int, icon_text_gap: int,
    ) -> float:
        """The widest line of any mode column: each column is sized to fit its own text, then all share the widest."""
        probe_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        col_content_w = 0.0
        for label, _mode, dist, dur in columns:
            distance_str = f"{dist * 1000:.0f} m" if dist < 1 else f"{dist:.1f} km"
            dur_str = self._format_duration_ja(dur) if dur > 0 else None
            widths = [
                probe_draw.textlength(label, font=font_label),
                probe_draw.textlength(distance_str, font=font_value),
            ]
            if dur_str:
                widths.append(
                    stat_icon_d + icon_text_gap
                    + probe_draw.textlength(dur_str, font=font_label_time)
                )
            col_content_w = max(col_content_w, *widths)
        return col_content_w

    def _draw_mode_column(
        self, draw, i: int, column: tuple, col_w: float, icon_cy: float, h: int, scale: int, fonts: tuple,
        sizes: tuple, colors: tuple,
    ) -> None:
        """One mode's column: divider, icon, label, distance, and the duration with its clock."""
        label, mode, dist, dur = column
        font_label, font_label_time, font_value_2 = fonts
        icon_size, icon_text_gap, stat_icon_d, label_gap, value_gap, row_gap = sizes
        text_color, label_color, divider_color = colors
        col_cx = col_w * i + col_w / 2
        col_accent = self._mode_accent(mode)
        if i > 0:
            x_div = col_w * i
            draw.line(
                [(x_div, 22 * scale), (x_div, h * scale - 22 * scale)],
                fill=divider_color,
                width=2 * scale,
            )

        if mode == "total":
            self._draw_total_icon(draw, col_cx, icon_cy, icon_size, text_color)
        else:
            self._draw_mode_icon(draw, mode, col_cx, icon_cy, icon_size, col_accent)

        label_w = draw.textlength(label, font=font_label)
        label_y = icon_cy + icon_size / 2 + label_gap
        draw.text(
            (col_cx - label_w / 2, label_y), label, font=font_label, fill=label_color
        )

        distance_str = f"{dist * 1000:.0f} m" if dist < 1 else f"{dist:.1f} km"
        value_w = draw.textlength(distance_str, font=font_value_2)
        value_y = label_y + value_gap
        draw.text(
            (col_cx - value_w / 2, value_y),
            distance_str,
            font=font_value_2,
            fill=col_accent,
        )

        dur_str = self._format_duration_ja(dur) if dur > 0 else None
        if dur_str:
            row_y = value_y + row_gap
            dur_w = draw.textlength(dur_str, font=font_label_time)
            line_x = col_cx - (stat_icon_d + icon_text_gap + dur_w) / 2
            self._draw_clock_icon(
                draw, line_x + stat_icon_d / 2, row_y + stat_icon_d / 2,
                stat_icon_d, col_accent,
            )
            draw.text(
                (line_x + stat_icon_d + icon_text_gap, row_y),
                dur_str, font=font_label_time, fill=label_color,
            )

    def _summary_modes(self, columns: list, w: int, h: int, border_rgba: tuple, scale: int):
        """The multi-mode card: the same light "residential" theme as the single-mode pill (white glass, dark
        text, thin neutral border); only the layout (one column per mode) differs. Returns (canvas, corner radius px)."""
        bg_color = self.ui["card_bg"]
        text_color, label_color = self.ui["card_text"], self.ui["card_label"]
        divider_color = self.ui["divider"]

        # Mode header ("Draw"/"Walking"/"Driving"/"Total") is Regular —
        # LINE Seed JP's regular weight reads fine at this size, unlike
        # the old Kosugi Maru default this comment used to justify Bold
        # for. Kept bold for the per-column time caption below it
        # (font_label_time) and the big distance value, so those two
        # still stand out from the plain mode name above them.
        font_label = self._load_font(
            self.FONT_CANDIDATES_REGULAR, tuning.SUMMARY_CARD_LABEL_FONT_SIZE * scale
        )
        font_label_time = self._load_font(
            self.FONT_CANDIDATES_BOLD, tuning.SUMMARY_CARD_LABEL_FONT_SIZE * scale
        )
        font_value_2 = self._load_font(
            self.FONT_CANDIDATES_BOLD, tuning.SUMMARY_CARD_VALUE_FONT_SIZE * scale
        )

        icon_size = 26 * scale
        icon_text_gap = 6 * scale
        stat_icon_d = 15 * scale

        # Card width used to be a fixed 560px split evenly across
        # however many columns there were — fine for 2-3 columns, but a
        # 4+ column trip (e.g. Draw/Walking/Driving/Total) squeezed each
        # column well below what its own value/time text actually
        # needed, so neighboring columns' text ran together with no gap
        # between them. Size each column to fit its own widest line
        # instead (same content-driven approach the single-mode pill
        # card above already uses), then every column gets the same
        # width — the widest one's — so the divider lines still land
        # evenly.
        num_columns = len(columns)
        col_content_w = self._mode_column_width(
            columns, font_label, font_label_time, font_value_2, stat_icon_d, icon_text_gap
        )
        col_padding = 20 * scale
        col_w = max((w * scale) / num_columns, col_content_w + col_padding * 2)
        card_w_px, card_h_px = int(col_w * num_columns), h * scale

        card_radius_px = 18 * scale
        canvas = Image.new("RGBA", (card_w_px, card_h_px), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle(
            [0, 0, card_w_px - 1, card_h_px - 1],
            radius=card_radius_px,
            fill=bg_color,
            outline=border_rgba if self.card_border_thickness else None,
            width=self.card_border_thickness * scale,
        )
        # label_gap was 6*scale — the icon and the mode label ("Draw",
        # "Walking", ...) sat almost touching with no visible breathing
        # room, unlike the single-mode pill card's own label/value gap
        # (line_gap = 12*scale) above. Matched to that same spacing.
        label_gap = 12 * scale
        value_gap = 18 * scale
        row_gap = 36 * scale

        # The icon/label/value/time stack used to anchor near the top
        # (icon_cy fixed at 32*scale) regardless of the card's actual
        # height, leaving the value and time rows crowded near the top
        # border with a lot of unused space below them. Center the
        # whole stack in the card instead, so it has even breathing
        # room from both the top and bottom borders. Mirrors the same
        # relative offsets the per-column drawing below uses, just
        # measured from icon_cy = 0 first to find where icon_cy should
        # actually land.
        icon_top_rel = -icon_size / 2
        content_bottom_rel = (
            icon_size / 2 + label_gap + value_gap + row_gap + stat_icon_d
        )
        # [NOTE] [Animation] Vertically centers the icon/label/value/time stack by measuring its relative extents from a hypothetical icon_cy=0 first, then solving for the real icon_cy.
        icon_cy = h * scale / 2 - (icon_top_rel + content_bottom_rel) / 2

        for i, column in enumerate(columns):
            self._draw_mode_column(
                draw, i, column, col_w, icon_cy, h, scale, (font_label, font_label_time, font_value_2),
                (icon_size, icon_text_gap, stat_icon_d, label_gap, value_gap, row_gap),
                (text_color, label_color, divider_color),
            )
        return canvas, card_radius_px

    def create_summary_card(
        self,
        distance_km: float,
        duration_seconds: float,
        mode_breakdown: Optional[Dict[str, float]] = None,
        mode_duration: Optional[Dict[str, float]] = None,
        card_size=(560, 190),
    ) -> np.ndarray:
        """A dark glass stat card for the end of the overview video: one
        column per travel mode actually used (icon, distance, time), plus a
        final Total column. A single-mode trip only shows Total, since one
        mode column would just repeat it."""
        w, h = card_size
        scale = 2
        columns = self._summary_columns(distance_km, duration_seconds, mode_breakdown, mode_duration)
        # BGR, like every other color in job_config.json's settings —
        # reversed here since the canvas is RGBA->BGR swapped as a
        # whole at the end (see _mode_accent's own comment).
        border_rgba = tuple(reversed(self.card_border_color)) + (255,)

        # A single mode gets a light, fully-rounded "pill" card — icon on
        # the left of each stat, its label/value stacked to the right —
        # matching the reference walking-time/distance design. Multi-mode
        # trips keep the denser dark glass card with one column per mode,
        # since that layout (mode header + big number + small time row)
        # doesn't fit the pill style once there's more than one stat pair.
        if len(columns) == 1:
            canvas, card_radius_px = self._summary_pill(columns[0], border_rgba, scale)
        else:
            canvas, card_radius_px = self._summary_modes(columns, w, h, border_rgba, scale)

        # Same elevated-card shadow every popup card gets — see
        # _add_card_shadow's own comment on why the summary card was
        # missing one. Grows the canvas, so w/h are recomputed from its
        # new size before the final downscale.
        canvas = self._add_card_shadow(canvas, card_radius_px, border_rgba[:3], scale)
        w, h = canvas.size[0] // scale, canvas.size[1] // scale

        # [NOTE] [Animation] Downscales the 2x supersampled canvas for anti-aliasing, then swaps RGBA -> BGRA to match OpenCV's channel order.
        canvas = canvas.resize((w, h), Image.Resampling.LANCZOS)
        return np.array(canvas)[:, :, [2, 1, 0, 3]]

    def _stacked_blocks(
        self, distance_km: float, duration_seconds: float, mode_breakdown: Optional[Dict[str, float]],
        mode_duration: Optional[Dict[str, float]], row_gap: int, scale: int,
    ) -> Tuple[List[List[Tuple]], int]:
        """(blocks of (icon drawer, text, color) rows, the gap between blocks) of the stacked card.

        A single-mode trip (or no mode_breakdown at all) is two rows: a walking figure beside the total
        distance, a clock beside the total duration; more than one mode gets a block per mode plus a Total block.
        """
        mode_duration = mode_duration or {}
        if bool(mode_breakdown) and len(mode_breakdown) > 1:
            blocks: List[List[Tuple]] = []
            for mode, dist in sorted(mode_breakdown.items(), key=lambda kv: -kv[1]):
                accent = self._mode_accent(mode)
                mode_icon = (lambda d, cx, cy, sz, col, m=mode: self._draw_mode_icon(d, m, cx, cy, sz, col))
                blocks.append([
                    (mode_icon, _fmt_distance(dist), accent),
                    (self._draw_clock_icon, self._fmt_duration(mode_duration.get(mode, 0.0)), accent),
                ])
            blocks.append([
                (self._draw_ruler_icon, _fmt_distance(distance_km), self.ui["card_text"]),
                (self._draw_clock_icon, self._fmt_duration(duration_seconds), self.ui["card_text"]),
            ])
            return blocks, 22 * scale
        blocks = [[
            (self._draw_walking_icon, _fmt_distance(distance_km), self.ui["card_text"]),
            (self._draw_clock_icon, self._fmt_duration(duration_seconds), self.ui["card_text"]),
        ]]
        return blocks, row_gap

    def _draw_stacked_rows(self, draw, blocks: list, font_value, sizes: tuple) -> None:
        """Each block's rows top to bottom: icon, then its text; a wider gap between blocks than between a block's own rows."""
        margin_x, margin_y, row_h, row_gap, block_gap, icon_size, icon_text_gap = sizes
        text_ascent = font_value.getmetrics()[0]
        row_cy = margin_y + row_h / 2
        for block_idx, block in enumerate(blocks):
            for row_idx, (icon_fn, text, color) in enumerate(block):
                icon_fn(draw, margin_x + icon_size / 2, row_cy, icon_size, color)
                text_x = margin_x + icon_size + icon_text_gap
                draw.text((text_x, row_cy - text_ascent / 2), text, font=font_value, fill=color)
                row_cy += row_h + (row_gap if row_idx < len(block) - 1 else 0)
            if block_idx < len(blocks) - 1:
                row_cy += block_gap

    def create_summary_card_stacked(
        self,
        distance_km: float,
        duration_seconds: float,
        mode_breakdown: Optional[Dict[str, float]] = None,
        mode_duration: Optional[Dict[str, float]] = None,
    ) -> np.ndarray:
        """Third summary-card template: the user's own sketch — stacked
        rows, each just an icon and a number, no captions explaining what
        each one is (create_summary_card's pill/column and
        create_summary_card_taskbar's notification flyout both spell that
        out with a label; this one assumes the viewer already knows).

        A single-mode trip (or no mode_breakdown at all) is two rows: a
        walking figure beside the total distance, a clock beside the total
        duration, both in plain text color — that single mode already IS
        the total, same reasoning create_summary_card's own single-column
        pill uses. More than one mode gets a "route mode" block per mode
        (distance row, then duration row, each colored in that mode's own
        route-line accent — see _mode_accent) plus a Total block in
        self.ui["card_text"], the same color language create_summary_card's
        multi-column layout already uses, just as rows instead of columns."""
        scale = 2

        font_value = self._load_font(
            self.FONT_CANDIDATES_BOLD, tuning.SUMMARY_CARD_VALUE_FONT_SIZE * scale
        )
        icon_size = 34 * scale
        icon_text_gap = 16 * scale
        row_gap = 14 * scale
        margin_x, margin_y = 26 * scale, 20 * scale
        border_rgba = tuple(reversed(self.card_border_color)) + (255,)

        # blocks: a list of rows, each (icon_fn, text, color); the
        # (slightly larger) gap between blocks can be told apart from the
        # (smaller) gap between a mode's own distance/time rows.
        blocks, block_gap = self._stacked_blocks(
            distance_km, duration_seconds, mode_breakdown, mode_duration, row_gap, scale
        )
        rows = [row for block in blocks for row in block]

        probe_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        row_h = max(icon_size, font_value.getmetrics()[0])
        content_w = max(
            icon_size + icon_text_gap + probe_draw.textlength(text, font=font_value)
            for _, text, _ in rows
        )
        content_h = (
            row_h * len(rows)
            + row_gap * sum(len(block) - 1 for block in blocks)
            + block_gap * (len(blocks) - 1)
        )

        card_w_px = int(content_w + margin_x * 2)
        card_h_px = int(content_h + margin_y * 2)
        card_radius_px = 20 * scale
        canvas, draw = self._rounded_card(
            card_w_px, card_h_px, card_radius_px, self.ui["card_bg"],
            border_rgba if self.card_border_thickness else None, self.card_border_thickness * scale,
        )

        self._draw_stacked_rows(
            draw, blocks, font_value, (margin_x, margin_y, row_h, row_gap, block_gap, icon_size, icon_text_gap)
        )

        canvas = self._add_card_shadow(canvas, card_radius_px, border_rgba[:3], scale)
        w, h = canvas.size[0] // scale, canvas.size[1] // scale
        canvas = canvas.resize((w, h), Image.Resampling.LANCZOS)
        return np.array(canvas)[:, :, [2, 1, 0, 3]]

    def _columns_spec(
        self, distance_km: float, duration_seconds: float, mode_breakdown: Optional[Dict[str, float]],
        mode_duration: Optional[Dict[str, float]], total_dist: float, total_dur: float, banner_theme: bool,
        remaining: bool = False,
    ) -> list:
        """(label, mode, distance, duration, color) per column of the columns card: one per mode plus a Total
        when there is more than one, a lone mode with its own total, or just the distance without a breakdown.
        `remaining`: the Total column is what is LEFT of the trip (a leg's card), labelled remaining_label."""
        mode_duration = mode_duration or {}
        multi_mode = bool(mode_breakdown) and len(mode_breakdown) > 1
        total_label = self.summary_card_labels.get(
            "remaining_label" if remaining else "total_label") or self.summary_card_labels["total_label"]
        if multi_mode:
            columns = [
                (self._mode_name_ja(mode), mode, dist, mode_duration.get(mode, 0.0), self._mode_accent(mode))
                for mode, dist in sorted(mode_breakdown.items(), key=lambda kv: -kv[1])
            ]
            columns.append((
                total_label, "total", total_dist, total_dur,
                self.ui["card_text"],
            ))
        elif mode_breakdown and len(mode_breakdown) == 1:
            # The total is shown even when it repeats the one mode (user's choice).
            (single_mode,) = mode_breakdown.keys()
            columns = [
                (
                    self._mode_name_ja(single_mode), single_mode, distance_km, duration_seconds,
                    self._mode_accent(single_mode),
                ),
                (
                    total_label, "total", total_dist, total_dur,
                    self.ui["card_text"],
                ),
            ]
        else:
            columns = [(
                self.summary_card_labels["distance_label"], "walking", distance_km, duration_seconds,
                self.ui["card_text"],
            )]

        if banner_theme:
            bright = self.ui["pill_text"]
            columns = [(lab, mode, d, t, bright) for lab, mode, d, t, _ in columns]
        return columns

    def _draw_stat_column(
        self, draw, i: int, row: tuple, col_w: float, card_h_px: int, scale: int, fonts: tuple, metrics: tuple,
        divider_color,
    ) -> None:
        """One column of the columns card: divider, the mode icon and the clock icon on one vertical line,
        then label, distance and time sharing one left edge."""
        label_text, mode, dist_s, dur_s, color, _text_w = row
        font_label, font_value, font_time = fonts
        (label_ascent, time_ascent, line_gap, row_gap, group_h, icon_size, clock_icon_size, time_row_h,
         icon_col_w, icon_col_gap, col_pad_x, margin_y) = metrics
        col_x0 = col_w * i + col_pad_x
        if i > 0:
            x_div = col_w * i
            draw.line(
                [(x_div, 18 * scale), (x_div, card_h_px - 18 * scale)],
                fill=divider_color, width=2 * scale,
            )

        icon_fn = (
            self._draw_total_icon if mode == "total"
            else (lambda d, cx, cy, sz, col, m=mode: self._draw_mode_icon(d, m, cx, cy, sz, col))
        )
        icon_cx = col_x0 + icon_col_w / 2  # both icons share this x - vertical alignment
        # Mode icon, centered on the label/value pair's own height.
        icon_fn(draw, icon_cx, margin_y + group_h / 2, icon_size, color)
        # Clock icon, directly below it, centered on the time line's
        # height - same icon_cx, so the two icons line up vertically.
        time_y = margin_y + group_h + row_gap
        self._draw_clock_icon(draw, icon_cx, time_y + time_row_h / 2, clock_icon_size, color)

        # Text column: one shared left edge for every line, including
        # the time line - no icon glued to it here anymore.
        text_x = col_x0 + icon_col_w + icon_col_gap
        y = margin_y
        draw.text((text_x, y), label_text, font=font_label, fill=color)
        y += label_ascent + line_gap
        draw.text((text_x, y), dist_s, font=font_value, fill=color)
        draw.text(
            (text_x, time_y + (time_row_h - time_ascent) / 2), dur_s, font=font_time, fill=color,
        )

    def create_summary_card_columns(
        self,
        distance_km: float,
        duration_seconds: float,
        mode_breakdown: Optional[Dict[str, float]] = None,
        mode_duration: Optional[Dict[str, float]] = None,
        out_scale: float = 1.0,
        total_km: Optional[float] = None,
        total_seconds: Optional[float] = None,
        banner_theme: bool = False,
    ) -> np.ndarray:
        """Fourth summary-card template: still split into columns like
        create_summary_card's own multi-column layout, colored per mode like
        create_summary_card_stacked. Each mode-column is itself two columns
        (the user's own sketch, refined over four rounds): a fixed-width
        icon column on the left holding BOTH icons — the mode icon on top
        (sized to span the label+value pair beside it) and the clock icon
        below it, each horizontally centered on the SAME vertical line so
        the two icons align — then a text column on the right where the
        label, value and time all share one left edge (the time line is
        just its own text now, no icon glued to it — that icon lives in the
        icon column instead). Weights differ per line: label Regular, value
        ExtraBold, time Bold (tuning.SUMMARY_CARD_LABEL_FONT_SIZE/
        VALUE_FONT_SIZE size the label/value; time reuses the label size).
        A single mode (or no breakdown at all) is one column, no dividers,
        in plain text color; more than one mode gets one column per mode
        plus a Total column, colored via _mode_accent / self.ui["card_text"]
        — same reasoning create_summary_card's own single-vs-multi split
        uses. `total_km`/`total_seconds` override the Total column (a leg's
        card shows the whole trip still ahead there).

        `banner_theme`: the card as one more of the overview's accent pills — accent ground,
        cream content, the headline's own corner — for a frame where it sits beside the
        headline and the totals chip rather than alone in a corner of the map. The per-mode
        accents go with it: a blue ferry on an accent ground fights the ground."""
        scale = 2
        total_dist = distance_km if total_km is None else total_km
        total_dur = duration_seconds if total_seconds is None else total_seconds
        font_label, font_value, font_time = self._columns_fonts(scale)
        columns = self._columns_spec(
            distance_km, duration_seconds, mode_breakdown, mode_duration, total_dist, total_dur, banner_theme,
            remaining=total_km is not None,  # a leg's card: its "total" is the trip still ahead
        )

        label_ascent, _ = font_label.getmetrics()
        value_ascent, _ = font_value.getmetrics()
        time_ascent, _ = font_time.getmetrics()
        line_gap = 6 * scale
        row_gap = 10 * scale  # between the label/value pair and the time line
        group_h = label_ascent + line_gap + value_ascent  # the mode icon spans exactly this
        icon_size = group_h
        clock_icon_size = label_ascent  # matches the label line's own height
        time_row_h = max(clock_icon_size, time_ascent)
        content_h = group_h + row_gap + time_row_h
        icon_col_w = icon_size  # widest of the two icons - both center on this column
        icon_col_gap = 14 * scale
        col_pad_x = 26 * scale
        margin_y = 22 * scale
        border_rgba = tuple(reversed(self.card_border_color)) + (255,)

        rows, fixed_text_w = self._column_rows(columns, font_label, font_value, font_time)
        col_w = icon_col_w + icon_col_gap + max(fixed_text_w, *(r[5] for r in rows)) + col_pad_x * 2
        card_w_px = int(col_w * len(rows))
        card_h_px = int(content_h + margin_y * 2)

        card_radius_px = (10 if banner_theme else 18) * scale
        canvas = self._paint_columns_card(
            rows, (card_w_px, card_h_px, card_radius_px, col_w, scale), (font_label, font_value, font_time),
            (label_ascent, time_ascent, line_gap, row_gap, group_h, icon_size, clock_icon_size, time_row_h,
             icon_col_w, icon_col_gap, col_pad_x, margin_y),
            banner_theme, border_rgba,
        )

        canvas = self._add_card_shadow(
            canvas, card_radius_px,
            self.ui["pill_bg"][:3] if banner_theme else border_rgba[:3], scale,
        )
        w, h = round(canvas.size[0] * out_scale / scale), round(canvas.size[1] * out_scale / scale)
        canvas = canvas.resize((w, h), Image.Resampling.LANCZOS)
        return np.array(canvas)[:, :, [2, 1, 0, 3]]

    def create_summary_card_circles(
        self,
        distance_km: float,
        duration_seconds: float,
        mode_breakdown: Optional[Dict[str, float]] = None,
        mode_duration: Optional[Dict[str, float]] = None,
        out_scale: float = 1.0,
        total_km: Optional[float] = None,
        total_seconds: Optional[float] = None,
    ) -> np.ndarray:
        """Fifth summary-card template: no card behind it at all. One disc per travel mode
        holding that mode's icon, and under each disc two chips, its distance and its time,
        with the whole trip's own disc last. For a frame whose corners are already accent
        pills (the headline, the totals chip): a sixth panel there would be one too many, and
        these discs read as part of the map instead."""
        scale = 2
        total_dist = distance_km if total_km is None else total_km
        total_dur = duration_seconds if total_seconds is None else total_seconds
        font = self._load_font(
            self.FONT_CANDIDATES_BOLD, tuning.SUMMARY_CARD_LABEL_FONT_SIZE * scale
        )
        mode_duration = mode_duration or {}
        columns = [
            (mode, dist, mode_duration.get(mode, 0.0))
            for mode, dist in sorted((mode_breakdown or {}).items(), key=lambda kv: -kv[1])
        ]
        columns.append(("total", total_dist, total_dur))

        disc_d = 112 * scale
        chip_h = 38 * scale
        chip_pad_x = 14 * scale
        chip_gap = 7 * scale
        disc_gap = 13 * scale
        col_gap = 26 * scale
        probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

        rows = []  # (mode, [chip texts], column width)
        for mode, dist, dur in columns:
            chips = [_fmt_distance(dist), self._fmt_duration(dur)]
            widest = max(probe.textlength(c, font=font) for c in chips) + chip_pad_x * 2
            rows.append((mode, chips, max(disc_d, widest)))

        card_w = int(sum(r[2] for r in rows) + col_gap * (len(rows) - 1))
        card_h = int(disc_d + disc_gap + chip_h * 2 + chip_gap)
        canvas = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
        self._draw_disc_columns(
            ImageDraw.Draw(canvas), probe, font, rows, (disc_d, chip_h, chip_gap, disc_gap, col_gap)
        )

        w, h = round(card_w * out_scale / scale), round(card_h * out_scale / scale)
        canvas = canvas.resize((w, h), Image.Resampling.LANCZOS)
        return np.array(canvas)[:, :, [2, 1, 0, 3]]

    def _columns_fonts(self, scale: int) -> tuple:
        """(label Regular, value ExtraBold, time Bold) fonts of the columns card."""
        font_label = self._load_font(
            self.FONT_CANDIDATES_REGULAR, tuning.SUMMARY_CARD_LABEL_FONT_SIZE * scale
        )
        font_value = self._load_font(
            self.FONT_CANDIDATES_EXTRABOLD, tuning.SUMMARY_CARD_VALUE_FONT_SIZE * scale
        )
        font_time = self._load_font(
            self.FONT_CANDIDATES_BOLD, tuning.SUMMARY_CARD_LABEL_FONT_SIZE * scale
        )
        return font_label, font_value, font_time

    def _paint_columns_card(self, rows: list, size: tuple, fonts: tuple, metrics: tuple, banner_theme: bool, border_rgba: tuple):
        """The columns card's rounded body with every stat column (and its divider) drawn on it."""
        card_w_px, card_h_px, card_radius_px, col_w, scale = size
        canvas, draw = self._rounded_card(
            card_w_px, card_h_px, card_radius_px,
            self.ui["pill_bg"] if banner_theme else self.ui["card_bg"],
            None if banner_theme else (border_rgba if self.card_border_thickness else None),
            0 if banner_theme else self.card_border_thickness * scale,
        )

        divider_color = (
            (*self.ui["pill_text"][:3], 90) if banner_theme else self.ui["divider"]
        )
        for i, row in enumerate(rows):
            self._draw_stat_column(draw, i, row, col_w, card_h_px, scale, fonts, metrics, divider_color)
        return canvas

    def _column_rows(self, columns: list, font_label, font_value, font_time) -> Tuple[list, float]:
        """((label, mode, dist_str, dur_str, color, text_w) per column, the fixed text width the card pads to)."""
        probe_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        rows = []
        for label, mode, dist, dur, color in columns:
            dist_s, dur_s = _fmt_distance(dist), self._fmt_duration(dur)
            text_w = max(
                probe_draw.textlength(label, font=font_label),
                probe_draw.textlength(dist_s, font=font_value),
                probe_draw.textlength(dur_s, font=font_time),
            )
            rows.append((label, mode, dist_s, dur_s, color, text_w))

        # Fixed width: pad to sample strings so the card doesn't resize with its values.
        fixed_text_w = max(
            probe_draw.textlength(tuning.SUMMARY_CARD_FIXED_DISTANCE_SAMPLE, font=font_value),
            probe_draw.textlength(video_text.current_labels()["duration_sample"], font=font_time),
        )
        return rows, fixed_text_w

    def _draw_disc_columns(self, draw, probe, font, rows: list, sizes: tuple) -> None:
        """Each travel mode's disc with its icon, and under it the distance and time chips."""
        disc_d, chip_h, chip_gap, disc_gap, col_gap = sizes
        ascent = sum(font.getmetrics())
        # The disc and the chips share the card's own ground/ink pair, so the icon reads
        # against the disc whichever theme is on.
        ink = tuple(self.ui["card_text"][:3])
        disc_fill = tuple(self.ui["card_bg"][:3]) + (205,)
        chip_fill = tuple(self.ui["card_bg"][:3]) + (238,)

        x = 0
        for mode, chips, col_w in rows:
            cx = x + col_w / 2
            draw.ellipse([cx - disc_d / 2, 0, cx + disc_d / 2, disc_d], fill=disc_fill)
            if mode == "total":
                self._draw_total_icon(draw, cx, disc_d / 2, disc_d * 0.5, ink + (235,))
            else:
                self._draw_mode_icon(draw, mode, cx, disc_d / 2, disc_d * 0.5, ink + (235,))
            y = disc_d + disc_gap
            for text in chips:
                tw = probe.textlength(text, font=font)
                draw.rounded_rectangle(
                    [cx - col_w / 2, y, cx + col_w / 2, y + chip_h], radius=chip_h / 2, fill=chip_fill,
                )
                draw.text((cx - tw / 2, y + (chip_h - ascent) / 2), text, font=font, fill=ink)
                y += chip_h + chip_gap
            x += col_w + col_gap

    def create_summary_card_taskbar(
        self,
        distance_km: float,
        duration_seconds: float,
        mode_breakdown: Optional[Dict[str, float]] = None,
        mode_duration: Optional[Dict[str, float]] = None,
        min_card_width: int = 260,
        title: Optional[str] = None,
        max_title_width: int = 420,
    ) -> np.ndarray:
        """Second summary-card template: a narrow vertical list styled like
        a Windows taskbar/notification flyout (icon-badge header row, then
        one label+value row per travel mode, ending in a Total row) rather
        than create_summary_card's wide horizontal pill/column layout.
        Sibling to create_summary_card, not a replacement for it — pick
        between the two via GraphicsEngine.summary_card_style (see
        tuning.DEFAULT_SUMMARY_CARD_STYLE / job_config.json's
        settings.summary_card_style) through render_summary_card, the
        shared dispatch point every call site should use instead of
        calling either template directly.

        Width is measured from the actual longest row (label + value text)
        rather than a fixed card_width — a fixed width let a long value
        string ("10.7 km · 3 hr 35 min") run past the card edge or
        collide with its own row's label/icon on the left.

        `title` overrides the default "taskbar_card_title" header text
        (e.g. a per-leg "{from} → {to}" route line instead of the trip-
        wide "旅の概要") — truncated with an ellipsis past
        `max_title_width` px so an unusually long pair of place names
        can't blow the whole card out to an awkward width."""
        # Same "skip the redundant Total column for a single mode" rule as
        # create_summary_card — a lone mode's own row already IS the total.
        rows = self._summary_columns(distance_km, duration_seconds, mode_breakdown, mode_duration)

        # Light "white glass" flyout — same family as create_summary_card's
        # own light palette (this project's actual card theme) rather than
        # the dark mica look this template first shipped with.
        bg_color = self.ui["card_bg"]
        border_rgba = tuple(reversed(self.card_border_color)) + (255,)

        scale = 2
        font_header = self._load_font(self.FONT_CANDIDATES_BOLD, 22 * scale)
        # Bold, not regular — same reasoning as create_summary_card's own
        # font_label (see its comment): a mode label drawn in its own
        # accent color (rather than plain text-color gray) needs the extra
        # weight to stay legible against the card's light background,
        # especially for a pale accent like the walking mode's yellow.
        font_label = self._load_font(
            self.FONT_CANDIDATES_BOLD, tuning.SUMMARY_CARD_LABEL_FONT_SIZE * scale
        )
        font_value = self._load_font(
            self.FONT_CANDIDATES_BOLD, int(tuning.SUMMARY_CARD_LABEL_FONT_SIZE * 1.15) * scale
        )

        pad_x = 20 * scale
        header_h = 52 * scale
        row_h = 46 * scale
        icon_size = 22 * scale
        radius = 14 * scale
        badge_r = 9 * scale
        text_gap = 12 * scale
        # Minimum breathing room between a row's label (left) and its value
        # (right) — without this floor, a wide value could still be laid
        # out flush against a barely-clipped label at the card's own
        # measured minimum width.
        label_value_gap = 16 * scale

        row_texts, content_w_px = self._taskbar_row_texts(
            rows, font_label, font_value, pad_x + icon_size + text_gap, label_value_gap, pad_x
        )
        title_text, title_w = self._taskbar_title(title, max_title_width * scale, font_header)
        header_w_px = pad_x + badge_r * 2 + text_gap + title_w + pad_x
        card_w_px = max(min_card_width * scale, content_w_px, header_w_px)

        card_h_px = int(header_h + row_h * len(rows) + 14 * scale)
        canvas, draw = self._rounded_card(
            card_w_px, card_h_px, radius, bg_color,
            border_rgba if self.card_border_thickness else None, max(1, self.card_border_thickness) * scale,
        )
        self._draw_taskbar_header(draw, title_text, font_header, pad_x, header_h, badge_r, text_gap, card_w_px, scale)
        self._draw_taskbar_rows(
            draw, row_texts, (font_label, font_value), (pad_x, header_h, row_h, icon_size, text_gap), card_w_px, scale
        )

        canvas = self._add_card_shadow(canvas, radius, border_rgba[:3], scale)
        w_px = canvas.size[0] // scale
        h_px = canvas.size[1] // scale
        canvas = canvas.resize((w_px, h_px), Image.Resampling.LANCZOS)
        return np.array(canvas)[:, :, [2, 1, 0, 3]]

    def _taskbar_row_texts(
        self, rows: list, font_label, font_value, left: float, label_value_gap: float, pad_x: float,
    ) -> Tuple[List[Tuple[str, str, Tuple, str]], float]:
        """((label, "distance · duration", accent, mode) per row, the width the longest row needs)."""
        probe_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        row_texts: List[Tuple[str, str, Tuple, str]] = []
        content_w_px = 0.0
        for label, mode, dist, dur in rows:
            distance_str = f"{dist * 1000:.0f} m" if dist < 1 else f"{dist:.1f} km"
            dur_str = self._format_duration_ja(dur) if dur > 0 else "--"
            value_str = f"{distance_str} · {dur_str}"
            col_accent = self._mode_accent(mode)
            row_texts.append((label, value_str, col_accent, mode))
            label_w = probe_draw.textlength(label, font=font_label)
            value_w = probe_draw.textlength(value_str, font=font_value)
            row_w = left + label_w + label_value_gap + value_w + pad_x
            content_w_px = max(content_w_px, row_w)
        return row_texts, content_w_px

    def _taskbar_title(self, title: Optional[str], max_title_w_px: float, font_header) -> Tuple[str, float]:
        """(the header text, its width), cut with an ellipsis past `max_title_w_px`."""
        probe_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        title_text = title if title is not None else self.summary_card_labels["taskbar_card_title"]
        title_w = probe_draw.textlength(title_text, font=font_header)
        if title_w > max_title_w_px:
            while title_text and probe_draw.textlength(title_text + "…", font=font_header) > max_title_w_px:
                title_text = title_text[:-1]
            title_text += "…"
            title_w = probe_draw.textlength(title_text, font=font_header)
        return title_text, title_w

    def _draw_taskbar_header(
        self, draw, title_text: str, font_header, pad_x: int, header_h: int, badge_r: int, text_gap: int,
        card_w_px: float, scale: int,
    ) -> None:
        """Header: small route badge + title, like a notification's own app-icon-and-name row."""
        # BGR, like every other color in job_config.json's settings — reversed here since the canvas is
        # RGBA->BGR swapped as a whole at the end (same convention create_summary_card uses).
        accent = tuple(reversed(self.line_color)) + (255,)
        badge_cx, badge_cy = pad_x + badge_r, header_h / 2
        draw.ellipse(
            [badge_cx - badge_r, badge_cy - badge_r, badge_cx + badge_r, badge_cy + badge_r],
            fill=accent,
        )
        self._draw_ruler_icon(draw, badge_cx, badge_cy, int(badge_r * 1.1), (255, 255, 255, 255))
        title_x = badge_cx + badge_r + text_gap
        header_ascent, _ = font_header.getmetrics()
        draw.text(
            (title_x, header_h / 2 - header_ascent / 2),
            title_text, font=font_header, fill=self.ui["card_text"],
        )
        draw.line(
            [(pad_x, header_h), (card_w_px - pad_x, header_h)],
            fill=self.ui["divider"], width=max(1, scale),
        )

    def _draw_taskbar_rows(self, draw, row_texts: list, fonts: tuple, sizes: tuple, card_w_px: float, scale: int) -> None:
        """One label + value row per mode, each in its accent color, with dividers between them."""
        font_label, font_value = fonts
        pad_x, header_h, row_h, icon_size, text_gap = sizes
        divider_color = self.ui["divider"]
        y = header_h
        for i, (label, value_str, col_accent, mode) in enumerate(row_texts):
            row_top = y
            row_cy = row_top + row_h / 2
            icon_cx = pad_x + icon_size / 2
            if mode == "total":
                self._draw_total_icon(draw, icon_cx, row_cy, icon_size, col_accent)
            else:
                self._draw_mode_icon(draw, mode, icon_cx, row_cy, icon_size, col_accent)

            text_x = pad_x + icon_size + text_gap
            label_ascent, _ = font_label.getmetrics()
            # Label text now shares its row's own accent color (same one
            # the icon and the route line for that mode use) rather than
            # a flat gray — a row's label previously didn't visually tie
            # back to its icon/line color at all, only the value did (and
            # only for the total row).
            draw.text(
                (text_x, row_cy - label_ascent / 2), label, font=font_label,
                fill=col_accent,
            )

            value_w = draw.textlength(value_str, font=font_value)
            value_ascent, _ = font_value.getmetrics()
            draw.text(
                (card_w_px - pad_x - value_w, row_cy - value_ascent / 2),
                value_str, font=font_value, fill=col_accent,
            )

            if i < len(row_texts) - 1:
                draw.line(
                    [(pad_x, row_top + row_h), (card_w_px - pad_x, row_top + row_h)],
                    fill=divider_color, width=max(1, scale),
                )
            y += row_h

    def render_summary_card(self, card_size: Optional[Tuple[int, int]] = None, **kwargs) -> np.ndarray:
        """Shared dispatch point for every summary-card call site: picks
        create_summary_card (the original wide pill/column card), the
        narrow notification-flyout create_summary_card_taskbar, the
        minimal two-row create_summary_card_stacked (icon + number, no
        labels), or create_summary_card_columns (columns again, colored per
        mode, but a tall icon spanning the label+value inside each one —
        the user's own sketch), based on self.summary_card_style, which
        GraphicsEngine sets from job_config.json's settings.summary_card_style
        (default "glass" — see tuning.DEFAULT_SUMMARY_CARD_STYLE). Call
        sites should use this instead of calling any create_summary_card*
        method directly, so a project can opt into a different template
        without every call site needing its own if/else."""
        style = getattr(self, "summary_card_style", tuning.DEFAULT_SUMMARY_CARD_STYLE)
        out_scale = kwargs.pop("out_scale", 1.0)
        banner_theme = kwargs.pop("banner_theme", False)
        if style == "circles":
            kwargs.pop("title", None)
            kwargs.pop("max_title_width", None)
            return self.create_summary_card_circles(out_scale=out_scale, **kwargs)
        if style == "columns":
            kwargs.pop("title", None)
            kwargs.pop("max_title_width", None)
            return self.create_summary_card_columns(
                out_scale=out_scale, banner_theme=banner_theme, **kwargs)
        kwargs.pop("total_km", None)
        kwargs.pop("total_seconds", None)
        card =self._render_summary_card_style(style, card_size, **kwargs)
        if out_scale != 1.0:
            h, w = card.shape[:2]
            card = np.array(Image.fromarray(card).resize(
                (round(w * out_scale), round(h * out_scale)), Image.Resampling.LANCZOS))
        return card

    def _render_summary_card_style(self, style: str, card_size, **kwargs) -> np.ndarray:
        if style == "circles":
            for key in ("title", "max_title_width", "card_size", "banner_theme"):
                kwargs.pop(key, None)
            return self.create_summary_card_circles(**kwargs)
        if style == "taskbar":
            if card_size is not None:
                kwargs.setdefault("min_card_width", card_size[0])
            return self.create_summary_card_taskbar(**kwargs)
        if style == "stacked":
            kwargs.pop("title", None)
            kwargs.pop("max_title_width", None)
            return self.create_summary_card_stacked(**kwargs)
        # create_summary_card (the pill/column style) has no concept of a
        # custom header title — a caller passing `title` (e.g. a per-leg
        # "{from} → {to}" route line) only meant it for the taskbar
        # template; silently drop it here rather than raising a
        # TypeError for an unexpected keyword.
        kwargs.pop("title", None)
        kwargs.pop("max_title_width", None)
        if card_size is not None:
            kwargs["card_size"] = card_size
        return self.create_summary_card(**kwargs)

    def composite_card_on_frame(
        self,
        frame: np.ndarray,
        card_bgra: np.ndarray,
        alpha: float,
        margin: int = 20,
        corner: str = "bottom_right",
        slide_offset_y: float = 0.0,
        margin_y: Optional[int] = None,
    ) -> np.ndarray:
        """`margin_y` (default: `margin`) is the gap to the top/bottom edge, which may be negative
        to cancel the card image's own transparent padding."""
        out = frame.copy()
        h, w = out.shape[:2]
        ch, cw = card_bgra.shape[:2]
        # [NOTE] [Animation] Downscales the card (preserving aspect ratio) only if it wouldn't otherwise fit within the frame minus margins, rather than clipping it.
        if cw > w - 2 * margin or ch > h - 2 * margin:
            shrink = min((w - 2 * margin) / cw, (h - 2 * margin) / ch)
            card_bgra = cv2.resize(
                card_bgra,
                (max(1, int(cw * shrink)), max(1, int(ch * shrink))),
                interpolation=cv2.INTER_AREA,
            )
            ch, cw = card_bgra.shape[:2]
        x = margin if "left" in corner else w - cw - margin
        edge_y = margin if margin_y is None else margin_y
        y = edge_y if "top" in corner else h - ch - edge_y
        # Positive slide_offset_y pushes the card DOWN below its resting
        # spot — animating this from a large value down to 0 (and back up
        # on exit) is the "pop up from the bottom" entrance/exit, without
        # needing a separate drawing path: it's the exact same composite,
        # just offset, so the fade above still applies identically.
        y += int(slide_offset_y)
        x0, y0 = x, y
        # A slid-down card can partially (or fully) fall below the frame
        # — clip the blend region to what's actually still on-screen
        # rather than letting a negative-height/out-of-bounds slice
        # silently no-op or raise.
        src_y0 = max(0, -y0)
        src_x0 = max(0, -x0)
        dst_y0 = max(0, y0)
        dst_x0 = max(0, x0)
        blend_h = min(ch, h - dst_y0) - src_y0
        blend_w = min(cw, w - dst_x0) - src_x0
        if blend_h <= 0 or blend_w <= 0:
            return out
        card_bgra = card_bgra[src_y0 : src_y0 + blend_h, src_x0 : src_x0 + blend_w]
        _blend_card(out, card_bgra, dst_x0, dst_y0, alpha)
        return out

    def _headline_run(self, measure, font, steps: Sequence[Tuple[str, str]], chip_d: int, gap: float) -> List[Tuple[str, str, float]]:
        """The headline's stretch as (kind, text, width) pieces: each place behind its glyph chip, arrows between."""
        arrow = "  →  "
        run: List[Tuple[str, str, float]] = []  # (kind, text, width)
        for i, (glyph, name) in enumerate(steps):
            if i:
                run.append(("text", arrow, measure.textlength(arrow, font=font)))
            run.append(("chip", glyph, chip_d + gap / 2))
            run.append(("text", name, measure.textlength(name, font=font)))
        return run

    def _render_headline(self, title: str, steps: Sequence[Tuple[str, str]], font_px: int) -> Image.Image:
        """The headline panel itself (see route_headline_panel): the title strip, then the stretch's pieces."""
        scale = 2
        font = self._card_font(self.FONT_CANDIDATES_BOLD, font_px * scale)
        pad_x, pad_y, gap = int(20 * scale), int(10 * scale), int(10 * scale)
        measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        line_h = sum(font.getmetrics())  # the font's own line box, so a CJK name is not clipped
        chip_d = int(line_h * 1.15)

        run = self._headline_run(measure, font, steps, chip_d, gap)
        body_w = sum(w for _, _, w in run)
        title_w = measure.textlength(title, font=font) if title else 0
        card_w = int(max(title_w, body_w) + pad_x * 2)
        strip_h = int(line_h + pad_y * 2) if title else 0
        card_h = strip_h + (int(max(line_h, chip_d) + pad_y * 2) if run else 0)

        canvas = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        radius = 10 * scale
        draw.rounded_rectangle([0, 0, card_w - 1, card_h - 1], radius=radius, fill=self.ui["pill_bg"])
        if title:
            draw.rounded_rectangle(
                [0, 0, card_w - 1, strip_h - 1], radius=radius, fill=self.ui["pill_text"],
            )
            draw.text(
                ((card_w - title_w) / 2, pad_y), title, font=font, fill=self.ui["pill_bg"],
                anchor="la",
            )
        x, y = pad_x, strip_h + pad_y
        for kind, text, w in run:
            if kind == "chip":
                cy = y + (max(line_h, chip_d) - chip_d) / 2
                draw.ellipse([x, cy, x + chip_d, cy + chip_d], fill=self.ui["pill_text"])
                gw = measure.textlength(text, font=font)
                draw.text(
                    (x + (chip_d - gw) / 2, cy + (chip_d - line_h) / 2), text, font=font,
                    fill=self.ui["pill_bg"], anchor="la",
                )
            else:
                draw.text((x, y), text, font=font, fill=self.ui["pill_text"], anchor="la")
            x += w
        return canvas.resize((max(1, card_w // scale), max(1, card_h // scale)), Image.LANCZOS)

    def route_headline_panel(
        self, title: str, steps: Sequence[Tuple[str, str]], font_px: int = 22,
    ) -> Optional[Image.Image]:
        """The course overview's headline: the area's name on a light strip, and under it
        the stretch being traced, each place behind the glyph its own pin shows — "S 加太駅
        → 1 加太春日神社". `steps` is [(glyph, name), …]; with none, the strip alone.
        Memoized on its text, since it is composited onto every frame."""
        title, steps = drawable(title or ""), [(g, drawable(n)) for g, n in steps]
        if not title and not steps:
            return None
        cache = self.__dict__.setdefault("_route_headlines", {})
        key = (title, tuple(steps), font_px, self.theme)
        if key in cache:
            return cache[key]

        canvas = self._render_headline(title, steps, font_px)
        if len(cache) >= self._HUD_PANEL_CACHE_MAX:
            cache.clear()
        cache[key] = canvas
        return canvas

    def route_progress_rail_height(self, h: int) -> int:
        """How tall the bottom rail is, so a caller can keep its cards off it."""
        return int(round(h * 0.068))

    def _rail_geometry(self, w: int, h: int, margin: int, left: Optional[int] = None):
        """(rail height, cap diameter, bar top, bar height, left x, right x) of the bottom rail,
        shared by the track drawn per frame and the sprite of ticks and caps drawn once.
        `left` is where the rail starts (default: the margin)."""
        rail_h = self.route_progress_rail_height(h)
        cap_d = int(rail_h * 0.62)
        bar_h = max(4, int(rail_h * 0.16))
        bar_y = rail_h - cap_d // 2 - bar_h // 2  # the caps hang off the bar and still clear the edge
        return rail_h, cap_d, bar_y, bar_h, (margin if left is None else left) + cap_d // 2, w - margin - cap_d // 2

    def render_route_progress_rail(
        self, frame: np.ndarray, fraction: float,
        marks: Sequence[Tuple[float, str, Tuple[int, int, int]]],
        alpha: float = 1.0, margin: int = 32,
        mode: Optional[str] = None, frame_count: int = 0, left: Optional[int] = None,
    ) -> np.ndarray:
        """The whole route as one line across the foot of the frame: a tick per stop at its
        own share of the distance, the first and last behind their pin's glyph, and the
        trace's progress filled in from the left. `marks` is (fraction, glyph, BGR colour)
        per stop, in route order. The track and fill are drawn straight onto the frame (they
        change every frame); only the ticks and end caps are a cached sprite. `left` starts the
        rail further right (the course recap shrinks it beside the notices)."""
        if alpha <= 0 or not marks:
            return frame
        h, w = frame.shape[:2]
        rail_h, _, bar_y, bar_h, x0, x1 = self._rail_geometry(w, h, margin, left)
        top = h - margin - rail_h
        y = top + bar_y

        out = frame.copy()
        # self.ui holds RGB (it is mostly drawn through PIL); cv2 wants BGR.
        track = tuple(int(c) for c in reversed(self.ui["divider"][:3]))
        fill = tuple(int(c) for c in reversed(self.ui["pill_bg"][:3]))
        cv2.rectangle(out, (x0, y), (x1, y + bar_h), track, -1, cv2.LINE_AA)
        end = x0 + int(round((x1 - x0) * min(1.0, max(0.0, fraction))))
        if end > x0:
            cv2.rectangle(out, (x0, y), (end, y + bar_h), fill, -1, cv2.LINE_AA)

        # The traveler rides the head of the fill, shrunk to the rail: the same walker,
        # ferry or vehicle as on the map, so the two read as one journey.
        if mode and end > x0:
            icon = self.transport_icon_sprite(frame_count, 0.0, mode, int(rail_h * 0.62))
            if icon is not None:
                self.blit_sprite(out, icon, (icon.shape[1] // 2, icon.shape[0]), end, y + 1)

        sprite = self._progress_rail_sprite(w, h, tuple(marks), margin, left)
        roi = out[top:top + sprite.shape[0], 0:w].astype(np.float32)
        a = sprite[:, :, 3:].astype(np.float32) / 255.0
        out[top:top + sprite.shape[0], 0:w] = np.clip(
            sprite[:, :, :3].astype(np.float32) * a + roi * (1 - a) + 0.5, 0, 255).astype(np.uint8)
        # One fade for the whole rail, track and ticks together.
        return out if alpha >= 1.0 else cv2.addWeighted(out, alpha, frame, 1.0 - alpha, 0.0)

    def _progress_rail_sprite(
        self, w: int, h: int,
        marks: Tuple[Tuple[float, str, Tuple[int, int, int]], ...], margin: int,
        left: Optional[int] = None,
    ) -> np.ndarray:
        """BGRA strip of the rail's ticks and its two end caps (everything that never moves)."""
        cache = self.__dict__.setdefault("_progress_rails", {})
        key = (w, h, marks, margin, left, self.theme)
        if key in cache:
            return cache[key]
        rail_h, cap_d, bar_y, bar_h, x0, x1 = self._rail_geometry(w, h, margin, left)

        scale = 2
        canvas = Image.new("RGBA", (w * scale, rail_h * scale), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        font = self._card_font(self.FONT_CANDIDATES_BOLD, max(9, int(cap_d * 0.52)) * scale)
        small = self._card_font(self.FONT_CANDIDATES_BOLD, max(9, int(rail_h * 0.26)) * scale)
        label_h = sum(small.getmetrics())
        tick_top = label_h + int(3 * scale)
        cy = (bar_y + bar_h / 2) * scale
        # Two stops a few metres apart put their ticks all but on top of each other, so a
        # number that would land on the one before it slides right until it clears: the tick
        # stays at its true distance, only the number moves.
        last_right = -1e9
        gap = int(4 * scale)
        for i, (f, glyph, color) in enumerate(marks):
            x = (x0 + (x1 - x0) * min(1.0, max(0.0, f))) * scale
            rgb = tuple(int(c) for c in reversed(color[:3]))  # the caller passes BGR, PIL wants RGB
            if i in (0, len(marks) - 1):
                r = cap_d * scale / 2
                draw.ellipse([x - r, cy - r, x + r, cy + r], fill=rgb + (255,))
                tw = draw.textlength(glyph, font=font)
                draw.text((x - tw / 2, cy - font.size * 0.62), glyph, font=font, fill=self.ui["pill_text"])
                last_right = max(last_right, x + r)
                continue
            tw = max(1, int(2.5 * scale))
            draw.rectangle([x - tw / 2, tick_top, x + tw / 2, bar_y * scale], fill=rgb + (235,))
            if not glyph:
                continue
            lw = draw.textlength(glyph, font=small)
            lx = max(x - lw / 2, last_right + gap)
            if lx + lw > w * scale:
                continue
            draw.text((lx, 0), glyph, font=small, fill=rgb + (255,))
            last_right = lx + lw
        strip = np.array(canvas.resize((w, rail_h), Image.LANCZOS))[:, :, [2, 1, 0, 3]]
        if len(cache) >= self._HUD_PANEL_CACHE_MAX:
            cache.clear()
        cache[key] = strip
        return strip

    def route_totals_panel(
        self, distance_km: Optional[float], duration_seconds: Optional[float],
    ) -> Optional[Image.Image]:
        """The whole route's distance and time as one corner chip (the HUD panel the walk
        overview uses for what is LEFT, here for the totals, which never change)."""
        labels = getattr(self, "summary_card_labels", None) or video_text.current_labels()
        parts = []
        if distance_km is not None:
            parts.append(f"{distance_km * 1000:.0f} m" if distance_km < 1 else f"{distance_km:.1f} km")
        if duration_seconds is not None:
            parts.append(self._format_duration_ja(duration_seconds))
        return self._hud_panel(((labels["separator"].join(parts), 20, False),))

    def top_banner_width(self, text: str, font_px: int = 22) -> int:
        """Width in px of the pill render_top_banner draws for `text`."""
        text = drawable(text)
        scale = 2
        font = self._card_font(self.FONT_CANDIDATES_BOLD, font_px * scale)
        bbox = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox((0, 0), text, font=font)
        return (bbox[2] - bbox[0] + int(28 * font_px / 22) * scale * 2) // scale

    def _top_banner_card(self, text: str, font_px: int) -> np.ndarray:
        """The banner's pill as a finished BGRA card sized to fit `text` (supersampled, then downscaled)."""
        scale = 2  # supersampled for antialiased text/corners, then downscaled
        font = self._card_font(self.FONT_CANDIDATES_BOLD, font_px * scale)
        measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        bbox = measure.textbbox((0, 0), text, font=font)
        text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        pad = font_px / 22
        pad_x, pad_y = int(28 * pad) * scale, int(14 * pad) * scale
        card_w, card_h = text_w + pad_x * 2, text_h + pad_y * 2

        canvas = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle(
            [0, 0, card_w, card_h], radius=14 * scale, fill=self.ui["pill_bg"],
            outline=self.ui["divider"], width=max(1, scale),
        )
        # Same ground as the leg HUD's #hud-banner: pill_bg is the accent color itself now, so the text
        # is the theme's pill_text (white), not tuning.ACCENT_COLOR -- that would be invisible on itself.
        draw.text((pad_x - bbox[0], pad_y - bbox[1]), text, font=font, fill=self.ui["pill_text"])
        canvas = canvas.resize((max(1, card_w // scale), max(1, card_h // scale)), Image.LANCZOS)
        return np.array(canvas)[:, :, [2, 1, 0, 3]]

    def render_top_banner(
        self, frame: np.ndarray, text: str, alpha: float = 1.0, top_margin: int = 30, font_px: int = 22,
        align: str = "center", left_margin: int = 32,
    ) -> np.ndarray:
        """A dark rounded-pill caption centered near the top of the frame —
        the OpenCV/PIL equivalent of pydeckrecorder.pedestrian's own CSS HUD
        banner (same dark pill + bold white text), for the 2D
        spatial_renderer overview's dynamic "next stop" caption. Sized to
        fit `text` exactly (plus padding) rather than a fixed card_size,
        since the destination label's length varies waypoint to waypoint.
        `alpha` fades the whole pill (not just its own soft edges) the same
        way composite_card_on_frame's own `alpha` does for popup/summary
        cards, for a consistent fade in/out. `align="left"` docks it `left_margin` px from the left edge."""
        if not text:
            return frame

        card_bgra = self._top_banner_card(drawable(text), font_px)
        ch, cw = card_bgra.shape[:2]
        h, w = frame.shape[:2]
        x0 = max(0, left_margin) if align == "left" else max(0, (w - cw) // 2)
        y0 = max(0, top_margin)
        cw = min(cw, w - x0)
        ch = min(ch, h - y0)
        if cw <= 0 or ch <= 0:
            return frame
        card_bgra = card_bgra[:ch, :cw]

        out = frame.copy()
        _blend_card(out, card_bgra, x0, y0, alpha)
        return out

    # --- Overview HUD -------------------------------------------------------
    # The persistent corner panels of the 2D overview (title + mode times on
    # the left, what is left of the route + stop counter + next stop on the
    # right). Accent ground / white text, the same pill as render_top_banner,
    # so the HUD reads as part of the video's palette rather than a neutral
    # card. Drawn on every frame, so finished panels are memoized on their
    # own text (which only changes a few times a second).
    _HUD_PANEL_CACHE_MAX = 512
    _HUD_SCALE = 1.5  # the panels were too small to read on a 1080p frame

    def _hud_panel(
        self, rows: Tuple[Tuple[str, int, bool], ...], progress: Optional[float] = None,
    ) -> Optional[Image.Image]:
        """One rounded accent panel: `rows` of (text, font_px, dim), with an
        optional progress bar below them (None = no bar)."""
        rows = tuple(r for r in rows if r[0])
        if not rows:
            return None
        cache = self.__dict__.setdefault("_hud_panels", {})
        key = (rows, progress, self.theme)
        if key in cache:
            return cache[key]

        scale = 2
        k = scale * self._HUD_SCALE
        pad_x, pad_y, gap, bar_h = int(18 * k), int(11 * k), int(7 * k), int(4 * k)
        measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        laid = []
        for text, font_px, dim in rows:
            font = self._card_font(self.FONT_CANDIDATES_BOLD, font_px * scale)
            laid.append((drawable(text), font, measure.textbbox((0, 0), drawable(text), font=font), dim))
        text_w = max(b[2] - b[0] for _, _, b, _ in laid)
        text_h = sum(b[3] - b[1] for _, _, b, _ in laid) + gap * (len(laid) - 1)
        card_w = text_w + pad_x * 2
        card_h = text_h + pad_y * 2 + ((gap + bar_h) if progress is not None else 0)

        canvas = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle([0, 0, card_w, card_h], radius=14 * scale, fill=self.ui["pill_bg"])
        bright = self.ui["pill_text"]
        dimmed = (*bright[:3], 175)
        y = pad_y
        for text, font, bbox, dim in laid:
            draw.text((pad_x - bbox[0], y - bbox[1]), text, font=font, fill=dimmed if dim else bright)
            y += bbox[3] - bbox[1] + gap
        if progress is not None:
            inner = card_w - pad_x * 2
            draw.rounded_rectangle(
                [pad_x, y, pad_x + inner, y + bar_h], radius=bar_h // 2, fill=(*bright[:3], 70),
            )
            fill_w = int(inner * min(1.0, max(0.0, progress)))
            if fill_w > bar_h:
                draw.rounded_rectangle(
                    [pad_x, y, pad_x + fill_w, y + bar_h], radius=bar_h // 2, fill=bright,
                )
        canvas = canvas.resize((max(1, card_w // scale), max(1, card_h // scale)), Image.LANCZOS)
        if len(cache) >= self._HUD_PANEL_CACHE_MAX:
            cache.clear()
        cache[key] = canvas
        return canvas

    def render_overview_hud(
        self, frame: np.ndarray, title: Optional[str] = None,
        mode_duration: Optional[Dict[str, float]] = None,
        remaining_km: Optional[float] = None, remaining_seconds: Optional[float] = None,
        stops: Optional[Tuple[int, int]] = None, next_stop: Optional[str] = None,
        progress: Optional[float] = None, alpha: float = 1.0,
        top_margin: int = 20, side_margin: int = 32,
    ) -> np.ndarray:
        """The overview's persistent HUD. Left: the trip's name and how long
        each travel mode takes. Right: distance/time still ahead, how many
        stops are done, the stop being walked to, and a progress bar."""
        labels = getattr(self, "summary_card_labels", None) or video_text.current_labels()

        modes = ""
        if mode_duration:
            modes = labels["separator"].join(
                f"{self._mode_name_ja(m)} {self._format_duration_ja(s)}"
                for m, s in mode_duration.items() if s
            )
        left = self._hud_panel(((title or "", 20, False), (modes, 14, True)))

        remaining = ""
        if remaining_km is not None and remaining_seconds is not None:
            dist_s = f"{remaining_km * 1000:.0f} m" if remaining_km < 1 else f"{remaining_km:.1f} km"
            remaining = labels["overview_remaining_hud"].format(
                distance=dist_s, duration=self._format_duration_ja(remaining_seconds),
            )
        line2 = []
        if stops:
            line2.append(labels["overview_stops_hud"].format(n=stops[0], total=stops[1]))
        if next_stop:
            line2.append(labels["overview_next_hud"].format(name=next_stop))
        right = self._hud_panel(
            ((remaining, 20, False), (labels["separator"].join(line2), 14, True)),
            # Quantized: the bar only needs to move in visible steps, and a
            # unique fraction per frame would make the panel cache useless.
            progress=None if progress is None else round(min(1.0, max(0.0, progress)) * 200) / 200,
        )

        for canvas, from_left in ((left, True), (right, False)):
            if canvas is None:
                continue
            frame = self._composite_pill(
                frame, canvas, alpha, y_from_top=top_margin,
                **({"x_from_left": side_margin} if from_left else {"x_from_right": side_margin}),
            )
        return frame

    @staticmethod
    def _composite_pill(
        frame: np.ndarray, canvas: Image.Image, alpha: float,
        x_from_right: Optional[int] = None, x_from_left: Optional[int] = None,
        y_from_top: Optional[int] = None, y_from_bottom: Optional[int] = None,
    ) -> np.ndarray:
        """Shared alpha-composite of a finished RGBA PIL pill onto `frame`,
        anchored by whichever edge margin the caller gives (render_top_banner
        duplicates this inline for its own center/left anchoring; this is
        the edge-anchored case the new HUD chips share)."""
        card_bgra = np.array(canvas)[:, :, [2, 1, 0, 3]]
        ch, cw = card_bgra.shape[:2]
        h, w = frame.shape[:2]
        x0 = (w - x_from_right - cw) if x_from_right is not None else (x_from_left or 0)
        y0 = (h - y_from_bottom - ch) if y_from_bottom is not None else (y_from_top or 0)
        x0, y0 = max(0, x0), max(0, y0)
        cw, ch = min(cw, w - x0), min(ch, h - y0)
        if cw <= 0 or ch <= 0:
            return frame
        card_bgra = card_bgra[:ch, :cw]
        out = frame.copy()
        _blend_card(out, card_bgra, x0, y0, alpha)
        return out
