"""End-of-video summary stat card and generic card compositing."""

from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from services import tuning

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

# Shared light "glass" card palette (white background, dark text, muted
# gray labels) reused by every one of this file's summary/leg-bar card
# templates.
_CARD_BG_COLOR: Tuple[int, int, int, int] = (255, 255, 255, 240)
_CARD_TEXT_COLOR: Tuple[int, int, int, int] = (35, 35, 35, 255)
_CARD_LABEL_COLOR: Tuple[int, int, int, int] = (110, 110, 110, 255)
# Total column/row always reads in this same neutral dark color rather than
# borrowing whichever mode happens to be self.line_color, or one of the
# per-mode accent colors below - it summarizes across modes, not one of
# them, and every _mode_accent color is a vivid, fully-saturated hue
# (MODE_LINE_COLORS), so a plain near-black can never coincidentally match
# one, unlike a specific color pick could as modes are added. (This used to
# be a literal copy of walking's own BGR tuple, meant to read as blue once
# reversed for PIL - but this file draws directly in PIL's RGB space and
# never reverses it, so it rendered as orange instead, indistinguishable
# from ferry's own orange - see _mode_accent's own reversal for how a mode
# color is actually meant to make that BGR->RGB trip.)
_TOTAL_ACCENT_COLOR: Tuple[int, int, int, int] = _CARD_TEXT_COLOR


