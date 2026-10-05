import asyncio
import json
import wave
from pathlib import Path

import pytest

from services import tuning
from services.cli.voice_commands import run_voice_action
from services.tts import voices
from services.tts.ttsengine import TTSConfig, tts_config_from_settings
from services.vdoprocessing.videopipeline import audio_step


@pytest.fixture
def lib(tmp_path):
    root = tmp_path / "voices"
    root.mkdir()
    voices.set_voices_dir(root)
    voices.set_stock_dir(tmp_path / "no-stock-voices")  # the real bundle must not leak into tests
    yield root
    voices.set_voices_dir(None)
    voices.set_stock_dir(None)


def _wav(path: Path, seconds: float = 1.0, level: int = 16) -> Path:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(level.to_bytes(2, "little") * int(8000 * seconds))
    return path


def test_add_list_delete(lib, tmp_path):
    src = _wav(tmp_path / "narrator.wav")
    added = voices.add_voice(str(src), "alice")
    assert added["id"] == "alice" and (lib / "alice.wav").is_file()
    ids = [v["id"] for v in voices.list_voices()]
    assert ids == ["none", "alice"]
    assert voices.delete_voice("alice") is True
    assert voices.delete_voice("alice") is False


def test_add_defaults_id_to_filename_stem(lib, tmp_path):
    voices.add_voice(str(_wav(tmp_path / "bob_1.wav")))
    assert voices.voice_exists("bob_1")


@pytest.mark.parametrize("bad_id", ["日本語", "a b", "none", "../x"])
def test_add_rejects_bad_ids(lib, tmp_path, bad_id):
    src = _wav(tmp_path / "x.wav")
    with pytest.raises(ValueError):
        voices.add_voice(str(src), bad_id)


def test_add_rejects_extension_and_empty(lib, tmp_path):
    txt = tmp_path / "a.txt"
    txt.write_text("hi")
    with pytest.raises(ValueError):
        voices.add_voice(str(txt), "a")
    empty = tmp_path / "e.wav"
    empty.write_bytes(b"")
    with pytest.raises(ValueError):
        voices.add_voice(str(empty), "e")


def test_add_duplicate_needs_replace(lib, tmp_path):
    voices.add_voice(str(_wav(tmp_path / "a.wav")), "carol")
    with pytest.raises(FileExistsError):
        voices.add_voice(str(_wav(tmp_path / "b.wav")), "carol")
    flac = tmp_path / "b.flac"
    flac.write_bytes(b"not really flac")
    voices.add_voice(str(flac), "carol", replace=True)
    assert sorted(p.name for p in lib.iterdir()) == ["carol.flac"]


def test_none_is_builtin(lib):
    assert voices.voice_exists("none")
    with pytest.raises(ValueError):
        voices.delete_voice("none")


def test_config_from_settings(lib, tmp_path):
    voices.add_voice(str(_wav(tmp_path / "d.wav")), "dave")
    cfg = tts_config_from_settings({"tts": {"voice": "dave", "speed": 1.0}, "hardware_spec_override": "low"})
    assert (cfg.voice, cfg.speed, cfg.hardware_override) == ("dave", 1.0, "low")


def test_config_falls_back_when_voice_missing_or_speed_bad(lib):
    cfg = tts_config_from_settings({"tts": {"voice": "ghost", "speed": 99}})
    assert (cfg.voice, cfg.speed, cfg.hardware_override) == (tuning.TTS_VOICE, tuning.TTS_SPEED, None)
    assert tts_config_from_settings(None).voice == tuning.TTS_VOICE


class _Client:
    def __init__(self, voice, speed, caption=None):
        self.config = TTSConfig(voice=voice, speed=speed, caption=caption)


def test_legacy_clip_counts_as_old_default(lib, tmp_path):
    clip = _wav(tmp_path / "clip.wav")
    voices.add_voice(str(_wav(tmp_path / "t.wav")), tuning.TTS_VOICE)
    assert audio_step._voice_matches(clip, _Client(tuning.TTS_VOICE, tuning.TTS_SPEED))
    assert not audio_step._voice_matches(clip, _Client(tuning.TTS_VOICE, tuning.TTS_SPEED + 0.5))
    assert not audio_step._voice_matches(clip, _Client(tuning.TTS_VOICE, tuning.TTS_SPEED, "明るく"))


def test_caption_in_payload_and_settings_override():
    assert TTSConfig(caption="明るく").to_payload("x")["caption"] == "明るく"
    assert "caption" not in TTSConfig(caption=None).to_payload("x")
    assert tts_config_from_settings({"tts": {"caption": "静かに"}}).caption == "静かに"
    assert tts_config_from_settings({"tts": {"caption": ""}}).caption is None
    assert tts_config_from_settings({}).caption == (tuning.TTS_CAPTION or None)


