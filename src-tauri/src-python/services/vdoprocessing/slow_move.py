"""Fills an attraction clip's gap before its narration ends with a slow camera
move over its own last frame, instead of freezing that frame.

A Wan clip covers only a few seconds (tuning.COMFYUI_MAX_FRAMES, times
COMFYUI_EXTEND_MAX_SEGMENTS); longer narration used to hold the last frame
still for the rest. Continuing the preset's direction as a plain 2D move on
that frame keeps the picture moving without generating anything new, so it
cannot drift or invent objects the way extra Wan segments do.
"""

import math
import random
import subprocess
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from services import tuning
from services.logger.logger import setup_logger
from services.vdoprocessing.camera_pan import normalize_camera_pan

logger = setup_logger("SlowMove")

# The presets that get a slow tail (every editor move; "none" is a still).
# The tail itself doesn't follow the preset: each clip picks a random gentle
# drift (see _random_drift), always on a slow push-in, which keeps the frame
# edges out of view while drifting. Zoom In/Out are jump cuts and hold instead.
# Dollies too since they became LTXV (2026-10-07): a 4 s dolly-out then sat
# frozen for 6.4 s of 西ノ庄駅's narration.
_MOVING = {"panright", "panleft", "panup", "pandown", "walkin", "zoomin", "zoomout"}


def _random_drift(rng: random.Random) -> tuple:
    """(dx, dy, zoom per second): a random direction, a random share of the
    push-in's margin (so it never shows an edge) and a random speed around
    tuning.ATTRACTION_SLOW_MOVE_ZOOM_PER_SEC."""
    angle = rng.uniform(0.0, 2.0 * math.pi)
    strength = rng.uniform(0.3, 1.0)
    rate = tuning.ATTRACTION_SLOW_MOVE_ZOOM_PER_SEC * rng.uniform(0.75, 1.25)
    return math.cos(angle) * strength, math.sin(angle) * strength, rate


def is_moving_preset(camera_pan) -> bool:
    key = normalize_camera_pan(camera_pan)
    return key in _MOVING


def _progress(t: float, gap: float, ease: float = 1.0) -> float:
    """Seconds' worth of movement done by time t of a gap-long move: full
    speed from the join (so it carries straight on from the clip), slowing
    linearly to a stop over the last `ease` seconds."""
    ease = min(ease, gap)
    cruise = gap - ease
    if t <= cruise:
        return t
    u = min(t, gap) - cruise
    return cruise + u - u * u / (2 * ease)


def _last_frame(video_path: str) -> Optional[np.ndarray]:
    cap = cv2.VideoCapture(video_path)
    last = None
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            last = frame
    finally:
        cap.release()
    return last


def _fps(video_path: str) -> float:
    cap = cv2.VideoCapture(video_path)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
    finally:
        cap.release()
    return fps if fps and fps > 0 else float(tuning.COMFYUI_FPS)


def _scale_about_centre(frame: np.ndarray, scale: float) -> np.ndarray:
    h, w = frame.shape[:2]
    m = np.array(
        [[scale, 0.0, w / 2 * (1 - scale)], [0.0, scale, h / 2 * (1 - scale)]],
        dtype=np.float32,
    )
    return cv2.warpAffine(frame, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)


def zoom_out_scales(gap: float, fps: float, frames: int):
    """(the whole clip's starting zoom, [zoom of each tail frame]): the tail
    eases from that zoom back to exactly 1.0 (the full picture) - full speed
    from the join, slowing to a stop at the end (see _progress). The zoom is
    tuning.ATTRACTION_SLOW_MOVE_ZOOM_PER_SEC's worth of the gap, at most
    ATTRACTION_SLOW_MOVE_MAX_ZOOM_OUT."""
    travel = _progress(gap, gap)
    total = min(tuning.ATTRACTION_SLOW_MOVE_ZOOM_PER_SEC * travel, tuning.ATTRACTION_SLOW_MOVE_MAX_ZOOM_OUT)
    start = 1.0 + total
    tail = [start - total * (_progress(i / fps, gap) / travel if travel > 0 else 1.0) for i in range(1, frames + 1)]
    return start, tail


