"""FFmpeg/FFprobe binary resolution, media probing, and the narration speed filter."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple

from services import runtime_paths
from services.logger.logger import setup_logger

logger = setup_logger("TTSEngine")

ATEMPO_MIN = 0.5
ATEMPO_MAX = 2.0
SPEED_UNCHANGED_TOLERANCE = 0.01


class FFmpegManager:
    """Encapsulates binary resolution and direct media probing via FFmpeg/FFprobe."""

    @staticmethod
    def resolve_ffmpeg_bin() -> str:
        """Locates the bundled FFmpeg binary or falls back to system PATH."""
        found = runtime_paths.ffmpeg_exe()
        if not found:
            raise RuntimeError(
                "ffmpeg not found (bundled path or PATH). Check network/install settings."
            )
        return found

    @staticmethod
    def resolve_ffprobe_bin() -> Optional[str]:
        """Locates ffprobe next to the resolved ffmpeg binary, or on PATH."""
        try:
            ffmpeg_path = Path(FFmpegManager.resolve_ffmpeg_bin())
            candidate = ffmpeg_path.with_name(
                "ffprobe.exe" if os.name == "nt" else "ffprobe"
            )
            if candidate.exists():
                return str(candidate)
        except Exception:
            pass
        return runtime_paths.ffprobe_exe()

    @classmethod
    def get_media_duration(cls, path: str) -> float:
        """Queries container duration precisely via ffprobe."""
        ffprobe_cmd = cls.resolve_ffprobe_bin()
        if not ffprobe_cmd:
            raise RuntimeError("ffprobe not found; cannot determine media duration.")

        result = subprocess.run(
            [
                ffprobe_cmd,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError(f"ffprobe failed on '{path}': {result.stderr.strip()}")
        return float(result.stdout.strip())

    @classmethod
    def get_audio_format(cls, path: str) -> Tuple[int, int]:
        """Probes a real audio file's sample_rate and channel count via ffprobe."""
        ffprobe_cmd = cls.resolve_ffprobe_bin()
        if not ffprobe_cmd:
            raise RuntimeError(
                "ffprobe not found; cannot detect narration audio's sample rate."
            )

        result = subprocess.run(
            [
                ffprobe_cmd,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=sample_rate,channels",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError(
                f"ffprobe failed to read audio format of '{path}': {result.stderr.strip()}"
            )

        lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
        if len(lines) < 2:
            raise RuntimeError(
                f"Unexpected ffprobe output for '{path}': {result.stdout!r}"
            )
        return int(lines[0]), int(lines[1])


def _atempo_filter(speed: float) -> str:
    """ffmpeg's atempo only takes 0.5-2.0 per filter, so a bigger change is a chain of them."""
    stages = []
    while speed > ATEMPO_MAX:
        stages.append(f"atempo={ATEMPO_MAX}")
        speed /= ATEMPO_MAX
    while speed < ATEMPO_MIN:
        stages.append(f"atempo={ATEMPO_MIN}")
        speed /= ATEMPO_MIN
    stages.append(f"atempo={speed:.4f}")
    return ",".join(stages)


def apply_speed(wav: bytes, speed: float) -> bytes:
    """Applies the narration speed to a finished line (Qwen3-TTS has no speed control of its own)."""
    if abs(speed - 1.0) < SPEED_UNCHANGED_TOLERANCE:
        return wav
    # [NOTE] [TTS] ffmpeg can't seek back to fill in a WAV's sizes when it writes to a pipe, so it leaves them as
    # 0xFFFFFFFF and the line reads as ~24 hours long. Write to a file so the header is finished.
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "sped.wav"
        result = subprocess.run(
            [FFmpegManager.resolve_ffmpeg_bin(), "-y", "-loglevel", "error", "-i", "pipe:0", "-filter:a", _atempo_filter(speed), str(out_path)],
            input=wav, capture_output=True,
        )
        if result.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
            logger.warning("Could not change the speed of a narration line, using it as spoken: %s", result.stderr[-200:])
            return wav
        return out_path.read_bytes()
