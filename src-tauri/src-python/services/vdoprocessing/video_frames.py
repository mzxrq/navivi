"""Reading a clip's frames and the ffmpeg command that encodes raw frames: what the per-frame clip filters share
(colour match, sign lock, slow move, the 3D photo move)."""

from typing import List, Tuple

import cv2
import numpy as np

from services import tuning


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
