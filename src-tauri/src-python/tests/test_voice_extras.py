"""Voice tab extras: the speaking-style caption in the voice fingerprint, and the spoken-line cache actions."""

import wave

import pytest

from services import tuning
from services.cli import voice_commands
from services.tts import phrase_cache, voices
from services.tts.ttsengine import tts_config_from_settings


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVIVI_CACHE_DIR", str(tmp_path / "cache"))
    return tmp_path / "cache" / "tts"


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


def _fingerprint(settings):
    config = tts_config_from_settings({"tts": settings})
    return voices.voice_fingerprint(config.voice, config.speed, config.caption, config.engine)


class TestCaptionFingerprint:
    def test_a_project_that_never_set_the_caption_gets_the_default_in_its_fingerprint(self, voice_lib):
        before = _fingerprint({"voice": "alice"})
        assert before["caption"] == tuning.TTS_CAPTION
        # what the Reset button does: the key is dropped, so a saved project is unchanged
        assert voices.fingerprints_match(before, _fingerprint({"voice": "alice", "caption": tuning.TTS_CAPTION}))

    def test_changing_the_caption_makes_the_narration_out_of_date(self, voice_lib):
        stored = _fingerprint({"voice": "alice"})
        assert not voices.fingerprints_match(stored, _fingerprint({"voice": "alice", "caption": "落ち着いた、静かな話し方。"}))

    def test_an_empty_caption_is_no_style_and_differs_from_the_default(self, voice_lib):
        stored = _fingerprint({"voice": "alice"})
        none = _fingerprint({"voice": "alice", "caption": "  "})
        assert none["caption"] is None
        assert not voices.fingerprints_match(stored, none)

    def test_only_the_natural_voice_has_a_style(self, voice_lib):
        assert _fingerprint({"voice": "alice", "engine": "qwen3", "caption": "calm"})["caption"] is None


class TestCacheActions:
    def test_the_actions_are_registered(self):
        assert {"tts_cache_info", "tts_cache_clear"} <= set(voice_commands.VOICE_ACTIONS)

    def test_info_counts_files_and_bytes(self, cache_dir):
        empty = voice_commands.run_voice_action("tts_cache_info", {})
        assert empty == {"success": True, "files": 0, "bytes": 0, "max_bytes": tuning.TTS_CACHE_MAX_MB * 1024 * 1024}
        phrase_cache.put("a", b"RIFF\x24\x00\x00\x00WAVEdata")
        phrase_cache.put("b", b"RIFF\x24\x00\x00\x00WAVEdata" + b"\0" * 100)
        info = voice_commands.run_voice_action("tts_cache_info", {})
        assert (info["files"], info["bytes"]) == (2, 16 + 16 + 100)

    def test_clear_removes_every_line_and_reports_it(self, cache_dir):
        phrase_cache.put("a", b"RIFF\x24\x00\x00\x00WAVEdata")
        (cache_dir / "half.part").write_bytes(b"xx")
        (cache_dir / "keep.txt").write_text("not ours")
        out = voice_commands.run_voice_action("tts_cache_clear", {})
        assert out["success"] and out["files"] == 2 and out["bytes"] == 18
        assert phrase_cache.get("a") is None
        assert (cache_dir / "keep.txt").exists()
        assert voice_commands.run_voice_action("tts_cache_info", {})["files"] == 0

    def test_clear_with_no_cache_folder_is_fine(self, cache_dir):
        assert voice_commands.run_voice_action("tts_cache_clear", {}) == {"success": True, "files": 0, "bytes": 0}


class TestFrontendMirror:
    def test_the_voice_tab_default_style_and_speed_range_match_the_engine(self):
        from pathlib import Path

        src = (Path(__file__).resolve().parents[3] / "src" / "components" / "ui" / "voiceOptions.ts").read_text(encoding="utf-8")
        assert f'DEFAULT_TTS_CAPTION = "{tuning.TTS_CAPTION}"' in src
        assert f"min: {tuning.TTS_MIN_SPEED}, max: {int(tuning.TTS_MAX_SPEED)}," in src