def merge_summary_card_labels(overrides: Optional[Dict]) -> Dict:
    """Merges a job_config.json settings.summary_card_labels override (any
    subset of keys, including a partial mode_name/mode_duration_label) over
    tuning.LABELS_JA's bundled/shared defaults — never mutates either
    input."""
    merged = dict(tuning.LABELS_JA)
    if not overrides:
        return merged
    for key, value in overrides.items():
        if key in _NESTED_LABEL_KEYS and isinstance(value, dict):
            merged[key] = {**merged.get(key, {}), **value}
        else:
            merged[key] = value
    return merged


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
        labels = getattr(self, "summary_card_labels", tuning.LABELS_JA)
        return labels["mode_duration_label"].get((mode or "").lower(), "時間")

    def _mode_name_ja(self, mode: str) -> str:
        labels = getattr(self, "summary_card_labels", tuning.LABELS_JA)
        return labels["mode_name"].get((mode or "").lower(), (mode or "").capitalize())

    @staticmethod
    def _format_duration_ja(seconds: float) -> str:
        if seconds < 60:
            return f"{max(1, int(round(seconds)))}秒"
        hrs, mins = divmod(int(round(seconds / 60)), 60)
        return f"{hrs}時間{mins:02d}分" if hrs else f"{mins}分"

    def _mode_accent(self, mode: str) -> Tuple:
        """Same color the route line itself uses for this mode
        (MODE_COLORS), pre-reversed so it comes out correct after the
        canvas-wide BGR swap at the end — ties each mode's stat
        column/row back to its own line color on the map instead of
        every one sharing one generic accent. "total" isn't a real
        travel mode with a line color of its own, so it always gets the
        same neutral dark color instead (_TOTAL_ACCENT_COLOR) — never one
        of the vivid per-mode accents, so it can't end up looking like
        whichever mode happens to also be that hue (walking's blue, say)."""
        if mode == "total":
            return _TOTAL_ACCENT_COLOR
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

    def _stopby_notice_layout(self, w: int, h: int):
        """Fonts, wrapped body lines and every box of the stop-by notice for
        a w x h frame: (scale, title_font, body_font, lines, ribbon box,
        body box). Shared by the drawing and by `stopby_notice_box`."""
        s = h / 1080.0
        margin = int(28 * s)
        title_font = self._load_font(self.FONT_CANDIDATES_BOLD, int(26 * s))
        body_font = self._load_font(self.FONT_CANDIDATES_REGULAR, int(21 * s))
        probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
        icon_d = int(26 * s)
        text_x0 = int(22 * s) + icon_d + int(14 * s)
        # As wide as its longest line (so the given line breaks hold), within
        # a sensible range; anything longer still wraps.
        longest = max(
            (probe.textlength(p, font=body_font) for p in tuning.STOPBY_NOTICE_BODY.split(chr(10))),
            default=0,
        )
        body_w = int(min(0.45 * w, max(360 * s, text_x0 + longest + 24 * s)))
        text_w = body_w - text_x0 - int(20 * s)
        lines: List[str] = []
        for paragraph in tuning.STOPBY_NOTICE_BODY.split(chr(10)):
            line = ""
            for ch in paragraph:
                if line and probe.textlength(line + ch, font=body_font) > text_w:
                    lines.append(line)
                    line = ""
                line += ch
            if line:
                lines.append(line)
        line_h = int(body_font.size * 1.45)
        body_h = int(18 * s) * 2 + line_h * len(lines)
        body_x0 = margin
        body_y1 = h - margin
        body_y0 = body_y1 - body_h
        title_w = int(probe.textlength(tuning.STOPBY_NOTICE_TITLE, font=title_font))
        ribbon_h = int(50 * s)
        ribbon_x0 = body_x0 - int(10 * s)
        ribbon_y1 = body_y0 + int(12 * s)  # overlaps the body card's top edge
        ribbon = (ribbon_x0, ribbon_y1 - ribbon_h, ribbon_x0 + title_w + int(44 * s), ribbon_y1)
        body = (body_x0, body_y0, body_x0 + body_w, body_y1)
        return s, title_font, body_font, lines, ribbon, body

    def stopby_notice_box(self, w: int, h: int) -> Tuple[int, int, int, int]:
        """(x0, y0, x1, y1) the notice covers, so cards can be kept off it."""
        _, _, _, _, ribbon, body = self._stopby_notice_layout(w, h)
        return (min(ribbon[0], body[0]), ribbon[1], max(ribbon[2], body[2]), body[3])

    def render_stopby_notice(
        self, frame: np.ndarray, alpha: float = 1.0,
        marker_color: Tuple[int, int, int] = tuning.STOPBY_PIN_COLOR,
    ) -> np.ndarray:
        """Bottom-left notice for the round stop-by markers: a ribbon with
        tuning.STOPBY_NOTICE_TITLE over a white rounded card with the marker
        itself and tuning.STOPBY_NOTICE_BODY (they are optional extras).
        `alpha` fades it as one unit. Colors are BGR, like the frame."""
        if alpha <= 0:
            return frame
        h, w = frame.shape[:2]
        s, title_font, body_font, lines, ribbon, body = self._stopby_notice_layout(w, h)
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
        ring = int(3 * s) + 1
        d.ellipse([ix - ring, iy - ring, ix + icon_d + ring, iy + icon_d + ring],
                  fill=(200, 200, 200, 255))
        d.ellipse([ix - ring + 1, iy - ring + 1, ix + icon_d + ring - 1, iy + icon_d + ring - 1],
                  fill=(255, 255, 255, 255))
        d.ellipse([ix, iy, ix + icon_d, iy + icon_d], fill=tuple(reversed(marker_color)) + (255,))
        tx = ix + icon_d + int(14 * s)
        ty = body[1] + int(18 * s) + int(4 * s)
        for line in lines:
            d.text((tx, ty), line, font=body_font, fill=(45, 45, 45, 255))
            ty += int(body_font.size * 1.45)

        # ribbon: a banded title with a folded tail under its left end
        rgb = tuple(reversed(tuning.STOPBY_NOTICE_RIBBON_COLOR))
        dark = tuple(int(c * 0.6) for c in rgb)
        fold = int(10 * s)
        d.polygon([(ribbon[0], ribbon[3]), (ribbon[0] + fold, ribbon[3]),
                   (ribbon[0] + fold, ribbon[3] + fold)], fill=dark + (255,))
        d.rounded_rectangle(ribbon, radius=int(10 * s), fill=rgb + (255,))
        tb = d.textbbox((0, 0), tuning.STOPBY_NOTICE_TITLE, font=title_font)
        d.text((ribbon[0] + int(22 * s), (ribbon[1] + ribbon[3]) // 2 - (tb[1] + tb[3]) // 2),
               tuning.STOPBY_NOTICE_TITLE, font=title_font, fill=(255, 255, 255, 255))

        if alpha < 1.0:
            a = layer.getchannel("A").point(lambda v: int(v * alpha))
            layer.putalpha(a)
        base = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA))
        base.alpha_composite(layer)
        return cv2.cvtColor(np.asarray(base), cv2.COLOR_RGBA2BGR)

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

        num_columns = len(columns)

        # A single mode gets a light, fully-rounded "pill" card — icon on
        # the left of each stat, its label/value stacked to the right —
        # matching the reference walking-time/distance design. Multi-mode
        # trips keep the denser dark glass card with one column per mode,
        # since that layout (mode header + big number + small time row)
        # doesn't fit the pill style once there's more than one stat pair.
        if num_columns == 1:
            bg_color = _CARD_BG_COLOR
            text_color, label_color = _CARD_TEXT_COLOR, _CARD_LABEL_COLOR
            icon_color = _CARD_TEXT_COLOR
            # BGR, like every other color in job_config.json's settings —
            # reversed here since the canvas is RGBA->BGR swapped as a
            # whole at the end (see _mode_accent's own comment).
            border_rgba = tuple(reversed(self.card_border_color)) + (255,)

            # Bold, not regular — Noto Sans's regular weight read as too
            # thin for this small a caption; size/color still separate it
            # from the (also bold) value below it.
            font_label = self._load_font(
                self.FONT_CANDIDATES_BOLD, tuning.SUMMARY_CARD_LABEL_FONT_SIZE * scale
            )
            font_value = self._load_font(
                self.FONT_CANDIDATES_BOLD, tuning.SUMMARY_CARD_VALUE_FONT_SIZE * scale
            )

            label, mode, dist, dur = columns[0]
            distance_str = f"{dist * 1000:.0f} m" if dist < 1 else f"{dist:.1f} km"
            dur_str = self._format_duration_ja(dur) if dur > 0 else "--"
            time_icon = lambda d, cx, cy, sz, col: self._draw_mode_icon(d, mode, cx, cy, sz, col)

            tiles = [
                (time_icon, self._mode_duration_label(mode), dur_str),
                (self._draw_ruler_icon, self.summary_card_labels["distance_label"], distance_str),
            ]

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
            canvas = Image.new("RGBA", (card_w_px, card_h_px), (0, 0, 0, 0))
            draw = ImageDraw.Draw(canvas)
            w, h = card_w_px // scale, card_h_px // scale

            card_radius_px = 22 * scale
            draw.rounded_rectangle(
                [0, 0, card_w_px - 1, card_h_px - 1],
                radius=card_radius_px,
                fill=bg_color,
                outline=border_rgba if self.card_border_thickness else None,
                width=self.card_border_thickness * scale,
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
        else:
            # Same light "residential" card theme as the single-mode pill
            # above (white glass, dark text, thin neutral border) rather
            # than a separate dark-glass/yellow-accent look — only the
            # layout (one column per mode) differs between the two.
            bg_color = _CARD_BG_COLOR
            text_color, label_color = _CARD_TEXT_COLOR, _CARD_LABEL_COLOR
            divider_color = (0, 0, 0, 30)
            # BGR, like every other color in job_config.json's settings —
            # reversed here since the canvas is RGBA->BGR swapped as a
            # whole at the end (see _mode_accent's own comment).
            border_rgba = tuple(reversed(self.card_border_color)) + (255,)
            accent = tuple(reversed(self.line_color)) + (255,)

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
            probe_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
            col_content_w = 0.0
            for label, mode, dist, dur in columns:
                distance_str = f"{dist * 1000:.0f} m" if dist < 1 else f"{dist:.1f} km"
                dur_str = self._format_duration_ja(dur) if dur > 0 else None
                widths = [
                    probe_draw.textlength(label, font=font_label),
                    probe_draw.textlength(distance_str, font=font_value_2),
                ]
                if dur_str:
                    widths.append(
                        stat_icon_d + icon_text_gap
                        + probe_draw.textlength(dur_str, font=font_label_time)
                    )
                col_content_w = max(col_content_w, *widths)

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
            w = card_w_px // scale
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

            for i, (label, mode, dist, dur) in enumerate(columns):
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
                    self._draw_ruler_icon(draw, col_cx, icon_cy, icon_size, text_color)
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

        # Same elevated-card shadow every popup card gets — see
        # _add_card_shadow's own comment on why the summary card was
        # missing one. Grows the canvas, so w/h are recomputed from its
        # new size before the final downscale.
        canvas = self._add_card_shadow(canvas, card_radius_px, border_rgba[:3], scale)
        w, h = canvas.size[0] // scale, canvas.size[1] // scale

        # [NOTE] [Animation] Downscales the 2x supersampled canvas for anti-aliasing, then swaps RGBA -> BGRA to match OpenCV's channel order.
        canvas = canvas.resize((w, h), Image.Resampling.LANCZOS)
        return np.array(canvas)[:, :, [2, 1, 0, 3]]

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
        _TOTAL_ACCENT_COLOR, the same color language create_summary_card's
        multi-column layout already uses, just as rows instead of columns."""
        scale = 2

        font_value = self._load_font(
            self.FONT_CANDIDATES_BOLD, tuning.SUMMARY_CARD_VALUE_FONT_SIZE * scale
        )

        def fmt_distance(km: float) -> str:
            return f"{km * 1000:.0f} m" if km < 1 else f"{km:.1f} km"

        def fmt_duration(seconds: float) -> str:
            return self._format_duration_ja(seconds) if seconds > 0 else "--"

        mode_duration = mode_duration or {}
        multi_mode = bool(mode_breakdown) and len(mode_breakdown) > 1
        icon_size = 34 * scale
        icon_text_gap = 16 * scale
        row_gap = 14 * scale
        margin_x, margin_y = 26 * scale, 20 * scale
        border_rgba = tuple(reversed(self.card_border_color)) + (255,)

        # blocks: a list of rows, each (icon_fn, text, color); block_sizes
        # says how many consecutive rows belong to the same mode, so the
        # (slightly larger) gap between blocks can be told apart from the
        # (smaller) gap between a mode's own distance/time rows.
        if multi_mode:
            blocks: List[List[Tuple]] = []
            for mode, dist in sorted(mode_breakdown.items(), key=lambda kv: -kv[1]):
                accent = self._mode_accent(mode)
                mode_icon = (lambda d, cx, cy, sz, col, m=mode: self._draw_mode_icon(d, m, cx, cy, sz, col))
                blocks.append([
                    (mode_icon, fmt_distance(dist), accent),
                    (self._draw_clock_icon, fmt_duration(mode_duration.get(mode, 0.0)), accent),
                ])
            blocks.append([
                (self._draw_ruler_icon, fmt_distance(distance_km), _TOTAL_ACCENT_COLOR),
                (self._draw_clock_icon, fmt_duration(duration_seconds), _TOTAL_ACCENT_COLOR),
            ])
            block_gap = 22 * scale
        else:
            blocks = [[
                (self._draw_walking_icon, fmt_distance(distance_km), _CARD_TEXT_COLOR),
                (self._draw_clock_icon, fmt_duration(duration_seconds), _CARD_TEXT_COLOR),
            ]]
            block_gap = row_gap

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
        canvas = Image.new("RGBA", (card_w_px, card_h_px), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)

        card_radius_px = 20 * scale
        draw.rounded_rectangle(
            [0, 0, card_w_px - 1, card_h_px - 1],
            radius=card_radius_px,
            fill=_CARD_BG_COLOR,
            outline=border_rgba if self.card_border_thickness else None,
            width=self.card_border_thickness * scale,
        )

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

        canvas = self._add_card_shadow(canvas, card_radius_px, border_rgba[:3], scale)
        w, h = canvas.size[0] // scale, canvas.size[1] // scale
        canvas = canvas.resize((w, h), Image.Resampling.LANCZOS)
        return np.array(canvas)[:, :, [2, 1, 0, 3]]

    def create_summary_card_columns(
        self,
        distance_km: float,
        duration_seconds: float,
        mode_breakdown: Optional[Dict[str, float]] = None,
        mode_duration: Optional[Dict[str, float]] = None,
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
        plus a Total column, colored via _mode_accent / _TOTAL_ACCENT_COLOR
        — same reasoning create_summary_card's own single-vs-multi split
        uses."""
        scale = 2
        font_label = self._load_font(
            self.FONT_CANDIDATES_REGULAR, tuning.SUMMARY_CARD_LABEL_FONT_SIZE * scale
        )
        font_value = self._load_font(
            self.FONT_CANDIDATES_EXTRABOLD, tuning.SUMMARY_CARD_VALUE_FONT_SIZE * scale
        )
        font_time = self._load_font(
            self.FONT_CANDIDATES_BOLD, tuning.SUMMARY_CARD_LABEL_FONT_SIZE * scale
        )

        def fmt_distance(km: float) -> str:
            return f"{km * 1000:.0f} m" if km < 1 else f"{km:.1f} km"

        def fmt_duration(seconds: float) -> str:
            return self._format_duration_ja(seconds) if seconds > 0 else "--"

        mode_duration = mode_duration or {}
        multi_mode = bool(mode_breakdown) and len(mode_breakdown) > 1
        if multi_mode:
            columns = [
                (self._mode_name_ja(mode), mode, dist, mode_duration.get(mode, 0.0), self._mode_accent(mode))
                for mode, dist in sorted(mode_breakdown.items(), key=lambda kv: -kv[1])
            ]
            columns.append((
                self.summary_card_labels["total_label"], "total", distance_km, duration_seconds,
                _TOTAL_ACCENT_COLOR,
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
                    self.summary_card_labels["total_label"], "total", distance_km, duration_seconds,
                    _TOTAL_ACCENT_COLOR,
                ),
            ]
        else:
            columns = [(
                self.summary_card_labels["distance_label"], "walking", distance_km, duration_seconds,
                _CARD_TEXT_COLOR,
            )]

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

        probe_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        rows = []  # (label, mode, dist_str, dur_str, color, text_w)
        for label, mode, dist, dur, color in columns:
            dist_s, dur_s = fmt_distance(dist), fmt_duration(dur)
            text_w = max(
                probe_draw.textlength(label, font=font_label),
                probe_draw.textlength(dist_s, font=font_value),
                probe_draw.textlength(dur_s, font=font_time),
            )
            rows.append((label, mode, dist_s, dur_s, color, text_w))

        col_w = icon_col_w + icon_col_gap + max(r[5] for r in rows) + col_pad_x * 2
        card_w_px = int(col_w * len(rows))
        card_h_px = int(content_h + margin_y * 2)

        canvas = Image.new("RGBA", (card_w_px, card_h_px), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        card_radius_px = 18 * scale
        draw.rounded_rectangle(
            [0, 0, card_w_px - 1, card_h_px - 1],
            radius=card_radius_px,
            fill=_CARD_BG_COLOR,
            outline=border_rgba if self.card_border_thickness else None,
            width=self.card_border_thickness * scale,
        )

        divider_color = (0, 0, 0, 30)
        for i, (label_text, mode, dist_s, dur_s, color, text_w) in enumerate(rows):
            col_x0 = col_w * i + col_pad_x
            if i > 0:
                x_div = col_w * i
                draw.line(
                    [(x_div, 18 * scale), (x_div, card_h_px - 18 * scale)],
                    fill=divider_color, width=2 * scale,
                )

            icon_fn = (
                self._draw_ruler_icon if mode == "total"
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

        canvas = self._add_card_shadow(canvas, card_radius_px, border_rgba[:3], scale)
        w, h = canvas.size[0] // scale, canvas.size[1] // scale
        canvas = canvas.resize((w, h), Image.Resampling.LANCZOS)
        return np.array(canvas)[:, :, [2, 1, 0, 3]]

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
        mode_duration = mode_duration or {}
        rows: List[Tuple[str, str, float, float]] = []
        if mode_breakdown:
            for mode, dist in sorted(mode_breakdown.items(), key=lambda kv: -kv[1]):
                rows.append(
                    (self._mode_name_ja(mode), mode.lower(), dist, mode_duration.get(mode, 0.0))
                )
        # Same "skip the redundant Total column for a single mode" rule as
        # create_summary_card — a lone mode's own row already IS the total.
        if not mode_breakdown or len(mode_breakdown) > 1:
            rows.append((self.summary_card_labels["total_label"], "total", distance_km, duration_seconds))

        # Light "white glass" flyout — same family as create_summary_card's
        # own light palette (this project's actual card theme) rather than
        # the dark mica look this template first shipped with.
        bg_color = _CARD_BG_COLOR
        header_color = _CARD_TEXT_COLOR
        label_color = _CARD_LABEL_COLOR
        value_color = _CARD_TEXT_COLOR
        divider_color = (0, 0, 0, 24)
        border_rgba = tuple(reversed(self.card_border_color)) + (255,)
        # BGR, like every other color in job_config.json's settings —
        # reversed here since the canvas is RGBA->BGR swapped as a whole
        # at the end (same convention create_summary_card uses).
        accent = tuple(reversed(self.line_color)) + (255,)

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

        probe_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        row_texts: List[Tuple[str, str, Tuple, float]] = []
        content_w_px = 0.0
        for label, mode, dist, dur in rows:
            distance_str = f"{dist * 1000:.0f} m" if dist < 1 else f"{dist:.1f} km"
            dur_str = self._format_duration_ja(dur) if dur > 0 else "--"
            value_str = f"{distance_str} · {dur_str}"
            col_accent = self._mode_accent(mode)
            row_texts.append((label, value_str, col_accent, mode))
            label_w = probe_draw.textlength(label, font=font_label)
            value_w = probe_draw.textlength(value_str, font=font_value)
            row_w = (
                pad_x + icon_size + text_gap + label_w
                + label_value_gap + value_w + pad_x
            )
            content_w_px = max(content_w_px, row_w)

        title_text = title if title is not None else self.summary_card_labels["taskbar_card_title"]
        title_w = probe_draw.textlength(title_text, font=font_header)
        max_title_w_px = max_title_width * scale
        if title_w > max_title_w_px:
            while title_text and probe_draw.textlength(title_text + "…", font=font_header) > max_title_w_px:
                title_text = title_text[:-1]
            title_text += "…"
            title_w = probe_draw.textlength(title_text, font=font_header)
        header_w_px = pad_x + badge_r * 2 + text_gap + title_w + pad_x
        card_w_px = max(min_card_width * scale, content_w_px, header_w_px)

        card_h_px = int(header_h + row_h * len(rows) + 14 * scale)
        canvas = Image.new("RGBA", (int(card_w_px), card_h_px), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)

        draw.rounded_rectangle(
            [0, 0, card_w_px - 1, card_h_px - 1],
            radius=radius,
            fill=bg_color,
            outline=border_rgba if self.card_border_thickness else None,
            width=max(1, self.card_border_thickness) * scale,
        )

        # Header: small route badge + title, like a notification's own
        # app-icon-and-name row.
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
            title_text, font=font_header, fill=header_color,
        )
        draw.line(
            [(pad_x, header_h), (card_w_px - pad_x, header_h)],
            fill=divider_color, width=max(1, scale),
        )

        y = header_h
        for i, (label, value_str, col_accent, mode) in enumerate(row_texts):
            row_top = y
            row_cy = row_top + row_h / 2
            icon_cx = pad_x + icon_size / 2
            if mode == "total":
                self._draw_ruler_icon(draw, icon_cx, row_cy, icon_size, col_accent)
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

        canvas = self._add_card_shadow(canvas, radius, border_rgba[:3], scale)
        w_px = canvas.size[0] // scale
        h_px = canvas.size[1] // scale
        canvas = canvas.resize((w_px, h_px), Image.Resampling.LANCZOS)
        return np.array(canvas)[:, :, [2, 1, 0, 3]]

    def create_leg_summary_bar(
        self,
        frame_width: int,
        distance_km: float,
        duration_seconds: float,
        mode: str,
        from_label: str = "",
        to_label: str = "",
        bar_height: int = 140,
    ) -> np.ndarray:
        """A per-residential-leg summary bar spanning the FULL video
        width — a lower-third strip, not a floating corner card like
        create_summary_card/create_summary_card_taskbar. Route
        ("{from} → {to}") on the left (a colored mode-icon badge, not a
        bare icon, matching the taskbar card's own badge language) and
        this leg's distance/time on the right — no border, no divider
        line, just whitespace and a soft shadow lifting it off the video
        below, for a minimal look rather than a boxed-in table row.

        Returned taller than `bar_height` alone — a soft shadow band sits
        above the actual bar within the same image — so callers should
        keep using the array's own .shape[0] (not `bar_height`) for
        placement/slide-distance math; composite_card_on_frame (margin=0)
        already does. The bar itself is exactly `frame_width` px wide,
        flush against both side edges once composited."""
        scale = 2
        pad_x = 40 * scale
        badge_r = 30 * scale
        text_gap = 22 * scale
        bar_h_px = bar_height * scale
        bar_w_px = frame_width * scale
        # A soft gradient shadow ABOVE the bar reads as "floating just
        # above the video" rather than a hard-edged box sitting on it —
        # replaces the old flat top border line entirely.
        shadow_h_px = 34 * scale

        bg_color = (255, 255, 255, 242)
        route_color = (28, 28, 30, 255)
        label_color = (120, 120, 126, 255)
        col_accent = tuple(reversed(self.MODE_COLORS.get(mode, self.line_color))) + (255,)

        font_route = self._load_font(self.FONT_CANDIDATES_BOLD, 36 * scale)
        font_value = self._load_font(
            self.FONT_CANDIDATES_BOLD, int(tuning.SUMMARY_CARD_LABEL_FONT_SIZE * 1.55) * scale
        )
        font_label = self._load_font(
            self.FONT_CANDIDATES_REGULAR, int(tuning.SUMMARY_CARD_LABEL_FONT_SIZE * 1.15) * scale
        )

        canvas = Image.new("RGBA", (bar_w_px, shadow_h_px + bar_h_px), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        for i in range(shadow_h_px):
            # Quadratic ease so the shadow is nearly invisible for most of
            # its span and only darkens right near the bar's own top edge
            # — a soft lift, not a visible gray stripe.
            t = (i + 1) / shadow_h_px
            shadow_alpha = int(26 * (t ** 2))
            draw.line([(0, i), (bar_w_px, i)], fill=(0, 0, 0, shadow_alpha))
        draw.rectangle([0, shadow_h_px, bar_w_px - 1, shadow_h_px + bar_h_px - 1], fill=bg_color)

        bar_cy = shadow_h_px + bar_h_px / 2

        # Left: colored circular badge (mode icon in white, like the
        # taskbar card's own header badge) + route text.
        badge_cx = pad_x + badge_r
        draw.ellipse(
            [badge_cx - badge_r, bar_cy - badge_r, badge_cx + badge_r, bar_cy + badge_r],
            fill=col_accent,
        )
        self._draw_mode_icon(draw, mode, badge_cx, bar_cy, int(badge_r * 1.15), (255, 255, 255, 255))

        route_text = f"{from_label}  →  {to_label}" if from_label and to_label else (from_label or to_label)
        if route_text:
            route_ascent, _ = font_route.getmetrics()
            draw.text(
                (badge_cx + badge_r + text_gap, bar_cy - route_ascent / 2),
                route_text, font=font_route, fill=route_color,
            )

        # Right: distance/time (bold, accent-colored) over this leg's
        # mode name (small, muted) — right-aligned, tight line spacing,
        # no divider needed since the two blocks already read as
        # distinct groups (icon+text vs. stacked numbers).
        distance_str = f"{distance_km * 1000:.0f} m" if distance_km < 1 else f"{distance_km:.1f} km"
        dur_str = self._format_duration_ja(duration_seconds) if duration_seconds > 0 else "--"
        value_str = f"{distance_str}  ·  {dur_str}"
        label_str = self._mode_name_ja(mode)

        value_w = draw.textlength(value_str, font=font_value)
        label_w = draw.textlength(label_str, font=font_label)
        right_x = bar_w_px - pad_x
        value_ascent, value_descent = font_value.getmetrics()
        label_ascent, _ = font_label.getmetrics()
        # Full ascent+descent (not just ascent) for the value's own line
        # height, plus real breathing room between the two rows — using
        # ascent alone for spacing ignored descenders (the "分"/"秒"
        # glyphs, the value row's own comma-like punctuation), which
        # left the label row crowding right up against them with almost
        # no visible gap.
        row_gap = 10 * scale
        block_h = value_ascent + value_descent + row_gap + label_ascent
        block_top = bar_cy - block_h / 2
        draw.text((right_x - value_w, block_top), value_str, font=font_value, fill=col_accent)
        draw.text(
            (right_x - label_w, block_top + value_ascent + value_descent + row_gap),
            label_str, font=font_label, fill=label_color,
        )

        out_h = bar_height + int(shadow_h_px / scale)
        canvas = canvas.resize((frame_width, out_h), Image.Resampling.LANCZOS)
        return np.array(canvas)[:, :, [2, 1, 0, 3]]

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
        if style == "taskbar":
            if card_size is not None:
                kwargs.setdefault("min_card_width", card_size[0])
            return self.create_summary_card_taskbar(**kwargs)
        if style == "stacked":
            kwargs.pop("title", None)
            kwargs.pop("max_title_width", None)
            return self.create_summary_card_stacked(**kwargs)
        if style == "columns":
            kwargs.pop("title", None)
            kwargs.pop("max_title_width", None)
            return self.create_summary_card_columns(**kwargs)
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
    ) -> np.ndarray:
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
        y = margin if "top" in corner else h - ch - margin
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
        x0, y0, cw, ch = dst_x0, dst_y0, blend_w, blend_h
        # Alpha-blends the card's own per-pixel alpha channel together with
        # the caller-supplied fade-in/out `alpha`, so the card can both have
        # soft edges and fade as a whole.
        card_bgr, card_alpha = (
            card_bgra[:, :, :3].astype(np.float32),
            (card_bgra[:, :, 3].astype(np.float32) / 255.0) * alpha,
        )
        roi = out[y0 : y0 + ch, x0 : x0 + cw].astype(np.float32)
        out[y0 : y0 + ch, x0 : x0 + cw] = (
            card_bgr * card_alpha[..., None] + roi * (1 - card_alpha[..., None])
        ).astype(np.uint8)
        return out

    def render_top_banner(
        self, frame: np.ndarray, text: str, alpha: float = 1.0, top_margin: int = 30,
    ) -> np.ndarray:
        """A dark rounded-pill caption centered near the top of the frame —
        the OpenCV/PIL equivalent of pydeckrecorder.pedestrian's own CSS HUD
        banner (same dark pill + bold white text), for the 2D
        spatial_renderer overview's dynamic "next stop" caption. Sized to
        fit `text` exactly (plus padding) rather than a fixed card_size,
        since the destination label's length varies waypoint to waypoint.
        `alpha` fades the whole pill (not just its own soft edges) the same
        way composite_card_on_frame's own `alpha` does for popup/summary
        cards, for a consistent fade in/out."""
        if not text:
            return frame

        scale = 2  # supersampled for antialiased text/corners, then downscaled
        font = self._load_font(self.FONT_CANDIDATES_BOLD, 22 * scale)
        measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        bbox = measure.textbbox((0, 0), text, font=font)
        text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        pad_x, pad_y = 28 * scale, 14 * scale
        card_w, card_h = text_w + pad_x * 2, text_h + pad_y * 2

        canvas = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle([0, 0, card_w, card_h], radius=card_h // 2, fill=(30, 34, 40, 225))
        draw.text((pad_x - bbox[0], pad_y - bbox[1]), text, font=font, fill=(255, 255, 255, 255))
        canvas = canvas.resize((max(1, card_w // scale), max(1, card_h // scale)), Image.LANCZOS)

        card_bgra = np.array(canvas)
        ch, cw = card_bgra.shape[:2]
        h, w = frame.shape[:2]
        x0 = max(0, (w - cw) // 2)
        y0 = max(0, top_margin)
        cw = min(cw, w - x0)
        ch = min(ch, h - y0)
        if cw <= 0 or ch <= 0:
            return frame
        card_bgra = card_bgra[:ch, :cw]

        out = frame.copy()
        card_bgr = card_bgra[:, :, :3].astype(np.float32)
        card_alpha = (card_bgra[:, :, 3].astype(np.float32) / 255.0) * alpha
        roi = out[y0 : y0 + ch, x0 : x0 + cw].astype(np.float32)
        out[y0 : y0 + ch, x0 : x0 + cw] = (
            card_bgr * card_alpha[..., None] + roi * (1 - card_alpha[..., None])
        ).astype(np.uint8)
        return out
