"""Small vector mode icons (walking/ruler/ship/car/plane) drawn on PIL canvases."""

import math
import re
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import ImageDraw

# The walking/ferry/car pictograms' own source files (the user's assets,
# not hand-drawn like the other mode icons below) — see _load_svg_icon_polygons.
_ICON_DIR = Path(__file__).resolve().parents[3] / "assets" / "image" / "icon"
_WALKING_SVG_PATH = _ICON_DIR / "walking.svg"
_FERRY_SVG_PATH = _ICON_DIR / "ferry.svg"
_CAR_SVG_PATH = _ICON_DIR / "car.svg"

_SVG_COMMAND_CHARS = set("MmLlCcZz")
_SVG_TOKEN_RE = re.compile(r"[MmLlCcZz]|-?\d+\.?\d*(?:[eE][+-]?\d+)?")
_SVG_TRANSFORM_RE = re.compile(r"(translate|scale)\(\s*([-\d.eE]+)[ ,]+([-\d.eE]+)\s*\)")


def _parse_svg_path_polygons(d: str) -> List[List[Tuple[float, float]]]:
    """A `<path d="...">` string (M/L/C/Z, absolute or relative, with the
    implicit-lineto-after-moveto repeat SVG's grammar allows — everything
    potrace itself emits) flattened into closed polygons: each cubic Bezier
    is sampled into straight segments, since PIL's ImageDraw can't stroke or
    fill a curve directly."""
    tokens = _SVG_TOKEN_RE.findall(d)
    pos = 0

    def read_float() -> float:
        nonlocal pos
        value = float(tokens[pos])
        pos += 1
        return value

    cur = (0.0, 0.0)
    start = (0.0, 0.0)
    cmd: Optional[str] = None
    polygons: List[List[Tuple[float, float]]] = []
    poly: List[Tuple[float, float]] = []

    while pos < len(tokens):
        tok = tokens[pos]
        if tok in _SVG_COMMAND_CHARS:
            cmd = tok
            pos += 1
            if cmd in "Zz":
                if poly:
                    polygons.append(poly)
                cur = start
                poly = []
                cmd = None
                continue
            if cmd in "Mm":
                x, y = read_float(), read_float()
                if cmd == "m":
                    x, y = cur[0] + x, cur[1] + y
                cur = (x, y)
                start = cur
                if poly:
                    polygons.append(poly)
                poly = [cur]
                # A bare coordinate pair right after M/m (no new command
                # letter) is an implicit LINETO, per the SVG path grammar.
                cmd = "L" if cmd == "M" else "l"
                continue
        if cmd in ("L", "l"):
            x, y = read_float(), read_float()
            if cmd == "l":
                x, y = cur[0] + x, cur[1] + y
            cur = (x, y)
            poly.append(cur)
        elif cmd in ("C", "c"):
            x1, y1 = read_float(), read_float()
            x2, y2 = read_float(), read_float()
            x, y = read_float(), read_float()
            if cmd == "c":
                x1, y1 = cur[0] + x1, cur[1] + y1
                x2, y2 = cur[0] + x2, cur[1] + y2
                x, y = cur[0] + x, cur[1] + y
            steps = 10
            for step in range(1, steps + 1):
                t = step / steps
                mt = 1 - t
                bx = mt**3 * cur[0] + 3 * mt**2 * t * x1 + 3 * mt * t**2 * x2 + t**3 * x
                by = mt**3 * cur[1] + 3 * mt**2 * t * y1 + 3 * mt * t**2 * y2 + t**3 * y
                poly.append((bx, by))
            cur = (x, y)
        else:
            pos += 1  # an unrecognized leading token — skip it defensively
    if poly:
        polygons.append(poly)
    return polygons


