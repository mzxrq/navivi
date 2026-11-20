"""Wave pause analysis, silence synthesis, and audio file concatenation."""

from __future__ import annotations

import os
import subprocess
import wave
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

from services import tuning
from services.ffconcat import concat_entry
from services.logger.logger import setup_logger
from services.tts.ffmpeg_tools import FFmpegManager

logger = setup_logger("TTSEngine")

PAUSE_SCAN_WINDOW_SECONDS = 0.05
DEFAULT_OUTPUT_DIR = Path("data/outputs/audio")


def _read_mono_samples(wav_path: str) -> Tuple[np.ndarray, int, float]:
    """Reads a 16-bit .wav as one channel (channels averaged): (samples, frame rate, duration in seconds)."""
    with wave.open(wav_path, "rb") as wf:
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        duration = n_frames / framerate

        audio_bytes = wf.readframes(n_frames)
        audio_np = np.frombuffer(audio_bytes, dtype=np.int16)

        channels = wf.getnchannels()
        if channels > 1:
            audio_np = audio_np.reshape(-1, channels).mean(axis=1)
    return audio_np, framerate, duration


def _pause_entry(start: float, end: float) -> Dict[str, float]:
    return {
        "start": round(start, 3),
        "end": round(end, 3),
        "duration": round(end - start, 3),
    }


def _scan_pauses(
    audio_np: np.ndarray, framerate: int, silence_threshold: int, min_pause_duration: float
) -> List[Dict[str, float]]:
    """Pause intervals of `audio_np`: runs of quiet windows at least `min_pause_duration` long.

    [NOTE] [TTS] Sliding-window peak-amplitude scan: a chunk below silence_threshold
    opens a pause, the first chunk back above it closes one — only pauses
    meeting min_pause_duration are kept, so brief dips in loudness don't register.
    """
    chunk_size = int(framerate * PAUSE_SCAN_WINDOW_SECONDS)
    pauses: List[Dict[str, float]] = []
    in_pause = False
    pause_start = 0.0

    for i in range(0, len(audio_np), chunk_size):
        chunk = audio_np[i : i + chunk_size]
        if len(chunk) == 0:
            continue

        peak_amplitude = np.max(np.abs(chunk))
        current_time = i / framerate

        if peak_amplitude < silence_threshold:
            if not in_pause:
                in_pause = True
                pause_start = current_time
        elif in_pause:
            in_pause = False
            if (current_time - pause_start) >= min_pause_duration:
                pauses.append(_pause_entry(pause_start, current_time))

    if in_pause:
        pause_end = len(audio_np) / framerate
        if (pause_end - pause_start) >= min_pause_duration:
            pauses.append(_pause_entry(pause_start, pause_end))
    return pauses


class AudioProcessor:
    """Handles wave pause analysis, silence synthesis, and file concatenations."""

    def __init__(self, output_dir: Path = DEFAULT_OUTPUT_DIR):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def analyze_pauses(
        self,
        wav_path: str,
        silence_threshold: int = 500,
        min_pause_duration: float = 0.2,
    ) -> Dict[str, Any]:
        """Reads a .wav file, gets its duration, and detects silent pause intervals."""
        audio_np, framerate, duration = _read_mono_samples(wav_path)
        pauses = _scan_pauses(audio_np, framerate, silence_threshold, min_pause_duration)
        return {"duration_seconds": round(duration, 3), "pauses": pauses}

    def concatenate_files(
        self,
        audio_paths: List[str],
        final_output_path: str = "outputs/master_narration.wav",
    ) -> str:
        """Concatenates multiple WAV audio segments into 1 single master audio file using FFmpeg."""
        out_path_obj = Path(final_output_path)
        out_path_obj.parent.mkdir(parents=True, exist_ok=True)

        concat_list_path = self.output_dir.resolve() / "audio_concat_list.txt"

        with open(concat_list_path, "w", encoding="utf-8") as f:
            for path in audio_paths:
                if path and os.path.exists(path):
                    f.write(concat_entry(path))

        ffmpeg_cmd = FFmpegManager.resolve_ffmpeg_bin()
        cmd = [
            str(ffmpeg_cmd),
            "-y", *tuning.ffmpeg_log_args(),
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list_path),
            "-c",
            "copy",
            str(out_path_obj.resolve()),
        ]

        logger.info("Merging audio segments...")
        result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
        concat_list_path.unlink(missing_ok=True)
        if result.returncode != 0:
            raise RuntimeError(f"Audio merge failed: {result.stderr.strip()[-600:]}")

        logger.info(
            f"Successfully compiled audio into 1 single file: {final_output_path}"
        )
        return final_output_path

    def make_silent_audio(
        self,
        duration_seconds: float,
        output_path: str,
        sample_rate: int = 44100,
        channels: int = 2,
        as_wav: bool = False,
    ) -> str:
        """Synthesizes a silent audio track via ffmpeg's `anullsrc` filter."""
        ffmpeg_cmd = FFmpegManager.resolve_ffmpeg_bin()
        codec_args = (
            ["-c:a", "pcm_s16le"] if as_wav else ["-c:a", "aac", "-b:a", "128k"]
        )

        cmd = [
            ffmpeg_cmd,
            "-y", *tuning.ffmpeg_log_args(),
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=channel_layout={'stereo' if channels >= 2 else 'mono'}:sample_rate={sample_rate}",
            "-t",
            f"{max(duration_seconds, 0.05):.3f}",
            *codec_args,
            output_path,
        ]
        result = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", errors="replace"
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to synthesize silent audio '{output_path}': {result.stderr.strip()}"
            )
        return output_path
