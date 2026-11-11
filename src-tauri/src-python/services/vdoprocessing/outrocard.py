"""Outro/end-card clip generator: the project title plus a numbered card for
every waypoint that has a popup image, as the video's closing clip. Two
styles (tuning.DEFAULT_OUTRO_STYLE / settings.outro_style):

- "scroll": cards three to a row in a centred column that slowly scrolls up,
  credits-style, under the pinned title until every card has faded out, then
  the logos alone, centred.
- "grid": one composited frame, every card squeezed onto a single screen,
  held for a fixed duration.
- "scrapbook": the stops' photos drop onto paper as polaroids, then a round
  stamp with the title, distance and travel time; then the logo end card.

Standalone (PIL-only compositing + a plain ffmpeg `-loop 1` hold), reusing
the same bundled Japanese-capable fonts as graphicengine/base.py rather
than duplicating font-candidate lists.
"""

from __future__ import annotations

import itertools
import math
import random
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps
from PIL.ImageFont import FreeTypeFont, load_default, truetype

from services.mapfetcher.graphicengine.base import _GraphicsEngineBase
from services.logger.logger import setup_logger
from services.tts.ttsengine import FFmpegManager
from services import tuning, video_text
from services.projectfiles import replace_into

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


def _word_edges(text: str) -> List[int]:
    """Where one word ends and the next starts (葛城|一言主|神社), so a wrapped name never leaves one character alone."""
    from services.localization.japanese_words import _tagger

    tagger = _tagger()
    if tagger is None:
        return []
    edges, pos = [], 0
    for token in tagger(text):
        at = text.find(token.surface, pos)
        if at < 0:
            continue
        pos = at + len(token.surface)
        if 0 < pos < len(text) and not (text[pos - 1].isascii() and text[pos - 1].isalpha() and text[pos].isascii() and text[pos].isalpha()):
            edges.append(pos)
    return edges


def _wrap_at(draw: ImageDraw.ImageDraw, text: str, breaks: List[int], font: FreeTypeFont, max_width: float) -> List[str]:
    """Greedy wrap: each line runs to the last break that still fits. [] when a piece is too wide alone."""
    lines, start, last = [], 0, None
    for i in breaks + [len(text)]:
        if draw.textlength(text[start:i].strip(), font=font) <= max_width:
            last = i
            continue
        if last is None:
            return []
        lines.append(text[start:last].strip())
        start, last = last, (i if draw.textlength(text[last:i].strip(), font=font) <= max_width else None)
        if last is None:
            return []
    return lines + [text[start:].strip()]


def _name_lines(
    draw: ImageDraw.ImageDraw, name: str, font_candidates, size: int, min_size: int, max_width: float
) -> Tuple[List[str], FreeTypeFont, int]:
    """A card's name on one line, else two split at a space or bracket, else between words, shrinking toward
    `min_size` until a split fits; else three lines wrapped at those breaks; at `min_size` it splits where the line
    fills and cuts the rest with "…"."""
    font = _load_font(font_candidates, size)
    if draw.textlength(name, font=font) <= max_width:
        return [name], font, size
    marks = [i for i in range(1, len(name)) if name[i] in tuning.OUTRO_NAME_BREAK_BEFORE or name[i - 1] in tuning.OUTRO_NAME_BREAK_AFTER]
    breaks = sorted(i for i in set(marks) | set(_word_edges(name)) if name[i - 1] not in tuning.OUTRO_NAME_NO_BREAK_AFTER)
    sizes = range(size, min_size - 1, -1)
    for s in sizes:
        font = _load_font(font_candidates, s)
        fits = lambda a: draw.textlength(a, font=font) <= max_width
        for edges in (marks, breaks):
            splits = sorted((abs(len(name) - 2 * i), name[:i].rstrip(), name[i:].lstrip()) for i in edges)
            splits = [p for p in splits if p[1] and p[2] and fits(p[1]) and fits(p[2])]
            if splits:
                return [splits[0][1], splits[0][2]], font, s
    for s in sizes:
        font = _load_font(font_candidates, s)
        lines = _wrap_at(draw, name, breaks, font, max_width)
        if lines and len(lines) <= 3:
            return lines, font, s
    cut = max(i for i in range(1, len(name) + 1) if draw.textlength(name[:i], font=font) <= max_width or i == 1)
    return [name[:cut], _truncate_to_width(draw, name[cut:].lstrip(), font, max_width)], font, min_size


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
        src = ImageOps.exif_transpose(Image.open(image_path)).convert("RGB")  # phone photos are stored sideways + a tag
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
    page: Image.Image, x: int, y: int, number: int | str, font: FreeTypeFont, px,
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


LOGO_DIR = Path(__file__).resolve().parents[2] / "assets" / "image" / "logo"


def trimmed_logo(path: Path, height: int) -> Optional[Image.Image]:
    """The logo cropped to its ink (near-white margins dropped) and scaled to
    `height`; None when it can't be read or is blank."""
    try:
        src = Image.open(path).convert("RGBA")
    except Exception as exc:
        logger.warning("Could not read logo '%s': %s", path, exc)
        return None
    flat = Image.new("RGBA", src.size, (255, 255, 255, 255))
    flat.alpha_composite(src)
    box = flat.convert("L").point(lambda v: 255 if v < 245 else 0).getbbox()
    if not box:
        return None
    src = src.crop(box)
    return src.resize((max(1, round(src.width * height / src.height)), height), Image.LANCZOS)


def _logo_plate(px, max_width: Optional[int] = None) -> Optional[Image.Image]:
    """Every logo in LOGO_DIR, trimmed and scaled to one height, side by side,
    each on its own rounded plate if OUTRO_LOGO_PLATE_COLOR is set; None when
    there are none. Scaled down as a whole when wider than `max_width`."""
    plate = _logo_row(px)
    if plate is not None and max_width and plate.width > max_width:
        plate = plate.resize(
            (max_width, max(1, round(plate.height * max_width / plate.width))), Image.LANCZOS,
        )
    return plate


def _logo_row(px) -> Optional[Image.Image]:
    height = px(tuning.OUTRO_LOGO_HEIGHT)
    paths = sorted(LOGO_DIR.glob("*.png")) if LOGO_DIR.is_dir() else []
    logos = [logo for logo in (trimmed_logo(p, height) for p in paths) if logo is not None]
    if not logos:
        return None
    pad, gap = px(tuning.OUTRO_LOGO_PLATE_PADDING), px(tuning.OUTRO_LOGO_GAP)
    w = sum(logo.width + 2 * pad for logo in logos) + gap * (len(logos) - 1)
    plate = Image.new("RGBA", (w, height + 2 * pad), (0, 0, 0, 0))
    draw = ImageDraw.Draw(plate)
    x = 0
    for logo in logos:
        if tuning.OUTRO_LOGO_PLATE_COLOR is not None:
            draw.rounded_rectangle(
                [x, 0, x + logo.width + 2 * pad - 1, plate.height - 1],
                radius=px(16), fill=tuning.OUTRO_LOGO_PLATE_COLOR,
            )
        plate.alpha_composite(logo, (x + pad, pad))
        x += logo.width + 2 * pad + gap
    return plate


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


def _outro_subtitle(count: int) -> str:
    return video_text.plural(video_text.current_labels(), "outro_subtitle", count, count=count)