@lru_cache(maxsize=None)
def _load_svg_icon_polygons(svg_path: Path) -> Tuple[Tuple[Tuple[float, float], ...], ...]:
    """One SVG file's own <path> outlines, in normalized 0..1 coordinates
    (its own aspect ratio kept, longest side spanning 0..1, centered on the
    shorter one) so a _draw_*_icon method can scale/center them into any
    (cx, cy, size) box the same way _draw_ship_icon's hand-traced polygons
    do. Handles both a potrace-style file (a <g transform="translate(...)
    scale(...)"> wrapping several bare M/l/c/z paths — walking.svg) and a
    plain single-path file with no group transform at all (ferry.svg).
    Parsed once per file (an SVG icon never changes at runtime) rather than
    on every frame's icon draw, keyed by path so different icons don't
    collide in the cache."""
    try:
        svg_text = svg_path.read_text(encoding="utf-8")
    except OSError:
        return ()

    group_match = re.search(r"<g\s+transform=\"([^\"]+)\"", svg_text)
    tx = ty = 0.0
    sx = sy = 1.0
    if group_match:
        for name, a, b in _SVG_TRANSFORM_RE.findall(group_match.group(1)):
            if name == "translate":
                tx, ty = float(a), float(b)
            elif name == "scale":
                sx, sy = float(a), float(b)

    polygons: List[List[Tuple[float, float]]] = []
    for path_d in re.findall(r'<path\s+[^>]*\bd="([^"]+)"', svg_text):
        for poly in _parse_svg_path_polygons(path_d):
            # The group's own transform (potrace's usual "translate(0,H)
            # scale(0.1,-0.1)": shrink 10x and flip the y axis it traced
            # bottom-up in) is applied to the raw path coordinates before
            # anything downstream ever sees them — same order SVG itself
            # composes transform="translate(...) scale(...)" in (scale
            # first, then translate). A file with no <g transform> at all
            # (ferry.svg) leaves tx=ty=0, sx=sy=1 - a no-op.
            polygons.append([(x * sx + tx, y * sy + ty) for x, y in poly])
    if not polygons:
        return ()

    xs = [x for poly in polygons for x, _ in poly]
    ys = [y for poly in polygons for _, y in poly]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    span = max(max_x - min_x, max_y - min_y) or 1.0
    # Centered within the longer axis's own span, so the shorter axis sits
    # in the middle of the square it's about to be scaled into instead of
    # hugging one edge.
    off_x = (span - (max_x - min_x)) / 2
    off_y = (span - (max_y - min_y)) / 2
    return tuple(
        tuple(((x - min_x + off_x) / span, (y - min_y + off_y) / span) for x, y in poly)
        for poly in polygons
    )


def _signed_area(poly) -> float:
    """The polygon's own signed area (shoelace formula): its sign is the
    winding direction. A multi-subpath SVG fill (nonzero rule) draws a hole
    as a subpath wound the OPPOSITE way from the shape it cuts into — e.g.
    ferry.svg's three porthole circles are wound backwards from its hull —
    so comparing signs (not sizes: a walking figure's separate head and body
    are both solid despite being very different sizes) tells a real hole
    apart from just another solid piece of the same icon."""
    total = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return total / 2


