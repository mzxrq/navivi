"""Narration lines already spoken, shared by every project (see projectfiles.tts_cache_dir).

A line is the request that made it (text, voice, speed, caption, sampling options) plus the voice file's content hash, so a changed
voice or preset is a different line. Entries are plain WAV files named by that hash; the oldest are removed past TTS_CACHE_MAX_MB."""

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from services import tuning
from services.logger.logger import setup_logger
from services.projectfiles import tts_cache_dir

logger = setup_logger("TTSPhraseCache")


def cache_key(payload: Dict[str, Any], voice_sha256: Optional[str]) -> str:
    blob = json.dumps({"request": payload, "voice": voice_sha256}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _path(key: str) -> Path:
    return tts_cache_dir() / f"{key}.wav"


def get(key: str) -> Optional[bytes]:
    path = _path(key)
    try:
        data = path.read_bytes()
        os.utime(path)  # a line that keeps being used is the last to go
        return data or None
    except OSError:
        return None


def put(key: str, data: bytes) -> None:
    if not data:
        return
    path = _path(key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        prune()
    except OSError as exc:  # the cache is only an optimisation
        logger.warning("Could not cache a narration line: %s", exc)


def prune(max_mb: int = tuning.TTS_CACHE_MAX_MB) -> None:
    entries = []
    for p in tts_cache_dir().glob("*.wav"):
        try:
            st = p.stat()
        except OSError:
            continue
        entries.append((st.st_mtime, st.st_size, p))
    total = sum(size for _, size, _ in entries)
    for _, size, p in sorted(entries):
        if total <= max_mb * 1024 * 1024:
            break
        try:
            p.unlink()
            total -= size
        except OSError:
            pass
