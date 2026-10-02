"""
TTS Engine Service (tts_engine.py)
---------------------------------------------------------------------------
Low-level TTS API client, Audio pause analysis, and FFmpeg media processing.
Extracted from tts.py to improve modularity.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import asyncio
import random
import re
import httpx
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
import wave
import numpy as np
import subprocess
import os
import shutil

import logging
from typing import Any, ClassVar, Dict, Final, List, Optional, Tuple

from services import tuning
from services.tts import phrase_cache
from services.tts.artifacts import remove_stray_bursts
from services.localization.subtitle import SubtitleStyle
from services.logger.logger import setup_logger

# Logging configuration
logger = setup_logger("TTSEngine")


# [Config] TTSConfig: every knob the Irodori TTS request payload accepts, with tuning.py defaults
@dataclass(frozen=True)
class TTSConfig:
    """Narration-synthesis parameters sent to the Irodori TTS server.

    Covers the request's named fields (model/voice/speed/response_format)
    directly; anything beyond that — the server's ~30 advanced sampling
    knobs (cfg_scale, seed, chunking, ...) — goes through `extra_options`
    and is forwarded verbatim as the request's `irodori` sub-object, so this
    class doesn't have to mirror each one by hand to stay "fully configurable".
    Built once per client/call (frozen, validated up front) rather than
    re-validated on every request.
    """

    model: str = tuning.TTS_MODEL
    voice: str = tuning.TTS_VOICE
    speed: float = tuning.TTS_SPEED
    response_format: Optional[str] = tuning.TTS_RESPONSE_FORMAT
    caption: Optional[str] = tuning.TTS_CAPTION
    hardware_override: Optional[str] = None
    extra_options: Dict[str, Any] = field(default_factory=dict)
    quality: str = tuning.TTS_QUALITY_DEFAULT
    engine: str = tuning.TTS_ENGINE_DEFAULT

    def __post_init__(self) -> None:
        if not (tuning.TTS_MIN_SPEED <= self.speed <= tuning.TTS_MAX_SPEED):
            raise ValueError(
                f"TTS speed must be between {tuning.TTS_MIN_SPEED} and "
                f"{tuning.TTS_MAX_SPEED}, got {self.speed}"
            )

    # [Util] Serializes this config + the narration text into the request body IrodoriTTSClient posts
    def to_payload(self, text: str) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.model,
            "input": text,
            "voice": self.voice,
            "speed": self.speed,
        }
        if self.response_format:
            payload["response_format"] = self.response_format
        if self.caption:
            payload["caption"] = self.caption
        options = {**tuning.TTS_QUALITY_PRESETS.get(self.quality, {}), **self.extra_options}
        if options:
            payload["irodori"] = options
        return payload


# [Config] Builds a TTSConfig from job_config.json's settings (settings.tts.engine/voice/kokoro_voice/speed/quality, hardware_spec_override)
def tts_config_from_settings(settings: Optional[Dict[str, Any]]) -> TTSConfig:
    from services.tts import voices

    settings = settings or {}
    tts = settings.get("tts") or {}
    engine = str(tts.get("engine") or tuning.TTS_ENGINE_DEFAULT)
    if engine not in tuning.TTS_ENGINES:
        logger.warning("TTS engine '%s' is not one of %s; using '%s'.", engine, list(tuning.TTS_ENGINES), tuning.TTS_ENGINE_DEFAULT)
        engine = tuning.TTS_ENGINE_DEFAULT
    try:
        speed = float(tts.get("speed", tuning.TTS_SPEED))
    except (TypeError, ValueError):
        speed = tuning.TTS_SPEED
    if not (tuning.TTS_MIN_SPEED <= speed <= tuning.TTS_MAX_SPEED):
        logger.warning("TTS speed %s out of range; using %s.", speed, tuning.TTS_SPEED)
        speed = tuning.TTS_SPEED

    if engine == "kokoro":
        voice = str(tts.get("kokoro_voice") or tuning.KOKORO_VOICE)
        if voice not in tuning.KOKORO_VOICES:
            logger.warning("Kokoro voice '%s' is not one of %s; using '%s'.", voice, list(tuning.KOKORO_VOICES), tuning.KOKORO_VOICE)
            voice = tuning.KOKORO_VOICE
        return TTSConfig(model="kokoro", voice=voice, speed=speed, caption=None, engine="kokoro")

    voice = str(tts.get("voice") or tuning.TTS_VOICE).strip()
    if not voices.voice_exists(voice):
        logger.warning("TTS voice '%s' not found in %s; using '%s'.", voice, voices.voices_dir(), tuning.TTS_VOICE)
        voice = tuning.TTS_VOICE
    caption = tts.get("caption", tuning.TTS_CAPTION)
    caption = str(caption).strip() if caption else None
    quality = str(tts.get("quality") or tuning.TTS_QUALITY_DEFAULT)
    if quality not in tuning.TTS_QUALITY_PRESETS:
        logger.warning("TTS quality '%s' is not one of %s; using '%s'.", quality, list(tuning.TTS_QUALITY_PRESETS), tuning.TTS_QUALITY_DEFAULT)
        quality = tuning.TTS_QUALITY_DEFAULT
    hardware = settings.get("hardware_spec_override")
    return TTSConfig(
        voice=voice,
        speed=speed,
        caption=caption,
        quality=quality,
        hardware_override=hardware if hardware in ("low", "high") else None,
    )


def _kill_process_tree(pid: int) -> None:
    """Same approach as idle_watchdog.py's _kill — /T also takes down the
    child process(es) a server subprocess may have spawned, not just the
    immediate PID."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        import signal
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


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
            encoding="utf-8",
            errors="replace",
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


