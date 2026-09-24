"""Small vector mode icons (walking/ruler/ship/car/plane) drawn on PIL canvases."""

from typing import Tuple

from PIL import ImageDraw


class _IconMixin:
    def _draw_walking_icon(
        self, draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color: Tuple
    ):
        r = size // 5
        width = max(2, round(size * 0.11))
        draw.ellipse(
            [cx - r, cy - size // 2, cx + r, cy - size // 2 + 2 * r], fill=color
        )
        torso_top = (cx, cy - size // 2 + 2 * r)
        torso_bottom = (cx - size // 10, cy + size // 10)
        draw.line([torso_top, torso_bottom], fill=color, width=width, joint="curve")
        draw.line(
            [torso_bottom, (cx - size // 3, cy + size // 2)],
            fill=color,
            width=width,
            joint="curve",
        )
        draw.line(
            [torso_bottom, (cx + size // 3, cy + size // 2 - r // 3)],
            fill=color,
            width=width,
            joint="curve",
        )
        # Trailing arm, swung back opposite the forward leg — without it
        # the silhouette read as a scarecrow standing still rather than a
        # mid-stride walking figure at these small icon sizes.
        draw.line(
            [torso_top, (cx + size // 4, cy - size // 10)],
            fill=color,
            width=max(2, round(width * 0.8)),
            joint="curve",
        )

    def _draw_ruler_icon(
        self, draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color: Tuple
    ):
        half = size / 2
        width = max(3, round(size * 0.12))
        p1 = (cx - half, cy + half * 0.5)
        p2 = (cx + half, cy - half * 0.5)
        draw.line([p1, p2], fill=color, width=width, joint="curve")
        # Tick length/thickness scale with the icon itself — a fixed pixel
        # offset (as before) shrank to near-invisible hairlines once the
        # base bar got long enough to need scale to stay legible.
        tick_half = size * 0.14
        for t in (0.28, 0.5, 0.72):
            tx, ty = p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t
            draw.line(
                [(tx - tick_half, ty - tick_half), (tx + tick_half, ty + tick_half)],
                fill=color,
                width=max(2, round(width * 0.6)),
            )

    # [NOTE] [Animation] Ship/car/plane silhouettes below are all hand-tuned polygons expressed as fractions of `half` (size/2) around (cx, cy) — proportions were chosen by eye to read as a recognizable icon at small sizes, not derived from any real vehicle geometry.
    def _draw_ship_icon(
        self, draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color: Tuple
    ):
        # Traced (not hand-tuned by eye like the other icons in this file)
        # from a specific reference ferry glyph the user supplied: a solid
        # deckhouse block — slanted bow pennant, four square windows, a
        # stacked (not side-by-side) two-tier funnel — floating above a
        # separate, wider hull trapezoid, with a visible gap between the
        # two pieces. Coordinates are normalized 0..1 over the glyph's own
        # square canvas, scaled by `size` here, so they reproduce its exact
        # proportions rather than approximating them.
        left, top = cx - size / 2, cy - size / 2

        def pt(nx: float, ny: float) -> Tuple[float, float]:
            return (left + nx * size, top + ny * size)

        white = (255, 255, 255, 255) if len(color) == 4 else (255, 255, 255)

        draw.polygon(
            [pt(0.431, 0.250), pt(0.4625, 0.250), pt(0.369, 0.3375)], fill=color
        )
        draw.polygon(
            [pt(0.621, 0.1875), pt(0.735, 0.1875), pt(0.735, 0.255), pt(0.621, 0.255)],
            fill=color,
        )
        draw.polygon(
            [pt(0.621, 0.271), pt(0.735, 0.271), pt(0.735, 0.3375), pt(0.621, 0.3375)],
            fill=color,
        )
        draw.polygon(
            [
                pt(0.294, 0.3375), pt(0.819, 0.3375), pt(0.819, 0.4375),
                pt(0.8625, 0.4375), pt(0.8625, 0.481), pt(0.95, 0.481),
                pt(0.95, 0.5375), pt(0.156, 0.5375),
            ],
            fill=color,
        )
        draw.polygon(
            [pt(0.0, 0.575), pt(1.0, 0.575), pt(0.8625, 0.8125), pt(0.1375, 0.8125)],
            fill=color,
        )

        win = 0.045 * size
        win_y = pt(0, 0.4375)[1]
        for wx_n in (0.365, 0.4525, 0.54, 0.6275):
            wx = pt(wx_n, 0)[0]
            draw.rectangle(
                [wx - win / 2, win_y - win / 2, wx + win / 2, win_y + win / 2],
                fill=white,
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
        # [NOTE] [Animation] Unrecognized/empty modes silently fall back to the walking icon rather than raising or drawing nothing.
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
        # Anything under a minute used to always round UP to "1 min" (or
        # down to a misleading "0 min") — a short leg like a 315m hop
        # estimated at ~32s read as "1 min", nearly double the real value.
        # Showing seconds directly below that threshold keeps short legs
        # honest instead of rounding them into a whole minute they don't
        # actually take.
        if seconds < 60:
            return f"{max(1, int(round(seconds)))} sec"
        hrs, mins = divmod(int(round(seconds / 60)), 60)
        return f"{hrs} hr {mins:02d} min" if hrs else f"{mins} min"
