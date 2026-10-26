"""Intro clip generator: picks several random waypoint popup images, renders
a slow Ken Burns zoom-in over each, crossfades them into one slideshow, and
burns the project's name centered on top — used as the first clip in a
project's video.

Standalone (no dependency on VideoEditor/JobConfig) — reuses SubtitleStyle's
libass force_style formatting (services/localization/subtitle.py) and
FFmpegManager's binary resolution (services/tts/ttsengine.py) rather than
duplicating either. The zoom geometry (cover-fit crop + ease-in-out) mirrors
local_pan_generator.py's, kept as a small standalone copy here rather than
importing that module — it pulls in torch/diffusers/transformers at import
time for its (unrelated) AI-outpaint path, which would be a heavy, slow
dependency to load just for three lines of crop math.
"""

from __future__ import annotations

import math
import re
import random
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw

from services.localization.subtitle import SubtitleStyle
from services.localization.text_style import TextStyle
from services.logger.logger import setup_logger
from services.mapfetcher.graphicengine.base import _GraphicsEngineBase
from services.tts.ttsengine import FFmpegManager
from services.vdoprocessing.outrocard import LOGO_DIR, _load_font, trimmed_logo
from services import tuning, video_text
from services.projectfiles import replace_into

logger = setup_logger("IntroClip")

# Centered, bold, larger than a normal subtitle line — this is a title card,
# not a caption. Keeps the same outline/shadow approach as SubtitleStyle's
# default so it stays readable over any busy background photo.
def _ass_bgr(rgb) -> str:
    r, g, b = rgb
    return f"{b:02X}{g:02X}{r:02X}"


_TITLE_STYLE = SubtitleStyle(
    font_size=tuning.INTRO_TITLE_FONT_SIZE,
    primary_color=f"&H00{_ass_bgr(tuning.INTRO_TITLE_COLOR)}",
    bold=tuning.INTRO_TITLE_BOLD,
    alignment=10,  # old-SSA numbering (see SubtitleStyle.alignment) = middle-center
    outline=tuning.INTRO_TITLE_OUTLINE,
    shadow=1.0,
    margin_v=0,
)


DEFAULT_TITLE_STYLE = TextStyle(
    font_family=tuning.INTRO_TITLE_FONT_FAMILY,
    font_size=tuning.INTRO_TITLE_FONT_SIZE,
    color=tuning.INTRO_TITLE_COLOR,
    bold=tuning.INTRO_TITLE_BOLD,
    outline_width=tuning.INTRO_TITLE_OUTLINE,
)
DEFAULT_SUBTITLE_STYLE = TextStyle(
    font_family=tuning.INTRO_SUBTITLE_FONT_FAMILY,
    font_size=tuning.INTRO_SUBTITLE_FONT_SIZE,
    color=tuning.INTRO_SUBTITLE_COLOR,
    bold=tuning.INTRO_SUBTITLE_BOLD,
    outline_width=tuning.INTRO_SUBTITLE_OUTLINE,
)
DEFAULT_KICKER_STYLE = TextStyle(
    font_family=tuning.INTRO_KICKER_FONT_FAMILY,
    font_size=tuning.INTRO_KICKER_FONT_SIZE,
    color=tuning.INTRO_KICKER_COLOR,
    bold=tuning.INTRO_KICKER_BOLD,
    outline_width=tuning.INTRO_KICKER_OUTLINE,
    letter_spacing=tuning.INTRO_KICKER_LETTER_SPACING,
)