# [Core] IrodoriTTSClient : Handles communication with the local Irodori TTS service.
_latent_failures: set = set()


# [TTS] Encodes `voice`'s reference file into a latent next to the voices (once per file content) using the server's own Python.
def ensure_reference_latent(voice: str) -> Optional[Path]:
    from services.tts import voices

    path = voices.voice_file(voice)
    python = IrodoriTTSClient._SERVER_VENV_PYTHON
    if path is None or not python.exists() or voice in _latent_failures:
        return None
    out = voices.voices_dir() / ".latents" / f"{voice}-{voices._sha256(path)[:12]}.pt"
    if out.exists():
        return out
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Encoding the reference voice '%s' once (saves ~5 s on every narration line)...", voice)
        result = subprocess.run(
            [str(python), str(Path(__file__).with_name("make_latent.py")), str(path), str(out)],
            capture_output=True, encoding="utf-8", errors="replace", timeout=600,
        )
        if result.returncode == 0 and out.exists():
            return out
        logger.warning("Could not encode the reference voice, using the plain file: %s", result.stderr[-300:])
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Could not encode the reference voice, using the plain file: %s", exc)
    _latent_failures.add(voice)
    return None


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

    # Written with the spawning process's PID right after Popen, so a
    # second, separate `main.py` invocation racing to start the server at
    # nearly the same moment (before either can see the other's server as
    # healthy) can detect "someone else is already starting it" and just
    # wait, instead of spawning its own second copy.
    _PIDFILE: Final[Path] = _SERVER_DIR / ".server.pid"

    # Class-level: one server subprocess (and one watchdog) is enough for
    # every client instance/every caller in this process (main.py's
    # tts/tts-all/attraction commands, and the real audio_step.py pipeline,
    # can each construct their own IrodoriTTSClient).
    _server_process: Optional[subprocess.Popen] = None

    # [TTS] Starts the server process (Irodori: its own venv and model; a subclass launches its own).
    def _spawn_server(self, port: int, popen_kwargs: Dict[str, Any]) -> subprocess.Popen:
        log_path = self._SERVER_DIR / "server.log"
        log_file = open(log_path, "ab")
        # Base device from env or tuning.py
        device = os.environ.get("NAVIVI_TTS_DEVICE") or tuning.TTS_DEVICE

        # [Hardware Detection] Check frontend flag first, fallback to nvidia-smi
        if self.config.hardware_override == "low":
            has_nvidia = False
            logger.info("Hardware override set to 'low'. Forcing TTS to CPU mode.")
        elif self.config.hardware_override == "high":
            has_nvidia = True
            logger.info("Hardware override set to 'high'. Trusting GPU presence.")
        else:
            has_nvidia = shutil.which("nvidia-smi") is not None

        # Force CPU fallback for older PCs    
        if not has_nvidia and device != "cpu":
            logger.warning("No NVIDIA GPU detected/reported. Forcing TTS device to 'cpu' and precision to 'fp32'.")
            device = "cpu"

        # bf16 requires a CUDA GPU, standard CPUs need fp32
        precision = "bf16" if device == "cuda" else "fp32"

        from services.tts.voices import voices_dir

        server_env = {
            **os.environ,
            "IRODORI_MODEL_DEVICE": device,
            "IRODORI_CODEC_DEVICE": device,
            "IRODORI_HF_CHECKPOINT": "Aratako/Irodori-TTS-v4.1-Small",
            "IRODORI_MODEL_PRECISION": precision,
            "IRODORI_VOICES_DIR": str(voices_dir()),
        }
        logger.info("Irodori TTS server device: %s (Precision: %s).", device, precision)
        return subprocess.Popen(
            [
                str(self._SERVER_VENV_PYTHON), "-m", "irodori_openai_tts",
                "--host", "127.0.0.1", "--port", str(port),
            ],
            cwd=str(self._SERVER_DIR),
            env=server_env,
            stdout=log_file,    
            stderr=subprocess.STDOUT,
            **popen_kwargs,
        )

    # [Config] Initializes the TTS client with output directory, API base URL, and synthesis config
    def __init__(
        self,
        output_dir: Path = Path("data/outputs/audio"),
        base_url: str = "http://127.0.0.1:8088/v1/audio/speech",
        config: Optional[TTSConfig] = None,
    ):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.base_url = base_url
        # Built once per client (not per call) — TTSConfig is frozen and
        # validated in __post_init__, so every later generate_speech() call
        # just reuses it instead of re-validating speed on every request.
        self.config = config or TTSConfig()

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

    @staticmethod
    def _pid_is_alive(pid: int) -> bool:
        if os.name == "nt":
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    capture_output=True, text=True, timeout=5,
                )
                return str(pid) in result.stdout
            except Exception:
                return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    @classmethod
    def _other_process_is_starting_server(cls) -> bool:
        """Reads the pidfile a spawning process writes right after Popen —
        True if some other still-alive process claims to already be
        starting the server, so this one should just wait instead of
        racing to spawn a second copy."""
        try:
            pid = int(cls._PIDFILE.read_text().strip())
        except (OSError, ValueError):
            return False
        return cls._pid_is_alive(pid)

    async def _ensure_server_running(self) -> None:
        """Starts the local Irodori TTS server as a subprocess if it isn't
        already reachable, then waits for its /health endpoint to come up.
        Raises RuntimeError if it can't be found/started or never becomes
        healthy in time — callers should let that propagate rather than
        silently continuing to a request that would just fail the same way."""
        # Check health FIRST — a fresh IrodoriTTSClient in a brand new
        # `main.py` process always starts with _server_process == None, so
        # without this check every single invocation would fall straight
        # into the spawn branch below even when a server from an earlier
        # invocation is already up and healthy.
        if await self._is_server_up():
            logger.info("Irodori TTS server already up at %s.", self.base_url)
            return

        if not self._SERVER_VENV_PYTHON.exists():
            raise RuntimeError(self._missing_server_message())

        if (
            type(self)._server_process is None
            or type(self)._server_process.poll() is not None
        ):
            if self._other_process_is_starting_server():
                logger.info(
                    "Another process is already starting the Irodori TTS "
                    "server — waiting for it instead of starting a second copy."
                )
            else:
                logger.info(
                    "Irodori TTS server not reachable at %s — starting it as a "
                    "subprocess (this can take a while on first run while it "
                    "downloads/loads the model)...",
                    self.base_url,
                )
                port = urlsplit(self.base_url).port or 8088
                popen_kwargs: Dict[str, Any] = {}
                if os.name == "nt":
                    # CREATE_NEW_PROCESS_GROUP: outlives a short-lived
                    # `python main.py ...` CLI invocation instead of being
                    # torn down (or fighting over Ctrl+C) with it.
                    # CREATE_NO_WINDOW (not DETACHED_PROCESS): a fully
                    # detached process has NO console at all, which some
                    # Fortran/MKL-linked scientific-Python dependencies
                    # crash under on Windows ("forrtl: error (200): program
                    # aborting due to window-CLOSE event") — CREATE_NO_WINDOW
                    # still shows no visible window but keeps a (hidden)
                    # console allocated.
                    popen_kwargs["creationflags"] = (
                        subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
                    )
                else:
                    popen_kwargs["start_new_session"] = True
                type(self)._server_process = self._spawn_server(port, popen_kwargs)
                self._PIDFILE.write_text(str(type(self)._server_process.pid))
                # Baseline activity timestamp so the watchdog's idle clock
                # starts from "just launched", not from whatever this file's
                # mtime happened to be left at by a previous run.
                self._touch_activity()
                self._start_idle_watchdog(type(self)._server_process.pid)

        deadline = time.monotonic() + self._SERVER_START_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if await self._is_server_up():
                logger.info("Irodori TTS server is up at %s.", self.base_url)
                return
            if (
                type(self)._server_process is not None
                and type(self)._server_process.poll() is not None
            ):
                raise RuntimeError(
                    "Irodori TTS server subprocess exited while starting up — "
                    f"see {self._SERVER_DIR / 'server.log'} for details."
                )
            await asyncio.sleep(self._SERVER_POLL_INTERVAL_SECONDS)

        raise RuntimeError(
            f"Irodori TTS server did not become healthy within "
            f"{self._SERVER_START_TIMEOUT_SECONDS:.0f}s of starting."
        )

    @classmethod
    def stop_server(cls) -> None:
        """Explicitly terminates the TTS server now, rather than waiting on
        its idle timeout. For a single process/job that runs TTS generation
        fully up front and then a separate GPU-heavy step afterward (see
        main.py's test_all) — the 10-minute idle timeout was sized for gaps
        BETWEEN waypoints within one job, not for handing the GPU off to a
        different consumer right after TTS finishes, so left alone the
        server stays fully loaded and fights that next step for VRAM for
        most/all of the idle window. Only effective if THIS process is the
        one that started the server (holds the live subprocess handle) — a
        server left running from an earlier process can't be reached here;
        it'll fall back to its own idle-timeout watchdog as before."""
        if cls._server_process is not None and cls._server_process.poll() is None:
            logger.info("Stopping Irodori TTS server (%s) to free its resources for the next step.", cls._server_process.pid)
            _kill_process_tree(cls._server_process.pid)
            cls._server_process = None
            cls._PIDFILE.unlink(missing_ok=True)
            return
        # Started by another process (e.g. a voice preview): stop it via the pidfile.
        try:
            pid = int(cls._PIDFILE.read_text().strip())
        except (OSError, ValueError):
            return
        if cls._pid_is_server(pid):
            logger.info("Stopping Irodori TTS server (%s) started by another process.", pid)
            _kill_process_tree(pid)
        cls._PIDFILE.unlink(missing_ok=True)

    # What the server's command line contains, to tell it from an unrelated process that reused a stale pidfile's PID.
    _PROCESS_MARKER: ClassVar[str] = "irodori_openai_tts"
    _SERVER_NAME: ClassVar[str] = "Irodori TTS"

    def _missing_server_message(self) -> str:
        return (
            f"Irodori TTS server isn't reachable at {self.base_url} and its "
            f"bundled venv wasn't found at {self._SERVER_VENV_PYTHON} to "
            "auto-start it. Set it up per bin/Irodori-TTS-Server/README.md "
            "(uv sync), or start it manually."
        )

    @classmethod
    def _pid_is_server(cls, pid: int) -> bool:
        """Guards against a stale pidfile whose PID now belongs to something else."""
        try:
            if os.name == "nt":
                out = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine"],
                    capture_output=True, text=True, timeout=15,
                ).stdout
            else:
                out = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace")
        except Exception:
            return False
        return cls._PROCESS_MARKER in out

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
            # See _ensure_server_running's comment on CREATE_NO_WINDOW vs
            # DETACHED_PROCESS above.
            popen_kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
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
            response = await client.post(self.base_url, json=payload, timeout=None)

            if response.status_code != 200:
                error_msg = f"API request failed with status {response.status_code}: {response.text}"
                logger.error(error_msg)
                raise Exception(error_msg)

            self._touch_activity()
            return response.content

    # [TTS] Makes an HTTP POST request to the local Irodori TTS API to generate speech and returns the raw audio bytes
    async def call_api(self, text: str) -> bytes:
        """Makes an HTTP POST request to the local Irodori TTS API to generate speech.
        If the connection is refused/closed (server not running) OR the
        connection attempt just times out (server starting up too slowly to
        accept it yet — httpx.ConnectTimeout is a SEPARATE exception class
        from ConnectError, not a subclass, so both need to be caught here),
        starts/waits for it as a subprocess and retries once it's healthy."""
        payload = self.config.to_payload(text)

        # A line spoken before (in this or any project) is not synthesized again; ~40 s each on a CPU.
        key = phrase_cache.cache_key(payload, self._voice_sha256())
        cached = phrase_cache.get(key)
        if cached is not None:
            logger.info("TTS line served from the cache (%d characters).", len(text))
            return cached

        wire = await self._with_reference_latent(payload)
        try:
            audio = await self._post_speech(wire)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            await self._ensure_server_running()
            audio = await self._post_speech(wire)
        phrase_cache.put(key, audio)
        return audio

    def _voice_sha256(self) -> Optional[str]:
        from services.tts import voices

        path = voices.voice_file(self.config.voice)
        return voices._sha256(path) if path else None

    # [TTS] The voice's reference audio, encoded once and reused: the server otherwise re-encodes the wav on every request (~5 s on a CPU).
    # Anything that goes wrong falls back to the plain voice, which the server resolves itself.
    async def _with_reference_latent(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        latent = await asyncio.to_thread(ensure_reference_latent, self.config.voice)
        if latent is None:
            return payload
        return {**payload, "irodori": {**payload.get("irodori", {}), "ref_latent": str(latent)}}

    # [TTS] Generates speech audio for the given text and saves it to a local WAV file, returning the file path
    async def generate_speech(
        self, text: str, output_filename: Optional[str] = None
    ) -> str:
        """Generates speech audio and saves it to a local WAV file."""
        filename = output_filename or f"{uuid.uuid4()}.wav"
        file_path = self.output_dir / filename

        # A long text in one request overloads the GPU (see tuning.TTS_DEVICE):
        # speak it in short chunks, one request at a time, and join them.
        # Packed (split_text_for_tts groups whole sentences up to
        # TTS_MAX_CHUNK_CHARS per request) rather than one request per
        # sentence (split_sentences_for_tts) - CPU inference (tuning's
        # current TTS_DEVICE default) makes many small sequential requests
        # far slower than a few packed ones. The gap inserted below still
        # lands at every CHUNK boundary (so a multi-sentence chunk plays
        # with no pause between ITS OWN sentences, only after the chunk as
        # a whole) - less granular than a pause after every single
        # sentence, but still nowhere near as rushed/robotic as one
        # continuous zero-gap synthesis of the whole text.
        chunks = split_text_for_tts(text, tuning.TTS_MAX_CHUNK_CHARS, tuning.TTS_MIN_CHUNK_CHARS)
        if len(chunks) <= 1:
            audio_content = await self.call_api(text)
            with open(file_path, "wb") as f:
                f.write(audio_content)
            remove_stray_bursts(str(file_path))
            return str(file_path)

        logger.info("TTS text of %d characters split into %d chunk(s).", len(text), len(chunks))
        processor = AudioProcessor(output_dir=self.output_dir)
        parts: List[str] = []
        gaps: List[str] = []
        try:
            sample_rate: Optional[int] = None
            channels: Optional[int] = None
            for i, chunk in enumerate(chunks):
                part = file_path.with_name(f"{file_path.stem}.part{i:02d}.wav")
                with open(part, "wb") as f:
                    f.write(await self.call_api(chunk))
                parts.append(str(part))
                if sample_rate is None:  # once is enough, every part shares the server's format
                    sample_rate, channels = FFmpegManager.get_audio_format(str(part))

            # Interleave a short, randomized pause after every sentence but
            # the last (nothing to breathe before at the very end).
            interleaved: List[str] = []
            for i, part in enumerate(parts):
                interleaved.append(part)
                if i < len(parts) - 1:
                    gap_seconds = random.uniform(
                        tuning.TTS_SENTENCE_GAP_MIN_SECONDS, tuning.TTS_SENTENCE_GAP_MAX_SECONDS
                    )
                    gap_path = str(file_path.with_name(f"{file_path.stem}.gap{i:02d}.wav"))
                    processor.make_silent_audio(
                        gap_seconds, gap_path,
                        sample_rate=sample_rate or 44100, channels=channels or 1,
                        as_wav=True,
                    )
                    gaps.append(gap_path)
                    interleaved.append(gap_path)

            processor.concatenate_files(interleaved, str(file_path))
            remove_stray_bursts(str(file_path))
        finally:
            for p in parts + gaps:
                Path(p).unlink(missing_ok=True)
        return str(file_path)



# [TTS] The fast engine: Kokoro, a small model with a few fixed Japanese voices (no cloning), run by services/tts/kokoro_server.py in
# its own venv (bin/Kokoro-TTS, set up by services/tts/kokoro_setup.py). Everything else (chunking, gaps, cache, server reuse across
# processes) is the Irodori client's.
class KokoroTTSClient(IrodoriTTSClient):
    _SERVER_DIR: Final[Path] = Path(__file__).resolve().parents[2] / "bin" / "Kokoro-TTS"
    _SERVER_VENV_PYTHON: Final[Path] = _SERVER_DIR / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    _SERVER_START_TIMEOUT_SECONDS: Final[float] = 300.0
    _IDLE_TIMEOUT_SECONDS: Final[float] = 600.0
    _ACTIVITY_FILE: Final[Path] = _SERVER_DIR / ".last_active"
    _PIDFILE: Final[Path] = _SERVER_DIR / ".server.pid"
    _READY_FILE: Final[Path] = _SERVER_DIR / ".ready"
    _PROCESS_MARKER: ClassVar[str] = "kokoro_server"
    _SERVER_NAME: ClassVar[str] = "Kokoro TTS"
    _server_process: Optional[subprocess.Popen] = None

    def __init__(
        self,
        output_dir: Path = Path("data/outputs/audio"),
        base_url: str = f"http://127.0.0.1:{tuning.KOKORO_PORT}/v1/audio/speech",
        config: Optional[TTSConfig] = None,
    ):
        super().__init__(output_dir=output_dir, base_url=base_url, config=config or TTSConfig(engine="kokoro", voice=tuning.KOKORO_VOICE, model="kokoro", caption=None))

    @classmethod
    def is_ready(cls) -> bool:
        return cls._SERVER_VENV_PYTHON.exists() and cls._READY_FILE.exists()

    def _missing_server_message(self) -> str:
        return "The fast voice (Kokoro) is not set up yet. Open Settings > Voice and press Set up fast voice."

    def _spawn_server(self, port: int, popen_kwargs: Dict[str, Any]) -> subprocess.Popen:
        log_file = open(self._SERVER_DIR / "server.log", "ab")
        return subprocess.Popen(
            [
                str(self._SERVER_VENV_PYTHON), str(Path(__file__).with_name("kokoro_server.py")),
                "--host", "127.0.0.1", "--port", str(port), "--idle-seconds", str(int(self._IDLE_TIMEOUT_SECONDS)),
            ],
            cwd=str(self._SERVER_DIR),
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "HF_HUB_DISABLE_SYMLINKS_WARNING": "1"},
            stdout=log_file,
            stderr=subprocess.STDOUT,
            **popen_kwargs,
        )

    def _start_idle_watchdog(self, server_pid: int) -> None:
        pass  # the server stops itself after --idle-seconds without a request

    def _voice_sha256(self) -> Optional[str]:
        return None  # the voice is built into the model

    async def call_api(self, text: str) -> bytes:
        payload = {"input": text, "voice": self.config.voice, "speed": self.config.speed}
        key = phrase_cache.cache_key({"engine": "kokoro", **payload}, None)
        cached = phrase_cache.get(key)
        if cached is not None:
            logger.info("TTS line served from the cache (%d characters).", len(text))
            return cached
        try:
            audio = await self._post_speech(payload)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            await self._ensure_server_running()
            audio = await self._post_speech(payload)
        phrase_cache.put(key, audio)
        return audio


