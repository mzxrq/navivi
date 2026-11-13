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


def test_english_is_voiced_in_whole_sentences_japanese_as_before():
    from services import tuning
    from services.tts.ttsengine import chunk_limits, split_text_for_tts

    en = ("Take a moment to explore ancient shrines and temples nestled amid beautiful natural scenery. "
          "Welcome to “The Katsuragi Trail,” a historic land where ancient beliefs still thrive today.")
    assert all(c.strip().endswith(".") for c in split_text_for_tts(en, *chunk_limits(en)))
    assert chunk_limits("西へ歩きます。") == (tuning.TTS_MAX_CHUNK_CHARS, tuning.TTS_MIN_CHUNK_CHARS)


def test_english_clips_cut_the_old_way_are_remade(tmp_path, monkeypatch):
    kokoro = {"voice": "af_heart", "sha256": None, "speed": 1.0, "caption": None, "engine": "kokoro"}
    monkeypatch.setattr(audio_step, "_client_fingerprint", lambda client: dict(kokoro))
    old = _clip(tmp_path, "Walk west for a while.", kokoro)
    assert not audio_step._voice_matches(old, None)
    audio_step._write_voice_note(old, None)
    assert audio_step._voice_matches(old, None)


def test_a_new_high_low_pattern_remakes_only_the_lines_with_that_word(tmp_path, monkeypatch):
    from services.tts import pitch_accent

    monkeypatch.setattr(audio_step, "_client_fingerprint", lambda client: dict(QWEN))
    monkeypatch.setattr(pitch_accent, "_patterns", {"カツラギ": "LHHH"})
    with_word = _clip(tmp_path, "カツラギへ歩きます。", QWEN)
    audio_step._write_voice_note(with_word, None)
    assert audio_step._voice_matches(with_word, None)
    other = tmp_path / "other"
    other.mkdir()
    without = _clip(other, "西へ歩きます。", QWEN)
    monkeypatch.setattr(pitch_accent, "_patterns", {"カツラギ": "HLLL"})
    assert not audio_step._voice_matches(with_word, None)
    assert audio_step._voice_matches(without, None)


def test_kept_sentences_are_not_reused_after_a_pattern_change(tmp_path, monkeypatch):
    import asyncio

    from services.tts import pitch_accent

    monkeypatch.setattr(audio_step, "_client_fingerprint", lambda client: dict(QWEN))
    seen = []

    class Client:
        bypass_cache, pieces_dir, pieces_voice, redo_texts = False, None, None, frozenset()

        async def generate_speech(self, text, output_filename):
            seen.append(self.pieces_voice)
            return output_filename

    for pattern in ("LHHH", "HLLL"):
        monkeypatch.setattr(pitch_accent, "_patterns", {"カツラギ": pattern})
        asyncio.run(audio_step._speak(Client(), "カツラギへ。", "a.wav", tmp_path))
    monkeypatch.setattr(pitch_accent, "_patterns", {})
    asyncio.run(audio_step._speak(Client(), "西へ。", "b.wav", tmp_path))
    assert seen[0]["pitch"] == [["カツラギ", "LHHH"]] and seen[1]["pitch"] == [["カツラギ", "HLLL"]]
    assert seen[2] == QWEN  # no patterns: the fingerprint kept sentences were saved under before
