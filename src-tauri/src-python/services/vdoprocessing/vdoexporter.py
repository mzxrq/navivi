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
from typing import List, Optional, Tuple
import uuid

import cv2
import numpy as np

from services import tuning
from services.localization.subtitle import SubtitleStyle
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
        # [FIXME] [Editor] stderr must stay PIPE'd and only ever be drained via
        # communicate() — a bare .wait() here deadlocks once ffmpeg fills the pipe buffer.
        return subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

    def write(self, frame: np.ndarray) -> None:
        if self.proc is not None and self.proc.stdin:
            try:
                self.proc.stdin.write(frame.tobytes())
            except (BrokenPipeError, OSError) as exc:
                # [FIXME] [Editor] ffmpeg died mid-stream; communicate() drains buffered
                # stderr and reaps the process so the real ffmpeg error is attached
                # instead of letting every later frame re-raise a bare BrokenPipeError.
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

            # [FIXME] [Editor] communicate() instead of wait() — deadlock-safe stderr drain.
            _, stderr_bytes = self.proc.communicate()

            # [FIXME] [Editor] Exit code was previously never checked, so a failed
            # encode looked identical to a successful one to every downstream caller.
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
            # [FIXME] [Editor] Previously ran with stdout/stderr=DEVNULL and never
            # checked the returncode — a failed concat silently left a missing or
            # truncated output file while the caller assumed success.
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

        # [NOTE] [Editor] Pre-flight existence check runs before any file is opened so a
        # missing atomic clip fails fast with its path, not as an opaque ffmpeg error.
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
            encoding="utf-8",
            errors="replace",
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

        # [HACK] [Editor] FFmpeg's subtitles filter crashes on Windows absolute paths
        # (C:\...); forward-slashing and escaping the colon keeps its filter-graph parser happy.
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
            encoding="utf-8",
            errors="replace",
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
        # [NOTE] [Editor] CPU lanczos scale keeps this off the GPU so it doesn't
        # contend with ComfyUI's attraction-video generation for the 8GB VRAM budget.
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
            encoding="utf-8",
            errors="replace",
        )

        if result.returncode != 0:
            logger.error("upscale_video failed: %s", result.stderr)
            raise RuntimeError(f"FFmpeg upscale failed: {result.stderr}")

        return str(out_path)

    # [Core/Animation] Burns a persistent corner label (e.g. an attraction's place name) into a video
    @staticmethod
    def burn_static_label(
        input_video_path: str,
        text: str,
        output_video_path: str,
        style: Optional[SubtitleStyle] = None,
    ) -> str:
        """Burns a single always-on text label (e.g. an attraction clip's
        place name) into a video for its entire duration. Reuses the same
        subtitles-filter approach as burn_subtitles/introclip's title card —
        one big single-cue .srt spanning the whole clip instead of many
        timed lines — rather than introducing a second burn-in mechanism."""
        video_path = Path(input_video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Cannot burn label: video missing {video_path}")
        if not text:
            raise ValueError("Cannot burn an empty label.")

        out_path = Path(output_video_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        ffmpeg_cmd = VideoExporter.resolve_ffmpeg()
        if not ffmpeg_cmd:
            raise RuntimeError("FFmpeg binary not found.")

        from services.tts.ttsengine import FFmpegManager

        duration = FFmpegManager.get_media_duration(str(video_path))

        style = style or SubtitleStyle(
            font_size=tuning.ATTRACTION_LABEL_FONT_SIZE,
            bold=True,
            alignment=5,  # old-SSA top-left — see SubtitleStyle.alignment's note
            outline=tuning.ATTRACTION_LABEL_OUTLINE,
            shadow=1.0,
            margin_v=tuning.ATTRACTION_LABEL_MARGIN,
        )

        srt_path = out_path.parent / f".label_{uuid.uuid4().hex[:8]}.srt"
        end_ts = VideoExporter._format_srt_timestamp(duration)
        srt_path.write_text(f"1\n00:00:00,000 --> {end_ts}\n{text}\n", encoding="utf-8")

        # [HACK] [Subtitle] Same absolute/forward-slashed/colon-escaped path
        # normalization burn_subtitles uses — libass's own escaping rules.
        escaped_srt = str(srt_path.resolve()).replace("\\", "/").replace(":", r"\:")

        try:
            result = subprocess.run(
                [
                    ffmpeg_cmd, "-y",
                    "-i", str(video_path),
                    "-vf",
                    f"subtitles=filename='{escaped_srt}':force_style='{style.to_force_style()}'",
                    "-c:a", "copy",
                    str(out_path),
                ],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
            )
        finally:
            srt_path.unlink(missing_ok=True)

        if result.returncode != 0:
            logger.error("burn_static_label failed: %s", result.stderr)
            raise RuntimeError(f"FFmpeg label burn failed: {result.stderr}")

        return str(out_path)

    # [Util] Formats a timestamp in seconds to the SRT timestamp format (HH:MM:SS,mmm)
    @staticmethod
    def _format_srt_timestamp(seconds: float) -> str:
        total_ms = max(0, int(round(seconds * 1000)))
        hours, rem_ms = divmod(total_ms, 3_600_000)
        minutes, rem_ms = divmod(rem_ms, 60_000)
        secs, ms = divmod(rem_ms, 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"

    # [Core/Animation] Fuses duration-fit + upscale + label burn into one ffmpeg pass
    @staticmethod
    def finalize_clip(
        input_video_path: str,
        output_video_path: str,
        *,
        trim_to: Optional[float] = None,
        stretch_to: Optional[float] = None,
        scale_to: Optional[Tuple[int, int]] = None,
        sharpen: bool = False,
        label_text: Optional[str] = None,
        label_style: Optional[SubtitleStyle] = None,
    ) -> str:
        """Combines what used to be up to three sequential ffmpeg re-encodes
        — trim_video_duration/adjust_video_duration, upscale_video, and
        burn_static_label, each a full decode+encode pass over the same
        clip — into a single filter graph and a single encode. Pass only
        the stages actually needed; omitting all of them is just a
        (still single-pass) re-encode/copy.

        trim_to and stretch_to are mutually exclusive: trim_to hard-cuts
        the tail (same as trim_video_duration), stretch_to time-scales via
        setpts (same as adjust_video_duration). scale_to applies a lanczos
        resize; sharpen adds a mild unsharp pass right after it to claw
        back some of the perceived softness a lanczos upscale introduces.
        label_text burns a full-duration top-left caption (see
        burn_static_label) using the SAME output duration as trim_to/
        stretch_to, so the label's .srt cue doesn't have to be probed
        against a not-yet-written file.
        """
        if trim_to is not None and stretch_to is not None:
            raise ValueError(
                "finalize_clip: pass at most one of trim_to/stretch_to, not both."
            )

        video_path = Path(input_video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Cannot finalize clip: video missing {video_path}")

        out_path = Path(output_video_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        ffmpeg_cmd = VideoExporter.resolve_ffmpeg()
        if not ffmpeg_cmd:
            raise RuntimeError("FFmpeg binary not found.")

        from services.tts.ttsengine import FFmpegManager

        vf_parts: List[str] = []

        if stretch_to is not None:
            current_duration = FFmpegManager.get_media_duration(str(video_path))
            if current_duration <= 0:
                raise RuntimeError(
                    f"ffprobe reported non-positive duration for '{video_path}'"
                )
            pts_factor = stretch_to / current_duration
            vf_parts.append(f"setpts={pts_factor:.6f}*PTS")

        if scale_to is not None:
            target_width, target_height = scale_to
            vf_parts.append(f"scale={target_width}:{target_height}:flags=lanczos")
            if sharpen:
                # Mild luma-only unsharp mask — just enough to counter a
                # lanczos upscale's softening, not a stylistic sharpen.
                vf_parts.append("unsharp=5:5:0.5:5:5:0.0")

        srt_path: Optional[Path] = None
        if label_text:
            output_duration = trim_to or stretch_to
            if output_duration is None:
                output_duration = FFmpegManager.get_media_duration(str(video_path))

            style = label_style or SubtitleStyle(
                font_size=tuning.ATTRACTION_LABEL_FONT_SIZE,
                bold=True,
                alignment=5,  # old-SSA top-left — see SubtitleStyle.alignment's note
                outline=tuning.ATTRACTION_LABEL_OUTLINE,
                shadow=1.0,
                margin_v=tuning.ATTRACTION_LABEL_MARGIN,
            )
            srt_path = out_path.parent / f".label_{uuid.uuid4().hex[:8]}.srt"
            end_ts = VideoExporter._format_srt_timestamp(output_duration)
            srt_path.write_text(
                f"1\n00:00:00,000 --> {end_ts}\n{label_text}\n", encoding="utf-8"
            )
            escaped_srt = str(srt_path.resolve()).replace("\\", "/").replace(":", r"\:")
            vf_parts.append(
                f"subtitles=filename='{escaped_srt}':force_style='{style.to_force_style()}'"
            )

        cmd = [ffmpeg_cmd, "-y", "-i", str(video_path)]
        if vf_parts:
            cmd += ["-vf", ",".join(vf_parts)]
        if trim_to is not None:
            cmd += ["-t", f"{trim_to:.3f}"]
        cmd += [
            "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            str(out_path),
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, encoding="utf-8", errors="replace"
            )
        finally:
            if srt_path is not None:
                srt_path.unlink(missing_ok=True)

        if result.returncode != 0:
            logger.error("finalize_clip failed: %s", result.stderr)
            raise RuntimeError(f"FFmpeg finalize_clip failed: {result.stderr}")

        return str(out_path)