"""Outro/end-card clip generator: the project title plus a numbered card for
every waypoint that has a popup image, as the video's closing clip. Two
styles (tuning.DEFAULT_OUTRO_STYLE / settings.outro_style):

- "scroll": cards three to a row in a centred column that slowly scrolls up,
  credits-style, until every card has left the screen.
- "grid": one composited frame, every card squeezed onto a single screen,
  held for a fixed duration.

Standalone (PIL-only compositing + a plain ffmpeg `-loop 1` hold), reusing
the same bundled Japanese-capable fonts as graphicengine/base.py rather
than duplicating font-candidate lists.
"""

from __future__ import annotations

import math
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw
from PIL.ImageFont import FreeTypeFont, load_default, truetype

from services.mapfetcher.graphicengine.base import _GraphicsEngineBase
from services.logger.logger import setup_logger
from services.tts.ttsengine import FFmpegManager
from services import tuning

logger = setup_logger("OutroCard")

_CANVAS_W, _CANVAS_H = 1280, 704
_HEADER_HEIGHT = 130
_LABEL_ROW_HEIGHT = 26
_BADGE_RADIUS = 14
_CORNER_RADIUS = 10


def _load_font(candidates: List[str], size: int) -> FreeTypeFont | Any:
    for name in candidates:
        try:
            return truetype(name, size)
        except OSError:
            continue
    return load_default()


def _truncate_to_width(
    draw: ImageDraw.ImageDraw, text: str, font: FreeTypeFont, max_width: float
) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "…"
    truncated = text
    while truncated and draw.textlength(truncated + ellipsis, font=font) > max_width:
        truncated = truncated[:-1]
    return (truncated + ellipsis) if truncated else ellipsis


def _center_text(
    draw: ImageDraw.ImageDraw, text: str, font: FreeTypeFont, center_x: float, y: float, fill
) -> None:
    width = draw.textlength(text, font=font)
    draw.text((center_x - width / 2, y), text, font=font, fill=fill)


def _rounded_thumbnail(
    image_path: str, size: tuple, radius: int = _CORNER_RADIUS,
) -> Optional[Image.Image]:
    """Loads image_path, center-crops to size's aspect ratio, resizes, and
    applies rounded corners via an alpha mask. Returns None if the image
    can't be read."""
    # [NOTE] [Animation] Center-crop to the target aspect first, then resize, so
    # thumbnails fill their cell without letterboxing or distortion.
    try:
        src = Image.open(image_path).convert("RGB")
    except Exception as exc:
        logger.warning("Outro: could not read popup image '%s': %s", image_path, exc)
        return None

    target_w, target_h = size
    target_aspect = target_w / target_h
    src_aspect = src.width / src.height
    if src_aspect > target_aspect:
        crop_w = int(src.height * target_aspect)
        x0 = (src.width - crop_w) // 2
        src = src.crop((x0, 0, x0 + crop_w, src.height))
    else:
        crop_h = int(src.width / target_aspect)
        y0 = (src.height - crop_h) // 2
        src = src.crop((0, y0, src.width, y0 + crop_h))
    src = src.resize((target_w, target_h), Image.LANCZOS)

    mask = Image.new("L", (target_w, target_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, target_w - 1, target_h - 1], radius=radius, fill=255
    )
    out = Image.new("RGBA", (target_w, target_h))
    out.paste(src, (0, 0), mask)
    return out


def _draw_badge(
    canvas: Image.Image, center: tuple, number: int, font: FreeTypeFont,
    radius: int = _BADGE_RADIUS,
) -> None:
    draw = ImageDraw.Draw(canvas)
    cx, cy = center
    draw.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        fill=tuning.OUTRO_BADGE_COLOR,
        outline=tuning.OUTRO_BG_COLOR,
        width=2,
    )
    text = str(number)
    tw = draw.textlength(text, font=font)
    draw.text((cx - tw / 2, cy - font.size / 2 - 1), text, font=font, fill=(255, 255, 255))