# [TTS] The client for the project's engine (settings.tts.engine).
def make_tts_client(settings: Optional[Dict[str, Any]], output_dir: Path) -> IrodoriTTSClient:
    config = tts_config_from_settings(settings)
    client_class = KokoroTTSClient if config.engine == "kokoro" else IrodoriTTSClient
    return client_class(output_dir=output_dir, config=config)


def stop_all_tts_servers() -> None:
    IrodoriTTSClient.stop_server()
    KokoroTTSClient.stop_server()

_SENTENCE_END = re.compile(r"(?<=[。！？!?\n])")
_CLAUSE_END = re.compile(r"(?<=[、，,])")


def _cut_to_chars(piece: str, max_chars: int) -> List[str]:
    """A single sentence (or any piece), forced under `max_chars`: cut at its
    commas, and only as a last resort in the middle of a clause. Shared by
    split_text_for_tts (which then re-packs pieces up to max_chars) and
    split_sentences_for_tts (which doesn't re-pack - see its own docstring
    for why)."""
    if len(piece) <= max_chars:
        return [piece]
    out, cur = [], ""
    for clause in (c for c in _CLAUSE_END.split(piece) if c):
        while len(clause) > max_chars:  # no comma to cut at
            if cur:
                out.append(cur)
                cur = ""
            out.append(clause[:max_chars])
            clause = clause[max_chars:]
        if cur and len(cur) + len(clause) > max_chars:
            out.append(cur)
            cur = ""
        cur += clause
    if cur:
        out.append(cur)
    return out


