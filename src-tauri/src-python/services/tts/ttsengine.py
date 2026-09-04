"""
TTS Engine Service (tts_engine.py)
---------------------------------------------------------------------------
Low-level TTS API client, Audio pause analysis, and FFmpeg media processing.
Extracted from tts.py to improve modularity.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import asyncio
import httpx
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit
import wave
import numpy as np
import subprocess
import os
import shutil
import logging
from typing import Final, Optional, Tuple, List, Dict, Any

from services.localization.subtitle import SubtitleStyle
from services.logger.logger import setup_logger

# Logging configuration
logger = setup_logger("TTSEngine")


# [Core/Util] FFmpegManager : Encapsulates binary resolution and direct media probing via FFmpeg/FFprobe.
class FFmpegManager:
    """Encapsulates binary resolution and direct media probing via FFmpeg/FFprobe."""

    # [Validate] Resolves the FFmpeg binary path, checking both bundled and system PATH locations
    @staticmethod
    def resolve_ffmpeg_bin() -> str:
        """Locates the bundled FFmpeg binary or falls back to system PATH."""
        bundled = (
            Path(__file__).resolve().parent.parent
            / "bin"
            / "FFmpeg"
            / "bin"
            / "ffmpeg.exe"
        )
        if bundled.exists():
            return str(bundled)
        found = shutil.which("ffmpeg")
        if not found:
            raise RuntimeError(
                "ffmpeg not found (bundled path or PATH). Check network/install settings."
            )
        return found

    # [Validate] Resolves the FFprobe binary path, checking both bundled and system PATH locations
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
        return shutil.which("ffprobe")

    # [TTS] Queries media duration precisely via ffprobe, raising an error if unavailable
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
            text=True,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError(f"ffprobe failed on '{path}': {result.stderr.strip()}")
        return float(result.stdout.strip())

    # [TTS] Probes a real audio file's sample_rate and channel count via ffprobe, raising an error if unavailable
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
            text=True,
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


# [Core] IrodoriTTSClient : Handles communication with the local Irodori TTS service.
class IrodoriTTSClient:
    """Handles communication with the local Irodori TTS service."""

    # The server this client talks to is a separate, bundled process (see
    # bin/Irodori-TTS-Server/README.md) that has to be started by hand
    # before any TTS call would work — normally `uv run python -m
    # irodori_openai_tts` from that directory. Auto-started as a subprocess
    # instead, the first time a request finds the connection refused/closed
    # (server not running yet), using its own already-synced .venv so
    # nothing here depends on `uv` being on PATH. Kept running afterward
    # (not torn down when this process exits) since it's slow to start —
    # it loads a real model — and every later call in the same session, or
    # a later main.py invocation, should find it already warm.
    _SERVER_DIR: Final[Path] = (
        Path(__file__).resolve().parents[2] / "bin" / "Irodori-TTS-Server"
    )
    _SERVER_VENV_PYTHON: Final[Path] = _SERVER_DIR / ".venv" / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    # The server's own IRODORI_MODEL_LOAD_TIMEOUT defaults to 300s for
    # loading an already-downloaded model — and the FIRST run also has to
    # download the model from Hugging Face before that even starts, which
    # isn't bounded by that setting at all. Generous on purpose: giving up
    # too early on a legitimately slow first-time download/load is a much
    # worse failure mode than this function just taking a while.
    _SERVER_START_TIMEOUT_SECONDS: Final[float] = 600.0
    _SERVER_POLL_INTERVAL_SECONDS: Final[float] = 1.0

    # How long the server can sit unused before the watchdog (see
    # idle_watchdog.py) shuts it down. Auto-starting it is only worth doing
    # if it doesn't also sit there forever afterward, especially since it
    # holds a loaded model — 10 minutes is generous enough to cover the gaps
    # between waypoints in a single pipeline run without shutting down
    # mid-job, short enough not to waste resources long after the last run
    # finished.
    _IDLE_TIMEOUT_SECONDS: Final[float] = 600.0
    _ACTIVITY_FILE: Final[Path] = _SERVER_DIR / ".last_active"

    # Class-level: one server subprocess (and one watchdog) is enough for
    # every client instance/every caller in this process (main.py's
    # tts/tts-all/attraction commands, and the real audio_step.py pipeline,
    # can each construct their own IrodoriTTSClient).
    _server_process: Optional[subprocess.Popen] = None

    # [Config] Initializes the TTS client with output directory and API base URL
    def __init__(
        self,
        output_dir: Path = Path("data/outputs/audio"),
        base_url: str = "http://127.0.0.1:8088/v1/audio/speech",
    ):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.base_url = base_url

    def _health_url(self) -> str:
        parts = urlsplit(self.base_url)
        return f"{parts.scheme}://{parts.netloc}/health"

    async def _is_server_up(self) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(self._health_url(), timeout=3.0)
                return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def _ensure_server_running(self) -> None:
        """Starts the local Irodori TTS server as a subprocess if it isn't
        already reachable, then waits for its /health endpoint to come up.
        Raises RuntimeError if it can't be found/started or never becomes
        healthy in time — callers should let that propagate rather than
        silently continuing to a request that would just fail the same way."""
        if not self._SERVER_VENV_PYTHON.exists():
            raise RuntimeError(
                f"Irodori TTS server isn't reachable at {self.base_url} and its "
                f"bundled venv wasn't found at {self._SERVER_VENV_PYTHON} to "
                "auto-start it. Set it up per bin/Irodori-TTS-Server/README.md "
                "(uv sync), or start it manually."
            )

        if (
            IrodoriTTSClient._server_process is None
            or IrodoriTTSClient._server_process.poll() is not None
        ):
            logger.info(
                "Irodori TTS server not reachable at %s — starting it as a "
                "subprocess (this can take a while on first run while it "
                "downloads/loads the model)...",
                self.base_url,
            )
            port = urlsplit(self.base_url).port or 8088
            popen_kwargs: Dict[str, Any] = {}
            if os.name == "nt":
                # Detached from this console/process group so it outlives a
                # short-lived `python main.py ...` CLI invocation instead of
                # being torn down (or fighting over Ctrl+C) with it.
                popen_kwargs["creationflags"] = (
                    subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
                )
            else:
                popen_kwargs["start_new_session"] = True
            log_path = self._SERVER_DIR / "server.log"
            log_file = open(log_path, "ab")
            IrodoriTTSClient._server_process = subprocess.Popen(
                [
                    str(self._SERVER_VENV_PYTHON), "-m", "irodori_openai_tts",
                    "--host", "127.0.0.1", "--port", str(port),
                ],
                cwd=str(self._SERVER_DIR),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                **popen_kwargs,
            )
            # Baseline activity timestamp so the watchdog's idle clock
            # starts from "just launched", not from whatever this file's
            # mtime happened to be left at by a previous run.
            self._touch_activity()
            self._start_idle_watchdog(IrodoriTTSClient._server_process.pid)

        deadline = time.monotonic() + self._SERVER_START_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if await self._is_server_up():
                logger.info("Irodori TTS server is up at %s.", self.base_url)
                return
            if IrodoriTTSClient._server_process.poll() is not None:
                raise RuntimeError(
                    "Irodori TTS server subprocess exited while starting up — "
                    f"see {self._SERVER_DIR / 'server.log'} for details."
                )
            await asyncio.sleep(self._SERVER_POLL_INTERVAL_SECONDS)

        raise RuntimeError(
            f"Irodori TTS server did not become healthy within "
            f"{self._SERVER_START_TIMEOUT_SECONDS:.0f}s of starting."
        )

    def _touch_activity(self) -> None:
        """Marks the server as just-used — read by idle_watchdog.py (as the
        activity file's mtime) to decide whether it's been idle long enough
        to shut down. Failure here (e.g. read-only filesystem) shouldn't
        break an otherwise-successful TTS call, just the idle-shutdown
        feature, so it's swallowed rather than raised."""
        try:
            self._ACTIVITY_FILE.touch()
        except OSError:
            pass

    def _start_idle_watchdog(self, server_pid: int) -> None:
        """Spawns idle_watchdog.py as its own detached process — not a
        thread or asyncio task in THIS process, because this process (a
        `python main.py ...` CLI invocation) is typically short-lived and
        exits long before 10 minutes of idle TTS server time would ever
        elapse; the watchdog has to keep running independently of whatever
        started the server to actually catch that."""
        popen_kwargs: Dict[str, Any] = {}
        if os.name == "nt":
            popen_kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            )
        else:
            popen_kwargs["start_new_session"] = True
        watchdog_script = Path(__file__).resolve().parent / "idle_watchdog.py"
        subprocess.Popen(
            [
                sys.executable, str(watchdog_script),
                str(server_pid), str(self._ACTIVITY_FILE),
                str(self._IDLE_TIMEOUT_SECONDS),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **popen_kwargs,
        )

    async def _post_speech(self, payload: Dict[str, Any]) -> bytes:
        async with httpx.AsyncClient() as client:
            response = await client.post(self.base_url, json=payload, timeout=300.0)

            if response.status_code != 200:
                logger.info(f"Server returned {response.status_code}: {response.text}")
                raise Exception(
                    f"API request failed with status {response.status_code}"
                )

            self._touch_activity()
            return response.content

    # [TTS] Makes an HTTP POST request to the local Irodori TTS API to generate speech and returns the raw audio bytes
    async def call_api(self, text: str) -> bytes:
        """Makes an HTTP POST request to the local Irodori TTS API to generate speech.
        If the connection is refused/closed (server not running), starts it
        as a subprocess and retries once it's healthy."""
        payload = {"model": "irodori-tts", "input": text, "voice": "string"}

        try:
            return await self._post_speech(payload)
        except httpx.ConnectError:
            await self._ensure_server_running()
            return await self._post_speech(payload)

    # [TTS] Generates speech audio for the given text and saves it to a local WAV file, returning the file path
    async def generate_speech(
        self, text: str, output_filename: Optional[str] = None
    ) -> str:
        """Generates speech audio and saves it to a local WAV file."""
        filename = output_filename or f"{uuid.uuid4()}.wav"
        file_path = self.output_dir / filename

        audio_content = await self.call_api(text)

        with open(file_path, "wb") as f:
            f.write(audio_content)

        return str(file_path)


# [Core] AudioProcessor : Handles wave pause analysis, silence synthesis, and file concatenations.
class AudioProcessor:
    """Handles wave pause analysis, silence synthesis, and file concatenations."""

    # [Config] Initializes the AudioProcessor with an output directory for temporary and final audio files
    def __init__(self, output_dir: Path = Path("data/outputs/audio")):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # [TTS] Analyzes a WAV file for silent pauses based on amplitude threshold and minimum duration, returning pause intervals and total duration
    def analyze_pauses(
        self,
        wav_path: str,
        silence_threshold: int = 500,
        min_pause_duration: float = 0.2,
    ) -> Dict[str, Any]:
        """Reads a .wav file, gets its duration, and detects silent pause intervals."""
        with wave.open(wav_path, "rb") as wf:
            framerate = wf.getframerate()
            n_frames = wf.getnframes()
            duration = n_frames / framerate

            audio_bytes = wf.readframes(n_frames)
            audio_np = np.frombuffer(audio_bytes, dtype=np.int16)

            channels = wf.getnchannels()
            if channels > 1:
                audio_np = audio_np.reshape(-1, channels).mean(axis=1)

        chunk_duration = 0.05
        chunk_size = int(framerate * chunk_duration)

        pauses = []
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
            else:
                if in_pause:
                    in_pause = False
                    pause_end = current_time
                    if (pause_end - pause_start) >= min_pause_duration:
                        pauses.append(
                            {
                                "start": round(pause_start, 3),
                                "end": round(pause_end, 3),
                                "duration": round(pause_end - pause_start, 3),
                            }
                        )

        if in_pause:
            pause_end = len(audio_np) / framerate
            if (pause_end - pause_start) >= min_pause_duration:
                pauses.append(
                    {
                        "start": round(pause_start, 3),
                        "end": round(pause_end, 3),
                        "duration": round(pause_end - pause_start, 3),
                    }
                )

        return {"duration_seconds": round(duration, 3), "pauses": pauses}

    # [TTS] Concatenates multiple WAV audio segments into 1 single master audio file using FFmpeg
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
                    abs_path = os.path.abspath(path).replace("\\", "/")
                    f.write(f"file '{abs_path}'\n")

        ffmpeg_cmd = FFmpegManager.resolve_ffmpeg_bin()
        cmd = [
            str(ffmpeg_cmd),
            "-y",
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

        logger.info(f"Merging audio segments...")
        subprocess.run(cmd, check=True)

        if concat_list_path.exists():
            concat_list_path.unlink()

        logger.info(
            f"Successfully compiled audio into 1 single file: {final_output_path}"
        )
        return final_output_path

    # [TTS] Synthesizes a silent audio track of specified duration using FFmpeg's anullsrc filter
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
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=channel_layout={'stereo' if channels >= 2 else 'mono'}:sample_rate={sample_rate}",
            "-t",
            f"{max(duration_seconds, 0.05):.3f}",
            *codec_args,
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to synthesize silent audio '{output_path}': {result.stderr.strip()}"
            )
        return output_path

    # [TTS] Normalizes a video segment's audio stream, padding with silent AAC if narration is missing
    def build_full_narration_master(
        self,
        segment_durations: List[float],
        segment_narration_audio: List[Optional[str]],
        final_output_path: str = "outputs/master_full_timeline_audio.wav",
    ) -> str:
        """Builds a timeline-accurate master audio track combining narration and procedural silence."""
        if len(segment_durations) != len(segment_narration_audio):
            raise ValueError(
                "segment_durations and segment_narration_audio must be the same length and order."
            )

        ref_sample_rate, ref_channels = self._detect_reference_audio_format(
            segment_narration_audio
        )
        logger.info(
            f"Reference audio format for silence padding: {ref_sample_rate}Hz, {ref_channels}ch"
        )

        # Route temporary audio files into the active project audio directory instead of root outputs
        temp_dir = self.output_dir / "tmp_master_audio"
        temp_dir.mkdir(parents=True, exist_ok=True)
        parts = []

        try:
            for i, (duration, narration_path) in enumerate(
                zip(segment_durations, segment_narration_audio)
            ):
                if narration_path and os.path.exists(narration_path):
                    parts.append(narration_path)
                else:
                    silent_path = str(
                        temp_dir / f"silence_{i:03d}_{uuid.uuid4().hex[:8]}.wav"
                    )
                    self.make_silent_audio(
                        duration,
                        silent_path,
                        sample_rate=ref_sample_rate,
                        channels=ref_channels,
                        as_wav=True,
                    )
                    parts.append(silent_path)

            return self.concatenate_files(parts, final_output_path)
        finally:
            for p in parts:
                if "tmp_master_audio" in p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

    # [TTS] Detects sample rate and channels from the first available narration clip, or returns defaults if none exist
    @staticmethod
    def _detect_reference_audio_format(
        narration_paths: List[Optional[str]],
        default_sample_rate: int = 44100,
        default_channels: int = 2,
    ) -> Tuple[int, int]:
        """Detects sample rate and channels from the first available narration clip."""
        for path in narration_paths:
            if path and os.path.exists(path):
                return FFmpegManager.get_audio_format(path)
        return default_sample_rate, default_channels


# [Core] VideoProcessor : Manages video segment padding, stream-copy concatenation, and final muxing.
class VideoProcessor:
    """Manages video segment padding, stream-copy concatenation, and final muxing."""

    # [TTS] Normalizes a video segment's audio stream, padding with silent AAC if narration is missing
    @staticmethod
    def normalize_segment_audio(
        video_path: str,
        has_narration: bool,
        sample_rate: int,
        channels: int,
        temp_dir: str = "",
    ) -> str:
        """Ensures a video segment has a matching audio stream (pads with silent AAC if missing)."""
        if has_narration:
            return video_path

        os.makedirs(temp_dir, exist_ok=True)
        duration = FFmpegManager.get_media_duration(video_path)

        silent_aac = str(Path(temp_dir) / f"silence_{uuid.uuid4().hex}.aac")
        audio_proc = AudioProcessor()
        audio_proc.make_silent_audio(
            duration,
            silent_aac,
            sample_rate=sample_rate,
            channels=channels,
            as_wav=False,
        )

        muxed_path = str(Path(temp_dir) / f"{Path(video_path).stem}_padded.mp4")
        ffmpeg_cmd = FFmpegManager.resolve_ffmpeg_bin()
        cmd = [
            ffmpeg_cmd,
            "-y",
            "-i",
            video_path,
            "-i",
            silent_aac,
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-shortest",
            muxed_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if os.path.exists(silent_aac):
            os.remove(silent_aac)

        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to pad silent segment '{video_path}': {result.stderr.strip()}"
            )
        return muxed_path

    # [TTS/Animation] Concatenates multiple video segments into a single output file using FFmpeg's concat demuxer
    @staticmethod
    def concatenate_segments(
        video_paths: List[str],
        final_output_path: str = "outputs/final_navigation_video.mp4",
    ) -> str:
        """Joins stream-homogeneous video segments via FFmpeg's concat demuxer (-c copy)."""
        if not video_paths:
            raise ValueError("No video segments provided to concatenate.")

        for path in video_paths:
            if not os.path.exists(path):
                raise FileNotFoundError(f"Segment missing before concat: {path}")

        out_dir = Path(final_output_path).parent
        out_dir.mkdir(parents=True, exist_ok=True)
        concat_list_path = out_dir / f"video_concat_list_{uuid.uuid4().hex}.txt"

        with open(concat_list_path, "w", encoding="utf-8") as f:
            for path in video_paths:
                abs_path = os.path.abspath(path).replace("\\", "/")
                f.write(f"file '{abs_path}'\n")

        ffmpeg_cmd = FFmpegManager.resolve_ffmpeg_bin()
        cmd = [
            ffmpeg_cmd,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list_path),
            "-c",
            "copy",
            final_output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        concat_list_path.unlink(missing_ok=True)

        if result.returncode != 0:
            raise RuntimeError(f"Video concat failed: {result.stderr.strip()}")

        logger.info(f"Final navigation video assembled: {final_output_path}")
        return final_output_path

    # [TTS/Animation] Combines a video file and an audio file into a single output, optionally burning in subtitles with styling
    @staticmethod
    def combine_video_and_audio(
        video_path: str,
        audio_path: str,
        final_output_path: str = "outputs/final_output_with_audio.mp4",
        subtitle_path: Optional[str] = None,
        style: Optional["SubtitleStyle"] = None,
    ) -> str:
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video not found: {video_path}")
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio not found: {audio_path}")

        out_dir = Path(final_output_path).parent
        out_dir.mkdir(parents=True, exist_ok=True)
        ffmpeg_cmd = FFmpegManager.resolve_ffmpeg_bin()
        cmd = [ffmpeg_cmd, "-y", "-i", video_path, "-i", audio_path]

        if subtitle_path and os.path.exists(subtitle_path):
            normalized = os.path.abspath(subtitle_path).replace("\\", "/")
            escaped = normalized.replace(":", r"\:")

            vf_filter = f"subtitles=filename='{escaped}'"
            if style is not None:
                vf_filter += f":force_style='{style.to_force_style()}'"

            cmd.extend(
                [
                    "-vf",
                    vf_filter,
                    "-c:v",
                    "libx264",
                    "-crf",
                    "18",
                    "-preset",
                    "fast",
                    "-pix_fmt",
                    "yuv420p",
                ]
            )
            logger.info(
                "Burning subtitles from: %s (style=%s)",
                subtitle_path,
                "custom" if style else "default",
            )
        else:
            cmd.extend(["-c:v", "copy"])
            reason = (
                "subtitle_path was None/empty"
                if not subtitle_path
                else f"file not found: {subtitle_path}"
            )
            logger.warning(
                "Skipping subtitle burn-in (%s) — output will have NO captions.", reason
            )

        cmd.extend(
            [
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-shortest",
                final_output_path,
            ]
        )

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"Final audio/video/subtitle burn failed: {result.stderr.strip()}"
            )

        if subtitle_path and result.stderr and "error" in result.stderr.lower():
            logger.warning(
                "FFmpeg reported a possible subtitle issue despite exit 0:\n%s",
                result.stderr[-800:],
            )

        logger.info(f"Final combined video with burned subtitles: {final_output_path}")
        return final_output_path