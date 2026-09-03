"""End-of-video summary stat card and generic card compositing."""

from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw


class _CardMixin:
    def create_summary_card(
        self,
        distance_km: float,
        duration_seconds: float,
        mode_breakdown: Optional[Dict[str, float]] = None,
        mode_duration: Optional[Dict[str, float]] = None,
        card_size=(560, 130),
    ) -> np.ndarray:
        """A dark glass stat card for the end of the overview video: one
        column per travel mode actually used (icon, distance, time), plus a
        final Total column. A single-mode trip only shows Total, since one
        mode column would just repeat it."""
        w, h = card_size
        scale = 2
        canvas = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)

        bg_color = (18, 18, 20, 225)
        text_color, label_color = (255, 255, 255, 255), (185, 185, 185, 255)
        divider_color = (255, 255, 255, 45)
        # The canvas is RGB<->BGR swapped as a whole at the end (see the
        # final `[2, 1, 0, 3]` reindex below), so a color already in BGR
        # (line_color, shared with the cv2 path drawing) must be
        # pre-reversed here to come out correct after that swap — ties the
        # card's border to the route line's own color.
        accent = tuple(reversed(self.line_color)) + (255,)

        draw.rounded_rectangle(
            [0, 0, w * scale - 1, h * scale - 1],
            radius=18 * scale,
            fill=bg_color,
            outline=accent,
            width=3 * scale,
        )

        font_label = self._load_font(self.FONT_CANDIDATES_REGULAR, 13 * scale)
        font_value = self._load_font(self.FONT_CANDIDATES_BOLD, 23 * scale)
        font_sub = self._load_font(self.FONT_CANDIDATES_REGULAR, 12 * scale)

        mode_duration = mode_duration or {}
        columns: List[Tuple[str, str, float, float]] = []
        if mode_breakdown and len(mode_breakdown) > 1:
            for mode, dist in sorted(mode_breakdown.items(), key=lambda kv: -kv[1]):
                columns.append(
                    (mode.capitalize(), mode.lower(), dist, mode_duration.get(mode, 0.0))
                )
        columns.append(("Total", "total", distance_km, duration_seconds))

        n = len(columns)
        col_w = (w * scale) / n
        icon_size = 30 * scale
        icon_cy = 36 * scale

        for i, (label, mode, dist, dur) in enumerate(columns):
            col_cx = col_w * i + col_w / 2
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
                self._draw_mode_icon(draw, mode, col_cx, icon_cy, icon_size, text_color)

            label_w = draw.textlength(label, font=font_label)
            label_y = icon_cy + icon_size // 2 + 8 * scale
            draw.text(
                (col_cx - label_w / 2, label_y), label, font=font_label, fill=label_color
            )

            distance_str = f"{dist * 1000:.0f} m" if dist < 1 else f"{dist:.1f} km"
            value_w = draw.textlength(distance_str, font=font_value)
            value_y = label_y + 20 * scale
            draw.text(
                (col_cx - value_w / 2, value_y),
                distance_str,
                font=font_value,
                fill=text_color,
            )

            if dur > 0:
                dur_str = self._format_duration_short(dur)
                dur_w = draw.textlength(dur_str, font=font_sub)
                draw.text(
                    (col_cx - dur_w / 2, value_y + 30 * scale),
                    dur_str,
                    font=font_sub,
                    fill=label_color,
                )

        canvas = canvas.resize((w, h), Image.Resampling.LANCZOS)
        return np.array(canvas)[:, :, [2, 1, 0, 3]]

    def composite_card_on_frame(
        self,
        frame: np.ndarray,
        card_bgra: np.ndarray,
        alpha: float,
        margin: int = 40,
        corner: str = "bottom_right",
    ) -> np.ndarray:
        out = frame.copy()
        h, w = out.shape[:2]
        ch, cw = card_bgra.shape[:2]
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
        card_bgr, card_alpha = (
            card_bgra[:, :, :3].astype(np.float32),
            (card_bgra[:, :, 3].astype(np.float32) / 255.0) * alpha,
        )
        roi = out[y0 : y0 + ch, x0 : x0 + cw].astype(np.float32)
        out[y0 : y0 + ch, x0 : x0 + cw] = (
            card_bgr * card_alpha[..., None] + roi * (1 - card_alpha[..., None])
        ).astype(np.uint8)
        return out
