"""A TTS take that stops mid-word is retaken, then spoken in halves."""

import asyncio
import io
import wave

import numpy as np
import pytest

from services import tuning
from services.tts.artifacts import cut_off_ratio
from services.tts.ttsengine import KokoroTTSClient, make_tts_client

SR = 24000


def _wav(signal) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(signal, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


def _speech(seconds, cut=False):
    t = np.arange(int(SR * seconds)) / SR
    tone = 0.3 * np.sin(2 * np.pi * 220 * t)
    if not cut:
        fade = int(SR * 0.25)
        tone[-fade:] *= np.linspace(1.0, 0.0, fade)
    return np.concatenate([tone, np.zeros(int(SR * 0.25))])  # the server's end pad


GOOD, CUT = _wav(_speech(2.0)), _wav(_speech(2.0, cut=True))


def test_a_faded_ending_is_fine_and_an_abrupt_one_is_cut():
    assert cut_off_ratio(GOOD) <= tuning.TTS_CUTOFF_RATIO
    assert cut_off_ratio(CUT) > tuning.TTS_CUTOFF_RATIO


def test_unreadable_audio_counts_as_fine():
    assert cut_off_ratio(b"not a wav") == 0.0


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVIVI_CACHE_DIR", str(tmp_path / "cache"))
    c = make_tts_client({"tts": {"engine": "kokoro"}}, tmp_path / "out")
    c.calls = []
    return c


def _serve(monkeypatch, client, answer):
    async def call_api(self, text):
        client.calls.append((text, self.bypass_cache))
        return answer(text, len(client.calls))

    monkeypatch.setattr(KokoroTTSClient, "call_api", call_api)


def test_a_cut_take_is_retaken_without_the_cache(client, monkeypatch):
    _serve(monkeypatch, client, lambda text, n: CUT if n == 1 else GOOD)
    assert asyncio.run(client._speak_chunk("今日の旅は、ここまでです。")) == [GOOD]
    assert [bypass for _, bypass in client.calls] == [False, True]
    assert client.bypass_cache is False


def test_a_chunk_that_keeps_cutting_is_spoken_in_halves(client, monkeypatch):
    whole = "ここは雄大な景色が広がる場所です。次は南東へ。52分ほど歩くと、札立山です。次は南へ。"
    _serve(monkeypatch, client, lambda text, n: CUT if text == whole else GOOD)
    takes = asyncio.run(client._speak_chunk(whole))
    assert len(takes) > 1 and all(t == GOOD for t in takes)
    assert "".join(text for text, _ in client.calls[tuning.TTS_CUTOFF_RETAKES + 1:]) == whole


def test_the_least_cut_take_is_kept_when_nothing_helps(client, monkeypatch):
    _serve(monkeypatch, client, lambda text, n: CUT)
    assert asyncio.run(client._speak_chunk("次は南へ。")) == [CUT]
    assert len(client.calls) == tuning.TTS_CUTOFF_RETAKES + 1


def test_generate_speech_writes_the_retaken_audio(client, monkeypatch, tmp_path):
    _serve(monkeypatch, client, lambda text, n: CUT if n == 1 else GOOD)
    path = asyncio.run(client.generate_speech("今日の旅は、ここまでです。", "a.wav"))
    assert cut_off_ratio(open(path, "rb").read()) <= tuning.TTS_CUTOFF_RATIO


@pytest.mark.parametrize("engine, cleaned", [("irodori", True), ("qwen3", False), ("kokoro", False)])
def test_only_the_listed_engines_remove_stray_bursts(tmp_path, monkeypatch, engine, cleaned):
    from services.tts import ttsengine

    monkeypatch.setenv("NAVIVI_CACHE_DIR", str(tmp_path / "cache"))
    c = make_tts_client({"tts": {"engine": engine}}, tmp_path / "out")
    seen = []
    monkeypatch.setattr(ttsengine, "remove_stray_bursts", lambda path: seen.append(path) or [])

    async def call_api(self, text):
        return GOOD

    monkeypatch.setattr(type(c), "call_api", call_api)
    asyncio.run(c.generate_speech("今日の旅は、ここまでです。", "a.wav"))
    assert bool(seen) is cleaned
