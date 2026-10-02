"""Narration speed on a CPU: quality presets, the cross-project phrase cache, the saved reference latent."""

import asyncio
import os
import wave
from pathlib import Path

import pytest

from services import tuning
from services.tts import phrase_cache, voices
from services.tts import ttsengine
from services.tts.ttsengine import IrodoriTTSClient, TTSConfig, ensure_reference_latent, tts_config_from_settings


@pytest.fixture
def voice_lib(tmp_path):
    root = tmp_path / "voices"
    root.mkdir()
    with wave.open(str(root / "alice.wav"), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes((16).to_bytes(2, "little") * 8000 * 4)
    voices.set_voices_dir(root)
    yield root
    voices.set_voices_dir(None)


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVIVI_CACHE_DIR", str(tmp_path / "cache"))
    return tmp_path / "cache" / "tts"


class TestQualityPresets:
    def test_each_preset_sets_the_sampling_steps(self):
        assert TTSConfig(quality="fast").to_payload("hi")["irodori"] == {"num_steps": 16}
        assert TTSConfig(quality="balanced").to_payload("hi")["irodori"] == {"num_steps": 24}
        assert TTSConfig(quality="best").to_payload("hi")["irodori"] == {"num_steps": 40}

    def test_explicit_options_win_over_the_preset(self):
        payload = TTSConfig(quality="fast", extra_options={"num_steps": 8, "seed": 3}).to_payload("hi")
        assert payload["irodori"] == {"num_steps": 8, "seed": 3}

    def test_settings_pick_the_preset_and_a_bad_name_falls_back(self, voice_lib):
        assert tts_config_from_settings({"tts": {"voice": "alice", "quality": "fast"}}).quality == "fast"
        assert tts_config_from_settings({"tts": {"voice": "alice", "quality": "ultra"}}).quality == tuning.TTS_QUALITY_DEFAULT
        assert tts_config_from_settings({}).quality == tuning.TTS_QUALITY_DEFAULT


class TestPhraseCache:
    def test_key_follows_the_request_and_the_voice_file(self):
        base = TTSConfig(voice="alice").to_payload("こんにちは")
        key = phrase_cache.cache_key(base, "aaa")
        assert key == phrase_cache.cache_key(dict(base), "aaa")
        assert key != phrase_cache.cache_key(TTSConfig(voice="alice").to_payload("さようなら"), "aaa")
        assert key != phrase_cache.cache_key(base, "bbb")
        assert key != phrase_cache.cache_key(TTSConfig(voice="alice", quality="fast").to_payload("こんにちは"), "aaa")
        assert key != phrase_cache.cache_key(TTSConfig(voice="alice", speed=1.2).to_payload("こんにちは"), "aaa")

    def test_round_trip_and_miss(self, cache_dir):
        assert phrase_cache.get("nope") is None
        phrase_cache.put("k1", b"RIFFdata")
        assert phrase_cache.get("k1") == b"RIFFdata"
        assert (cache_dir / "k1.wav").exists()

    def test_empty_audio_is_never_cached(self, cache_dir):
        phrase_cache.put("k2", b"")
        assert phrase_cache.get("k2") is None

    def test_oldest_lines_go_first_and_use_keeps_a_line(self, cache_dir):
        for i, name in enumerate(("old", "mid", "new")):
            phrase_cache.put(name, b"x" * 400_000)
            os.utime(cache_dir / f"{name}.wav", (1_000 + i, 1_000 + i))
        phrase_cache.get("old")  # touched: now the newest
        phrase_cache.prune(max_mb=1)  # room for two of the three
        left = sorted(p.stem for p in cache_dir.glob("*.wav"))
        assert left == ["new", "old"] or left == ["mid", "old"]
        assert "old" in left


class TestCallApi:
    @pytest.fixture
    def client(self, tmp_path, voice_lib, cache_dir, monkeypatch):
        sent = []

        async def post(self, payload):
            sent.append(payload)
            return b"AUDIO-" + payload["input"].encode("utf-8")

        monkeypatch.setattr(IrodoriTTSClient, "_post_speech", post)
        monkeypatch.setattr(ttsengine, "ensure_reference_latent", lambda voice: None)
        c = IrodoriTTSClient(output_dir=tmp_path / "out", config=TTSConfig(voice="alice", quality="fast"))
        c.sent = sent
        return c

    def test_a_repeated_line_is_synthesized_once(self, client):
        assert asyncio.run(client.call_api("お疲れ様です")) == "AUDIO-お疲れ様です".encode("utf-8")
        assert asyncio.run(client.call_api("お疲れ様です")) == "AUDIO-お疲れ様です".encode("utf-8")
        assert len(client.sent) == 1

    def test_another_line_or_voice_file_is_not_a_hit(self, client, voice_lib):
        asyncio.run(client.call_api("一"))
        asyncio.run(client.call_api("二"))
        assert len(client.sent) == 2
        (voice_lib / "alice.wav").write_bytes((voice_lib / "alice.wav").read_bytes() + b"\0\0")  # a changed voice file
        asyncio.run(client.call_api("一"))
        assert len(client.sent) == 3

    def test_the_saved_latent_is_sent_but_is_not_part_of_the_cache_key(self, client, monkeypatch, tmp_path):
        first = tmp_path / "a.pt"
        monkeypatch.setattr(ttsengine, "ensure_reference_latent", lambda voice: first)
        asyncio.run(client.call_api("一"))
        assert client.sent[0]["irodori"] == {"num_steps": 16, "ref_latent": str(first)}
        monkeypatch.setattr(ttsengine, "ensure_reference_latent", lambda voice: tmp_path / "b.pt")
        asyncio.run(client.call_api("一"))  # same line, the latent file moved: still a cache hit
        assert len(client.sent) == 1


class TestReferenceLatent:
    def test_without_the_server_python_it_quietly_returns_nothing(self, voice_lib, monkeypatch, tmp_path):
        monkeypatch.setattr(IrodoriTTSClient, "_SERVER_VENV_PYTHON", tmp_path / "missing" / "python.exe")
        assert ensure_reference_latent("alice") is None

    def test_an_unknown_voice_returns_nothing(self, voice_lib):
        assert ensure_reference_latent("nobody") is None

    def test_an_existing_latent_is_reused_without_running_anything(self, voice_lib, monkeypatch, tmp_path):
        fake_python = tmp_path / "python.exe"
        fake_python.write_bytes(b"")
        monkeypatch.setattr(IrodoriTTSClient, "_SERVER_VENV_PYTHON", fake_python)
        sha = voices._sha256(voice_lib / "alice.wav")[:12]
        latent = voice_lib / ".latents" / f"alice-{sha}.pt"
        latent.parent.mkdir()
        latent.write_bytes(b"x")

        def boom(*a, **k):
            raise AssertionError("must not run the encoder again")

        monkeypatch.setattr(ttsengine.subprocess, "run", boom)
        assert ensure_reference_latent("alice") == latent

    def test_a_failing_encoder_falls_back_and_is_not_retried(self, voice_lib, monkeypatch, tmp_path):
        fake_python = tmp_path / "python.exe"
        fake_python.write_bytes(b"")
        monkeypatch.setattr(IrodoriTTSClient, "_SERVER_VENV_PYTHON", fake_python)
        monkeypatch.setattr(ttsengine, "_latent_failures", set())
        calls = []

        def fail(*a, **k):
            calls.append(1)
            return type("R", (), {"returncode": 1, "stderr": "boom"})()

        monkeypatch.setattr(ttsengine.subprocess, "run", fail)
        assert ensure_reference_latent("alice") is None
        assert ensure_reference_latent("alice") is None
        assert len(calls) == 1