def _extend_with_zoom_out(video_path: str, gap: float, output_path: str) -> Optional[str]:
    """video_path shown slightly zoomed in, then a slow centred zoom-out over
    its last frame back to the full picture, lasting `gap` seconds. The Wan
    part and the tail go through the same scaling, so the join doesn't move
    by even a pixel. One encode, no separate tail file."""
    from services.tts.ttsengine import FFmpegManager

    fps = _fps(video_path)
    frames = max(1, int(round(gap * fps)))
    start, tail = zoom_out_scales(gap, fps, frames)

    cap = cv2.VideoCapture(video_path)
    ok, first = cap.read()
    if not ok:
        cap.release()
        return None
    h, w = first.shape[:2]
    proc = subprocess.Popen(
        [
            FFmpegManager.resolve_ffmpeg_bin(), "-y", *tuning.ffmpeg_pipe_log_args(),
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{fps:.3f}", "-i", "-",
            "-c:v", "libx264", *tuning.ffmpeg_thread_args(), "-crf", "18", "-preset", "fast",
            "-pix_fmt", "yuv420p", output_path,
        ],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        last = first
        frame = first
        while frame is not None:
            last = frame
            proc.stdin.write(_scale_about_centre(frame, start).tobytes())
            ok, frame = cap.read()
            if not ok:
                frame = None
        for scale in tail:
            proc.stdin.write(_scale_about_centre(last, scale).tobytes())
        proc.stdin.close()
        if proc.wait() != 0:
            logger.warning("Zoom-out tail failed: %s", proc.stderr.read().decode("utf-8", "replace"))
            return None
    except Exception:
        proc.kill()
        raise
    finally:
        cap.release()
    logger.info(
        "Filled %.1fs after %s with a slow zoom-out (clip shown at %.1f%%, ending at 100%%).",
        gap, video_path, start * 100,
    )
    return output_path


def extend_with_slow_move(
    video_path: str, target_duration: float, camera_pan, output_path: str,
    rng: Optional[random.Random] = None,
) -> Optional[str]:
    """video_path followed by a slow move over its last frame, lasting until
    target_duration. Returns output_path, or None when there is nothing to
    add, the preset doesn't move, or anything fails (the caller then keeps
    the old last-frame hold)."""
    key = normalize_camera_pan(camera_pan)
    if key not in _MOVING:
        return None
    try:
        from services.tts.ttsengine import FFmpegManager

        current = FFmpegManager.get_media_duration(video_path)
        gap = target_duration - current
        if gap <= 0.05:
            return None
        # A dolly-in keeps pushing in; a zoom-out tail would reverse it.
        if tuning.ATTRACTION_SLOW_MOVE_STYLE == "zoomout" and key != "zoomin":
            return _extend_with_zoom_out(video_path, gap, output_path)
        frame = _last_frame(video_path)
        if frame is None:
            return None
        fps = _fps(video_path)
        h, w = frame.shape[:2]
        dx, dy, rate = _random_drift(rng or random.Random())
        if key == "zoomin":
            dx = dy = 0.0
        frames = max(1, int(round(gap * fps)))

        tail_path = str(Path(output_path).with_suffix(".tail.mp4"))
        ffmpeg = FFmpegManager.resolve_ffmpeg_bin()
        proc = subprocess.Popen(
            [
                ffmpeg, "-y", *tuning.ffmpeg_pipe_log_args(),
                "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{fps:.3f}", "-i", "-",
                "-c:v", "libx264", *tuning.ffmpeg_thread_args(), "-crf", "18", "-preset", "fast",
                "-pix_fmt", "yuv420p", tail_path,
            ],
            stdin=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            for i in range(1, frames + 1):
                scale = 1.0 + rate * _progress(i / fps, gap)
                # Drift uses up to 90% of the margin the push-in has made.
                margin_x = (scale - 1.0) * w / 2 * 0.9
                margin_y = (scale - 1.0) * h / 2 * 0.9
                cx, cy = w / 2 + dx * margin_x, h / 2 + dy * margin_y
                # Sub-pixel affine (scale about the moving centre), so a very
                # slow move glides instead of stepping a whole pixel at a time.
                m = np.array(
                    [[scale, 0.0, w / 2 - scale * cx], [0.0, scale, h / 2 - scale * cy]],
                    dtype=np.float32,
                )
                out = cv2.warpAffine(frame, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
                proc.stdin.write(out.tobytes())
            proc.stdin.close()
            if proc.wait() != 0:
                logger.warning("Slow move tail failed: %s", proc.stderr.read().decode("utf-8", "replace"))
                return None
        except Exception:
            proc.kill()
            raise

        concat = subprocess.run(
            [
                ffmpeg, "-y", *tuning.ffmpeg_log_args(), "-i", video_path, "-i", tail_path,
                "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]",
                "-c:v", "libx264", *tuning.ffmpeg_thread_args(), "-crf", "18", "-preset", "fast",
                "-pix_fmt", "yuv420p", output_path,
            ],
            capture_output=True, encoding="utf-8", errors="replace",
        )
        Path(tail_path).unlink(missing_ok=True)
        if concat.returncode != 0:
            logger.warning("Slow move join failed: %s", concat.stderr.strip())
            return None
        logger.info(
            "Filled %.1fs after %s with a slow move (drift %.2f, %.2f; +%.1f%%/s).",
            gap, video_path, dx, dy, rate * 100,
        )
        return output_path
    except Exception as exc:
        logger.warning("Slow move failed for %s (%s) - keeping the last-frame hold.", video_path, exc)
        return None
