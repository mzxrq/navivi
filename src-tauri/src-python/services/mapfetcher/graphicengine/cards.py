"""End-of-video summary stat card and generic card compositing."""

from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw


class _CardMixin:
    @staticmethod
    def _draw_clock_icon(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color: Tuple):
        r = size / 2
        width = max(2, round(size * 0.12))
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=width)
        draw.line([(cx, cy), (cx, cy - r * 0.55)], fill=color, width=width)
        draw.line([(cx, cy), (cx + r * 0.4, cy + r * 0.1)], fill=color, width=width)

    @staticmethod
    def _draw_stat_block(
        draw: ImageDraw.ImageDraw,
        cx: float,
        top_y: float,
        icon_size: float,
        icon_fn,
        icon_color: Tuple,
        label: str,
        font_label,
        label_color: Tuple,
        value: str,
        font_value,
        value_color: Tuple,
    ) -> None:
        """One stat 'tile': a small icon + label side by side, then the
        actual value large and bold underneath — the icon+label identify
        what the number IS before the eye even reaches it, rather than
        making the viewer infer it from a single big number alone."""
        label_w = draw.textlength(label, font=font_label)
        gap = icon_size * 0.4
        row_w = icon_size + gap + label_w
        row_x0 = cx - row_w / 2
        icon_cy = top_y + icon_size / 2
        icon_fn(draw, row_x0 + icon_size / 2, icon_cy, icon_size, icon_color)
        draw.text(
            (row_x0 + icon_size + gap, top_y + icon_size * 0.12),
            label,
            font=font_label,
            fill=label_color,
        )
        value_w = draw.textlength(value, font=font_value)
        value_y = top_y + icon_size + gap
        draw.text((cx - value_w / 2, value_y), value, font=font_value, fill=value_color)

    def create_summary_card(
        self,
        distance_km: float,
        duration_seconds: float,
        mode_breakdown: Optional[Dict[str, float]] = None,
        mode_duration: Optional[Dict[str, float]] = None,
        card_size=(560, 150),
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

        def mode_accent(mode: str) -> Tuple:
            """Same color the route line itself uses for this mode
            (MODE_COLORS), pre-reversed like `accent` above so it comes out
            correct after the canvas-wide BGR swap at the end — ties each
            mode's stat column back to its own line color on the map
            instead of every column sharing one generic accent. "total"
            isn't a real travel mode with a line color of its own, so it
            keeps the generic accent."""
            if mode == "total":
                return accent
            return tuple(reversed(self.MODE_COLORS.get(mode, self.line_color))) + (255,)

        draw.rounded_rectangle(
            [0, 0, w * scale - 1, h * scale - 1],
            radius=18 * scale,
            fill=bg_color,
            outline=accent,
            width=3 * scale,
        )

        font_label = self._load_font(self.FONT_CANDIDATES_REGULAR, 14 * scale)
        font_value_2 = self._load_font(self.FONT_CANDIDATES_BOLD, 26 * scale)

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
        col_w = (w * scale) / n
        tile_icon_size = 20 * scale
        # A single mode gets the whole card as icon+label / big-value
        # "tiles" (Time, Distance) — this is the layout width a
        # multi-mode card's per-mode columns don't have room for; longer
        # values there (e.g. "2 hr 36 min") would overflow a column
        # that's also carrying its own mode header. Multi-mode columns
        # keep the more compact single-big-number-plus-small-stats style
        # instead.
        if n == 1:
            label, mode, dist, dur = columns[0]
            col_cx = col_w / 2
            distance_str = f"{dist * 1000:.0f} m" if dist < 1 else f"{dist:.1f} km"
            dur_str = self._format_duration_short(dur) if dur > 0 else "--"
            time_icon = lambda d, cx, cy, sz, col: self._draw_mode_icon(d, mode, cx, cy, sz, col)

            tiles = [
                (time_icon, "Time", dur_str),
                (self._draw_ruler_icon, "Distance", distance_str),
            ]

            col_accent = mode_accent(mode)
            top_y = (h * scale - (tile_icon_size + 18 * scale + 26 * scale)) / 2
            tile_w = col_w / len(tiles)
            for j, (icon_fn, tile_label, tile_value) in enumerate(tiles):
                tile_cx = tile_w * j + tile_w / 2
                self._draw_stat_block(
                    draw, tile_cx, top_y, tile_icon_size,
                    icon_fn, col_accent, tile_label, font_label, label_color,
                    tile_value, font_value_2, text_color,
                )
        else:
            icon_size = 26 * scale
            icon_cy = 32 * scale
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
                label_y = icon_cy + icon_size // 2 + 6 * scale
                draw.text(
                    (col_cx - label_w / 2, label_y), label, font=font_label, fill=label_color
                )

                distance_str = f"{dist * 1000:.0f} m" if dist < 1 else f"{dist:.1f} km"
                value_w = draw.textlength(distance_str, font=font_value_2)
                value_y = label_y + 16 * scale
                draw.text(
                    (col_cx - value_w / 2, value_y),
                    distance_str,
                    font=font_value_2,
                    fill=col_accent,
                )

                dur_str = self._format_duration_short(dur) if dur > 0 else None
                stat_icon_d = 15 * scale
                icon_text_gap = 6 * scale
                if dur_str:
                    row_y = value_y + 34 * scale
                    dur_w = draw.textlength(dur_str, font=font_label)
                    line_x = col_cx - (stat_icon_d + icon_text_gap + dur_w) / 2
                    self._draw_clock_icon(
                        draw, line_x + stat_icon_d / 2, row_y + stat_icon_d / 2,
                        stat_icon_d, col_accent,
                    )
                    draw.text(
                        (line_x + stat_icon_d + icon_text_gap, row_y),
                        dur_str, font=font_label, fill=label_color,
                    )

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