class _IconMixin:
    @staticmethod
    def _draw_svg_icon(
        draw: ImageDraw.ImageDraw, polygons, cx: int, cy: int, size: int, color: Tuple
    ) -> bool:
        """Fills polygons (normalized 0..1, from _load_svg_icon_polygons)
        scaled/centered into a size x size box at (cx, cy). A polygon wound
        the opposite way from the icon's main shape (see _signed_area) is a
        hole (e.g. ferry.svg's portholes) — filled white instead of `color`,
        the same trick _draw_ship_icon_fallback's windows already use,
        rather than actually punched transparent (these icons only ever sit
        on the light card backgrounds this file draws them onto). Returns
        False (drawing nothing) when there were no polygons to draw, so a
        caller can fall back to its own hand-drawn shape."""
        if not polygons:
            return False
        main_sign = max(polygons, key=lambda p: abs(_signed_area(p)))
        main_sign = _signed_area(main_sign) >= 0
        white = (255, 255, 255, 255) if len(color) == 4 else (255, 255, 255)
        left, top = cx - size / 2, cy - size / 2
        holes = []
        # Every filled (main-sign) polygon first, then the holes on top —
        # not the file's own subpath order, which can (and does, in
        # ferry.svg) put a hole BEFORE the shape it's meant to cut into,
        # where a same-order draw would immediately paint over it.
        for poly in polygons:
            points = [(left + nx * size, top + ny * size) for nx, ny in poly]
            if (_signed_area(poly) >= 0) != main_sign:
                holes.append(points)
            else:
                draw.polygon(points, fill=color)
        for points in holes:
            draw.polygon(points, fill=white)
        return True

    def _draw_walking_icon(
        self, draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color: Tuple
    ):
        """The user's own walking pictogram (assets/image/icon/walking.svg —
        the same file pydeckrecorder.pedestrian embeds as CSS/HTML for the
        residential HUD), traced into filled polygons here so the OpenCV/PIL
        summary-card path draws the identical silhouette instead of the
        older hand-tuned stick figure below."""
        polygons = _load_svg_icon_polygons(_WALKING_SVG_PATH)
        if not self._draw_svg_icon(draw, polygons, cx, cy, size, color):
            self._draw_walking_stick_figure(draw, cx, cy, size, color)

    def _draw_walking_stick_figure(
        self, draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color: Tuple
    ):
        """The original hand-drawn stick figure — kept as a fallback for
        _draw_walking_icon if walking.svg is ever missing/unreadable."""
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
        # Perpendicular to the bar (dx, dy) -> (-dy, dx), normalized — each
        # tick used to be drawn PARALLEL to the bar itself (same (dx, dy)
        # direction as the offset), which at this width/length just laid a
        # short stripe next to the main line instead of a crossing hash
        # mark, reading as a jagged zigzag rather than a ruler.
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        length = math.hypot(dx, dy) or 1.0
        perp_x, perp_y = -dy / length, dx / length
        for t in (0.28, 0.5, 0.72):
            tx, ty = p1[0] + dx * t, p1[1] + dy * t
            draw.line(
                [
                    (tx - tick_half * perp_x, ty - tick_half * perp_y),
                    (tx + tick_half * perp_x, ty + tick_half * perp_y),
                ],
                fill=color,
                width=max(2, round(width * 0.6)),
            )

    def _draw_ship_icon(
        self, draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color: Tuple
    ):
        """The user's own ferry pictogram (assets/image/icon/ferry.svg),
        traced into filled polygons the same way _draw_walking_icon uses
        walking.svg. Falls back to the hand-traced glyph below if the file
        is ever missing/unreadable."""
        polygons = _load_svg_icon_polygons(_FERRY_SVG_PATH)
        if not self._draw_svg_icon(draw, polygons, cx, cy, size, color):
            self._draw_ship_icon_fallback(draw, cx, cy, size, color)

    # [NOTE] [Animation] Car/plane silhouettes below (and this ship fallback) are all hand-tuned polygons expressed as fractions of `half` (size/2) around (cx, cy) — proportions were chosen by eye to read as a recognizable icon at small sizes, not derived from any real vehicle geometry.
    def _draw_ship_icon_fallback(
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
        """The user's own car pictogram (assets/image/icon/car.svg), traced
        the same way _draw_walking_icon/_draw_ship_icon use theirs. Falls
        back to the hand-drawn shape below if the file is ever missing/
        unreadable."""
        polygons = _load_svg_icon_polygons(_CAR_SVG_PATH)
        if not self._draw_svg_icon(draw, polygons, cx, cy, size, color):
            self._draw_car_icon_fallback(draw, cx, cy, size, color)

    def _draw_car_icon_fallback(
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
