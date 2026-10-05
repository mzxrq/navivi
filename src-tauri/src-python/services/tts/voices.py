"""Voice library for the Irodori TTS server: reference audio files in its
voices/ folder, each one a cloneable voice named by its filename stem.

Plain file operations, so listing/adding/deleting never starts the server.
The server rescans the folder on every request."""

from __future__ import annotations

import hashlib
import re
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from services import runtime_paths, tuning
from services.logger.logger import setup_logger

logger = setup_logger("TTSVoices")

# Mirrors bin/Irodori-TTS-Server/src/irodori_openai_tts/voices.py (separate venv).
VOICE_EXTENSIONS = {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus", ".aac", ".webm"}
VOICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
NO_REF_VOICE = "none"

# Reference clips outside this range clone poorly (too short) or slowly (too long).
MIN_REF_SECONDS = 3.0
MAX_REF_SECONDS = 30.0

_voices_dir_override: Optional[Path] = None


def voices_dir() -> Path:
    if _voices_dir_override is not None:
        return _voices_dir_override
    return runtime_paths.engine_dir("Irodori-TTS-Server") / "voices"


def set_voices_dir(path: Optional[Path]) -> None:
    """Test hook."""
    global _voices_dir_override
    _voices_dir_override = Path(path) if path is not None else None


def _duration(path: Path) -> Optional[float]:
    try:
        from services.tts.ttsengine import FFmpegManager
        return round(FFmpegManager.get_media_duration(str(path)), 2)
    except Exception:
        return None


def voice_file(voice_id: str) -> Optional[Path]:
    root = voices_dir()
    if not voice_id or not root.is_dir():
        return None
    for path in sorted(root.iterdir()):
        if path.is_file() and path.stem == voice_id and path.suffix.lower() in VOICE_EXTENSIONS:
            return path
    return None


def voice_exists(voice_id: str) -> bool:
    return voice_id == NO_REF_VOICE or voice_file(voice_id) is not None


def validate_voice_id(voice_id: str) -> None:
    if not voice_id or VOICE_ID_PATTERN.fullmatch(voice_id) is None:
        raise ValueError("Voice id must use only ASCII letters, numbers, '_' or '-'.")
    if voice_id.lower() == NO_REF_VOICE:
        raise ValueError(f"'{NO_REF_VOICE}' is reserved.")


def list_voices() -> List[Dict[str, Any]]:
    voices: List[Dict[str, Any]] = [{
        "id": NO_REF_VOICE, "filename": None, "bytes": 0,
        "duration_seconds": None, "builtin": True,
    }]
    root = voices_dir()
    if root.is_dir():
        for path in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if path.is_file() and path.suffix.lower() in VOICE_EXTENSIONS:
                voices.append({
                    "id": path.stem,
                    "filename": path.name,
                    "bytes": path.stat().st_size,
                    "duration_seconds": _duration(path),
                    "builtin": False,
                })
    return voices


def add_voice(src_path: str, voice_id: Optional[str] = None, replace: bool = False) -> Dict[str, Any]:
    src = Path(src_path)
    if not src.is_file():
        raise FileNotFoundError(f"File not found: {src_path}")
    suffix = src.suffix.lower()
    if suffix not in VOICE_EXTENSIONS:
        raise ValueError(f"Unsupported audio type '{suffix}'. Use one of: {', '.join(sorted(VOICE_EXTENSIONS))}.")
    if src.stat().st_size == 0:
        raise ValueError("Voice file is empty.")
    voice_id = (voice_id or src.stem).strip()
    validate_voice_id(voice_id)

    existing = voice_file(voice_id)
    if existing is not None and not replace:
        raise FileExistsError(f"Voice '{voice_id}' already exists.")

    root = voices_dir()
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{voice_id}{suffix}"
    shutil.copyfile(src, target)
    if existing is not None and existing != target:
        existing.unlink(missing_ok=True)

    duration = _duration(target)
    warning = None
    if duration is not None and duration < MIN_REF_SECONDS:
        warning = f"Reference is {duration:.1f}s; under {MIN_REF_SECONDS:.0f}s the voice may not clone well."
    elif duration is not None and duration > MAX_REF_SECONDS:
        warning = f"Reference is {duration:.1f}s; over {MAX_REF_SECONDS:.0f}s makes every TTS request slower."
    logger.info("Voice '%s' added from %s.", voice_id, src)
    return {
        "id": voice_id, "filename": target.name, "bytes": target.stat().st_size,
        "duration_seconds": duration, "warning": warning,
    }


def delete_voice(voice_id: str) -> bool:
    if voice_id == NO_REF_VOICE:
        raise ValueError(f"'{NO_REF_VOICE}' is built in and can't be deleted.")
    path = voice_file(voice_id)
    if path is None:
        return False
    path.unlink()
    logger.info("Voice '%s' deleted.", voice_id)
    return True


@lru_cache(maxsize=64)
def _sha256_of(path: str, mtime_ns: int, size: int) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# [NOTE] [TTS] Called for every narration line (cache key, fingerprint, latent name): hashed again only when the file changes.
def _sha256(path: Path) -> str:
    st = Path(path).stat()
    return _sha256_of(str(path), st.st_mtime_ns, st.st_size)


def voice_fingerprint(voice: str, speed: float, caption: Optional[str] = None, engine: str = "irodori") -> Dict[str, Any]:
    """What a narration clip was spoken with; a mismatch means it's remade."""
    if engine == "kokoro":  # the engine's own voice, not a file of ours
        return {"voice": voice, "sha256": None, "speed": float(speed), "caption": None, "engine": engine}
    path = voice_file(voice)
    fingerprint = {
        "voice": voice, "sha256": _sha256(path) if path else None,
        "speed": float(speed), "caption": (caption or None) if engine == "irodori" else None,  # the style caption is Irodori's
    }
    return fingerprint if engine == "irodori" else {**fingerprint, "engine": engine}


# Clips made before fingerprints existed used the old fixed defaults.
LEGACY_FINGERPRINT = {"voice": tuning.TTS_VOICE, "sha256": None, "speed": tuning.TTS_SPEED}


def fingerprints_match(stored: Dict[str, Any], current: Dict[str, Any]) -> bool:
    if stored.get("engine", "irodori") != current.get("engine", "irodori"):
        return False
    if stored.get("voice") != current.get("voice"):
        return False
    if abs(float(stored.get("speed", 0)) - float(current.get("speed", 0))) > 1e-6:
        return False
    if (stored.get("caption") or None) != (current.get("caption") or None):
        return False
    a, b = stored.get("sha256"), current.get("sha256")
    return a is None or b is None or a == b