def test_voice_change_or_new_reference_invalidates(lib, tmp_path):
    voices.add_voice(str(_wav(tmp_path / "e.wav")), "erin")
    voices.add_voice(str(_wav(tmp_path / "f.wav")), "frank")
    clip = _wav(tmp_path / "clip.wav")
    erin = _Client("erin", 1.25)
    audio_step._write_voice_note(clip, erin)
    assert audio_step._voice_matches(clip, _Client("erin", 1.25))
    assert not audio_step._voice_matches(clip, _Client("frank", 1.25))
    # Same id, different reference audio.
    voices.add_voice(str(_wav(tmp_path / "e2.wav", level=900)), "erin", replace=True)
    assert not audio_step._voice_matches(clip, _Client("erin", 1.25))


def test_waypoint_audio_regenerates_on_voice_change(lib, tmp_path):
    voices.add_voice(str(_wav(tmp_path / "g.wav")), "gina")
    out = tmp_path / "audio"
    out.mkdir()
    calls = []

    class FakeClient(_Client):
        async def generate_speech(self, text, output_filename):
            calls.append(output_filename)
            return str(_wav(out / output_filename, 0.5, level=1000))

    class FakeProcessor:
        def analyze_pauses(self, path):
            return {"duration_seconds": 0.5, "pauses": []}

    wp = {"label": "A", "arrivingNarration": "こんにちは。"}
    run = lambda c: asyncio.run(audio_step.generate_waypoint_audio(wp, 0, c, FakeProcessor(), out))
    run(FakeClient("gina", 1.25))
    run(FakeClient("gina", 1.25))
    assert len(calls) == 1
    note = json.loads((out / (calls[0] + ".voice.json")).read_text(encoding="utf-8"))
    assert note["voice"] == "gina"
    run(FakeClient("none", 1.25))
    assert len(calls) == 2


def test_all_narration_speaks_the_pronunciation_dictionary(lib, tmp_path):
    out = tmp_path / "audio"
    out.mkdir()
    spoken = []

    class FakeClient(_Client):
        async def generate_speech(self, text, output_filename):
            spoken.append(text)
            return str(_wav(out / output_filename, 0.5, level=1000))

    class FakeProcessor:
        def analyze_pauses(self, path):
            return {"duration_seconds": 0.5, "pauses": []}

    wp = {"label": "A", "arrivingNarration": "孝子駅へ。", "attractionNarration": "孝子駅です。"}
    d = [{"word": "孝子", "reading": "きょうし"}]
    c = FakeClient("none", 1.25)
    leg = lambda p: asyncio.run(audio_step.generate_waypoint_audio(wp, 0, c, FakeProcessor(), out, pronunciation_dict=p))
    att = lambda p: asyncio.run(audio_step.generate_attraction_audio_for_waypoint(wp, 0, c, FakeProcessor(), out, pronunciation_dict=p))
    leg([]), att([])
    leg(d), att(d)
    assert all("孝子" not in s and "きょうし" in s for s in spoken[-2:])
    leg(d), att(d)
    assert len(spoken) == 4  # unchanged dictionary reuses the audio
    assert "孝子" in leg(d)["text"]  # subtitles keep the kanji


def test_cli_actions_return_json_errors(lib, tmp_path):
    assert run_voice_action("tts_voices_list", {})["voices"][0]["id"] == "none"
    res = run_voice_action("tts_voice_add", {"path": str(tmp_path / "missing.wav"), "id": "x"})
    assert res["success"] is False and "not found" in res["error"]
    res = run_voice_action("tts_voice_delete", {"id": "nobody"})
    assert res["success"] is False
    assert run_voice_action("tts_voice_add", {})["success"] is False


class TestBundledVoices:
    @pytest.fixture
    def stock(self, lib, tmp_path):
        stock = tmp_path / "stock"
        stock.mkdir()
        _wav(stock / "amitaro.wav")
        _wav(stock / "test1.wav")
        (stock / "notes.txt").write_text("not a voice")
        voices.set_stock_dir(stock)
        return stock

    def test_a_fresh_voice_library_gets_the_bundled_voices(self, lib, stock):
        listed = [v["id"] for v in voices.list_voices()]
        assert {"amitaro", "test1"} <= set(listed)
        assert voices.voice_file("test1") is not None
        assert not (lib / "notes.txt").exists()

    def test_a_voice_the_user_deleted_does_not_come_back(self, lib, stock):
        voices.list_voices()
        assert voices.delete_voice("amitaro") is True
        assert "amitaro" not in [v["id"] for v in voices.list_voices()]
        assert voices.voice_file("amitaro") is None

    def test_the_users_own_voice_with_the_same_name_is_left_alone(self, lib, stock):
        _wav(lib / "test1.wav", seconds=2.0)
        mine = (lib / "test1.wav").read_bytes()
        voices.list_voices()
        assert (lib / "test1.wav").read_bytes() == mine

    def test_a_voice_added_to_the_bundle_later_arrives_on_the_next_look(self, lib, stock):
        voices.list_voices()
        _wav(stock / "newone.wav")
        assert "newone" in [v["id"] for v in voices.list_voices()]

    def test_without_a_bundle_nothing_happens(self, lib):
        assert voices.sync_stock_voices() == []
        assert [v["id"] for v in voices.list_voices()] == ["none"]
