"""A hand-held camera feel added to a finished attraction clip: a slow seeded
drift (breathing hands) on every move, plus footsteps on walking moves. Done
after generation because prompting LTX for "hand-held" draws hands and feet."""

import math
import random
import subprocess
from pathlib import Path
from typing import List, Tuple

import cv2

from services import tuning
from services.logger.logger import setup_logger

logger = setup_logger("Handheld")


def offsets(frames: int, fps: float, walking: bool, seed: str) -> List[Tuple[float, float, float]]:
    """(dx share of width, dy share of height, roll degrees) per frame."""
    rng = random.Random(seed)
    waves = [[(rng.uniform(0.15, 0.7), rng.uniform(0, 2 * math.pi)) for _ in range(3)] for _ in range(3)]

    def drift(axis: int, t: float) -> float:
        return sum(math.sin(2 * math.pi * f * t + p) for f, p in waves[axis]) / 3

    out = []
    for i in range(frames):
        t = i / fps
        dx = tuning.HANDHELD_DRIFT * drift(0, t)
        dy = tuning.HANDHELD_DRIFT * drift(1, t)
        roll = tuning.HANDHELD_ROLL_DEG * drift(2, t)
        if walking:  # parallax_generator.walk_camera's step bob, sway and roll
            steps = math.pi * tuning.PARALLAX_WALK_STEPS_PER_SEC * t
            dx += tuning.PARALLAX_WALK_SWAY * math.sin(steps / 2)
            dy += tuning.PARALLAX_WALK_BOB * (abs(math.sin(steps)) - 0.5)
            roll += tuning.PARALLAX_WALK_ROLL_DEG * math.sin(steps / 2)
        out.append((dx, dy, roll))
    return out


def _grow(moves: List[Tuple[float, float, float]], w: int, h: int) -> float:
    """Zoom that keeps the corners filled at the largest shift and roll."""
    a = math.radians(max(abs(r) for _, _, r in moves))
    shift = max(max(abs(dx), abs(dy)) for dx, dy, _ in moves)
    return math.cos(a) + math.sin(a) * max(w / h, h / w) + 2 * shift


def apply_handheld(src: str, dst: str, walking: bool, seed: str) -> bool:
    """Writes `src` with the hand-held motion to `dst`; False (and no `dst`) on any failure."""
    from services.tts.ttsengine import FFmpegManager

    tmp = Path(dst).with_suffix(".part.mp4")
    try:
        cap = cv2.VideoCapture(src)
        fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if n <= 0 or w <= 0 or h <= 0:
            cap.release()
            return False
        moves = offsets(n, fps, walking, seed)
        grow = _grow(moves, w, h)
        proc = subprocess.Popen(
            [
                FFmpegManager.resolve_ffmpeg_bin(), "-y", *tuning.ffmpeg_pipe_log_args(),
                "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{fps:.3f}", "-i", "-",
                "-c:v", "libx264", *tuning.ffmpeg_thread_args(), "-crf", "16", "-preset", "fast",
                "-pix_fmt", "yuv420p", str(tmp),
            ],
            stdin=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            for dx, dy, roll in moves:
                ok, frame = cap.read()
                if not ok:
                    break
                m = cv2.getRotationMatrix2D((w / 2, h / 2), roll, grow)
                m[0, 2] += dx * w
                m[1, 2] += dy * h
                proc.stdin.write(cv2.warpAffine(frame, m, (w, h), flags=cv2.INTER_LINEAR,
                                                borderMode=cv2.BORDER_REFLECT).tobytes())
            proc.stdin.close()
            if proc.wait() != 0:
                logger.warning("Hand-held encode failed: %s", proc.stderr.read().decode("utf-8", "replace"))
                return False
        except Exception:
            proc.kill()
            raise
        finally:
            cap.release()
        tmp.replace(dst)
        return True
    except Exception as exc:
        logger.warning("Hand-held finish failed for %s (%s) - keeping the steady clip.", src, exc)
        return False
    finally:
        tmp.unlink(missing_ok=True)
