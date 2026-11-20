"""TTS engine clients: Irodori (natural), Qwen3 (balanced), Kokoro (fast), and the factory that picks one."""

from __future__ import annotations

import asyncio
import hashlib
import os
import random
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, ClassVar, Dict, Final, List, Optional, Tuple

import httpx

from services import runtime_paths, tuning
from services.gpu_cooldown import wait_for_gpu_cooldown
from services.logger.logger import setup_logger
from services.projectfiles import replace_into, write_atomic
from services.runtime_paths import server_environ
from services.tts import japanese_names, phrase_cache
from services.tts.artifacts import cut_off_ratio, remove_stray_bursts, shorten_word_gaps, trim_edge_silence
from services.tts.audio_processor import DEFAULT_OUTPUT_DIR, AudioProcessor
from services.tts.errors import TTSNotReady
from services.tts.ffmpeg_tools import FFmpegManager, apply_speed
from services.tts.server_client import DEFAULT_SERVER_PORT, _LocalServerClient
from services.tts.text_split import chunk_limits, split_text_for_tts
from services.tts.tts_config import TTSConfig, tts_config_from_settings

logger = setup_logger("TTSEngine")

IRODORI_CHECKPOINT = "Aratako/Irodori-TTS-v4.1-Small"
LATENT_ENCODE_TIMEOUT_SECONDS = 600
LATENT_HASH_CHARS = 12
VENV_ENGINE_START_TIMEOUT_SECONDS = 300.0

_latent_failures: set = set()


def ensure_reference_latent(voice: str) -> Optional[Path]:
    """Encodes `voice`'s reference file into a latent next to the voices (once per file content) using the server's own Python."""
    from services.tts import voices

    path = voices.voice_file(voice)
    python = IrodoriTTSClient._SERVER_VENV_PYTHON
    if path is None or not python.exists() or voice in _latent_failures:
        return None
    out = voices.voices_dir() / ".latents" / f"{voice}-{voices._sha256(path)[:LATENT_HASH_CHARS]}.pt"
    if out.exists():
        return out
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Encoding the reference voice '%s' once (saves ~5 s on every narration line)...", voice)
        result = subprocess.run(
            [str(python), str(Path(__file__).with_name("make_latent.py")), str(path), str(out)],
            capture_output=True, encoding="utf-8", errors="replace", timeout=LATENT_ENCODE_TIMEOUT_SECONDS,
        )
        if result.returncode == 0 and out.exists():
            for stale in out.parent.glob(f"{voice}-*.pt"):  # latents of earlier versions of this recording
                if stale != out:
                    stale.unlink(missing_ok=True)
            return out
        logger.warning("Could not encode the reference voice, using the plain file: %s", result.stderr[-300:])
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Could not encode the reference voice, using the plain file: %s", exc)
    _latent_failures.add(voice)
    return None


