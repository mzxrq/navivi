"""Pulls a generated attraction clip's colours back to its source photo.

Wan "grades" what it generates: contrast and saturation climb over the clip,
and each extension segment can jump in brightness (a 石標 clip went from the
photo's L 132 / spread 62 to L 164 / spread 86). The prompts ask for the
original colours, but only this pass guarantees them: every frame's LAB mean
and spread are matched to the photo's (the same crop Wan saw), with the
per-frame correction smoothed over time so content moving in and out of view
doesn't make it flicker.
"""

import subprocess
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

from services import tuning
from services.logger.logger import setup_logger

logger = setup_logger("ColorMatch")

# Frames are measured at this width (colour stats don't need full size).
_STATS_WIDTH = 320


def _lab_stats(image_bgr: np.ndarray) -> np.ndarray:
    """[[mean L, a, b], [spread L, a, b]] of an image, measured small."""
    h, w = image_bgr.shape[:2]
    if w > _STATS_WIDTH:
        image_bgr = cv2.resize(image_bgr, (_STATS_WIDTH, max(1, round(h * _STATS_WIDTH / w))), interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float64)
    return np.stack([lab.mean(0), np.maximum(lab.std(0), 1.0)])


def _crop_to_aspect(image_bgr: np.ndarray, width: int, height: int) -> np.ndarray:
    """The centre crop of the photo with the clip's aspect ratio - the part
    of the photo the clip actually shows."""
    h, w = image_bgr.shape[:2]
    target = width / height
    if w / h > target:
        new_w = max(1, round(h * target))
        x = (w - new_w) // 2
        return image_bgr[:, x:x + new_w]
    new_h = max(1, round(w / target))
    y = (h - new_h) // 2
    return image_bgr[y:y + new_h]


def _smooth(stats: List[np.ndarray], radius: int) -> List[np.ndarray]:
    """Centred moving average over +/-radius frames."""
    arr = np.stack(stats)
    out = []
    for i in range(len(arr)):
        lo, hi = max(0, i - radius), min(len(arr), i + radius + 1)
        out.append(arr[lo:hi].mean(0))
    return out


def correct_frame(frame_bgr: np.ndarray, frame_stats: np.ndarray, target_stats: np.ndarray,
                  strength: float = 1.0) -> np.ndarray:
    """frame_bgr with its LAB mean/spread moved to target_stats (strength
    1.0 = fully, 0 = untouched). The lightness gain is clamped so a nearly
    flat frame can't be blown up, and the colour (a/b) gain never goes above
    1: it only takes back saturation Wan added, so it can never amplify a
    faint tint Wan left in a grey area into a visible colour."""
    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    gain = np.clip(target_stats[1] / frame_stats[1], 0.5, 2.0)
    gain[1:] = np.minimum(gain[1:], 1.0)
    corrected = (lab - frame_stats[0]) * gain + target_stats[0]
    if strength < 1.0:
        corrected = lab + (corrected - lab) * strength
    return cv2.cvtColor(np.clip(corrected, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)


def match_clip_to_photo(video_path: str, photo_path: str) -> bool:
    """Rewrites video_path in place with its colours matched to photo_path.
    Returns False (leaving the clip untouched) when switched off or on any
    failure."""
    if not tuning.ATTRACTION_COLOR_MATCH:
        return False
    try:
        photo = cv2.imread(photo_path, cv2.IMREAD_COLOR)
        if photo is None:
            # cv2.imread can't open non-ASCII paths on Windows.
            data = np.fromfile(photo_path, dtype=np.uint8)
            photo = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if photo is None:
            logger.warning("Colour match skipped: can't read %s", photo_path)
            return False

        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or float(tuning.COMFYUI_FPS)
        frames = []
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frames.append(frame)
        cap.release()
        if not frames:
            logger.warning("Colour match skipped: no frames in %s", video_path)
            return False

        h, w = frames[0].shape[:2]
        target = _lab_stats(_crop_to_aspect(photo, w, h))
        radius = max(1, round(fps * tuning.ATTRACTION_COLOR_MATCH_SMOOTH_SECONDS / 2))
        stats = _smooth([_lab_stats(f) for f in frames], radius)

        from services.tts.ttsengine import FFmpegManager

        out_path = str(Path(video_path).with_suffix(".colormatch.mp4"))
        proc = subprocess.Popen(
            [
                FFmpegManager.resolve_ffmpeg_bin(), "-y", *tuning.ffmpeg_log_args(),
                "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{fps:.3f}", "-i", "-",
                "-c:v", "libx264", *tuning.ffmpeg_thread_args(), "-crf", "16", "-preset", "fast",
                "-pix_fmt", "yuv420p", out_path,
            ],
            stdin=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            for frame, frame_stats in zip(frames, stats):
                proc.stdin.write(correct_frame(frame, frame_stats, target, tuning.ATTRACTION_COLOR_MATCH_STRENGTH).tobytes())
            proc.stdin.close()
            if proc.wait() != 0:
                logger.warning("Colour match encode failed: %s", proc.stderr.read().decode("utf-8", "replace"))
                Path(out_path).unlink(missing_ok=True)
                return False
        except Exception:
            proc.kill()
            Path(out_path).unlink(missing_ok=True)
            raise

        Path(out_path).replace(video_path)
        drift = np.abs(np.stack(stats) - target).max(0)
        logger.info(
            "Matched %s's colours to %s (largest drift fixed: L %.0f / spread %.0f).",
            Path(video_path).name, Path(photo_path).name, drift[0][0], drift[1][0],
        )
        return True
    except Exception as exc:
        logger.warning("Colour match failed for %s (%s) - keeping Wan's colours.", video_path, exc)
        return False
