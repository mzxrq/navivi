"""Small vector mode icons (walking/ruler/ship/car/plane) drawn on PIL canvases."""

from typing import Tuple

from PIL import ImageDraw


class _IconMixin:
    def _draw_walking_icon(
        self, draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color: Tuple
    ):
        r = size // 6
        draw.ellipse(
            [cx - r, cy - size // 2, cx + r, cy - size // 2 + 2 * r], fill=color
        )
        torso_top = (cx, cy - size // 2 + 2 * r)
        torso_bottom = (cx - size // 8, cy)
        draw.line([torso_top, torso_bottom], fill=color, width=max(2, size // 12))
        draw.line(
            [torso_bottom, (cx - size // 3, cy + size // 2)],
            fill=color,
            width=max(2, size // 12),
        )
        draw.line(
            [torso_bottom, (cx + size // 4, cy + size // 2 - r // 2)],
            fill=color,
            width=max(2, size // 12),
        )

    def _draw_ruler_icon(
        self, draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color: Tuple
    ):
        half = size // 2
        p1 = (cx - half, cy + half // 2)
        p2 = (cx + half, cy - half // 2)
        draw.line([p1, p2], fill=color, width=max(3, size // 10))
        for t in (0.25, 0.5, 0.75):
            tx, ty = p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t
            draw.line([(tx - 4, ty - 6), (tx + 4, ty + 6)], fill=color, width=2)

    def _draw_ship_icon(
        self, draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color: Tuple
    ):
        half = size / 2
        width = max(2, size // 12)
        hull = [
            (cx - half, cy + half * 0.3),
            (cx - half * 0.6, cy + half * 0.8),
            (cx + half * 0.6, cy + half * 0.8),
            (cx + half, cy + half * 0.3),
        ]
        draw.line(hull + [hull[0]], fill=color, width=width, joint="curve")
        draw.line(
            [(cx, cy + half * 0.3), (cx, cy - half)], fill=color, width=width
        )
        draw.polygon(
            [(cx, cy - half), (cx, cy - half * 0.1), (cx + half * 0.6, cy - half * 0.3)],
            fill=color,
        )

    def _draw_car_icon(
        self, draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color: Tuple
    ):
        half = size / 2
        width = max(2, size // 12)
        draw.rounded_rectangle(
            [cx - half, cy - half * 0.2, cx + half, cy + half * 0.4],
            radius=size // 8,
            outline=color,
            width=width,
        )
        wheel_r = size / 8
        for wx in (cx - half * 0.55, cx + half * 0.55):
            draw.ellipse(
                [
                    wx - wheel_r, cy + half * 0.4 - wheel_r,
                    wx + wheel_r, cy + half * 0.4 + wheel_r,
                ],
                fill=color,
            )

    def _draw_plane_icon(
        self, draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color: Tuple
    ):
        half = size / 2
        width = max(2, size // 12)
        draw.line([(cx - half, cy), (cx + half * 0.6, cy)], fill=color, width=width)
        draw.line(
            [(cx - half * 0.1, cy - half * 0.7), (cx - half * 0.1, cy + half * 0.7)],
            fill=color,
            width=width,
        )
        draw.polygon(
            [
                (cx + half, cy),
                (cx + half * 0.45, cy - half * 0.35),
                (cx + half * 0.45, cy + half * 0.35),
            ],
            fill=color,
        )

    def _draw_mode_icon(
        self,
        draw: ImageDraw.ImageDraw,
        mode: str,
        cx: int,
        cy: int,
        size: int,
        color: Tuple,
    ):
        key = (mode or "").lower()
        if key in ("ferry", "ship", "boat"):
            self._draw_ship_icon(draw, cx, cy, size, color)
        elif key in ("car", "driving"):
            self._draw_car_icon(draw, cx, cy, size, color)
        elif key == "airplane":
            self._draw_plane_icon(draw, cx, cy, size, color)
        else:
            self._draw_walking_icon(draw, cx, cy, size, color)

    def _format_duration_short(self, seconds: float) -> str:
        hrs, mins = divmod(int(round(seconds / 60)), 60)
        return f"{hrs} hr {mins:02d} min" if hrs else f"{mins} min"
