"""
Frame Sink Service (frame_sink.py)
----------------------------------------------------------------------------
This module provides a robust frame sink service that writes video frames to a file.
It attempts to use FFmpeg for high-performance video encoding, and falls back to OpenCV's
VideoWriter if FFmpeg is unavailable. The service handles frame writing, resource management,
and re-encoding to H.264 format when necessary.
----------------------------------------------------------------------------
"""

import os
import subprocess
import tempfile
from pathlib import Path
import cv2
import numpy as np

from services import tuning
from services.logger.logger import setup_logger

# Logging configuration
logger = setup_logger("FrameSink")


# [NOTE] [Editor] FrameSink writes frames to a video file via FFmpeg, falling back to OpenCV's VideoWriter if FFmpeg is unavailable.
class FrameSink:
    """Handles writing frames to a video file using FFmpeg or OpenCV fallback."""

    # [Config] Setup the FFmpeg path
    def __init__(self, output_path: str, w: int, h: int, fps: int, ffmpeg_path: Path):
        self.ffmpeg_path = ffmpeg_path
        self.w = w
        self.h = h
        self.fps = fps
        self.proc = self._open_ffmpeg_writer(output_path, w, h, fps)
        self._fallback_path = None
        self._fallback_writer = None

        if self.proc is None:
            self._fallback_path = tempfile.mktemp(suffix=".avi")
            # [NOTE] [Editor] 0x44495658 is the raw FOURCC for "XVID" packed
            # as a little-endian int — used directly instead of
            # cv2.VideoWriter_fourcc(*"XVID") for the same result.
            self._fallback_writer = cv2.VideoWriter(
                self._fallback_path, 0x44495658, fps, (w, h)
            )
            if not self._fallback_writer.isOpened():
                raise RuntimeError(
                    "Neither ffmpeg nor OpenCV VideoWriter is available."
                )

    # [Editor] Write a frame to the video file
    def write(self, frame: np.ndarray) -> None:
        # Check if FFmpeg process is running and its stdin pipe is open
        if self.proc is not None and self.proc.stdin is not None:
            try:
                # Ensure frame matches expected dimensions
                if frame.shape[0] != self.h or frame.shape[1] != self.w:
                    frame = cv2.resize(frame, (self.w, self.h))
                self.proc.stdin.write(frame.tobytes())
            except (BrokenPipeError, AttributeError) as e:
                # [NOTE] [Editor] Raises instead of silently switching to
                # _fallback_writer here — every frame written before this
                # point went to the now-dead ffmpeg pipe, not to
                # _fallback_writer, so a mid-stream switch would produce a
                # video silently missing everything written so far rather
                # than failing loudly. Matches VideoExporter.write's own
                # behavior on a broken pipe.
                logger.error(f"FFmpeg pipe failed: {e}")
                self.proc = None  # Disable broken pipe
                raise RuntimeError(f"FFmpeg pipe failed mid-stream: {e}") from e
        elif self._fallback_writer is not None:
            # Fallback to OpenCV writer if FFmpeg is None
            self._fallback_writer.write(frame)
        else:
            raise RuntimeError(
                "No active video writer available (both FFmpeg and OpenCV failed)."
            )

    def release(self, output_path: str) -> str:
        if self.proc is not None:
            try:
                if self.proc.stdin:
                    self.proc.stdin.close()
                self.proc.wait()
            except Exception as e:
                logger.warning(f"Error while closing FFmpeg stdin: {e}")
            # [NOTE] [Editor] Checked after wait() (unlike before) — a
            # non-zero exit means ffmpeg failed partway through encoding,
            # so output_path is likely missing or truncated even though
            # the process itself didn't raise.
            if self.proc.returncode not in (0, None):
                raise RuntimeError(
                    f"FFmpeg exited with code {self.proc.returncode} while writing {output_path}"
                )
            return output_path

        if self._fallback_writer:
            self._fallback_writer.release()

        if self._fallback_path and Path(self._fallback_path).exists():
            if output_path.lower().endswith(".mp4") and self._reencode_to_h264(
                self._fallback_path, output_path
            ):
                try:
                    os.remove(self._fallback_path)
                except OSError:
                    pass
                return output_path

            avi_path = str(Path(output_path).with_suffix(".avi"))
            try:
                os.rename(self._fallback_path, avi_path)
            except OSError:
                avi_path = self._fallback_path
            return avi_path

        return output_path

    # [Util/Config] Open an FFmpeg process for writing video frames
    def _open_ffmpeg_writer(self, output_path: str, w: int, h: int, fps: int):
        if not self.ffmpeg_path.exists():
            return None
        cmd = [
            str(self.ffmpeg_path),
            "-y",
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{w}x{h}",
            "-r",
            str(fps),
            "-i",
            "-",
            "-an",
            "-vcodec",
            "libx264",
            *tuning.ffmpeg_thread_args(),
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ]
        try:
            return subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            return None

    # [Util/Core] Re-encoding operations
    def _reencode_to_h264(self, src: str, dst: str) -> bool:
        if not self.ffmpeg_path.exists():
            return False
        try:
            r = subprocess.run(
                [
                    str(self.ffmpeg_path),
                    "-y",
                    "-i",
                    src,
                    "-vcodec",
                    "libx264",
                    *tuning.ffmpeg_thread_args(),
                    "-crf",
                    "18",
                    "-preset",
                    "fast",
                    "-pix_fmt",
                    "yuv420p",
                    dst,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return r.returncode == 0
        except FileNotFoundError:
            return False