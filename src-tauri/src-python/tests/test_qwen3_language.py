"""Qwen3 reads each line in its own language, and English clips voiced as Japanese are remade."""

import json

from services.tts.ttsengine import qwen3_language
from services.vdoprocessing.videopipeline import audio_step

QWEN = {"voice": "jvs004", "sha256": None, "speed": 1.0, "caption": None, "engine": "qwen3"}


def test_language_comes_from_the_text():
    assert qwen3_language("葛木水分神社に着きます。") == "Japanese"
    assert qwen3_language("Walk west from Teradabashi bus stop.") == "English"


def _clip(tmp_path, text, note):
    wav = tmp_path / "02_waypoint_02_A.wav"
    wav.write_bytes(b"x")
    (tmp_path / "02_waypoint_02_A.wav.txt").write_text(text, encoding="utf-8")
    if note is not None:
        audio_step._voice_note_path(wav).write_text(json.dumps(note), encoding="utf-8")
    return wav


def test_english_voiced_as_japanese_is_remade(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_step, "_client_fingerprint", lambda client: dict(QWEN))
    old = _clip(tmp_path, "Walk west for a while.", QWEN)
    assert not audio_step._voice_matches(old, None)
    audio_step._write_voice_note(old, None)  # what a new take records
    assert audio_step._voice_matches(old, None)


def test_japanese_clips_stay_valid(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_step, "_client_fingerprint", lambda client: dict(QWEN))
    assert audio_step._voice_matches(_clip(tmp_path, "西へ歩きます。", QWEN), None)