def _draw_photo_badge(
    page: Image.Image, x: int, y: int, number: int, font: FreeTypeFont, px,
) -> None:
    """A white pill with a soft shadow and the number centred, over a photo."""
    from PIL import ImageFilter

    h = px(tuning.OUTRO_PHOTO_BADGE_HEIGHT)
    text = str(number)
    w = max(h, int(ImageDraw.Draw(page).textlength(text, font=font)) + px(16))
    s = px(6)  # room for the shadow
    layer = Image.new("RGBA", (w + 2 * s, h + 2 * s), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(
        [s, s + px(1), s + w - 1, s + h], radius=h // 2, fill=(0, 0, 0, 120),
    )
    layer = layer.filter(ImageFilter.GaussianBlur(px(3)))
    ld = ImageDraw.Draw(layer)
    ld.rounded_rectangle([s, s, s + w - 1, s + h - 1], radius=h // 2, fill=tuning.OUTRO_PHOTO_BADGE_FILL)
    ld.text((s + w / 2, s + h / 2), text, font=font, fill=tuning.OUTRO_PHOTO_BADGE_TEXT, anchor="mm")
    page.paste(layer, (int(x) - s, int(y) - s), layer)


def _first_image(wp: Dict[str, Any]) -> Optional[str]:
    popup_image = wp.get("popup_image")
    if isinstance(popup_image, list):
        return popup_image[0] if popup_image else None
    return popup_image


def _fmt_km(km: float) -> str:
    return f"{km * 1000:.0f} m" if km < 1 else f"{km:.1f} km"


def _engine():
    from services.mapfetcher.graphicengine import GraphicsEngine

    return GraphicsEngine()


def _mode_rgb(engine, mode: str) -> Tuple[int, int, int]:
    return tuple(reversed(engine.MODE_COLORS.get(mode, engine.line_color)))[:3]


def _leg_modes(leg: Dict[str, Any]) -> List[str]:
    """The leg's modes in travel order, repeats merged (walk, ferry, walk -> both)."""
    modes: List[str] = []
    for piece in leg.get("pieces") or [{"mode": leg.get("mode", "walking")}]:
        if piece["mode"] not in modes:
            modes.append(piece["mode"])
    return modes


def _mode_totals(brief: Dict[str, Any]) -> List[Tuple[str, float, int]]:
    """(mode, km, minutes) over the whole trip, longest distance first."""
    km: Dict[str, float] = {}
    minutes: Dict[str, int] = {}
    for leg in brief.get("legs") or []:
        for piece in leg.get("pieces") or [leg]:
            km[piece["mode"]] = km.get(piece["mode"], 0.0) + piece["km"]
            minutes[piece["mode"]] = minutes.get(piece["mode"], 0) + piece["minutes"]
    return sorted(((m, km[m], minutes[m]) for m in km), key=lambda r: -r[1])


def _totals_line(engine, brief: Dict[str, Any]) -> str:
    return f"{_fmt_km(brief['total_km'])} ・ {engine._format_duration_ja(brief['total_minutes'] * 60)}"


def _build_frame(
    project_name: str, waypoints: List[Dict[str, Any]], brief: Optional[Dict[str, Any]] = None,
) -> Image.Image:
    canvas = Image.new("RGB", (_CANVAS_W, _CANVAS_H), tuning.OUTRO_BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    title_font = _load_font(_GraphicsEngineBase.FONT_CANDIDATES_BOLD, tuning.OUTRO_TITLE_FONT_SIZE)
    subtitle_font = _load_font(
        _GraphicsEngineBase.FONT_CANDIDATES_THIN, tuning.OUTRO_SUBTITLE_FONT_SIZE
    )
    label_font = _load_font(
        _GraphicsEngineBase.FONT_CANDIDATES_THIN, tuning.OUTRO_LABEL_FONT_SIZE
    )
    badge_font = _load_font(
        _GraphicsEngineBase.FONT_CANDIDATES_BOLD, tuning.OUTRO_BADGE_FONT_SIZE
    )

    subtitle = tuning.OUTRO_SUBTITLE_TEMPLATE.format(count=len(waypoints))
    if brief and brief.get("legs"):
        subtitle += f" ・ {_totals_line(_engine(), brief)}"
    _center_text(draw, project_name, title_font, _CANVAS_W / 2, 34, tuning.OUTRO_TITLE_COLOR)
    _center_text(
        draw,
        subtitle,
        subtitle_font,
        _CANVAS_W / 2,
        34 + tuning.OUTRO_TITLE_FONT_SIZE + 10,
        tuning.OUTRO_SUBTITLE_COLOR,
    )

    shown = waypoints[: tuning.OUTRO_MAX_CARDS]
    if not shown:
        return canvas

    # [NOTE] [Map] Column count grows with card count (capped at OUTRO_GRID_COLS_MAX);
    # cell size is then derived to fill the fixed canvas rather than a fixed cell grid.
    cols = min(tuning.OUTRO_GRID_COLS_MAX, len(shown))
    rows = math.ceil(len(shown) / cols)
    margin = tuning.OUTRO_CARD_MARGIN

    grid_top = _HEADER_HEIGHT
    grid_h = _CANVAS_H - grid_top - margin
    cell_w = (_CANVAS_W - margin * (cols + 1)) / cols
    cell_h = (grid_h - margin * (rows - 1)) / rows
    thumb_h = cell_h - _LABEL_ROW_HEIGHT
    thumb_w = min(cell_w, thumb_h * tuning.OUTRO_CARD_ASPECT)
    thumb_h = thumb_w / tuning.OUTRO_CARD_ASPECT

    for idx, wp in enumerate(shown):
        row, col = divmod(idx, cols)
        cell_x = margin + col * (cell_w + margin)
        cell_y = grid_top + row * (cell_h + margin)
        thumb_x = cell_x + (cell_w - thumb_w) / 2
        thumb_y = cell_y

        image_path = _first_image(wp)
        thumb = (
            _rounded_thumbnail(image_path, (int(thumb_w), int(thumb_h)))
            if image_path
            else None
        )
        if thumb is not None:
            canvas.paste(thumb, (int(thumb_x), int(thumb_y)), thumb)
        else:
            draw.rounded_rectangle(
                [thumb_x, thumb_y, thumb_x + thumb_w, thumb_y + thumb_h],
                radius=_CORNER_RADIUS,
                fill=(40, 40, 44),
            )

        _draw_badge(canvas, (int(thumb_x) + 4, int(thumb_y) + 4), idx + 1, badge_font)

        label = _truncate_to_width(
            draw,
            str(wp.get("label", f"{tuning.PIPELINE_LABELS['waypoint_fallback']} {idx + 1}")),
            label_font, thumb_w,
        )
        _center_text(
            draw,
            label,
            label_font,
            thumb_x + thumb_w / 2,
            thumb_y + thumb_h + 6,
            tuning.OUTRO_LABEL_COLOR,
        )

    return canvas


def _build_scroll_page(
    project_name: str, waypoints: List[Dict[str, Any]], size: Tuple[int, int],
    brief: Optional[Dict[str, Any]] = None, heading: Optional[Dict[str, Any]] = None,
) -> Image.Image:
    """One tall page `size[0]` wide: the title block on top, then EVERY card
    (no OUTRO_MAX_CARDS cap - scrolling is what makes a long list fit),
    tuning.OUTRO_SCROLL_COLS to a row inside a centred container
    (OUTRO_SCROLL_SIDE_PADDING either side), each a rounded thumbnail with
    its number badge and bold name underneath. One empty screen follows the
    content, so scrolling to the page's bottom carries every card off the
    top.

    With a route `brief` (route_brief.build_brief) that has legs, the page is
    the route timeline instead (see _build_route_page).

    Drawn at the finished video's own size (tuning's px values are for the
    704-high canvas and scale with it): an outro drawn small and stretched
    up by the export has soft text that judders as it moves."""
    if brief and brief.get("legs"):
        return _build_route_page(project_name, waypoints, size, brief, heading)
    width, height = size
    k = height / _CANVAS_H

    def px(value: float) -> int:
        return int(round(value * k))

    bold = _GraphicsEngineBase.FONT_CANDIDATES_BOLD
    cols = tuning.OUTRO_SCROLL_COLS
    margin = px(tuning.OUTRO_SCROLL_MARGIN)
    container_w = width - 2 * px(tuning.OUTRO_SCROLL_SIDE_PADDING)
    label_size = px(tuning.OUTRO_SCROLL_LABEL_FONT_SIZE)
    label_min_size = px(tuning.OUTRO_SCROLL_LABEL_MIN_FONT_SIZE)
    label_font = _load_font(bold, label_size)
    badge_font = _load_font(bold, px(tuning.OUTRO_SCROLL_BADGE_FONT_SIZE))
    title_font = _load_font(bold, px(tuning.OUTRO_TITLE_FONT_SIZE))
    subtitle_font = _load_font(bold, px(tuning.OUTRO_SUBTITLE_FONT_SIZE))
    header_h = px(_HEADER_HEIGHT)

    thumb_w = int((container_w - margin * (cols - 1)) / cols)
    thumb_h = int(thumb_w / tuning.OUTRO_CARD_ASPECT)
    label_h = label_size + px(16)
    row_h = thumb_h + label_h + margin
    rows = math.ceil(len(waypoints) / cols)
    page_h = header_h + rows * row_h + height

    page = Image.new("RGB", (width, page_h), tuning.OUTRO_BG_COLOR)
    draw = ImageDraw.Draw(page)
    _center_text(draw, project_name, title_font, width / 2, px(34), tuning.OUTRO_TITLE_COLOR)
    _center_text(
        draw,
        tuning.OUTRO_SUBTITLE_TEMPLATE.format(count=len(waypoints)),
        subtitle_font,
        width / 2,
        px(34 + tuning.OUTRO_TITLE_FONT_SIZE + 10),
        tuning.OUTRO_SUBTITLE_COLOR,
    )

    badge_r = px(tuning.OUTRO_SCROLL_BADGE_RADIUS)
    for idx, wp in enumerate(waypoints):
        row, col = divmod(idx, cols)
        # A last row that isn't full is centred rather than left-aligned.
        in_row = min(cols, len(waypoints) - row * cols)
        row_left = (width - (in_row * thumb_w + (in_row - 1) * margin)) / 2
        x = int(row_left + col * (thumb_w + margin))
        y = header_h + row * row_h

        image_path = _first_image(wp)
        thumb = (
            _rounded_thumbnail(image_path, (thumb_w, thumb_h), px(_CORNER_RADIUS))
            if image_path else None
        )
        if thumb is not None:
            page.paste(thumb, (x, y), thumb)
        else:
            draw.rounded_rectangle(
                [x, y, x + thumb_w, y + thumb_h], radius=px(_CORNER_RADIUS), fill=(40, 40, 44)
            )
        _draw_badge(page, (x + badge_r + px(8), y + badge_r + px(8)), idx + 1, badge_font, badge_r)

        # A long name first shrinks (down to OUTRO_SCROLL_LABEL_MIN_FONT_SIZE)
        # to fit the card's width, and is only cut with "…" past that.
        text = str(wp.get("label", f"{tuning.PIPELINE_LABELS['waypoint_fallback']} {idx + 1}"))
        font = label_font
        font_size = label_size
        while draw.textlength(text, font=font) > thumb_w and font_size > label_min_size:
            font_size -= 1
            font = _load_font(bold, font_size)
        label = _truncate_to_width(draw, text, font, thumb_w)
        # Shrunk text stays vertically centred on the full-size label line.
        label_y = y + thumb_h + px(8) + (label_size - font_size) / 2
        _center_text(draw, label, font, x + thumb_w / 2, label_y, tuning.OUTRO_LABEL_COLOR)

    return page


def _image_at(waypoints: List[Dict[str, Any]], at) -> Optional[str]:
    """The popup image of the waypoint at `at` ([lat, lng], as the brief has it)."""
    for wp in waypoints:
        if [wp.get("lat"), wp.get("lng")] == list(at):
            return _first_image(wp)
    return None


def _mix(a: Tuple[int, int, int], b: Tuple[int, int, int], t: float) -> Tuple[int, int, int]:
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


def _style_font(style, size: int) -> FreeTypeFont | Any:
    """`style`'s installed font at `size` px, else the bundled one of its weight."""
    from services.localization.fonts import font_file

    found = font_file(style.font_family, style.bold)
    if found:
        try:
            return truetype(found[0], size, index=found[1])
        except OSError:
            pass
    base = _GraphicsEngineBase
    return _load_font(base.FONT_CANDIDATES_BOLD if style.bold else base.FONT_CANDIDATES_REGULAR, size)


def _heading_lines(
    title: str, subtitle: str, title_style: Optional[Dict[str, Any]],
    subtitle_style: Optional[Dict[str, Any]], height: int,
    kicker: str = "", kicker_style: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, Any, int]]:
    """(text, TextStyle, size px) for the kicker, title and subtitle, styled like
    the intro's (settings.intro_*_style over its defaults). Intro sizes are in
    1080-line units."""
    from services.vdoprocessing.introclip import DEFAULT_KICKER_STYLE, DEFAULT_SUBTITLE_STYLE, DEFAULT_TITLE_STYLE

    lines = []
    for text, default, raw in (
        (kicker, DEFAULT_KICKER_STYLE, kicker_style),
        (title, DEFAULT_TITLE_STYLE, title_style),
        (subtitle, DEFAULT_SUBTITLE_STYLE, subtitle_style),
    ):
        if text:
            style = default.merged(raw)
            size = int(round(style.font_size * tuning.OUTRO_HEADING_SCALE * height / 1080))
            lines.append((text, style, size))
    return lines


def _draw_heading(
    draw: ImageDraw.ImageDraw, lines: List[Tuple[str, Any, int]], center_x: float, top: float,
    max_w: float, k: float,
) -> None:
    y = top
    for text, style, size in lines:
        font = _style_font(style, size)
        while draw.textlength(text, font=font) > max_w and size > 12:
            size -= 1
            font = _style_font(style, size)
        stroke = int(round(style.outline_width * k))
        shadow = int(round(style.shadow * k))
        if shadow:
            draw.text(
                (center_x + shadow, y + shadow), text, font=font, anchor="ma",
                fill=style.shadow_color, stroke_width=stroke, stroke_fill=style.shadow_color,
            )
        draw.text(
            (center_x, y), text, font=font, anchor="ma", fill=style.color,
            stroke_width=stroke, stroke_fill=style.outline_color,
        )
        y += size + int(round(tuning.OUTRO_HEADING_LINE_GAP * k))


def _heading_height(lines: List[Tuple[str, Any, int]], k: float) -> int:
    gap = int(round(tuning.OUTRO_HEADING_LINE_GAP * k))
    return sum(size for _, _, size in lines) + gap * max(0, len(lines) - 1)


def _build_route_page(
    project_name: str, waypoints: List[Dict[str, Any]], size: Tuple[int, int],
    brief: Dict[str, Any], heading: Optional[Dict[str, Any]] = None,
) -> Image.Image:
    """The route page: the title, the trip summary, then one card per leg,
    OUTRO_ROUTE_COLS to a row (the destination's photo, its name and where the
    leg started, and the travel mode, distance and time on the right). The
    page ends just below the last row."""
    width, height = size
    k = height / _CANVAS_H

    def px(value: float) -> int:
        return int(round(value * k))

    engine = _engine()
    bold = _GraphicsEngineBase.FONT_CANDIDATES_BOLD
    legs = brief["legs"]
    x0 = px(tuning.OUTRO_SCROLL_SIDE_PADDING)
    box_w = width - 2 * x0
    row_h = px(tuning.OUTRO_ROUTE_ROW_HEIGHT)
    row_gap = px(tuning.OUTRO_ROUTE_ROW_GAP)
    heading = heading or {}
    lines = _heading_lines(
        heading.get("title", project_name), heading.get("subtitle", ""),
        heading.get("title_style"), heading.get("subtitle_style"), height,
        heading.get("kicker", ""), heading.get("kicker_style"),
    )
    heading_top = px(30)
    panel_top = heading_top + _heading_height(lines, k) + px(30)
    panel_h = _summary_height(brief, px)
    legs_top = panel_top + panel_h + px(32)
    cols = tuning.OUTRO_ROUTE_COLS
    rows = math.ceil(len(legs) / cols)
    page_h = max(height, legs_top + rows * (row_h + row_gap) - row_gap + px(70))

    page = Image.new("RGB", (width, page_h), tuning.OUTRO_BG_COLOR)
    draw = ImageDraw.Draw(page)
    name_font = _load_font(bold, px(tuning.OUTRO_ROUTE_NAME_FONT_SIZE))
    from_font = _load_font(_GraphicsEngineBase.FONT_CANDIDATES_REGULAR, px(tuning.OUTRO_ROUTE_FROM_FONT_SIZE))
    chip_font = _load_font(bold, px(tuning.OUTRO_LEG_FONT_SIZE))
    badge_font = _load_font(bold, px(15))

    _draw_heading(draw, lines, width / 2, heading_top, box_w, k)
    _draw_summary(page, engine, brief, px, x0, box_w, panel_top, panel_h)

    pad = px(12)
    thumb_h = row_h - 2 * pad
    thumb_w = int(thumb_h * tuning.OUTRO_ROUTE_THUMB_ASPECT)
    icon = px(tuning.OUTRO_LEG_FONT_SIZE + 2)
    dist_font = _load_font(
        _GraphicsEngineBase.FONT_CANDIDATES_EXTRABOLD, px(tuning.OUTRO_ROUTE_DISTANCE_FONT_SIZE)
    )
    chip_ascent = chip_font.getmetrics()[0]
    dist_ascent = dist_font.getmetrics()[0]

    # OUTRO_ROUTE_COLS cards to a row, together as wide as the summary.
    col_gap = px(tuning.OUTRO_ROUTE_COL_GAP)
    card_w = (box_w - col_gap * (cols - 1)) // cols
    stats = [
        (
            _leg_modes(leg),
            "・".join(engine._mode_name_ja(m) for m in _leg_modes(leg)),
            _fmt_km(leg["km"]),
            engine._format_duration_ja(leg["minutes"] * 60),
        )
        for leg in legs
    ]
    # One stats column width for every card, so they line up down the page.
    stats_w = max(
        max(
            icon + px(6) + draw.textlength(mode_label, font=chip_font),
            draw.textlength(dist, font=dist_font),
            icon + px(6) + draw.textlength(dur, font=chip_font),
        )
        for _, mode_label, dist, dur in stats
    )
    line_gap = px(8)
    stats_h = chip_ascent + line_gap + dist_ascent + line_gap + chip_ascent

    for i, (leg, (modes, mode_label, dist, dur)) in enumerate(zip(legs, stats)):
        row, col = divmod(i, cols)
        top = legs_top + row * (row_h + row_gap)
        cx0 = x0 + col * (card_w + col_gap)
        stats_right = cx0 + card_w - px(18)
        divider_x = stats_right - stats_w - px(16)
        color = _mode_rgb(engine, modes[0])
        thumb_x, thumb_y = cx0 + pad, top + pad

        draw.rounded_rectangle(
            [cx0, top, cx0 + card_w, top + row_h], radius=px(16), fill=tuning.OUTRO_PANEL_COLOR,
        )

        image_path = _image_at(waypoints, leg.get("to_at") or [])
        thumb = (
            _rounded_thumbnail(image_path, (thumb_w, thumb_h), px(_CORNER_RADIUS))
            if image_path else None
        )
        if thumb is not None:
            page.paste(thumb, (thumb_x, thumb_y), thumb)
        else:
            draw.rounded_rectangle(
                [thumb_x, thumb_y, thumb_x + thumb_w, thumb_y + thumb_h],
                radius=px(_CORNER_RADIUS), fill=_mix(tuning.OUTRO_PANEL_COLOR, color, 0.18),
            )
            engine._draw_mode_icon(
                draw, modes[0], thumb_x + thumb_w / 2, thumb_y + thumb_h / 2, thumb_h // 2, color,
            )
        _draw_photo_badge(page, thumb_x + px(8), thumb_y + px(8), i + 1, badge_font, px)

        # Left: the destination name over where the leg started, centred on the card.
        text_x = thumb_x + thumb_w + px(16)
        text_w = divider_x - px(14) - text_x
        font, size = name_font, px(tuning.OUTRO_ROUTE_NAME_FONT_SIZE)
        while draw.textlength(leg["to"], font=font) > text_w and size > px(16):
            size -= 1
            font = _load_font(bold, size)
        from_size = px(tuning.OUTRO_ROUTE_FROM_FONT_SIZE)
        block = size + px(10) + from_size
        name_y = top + (row_h - block) / 2 - px(2)
        draw.text(
            (text_x, name_y), _truncate_to_width(draw, leg["to"], font, text_w),
            font=font, fill=tuning.OUTRO_TITLE_COLOR,
        )
        origin = _truncate_to_width(
            draw, tuning.OUTRO_ROUTE_FROM_TEMPLATE.format(name=leg["from"]), from_font, text_w,
        )
        draw.text(
            (text_x, name_y + size + px(10)), origin, font=from_font, fill=tuning.OUTRO_SUBTITLE_COLOR,
        )

        # Right: mode, distance and time, right-aligned behind a thin divider.
        draw.line(
            [(divider_x, top + px(22)), (divider_x, top + row_h - px(22))],
            fill=tuning.OUTRO_CHIP_COLOR, width=max(1, px(2)),
        )
        y = top + (row_h - stats_h) / 2 - px(2)
        mode_w = icon + px(6) + draw.textlength(mode_label, font=chip_font)
        engine._draw_mode_icon(
            draw, modes[0], stats_right - mode_w + icon / 2, y + chip_ascent / 2 + px(2), icon, color,
        )
        draw.text((stats_right, y), mode_label, font=chip_font, fill=color, anchor="ra")
        y += chip_ascent + line_gap
        draw.text((stats_right, y), dist, font=dist_font, fill=tuning.OUTRO_TITLE_COLOR, anchor="ra")
        y += dist_ascent + line_gap
        dur_w = icon + px(6) + draw.textlength(dur, font=chip_font)
        engine._draw_clock_icon(
            draw, stats_right - dur_w + icon / 2, y + chip_ascent / 2 + px(2), int(icon * 0.85),
            tuning.OUTRO_SUBTITLE_COLOR,
        )
        draw.text((stats_right, y), dur, font=chip_font, fill=tuning.OUTRO_LABEL_COLOR, anchor="ra")

    return page


def _draw_pin_icon(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color, hole) -> None:
    r = size * 0.3
    hy = cy - size * 0.12
    draw.ellipse([cx - r, hy - r, cx + r, hy + r], fill=color)
    draw.polygon([(cx - r * 0.9, hy + r * 0.45), (cx + r * 0.9, hy + r * 0.45), (cx, cy + size * 0.45)], fill=color)
    h = r * 0.42
    draw.ellipse([cx - h, hy - h, cx + h, hy + h], fill=hole)


def _summary_height(brief: Dict[str, Any], px) -> int:
    """Tiles only, plus a row for the split by mode when there is more than one."""
    h = px(100)
    return h + px(44) if len(_mode_totals(brief)) > 1 else h


def _draw_summary(
    page: Image.Image, engine, brief: Dict[str, Any], px, x0: int, box_w: int,
    top: int, panel_h: int,
) -> None:
    """A row of stat tiles (distance, time, places, longest leg), then, on a
    trip with more than one travel mode, each mode's distance, time and share."""
    draw = ImageDraw.Draw(page)
    bold = _GraphicsEngineBase.FONT_CANDIDATES_BOLD
    labels = tuning.OUTRO_SUMMARY_LABELS
    small_font = _load_font(_GraphicsEngineBase.FONT_CANDIDATES_REGULAR, px(14))
    legend_font = _load_font(bold, px(tuning.OUTRO_LEG_FONT_SIZE))
    value_font = _load_font(
        _GraphicsEngineBase.FONT_CANDIDATES_EXTRABOLD, px(tuning.OUTRO_SUMMARY_VALUE_FONT_SIZE)
    )
    muted, text = tuning.OUTRO_SUBTITLE_COLOR, tuning.OUTRO_LABEL_COLOR

    legs = brief["legs"]
    longest = max(legs, key=lambda leg: leg["km"])
    longest_mode = _leg_modes(longest)[0]
    accent = tuple(reversed(tuning.DEFAULT_MARKER_COLOR))
    stops = len({leg["to"] for leg in legs if not leg.get("is_return")})
    tiles = [
        (lambda d, cx, cy, s: engine._draw_total_icon(d, cx, cy, s, tuning.OUTRO_TITLE_COLOR),
         labels["distance"], _fmt_km(brief["total_km"]), labels["legs"].format(count=len(legs))),
        (lambda d, cx, cy, s: engine._draw_clock_icon(d, cx, cy, s, tuning.OUTRO_TITLE_COLOR),
         labels["time"], engine._format_duration_ja(brief["total_minutes"] * 60), labels["time_note"]),
        (lambda d, cx, cy, s: _draw_pin_icon(d, cx, cy, s, accent, tuning.OUTRO_PANEL_COLOR),
         labels["places"], labels["places_value"].format(count=stops), ""),
        (lambda d, cx, cy, s: engine._draw_mode_icon(d, longest_mode, cx, cy, s, _mode_rgb(engine, longest_mode)),
         labels["longest"], _fmt_km(longest["km"]), f"→ {longest['to']}"),
    ]

    # No outer frame: the tiles span the full width, like the cards below.
    pad, gap = 0, px(tuning.OUTRO_ROUTE_COL_GAP)
    tile_bg = tuning.OUTRO_PANEL_COLOR
    tile_h = px(100)
    tile_w = (box_w - 2 * pad - gap * (len(tiles) - 1)) / len(tiles)
    icon = px(30)
    ty = top + pad
    for i, (icon_fn, label, value, sub) in enumerate(tiles):
        tx = x0 + pad + i * (tile_w + gap)
        draw.rounded_rectangle([tx, ty, tx + tile_w, ty + tile_h], radius=px(16), fill=tile_bg)
        icon_fn(draw, tx + px(16) + icon / 2, ty + tile_h / 2, icon)
        text_x = tx + px(16) + icon + px(14)
        text_w = tx + tile_w - px(12) - text_x
        draw.text((text_x, ty + px(14)), label, font=small_font, fill=muted)
        # A long value shrinks to fit the tile, and is only cut past the minimum.
        font, size = value_font, px(tuning.OUTRO_SUMMARY_VALUE_FONT_SIZE)
        while draw.textlength(value, font=font) > text_w and size > px(16):
            size -= 1
            font = _load_font(_GraphicsEngineBase.FONT_CANDIDATES_EXTRABOLD, size)
        draw.text(
            (text_x, ty + px(34) + (px(tuning.OUTRO_SUMMARY_VALUE_FONT_SIZE) - size) * 0.6),
            _truncate_to_width(draw, value, font, text_w), font=font, fill=tuning.OUTRO_TITLE_COLOR,
        )
        if sub:
            draw.text(
                (text_x, ty + px(72)), _truncate_to_width(draw, sub, small_font, text_w),
                font=small_font, fill=muted,
            )

    # Split by travel mode, only when there is more than one.
    totals = _mode_totals(brief)
    if len(totals) < 2:
        return
    total_km = sum(km for _, km, _ in totals) or 1.0
    y = ty + tile_h + px(18)
    legend_icon = px(20)
    ascent = legend_font.getmetrics()[0]
    x = x0 + pad
    for mode, km, minutes in totals:
        color = _mode_rgb(engine, mode)
        engine._draw_mode_icon(draw, mode, x + legend_icon / 2, y + ascent / 2 + px(2), legend_icon, color)
        x += legend_icon + px(8)
        name = engine._mode_name_ja(mode)
        draw.text((x, y), name, font=legend_font, fill=color)
        x += draw.textlength(name, font=legend_font) + px(10)
        detail = (
            f"{_fmt_km(km)} ・ {engine._format_duration_ja(minutes * 60)} ・ "
            f"{round(100 * km / total_km)}%"
        )
        draw.text((x, y), detail, font=legend_font, fill=text)
        x += draw.textlength(detail, font=legend_font) + px(34)


def _scroll_offsets(
    distance: int, fps: int, scale: float = 1.0, end_hold: Optional[float] = None,
    start_hold: Optional[float] = None,
) -> List[int]:
    """The page's top offset for every frame: a hold on the first screen, a
    scroll that moves the SAME whole number of pixels every frame (with a
    short whole-step ease in and out), then a short hold at the end.

    A whole, constant step is what keeps moving text readable: a speed that
    isn't a whole number of px per frame alternates short and long steps
    (5, 6, 5, 6 ...), and the eye reads that uneven motion as judder.
    `scale` is the page's size relative to the 704-high canvas the tuning
    speed is given for. No scroll at all - one OUTRO_DURATION_SECONDS hold -
    when there is nothing to scroll."""
    if distance <= 0:
        return [0] * max(1, int(round(tuning.OUTRO_DURATION_SECONDS * fps)))
    step = max(1, int(round(tuning.OUTRO_SCROLL_SPEED_PX * scale / fps)))
    # A page too long for OUTRO_SCROLL_MAX_SECONDS at this pace takes bigger
    # (still constant) steps instead.
    step = max(step, math.ceil(distance / (tuning.OUTRO_SCROLL_MAX_SECONDS * fps)))

    # Ease: whole steps growing evenly up to the cruising step, over at most
    # half a second (1, 2, 3, 4 for a step of 5).
    n = min(step - 1, fps // 2)
    ramp = [max(1, int(round(step * (i + 1) / (n + 1)))) for i in range(n)]
    while ramp and 2 * sum(ramp) > distance:
        ramp.pop()
    cruise, rest = divmod(distance - 2 * sum(ramp), step)
    steps = ramp + [step] * cruise + ramp[::-1]
    if rest:
        # The leftover (< one step) as one small step where the ease-out
        # begins, where a shorter step reads as part of the slowdown.
        steps.insert(len(ramp) + cruise, rest)

    if start_hold is None:
        start_hold = tuning.OUTRO_SCROLL_START_HOLD_SECONDS
    offsets = [0] * int(round(start_hold * fps))
    top = 0
    for moved in steps:
        top += moved
        offsets.append(top)
    if end_hold is None:
        end_hold = tuning.OUTRO_SCROLL_END_HOLD_SECONDS
    offsets += [distance] * int(round(end_hold * fps))
    return offsets


def _write_scroll_clip(
    page: Image.Image, output_path: Path, fps: int, size: Tuple[int, int],
    end_hold: Optional[float] = None, start_hold: Optional[float] = None,
) -> bool:
    """Crops the tall page frame by frame at each _scroll_offsets offset,
    softens the top/bottom screen edges into the background, and pipes the
    raw frames straight into ffmpeg."""
    width, height = size
    k = height / _CANVAS_H
    page_px = np.asarray(page, dtype=np.uint8)
    offsets = _scroll_offsets(page_px.shape[0] - height, fps, k, end_hold, start_hold)

    # Per-row blend weight toward the background: 1 at the very edge, 0 once
    # OUTRO_SCROLL_EDGE_FADE_PX in.
    fade = max(1, int(round(tuning.OUTRO_SCROLL_EDGE_FADE_PX * k)))
    ramp = np.clip(1.0 - np.arange(fade, dtype=np.float32) / fade, 0.0, 1.0)
    bg = np.asarray(tuning.OUTRO_BG_COLOR, dtype=np.float32)

    ffmpeg_cmd = FFmpegManager.resolve_ffmpeg_bin()
    cmd = [
        ffmpeg_cmd, "-y", *tuning.ffmpeg_pipe_log_args(),
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
        "-r", str(fps), "-i", "-",
        "-c:v", "libx264", *tuning.ffmpeg_thread_args(), "-crf", "18", "-preset", "fast",
        "-pix_fmt", "yuv420p", str(output_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for top in offsets:
            frame = page_px[top: top + height].astype(np.float32)
            # The top fade grows in over the first `fade` px of scrolling, so
            # the title is never dimmed while the page sits on its first screen.
            top_weight = ramp * min(1.0, top / fade)
            frame[:fade] += (bg - frame[:fade]) * top_weight[:, None, None]
            frame[-fade:] += (bg - frame[-fade:]) * ramp[::-1][:, None, None]
            proc.stdin.write(frame.astype(np.uint8).tobytes())
        proc.stdin.close()
        stderr = proc.stderr.read().decode("utf-8", errors="replace")
        if proc.wait() != 0:
            logger.error("Outro generation failed: %s", stderr.strip())
            return False
    except Exception:
        proc.kill()
        raise
    return True


def generate_outro_clip(
    video_dir: str,
    project_name: str,
    waypoints: List[Dict[str, Any]],
    output_filename: str = tuning.OUTRO_OUTPUT_FILENAME,
    duration_sec: float = tuning.OUTRO_DURATION_SECONDS,
    style: str = tuning.DEFAULT_OUTRO_STYLE,
    size: Optional[Tuple[int, int]] = None,
    brief: Optional[Dict[str, Any]] = None,
    heading: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Builds the outro in `style` ("scroll" or "grid" - see the module
    docstring) as an mp4; duration_sec is the grid's hold (the scroll's own
    length follows the page). `size` is the finished video's frame size,
    which the scroll is drawn at (default: the 1280x704 canvas). `brief`
    (route_brief.build_brief) adds the per-leg route and trip summary, under
    `heading` (intro_step.intro_heading: kicker, title, subtitle and their
    styles, the intro's).
    Returns the output path, or None (logged,
    never raises) on any failure — an outro is a nice-to-have, not something
    that should hard-fail a pipeline run."""
    waypoints_with_image = [wp for wp in waypoints if wp.get("popup_image")]
    has_route = bool(brief and brief.get("legs"))
    if not waypoints_with_image and not (has_route and style == "scroll"):
        logger.warning("Outro: no waypoints with a popup_image — nothing to show.")
        return None

    video_dir_path = Path(video_dir)
    video_dir_path.mkdir(parents=True, exist_ok=True)
    output_path = video_dir_path / output_filename
    frame_path = video_dir_path / f".outro_frame_{Path(output_filename).stem}.png"

    try:
        if style == "scroll":
            size = size or (_CANVAS_W, _CANVAS_H)
            page = _build_scroll_page(project_name or "", waypoints_with_image, size, brief, heading)
            holds = (
                (tuning.OUTRO_ROUTE_END_HOLD_SECONDS, tuning.OUTRO_SUMMARY_HOLD_SECONDS)
                if has_route else (None, None)
            )
            if not _write_scroll_clip(page, output_path, tuning.INTRO_FPS, size, *holds):
                return None
            logger.info(
                "Outro clip generated: %s (%d places, scroll)", output_path, len(waypoints_with_image)
            )
            return str(output_path)

        frame = _build_frame(project_name or "", waypoints_with_image, brief)
        frame.save(frame_path)

        ffmpeg_cmd = FFmpegManager.resolve_ffmpeg_bin()
        cmd = [
            ffmpeg_cmd, "-y", *tuning.ffmpeg_log_args(),
            "-loop", "1", "-i", str(frame_path),
            "-t", f"{duration_sec:.3f}",
            "-c:v", "libx264", *tuning.ffmpeg_thread_args(), "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p",
            str(output_path),
        ]
        result = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", errors="replace"
        )
        if result.returncode != 0:
            logger.error("Outro generation failed: %s", result.stderr.strip())
            return None
    except Exception as exc:
        logger.error("Outro generation failed: %s", exc)
        return None
    finally:
        frame_path.unlink(missing_ok=True)

    logger.info("Outro clip generated: %s (%d places)", output_path, len(waypoints_with_image))
    return str(output_path)
