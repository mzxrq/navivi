"""Rounded caption boxes for burned-in .ass captions.

libass only draws square boxes (BorderStyle=3), so a caption with a corner radius gets its
box drawn as a vector shape under bare text. The shape is one \\p1 drawing holding a
rounded rectangle per line; libass fills it once, so lines that overlap don't double up
the box's transparency.

[NOTE] [Captions] libass sizes a font by its cell height (ascent + descent), so a line is
`font_size` tall and its width is measured at that scale, not at PIL's em-based size.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import List, Optional

from services.localization.text_style import TextStyle, _bgr

FRAME_H = 1080
_PROBE_PX = 1000
_KAPPA = 0.5523  # cubic-bezier control distance for a quarter circle


@lru_cache(maxsize=32)
def _probe(file: str, number: int):
    from PIL import ImageFont

    font = ImageFont.truetype(file, _PROBE_PX, index=number)
    ascent, descent = font.getmetrics()
    return font, ascent + descent


def measure_line(style: TextStyle, text: str) -> Optional[float]:
    """Width in 1080p px of `text` as libass will set it, or None when the font can't be measured."""
    from services.localization.fonts import find_font_file

    found = find_font_file(style.font_family, style.bold, style.italic)
    if not found:
        return None
    try:
        font, cell = _probe(*found)
        width = font.getlength(text) * style.font_size / cell
    except Exception:  # unreadable file or unsupported format: draw the square box instead
        return None
    return width + style.letter_spacing * len(text)


@dataclass(frozen=True)
class CaptionBox:
    drawing: str  # the ASS drawing commands
    x: int  # where the text block's top centre goes (an8 \pos)
    y: int


def _rounded_rect(x0: float, y0: float, x1: float, y1: float, r: float) -> str:
    k = r * _KAPPA
    f = lambda v: f"{v:.1f}".rstrip("0").rstrip(".")  # noqa: E731
    return (
        f"m {f(x0 + r)} {f(y0)} l {f(x1 - r)} {f(y0)} "
        f"b {f(x1 - r + k)} {f(y0)} {f(x1)} {f(y0 + r - k)} {f(x1)} {f(y0 + r)} l {f(x1)} {f(y1 - r)} "
        f"b {f(x1)} {f(y1 - r + k)} {f(x1 - r + k)} {f(y1)} {f(x1 - r)} {f(y1)} l {f(x0 + r)} {f(y1)} "
        f"b {f(x0 + r - k)} {f(y1)} {f(x0)} {f(y1 - r + k)} {f(x0)} {f(y1 - r)} l {f(x0)} {f(y0 + r)} "
        f"b {f(x0)} {f(y0 + r - k)} {f(x0 + r - k)} {f(y0)} {f(x0 + r)} {f(y0)}"
    )


def build_box(style: TextStyle, lines: List[str], play_w: int) -> Optional[CaptionBox]:
    """The rounded box behind `lines` (centred), or None if it can't be laid out."""
    widths = [measure_line(style, line) for line in lines]
    if not lines or any(w is None for w in widths):
        return None
    fs = float(style.font_size)
    pad_x = max(style.outline_width, 9.0)
    pad_y = pad_x * 0.3
    block_h = fs * len(lines)
    if style.position == "top":
        top = style.margin_v
    elif style.position == "middle":
        top = (FRAME_H - block_h) / 2
    else:
        top = FRAME_H - style.margin_v - block_h
    cx = play_w / 2
    shapes = []
    for i, w in enumerate(widths):
        half = w / 2 + pad_x
        y0, y1 = top + i * fs - pad_y, top + (i + 1) * fs + pad_y
        r = min(style.background_radius, half, (y1 - y0) / 2)
        shapes.append(_rounded_rect(cx - half, y0, cx + half, y1, r))
    return CaptionBox(" ".join(shapes), int(round(cx)), int(round(top)))


def box_event_text(style: TextStyle, box: CaptionBox) -> str:
    alpha = 255 - int(round(style.background_opacity * 255))
    return (
        f"{{\\an7\\pos(0,0)\\bord0\\shad0\\1c&H{_bgr(style.background_color)}&\\1a&H{alpha:02X}&\\p1}}{box.drawing}"
    )


def text_position_tag(box: CaptionBox) -> str:
    return f"{{\\an8\\pos({box.x},{box.y})}}"