def _totals_line(engine, brief: Dict[str, Any]) -> str:
    sep = video_text.current_labels()["separator"]
    return f"{_fmt_km(brief['total_km'])}{sep}{engine._format_duration_ja(brief['total_minutes'] * 60)}"


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

    subtitle = _outro_subtitle(len(waypoints))
    if brief and brief.get("legs"):
        subtitle += f"{video_text.current_labels()['separator']}{_totals_line(_engine(), brief)}"
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
            str(wp.get("label", f"{video_text.current_labels()['waypoint_fallback']} {idx + 1}")),
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
    header_h, header_color = _header_box(
        heading, height, px(_HEADER_HEIGHT),
        px(34 + tuning.OUTRO_TITLE_FONT_SIZE + 10 + tuning.OUTRO_SUBTITLE_FONT_SIZE + 20),
    )
    thumb_w = int((container_w - margin * (cols - 1)) / cols)
    thumb_h = int(thumb_w / tuning.OUTRO_CARD_ASPECT)
    label_h = label_size + px(16)
    row_h = thumb_h + label_h + margin
    rows = math.ceil(len(waypoints) / cols)
    page_h = header_h + rows * row_h + height

    page = Image.new("RGB", (width, page_h), tuning.OUTRO_BG_COLOR)
    page.info["header_h"] = header_h - px(10)
    page.info["pinned"] = (heading or {}).get("burn_text", True)
    draw = ImageDraw.Draw(page)
    if header_color:
        draw.rectangle([0, 0, width, header_h - px(10)], fill=header_color)
    if (heading or {}).get("burn_text", True):
        _center_text(draw, project_name, title_font, width / 2, px(34), tuning.OUTRO_TITLE_COLOR)
        _center_text(
            draw,
            _outro_subtitle(len(waypoints)),
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
        text = str(wp.get("label", f"{video_text.current_labels()['waypoint_fallback']} {idx + 1}"))
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


def header_height_1080(heading: Optional[Dict[str, Any]], has_route: bool) -> float:
    """The pinned box's height without a custom one, in 1080-line px: what _build_scroll_page /
    _build_route_page give `page.info["header_h"]` at a 1080-high frame."""
    k = 1080 / _CANVAS_H
    if not has_route:
        return (_HEADER_HEIGHT - 10) * k
    heading = heading or {}
    lines = _heading_lines(
        heading.get("title", ""), heading.get("subtitle", ""), heading.get("title_style"),
        heading.get("subtitle_style"), 1080, heading.get("kicker", ""), heading.get("kicker_style"),
    )
    return (30 + 30 - 10) * k + _heading_height(lines, k)


def _header_box(heading: Optional[Dict[str, Any]], height: int, natural: int, minimum: int = 0):
    """(pinned header height px, its fill colour) for the outro's title box. `heading["header_height"]`
    (settings.outro_header_height, in 1080-line units like the text sizes) replaces `natural`, but never
    goes under `minimum` (the title would be cut off) or over 80% of the frame (some card has to show); `heading["header_color"]` is a colour
    (settings.outro_header_color) or None for the page's own background."""
    from services.localization.text_style import parse_color

    heading = heading or {}
    try:
        custom = float(heading.get("header_height") or 0)
    except (TypeError, ValueError):
        custom = 0.0
    h = max(minimum, min(int(round(custom * height / 1080)), int(height * 0.8))) if custom > 0 else natural
    parsed = parse_color(heading.get("header_color")) if heading.get("header_color") else None
    return h, (parsed[0] if parsed else None)


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


def route_cards(legs: List[Dict[str, Any]]) -> List[Tuple[str, Optional[int]]]:
    """The route page's cards as (badge, leg index): S for the start (None), then each leg's destination 1, 2 ...
    with the last E. A leg back to a place already reached (a return stop) gets none, so a trip that ends where
    it began shows S only."""
    from services.vdoprocessing.route_inputs import same_place

    def at(p) -> Dict[str, Any]:
        return {"lat": p[0], "lng": p[1]} if p else {}

    if not legs:
        return []
    seen, kept = [at(legs[0].get("from_at"))], []
    for n, leg in enumerate(legs):
        here = at(leg.get("to_at"))
        if not any(same_place(here, s) for s in seen):
            seen.append(here)
            kept.append(n)
    cards: List[Tuple[str, Optional[int]]] = [("S", None)] + [(str(k + 1), n) for k, n in enumerate(kept)]
    if kept and kept[-1] == len(legs) - 1:
        cards[-1] = ("E", kept[-1])
    return cards


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
    natural_top = heading_top + _heading_height(lines, k) + px(30)
    header_h, header_color = _header_box(
        heading, height, natural_top - px(10), heading_top + _heading_height(lines, k) + px(4))
    panel_top = header_h + px(10)
    panel_h = _summary_height(brief, px)
    legs_top = panel_top + panel_h + px(32)
    cols = tuning.OUTRO_ROUTE_COLS
    sb_title_h = px(12) + px(tuning.OUTRO_STOPBY_TITLE_FONT_SIZE) + px(12)

    cards = route_cards(legs)
    # Leg cards OUTRO_ROUTE_COLS to a row; after the last one, a title and
    # every stop-by in route order (the start pin's first) as shorter cards.
    rows: List[Tuple[str, List[Any]]] = [
        ("legs", list(range(n, min(n + cols, len(cards))))) for n in range(0, len(cards), cols)
    ]
    stopbys = _stopbys(brief, "start_batch", "start_batch_at")
    for leg in legs:
        stopbys += _stopbys(leg, "batch", "batch_at")
    if stopbys:
        rows.append(("title", []))
        rows.extend(("stopbys", stopbys[n:n + cols]) for n in range(0, len(stopbys), cols))
    # Then the closed places (the editor's "Closed"), their own section with a × badge.
    closed = _stopbys(brief, "closed", "closed_at")
    if closed:
        rows.append(("closed_title", []))
        rows.extend(("closed", closed[n:n + cols]) for n in range(0, len(closed), cols))

    row_tops, y = [], legs_top
    for kind, _ in rows:
        row_tops.append(y)
        y += sb_title_h if kind in ("title", "closed_title") else row_h + row_gap
    page_h = max(height, y - row_gap + px(70))

    page = Image.new("RGB", (width, page_h), tuning.OUTRO_BG_COLOR)
    page.info["header_h"] = panel_top - px(10)
    page.info["pinned"] = heading.get("burn_text", True)  # False: no box in the video, the text item's box does it
    draw = ImageDraw.Draw(page)
    if header_color:
        draw.rectangle([0, 0, width, panel_top - px(10)], fill=header_color)
    from_font = _load_font(_GraphicsEngineBase.FONT_CANDIDATES_REGULAR, px(tuning.OUTRO_ROUTE_FROM_FONT_SIZE))
    chip_font = _load_font(bold, px(tuning.OUTRO_LEG_FONT_SIZE))
    badge_font = _load_font(bold, px(15))

    if heading.get("burn_text", True):  # False: the title is a text-track item (outro_step.outro_text_item)
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
            video_text.current_labels()["mode_join"].join(engine._mode_name_ja(m) for m in _leg_modes(leg)),
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

    title_font = _load_font(bold, px(tuning.OUTRO_STOPBY_TITLE_FONT_SIZE))
    slots = []
    number = 0  # stop-bys are numbered +1, +2 ... after the leg cards
    for (kind, items), top in zip(rows, row_tops):
        if kind in ("title", "closed_title"):
            draw.text(
                (x0, top + px(12)),
                video_text.current_labels()["outro_stopby_title" if kind == "title" else "outro_closed_title"],
                font=title_font, fill=tuning.OUTRO_LABEL_COLOR,
            )
        for col, item in enumerate(items):
            cx0 = x0 + col * (card_w + col_gap)
            if kind == "stopbys":
                number += 1
                _draw_stopby_card(page, waypoints, item, cx0, top, card_w, px, f"+{number}", badge_font)
            elif kind == "closed":
                _draw_stopby_card(page, waypoints, item, cx0, top, card_w, px, "×", badge_font)
            else:
                slots.append((item, cx0, top))

    for i, cx0, top in slots:
        badge, leg_index = cards[i]
        start_card = leg_index is None
        # The S card: the start's photo and name, no leg stats.
        leg = (
            {"to": legs[0]["from"], "to_at": legs[0].get("from_at"), "from": ""} if start_card else legs[leg_index]
        )
        modes, mode_label, dist, dur = stats[0 if start_card else leg_index]
        stats_right = cx0 + card_w - px(18)
        divider_x = cx0 + card_w - px(18) if start_card else stats_right - stats_w - px(16)
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
        _draw_photo_badge(page, thumb_x + px(8), thumb_y + px(8), badge, badge_font, px)

        # Left: the destination name over where the leg started, centred on the card.
        text_x = thumb_x + thumb_w + px(16)
        text_w = divider_x - px(14) - text_x
        lines, font, size = _name_lines(draw, leg["to"], bold, px(tuning.OUTRO_ROUTE_NAME_FONT_SIZE), px(16), text_w)
        line_h = size + px(4)
        from_size = px(tuning.OUTRO_ROUTE_FROM_FONT_SIZE)
        block = len(lines) * line_h - px(4) + px(10) + from_size
        name_y = top + (row_h - block) / 2 - px(2)
        for n, line in enumerate(lines):
            draw.text((text_x, name_y + n * line_h), line, font=font, fill=tuning.OUTRO_TITLE_COLOR)
        labels = video_text.current_labels()
        origin = _truncate_to_width(
            draw, labels["overview_start"] if start_card else labels["outro_route_from"].format(name=leg["from"]),
            from_font, text_w,
        )
        draw.text(
            (text_x, name_y + block - from_size), origin, font=from_font, fill=tuning.OUTRO_SUBTITLE_COLOR,
        )
        if start_card:
            continue

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


def _stopbys(source: Dict[str, Any], names_key: str, at_key: str) -> List[Tuple[str, Any, str]]:
    """(name, [lat, lng], short fact) of each stop-by a brief entry hosts."""
    names = source.get(names_key) or []
    places = source.get(at_key) or []
    facts = source.get(f"{names_key}_facts") or []
    return [
        (name, places[n] if n < len(places) else None, facts[n] if n < len(facts) else "")
        for n, name in enumerate(names)
    ]


def _draw_stopby_card(
    page: Image.Image, waypoints: List[Dict[str, Any]], stopby: Tuple[str, Any, str],
    x: int, y: int, card_w: int, px, number: str, badge_font: FreeTypeFont,
) -> None:
    """A stop-by's card, sized like a leg card: numbered photo, name, its short fact."""
    name, at, fact = stopby
    draw = ImageDraw.Draw(page)
    row_h = px(tuning.OUTRO_ROUTE_ROW_HEIGHT)
    name_size = px(tuning.OUTRO_ROUTE_NAME_FONT_SIZE)
    bold = _GraphicsEngineBase.FONT_CANDIDATES_BOLD
    fact_size = px(tuning.OUTRO_ROUTE_FROM_FONT_SIZE)
    fact_font = _load_font(_GraphicsEngineBase.FONT_CANDIDATES_REGULAR, fact_size)
    muted = tuning.OUTRO_SUBTITLE_COLOR
    pad = px(12)
    thumb_h = row_h - 2 * pad
    thumb_w = int(thumb_h * tuning.OUTRO_ROUTE_THUMB_ASPECT)
    draw.rounded_rectangle([x, y, x + card_w, y + row_h], radius=px(16), fill=tuning.OUTRO_PANEL_COLOR)

    image_path = _image_at(waypoints, at) if at else None
    tile = _rounded_thumbnail(image_path, (thumb_w, thumb_h), px(_CORNER_RADIUS)) if image_path else None
    if tile is not None:
        page.paste(tile, (x + pad, y + pad), tile)
    else:
        well = _mix(tuning.OUTRO_PANEL_COLOR, muted, 0.15)
        draw.rounded_rectangle(
            [x + pad, y + pad, x + pad + thumb_w, y + pad + thumb_h], radius=px(_CORNER_RADIUS), fill=well,
        )
        _draw_pin_icon(draw, x + pad + thumb_w / 2, y + pad + thumb_h / 2, thumb_h * 0.5, muted, well)
    _draw_photo_badge(page, x + pad + px(8), y + pad + px(8), number, badge_font, px)

    text_x = x + pad + thumb_w + px(16)
    text_w = x + card_w - px(18) - text_x
    lines, font, size = _name_lines(draw, name, bold, name_size, px(16), text_w)
    line_h = size + px(4)
    names_h = len(lines) * line_h - px(4)
    block = names_h + (px(10) + fact_size if fact else 0)
    ty = y + (row_h - block) / 2 - px(2)
    for n, line in enumerate(lines):
        draw.text((text_x, ty + n * line_h), line, font=font, fill=tuning.OUTRO_TITLE_COLOR)
    if fact:
        draw.text(
            (text_x, ty + names_h + px(10)), _truncate_to_width(draw, fact, fact_font, text_w),
            font=fact_font, fill=muted,
        )


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
    labels = video_text.current_labels()["outro_summary"]
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
    stops = len(route_cards(legs))  # every card, start and end too: no return stops, a round trip's start once
    tiles = [
        (lambda d, cx, cy, s: engine._draw_total_icon(d, cx, cy, s, tuning.OUTRO_TITLE_COLOR),
         labels["distance"], _fmt_km(brief["total_km"]), video_text.plural(labels, "legs", len(legs), count=len(legs))),
        (lambda d, cx, cy, s: engine._draw_clock_icon(d, cx, cy, s, tuning.OUTRO_TITLE_COLOR),
         labels["time"], engine._format_duration_ja(brief["total_minutes"] * 60), labels["time_note"]),
        (lambda d, cx, cy, s: _draw_pin_icon(d, cx, cy, s, accent, tuning.OUTRO_PANEL_COLOR),
         labels["places"], video_text.plural(labels, "places_value", stops, count=stops), ""),
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
        sep = video_text.current_labels()["separator"]
        detail = (
            f"{_fmt_km(km)}{sep}{engine._format_duration_ja(minutes * 60)}{sep}"
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


def _end_card(
    size: Tuple[int, int], background: Optional[Image.Image] = None, text_color=tuning.OUTRO_SUBTITLE_COLOR,
) -> Optional[np.ndarray]:
    """The logos under a small "Powered by" title, centred on the background
    (the outro's plain colour unless given); None without logos."""
    width, height = size
    k = height / _CANVAS_H

    def px(value: float) -> int:
        return int(round(value * k))

    logos = _logo_plate(px, int(width * tuning.OUTRO_LOGO_MAX_WIDTH))
    if logos is None:
        return None
    font_size = px(tuning.OUTRO_LOGO_TITLE_FONT_SIZE)
    font = _load_font(_GraphicsEngineBase.FONT_CANDIDATES_BOLD, font_size)
    gap = px(tuning.OUTRO_LOGO_TITLE_GAP)
    top = (height - (font_size + gap + logos.height)) // 2
    card = background.convert("RGB") if background is not None else Image.new("RGB", size, tuning.OUTRO_BG_COLOR)
    _center_text(
        ImageDraw.Draw(card), video_text.current_labels()["outro_logo_title"], font,
        width / 2, top, text_color,
    )
    card.paste(logos, ((width - logos.width) // 2, top + font_size + gap), logos)
    return np.asarray(card, dtype=np.float32)


def end_card_seconds() -> float:
    """How long the logo end card lasts after the scroll (0 without logos)."""
    if _end_card((_CANVAS_W, _CANVAS_H)) is None:
        return 0.0
    return tuning.OUTRO_LOGO_FADE_SECONDS + tuning.OUTRO_LOGO_HOLD_SECONDS


def _write_scroll_clip(
    page: Image.Image, output_path: Path, fps: int, size: Tuple[int, int],
    start_hold: Optional[float] = None,
) -> bool:
    """Crops the tall page frame by frame at each _scroll_offsets offset, with
    the title (the page's top `header_h` rows) pinned in a box that the cards
    fade out under (no box when the page is not `pinned`), and pipes the raw frames straight into ffmpeg. Once every
    card is gone the title fades into the logo end card."""
    width, height = size
    k = height / _CANVAS_H
    # Not pinned: the title is a timeline text item whose box covers these same top rows. They are kept
    # plain background, so nothing shows there once that box ends, and the scroll ends when the cards are under it.
    pinned = bool(page.info.get("pinned", True))
    header_h = int(page.info.get("header_h", 0))
    page_px = np.asarray(page, dtype=np.uint8)
    bg = np.asarray(tuning.OUTRO_BG_COLOR, dtype=np.float32)

    # Scroll until the last non-background row has passed under the box.
    content = np.flatnonzero((page_px[header_h:] != bg.astype(np.uint8)).any(axis=(1, 2)))
    distance = int(content[-1]) + 1 if content.size else 0
    if page_px.shape[0] < distance + height:
        pad = np.empty((distance + height - page_px.shape[0], width, 3), dtype=np.uint8)
        pad[:] = bg.astype(np.uint8)
        page_px = np.concatenate([page_px, pad])
    end_card = _end_card(size)
    offsets = _scroll_offsets(distance, fps, k, 0.0 if end_card is not None else None, start_hold)

    # Per-row blend weight toward the background: 1 at the box / bottom edge,
    # 0 once OUTRO_SCROLL_EDGE_FADE_PX in.
    fade = max(1, int(round(tuning.OUTRO_SCROLL_EDGE_FADE_PX * k)))
    ramp = np.clip(1.0 - np.arange(fade, dtype=np.float32) / fade, 0.0, 1.0)
    header = page_px[:header_h].astype(np.float32) if pinned else np.broadcast_to(bg, (header_h, width, 3))

    def frame_at(top: int) -> np.ndarray:
        frame = page_px[top: top + height].astype(np.float32)
        # The fade grows in over the first `fade` px of scrolling, so nothing
        # is dimmed while the page sits on its first screen.
        if pinned:
            band = frame[header_h: header_h + fade]
            band += (bg - band) * (ramp[: len(band)] * min(1.0, top / fade))[:, None, None]
        frame[-fade:] += (bg - frame[-fade:]) * ramp[::-1][:, None, None]
        frame[:header_h] = header
        return frame

    frames = (frame_at(top) for top in offsets)
    if end_card is not None:
        last = frame_at(offsets[-1])
        steps = max(1, int(round(tuning.OUTRO_LOGO_FADE_SECONDS * fps)))
        fades = (last + (end_card - last) * ((i + 1) / steps) for i in range(steps))
        hold = (end_card for _ in range(int(round(tuning.OUTRO_LOGO_HOLD_SECONDS * fps))))
        frames = itertools.chain(frames, fades, hold)
    return _pipe_frames(frames, output_path, fps, size)


def _pipe_frames(frames, output_path: Path, fps: int, size: Tuple[int, int]) -> bool:
    """RGB frames (float or uint8 arrays) piped straight into an h264 mp4."""
    width, height = size
    cmd = [
        FFmpegManager.resolve_ffmpeg_bin(), "-y", *tuning.ffmpeg_pipe_log_args(),
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
        "-r", str(fps), "-i", "-",
        "-c:v", "libx264", *tuning.ffmpeg_thread_args(), "-crf", "18", "-preset", "fast",
        "-pix_fmt", "yuv420p", str(output_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for frame in frames:
            proc.stdin.write(np.asarray(frame).astype(np.uint8).tobytes())
        proc.stdin.close()
        stderr = proc.stderr.read().decode("utf-8", errors="replace")
        if proc.wait() != 0:
            logger.error("Outro generation failed: %s", stderr.strip())
            return False
    except Exception:
        proc.kill()
        raise
    return True


def scrapbook_layout(count: int, size: Tuple[int, int], top: float = 0.0, position: float = 0.5):
    """(card width, [(cx, cy, degrees)] per card, (cx, cy, radius) of the stamp): a loose grid below `top`
    (px kept for the heading), rows snaking left-right-left with the cell after the last card kept for the stamp, columns chosen so the cards
    come out as big as possible. `position`: where the cards sit in the room left below `top`, 0 = top, 1 = bottom."""
    width, height = size
    rng = random.Random(7)
    best = None
    for cols in range(2, 9):
        rows = math.ceil((count + 1) / cols)
        cell_w, cell_h = width * 0.97 / cols, (height - top) * 0.96 / rows
        # Nearly a full cell: neighbouring polaroids only just overlap, as in a real scrapbook.
        card_w = min(cell_w, cell_h / _POLAROID_RATIO) * tuning.OUTRO_SCRAPBOOK_CARD_FILL
        if best is None or card_w > best[0]:
            best = (card_w, cols, rows, cell_w, cell_h)
    card_w, cols, rows, cell_w, cell_h = best
    # Rows only as far apart as the cards need; the block sits at `position` in the room that leaves.
    cell_h = min(cell_h, card_w * _POLAROID_RATIO * 1.22)
    x0, y0 = width * 0.015, top + (height - top - rows * cell_h) * min(max(position, 0.0), 1.0)
    # Every other row runs right to left, so the route line snakes from row to row instead of crossing back.
    cells = [(c if r % 2 == 0 else cols - 1 - c, r) for r in range(rows) for c in range(cols)]
    stamp_cell = cells[count] if count < len(cells) else cells[-1]  # right after the last stop
    cards = []
    for c, r in cells[:count]:
        jx, jy = rng.uniform(-0.05, 0.05) * cell_w, rng.uniform(-0.04, 0.04) * cell_h
        # Neighbours lean opposite ways, so each card's edge stands out where they overlap.
        tilt = rng.uniform(3, 8) * (1 if (c + r) % 2 else -1)
        cards.append((x0 + (c + 0.5) * cell_w + jx, y0 + (r + 0.5) * cell_h + jy, tilt))
    sc, sr = stamp_cell
    stamp = (x0 + (sc + 0.5) * cell_w, y0 + (sr + 0.5) * cell_h, min(cell_w, cell_h) * 0.5)
    return card_w, cards, stamp


_INK = tuning.OUTRO_SCRAPBOOK_INK  # scrapbook text on paper
SCRAPBOOK_HEADING_SIZES = (64, 34)  # title, subtitle px at 1080p (the text item's default sizes)
SCRAPBOOK_HEADING_MARGIN = 24  # px from the top
_POLAROID_RATIO = 1.0  # card height / width: a 4:3 photo plus the white frame and name strip


def _polaroid(path: str, badge: str, name: str, card_w: int, badge_color=tuning.OUTRO_BADGE_COLOR) -> Optional[Image.Image]:
    border = max(4, card_w // 24)
    pw = card_w - 2 * border
    ph = int(pw * 3 / 4)
    thumb = _rounded_thumbnail(path, (pw, ph), 2)
    if thumb is None:
        return None
    card_h = int(card_w * _POLAROID_RATIO)
    card = Image.new("RGBA", (card_w, card_h), (255, 255, 255, 255))
    card.alpha_composite(thumb, (border, border))
    draw = ImageDraw.Draw(card)
    bold = _GraphicsEngineBase.FONT_CANDIDATES_BOLD
    size = max(10, card_w // 10)
    r, gap = size * 0.62, size * 0.35
    # A long name goes on two lines (split between words) beside the badge.
    lines, font, _ = _name_lines(draw, name, bold, size, max(8, card_w // 15), card_w - 2 * border - 2 * r - gap)
    line_h = font.size * 1.2
    block_w = max(draw.textlength(line, font=font) for line in lines)
    left = (card_w - (2 * r + gap + block_w)) / 2
    cy = (border + ph + card_h) / 2
    draw.ellipse([left, cy - r, left + 2 * r, cy + r], fill=badge_color)
    draw.text((left + r, cy), badge, font=_load_font(bold, int(r * 1.15)), fill="white", anchor="mm")
    for k, line in enumerate(lines):
        draw.text((left + 2 * r + gap, cy + (k - (len(lines) - 1) / 2) * line_h), line, font=font, fill=_INK, anchor="lm")
    blur = max(4, card_w // 30)
    out = _with_shadow(card, blur)
    # A strip of masking tape across the top edge holds it to the page.
    rng = random.Random(f"{badge}{name}")
    tape = Image.new("RGBA", (int(card_w * 0.36), max(6, int(card_w * 0.11))), tuning.OUTRO_SCRAPBOOK_TAPE_COLOR)
    tape = tape.rotate(rng.uniform(-7, 7), resample=Image.BICUBIC, expand=True)
    out.alpha_composite(tape, (int((out.width - tape.width) / 2 + rng.uniform(-0.1, 0.1) * card_w), max(0, blur * 3 - tape.height // 2)))
    return out


def _with_shadow(img: Image.Image, blur: int) -> Image.Image:
    pad = blur * 3
    out = Image.new("RGBA", (img.width + 2 * pad, img.height + 2 * pad), (0, 0, 0, 0))
    out.paste((0, 0, 0, 80), (pad, pad + blur, pad + img.width, pad + blur + img.height))
    out = out.filter(ImageFilter.GaussianBlur(blur))
    out.alpha_composite(img, (pad, pad))
    return out


def _stamp(radius: int, lines: List[str]) -> Image.Image:
    """A round ink stamp: the title big, then each further line smaller."""
    color = (*tuning.OUTRO_SCRAPBOOK_STAMP_COLOR, 235)
    size = 2 * radius + 4
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    c = size / 2
    draw.ellipse([2, 2, size - 3, size - 3], outline=color, width=max(3, radius // 17))
    inner = radius * 0.86
    draw.ellipse([c - inner, c - inner, c + inner, c + inner], outline=color, width=max(1, radius // 55))
    bold = _GraphicsEngineBase.FONT_CANDIDATES_BOLD
    sizes = [radius * 0.42] + [radius * 0.25] * (len(lines) - 1)
    fonts = []
    for text, fs in zip(lines, sizes):
        font = _load_font(bold, int(fs))
        while font.size > 8 and draw.textlength(text, font=font) > inner * 1.7:
            font = _load_font(bold, font.size - 2)
        fonts.append(font)
    gap = radius * 0.06
    total = sum(f.size for f in fonts) + gap * (len(fonts) - 1)
    y = c - total / 2
    for text, font in zip(lines, fonts):
        draw.text((c, y + font.size / 2), text, font=font, fill=color, anchor="mm")
        y += font.size + gap
    return img


def _foot(length: float, color) -> Image.Image:
    """One right footprint, toes up, like the 👣 icon: the front of the foot leaning out, the heel apart below it.
    Drawn at 4x and shrunk, so its edges stay smooth."""
    w, h = max(6, int(length * 0.46)), max(10, int(length))
    big = Image.new("RGBA", (w * 4, h * 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    W, H = w * 4, h * 4
    d.ellipse([W * 0.08, 0, W, H * 0.62], fill=color)
    d.ellipse([W * 0.12, H * 0.68, W * 0.78, H - 1], fill=color)
    return big.resize((w, h), Image.LANCZOS)


def _footsteps(a, b, bend: float, color, foot: float, step: float, trim: float = 0.0) -> List[Tuple[Image.Image, int, int]]:
    """(image, left, top) of each footprint walking from a to b along a gentle curve (the bend is a share of its
    length, sideways), in walking order, left and right in turn, each turned the way it walks; none in the last `trim` px."""
    (x1, y1), (x2, y2) = a, b
    qx, qy = (x1 + x2) / 2 - (y2 - y1) * bend, (y1 + y2) / 2 + (x2 - x1) * bend
    n = max(8, int(math.hypot(x2 - x1, y2 - y1) / 3))
    pts = [((1 - t) ** 2 * x1 + 2 * (1 - t) * t * qx + t * t * x2, (1 - t) ** 2 * y1 + 2 * (1 - t) * t * qy + t * t * y2)
           for t in (i / n for i in range(n + 1))]
    total = sum(math.dist(p, q) for p, q in zip(pts, pts[1:]))
    right = _foot(foot, color)
    left = ImageOps.mirror(right)
    s, next_at, side, out = 0.0, step / 2, 1, []
    for p, q in zip(pts, pts[1:]):
        seg = math.dist(p, q)
        while seg and next_at <= s + seg and next_at < total - trim:
            u = (next_at - s) / seg
            dx, dy = (q[0] - p[0]) / seg, (q[1] - p[1]) / seg
            # Left and right feet sit either side of the path, toes along it.
            x, y = p[0] + dx * u * seg - dy * side * foot * 0.28, p[1] + dy * u * seg + dx * side * foot * 0.28
            im = (right if side > 0 else left).rotate(-math.degrees(math.atan2(dy, dx)) - 90, resample=Image.BICUBIC, expand=True)
            out.append((im, int(x - im.width / 2), int(y - im.height / 2)))
            next_at += step
            side = -side
        s += seg
    return out


def _seal(size: int, text: str) -> Image.Image:
    """A worn red square seal (hanko) with up to two characters stacked in pale ink, turned a little."""
    big = size * 2
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 6, big - 6, big - 6], radius=big // 12, fill=(*tuning.OUTRO_SCRAPBOOK_STAMP_COLOR, 235))
    chars = list(text[:2])
    font = _load_font(_GraphicsEngineBase.FONT_CANDIDATES_BOLD, int(big * (0.38 if len(chars) > 1 else 0.62)))
    for i, ch in enumerate(chars):
        d.text((big / 2, big * ((0.3 + 0.4 * i) if len(chars) > 1 else 0.5)), ch, font=font, fill=(250, 240, 228, 255), anchor="mm")
    alpha = np.asarray(img.getchannel("A"), np.float32)
    wear = np.random.default_rng(len(text)).random(alpha.shape)
    img.putalpha(Image.fromarray((alpha * np.where(wear < 0.12, 0.45, 1.0)).astype(np.uint8)))
    return img.resize((size, size), Image.LANCZOS).rotate(8, resample=Image.BICUBIC, expand=True)


def seal_text(title: str) -> str:
    """The seal's characters: the last two of the heading's first line when they are kanji, else none (no seal)."""
    tail = (title or "").strip()[-2:]
    return tail if len(tail) == 2 and all(0x4E00 <= ord(c) <= 0x9FFF for c in tail) else ""


def _heading_decor(width: int, top: float, k: float, lines: List[Tuple[str, Any, float]]) -> Image.Image:
    """What sits behind and around the scrapbook's heading: soft mountain ridges fading out above the cards, a red
    sun, a small torii on the ridge, a pine sprig, and a red seal beside the heading's biggest line (seal_text).
    `lines`: (text, font, centre y) of each heading line. Drawn at 2x and shrunk, so the edges stay smooth."""
    z = 2
    h = int(top + 30 * k)
    img = Image.new("RGBA", (width * z, h * z), (0, 0, 0, 0))
    ink = (150, 118, 96)
    xs = np.arange(0, width * z + 1, 6, dtype=np.float32)

    def ridge(base_y, peaks):
        y = np.full_like(xs, base_y * z)
        for cx, ph, pw in peaks:
            y -= ph * k * z * np.exp(-(((xs - cx * width * z) / (pw * width * z)) ** 2))
        return y

    fade = np.clip((np.arange(h * z)[:, None] - top * 0.55 * z) / ((h - top * 0.55) * z), 0, 1)  # 0 high up .. 1 at the cards
    for base_y, peaks, a in (
        (top * 0.95, ((0.12, 120, 0.09), (0.3, 80, 0.07), (0.72, 140, 0.1), (0.9, 95, 0.07)), 46),
        (top * 1.0, ((0.05, 60, 0.06), (0.22, 95, 0.08), (0.55, 55, 0.1), (0.84, 110, 0.08)), 70),
    ):
        ys = ridge(base_y, peaks)
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).polygon(list(zip(xs, ys)) + [(width * z, h * z), (0, h * z)], fill=(*ink, a))
        ImageDraw.Draw(layer).line(list(zip(xs, ys)), fill=(*ink, a + 50), width=int(2 * k * z))
        # Fades out downward, so the cards sit on clean paper.
        mask = np.asarray(layer.getchannel("A"), np.float32) * (1 - fade) ** 1.5
        layer.putalpha(Image.fromarray(mask.astype(np.uint8)))
        img.alpha_composite(layer)
        front = ys
    d = ImageDraw.Draw(img)
    # Sun, upper left.
    r = 46 * k * z
    sx, sy = width * z * 0.2, top * 0.35 * z
    d.ellipse([sx - r, sy - r, sx + r, sy + r], outline=(*tuning.OUTRO_SCRAPBOOK_STAMP_COLOR, 150), width=int(3 * k * z))
    # A small torii standing on the front ridge.
    tx = width * z * 0.3
    ty = float(np.interp(tx, xs, front))
    tw, th, lw = 60 * k * z, 70 * k * z, int(5 * k * z)
    col = (*ink, 170)
    d.line([(tx - tw, ty - th), (tx + tw, ty - th)], fill=col, width=lw + 2)
    d.line([(tx - tw * 0.8, ty - th * 0.75), (tx + tw * 0.8, ty - th * 0.75)], fill=col, width=lw)
    d.line([(tx - tw * 0.55, ty - th), (tx - tw * 0.6, ty)], fill=col, width=lw)
    d.line([(tx + tw * 0.55, ty - th), (tx + tw * 0.6, ty)], fill=col, width=lw)
    # A pine sprig, upper right.
    px, py, n = width * z * 0.8, top * 0.3 * z, 7
    d.line([(px - 80 * k * z, py + 60 * k * z), (px + 70 * k * z, py - 40 * k * z)], fill=col, width=int(3 * k * z))
    for i in range(n):
        cx, cy = px - 70 * k * z + i * 21 * k * z, py + 53 * k * z - i * 14 * k * z
        for ang in range(-150, -29, 30):
            a = math.radians(ang)
            d.line([(cx, cy), (cx + 24 * k * z * math.cos(a), cy + 24 * k * z * math.sin(a))], fill=col, width=int(2 * k * z))
    img = img.resize((width, h), Image.LANCZOS)
    if lines and seal_text(lines[0][0]):
        text, font, cy = max(lines, key=lambda line: line[1].size)
        probe = ImageDraw.Draw(img)
        seal = _seal(int(font.size * 1.05), seal_text(lines[0][0]))
        x = width / 2 + probe.textlength(text, font=font) / 2 + 28 * k
        img.alpha_composite(seal, (int(min(x, width - seal.width - 8)), int(max(0, cy - seal.height / 2))))
    return img


def _ease(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def _place(canvas: Image.Image, img: Image.Image, cx: float, cy: float, scale: float, alpha: float, angle: float):
    if scale <= 0.01 or alpha <= 0.01:
        return
    im = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.BILINEAR)
    im = im.rotate(angle, resample=Image.BICUBIC, expand=True)
    if alpha < 1:
        im.putalpha(im.getchannel("A").point(lambda v: int(v * alpha)))
    canvas.alpha_composite(im, (int(cx - im.width / 2), int(cy - im.height / 2)))


def _write_scrapbook_clip(
    title: str, waypoints: List[Dict[str, Any]], brief: Optional[Dict[str, Any]],
    output_path: Path, fps: int, size: Tuple[int, int], colors: Optional[Dict[str, Any]] = None,
    heading: Optional[Dict[str, Any]] = None,
) -> bool:
    """Footprints walk the route across the paper and each stop's polaroid (S, 1, 2 … E) pops up as they reach it, then a round stamp with the title,
    distance and travel time lands in the bottom-right cell; then the logo end card, as after the scroll."""
    width, height = size
    stops = [(badge, wp) for badge, wp in _route_badges(waypoints) if _first_image(wp)][: tuning.OUTRO_MAX_CARDS]
    # The title and subtitle across the top: a text-track item the editor can restyle (outro_step), or burned
    # in (burn_text) when the caller wants them in the video. Either way the cards keep below their band.
    k = height / 1080
    sizes = [(heading or {}).get(f"{w}_size") or d for w, d in zip(("title", "subtitle"), SCRAPBOOK_HEADING_SIZES)]
    head = [(t, f) for t, f in (
        ((heading or {}).get("title") or "", _load_font(_GraphicsEngineBase.FONT_CANDIDATES_BOLD, int(sizes[0] * k))),
        ((heading or {}).get("subtitle") or "", _load_font(_GraphicsEngineBase.FONT_CANDIDATES_REGULAR, int(sizes[1] * k))),
    ) if t.strip()]
    top = (sum(f.size * 1.3 for _, f in head) + (SCRAPBOOK_HEADING_MARGIN + 16) * k) if head else 0.0
    decor_lines, y = [], SCRAPBOOK_HEADING_MARGIN * k
    for text, font in head:
        decor_lines.append((text, font, y + font.size * 0.65))
        y += font.size * 1.3
    if not (heading or {}).get("burn_text", True):
        head = []
    position = (heading or {}).get("content_position")
    card_w, spots, (sx, sy, sr) = scrapbook_layout(len(stops), size, top, float(position) if isinstance(position, (int, float)) else 0.5)
    cards = []
    for (badge, wp), (cx, cy, angle) in zip(stops, spots):
        card = _polaroid(
            _first_image(wp), badge, str(wp.get("label") or wp.get("name") or ""), int(card_w),
            (colors or {}).get("marker", tuning.OUTRO_BADGE_COLOR),
        )
        if card is not None:
            cards.append((card, cx, cy, angle))
    lines = [title]
    if brief and brief.get("legs"):
        lines += [_fmt_km(brief["total_km"]), _engine()._format_duration_ja(brief["total_minutes"] * 60)]
    stamp = _stamp(int(sr), lines)

    noise = np.random.default_rng(1).normal(0, 5, (height, width, 1))
    # Darker toward the corners, like a lit page.
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    shade = 1 - tuning.OUTRO_SCRAPBOOK_VIGNETTE * (((xx - width / 2) / (width / 2)) ** 2 + ((yy - height / 2) / (height / 2)) ** 2) / 2
    paper = np.asarray(tuning.OUTRO_SCRAPBOOK_PAPER_COLOR, np.float32) + noise
    paper = np.clip(paper * shade[..., None], 0, 255).astype(np.uint8)
    paper_bg = Image.fromarray(paper)
    base = paper_bg.convert("RGBA")
    if top:
        base.alpha_composite(_heading_decor(width, top, k, decor_lines))
    hd = ImageDraw.Draw(base)
    y = SCRAPBOOK_HEADING_MARGIN * k
    for text, font in head:
        hd.text((width / 2, y + font.size * 0.65), _truncate_to_width(hd, text, font, width * 0.9), font=font,
                fill=tuning.OUTRO_SCRAPBOOK_INK, anchor="mm")
        y += font.size * 1.3
    if top:
        # A short rule with a dot under the heading (drawn or on the text track) ties it to the cards.
        ink = (*tuning.OUTRO_SCRAPBOOK_STAMP_COLOR, 200)
        rule_y = SCRAPBOOK_HEADING_MARGIN * k + sum(f.size * 1.3 for f in (_load_font(_GraphicsEngineBase.FONT_CANDIDATES_BOLD, int(s * k)) for s in sizes)) + 8 * k
        rule_y = min(rule_y, top - 4 * k)
        half, dot = 110 * k, 5 * k
        hd.line([(width / 2 - half, rule_y), (width / 2 - 3 * dot, rule_y)], fill=ink, width=max(2, int(2 * k)))
        hd.line([(width / 2 + 3 * dot, rule_y), (width / 2 + half, rule_y)], fill=ink, width=max(2, int(2 * k)))
        hd.ellipse([width / 2 - dot, rule_y - dot, width / 2 + dot, rule_y + dot], fill=ink)
    # The journey: footprints walk from each card's spot to the next, and the card pops up when they get there;
    # after the last one they walk on to the stamp.
    trail = Image.new("RGBA", size, (0, 0, 0, 0))
    feet = dict(foot=26 * k, step=30 * k)
    pile = Image.new("RGBA", size, (0, 0, 0, 0))
    pop, start = 0.35, 0.3
    walk = min(tuning.OUTRO_SCRAPBOOK_WALK_SECONDS, 6.0 / max(1, len(cards)))
    pop_at, marks = [], []  # when each card pops; (time, footprint) as the walk reaches it
    t = start
    for i in range(len(cards) + 1):
        if i:
            to, trim = (cards[i][1:3], 0.0) if i < len(cards) else ((sx, sy), sr * 1.05)
            steps = _footsteps(cards[i - 1][1:3], to, 0.16 if i % 2 else -0.16, tuning.OUTRO_SCRAPBOOK_FOOTPRINT_COLOR, trim=trim, **feet)
            leg_start = t + pop * 0.5
            marks += [(leg_start + walk * (j + 1) / len(steps), mark) for j, mark in enumerate(steps)]
            t = leg_start + walk
        if i < len(cards):
            pop_at.append(t)
    stamp_at = t
    end = stamp_at + 0.25 + tuning.OUTRO_SCRAPBOOK_HOLD_SECONDS

    def compose() -> Image.Image:
        out = base.copy()
        out.alpha_composite(trail)
        out.alpha_composite(pile)
        return out

    def springy(e: float) -> float:
        """0 -> 1, overshooting a little before it settles (ease-out back)."""
        e -= 1
        return 1 + 2.7 * e ** 3 + 1.7 * e ** 2

    settled = compose()

    def frames():
        nonlocal settled
        landed = walked = 0
        last = None
        for f in range(int(round(end * fps))):
            t = f / fps
            changed = False
            while walked < len(marks) and t >= marks[walked][0]:
                im, x, y = marks[walked][1]
                trail.alpha_composite(im, (max(0, x), max(0, y)))
                walked += 1
                changed = True
            while landed < len(cards) and t >= pop_at[landed] + pop:
                card, cx, cy, angle = cards[landed]
                _place(pile, card, cx, cy, 1.0, 1.0, angle)
                landed += 1
                changed = True
            if changed:
                settled = compose()
            img = settled.copy()
            for i in range(landed, len(cards)):
                u = (t - pop_at[i]) / pop
                if u > 0:
                    card, cx, cy, angle = cards[i]
                    _place(img, card, cx, cy, 0.4 + 0.6 * springy(min(u, 1.0)), min(1.0, u * 2.5), angle)
            u = (t - stamp_at) / 0.25
            if u > 0:
                e = min(u, 1.0)
                _place(img, stamp, sx, sy, 1.8 - 0.8 * e, e, -12)
            last = np.asarray(img.convert("RGB"), dtype=np.float32)
            yield last
        end_card = _end_card(size, paper_bg, _INK)
        if end_card is not None:
            # Barn door: the logo card closes in from the top and bottom edges at once, meeting in the middle.
            steps = max(1, int(round(tuning.OUTRO_LOGO_FADE_SECONDS * fps)))
            rows = np.arange(height, dtype=np.float32)[:, None, None]
            soft = max(6.0, height / 30)
            for i in range(steps):
                band = _ease((i + 1) / steps) * height / 2
                edge = np.maximum(band - rows, rows - (height - band))  # >0 inside a door: px from its edge
                shadow = 1 - 0.45 * np.clip(1 + edge / soft, 0, 1)  # each door casts a soft shadow on the photos
                yield np.where(edge > 0, end_card, last * shadow)
            for _ in range(int(round(tuning.OUTRO_LOGO_HOLD_SECONDS * fps))):
                yield end_card

    return _pipe_frames(frames(), output_path, fps, size)


def _route_badges(waypoints: List[Dict[str, Any]]) -> List[Tuple[str, Dict[str, Any]]]:
    """The route's stops (stop-bys only when connected) as (S / 1 / 2 … / E, waypoint), numbered as the overview
    pins are (route_inputs.stop_is_numbered): a stop-by shows "・", a closed place "×"."""
    from services.vdoprocessing.route_inputs import stop_is_numbered

    route = [wp for wp in waypoints if not wp.get("isStopBy") or wp.get("connectToRoute")]
    out, order = [], 0
    for i, wp in enumerate(route):
        if 0 < i < len(route) - 1 and stop_is_numbered(wp):
            order += 1
        badge = ("S" if i == 0 else "E" if i == len(route) - 1 else "×" if wp.get("inaccessible")
                 else "・" if wp.get("isStopBy") or wp.get("skipAssetGeneration") else str(order))
        out.append((badge, wp))
    return out


def _leg_detail_card(
    engine, leg: Dict[str, Any], ends: Tuple[Tuple[str, str], Tuple[str, str]], size: Tuple[int, int], marker_rgb,
) -> Image.Image:
    """The route map pop-up's other side: from → to, the leg's distance and time big, then its modes (icon, name,
    distance) and its climb. Drawn to fill the pop-up's photo area."""
    w, h = size
    k = h / 432
    labels = video_text.current_labels()
    bold, regular = _GraphicsEngineBase.FONT_CANDIDATES_BOLD, _GraphicsEngineBase.FONT_CANDIDATES_REGULAR
    muted = (120, 126, 138)
    card = Image.new("RGBA", size, (247, 248, 250, 255))
    d = ImageDraw.Draw(card)

    # From → to, each with its badge.
    font = _load_font(bold, int(28 * k))
    r = int(17 * k)
    y = int(52 * k)
    half = (w - int(70 * k)) / 2
    for n, (badge, name) in enumerate(ends):
        x0 = int(24 * k) if n == 0 else int(w / 2 + 35 * k - 0 * k)
        d.ellipse([x0, y - r, x0 + 2 * r, y + r], fill=marker_rgb)
        d.text((x0 + r, y), badge, font=_load_font(bold, int(r * 1.15)), fill="white", anchor="mm")
        # A long name goes on two lines, split between words.
        lines, nf, _ = _name_lines(d, name, bold, font.size, int(20 * k), half - 2 * r - 14 * k)
        lines = lines[:2]
        for j, line in enumerate(lines):
            d.text((x0 + 2 * r + 10 * k, y + (j - (len(lines) - 1) / 2) * nf.size * 1.15), line, font=nf,
                   fill=_INK, anchor="lm")
    d.text((w / 2, y), "→", font=_load_font(bold, int(34 * k)), fill=muted, anchor="mm")
    d.line([(24 * k, 96 * k), (w - 24 * k, 96 * k)], fill=(222, 225, 231), width=max(1, int(2 * k)))

    # Distance and time.
    label_font = _load_font(regular, int(26 * k))
    value_font = _load_font(bold, int(66 * k))
    stats = [(labels.get("distance_label", "Distance"), _fmt_km(leg["km"])),
             (labels.get("duration_fallback", "Time"), engine._format_duration_ja(leg["minutes"] * 60))]
    for n, (label, value) in enumerate(stats):
        cx = w * (0.27 if n == 0 else 0.73)
        d.text((cx, 140 * k), label, font=label_font, fill=muted, anchor="mm")
        vf = value_font
        while vf.size > 20 and d.textlength(value, font=vf) > w * 0.44:
            vf = _load_font(bold, vf.size - 2)
        d.text((cx, 205 * k), value, font=vf, fill=_INK, anchor="mm")
    d.line([(w / 2, 125 * k), (w / 2, 245 * k)], fill=(222, 225, 231), width=max(1, int(2 * k)))
    d.line([(24 * k, 275 * k), (w - 24 * k, 275 * k)], fill=(222, 225, 231), width=max(1, int(2 * k)))

    # Modes, then the climb.
    chips = []
    for piece in leg.get("pieces") or [leg]:
        mode = piece.get("mode", "walking")
        name = labels.get("mode_name", {}).get(mode, mode)
        chips.append((mode, f"{name}  {_fmt_km(piece['km'])}" if len(leg.get("pieces") or []) > 1 else name))
    chip_font = _load_font(bold, int(30 * k))
    icon = int(40 * k)
    x, cy = 28 * k, 340 * k
    for mode, text in chips:
        color = _mode_rgb(engine, mode)
        engine._draw_mode_icon(d, mode, int(x + icon / 2), int(cy), icon, (*color, 255))
        d.text((x + icon + 10 * k, cy), text, font=chip_font, fill=color, anchor="lm")
        x += icon + 10 * k + d.textlength(text, font=chip_font) + 28 * k
    if leg.get("ascent_m"):
        climb = f"{labels.get('elevation_profile', '')} +{int(leg['ascent_m'])} m".strip()
        d.text((w - 28 * k, cy), climb, font=chip_font, fill=muted, anchor="rm")
    return card


def _project_colors(settings: Optional[Dict[str, Any]]) -> Dict[str, Tuple[int, int, int]]:
    """The project's pin and route colours (settings are BGR, like tuning) as RGB."""
    out = {}
    for key, name in (("marker_color", "marker"), ("line_color", "line")):
        value = (settings or {}).get(key)
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            out[name] = tuple(int(v) for v in reversed(value[:3]))
    return out


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
    settings: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """`settings` (the project's) give the scrapbook and map styles their pin and route colours and summary cards.
    Builds the outro in `style` ("scroll" or "grid" - see the module
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
    # Rendered beside it and swapped in when complete: a cancelled run leaves the last outro, never a cut-off one.
    partial_path = video_dir_path / f".{Path(output_filename).stem}.partial.mp4"

    try:
        if style == "scrapbook":
            if not _write_scrapbook_clip(
                (heading or {}).get("subtitle") or project_name or "", waypoints, brief, partial_path, tuning.INTRO_FPS,
                size or (1920, 1080), _project_colors(settings), heading,
            ):
                return None
            replace_into(partial_path, output_path)
            logger.info("Outro clip generated: %s (scrapbook)", output_path)
            return str(output_path)
        if style == "scroll":
            size = size or (_CANVAS_W, _CANVAS_H)
            page = _build_scroll_page(project_name or "", waypoints_with_image, size, brief, heading)
            start_hold = tuning.OUTRO_SUMMARY_HOLD_SECONDS if has_route else None
            if not _write_scroll_clip(page, partial_path, tuning.INTRO_FPS, size, start_hold):
                return None
            replace_into(partial_path, output_path)
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
            str(partial_path),
        ]
        result = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", errors="replace"
        )
        if result.returncode != 0:
            logger.error("Outro generation failed: %s", result.stderr.strip())
            return None
        replace_into(partial_path, output_path)
    except Exception as exc:
        logger.error("Outro generation failed: %s", exc)
        return None
    finally:
        frame_path.unlink(missing_ok=True)
        partial_path.unlink(missing_ok=True)

    logger.info("Outro clip generated: %s (%d places)", output_path, len(waypoints_with_image))
    return str(output_path)
