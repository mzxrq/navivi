"""Outro/end-card clip generator: composites one frame — the project title
plus a numbered thumbnail grid of every waypoint that has a popup image —
and holds it for a fixed duration as the video's closing clip.

Standalone (PIL-only compositing + a plain ffmpeg `-loop 1` hold), reusing
the same bundled Japanese-capable fonts as graphicengine/base.py rather
than duplicating font-candidate lists.
"""

from __future__ import annotations

import math
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

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


def _rounded_thumbnail(image_path: str, size: tuple) -> Optional[Image.Image]:
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
        [0, 0, target_w - 1, target_h - 1], radius=_CORNER_RADIUS, fill=255
    )
    out = Image.new("RGBA", (target_w, target_h))
    out.paste(src, (0, 0), mask)
    return out


def _draw_badge(canvas: Image.Image, center: tuple, number: int, font: FreeTypeFont) -> None:
    draw = ImageDraw.Draw(canvas)
    cx, cy = center
    draw.ellipse(
        [cx - _BADGE_RADIUS, cy - _BADGE_RADIUS, cx + _BADGE_RADIUS, cy + _BADGE_RADIUS],
        fill=tuning.OUTRO_BADGE_COLOR,
        outline=tuning.OUTRO_BG_COLOR,
        width=2,
    )
    text = str(number)
    tw = draw.textlength(text, font=font)
    draw.text((cx - tw / 2, cy - font.size / 2 - 1), text, font=font, fill=(255, 255, 255))


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

        popup_image = wp.get("popup_image")
        image_path = (
            popup_image[0]
            if isinstance(popup_image, list) and popup_image
            else popup_image
        )
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


def generate_outro_clip(
    video_dir: str,
    project_name: str,
    waypoints: List[Dict[str, Any]],
    output_filename: str = tuning.OUTRO_OUTPUT_FILENAME,
    duration_sec: float = tuning.OUTRO_DURATION_SECONDS,
) -> Optional[str]:
    """Composites the title + thumbnail-grid frame and holds it for
    duration_sec as an mp4. Returns the output path, or None (logged, never
    raises) on any failure — an outro is a nice-to-have, not something that
    should hard-fail a pipeline run."""
    waypoints_with_image = [wp for wp in waypoints if wp.get("popup_image")]
    if not waypoints_with_image:
        logger.warning("Outro: no waypoints with a popup_image — nothing to show.")
        return None

    video_dir_path = Path(video_dir)
    video_dir_path.mkdir(parents=True, exist_ok=True)
    output_path = video_dir_path / output_filename
    frame_path = video_dir_path / f".outro_frame_{Path(output_filename).stem}.png"

    try:
        frame = _build_frame(project_name or "", waypoints_with_image)
        frame.save(frame_path)

        ffmpeg_cmd = FFmpegManager.resolve_ffmpeg_bin()
        cmd = [
            ffmpeg_cmd, "-y",
            "-loop", "1", "-i", str(frame_path),
            "-t", f"{duration_sec:.3f}",
            "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p",
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