def _read_image_safe(path: str) -> Optional[np.ndarray]:
    """cv2.imread chokes on non-ASCII Windows paths — read the bytes
    ourselves and decode, same workaround graphicengine/base.py uses."""
    # [HACK] [Animation] cv2.imread can't handle non-ASCII Windows paths; decode
    # from an in-memory buffer instead of letting it open the path itself.
    try:
        with open(path, "rb") as f:
            chunk = f.read()
        return cv2.imdecode(np.frombuffer(chunk, dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception as exc:
        logger.warning("Could not read image '%s': %s", path, exc)
        return None


def _ease_in_out(t: float) -> float:
    return 0.5 - 0.5 * np.cos(np.pi * t)


def _cover_fit(sw: int, sh: int, out_aspect: float):
    """Largest out_aspect-shaped region that fits inside an sw x sh image —
    i.e. the crop size for a center-crop "cover" fit (no letterboxing)."""
    if sw / sh > out_aspect:
        fit_h = sh
        fit_w = int(fit_h * out_aspect)
    else:
        fit_w = sw
        fit_h = int(fit_w / out_aspect)
    return fit_w, fit_h


def _crop_rect(cx: float, cy: float, half_w: float, half_h: float, sw: int, sh: int):
    half_w = min(half_w, sw / 2)
    half_h = min(half_h, sh / 2)
    cx = min(max(cx, half_w), sw - half_w)
    cy = min(max(cy, half_h), sh - half_h)
    return int(cx - half_w), int(cy - half_h), int(cx + half_w), int(cy + half_h)


def _render_zoom_in(
    image_bgr: np.ndarray, raw_output_path: str, duration_sec: float,
    zoom: Tuple[float, float] = (tuning.INTRO_ZOOM_START, tuning.INTRO_ZOOM_END),
    pan: Tuple[float, float] = (0.0, 0.0),
    dim: float = tuning.INTRO_IMAGE_DIM_FACTOR,
    sat: float = 1.0,
) -> None:
    """Renders a Ken Burns move over a still image: the visible crop goes from
    zoom[0] to zoom[1] (ease-in-out) while its centre drifts by `pan` (a
    fraction of the free crop room, from -pan to +pan), then dims/desaturates."""
    sh, sw = image_bgr.shape[:2]
    out_w, out_h = tuning.INTRO_WIDTH, tuning.INTRO_HEIGHT
    fit_w, fit_h = _cover_fit(sw, sh, out_w / out_h)

    num_frames = max(1, round(duration_sec * tuning.INTRO_FPS))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(raw_output_path, fourcc, tuning.INTRO_FPS, (out_w, out_h))

    for i in range(num_frames):
        t = _ease_in_out(i / max(1, num_frames - 1))
        z = zoom[0] + (zoom[1] - zoom[0]) * t
        half_w, half_h = fit_w * z / 2, fit_h * z / 2
        cx = sw / 2 + pan[0] * (2 * t - 1) * max(0.0, sw / 2 - half_w)
        cy = sh / 2 + pan[1] * (2 * t - 1) * max(0.0, sh / 2 - half_h)
        x0, y0, x1, y1 = _crop_rect(cx, cy, half_w, half_h, sw, sh)
        crop = image_bgr[y0:y1, x0:x1]
        frame = cv2.resize(crop, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)
        if sat < 1.0:
            gray = cv2.cvtColor(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
            frame = cv2.addWeighted(frame, sat, gray, 1.0 - sat, 0)
        if dim < 1.0:
            frame = cv2.convertScaleAbs(frame, alpha=dim, beta=0)
        writer.write(frame)

    writer.release()


def _render_clip_slice(src: str, out: str, duration_sec: float, dim: float, sat: float) -> None:
    """`duration_sec` from the middle of a video clip (its own camera move is the motion), cover-fit to
    the intro size, dimmed and desaturated; held on its last frame if the clip is shorter."""
    try:
        length = float(FFmpegManager.get_media_duration(src))
    except Exception:
        length = 0.0
    start = max(0.0, (length - duration_sec) / 2)
    w, h = tuning.INTRO_WIDTH, tuning.INTRO_HEIGHT
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={tuning.INTRO_FPS},"
        f"eq=saturation={sat:.3f},colorchannelmixer=rr={dim:.3f}:gg={dim:.3f}:bb={dim:.3f},"
        f"tpad=stop_mode=clone:stop_duration={duration_sec:.3f},setsar=1"
    )
    cmd = [
        FFmpegManager.resolve_ffmpeg_bin(), "-y", *tuning.ffmpeg_log_args(),
        "-ss", f"{start:.3f}", "-i", src, "-vf", vf, "-t", f"{duration_sec:.3f}", "-an",
        "-c:v", "libx264", *tuning.ffmpeg_thread_args(), "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p", out,
    ]
    result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"Clip slice failed: {result.stderr.strip()}")


def scene_starts(durations: List[float], crossfade_sec: float) -> List[float]:
    """When each crossfaded clip starts on the joined timeline (clip i fades in over the end of clip i-1)."""
    starts, t = [], 0.0
    for d in durations:
        starts.append(round(t, 3))
        t += d - crossfade_sec
    return starts


def xfade_offsets(durations: List[float], crossfade_sec: float) -> List[float]:
    return scene_starts(durations, crossfade_sec)[1:]


def _crossfade_chain(
    clip_paths: List[str], durations: List[float], crossfade_sec: float, output_path: str
) -> None:
    """Chains N same-resolution clips (durations[i] seconds each) into one
    video, each crossfading into the next via ffmpeg's `xfade` filter. Raises
    RuntimeError on failure — the caller decides how to handle that."""
    if len(clip_paths) == 1:
        # [NOTE] [Transition] A single clip has nothing to crossfade into — skip
        # straight to a copy rather than building a degenerate one-input filter graph.
        shutil.copy2(clip_paths[0], output_path)
        return

    ffmpeg_cmd = FFmpegManager.resolve_ffmpeg_bin()
    inputs: List[str] = []
    for p in clip_paths:
        inputs += ["-i", p]

    # [NOTE] [Transition] Each xfade offset is computed against the running
    # cumulative timeline, chaining N clips through N-1 successive xfade filters.
    filter_parts = []
    prev_label = "0:v"
    for i, offset in enumerate(xfade_offsets(durations, crossfade_sec), start=1):
        out_label = f"v{i}"
        filter_parts.append(
            f"[{prev_label}][{i}:v]xfade=transition=fade:"
            f"duration={crossfade_sec:.3f}:offset={offset:.3f}[{out_label}]"
        )
        prev_label = out_label

    cmd = [
        ffmpeg_cmd, "-y", *tuning.ffmpeg_log_args(),
        *inputs,
        "-filter_complex", ";".join(filter_parts),
        "-map", f"[{prev_label}]",
        "-c:v", "libx264", *tuning.ffmpeg_thread_args(), "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"Crossfade chain failed: {result.stderr.strip()}")


def _format_ass_timestamp(seconds: float) -> str:
    total_cs = max(0, int(round(seconds * 100)))
    hours, rem_cs = divmod(total_cs, 360_000)
    minutes, rem_cs = divmod(rem_cs, 6_000)
    secs, cs = divmod(rem_cs, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


TEXT_POSITIONS = ("top", "middle", "bottom")
TEXT_DEFAULT_MARGIN_PX = 100


def stacked_line_ys(
    cy: int, kicker_size: int, title_size: int, subtitle_size: int,
    has_kicker: bool, has_title: bool, has_subtitle: bool,
) -> Tuple[int, int, int]:
    """(kicker_y, title_y, subtitle_y) centres. Title + subtitle sit as they always
    have; a kicker goes above the top line and the whole block shifts down by half
    that gap. Mirrors stackedLineYs in src/utils/textStyle.ts."""
    if has_title and has_subtitle:
        title_y, sub_y = cy - int(subtitle_size * 0.6), cy + int(title_size * 0.6)
    else:
        title_y = sub_y = cy
    if not has_kicker or not (has_title or has_subtitle):
        return cy, title_y, sub_y
    top_y, top_size = (title_y, title_size) if has_title else (sub_y, subtitle_size)
    gap = int(0.6 * (kicker_size + top_size))
    shift = gap // 2
    return top_y - gap + shift, title_y + shift, sub_y + shift


def apply_line_margins(
    position: str, ys: Tuple[int, int, int], margins: Tuple[float, float, float], has: Tuple[bool, bool, bool],
) -> Tuple[int, int, int]:
    """`ys` (kicker, title, subtitle centres) with each shown line's "space above" (`margins`, 1080-line px,
    may be negative) added to it and to every line under it. A top block keeps its first line where it was
    (that line's own margin moves the whole block down), a bottom block keeps its last line, a middle
    block stays centred. Mirrors applyLineMargins in src/utils/textStyle.ts."""
    added, running = [], 0.0
    for m, shown in zip(margins, has):
        if shown:
            running += float(m)
        added.append(running)
    shift = {"top": 0.0, "bottom": -running}.get(position, -running / 2)
    return tuple(  # type: ignore[return-value]
        int(math.floor(y + a + shift + 0.5)) if shown else y for y, a, shown in zip(ys, added, has)
    )


def text_block_center_y(
    position: str, margin_px: float, title_size: int, subtitle_size: int,
    has_title: bool, has_subtitle: bool, frame_h: int = 1080,
    kicker_size: int = 0,
) -> int:
    """Vertical centre of a title + subtitle block placed at the top, middle or
    bottom of the frame, `margin_px` from that edge. The block's height follows
    title_events' stacking; kicker_size > 0 adds a kicker line above.
    Mirrors textBlockCenterY in src/utils/textStyle.ts."""
    if position not in ("top", "bottom"):
        return frame_h // 2
    if has_title and has_subtitle:
        half = 0.55 * (title_size + subtitle_size)
    elif has_title or has_subtitle:
        half = (title_size if has_title else subtitle_size) / 2
    else:
        half = kicker_size / 2
    if kicker_size > 0 and (has_title or has_subtitle):
        half += 0.3 * (kicker_size + (title_size if has_title else subtitle_size))
    margin = max(0.0, float(margin_px))
    # Halves round up, like Math.round in the preview.
    return int(math.floor((margin + half if position == "top" else frame_h - margin - half) + 0.5))


TEXT_ANIMATIONS = ("pop", "rise", "fade", "none")
TEXT_FADE_SECONDS = 0.5
# \an numbers for a left / centre / right edge, vertically centred.
_ALIGN_AN = {"left": 4, "center": 5, "right": 6}


def line_motion(
    which: str, animation: Optional[str], delay: Optional[float], group_animation: Optional[str], duration_sec: float,
    paired: bool = True,
) -> Tuple[str, float]:
    """(animation, delay) for the title or subtitle line. A line's own setting
    wins; else the item-wide "fade"/"none"; else the intro's: the title pops in
    at once, the kicker fades in with it, the subtitle rises in
    INTRO_SUBTITLE_DELAY_SECONDS later (at once when it's shown alone).
    Mirrors lineMotion in src/utils/textStyle.ts."""
    if animation not in TEXT_ANIMATIONS:
        default = {"title": "pop", "kicker": "fade"}.get(which, "rise")
        animation = group_animation if group_animation in ("fade", "none") else default
    if isinstance(delay, (int, float)) and not isinstance(delay, bool):
        delay = max(0.0, float(delay))
    elif group_animation in ("fade", "none") or which != "subtitle" or not paired:
        delay = 0.0
    else:
        delay = min(tuning.INTRO_SUBTITLE_DELAY_SECONDS, duration_sec / 4)
    # A line keeps at least a tenth of the item on screen.
    return animation, min(delay, max(0.0, duration_sec * 0.45))


def _line_tags(animation: str, an: int, x: int, y: int, line_ms: int, line_sec: float) -> str:
    if animation == "pop":
        # \fad is the opacity half; \t animates \fscx/\fscy for the scale half.
        fade_ms = int(round(min(tuning.INTRO_LABEL_FADE_SECONDS, line_sec / 2) * 1000))
        s = tuning.INTRO_LABEL_SCALE_START_PCT
        return (
            rf"\an{an}\pos({x},{y})\fad({fade_ms},{fade_ms})\fscx{s}\fscy{s}"
            rf"\t(0,{fade_ms},\fscx100\fscy100)\t({max(0, line_ms - fade_ms)},{line_ms},\fscx{s}\fscy{s})"
        )
    if animation == "rise":
        fade_ms = int(round(min(tuning.INTRO_SUBTITLE_FADE_SECONDS, line_sec / 3) * 1000))
        rise = tuning.INTRO_SUBTITLE_RISE_PX
        return rf"\an{an}\move({x},{y + rise},{x},{y},0,{fade_ms})\fad({fade_ms},{fade_ms})"
    if animation == "fade":
        fade_ms = int(round(min(TEXT_FADE_SECONDS, line_sec / 2) * 1000))
        return rf"\an{an}\pos({x},{y})\fad({fade_ms},{fade_ms})"
    return rf"\an{an}\pos({x},{y})"


def title_events(
    title: str,
    subtitle: str,
    start_sec: float,
    end_sec: float,
    title_style: TextStyle,
    subtitle_style: TextStyle,
    cx: int,
    cy: int,
    align: str = "center",
    animation: Optional[str] = None,
    title_motion: Optional[dict] = None,
    subtitle_motion: Optional[dict] = None,
    kicker: str = "",
    kicker_style: TextStyle = DEFAULT_KICKER_STYLE,
    kicker_motion: Optional[dict] = None,
    position: str = "middle",
    margins: Tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> List[Tuple[float, float, str]]:
    """(start, end, text with override tags) for a title + subtitle block (plus
    an optional small kicker line above) whose `align` edge (left/center/right)
    sits at cx, centred vertically on cy.
    Each line has its own animation ("pop", "rise", "fade", "none") and enters
    `delay` seconds after the item starts, leaving as long before it ends
    (title_motion / subtitle_motion / kicker_motion: {"animation", "delay"}; see line_motion).
    `margins`/`position`: see apply_line_margins.
    Used by the intro and by text items on the editor's text track."""
    duration_sec = max(0.0, end_sec - start_sec)
    an = _ALIGN_AN.get(align, 5)
    # Braces open override tags and backslashes start escapes — strip them
    # from arbitrary project-name text rather than escaping.
    clean = lambda t: (t or "").replace("{", "").replace("}", "").replace("\\", "")  # noqa: E731
    safe_title, safe_subtitle, safe_kicker = clean(title), clean(subtitle), clean(kicker)

    kicker_y, title_y, sub_y = stacked_line_ys(
        cy, kicker_style.font_size, title_style.font_size, subtitle_style.font_size,
        bool(safe_kicker), bool(safe_title), bool(safe_subtitle),
    )
    # Each line's own "space above" (kicker, title, subtitle margins), as the editor sets them.
    kicker_y, title_y, sub_y = apply_line_margins(
        position, (kicker_y, title_y, sub_y), margins, (bool(safe_kicker), bool(safe_title), bool(safe_subtitle)),
    )

    events: List[Tuple[float, float, str]] = []
    for which, text, y, style, motion in (
        ("kicker", safe_kicker, kicker_y, kicker_style, kicker_motion or {}),
        ("title", safe_title, title_y, title_style, title_motion or {}),
        ("subtitle", safe_subtitle, sub_y, subtitle_style, subtitle_motion or {}),
    ):
        if not text:
            continue
        anim, delay = line_motion(
            which, motion.get("animation"), motion.get("delay"), animation, duration_sec,
            paired=bool(safe_title and safe_subtitle),
        )
        line_sec = max(0.0, duration_sec - 2 * delay)
        tags = _line_tags(anim, an, cx, y, int(round(line_sec * 1000)), line_sec)
        events.append((start_sec + delay, end_sec - delay, f"{{{tags}{style.to_ass_tags()}}}{text}"))
    return events


def _write_title_ass(
    title: str,
    subtitle: str,
    duration_sec: float,
    tmp_dir: Path,
    title_style: TextStyle = DEFAULT_TITLE_STYLE,
    subtitle_style: TextStyle = DEFAULT_SUBTITLE_STYLE,
) -> Path:
    """Writes a throwaway .ass (not .srt) spanning the whole intro, with the
    animated title + subtitle from title_events."""
    events = [
        f"Dialogue: Marked=0,{_format_ass_timestamp(a)},{_format_ass_timestamp(b)},Default,,0000,0000,0000,,{text}\n"
        for a, b, text in title_events(
            title, subtitle, 0.0, duration_sec, title_style, subtitle_style,
            tuning.INTRO_WIDTH // 2, tuning.INTRO_HEIGHT // 2,
        )
    ]

    ass_path = tmp_dir / f"intro_title_{uuid.uuid4().hex[:8]}.ass"
    ass_path.write_text(
        "[Script Info]\n"
        "ScriptType: v4.00\n"
        f"PlayResX: {tuning.INTRO_WIDTH}\n"
        f"PlayResY: {tuning.INTRO_HEIGHT}\n\n"
        "[V4 Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "TertiaryColour, BackColour, Bold, Italic, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, AlphaLevel, Encoding\n"
        "Style: Default,Arial,20,16777215,65535,0,0,0,0,1,2,2,2,10,10,10,0,1\n\n"
        "[Events]\n"
        "Format: Marked, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n" + "".join(events),
        encoding="utf-8",
    )
    return ass_path


def _pick_random_images(waypoints: List[Dict[str, Any]], count: int) -> List[str]:
    """Collects every distinct popup image across all waypoints and samples
    up to `count` of them at random (fresh pick every call) — deduped so a
    handful of waypoints sharing the same photo doesn't repeat it in the
    slideshow."""
    seen = set()
    candidates: List[str] = []
    for wp in waypoints:
        popup_image = wp.get("popup_image")
        images = popup_image if isinstance(popup_image, list) else [popup_image]
        for img in images:
            if img and img not in seen:
                seen.add(img)
                candidates.append(img)
    if not candidates:
        return []
    return random.sample(candidates, k=min(count, len(candidates)))


def _write_logo_badge(video_dir: Path, run_id: str) -> Optional[Path]:
    """INTRO_LOGO_FILE under a small "Powered by" line on a white rounded
    badge, as a PNG for ffmpeg to overlay; None when unset or unreadable."""
    if not tuning.INTRO_LOGO_FILE:
        return None
    logo = trimmed_logo(LOGO_DIR / tuning.INTRO_LOGO_FILE, tuning.INTRO_LOGO_HEIGHT)
    if logo is None:
        return None
    pad, size = tuning.INTRO_LOGO_PADDING, tuning.INTRO_LOGO_TITLE_FONT_SIZE
    font = _load_font(_GraphicsEngineBase.FONT_CANDIDATES_BOLD, size)
    text = video_text.current_labels()["outro_logo_title"]
    gap = round(size * 0.4)
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    w = int(max(logo.width, measure.textlength(text, font=font))) + 2 * pad
    badge = Image.new("RGBA", (w, size + gap + logo.height + 2 * pad), (0, 0, 0, 0))
    draw = ImageDraw.Draw(badge)
    draw.rounded_rectangle([0, 0, badge.width - 1, badge.height - 1], radius=pad, fill=(255, 255, 255))
    draw.text((w / 2, pad), text, font=font, fill=tuning.INTRO_LOGO_TITLE_COLOR, anchor="mt")
    badge.alpha_composite(logo, ((w - logo.width) // 2, pad + size + gap))
    path = video_dir / f".intro_logo_{run_id}.png"
    badge.save(path)
    return path


def fitted_layout(duration_sec: float, available: int) -> Tuple[int, float]:
    """(photos, seconds per photo) for an intro of `duration_sec` from up to
    `available` photos: about INTRO_PER_IMAGE_SECONDS each, at most
    INTRO_MAX_IMAGE_COUNT, each long enough for its crossfades."""
    cf = tuning.INTRO_CROSSFADE_SECONDS
    n = max(1, min(available, tuning.INTRO_MAX_IMAGE_COUNT, round(duration_sec / tuning.INTRO_PER_IMAGE_SECONDS)))
    while n > 1 and (duration_sec + (n - 1) * cf) / n < 2 * cf:
        n -= 1
    return n, (duration_sec + (n - 1) * cf) / n


def generate_intro_clip(
    video_dir: str,
    title: str,
    subtitle: str,
    waypoints: List[Dict[str, Any]],
    output_filename: str = tuning.INTRO_OUTPUT_FILENAME,
    title_style: Optional[Dict[str, Any]] = None,
    subtitle_style: Optional[Dict[str, Any]] = None,
    burn_text: bool = True,
    duration_sec: Optional[float] = None,
) -> Optional[str]:
    """Picks up to INTRO_IMAGE_COUNT random, distinct waypoint popup images
    (a fresh pick every call), renders a slow zoom-in over each, crossfades
    them into one slideshow, and burns project_name centered on top with a
    fade in/out at the very start/end. Returns the output path, or None
    (logged, never raises) if there are no waypoint images or generation
    fails — an intro is a nice-to-have, not something that should hard-fail
    a pipeline run. `duration_sec` fits the intro to that length (the overview
    voice's opening, see intro_step.plan_intro_seconds)."""
    count = tuning.INTRO_MAX_IMAGE_COUNT if duration_sec else tuning.INTRO_IMAGE_COUNT
    image_paths = _pick_random_images(waypoints, count)
    if not image_paths:
        logger.warning("No waypoint popup images available — cannot build an intro yet.")
        return None
    per_clip_sec = tuning.INTRO_PER_IMAGE_SECONDS
    if duration_sec:
        n, per_clip_sec = fitted_layout(duration_sec, len(image_paths))
        image_paths = image_paths[:n]

    logger.info("Intro: picked %d source image(s): %s", len(image_paths), image_paths)

    video_dir_path = Path(video_dir)
    video_dir_path.mkdir(parents=True, exist_ok=True)
    output_path = video_dir_path / output_filename
    run_id = uuid.uuid4().hex[:8]
    per_clip_raw_paths: List[str] = []
    combined_path = video_dir_path / f".intro_combined_{run_id}.mp4"
    title_path: Optional[Path] = None

    crossfade_sec = tuning.INTRO_CROSSFADE_SECONDS
    total_sec = (
        len(image_paths) * per_clip_sec - (len(image_paths) - 1) * crossfade_sec
    )

    try:
        for idx, image_path in enumerate(image_paths):
            image = _read_image_safe(image_path)
            if image is None:
                continue
            raw_path = video_dir_path / f".intro_raw_{run_id}_{idx}.mp4"
            _render_zoom_in(image, str(raw_path), per_clip_sec)
            per_clip_raw_paths.append(str(raw_path))

        if not per_clip_raw_paths:
            logger.error("Intro: none of the picked images could be read.")
            return None

        # [NOTE] [Animation] A picture failing to read shrinks the slideshow — recompute
        # the total against however many clips actually rendered.
        total_sec = (
            len(per_clip_raw_paths) * per_clip_sec
            - (len(per_clip_raw_paths) - 1) * crossfade_sec
        )
        _crossfade_chain(per_clip_raw_paths, [per_clip_sec] * len(per_clip_raw_paths), crossfade_sec, str(combined_path))

        base = "null"
        if burn_text:
            title_path = _write_title_ass(
                title or "", subtitle or "", total_sec, video_dir_path,
                title_style=DEFAULT_TITLE_STYLE.merged(title_style)
                .with_installed_font(DEFAULT_TITLE_STYLE.font_family),
                subtitle_style=DEFAULT_SUBTITLE_STYLE.merged(subtitle_style)
                .with_installed_font(DEFAULT_SUBTITLE_STYLE.font_family),
            )
            # [HACK] [Subtitle] Absolute, forward-slashed, colon-escaped path — libass's
            # subtitles filter needs this exact escaping, same as combine_video_and_audio.
            escaped_title_path = str(title_path.resolve()).replace("\\", "/").replace(":", r"\:")
            base = f"subtitles=filename='{escaped_title_path}':force_style='{_TITLE_STYLE.to_force_style()}'"

        if not _finish_intro(combined_path, total_sec, base, video_dir_path, run_id, output_path):
            return None
    except Exception as exc:
        logger.error("Intro generation failed: %s", exc)
        return None
    finally:
        if title_path is not None:
            title_path.unlink(missing_ok=True)
        combined_path.unlink(missing_ok=True)
        for p in per_clip_raw_paths:
            Path(p).unlink(missing_ok=True)

    logger.info("Intro clip generated: %s (%d pictures)", output_path, len(per_clip_raw_paths))
    return str(output_path)


def _finish_intro(combined_path: Path, total_sec: float, base: str, video_dir: Path, run_id: str, output_path: Path) -> bool:
    """Fade from/to black + the logo badge over the joined scenes, written to a temp file and swapped in.
    Cut to exactly `total_sec` (padded with its last frame if the joins came out a frame short): the
    overview voice is shifted by the intro's length, so a frame's wobble would re-render the overview."""
    fade_sec = tuning.INTRO_FADE_SECONDS
    fades = (
        f"fade=t=in:st=0:d={fade_sec:.2f},"
        f"fade=t=out:st={max(0.0, total_sec - fade_sec):.2f}:d={fade_sec:.2f},"
        "tpad=stop_mode=clone:stop_duration=0.5"
    )
    partial_path = video_dir / f".intro_partial_{run_id}.mp4"
    logo_path = _write_logo_badge(video_dir, run_id)
    inputs = ["-i", str(combined_path)]
    graph = f"[0:v]{base}[base];[base]{fades}"
    if logo_path is not None:
        inputs += ["-i", str(logo_path)]
        m = tuning.INTRO_LOGO_MARGIN
        graph = f"[0:v]{base}[base];[base][1:v]overlay=W-w-{m}:H-h-{m},{fades}"
    cmd = [
        FFmpegManager.resolve_ffmpeg_bin(), "-y", *tuning.ffmpeg_log_args(),
        *inputs,
        "-filter_complex", graph,
        "-t", f"{total_sec:.3f}",
        "-an",
        "-c:v", "libx264", *tuning.ffmpeg_thread_args(), "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p",
        str(partial_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
        if result.returncode != 0:
            logger.error("Intro generation failed: %s", result.stderr.strip())
            return False
        replace_into(partial_path, output_path)  # a cancelled run leaves the last intro, never a cut-off one
        return True
    finally:
        if logo_path is not None:
            logo_path.unlink(missing_ok=True)
        partial_path.unlink(missing_ok=True)


def _frame_at(path: str, fraction: float, length: float) -> Optional[np.ndarray]:
    """A photo, or the frame `fraction` of the way into a `length`-second video (through ffmpeg: cv2
    can't open non-ASCII paths)."""
    if Path(path).suffix.lower() not in _VIDEO_EXTS:
        return _read_image_safe(path)
    try:
        at = length * fraction
        result = subprocess.run(
            [FFmpegManager.resolve_ffmpeg_bin(), "-v", "error", "-ss", f"{at:.2f}", "-i", path,
             "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
            capture_output=True,
        )
        return cv2.imdecode(np.frombuffer(result.stdout, dtype=np.uint8), cv2.IMREAD_COLOR) if result.stdout else None
    except Exception as exc:
        logger.warning("Intro: could not read a frame of '%s': %s", path, exc)
        return None


def is_still(a: np.ndarray, b: np.ndarray) -> bool:
    """Two frames of a clip barely differ: a held photo (camera preset "none"), not a camera move."""
    small = lambda f: cv2.cvtColor(cv2.resize(f, (320, 180)), cv2.COLOR_BGR2GRAY).astype(np.float32)  # noqa: E731
    return float(np.abs(small(a) - small(b)).mean()) < tuning.INTRO_STILL_DIFF


def edge_density(image_bgr: np.ndarray) -> float:
    """Share of edge pixels: high = close detail (moss, a sign), low = an open wide view."""
    gray = cv2.cvtColor(cv2.resize(image_bgr, (480, 270)), cv2.COLOR_BGR2GRAY)
    return float((cv2.Canny(gray, 80, 200) > 0).mean())


def pick_scenes(densities: Dict[str, float], count: int = 2) -> List[str]:
    """[close-up, wide, middle...]: the most detailed source, the plainest, then a mid one for the title
    scene; sources repeat when there are fewer than `count`."""
    ranked = sorted(densities, key=lambda p: densities[p], reverse=True)
    if not ranked:
        return []
    order = [0, len(ranked) - 1, len(ranked) // 2]
    order += [i for i in range(len(ranked)) if i not in order]
    distinct = list(dict.fromkeys(order))
    return [ranked[distinct[i % len(distinct)]] for i in range(count)]


_VIDEO_EXTS = (".mp4", ".mov", ".webm", ".mkv")


def _source_seconds(src: str) -> float:
    """A clip's length; a photo never runs out (the zoom is drawn for any length)."""
    if Path(src).suffix.lower() not in _VIDEO_EXTS:
        return float("inf")
    try:
        return float(FFmpegManager.get_media_duration(src))
    except Exception:
        return 0.0


def plan_shots(seconds: float, main: str, pool: List[str], lengths: Dict[str, float], cf: float, scene: int) -> List[str]:
    """The sources a scene of `seconds` plays: `main`, plus clips taken from `pool` (busiest first; the
    close-up scene takes from the busy end, the wide one from the plain end, others from the middle)
    until every shot's equal share fits inside its clip. Takes them out of `pool`."""
    shots = [main]
    while pool and (seconds + (len(shots) - 1) * cf) / len(shots) > min(lengths.get(s, 0.0) for s in shots):
        shots.append(pool.pop(0 if scene == 0 else -1 if scene == 1 else len(pool) // 2))
    return shots


def raw_footage(attraction_videos: List[str]) -> List[str]:
    """One kept raw generation (raw_<clip stem>_<key>.mp4, beside the clip) per stop: the camera move
    alone, with no label, hold or slow-move tail."""
    raws = []
    for clip in attraction_videos:
        if clip:
            found = sorted(Path(clip).parent.glob(f"raw_{Path(clip).stem}_*.mp4"))
            if found:
                raws.append(str(found[0]))
    return raws


_TRANSPORT = re.compile(tuning.INTRO_TRANSPORT_PATTERN, re.I)


def is_transport_stop(clip: str, waypoint_count: int) -> bool:
    """The start/end stop, or a station / bus stop / pier by name: not intro scenery."""
    m = re.match(r"04_attraction_(\d+)_(.*)", Path(clip).stem)
    if not m:
        return False
    idx = int(m.group(1))
    return idx == 0 or idx >= waypoint_count - 1 or bool(_TRANSPORT.search(m.group(2)))


def _scene_sources(waypoints: List[Dict[str, Any]], attraction_videos: List[str]) -> List[str]:
    from services.vdoprocessing.place_label import unburned_place_label

    scenic = [p for p in attraction_videos if p and not is_transport_stop(p, len(waypoints))]
    attraction_videos = scenic or attraction_videos
    # The finished attraction videos (colour-matched, framed by the stop's camera preset). Older ones
    # have the place name burned in; those stops use their kept raw generation instead.
    clips = [p for p in attraction_videos if p and Path(p).is_file()]
    clean = [p for p in clips if unburned_place_label(p) is not None]
    sources = clean + raw_footage([p for p in clips if p not in clean])
    if sources:
        return sources
    seen: List[str] = []
    n = len(waypoints)
    scenic_wps = [w for i, w in enumerate(waypoints)
                  if 0 < i < n - 1 and not _TRANSPORT.search(str(w.get("label") or w.get("name") or ""))]
    for wp in scenic_wps if any(w.get("popup_image") for w in scenic_wps) else waypoints:
        popup_image = wp.get("popup_image")
        for img in popup_image if isinstance(popup_image, list) else [popup_image]:
            if img and img not in seen and Path(img).is_file():
                seen.append(img)
    return seen


def styled_intro_seconds(style: str, duration_sec: Optional[float] = None) -> float:
    return joined_seconds(styled_scenes(style, duration_sec))


def joined_seconds(scenes: List[Dict[str, Any]]) -> float:
    """The scenes crossfaded together: each join overlaps by one crossfade."""
    return sum(s["seconds"] for s in scenes) - (len(scenes) - 1) * tuning.INTRO_CROSSFADE_SECONDS


def styled_scenes(style: str, duration_sec: Optional[float] = None, cuts: Optional[List[float]] = None) -> List[Dict[str, Any]]:
    """INTRO_STYLE_SCENES[style] lasting `duration_sec` (the overview voice's opening, see
    intro_step.plan_intro_seconds). `cuts`: intro seconds where scene 2, 3... take over (the voice's
    {scene} cues), each crossfade centred on its cut; else every scene stretches by the same factor.
    Cuts that leave a scene shorter than two crossfades are ignored."""
    scenes = tuning.INTRO_STYLE_SCENES[style]
    if not duration_sec:
        return [dict(s) for s in scenes]
    cf = tuning.INTRO_CROSSFADE_SECONDS
    if cuts and len(cuts) == len(scenes) - 1:
        starts = [0.0] + [c - cf / 2 for c in cuts]
        ends = [s + cf for s in starts[1:]] + [duration_sec]
        lengths = [e - s for s, e in zip(starts, ends)]
        if all(n >= 2 * cf for n in lengths):
            return [{**s, "seconds": n} for s, n in zip(scenes, lengths)]
    factor = (duration_sec + (len(scenes) - 1) * cf) / sum(s["seconds"] for s in scenes)
    return [{**s, "seconds": max(2 * cf, s["seconds"] * factor)} for s in scenes]


def generate_styled_intro(
    video_dir: str,
    style: str,
    waypoints: List[Dict[str, Any]],
    attraction_videos: List[str],
    output_filename: str = tuning.INTRO_OUTPUT_FILENAME,
    duration_sec: Optional[float] = None,
    cuts: Optional[List[float]] = None,
) -> Optional[str]:
    """A text-led intro (tuning.INTRO_STYLE_SCENES[style]): a close-up scene, then a wide one, from the
    attraction clips (else the waypoint photos), crossfaded, faded from/to black, with the logo badge.
    The lines ride on the timeline's text track (intro_step.intro_text_items). None (logged) on failure."""
    scenes = styled_scenes(style, duration_sec, cuts)
    densities: Dict[str, float] = {}
    stills: Dict[str, np.ndarray] = {}  # held-photo clips: drawn like photos, with the zoom/pan
    lengths: Dict[str, float] = {}
    for src in _scene_sources(waypoints, attraction_videos):
        lengths[src] = _source_seconds(src)
        frame = _frame_at(src, 0.5, lengths[src])
        if frame is None:
            continue
        densities[src] = edge_density(frame)
        if Path(src).suffix.lower() in _VIDEO_EXTS:
            early, late = _frame_at(src, 0.2, lengths[src]), _frame_at(src, 0.8, lengths[src])
            if early is not None and late is not None and is_still(early, late):
                stills[src] = frame
                lengths[src] = float("inf")
    picks = pick_scenes(densities, len(scenes))
    if not picks:
        logger.warning("Intro: no attraction clips or waypoint photos to build a %s intro from.", style)
        return None
    logger.info("Intro (%s): scenes %s", style, picks)

    video_dir_path = Path(video_dir)
    video_dir_path.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex[:8]
    combined_path = video_dir_path / f".intro_combined_{run_id}.mp4"
    raws: List[str] = []
    cf = tuning.INTRO_CROSSFADE_SECONDS
    pool = [p for p in sorted(densities, key=lambda p: densities[p], reverse=True) if p not in picks]
    try:
        for idx, (scene, src) in enumerate(zip(scenes, picks)):
            raw = str(video_dir_path / f".intro_raw_{run_id}_{idx}.mp4")
            shots = plan_shots(scene["seconds"], src, pool, lengths, cf, idx)
            if len(shots) > 1:
                logger.info("Intro: scene %d (%.1fs) runs on %d shots: %s", idx + 1, scene["seconds"], len(shots), shots)
            shot_sec = (scene["seconds"] + (len(shots) - 1) * cf) / len(shots)
            parts = []
            for j, shot in enumerate(shots):
                part = raw if len(shots) == 1 else str(video_dir_path / f".intro_raw_{run_id}_{idx}_{j}.mp4")
                raws.append(part)
                parts.append(part)
                if Path(shot).suffix.lower() in _VIDEO_EXTS and shot not in stills:
                    _render_clip_slice(shot, part, shot_sec, scene["dim"], scene["sat"])
                else:
                    image = stills[shot] if shot in stills else _read_image_safe(shot)
                    if image is None:
                        return None
                    _render_zoom_in(image, part, shot_sec, scene["zoom"], scene["pan"], scene["dim"], scene["sat"])
            if len(parts) > 1:
                _crossfade_chain(parts, [shot_sec] * len(parts), cf, raw)
                raws.append(raw)
        scene_raws = [str(video_dir_path / f".intro_raw_{run_id}_{i}.mp4") for i in range(len(scenes))]
        _crossfade_chain(scene_raws, [s["seconds"] for s in scenes], cf, str(combined_path))
        if not _finish_intro(combined_path, joined_seconds(scenes), "null", video_dir_path, run_id,
                             video_dir_path / output_filename):
            return None
    except Exception as exc:
        logger.error("Intro generation failed: %s", exc)
        return None
    finally:
        combined_path.unlink(missing_ok=True)
        for p in raws:
            Path(p).unlink(missing_ok=True)
    return str(video_dir_path / output_filename)
