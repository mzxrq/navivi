"""Removes the stray "あ" the Irodori TTS sometimes emits inside a pause.

Seen at the comma pauses of a sentence: a burst of 40-80 ms, about as loud as speech, sitting alone
between two stretches of silence (real words are longer and sit inside phrases). It is not speech,
so it is silenced (with a short fade so the edit itself doesn't click) and nothing else changes:
the file keeps its length and every other sample.
"""

import os
import wave
from typing import List, Tuple

import numpy as np

from services.logger.logger import setup_logger

logger = setup_logger(__name__)

_WINDOW_SECONDS = 0.01
_SPEECH_RMS = 0.03          # a window above this counts as sound
_MAX_BURST_SECONDS = 0.09   # longer than this is a real sound
_MIN_SILENCE_SECONDS = 0.15  # silence needed on both sides of a burst
_PAD_SECONDS = 0.015        # also cleared around the burst, covers its tails
_FADE_SECONDS = 0.004


def find_stray_bursts(samples: np.ndarray, sample_rate: int) -> List[Tuple[int, int]]:
    """(start, end) sample ranges of short sounds isolated by silence. `samples` is mono float in -1..1.
    The file's start and end count as silence."""
    window = max(1, int(sample_rate * _WINDOW_SECONDS))
    frames = samples[: len(samples) // window * window].reshape(-1, window)
    if not len(frames):
        return []
    sound = np.sqrt((frames ** 2).mean(axis=1)) > _SPEECH_RMS

    runs: List[Tuple[int, int]] = []
    i = 0
    while i < len(sound):
        if sound[i]:
            j = i
            while j < len(sound) and sound[j]:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1

    max_windows = _MAX_BURST_SECONDS / _WINDOW_SECONDS
    min_gap = _MIN_SILENCE_SECONDS / _WINDOW_SECONDS
    found: List[Tuple[int, int]] = []
    for k, (a, b) in enumerate(runs):
        before = a - runs[k - 1][1] if k > 0 else float("inf")
        after = runs[k + 1][0] - b if k + 1 < len(runs) else float("inf")
        if b - a <= max_windows and before >= min_gap and after >= min_gap and len(runs) > 1:
            found.append((a * window, b * window))
    return found


def remove_stray_bursts(path: str) -> List[float]:
    """Silences stray bursts in a 16-bit PCM wav in place. Returns the seconds at which they were."""
    try:
        with wave.open(path, "rb") as w:
            params = w.getparams()
            if params.sampwidth != 2:
                return []
            raw = w.readframes(params.nframes)
    except (wave.Error, EOFError, OSError):
        return []

    data = np.frombuffer(raw, dtype=np.int16).copy()
    channels = params.nchannels
    frames = data.reshape(-1, channels)
    mono = frames.astype(np.float32).mean(axis=1) / 32768.0

    bursts = find_stray_bursts(mono, params.framerate)
    if not bursts:
        return []

    pad = int(params.framerate * _PAD_SECONDS)
    fade = max(1, int(params.framerate * _FADE_SECONDS))
    gain = np.ones(len(frames), dtype=np.float32)
    for start, end in bursts:
        s = max(0, start - pad)
        e = min(len(frames), end + pad)
        gain[s:e] = 0.0
        lo = max(0, s - fade)
        if s > lo:
            gain[lo:s] = np.minimum(gain[lo:s], np.linspace(1.0, 0.0, s - lo, dtype=np.float32))
        hi = min(len(frames), e + fade)
        if hi > e:
            gain[e:hi] = np.minimum(gain[e:hi], np.linspace(0.0, 1.0, hi - e, dtype=np.float32))

    cleaned = np.clip(frames.astype(np.float32) * gain[:, None], -32768, 32767).astype(np.int16)
    tmp = path + ".declick.tmp"
    with wave.open(tmp, "wb") as out:
        out.setparams(params)
        out.writeframes(cleaned.tobytes())
    os.replace(tmp, path)

    seconds = [round(start / params.framerate, 2) for start, _ in bursts]
    logger.info("Removed %d stray TTS burst(s) from %s at %s s", len(bursts), os.path.basename(path), seconds)
    return seconds
