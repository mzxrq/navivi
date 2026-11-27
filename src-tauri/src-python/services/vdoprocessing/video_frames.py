"""Reading a clip's frames and the ffmpeg command that encodes raw frames: what the per-frame clip filters share
(colour match, sign lock, slow move, the 3D photo move)."""

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

from services import runtime_paths, tuning
from services.logger.logger import setup_logger

logger = setup_logger(__name__)


def read_frames(video_path: str) -> Tuple[List[np.ndarray], float]:
    """(every frame of the clip, its frame rate or 0.0 when the file does not say)."""
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    frames = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(frame)
    cap.release()
    return frames, fps


def raw_encoder_command(width: int, height: int, fps: float, out_path: str, crf: int) -> List[str]:
    """The ffmpeg command that reads raw BGR frames from stdin and writes an H.264 mp4 to `out_path`."""
    from services.tts.ttsengine import FFmpegManager

    return [
        FFmpegManager.resolve_ffmpeg_bin(), "-y", *tuning.ffmpeg_pipe_log_args(),
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}", "-r", f"{fps:.3f}", "-i", "-",
        "-c:v", "libx264", *tuning.ffmpeg_thread_args(), "-crf", str(crf), "-preset", "fast",
        "-pix_fmt", "yuv420p", out_path,
    ]


def clip_end_frames(clip_path: str, out_dir: str) -> Optional[Tuple[str, str]]:
    """(first frame, last frame) of a clip as PNGs in `out_dir`, or None when either cannot be read.

    Each file is named after its own picture, so a remade clip gives new names and the legs showing it re-render.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    frames = []
    for end, before, after in (("first", [], ["-frames:v", "1"]), ("last", ["-sseof", "-1"], ["-update", "1"])):
        handle, temp = tempfile.mkstemp(suffix=".png", dir=out)
        os.close(handle)
        try:
            result = subprocess.run(
                [runtime_paths.ffmpeg_exe() or "ffmpeg", "-y", *tuning.ffmpeg_log_args(), *before,
                 "-i", str(clip_path), *after, temp],
                capture_output=True, encoding="utf-8", errors="replace",
            )
            data = Path(temp).read_bytes()
            if result.returncode != 0 or not data:
                logger.warning("No %s frame from '%s': %s", end, clip_path, result.stderr.strip()[-300:])
                return None
            # shortcut: frames of earlier versions of a clip stay on disk; clear the folder if it ever grows large.
            target = out / f"{Path(clip_path).stem}_{end}_{hashlib.sha256(data).hexdigest()[:10]}.png"
            if not target.exists():  # rewriting it would change its mtime, which the legs hash
                os.replace(temp, target)
            frames.append(str(target))
        finally:
            Path(temp).unlink(missing_ok=True)
    return frames[0], frames[1]
