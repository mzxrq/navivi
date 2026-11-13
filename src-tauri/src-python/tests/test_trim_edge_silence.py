import io
import wave

import numpy as np

from services.tts.artifacts import trim_edge_silence

RATE = 16000


def _wav(samples: np.ndarray) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(samples.astype(np.int16).tobytes())
    return out.getvalue()


def _seconds(wav: bytes) -> float:
    with wave.open(io.BytesIO(wav), "rb") as w:
        return w.getnframes() / w.getframerate()


def test_server_padding_is_cut_to_a_short_breath():
    speech = (np.sin(np.arange(RATE) / 5) * 8000)  # 1 s of "voice"
    pad = np.zeros(RATE // 2)  # 0.5 s of silence each side
    trimmed = trim_edge_silence(_wav(np.concatenate([pad, speech, pad])), 0.05, -45.0)
    assert abs(_seconds(trimmed) - 1.1) < 0.01  # 1 s + 0.05 s each side


def test_unreadable_or_silent_takes_are_left_alone():
    assert trim_edge_silence(b"not a wav", 0.05, -45.0) == b"not a wav"
    silent = _wav(np.zeros(RATE))
    assert trim_edge_silence(silent, 0.05, -45.0) == silent


def test_a_hesitation_inside_a_take_is_shortened_and_a_comma_pause_stays():
    from services.tts.artifacts import shorten_word_gaps

    tone = (8000 * np.sin(np.arange(int(RATE * 0.5)) / 3)).astype(np.int16)
    gap = lambda s: np.zeros(int(RATE * s), dtype=np.int16)  # noqa: E731
    take = _wav(np.concatenate([gap(0.2), tone, gap(0.15), tone, gap(0.45), tone, gap(0.2)]))
    out = shorten_word_gaps(take, 0.1, 0.3, 0.04, -45.0)
    assert abs(_seconds(take) - _seconds(out) - 0.11) < 0.02  # only the 0.15 s gap lost ~0.11 s; edges and 0.45 s kept
    assert shorten_word_gaps(b"not a wav", 0.1, 0.3, 0.04, -45.0) == b"not a wav"
