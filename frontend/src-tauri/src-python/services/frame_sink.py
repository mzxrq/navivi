"""
Frame Sink Service (frame_sink.py)
"""
'''
This module provides a service for managing frame sink operations, including saving frames to disk and handling related file operations. It is designed to be used within the Tauri application framework, allowing for seamless integration with the frontend.

How to Use:
"""
"""
'''

# Import necessary modules
import os
import subprocess
import tempfile
from pathlib import Path
import cv2
import numpy as np
import logging

# Logging configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class FrameSink:
    """Handles writing frames to a video file using FFmpeg or OpenCV fallback."""

    # =========================
    # Initialization
    # =========================
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
            self._fallback_writer = cv2.VideoWriter(
                self._fallback_path, 0x44495658, fps, (w, h)
            )
            if not self._fallback_writer.isOpened():
                raise RuntimeError("Neither ffmpeg nor OpenCV VideoWriter is available.")

    # ========================
    # Frame writing operations
    # ========================
    def write(self, frame: np.ndarray) -> None:
        # Check if FFmpeg process is running and its stdin pipe is open
        if self.proc is not None and self.proc.stdin is not None:
            try:
                # Ensure frame matches expected dimensions
                if frame.shape[0] != self.h or frame.shape[1] != self.w:
                    frame = cv2.resize(frame, (self.w, self.h))
                self.proc.stdin.write(frame.tobytes())
            except (BrokenPipeError, AttributeError) as e:
                logging.error(f"FFmpeg pipe failed: {e}. Falling back to OpenCV.")
                self.proc = None  # Disable broken pipe
                if self._fallback_writer is not None:
                    self._fallback_writer.write(frame)
        elif self._fallback_writer is not None:
            # Fallback to OpenCV writer if FFmpeg is None
            self._fallback_writer.write(frame)
        else:
            raise RuntimeError("No active video writer available (both FFmpeg and OpenCV failed).")

    # ========================
    # Release and cleanup operations
    # ========================
    def release(self, output_path: str) -> str:
        if self.proc is not None:
            try:
                if self.proc.stdin:
                    self.proc.stdin.close()
                self.proc.wait()
            except Exception as e:
                logging.warning(f"Error while closing FFmpeg stdin: {e}")
            return output_path
            
        if self._fallback_writer:
            self._fallback_writer.release()
            
        if self._fallback_path and Path(self._fallback_path).exists():
            if output_path.lower().endswith(".mp4") and self._reencode_to_h264(self._fallback_path, output_path):
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

    # ========================
    # Internal helper methods
    # ========================

    # ========================
    # FFmpeg operations
    # ========================
    def _open_ffmpeg_writer(self, output_path: str, w: int, h: int, fps: int):
        if not self.ffmpeg_path.exists():
            return None
        cmd = [
            str(self.ffmpeg_path), '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo',
            '-pix_fmt', 'bgr24', '-s', f'{w}x{h}', '-r', str(fps), '-i', '-',
            '-an', '-vcodec', 'libx264', '-pix_fmt', 'yuv420p', str(output_path)
        ]
        try:
            return subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            return None

    # ========================
    # Re-encoding operations
    # ========================
    def _reencode_to_h264(self, src: str, dst: str) -> bool:
        if not self.ffmpeg_path.exists():
            return False
        try:
            r = subprocess.run(
                [str(self.ffmpeg_path), "-y", "-i", src, "-vcodec", "libx264", 
                 "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p", dst],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return r.returncode == 0
        except FileNotFoundError:
            return False