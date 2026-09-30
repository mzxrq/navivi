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
from PIL import Image, ImageDraw, ImageFont
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


def _first_image(wp: Dict[str, Any]) -> Optional[str]:
    popup_image = wp.get("popup_image")
    if isinstance(popup_image, list):
        return popup_image[0] if popup_image else None
    return popup_image


def _build_frame(project_name: str, waypoints: List[Dict[str, Any]]) -> Image.Image:
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

    _center_text(draw, project_name, title_font, _CANVAS_W / 2, 34, tuning.OUTRO_TITLE_COLOR)
    _center_text(
        draw,
        tuning.OUTRO_SUBTITLE_TEMPLATE.format(count=len(waypoints)),
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
) -> Image.Image:
    """One tall page `size[0]` wide: the title block on top, then EVERY card
    (no OUTRO_MAX_CARDS cap - scrolling is what makes a long list fit),
    tuning.OUTRO_SCROLL_COLS to a row inside a centred container
    (OUTRO_SCROLL_SIDE_PADDING either side), each a rounded thumbnail with
    its number badge and bold name underneath. One empty screen follows the
    content, so scrolling to the page's bottom carries every card off the
    top.

    Drawn at the finished video's own size (tuning's px values are for the
    704-high canvas and scale with it): an outro drawn small and stretched
    up by the export has soft text that judders as it moves."""
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


def _scroll_offsets(distance: int, fps: int, scale: float = 1.0) -> List[int]:
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

    offsets = [0] * int(round(tuning.OUTRO_SCROLL_START_HOLD_SECONDS * fps))
    top = 0
    for moved in steps:
        top += moved
        offsets.append(top)
    offsets += [distance] * int(round(tuning.OUTRO_SCROLL_END_HOLD_SECONDS * fps))
    return offsets


def _write_scroll_clip(
    page: Image.Image, output_path: Path, fps: int, size: Tuple[int, int],
) -> bool:
    """Crops the tall page frame by frame at each _scroll_offsets offset,
    softens the top/bottom screen edges into the background, and pipes the
    raw frames straight into ffmpeg."""
    width, height = size
    k = height / _CANVAS_H
    page_px = np.asarray(page, dtype=np.uint8)
    offsets = _scroll_offsets(page_px.shape[0] - height, fps, k)

    # Per-row blend weight toward the background: 1 at the very edge, 0 once
    # OUTRO_SCROLL_EDGE_FADE_PX in.
    fade = max(1, int(round(tuning.OUTRO_SCROLL_EDGE_FADE_PX * k)))
    ramp = np.clip(1.0 - np.arange(fade, dtype=np.float32) / fade, 0.0, 1.0)
    bg = np.asarray(tuning.OUTRO_BG_COLOR, dtype=np.float32)

    ffmpeg_cmd = FFmpegManager.resolve_ffmpeg_bin()
    cmd = [
        ffmpeg_cmd, "-y", *tuning.ffmpeg_log_args(),
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
) -> Optional[str]:
    """Builds the outro in `style` ("scroll" or "grid" - see the module
    docstring) as an mp4; duration_sec is the grid's hold (the scroll's own
    length follows the page). `size` is the finished video's frame size,
    which the scroll is drawn at (default: the 1280x704 canvas). Returns the output path, or None (logged,
    never raises) on any failure — an outro is a nice-to-have, not something
    that should hard-fail a pipeline run."""
    waypoints_with_image = [wp for wp in waypoints if wp.get("popup_image")]
    if not waypoints_with_image:
        logger.warning("Outro: no waypoints with a popup_image — nothing to show.")
        return None

    video_dir_path = Path(video_dir)
    video_dir_path.mkdir(parents=True, exist_ok=True)
    output_path = video_dir_path / output_filename
    frame_path = video_dir_path / f".outro_frame_{Path(output_filename).stem}.png"

    try:
        if style == "scroll":
            size = size or (_CANVAS_W, _CANVAS_H)
            page = _build_scroll_page(project_name or "", waypoints_with_image, size)
            if not _write_scroll_clip(page, output_path, tuning.INTRO_FPS, size):
                return None
            logger.info(
                "Outro clip generated: %s (%d places, scroll)", output_path, len(waypoints_with_image)
            )
            return str(output_path)

        frame = _build_frame(project_name or "", waypoints_with_image)
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
