"""
services/video_exporter.py
---------------------------------------------------------------------------
Handles writing frames to video files using FFmpeg or OpenCV fallback.

[REFACTOR NOTE]
Two silent-failure bugs fixed in this pass:

  1. `release()` previously called `self.proc.wait()` and returned
     `output_path` unconditionally — NEVER checking `returncode`. If
     ffmpeg died (bad codec params, disk full, malformed frame stream),
     the caller received a "successful" path pointing at a missing or
     truncated file. The failure would then only surface several stages
     later (e.g. during `concat_from_timeline`'s pre-flight existence
     check, or worse, a downstream ffmpeg concat silently producing a
     corrupt final video) with no link back to the real root cause.

  2. Both stdout AND stderr were piped to `DEVNULL`, so even if we HAD
     checked the exit code, there was no diagnostic text to report.

Fix: stderr is now captured via `subprocess.PIPE` and drained with
`Popen.communicate()` rather than a bare `.wait()`. This matters: per the
Python docs, calling `.wait()` while a child process has a PIPE'd stream
you haven't read risks a classic pipe-full deadlock (child blocks writing
to stderr once the OS pipe buffer is full; you're blocked in `.wait()`
waiting for it to exit; neither side ever proceeds). `communicate()`
reads and waits atomically, so this can't happen. Non-zero exit codes now
raise immediately with the stderr tail attached.
---------------------------------------------------------------------------
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
import uuid

import cv2
import numpy as np

from services.logger.logger import setup_logger

FFMPEG_BIN = (
    Path(__file__).resolve().parent.parent / "bin" / "FFmpeg" / "bin" / "ffmpeg.exe"
)

# [NEW] This module previously had no logger at all — every ffmpeg
# failure was either swallowed (DEVNULL) or surfaced as a bare exception
# with no context. Matches the `setup_logger` convention used everywhere
# else in this codebase.
logger = setup_logger("VideoExporter")

# Cap on how much stderr tail we keep in memory/log per failure. Ffmpeg
# verbose logs can run to megabytes; we only need the last chunk (where
# the fatal error line lives) for diagnostics, not the entire stream.
_STDERR_TAIL_BYTES = 4000


class VideoExporter:
    def __init__(self, output_path: str, width: int, height: int, fps: int):
        self.width = width
        self.height = height
        self.fps = fps
        self.output_path = output_path
        self.proc = self._open_ffmpeg_writer(output_path)
        self._fallback_path = None
        self._fallback_writer = None

        if self.proc is None:
            self._fallback_path = tempfile.mktemp(suffix=".avi")
            self._fallback_writer = cv2.VideoWriter(
                self._fallback_path,
                cv2.VideoWriter.fourcc(*"XVID"),
                self.fps,
                (self.width, self.height),
            )
            if not self._fallback_writer.isOpened():
                raise RuntimeError(
                    "Neither ffmpeg nor OpenCV VideoWriter is available."
                )

    @staticmethod
    def resolve_ffmpeg() -> Optional[str]:
        if FFMPEG_BIN.exists():
            return str(FFMPEG_BIN)
        return shutil.which("ffmpeg")

    def _open_ffmpeg_writer(self, output_path: str) -> Optional[subprocess.Popen]:
        ffmpeg_cmd = self.resolve_ffmpeg()
        if ffmpeg_cmd is None:
            return None

        cmd = [
            ffmpeg_cmd,
            "-y",
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{self.width}x{self.height}",
            "-r",
            str(self.fps),
            "-i",
            "-",
            "-an",
            "-vcodec",
            "libx264",
            "-crf",
            "18",
            "-preset",
            "fast",
            "-pix_fmt",
            "yuv420p",
            output_path,
        ]
        return subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            # [CHANGED] was DEVNULL — now captured so failures are
            # diagnosable. Drained exclusively via communicate() (never
            # a bare .wait()) to avoid the pipe-full deadlock described
            # in the module docstring.
            stderr=subprocess.PIPE,
            bufsize=0,
        )

    def write(self, frame: np.ndarray) -> None:
        if self.proc is not None and self.proc.stdin:
            try:
                self.proc.stdin.write(frame.tobytes())
            except (BrokenPipeError, OSError) as exc:
                # [NEW] ffmpeg died mid-stream. Previously this exception
                # would propagate bare (or, in FrameSink's variant, get
                # silently swallowed) with zero indication of *why* the
                # encoder process exited. `communicate()` here safely
                # drains any buffered stderr and reaps the process so we
                # can attach the real ffmpeg error message instead of
                # letting every subsequent frame re-raise the same
                # uninformative BrokenPipeError.
                _, stderr_bytes = self.proc.communicate()
                stderr_text = self._decode_tail(stderr_bytes)
                logger.error(
                    "FFmpeg pipe broke mid-render for '%s': %s\n%s",
                    self.output_path,
                    exc,
                    stderr_text,
                )
                self.proc = None  # stop trying to write to a dead process
                raise RuntimeError(
                    f"FFmpeg process died mid-render while writing '{self.output_path}': "
                    f"{exc}\n--- ffmpeg stderr (tail) ---\n{stderr_text}"
                ) from exc
        elif self._fallback_writer:
            self._fallback_writer.write(frame)
        else:
            raise RuntimeError(
                "No active video writer available (ffmpeg died and no OpenCV fallback configured)."
            )

    def release(self, output_path: str) -> str:
        if self.proc is not None:
            if self.proc.stdin:
                try:
                    self.proc.stdin.close()
                except (BrokenPipeError, OSError):
                    pass  # already dead; communicate() below still reaps it safely

            # [FIX] communicate() instead of wait() — deadlock-safe stderr
            # drain, see module docstring.
            _, stderr_bytes = self.proc.communicate()

            # [FIX] Actually check the exit code. This was previously
            # ignored entirely, so a failed encode looked identical to a
            # successful one to every caller downstream.
            if self.proc.returncode != 0:
                stderr_text = self._decode_tail(stderr_bytes)
                logger.error(
                    "FFmpeg exited %d while producing '%s'\n%s",
                    self.proc.returncode,
                    output_path,
                    stderr_text,
                )
                raise RuntimeError(
                    f"FFmpeg failed (exit {self.proc.returncode}) while producing "
                    f"'{output_path}'.\n--- ffmpeg stderr (tail) ---\n{stderr_text}"
                )
            return output_path

        if self._fallback_writer:
            self._fallback_writer.release()

        if (
            output_path.lower().endswith(".mp4")
            and self._fallback_path
            and self._reencode_to_h264(self._fallback_path, output_path)
        ):
            if os.path.exists(self._fallback_path):
                os.remove(self._fallback_path)
            return output_path

        avi_path = str(Path(output_path).with_suffix(".avi"))
        if self._fallback_path:
            os.rename(self._fallback_path, avi_path)
        return avi_path

    @staticmethod
    def _decode_tail(stderr_bytes: Optional[bytes]) -> str:
        """Small helper: safely decode + truncate ffmpeg's stderr for logging."""
        if not stderr_bytes:
            return "(no stderr captured)"
        return stderr_bytes[-_STDERR_TAIL_BYTES:].decode("utf-8", errors="replace")

    @staticmethod
    def _reencode_to_h264(src: str, dst: str) -> bool:
        ffmpeg_cmd = VideoExporter.resolve_ffmpeg()
        if ffmpeg_cmd is None:
            return False
        try:
            r = subprocess.run(
                [
                    ffmpeg_cmd,
                    "-y",
                    "-i",
                    src,
                    "-vcodec",
                    "libx264",
                    "-crf",
                    "18",
                    "-preset",
                    "fast",
                    "-pix_fmt",
                    "yuv420p",
                    dst,
                ],
                capture_output=True,
            )
            if r.returncode != 0:
                logger.error(
                    "H.264 re-encode failed for '%s' -> '%s': %s",
                    src,
                    dst,
                    VideoExporter._decode_tail(r.stderr),
                )
            return r.returncode == 0
        except FileNotFoundError:
            return False

    @staticmethod
    def concat_clips(clip_paths: list[str], output_path: str) -> str:
        """NLE Engine: Stitches multiple atomic .mp4 clips into a seamless master video."""
        if not clip_paths:
            return output_path

        concat_txt = Path(output_path).parent / f"timeline_{uuid.uuid4().hex}.txt"
        with open(concat_txt, "w", encoding="utf-8") as f:
            for path in clip_paths:
                f.write(f"file '{Path(path).resolve().as_posix()}'\n")

        ffmpeg_cmd = VideoExporter.resolve_ffmpeg()
        if ffmpeg_cmd:
            # [FIX] Previously ran with stdout/stderr=DEVNULL and NEVER
            # inspected the CompletedProcess result at all — a failed
            # concat (e.g. one clip has mismatched codec params) silently
            # produced no output file (or a truncated one) while the
            # caller happily continued as if it had succeeded. Now
            # captured and checked, matching `concat_from_timeline`'s
            # (already-correct) error handling below.
            result = subprocess.run(
                [
                    ffmpeg_cmd,
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat_txt),
                    "-c",
                    "copy",
                    output_path,
                ],
                capture_output=True,
            )
            concat_txt.unlink(missing_ok=True)

            if result.returncode != 0:
                stderr_text = VideoExporter._decode_tail(result.stderr)
                logger.error(
                    "concat_clips failed (exit %d) for -> %s\n%s",
                    result.returncode,
                    output_path,
                    stderr_text,
                )
                raise RuntimeError(
                    f"FFmpeg concat_clips failed (exit {result.returncode}) "
                    f"producing '{output_path}'.\n{stderr_text}"
                )
        else:
            concat_txt.unlink(missing_ok=True)
            raise RuntimeError("FFmpeg binary not found; cannot concatenate clips.")

        return output_path

    @staticmethod
    def concat_from_timeline(
        timeline_data: dict, output_path: str, save_json_path: Optional[str] = None
    ) -> str:
        """NLE Engine: Stitches atomic clips using strict absolute paths and pre-flight file checks."""
        # 1. Save the timeline.json file to the disk
        if save_json_path:
            with open(save_json_path, "w", encoding="utf-8") as f:
                json.dump(timeline_data, f, indent=2, ensure_ascii=False)

        tracks = timeline_data.get("video_tracks", [])
        if not tracks:
            raise ValueError("Timeline data has no 'video_tracks' to stitch.")

        # 💡 FIX: Run the strict pre-flight check BEFORE opening any files!
        for track in tracks:
            clip_path = Path(track["file_path"]).resolve()
            if not clip_path.exists():
                raise FileNotFoundError(
                    f"Missing atomic clip! Cannot compile video because this file is missing: {clip_path}"
                )

        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)

        concat_txt = output_dir / f"timeline_{uuid.uuid4().hex}.txt"

        # 2. Write Absolute Paths
        with open(concat_txt, "w", encoding="utf-8") as f:
            for track in tracks:
                clip_path = Path(track["file_path"]).resolve()
                safe_path = clip_path.as_posix()
                f.write(f"file 'file:{safe_path}'\n")

        # 3. Execute the seamless stitch
        ffmpeg_cmd = VideoExporter.resolve_ffmpeg()
        if not ffmpeg_cmd:
            concat_txt.unlink(missing_ok=True)
            raise RuntimeError("FFmpeg binary not found.")

        result = subprocess.run(
            [
                ffmpeg_cmd,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_txt),
                "-c",
                "copy",
                str(output_path),
            ],
            capture_output=True,
            text=True,
        )

        # Clean up the temporary FFmpeg text file
        concat_txt.unlink(missing_ok=True)

        # 4. Strict Post-flight Check
        if result.returncode != 0:
            logger.error("concat_from_timeline failed: %s", result.stderr)
            raise RuntimeError(f"FFmpeg concat failed: {result.stderr}")

        final_file = Path(output_path)
        if not final_file.exists() or final_file.stat().st_size == 0:
            raise RuntimeError(
                f"FFmpeg reported success, but the output file is missing or 0 bytes! STDERR: {result.stderr}"
            )

        return output_path

    @staticmethod
    def burn_subtitles(
        input_video_path: str, subtitle_file_path: str, output_video_path: str
    ) -> str:
        """NLE Engine: Burns an .srt or .ass subtitle file permanently into a video track (Cross-Platform Safe)."""
        video_path = Path(input_video_path)
        sub_path = Path(subtitle_file_path)

        if not video_path.exists():
            raise FileNotFoundError(
                f"Cannot burn subtitles: Video missing {video_path}"
            )
        if not sub_path.exists():
            raise FileNotFoundError(
                f"Cannot burn subtitles: Subtitle file missing {sub_path}"
            )

        # Ensure output directory exists
        out_path = Path(output_video_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        ffmpeg_cmd = VideoExporter.resolve_ffmpeg()
        if not ffmpeg_cmd:
            raise RuntimeError("FFmpeg binary not found.")

        # 💡 CROSS-PLATFORM SECRET:
        # FFmpeg's subtitle filter crashes on Windows absolute paths (e.g., C:\).
        # We must format the path with forward slashes and escape the colon for the filter.
        # e.g., 'C\:/Users/...' -> safely parsed by the FFmpeg filter graph.
        safe_sub_path = sub_path.as_posix().replace(":", "\\:")

        result = subprocess.run(
            [
                ffmpeg_cmd,
                "-y",
                "-i",
                str(video_path),
                "-vf",
                f"subtitles='{safe_sub_path}'",
                "-c:a",
                "copy",  # Copy the audio without re-encoding it
                str(out_path),
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            logger.error("burn_subtitles failed: %s", result.stderr)
            raise RuntimeError(f"FFmpeg subtitle burn failed: {result.stderr}")

        return str(out_path)

    @staticmethod
    def upscale_video(
        input_video_path: str,
        output_video_path: str,
        target_width: int = 1920,
        target_height: int = 1080,
    ) -> str:
        """Scales a clip up to target_width x target_height via ffmpeg's CPU
        lanczos filter (no GPU/VRAM cost — unlike ComfyUI's own upscaler,
        this doesn't compete with attraction-video generation for the 8GB
        VRAM budget). Used to bring ComfyUI attraction clips (rendered at a
        lower resolution to fit VRAM) up to match the 1920x1080 map/waypoint
        clips before they're combined, since nothing else in the pipeline
        reconciles mismatched clip resolutions.
        """
        video_path = Path(input_video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Cannot upscale: video missing {video_path}")

        out_path = Path(output_video_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        ffmpeg_cmd = VideoExporter.resolve_ffmpeg()
        if not ffmpeg_cmd:
            raise RuntimeError("FFmpeg binary not found.")

        result = subprocess.run(
            [
                ffmpeg_cmd,
                "-y",
                "-i",
                str(video_path),
                "-vf",
                f"scale={target_width}:{target_height}:flags=lanczos",
                "-c:a",
                "copy",
                str(out_path),
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            logger.error("upscale_video failed: %s", result.stderr)
            raise RuntimeError(f"FFmpeg upscale failed: {result.stderr}")

        return str(out_path)