def split_text_for_tts(text: str, max_chars: int, min_chars: int = 0) -> List[str]:
    """Splits `text` into pieces of at most `max_chars` characters for separate
    TTS requests: whole sentences are grouped together up to the limit, a
    sentence that is too long is cut at its commas, and only as a last resort
    in the middle of a clause. The pieces joined give back exactly `text`.

    `min_chars` (tuning.TTS_MIN_CHUNK_CHARS): a trailing chunk left shorter
    than this - typically just the closing line, once nothing else remains
    to pack it with - is merged into the chunk before it, even past
    `max_chars`. See TTS_MIN_CHUNK_CHARS's own comment for why: sent alone,
    a too-short chunk risks the TTS server hallucinating a "ghost sentence"
    past the end of the real text."""
    text = text or ""
    if len(text) <= max_chars:
        return [text] if text else []

    chunks, cur = [], ""
    for sentence in (s for s in _SENTENCE_END.split(text) if s):
        for piece in _cut_to_chars(sentence, max_chars):
            if cur and len(cur) + len(piece) > max_chars:
                chunks.append(cur)
                cur = ""
            cur += piece
    if cur:
        chunks.append(cur)
    if min_chars and len(chunks) >= 2 and len(chunks[-1]) < min_chars:
        tail = chunks.pop()  # NOTE: chunks[-2] after pop() is chunks[-1] before it - grab the tail first
        chunks[-1] += tail
    return chunks


