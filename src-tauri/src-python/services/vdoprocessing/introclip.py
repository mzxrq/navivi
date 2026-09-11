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

import random
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from services.localization.subtitle import SubtitleStyle
from services.logger.logger import setup_logger
from services.tts.ttsengine import FFmpegManager
from services import tuning

logger = setup_logger("IntroClip")

# Centered, bold, larger than a normal subtitle line — this is a title card,
# not a caption. Keeps the same outline/shadow approach as SubtitleStyle's
# default so it stays readable over any busy background photo.
_TITLE_STYLE = SubtitleStyle(
    font_size=tuning.INTRO_TITLE_FONT_SIZE,
    bold=True,
    alignment=10,  # old-SSA numbering (see SubtitleStyle.alignment) = middle-center
    outline=tuning.INTRO_TITLE_OUTLINE,
    shadow=1.0,
    margin_v=0,
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


def _render_zoom_in(image_bgr: np.ndarray, raw_output_path: str, duration_sec: float) -> None:
    """Renders a centered Ken Burns zoom-in over a still image: the visible
    crop shrinks from INTRO_ZOOM_START to INTRO_ZOOM_END (ease-in-out) while
    staying centered on the image, giving the impression of pushing in."""
    # [NOTE] [Animation] Ease-in-out crop shrink around a fixed center is the whole
    # Ken Burns effect — no keyframe/spline library needed for a single push-in.
    sh, sw = image_bgr.shape[:2]
    out_w, out_h = tuning.INTRO_WIDTH, tuning.INTRO_HEIGHT
    fit_w, fit_h = _cover_fit(sw, sh, out_w / out_h)
    cx, cy = sw / 2, sh / 2

    num_frames = max(1, round(duration_sec * tuning.INTRO_FPS))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(raw_output_path, fourcc, tuning.INTRO_FPS, (out_w, out_h))

    dim = tuning.INTRO_IMAGE_DIM_FACTOR

    for i in range(num_frames):
        t = _ease_in_out(i / max(1, num_frames - 1))
        zoom = tuning.INTRO_ZOOM_START + (tuning.INTRO_ZOOM_END - tuning.INTRO_ZOOM_START) * t
        half_w, half_h = fit_w * zoom / 2, fit_h * zoom / 2
        x0, y0, x1, y1 = _crop_rect(cx, cy, half_w, half_h, sw, sh)
        crop = image_bgr[y0:y1, x0:x1]
        frame = cv2.resize(crop, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)
        if dim < 1.0:
            frame = cv2.convertScaleAbs(frame, alpha=dim, beta=0)
        writer.write(frame)

    writer.release()


def _crossfade_chain(
    clip_paths: List[str], per_clip_sec: float, crossfade_sec: float, output_path: str
) -> None:
    """Chains N same-length, same-resolution clips into one video, each
    crossfading into the next via ffmpeg's `xfade` filter. Raises
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
    cumulative = per_clip_sec
    for i in range(1, len(clip_paths)):
        offset = cumulative - crossfade_sec
        out_label = f"v{i}"
        filter_parts.append(
            f"[{prev_label}][{i}:v]xfade=transition=fade:"
            f"duration={crossfade_sec:.3f}:offset={offset:.3f}[{out_label}]"
        )
        prev_label = out_label
        cumulative += per_clip_sec - crossfade_sec

    cmd = [
        ffmpeg_cmd, "-y",
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


def _write_title_ass(text: str, duration_sec: float, tmp_dir: Path) -> Path:
    """Writes a throwaway single-line .ass (not .srt) spanning the whole
    intro, with inline ASS override tags on the dialogue line itself giving
    the TITLE TEXT its own "pop in" transition — a combined scale-up +
    fade-in on the way in, and the reverse on the way out — independent of
    the whole-frame fade applied later in the same ffmpeg pass. force_style
    (applied via the `subtitles` filter, same as before) still controls
    font/size/color/position; the Style line below just needs to exist and
    be named "Default" for that to have something to override."""
    fade_ms = int(round(tuning.INTRO_LABEL_FADE_SECONDS * 1000))
    duration_ms = int(round(duration_sec * 1000))
    fade_out_start_ms = max(0, duration_ms - fade_ms)
    scale_start = tuning.INTRO_LABEL_SCALE_START_PCT
    # \fad handles the opacity half of the transition; \t animates \fscx/
    # \fscy (ASS's font-scale override) across the same windows for the
    # scale half — \fscx60\fscy60 sets the STARTING scale (t=0), then each
    # \t(start,end,...) animates toward the scale given inside it over that
    # window, in timeline order: pop up to 100% during the fade-in window,
    # hold, then shrink back down during the fade-out window.
    override = (
        f"{{\\fad({fade_ms},{fade_ms})"
        f"\\fscx{scale_start}\\fscy{scale_start}"
        f"\\t(0,{fade_ms},\\fscx100\\fscy100)"
        f"\\t({fade_out_start_ms},{duration_ms},\\fscx{scale_start}\\fscy{scale_start})}}"
    )
    # Braces would be parsed as an ASS override-tag delimiter if left in —
    # strip them from arbitrary project-name text rather than escaping.
    safe_text = (text or "").replace("{", "").replace("}", "")
    end_ts = _format_ass_timestamp(duration_sec)

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
        "Effect, Text\n"
        f"Dialogue: Marked=0,0:00:00.00,{end_ts},Default,,0000,0000,0000,,"
        f"{override}{safe_text}\n",
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


def generate_intro_clip(
    video_dir: str,
    project_name: str,
    waypoints: List[Dict[str, Any]],
    output_filename: str = tuning.INTRO_OUTPUT_FILENAME,
) -> Optional[str]:
    """Picks up to INTRO_IMAGE_COUNT random, distinct waypoint popup images
    (a fresh pick every call), renders a slow zoom-in over each, crossfades
    them into one slideshow, and burns project_name centered on top with a
    fade in/out at the very start/end. Returns the output path, or None
    (logged, never raises) if there are no waypoint images or generation
    fails — an intro is a nice-to-have, not something that should hard-fail
    a pipeline run."""
    image_paths = _pick_random_images(waypoints, tuning.INTRO_IMAGE_COUNT)
    if not image_paths:
        logger.warning("No waypoint popup images available — cannot build an intro yet.")
        return None

    logger.info("Intro: picked %d source image(s): %s", len(image_paths), image_paths)

    video_dir_path = Path(video_dir)
    video_dir_path.mkdir(parents=True, exist_ok=True)
    output_path = video_dir_path / output_filename
    run_id = uuid.uuid4().hex[:8]
    per_clip_raw_paths: List[str] = []
    combined_path = video_dir_path / f".intro_combined_{run_id}.mp4"
    title_path: Optional[Path] = None

    per_clip_sec = tuning.INTRO_PER_IMAGE_SECONDS
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
        _crossfade_chain(per_clip_raw_paths, per_clip_sec, crossfade_sec, str(combined_path))

        title_path = _write_title_ass(project_name or "", total_sec, video_dir_path)

        # [HACK] [Subtitle] Absolute, forward-slashed, colon-escaped path — libass's
        # subtitles filter needs this exact escaping, same as combine_video_and_audio.
        escaped_title_path = str(title_path.resolve()).replace("\\", "/").replace(":", r"\:")
        fade_sec = tuning.INTRO_FADE_SECONDS
        vf_filter = (
            f"subtitles=filename='{escaped_title_path}':force_style='{_TITLE_STYLE.to_force_style()}',"
            f"fade=t=in:st=0:d={fade_sec:.2f},"
            f"fade=t=out:st={max(0.0, total_sec - fade_sec):.2f}:d={fade_sec:.2f}"
        )

        ffmpeg_cmd = FFmpegManager.resolve_ffmpeg_bin()
        cmd = [
            ffmpeg_cmd, "-y",
            "-i", str(combined_path),
            "-vf", vf_filter,
            "-an",
            "-c:v", "libx264", *tuning.ffmpeg_thread_args(), "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p",
            str(output_path),
        ]
        result = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", errors="replace"
        )
        if result.returncode != 0:
            logger.error("Intro generation failed: %s", result.stderr.strip())
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