class IrodoriTTSClient(_LocalServerClient):
    """Handles communication with the local Irodori TTS service."""

    _ENGINE: ClassVar[str] = "irodori"

    _SERVER_DIR: Final[Path] = runtime_paths.engine_dir("Irodori-TTS-Server")
    _SERVER_VENV_PYTHON: Final[Path] = runtime_paths.venv_python(_SERVER_DIR)
    _ACTIVITY_FILE: Final[Path] = _SERVER_DIR / ".last_active"

    # Written with the spawning process's PID right after Popen, so a
    # second, separate `main.py` invocation racing to start the server at
    # nearly the same moment (before either can see the other's server as
    # healthy) can detect "someone else is already starting it" and just
    # wait, instead of spawning its own second copy.
    _PIDFILE: Final[Path] = _SERVER_DIR / ".server.pid"

    _PROCESS_MARKER: ClassVar[str] = "irodori_openai_tts"
    _SERVER_NAME: ClassVar[str] = "Irodori TTS"

    _server_process: Optional[subprocess.Popen] = None

    # [NOTE] [TTS] A forced regeneration ("Redo voice") must not get the same stored take back, so it skips the read; it still writes the new one.
    bypass_cache: bool = False
    # Where the file being spoken keeps its sentences (voice_pieces.py), the voice they must match, and the
    # sentences to speak anew (picked in the editor); set by audio_step for the overview narration.
    pieces_dir: Optional[Path] = None
    pieces_voice: Optional[dict] = None
    redo_texts: frozenset = frozenset()
    # A line -> the spelling whose retake fixed a misread place name in it (name_check), for later retakes of that line.
    _names_spelled: Dict[str, str] = {}

    def __init__(
        self,
        output_dir: Path = DEFAULT_OUTPUT_DIR,
        base_url: str = f"http://127.0.0.1:{DEFAULT_SERVER_PORT}/v1/audio/speech",
        config: Optional[TTSConfig] = None,
    ):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.base_url = base_url
        # Built once per client (not per call) — TTSConfig is frozen and
        # validated in __post_init__, so every later generate_speech() call
        # just reuses it instead of re-validating speed on every request.
        self.config = config or TTSConfig()

    # --- server -----------------------------------------------------------

    def _spawn_server(self, port: int, popen_kwargs: Dict[str, Any]) -> subprocess.Popen:
        """Starts the server process (Irodori: its own venv and model; a subclass launches its own)."""
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
            **server_environ(),
            "IRODORI_MODEL_DEVICE": device,
            "IRODORI_CODEC_DEVICE": device,
            "IRODORI_HF_CHECKPOINT": IRODORI_CHECKPOINT,
            "IRODORI_MODEL_PRECISION": precision,
            "IRODORI_VOICES_DIR": str(voices_dir()),
        }
        logger.info("Irodori TTS server device: %s (Precision: %s).", device, precision)
        proc = subprocess.Popen(
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
        # The child holds its own copy of the handle; ours would stay open (and lock server.log) for as long as this process lives.
        log_file.close()
        return proc

    @classmethod
    def is_ready(cls) -> bool:
        return cls._SERVER_VENV_PYTHON.exists()

    def _missing_server_message(self) -> str:
        return (
            f"Irodori TTS server isn't reachable at {self.base_url} and its "
            f"venv wasn't found at {self._SERVER_VENV_PYTHON} to auto-start it. "
            "Open Settings > Voice and press Set up natural voice, or start the server by hand."
        )

    # --- one request ------------------------------------------------------

    async def _post_speech(self, payload: Dict[str, Any]) -> bytes:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.base_url, json=payload, timeout=httpx.Timeout(tuning.TTS_REQUEST_TIMEOUT_SECONDS, connect=10.0),
            )

            if response.status_code != 200:
                error_msg = f"API request failed with status {response.status_code}: {response.text}"
                logger.error(error_msg)
                raise Exception(error_msg)

            self._touch_activity()
            return response.content

    async def call_api(self, text: str) -> bytes:
        """Makes an HTTP POST request to the local Irodori TTS API to generate speech.
        If the connection is refused/closed (server not running) OR the
        connection attempt just times out (server starting up too slowly to
        accept it yet — httpx.ConnectTimeout is a SEPARATE exception class
        from ConnectError, not a subclass, so both need to be caught here),
        starts/waits for it as a subprocess and retries once it's healthy."""
        payload = self.config.to_payload(tuning.TTS_IRODORI_LEAD_IN + text)

        # A line spoken before (in this or any project) is not synthesized again; ~40 s each on a CPU.
        key = phrase_cache.cache_key(payload, self._voice_sha256())
        cached = self._cached_line(key)
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

    def _cached_line(self, key: str) -> Optional[bytes]:
        return None if self.bypass_cache else phrase_cache.get(key)

    def _voice_sha256(self) -> Optional[str]:
        from services.tts import voices

        path = voices.voice_file(self.config.voice)
        return voices._sha256(path) if path else None

    async def _with_reference_latent(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The payload with the voice's reference audio encoded once and reused.

        The server otherwise re-encodes the wav on every request (~5 s on a CPU).
        Anything that goes wrong falls back to the plain voice, which the server resolves itself.
        """
        latent = await asyncio.to_thread(ensure_reference_latent, self.config.voice)
        if latent is None:
            return payload
        return {**payload, "irodori": {**payload.get("irodori", {}), "ref_latent": str(latent)}}

    # --- one chunk: retakes for cut-off words, misread names, wrong pitch ---

    async def _speak_chunk(self, text: str, split: bool = True) -> List[bytes]:
        """A chunk's audio. A take that stops mid-word (cached or new) is retaken; if every take
        does, the chunk is spoken in halves, and only then is the least-cut take kept."""
        best: Optional[Tuple[float, bytes]] = None
        bypass = self.bypass_cache
        try:
            for attempt in range(tuning.TTS_CUTOFF_RETAKES + 1):
                self.bypass_cache = bypass or attempt > 0
                audio = await self.call_api(text)
                ratio = cut_off_ratio(audio)
                if ratio <= tuning.TTS_CUTOFF_RATIO:
                    return [await self._with_pitch_matched(text, await self._with_names_heard(text, audio))]
                logger.warning("TTS take %d ends mid-word (%.2f): %s", attempt + 1, ratio, text)
                if best is None or ratio < best[0]:
                    best = (ratio, audio)
        finally:
            self.bypass_cache = bypass
        if split:
            halves = split_text_for_tts(text, max(tuning.TTS_MIN_CHUNK_CHARS, len(text) // 2), tuning.TTS_MIN_CHUNK_CHARS)
            if len(halves) > 1:
                logger.warning("TTS speaking the chunk in %d parts instead.", len(halves))
                takes: List[bytes] = []
                for half in halves:
                    takes += await self._speak_chunk(half, split=False)
                return takes
        logger.warning("TTS kept a take that still ends mid-word (%.2f): %s", best[0], text)
        return [best[1]]

    async def _with_names_heard(self, text: str, audio: bytes) -> bytes:
        """`audio`, or a retake when the voice misread a place name in it; the take with the fewest misses is kept.
        A misread name left in kanji is spelled out for the retakes."""
        from services.tts import name_check

        if not tuning.TTS_NAME_CHECK or not name_check.expected_names(text):
            return audio
        # The take kept for this exact text + first take last time: a cached line is not checked and retaken on every run.
        settled_key = phrase_cache.cache_key({"names_checked": text, "take": hashlib.sha256(audio).hexdigest()}, None)
        settled = self._cached_line(settled_key)
        if settled is not None:
            return settled
        best = await self._best_heard_take(text, audio, name_check)
        phrase_cache.put(settled_key, best)
        return best

    async def _best_heard_take(self, text: str, audio: bytes, name_check: Any) -> bytes:
        original = text
        missing = await asyncio.to_thread(name_check.misheard_names, audio, text)
        best = (len(missing), audio)
        bypass = self.bypass_cache
        try:
            for attempt in range(tuning.TTS_NAME_RETAKES):
                if not best[0]:
                    break
                logger.warning("TTS retake %d for misread place names: %s", attempt + 1, ", ".join(missing))
                self.bypass_cache = True
                text = name_check.spell_out(text, missing)
                take = await self.call_api(text)
                if cut_off_ratio(take) > tuning.TTS_CUTOFF_RATIO:
                    continue
                missing = await asyncio.to_thread(name_check.misheard_names, take, text)
                if len(missing) < best[0]:
                    best = (len(missing), take)
                    self._names_spelled[original] = text
        finally:
            self.bypass_cache = bypass
        return best[1]

    async def _with_pitch_matched(self, text: str, audio: bytes) -> bytes:
        """`audio`, or the retake whose dictionary words best follow their high/low patterns (pitch_accent.py)."""
        from services.tts import pitch_accent

        wanted = pitch_accent.wanted(text)
        if not wanted:
            return audio
        settled = lambda take: phrase_cache.cache_key({"pitch_checked": text, "wanted": wanted, "take": hashlib.sha256(take).hexdigest()}, None)  # noqa: E731
        cached = self._cached_line(settled(audio))
        if cached is not None:
            return cached
        spoken = self._names_spelled.get(text, text)  # a retake keeps the spelling that fixed a misread name
        kana = await asyncio.to_thread(pitch_accent.sentence_kana, spoken)
        best = (await asyncio.to_thread(pitch_accent.score_take, audio, kana, wanted), audio)
        takes, bypass = [audio], self.bypass_cache
        try:
            for attempt in range(tuning.TTS_PITCH_RETAKES):
                if best[0] >= 1:
                    break
                logger.warning("TTS retake %d for high/low (%.2f): %s", attempt + 1, best[0], text)
                self.bypass_cache = True
                take = await self.call_api(spoken)
                takes.append(take)
                if cut_off_ratio(take) > tuning.TTS_CUTOFF_RATIO:
                    continue
                s = await asyncio.to_thread(pitch_accent.score_take, take, kana, wanted)
                if s > best[0]:
                    best = (s, take)
        finally:
            self.bypass_cache = bypass
        # The first take and the last retake (what the line cache now holds) both map to the kept one.
        for take in {takes[0], takes[-1]}:
            phrase_cache.put(settled(take), best[1])
        return best[1]

    # --- a whole text -> one wav file --------------------------------------

    def _remove_stray_bursts(self, path: Path) -> None:
        if self._ENGINE in tuning.TTS_STRAY_BURST_ENGINES:
            remove_stray_bursts(str(path))

    async def _speak_redoing(self, chunk: str) -> List[bytes]:
        """Speaks `chunk`, skipping the take cache when the editor picked it to be spoken anew."""
        bypass = self.bypass_cache
        self.bypass_cache = bypass or chunk in self.redo_texts
        try:
            return await self._speak_chunk(chunk)
        finally:
            self.bypass_cache = bypass

    async def _speak_text(self, text: str) -> List[bytes]:
        """Every take of `text`, chunk by chunk; the sentences are kept beside the file for the editor."""
        # A long text in one request overloads the GPU (see tuning.TTS_DEVICE): speak it in short chunks
        # (split_text_for_tts), one request at a time, and join them with a short random gap.
        chunks = split_text_for_tts(text, *chunk_limits(text))
        if len(chunks) > 1:
            logger.info("TTS text of %d characters split into %d chunk(s).", len(text), len(chunks))
        from services.tts import voice_pieces

        # A forced remake still keeps the sentences locked in the editor.
        kept = voice_pieces.load(self.pieces_dir, self.pieces_voice, locked_only=self.bypass_cache) if self.pieces_dir else {}
        takes: List[bytes] = []
        pieces = []
        for chunk in chunks or [text]:
            chunk_takes = None if chunk in self.redo_texts else kept.get(chunk)
            if chunk_takes is None:
                chunk_takes = await self._speak_redoing(chunk)
            pieces.append((chunk, chunk_takes))
            takes += chunk_takes
        if self.pieces_dir:
            voice_pieces.save(self.pieces_dir, self.pieces_voice, pieces)
        return takes

    def _polish_takes(self, takes: List[bytes]) -> List[bytes]:
        """Trims each take's edge silence and, for Kokoro's English voices, shortens the gaps between words."""
        takes = [
            trim_edge_silence(t, tuning.TTS_EDGE_SILENCE_KEEP_SECONDS, tuning.TTS_EDGE_SILENCE_DB) for t in takes
        ]
        if self._ENGINE == "kokoro" and tuning.kokoro_language(self.config.voice) != "j" and tuning.TTS_WORD_GAP_SECONDS:
            takes = [shorten_word_gaps(t, *tuning.TTS_WORD_GAP_SECONDS, tuning.TTS_EDGE_SILENCE_DB) for t in takes]
        return takes

    @staticmethod
    def _write_parts(takes: List[bytes], file_path: Path, parts: List[str]) -> Tuple[Optional[int], Optional[int]]:
        """Writes each take to its own part file (added to `parts` as it goes, so a failure still cleans up);
        returns the audio format of the first one."""
        sample_rate: Optional[int] = None
        channels: Optional[int] = None
        for i, take in enumerate(takes):
            part = file_path.with_name(f"{file_path.stem}.part{i:02d}.wav")
            with open(part, "wb") as f:
                f.write(take)
            parts.append(str(part))
            if sample_rate is None:  # once is enough, every part shares the server's format
                sample_rate, channels = FFmpegManager.get_audio_format(str(part))
        return sample_rate, channels

    @staticmethod
    def _interleave_gaps(
        processor: AudioProcessor, parts: List[str], gaps: List[str], file_path: Path,
        sample_rate: Optional[int], channels: Optional[int],
    ) -> List[str]:
        """The part files with a short, randomized pause after every sentence but the last
        (nothing to breathe before at the very end). Gap files are added to `gaps`."""
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
        return interleaved

    def _join_takes(self, takes: List[bytes], file_path: Path) -> None:
        """Joins several takes, with short pauses between them, into `file_path`."""
        processor = AudioProcessor(output_dir=self.output_dir)
        parts: List[str] = []
        gaps: List[str] = []
        try:
            sample_rate, channels = self._write_parts(takes, file_path, parts)
            interleaved = self._interleave_gaps(processor, parts, gaps, file_path, sample_rate, channels)
            joined = file_path.with_name(f".{file_path.stem}.joining{file_path.suffix}")
            processor.concatenate_files(interleaved, str(joined))
            replace_into(joined, file_path)
            self._remove_stray_bursts(file_path)
        finally:
            for p in parts + gaps:
                Path(p).unlink(missing_ok=True)

    async def generate_speech(
        self, text: str, output_filename: Optional[str] = None
    ) -> str:
        """Generates speech audio and saves it to a local WAV file."""
        filename = output_filename or f"{uuid.uuid4()}.wav"
        file_path = self.output_dir / filename

        takes = self._polish_takes(await self._speak_text(text))
        if len(takes) == 1:
            write_atomic(file_path, takes[0])
            self._remove_stray_bursts(file_path)
        else:
            self._join_takes(takes, file_path)
        return str(file_path)


class _VenvEngineClient(IrodoriTTSClient):
    """An engine that runs as a small server of its own, in a venv of its own.

    The venv is bin/<Engine>-TTS/.venv, put there by services/tts/<engine>_setup.py.
    Everything else (chunking, gaps, the shared phrase cache, server reuse across processes) is the Irodori client's.
    """

    _SERVER_SCRIPT: ClassVar[str] = ""
    _SERVER_PORT: ClassVar[int] = 0
    _SETUP_HINT: ClassVar[str] = ""
    _SERVER_START_TIMEOUT_SECONDS: ClassVar[float] = VENV_ENGINE_START_TIMEOUT_SECONDS
    _IDLE_TIMEOUT_SECONDS: ClassVar[float] = 600.0

    @classmethod
    def is_ready(cls) -> bool:
        return cls._SERVER_VENV_PYTHON.exists() and cls._READY_FILE.exists()

    def _missing_server_message(self) -> str:
        return self._SETUP_HINT

    def _spawn_server(self, port: int, popen_kwargs: Dict[str, Any]) -> subprocess.Popen:
        log_file = open(self._SERVER_DIR / "server.log", "ab")
        proc = subprocess.Popen(
            [
                str(self._SERVER_VENV_PYTHON), str(Path(__file__).with_name(self._SERVER_SCRIPT)),
                "--host", "127.0.0.1", "--port", str(port), "--idle-seconds", str(int(self._IDLE_TIMEOUT_SECONDS)),
            ],
            cwd=str(self._SERVER_DIR),
            env={**server_environ(), "PYTHONIOENCODING": "utf-8", "HF_HUB_DISABLE_SYMLINKS_WARNING": "1", **self._server_env()},
            stdout=log_file,
            stderr=subprocess.STDOUT,
            **popen_kwargs,
        )
        log_file.close()  # the child has its own copy of the handle
        return proc

    def _server_env(self) -> Dict[str, str]:
        return {}

    def _start_idle_watchdog(self, server_pid: int) -> None:
        pass  # the server stops itself after --idle-seconds without a request

    async def _post_starting_the_server(self, payload: Dict[str, Any]) -> bytes:
        try:
            return await self._post_speech(payload)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            await self._ensure_server_running()
            return await self._post_speech(payload)


class KokoroTTSClient(_VenvEngineClient):
    """The fast engine: Kokoro, a small model with fixed voices (no cloning): Japanese, and American and British English."""

    _SERVER_DIR: Final[Path] = runtime_paths.engine_dir("Kokoro-TTS")
    _SERVER_VENV_PYTHON: Final[Path] = runtime_paths.venv_python(_SERVER_DIR)
    _ACTIVITY_FILE: Final[Path] = _SERVER_DIR / ".last_active"
    _PIDFILE: Final[Path] = _SERVER_DIR / ".server.pid"
    _READY_FILE: Final[Path] = _SERVER_DIR / ".ready"
    _ENGLISH_READY_FILE: Final[Path] = _SERVER_DIR / ".ready_en"  # the English voices and language data are in
    _PROCESS_MARKER: ClassVar[str] = "kokoro_server"
    _SERVER_NAME: ClassVar[str] = "Kokoro TTS"
    _SERVER_SCRIPT: ClassVar[str] = "kokoro_server.py"
    _ENGINE: ClassVar[str] = "kokoro"
    _SERVER_PORT: ClassVar[int] = tuning.KOKORO_PORT
    _SETUP_HINT: ClassVar[str] = "The fast voice (Kokoro) is not set up yet. Open Settings > Voice and press Set up fast voice."
    _server_process: Optional[subprocess.Popen] = None

    def __init__(
        self,
        output_dir: Path = DEFAULT_OUTPUT_DIR,
        base_url: str = f"http://127.0.0.1:{tuning.KOKORO_PORT}/v1/audio/speech",
        config: Optional[TTSConfig] = None,
    ):
        super().__init__(output_dir=output_dir, base_url=base_url, config=config or TTSConfig(engine="kokoro", voice=tuning.KOKORO_VOICE, model="kokoro", caption=None))

    def _voice_sha256(self) -> Optional[str]:
        return None  # the voice is built into the model

    @classmethod
    def english_ready(cls) -> bool:
        return cls.is_ready() and cls._ENGLISH_READY_FILE.exists()

    @classmethod
    def require_voice(cls, voice: str) -> None:
        """Raises, with what to do, when `voice` speaks English and the English voices are not set up."""
        if tuning.kokoro_language(voice) != "j" and not cls.english_ready():
            raise TTSNotReady(
                f"The voice '{voice}' speaks English, which the fast voice does not have yet. "
                "Open Settings > Voice and press Add English voices."
            )

    async def call_api(self, text: str) -> bytes:
        self.require_voice(self.config.voice)
        if tuning.kokoro_language(self.config.voice) != "j":
            text = japanese_names.mark(text)
        payload = {"input": text, "voice": self.config.voice, "speed": self.config.speed}
        named = {"ja_names": japanese_names.RULE_VERSION} if "](ja:" in text else {}  # /sounds/ are in the text itself
        key = phrase_cache.cache_key({"engine": "kokoro", **payload, **named}, None)
        cached = self._cached_line(key)
        if cached is not None:
            logger.info("TTS line served from the cache (%d characters).", len(text))
            return cached
        audio = await self._post_starting_the_server(payload)
        phrase_cache.put(key, audio)
        return audio


def qwen3_language(text: str) -> str:
    """The language Qwen3 reads a line in: Japanese when it has any kana or kanji, else English (an English
    narration read as Japanese comes out with a heavy Japanese accent)."""
    from services.localization.localization import is_japanese

    return "Japanese" if is_japanese(text) else "English"


def qwen3_device() -> str:
    """Where the Qwen3 server runs its model: NAVIVI_TTS_DEVICE, else tuning.QWEN3_DEVICE ("auto" means the GPU)."""
    device = (os.environ.get("NAVIVI_TTS_DEVICE") or tuning.QWEN3_DEVICE).strip().lower()
    return "cpu" if device == "cpu" else "cuda"


class Qwen3TTSClient(_VenvEngineClient):
    """The middle engine: Qwen3-TTS 0.6B, clones a voice from a recording (the same library as Irodori) at about a third of Irodori's time."""

    _SERVER_DIR: Final[Path] = runtime_paths.engine_dir("Qwen3-TTS")
    _SERVER_VENV_PYTHON: Final[Path] = runtime_paths.venv_python(_SERVER_DIR)
    _ACTIVITY_FILE: Final[Path] = _SERVER_DIR / ".last_active"
    _PIDFILE: Final[Path] = _SERVER_DIR / ".server.pid"
    _READY_FILE: Final[Path] = _SERVER_DIR / ".ready"
    _PROCESS_MARKER: ClassVar[str] = "qwen3_server"
    _SERVER_NAME: ClassVar[str] = "Qwen3 TTS"
    _SERVER_SCRIPT: ClassVar[str] = "qwen3_server.py"
    _ENGINE: ClassVar[str] = "qwen3"
    _SERVER_PORT: ClassVar[int] = tuning.QWEN3_PORT
    _SETUP_HINT: ClassVar[str] = "The balanced voice (Qwen3-TTS) is not set up yet. Open Settings > Voice and press Set up balanced voice."
    _server_process: Optional[subprocess.Popen] = None

    def __init__(
        self,
        output_dir: Path = DEFAULT_OUTPUT_DIR,
        base_url: str = f"http://127.0.0.1:{tuning.QWEN3_PORT}/v1/audio/speech",
        config: Optional[TTSConfig] = None,
    ):
        super().__init__(output_dir=output_dir, base_url=base_url, config=config or TTSConfig(engine="qwen3", model="qwen3", caption=None))

    def _reference(self) -> Path:
        from services.tts import voices

        path = voices.voice_file(self.config.voice)
        if path is None:
            raise FileNotFoundError(
                f"The balanced voice clones a recording, and voice '{self.config.voice}' has none. Choose a voice in Settings > Voice."
            )
        return path

    def _server_env(self) -> Dict[str, str]:
        env = {
            "QWEN3_DEVICE": qwen3_device(),
            "QWEN3_VRAM_FRACTION": str(tuning.QWEN3_VRAM_FRACTION),
            "QWEN3_MAX_ATTEMPTS": str(tuning.QWEN3_MAX_ATTEMPTS),
        }
        if tuning.QWEN3_CPU_THREADS:
            env["QWEN3_THREADS"] = str(tuning.QWEN3_CPU_THREADS)
        return env

    async def call_api(self, text: str) -> bytes:
        reference = self._reference()
        if tuning.QWEN3_SPELL_OUT_KANJI:
            from services.localization.japanese_words import spoken_kana

            text = spoken_kana(text)
        language = qwen3_language(text)
        # Japanese lines keep their old key (cached before the language was sent).
        key = phrase_cache.cache_key(
            {"engine": "qwen3", "input": text, "speed": self.config.speed, **({"language": language} if language != "Japanese" else {})},
            self._voice_sha256(),
        )
        cached = self._cached_line(key)
        if cached is not None:
            logger.info("TTS line served from the cache (%d characters).", len(text))
            return cached
        if qwen3_device() == "cuda":
            await asyncio.to_thread(wait_for_gpu_cooldown, "the next TTS line")
        audio = await self._post_starting_the_server(
            {"input": text, "ref_audio": str(reference), "language": language}
        )
        audio = await asyncio.to_thread(apply_speed, audio, self.config.speed)
        phrase_cache.put(key, audio)
        return audio


def make_tts_client(settings: Optional[Dict[str, Any]], output_dir: Path) -> IrodoriTTSClient:
    """The client for the project's engine (settings.tts.engine)."""
    config = tts_config_from_settings(settings)
    client_class = {"kokoro": KokoroTTSClient, "qwen3": Qwen3TTSClient}.get(config.engine, IrodoriTTSClient)
    if client_class is KokoroTTSClient:
        KokoroTTSClient.require_voice(config.voice)  # stop before the run, not as silent narration halfway through
    return client_class(output_dir=output_dir, config=config)


def stop_all_tts_servers() -> None:
    IrodoriTTSClient.stop_server()
    KokoroTTSClient.stop_server()
    Qwen3TTSClient.stop_server()