def split_sentences_for_tts(text: str, max_chars: int) -> List[str]:
    """Splits `text` into ONE chunk per sentence - unlike split_text_for_tts,
    never packs several short sentences into one chunk. Used by
    generate_speech so every sentence becomes its own TTS request with a
    short silence inserted after it (see tuning.TTS_SENTENCE_GAP_*_SECONDS):
    concatenating whole-text-in-one-request audio (or even
    split_text_for_tts's packed multi-sentence chunks) butt-joins sentences
    with zero gap, which reads as rushed/robotic rather than naturally
    spoken. A sentence longer than `max_chars` is still cut at its commas
    (GPU-safety, same as split_text_for_tts) - it becomes several
    consecutive chunks with no gap between them (they're one sentence, a
    mid-sentence pause would sound wrong), only the boundary AFTER the full
    sentence gets a gap."""
    text = text or ""
    if not text:
        return []
    return [
        piece
        for sentence in (s for s in _SENTENCE_END.split(text) if s)
        for piece in _cut_to_chars(sentence, max_chars)
    ]


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

        # [NOTE] [TTS] Sliding-window peak-amplitude scan: a chunk below silence_threshold
        # opens a pause, the first chunk back above it closes one — only pauses
        # meeting min_pause_duration are kept, so brief dips in loudness don't register.
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
            "-y", *tuning.ffmpeg_log_args(),
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
        result = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", errors="replace"
        )

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
            "-y", *tuning.ffmpeg_log_args(),
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
        result = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", errors="replace"
        )
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
        cmd = [ffmpeg_cmd, "-y", *tuning.ffmpeg_log_args(), "-i", video_path, "-i", audio_path]

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
                    *tuning.ffmpeg_thread_args(),
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

        result = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", errors="replace"
        )
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