"""End-of-video summary stat card and generic card compositing."""

from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw

from services import tuning


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

    _MODE_DURATION_LABEL = {
        "walking": "歩く時間",
        "driving": "運転時間",
        "car": "運転時間",
        "ferry": "乗船時間",
        "airplane": "飛行時間",
    }

    @classmethod
    def _mode_duration_label(cls, mode: str) -> str:
        return cls._MODE_DURATION_LABEL.get((mode or "").lower(), "時間")

    @staticmethod
    def _format_duration_ja(seconds: float) -> str:
        if seconds < 60:
            return f"{max(1, int(round(seconds)))}秒"
        hrs, mins = divmod(int(round(seconds / 60)), 60)
        return f"{hrs}時間{mins:02d}分" if hrs else f"{mins}分"

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
                    (mode.capitalize(), mode.lower(), dist, mode_duration.get(mode, 0.0))
                )
        # A single mode's own column already IS the total (same distance,
        # same time) — appending "Total" too would just repeat it. Only
        # add it when there's more than one mode to actually total up, or
        # none at all (nothing else to show).
        if not mode_breakdown or len(mode_breakdown) > 1:
            columns.append(("Total", "total", distance_km, duration_seconds))

        n = len(columns)

        # A single mode gets a light, fully-rounded "pill" card — icon on
        # the left of each stat, its label/value stacked to the right —
        # matching the reference walking-time/distance design. Multi-mode
        # trips keep the denser dark glass card with one column per mode,
        # since that layout (mode header + big number + small time row)
        # doesn't fit the pill style once there's more than one stat pair.
        if n == 1:
            bg_color = (255, 255, 255, 240)
            text_color, label_color = (35, 35, 35, 255), (110, 110, 110, 255)
            icon_color = (35, 35, 35, 255)
            # BGR, like every other color in job_config.json's settings —
            # reversed here since the canvas is RGBA->BGR swapped as a
            # whole at the end (see mode_accent's own comment below).
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
                (self._draw_ruler_icon, "距離", distance_str),
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

            draw.rounded_rectangle(
                [0, 0, card_w_px - 1, card_h_px - 1],
                radius=22 * scale,
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
            bg_color = (255, 255, 255, 240)
            text_color, label_color = (35, 35, 35, 255), (110, 110, 110, 255)
            divider_color = (0, 0, 0, 30)
            # BGR, like every other color in job_config.json's settings —
            # reversed here since the canvas is RGBA->BGR swapped as a
            # whole at the end (see mode_accent's own comment below).
            border_rgba = tuple(reversed(self.card_border_color)) + (255,)
            accent = tuple(reversed(self.line_color)) + (255,)

            def mode_accent(mode: str) -> Tuple:
                """Same color the route line itself uses for this mode
                (MODE_COLORS), pre-reversed like `accent` above so it
                comes out correct after the canvas-wide BGR swap at the
                end — ties each mode's stat column back to its own line
                color on the map instead of every column sharing one
                generic accent. "total" isn't a real travel mode with a
                line color of its own, so it keeps the generic accent."""
                if mode == "total":
                    return accent
                return tuple(reversed(self.MODE_COLORS.get(mode, self.line_color))) + (255,)

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
                dur_str = self._format_duration_short(dur) if dur > 0 else None
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
            col_w = max((w * scale) / n, col_content_w + col_padding * 2)
            card_w_px, card_h_px = int(col_w * n), h * scale

            canvas = Image.new("RGBA", (card_w_px, card_h_px), (0, 0, 0, 0))
            draw = ImageDraw.Draw(canvas)
            draw.rounded_rectangle(
                [0, 0, card_w_px - 1, card_h_px - 1],
                radius=18 * scale,
                fill=bg_color,
                outline=border_rgba if self.card_border_thickness else None,
                width=self.card_border_thickness * scale,
            )
            w = card_w_px // scale
            label_gap = 6 * scale
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
                col_accent = mode_accent(mode)
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

                dur_str = self._format_duration_short(dur) if dur > 0 else None
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

        # [NOTE] [Animation] Downscales the 2x supersampled canvas for anti-aliasing, then swaps RGBA -> BGRA to match OpenCV's channel order.
        canvas = canvas.resize((w, h), Image.Resampling.LANCZOS)
        return np.array(canvas)[:, :, [2, 1, 0, 3]]

    def composite_card_on_frame(
        self,
        frame: np.ndarray,
        card_bgra: np.ndarray,
        alpha: float,
        margin: int = 20,
        corner: str = "bottom_right",
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
        x0, y0 = x, y
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
