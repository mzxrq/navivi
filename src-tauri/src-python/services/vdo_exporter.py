"""
services/video_exporter.py
---------------------------------------------------------------------------
Handles writing frames to video files using FFmpeg or OpenCV fallback.
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

FFMPEG_BIN = (
    Path(__file__).resolve().parent.parent / "bin" / "FFmpeg" / "bin" / "ffmpeg.exe"
)


class VideoExporter:
    def __init__(self, output_path: str, width: int, height: int, fps: int):
        self.width = width
        self.height = height
        self.fps = fps
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
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )

    def write(self, frame: np.ndarray) -> None:
        if self.proc is not None and self.proc.stdin:
            self.proc.stdin.write(frame.tobytes())
        elif self._fallback_writer:
            self._fallback_writer.write(frame)

    def release(self, output_path: str) -> str:
        if self.proc is not None:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait()
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
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
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
            subprocess.run(
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
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        concat_txt.unlink(missing_ok=True)
        return output_path

    @staticmethod
    def concat_from_timeline(
        timeline_data: dict, output_path: str, save_json_path: Optional[str] = None
    ) -> str:
        """NLE Engine: Stitches atomic clips using strict absolute paths and pre-flight file checks."""
        import json

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
            raise RuntimeError(f"FFmpeg subtitle burn failed: {result.stderr}")

        return str(out_path)
