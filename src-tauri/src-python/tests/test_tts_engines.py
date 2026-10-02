"""The narration engine switch: Irodori (clones a voice, slow) or Kokoro (fixed Japanese voices, fast)."""

import asyncio
import io
import wave

import pytest

from services import tuning
from services.cli import voice_commands
from services.tts import phrase_cache, ttsengine, voices
from services.tts.ttsengine import IrodoriTTSClient, KokoroTTSClient, make_tts_client, tts_config_from_settings


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


class TestConfig:
    def test_irodori_is_the_default(self, voice_lib):
        config = tts_config_from_settings({"tts": {"voice": "alice"}})
        assert (config.engine, config.voice) == ("irodori", "alice")

    def test_kokoro_uses_its_own_voice_setting_and_defaults_to_tebukuro(self):
        config = tts_config_from_settings({"tts": {"engine": "kokoro", "voice": "alice"}})
        assert (config.engine, config.voice, config.model, config.caption) == ("kokoro", "jf_tebukuro", "kokoro", None)
        assert tts_config_from_settings({"tts": {"engine": "kokoro", "kokoro_voice": "jm_kumo"}}).voice == "jm_kumo"

    def test_the_irodori_voice_is_kept_while_kokoro_is_chosen(self, voice_lib):
        settings = {"tts": {"engine": "irodori", "voice": "alice", "kokoro_voice": "jf_alpha"}}
        assert tts_config_from_settings(settings).voice == "alice"
        settings["tts"]["engine"] = "kokoro"
        assert tts_config_from_settings(settings).voice == "jf_alpha"

    def test_unknown_engine_or_voice_falls_back(self, voice_lib):
        assert tts_config_from_settings({"tts": {"engine": "nope", "voice": "alice"}}).engine == "irodori"
        assert tts_config_from_settings({"tts": {"engine": "kokoro", "kokoro_voice": "zz"}}).voice == tuning.KOKORO_VOICE

    def test_speed_applies_to_both(self):
        assert tts_config_from_settings({"tts": {"engine": "kokoro", "speed": 1.4}}).speed == 1.4
        assert tts_config_from_settings({"tts": {"engine": "kokoro", "speed": 99}}).speed == tuning.TTS_SPEED


class TestFactory:
    def test_picks_the_client_for_the_engine(self, tmp_path, voice_lib):
        assert type(make_tts_client({"tts": {"voice": "alice"}}, tmp_path / "a")) is IrodoriTTSClient
        kokoro = make_tts_client({"tts": {"engine": "kokoro"}}, tmp_path / "b")
        assert type(kokoro) is KokoroTTSClient
        assert kokoro.base_url.endswith(f":{tuning.KOKORO_PORT}/v1/audio/speech")

    def test_the_two_clients_track_their_own_server_process(self):
        assert KokoroTTSClient._server_process is None
        assert KokoroTTSClient._PIDFILE != IrodoriTTSClient._PIDFILE
        assert KokoroTTSClient._SERVER_DIR != IrodoriTTSClient._SERVER_DIR
        assert KokoroTTSClient._PROCESS_MARKER != IrodoriTTSClient._PROCESS_MARKER

    def test_stop_all_stops_both(self, monkeypatch):
        stopped = []
        monkeypatch.setattr(IrodoriTTSClient, "stop_server", classmethod(lambda cls: stopped.append("irodori")))
        monkeypatch.setattr(KokoroTTSClient, "stop_server", classmethod(lambda cls: stopped.append("kokoro")))
        ttsengine.stop_all_tts_servers()
        assert sorted(stopped) == ["irodori", "kokoro"]


class TestFingerprint:
    def test_switching_engine_makes_finished_narration_stale(self, voice_lib):
        irodori = voices.voice_fingerprint("alice", 1.0, None)
        kokoro = voices.voice_fingerprint("jf_tebukuro", 1.0, None, engine="kokoro")
        assert voices.fingerprints_match(irodori, irodori)
        assert voices.fingerprints_match(kokoro, kokoro)
        assert not voices.fingerprints_match(irodori, kokoro)
        assert not voices.fingerprints_match(kokoro, irodori)

    def test_a_clip_made_before_engines_existed_counts_as_irodori(self, voice_lib):
        legacy = {"voice": "alice", "sha256": voices._sha256(voice_lib / "alice.wav"), "speed": 1.0, "caption": None}
        assert voices.fingerprints_match(legacy, voices.voice_fingerprint("alice", 1.0, None))
        assert not voices.fingerprints_match(legacy, voices.voice_fingerprint("alice", 1.0, None, engine="kokoro"))

    def test_kokoro_voice_and_speed_changes_are_noticed(self):
        a = voices.voice_fingerprint("jf_tebukuro", 1.0, None, engine="kokoro")
        assert not voices.fingerprints_match(a, voices.voice_fingerprint("jf_alpha", 1.0, None, engine="kokoro"))
        assert not voices.fingerprints_match(a, voices.voice_fingerprint("jf_tebukuro", 1.3, None, engine="kokoro"))


class TestKokoroClient:
    @pytest.fixture
    def client(self, tmp_path, cache_dir, monkeypatch):
        sent = []

        async def post(self, payload):
            sent.append(payload)
            return b"WAV-" + payload["input"].encode("utf-8")

        monkeypatch.setattr(KokoroTTSClient, "_post_speech", post)
        c = make_tts_client({"tts": {"engine": "kokoro", "kokoro_voice": "jf_alpha", "speed": 1.2}}, tmp_path / "out")
        c.sent = sent
        return c

    def test_sends_text_voice_and_speed(self, client):
        assert asyncio.run(client.call_api("こんにちは")) == "WAV-こんにちは".encode("utf-8")
        assert client.sent == [{"input": "こんにちは", "voice": "jf_alpha", "speed": 1.2}]

    def test_a_repeated_line_comes_from_the_shared_cache(self, client):
        asyncio.run(client.call_api("お疲れ様です"))
        asyncio.run(client.call_api("お疲れ様です"))
        assert len(client.sent) == 1

    def test_another_voice_or_speed_is_not_a_hit(self, client, tmp_path):
        asyncio.run(client.call_api("お疲れ様です"))
        other = make_tts_client({"tts": {"engine": "kokoro", "kokoro_voice": "jm_kumo", "speed": 1.2}}, tmp_path / "o2")
        other.sent = client.sent
        asyncio.run(other.call_api("お疲れ様です"))
        assert len(client.sent) == 2

    def test_its_lines_never_collide_with_irodoris_in_the_cache(self, client, tmp_path, voice_lib, monkeypatch):
        irodori = make_tts_client({"tts": {"voice": "alice"}}, tmp_path / "i")
        monkeypatch.setattr(ttsengine, "ensure_reference_latent", lambda voice: None)
        hits = []

        async def post(self, payload):
            hits.append("irodori")
            return b"IRODORI"

        monkeypatch.setattr(IrodoriTTSClient, "_post_speech", post)
        asyncio.run(client.call_api("同じ文"))
        assert asyncio.run(irodori.call_api("同じ文")) == b"IRODORI"

    def test_it_does_not_look_for_a_voice_file(self, client):
        assert client._voice_sha256() is None

    def test_starting_without_setup_explains_what_to_do(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(KokoroTTSClient, "_SERVER_VENV_PYTHON", tmp_path / "missing" / "python.exe")
        assert "Set up fast voice" in client._missing_server_message()


class TestVoiceActions:
    def test_engines_lists_kokoros_voices_with_tebukuro_as_the_default(self, monkeypatch):
        monkeypatch.setattr(KokoroTTSClient, "is_ready", classmethod(lambda cls: True))
        result = voice_commands.run_voice_action("tts_engines", {})
        assert result["success"] and result["kokoro"]["ready"] is True
        assert result["kokoro"]["default_voice"] == "jf_tebukuro"
        assert [v["id"] for v in result["kokoro"]["voices"]] == list(tuning.KOKORO_VOICES)

    def test_engines_says_when_it_is_not_set_up(self, monkeypatch):
        monkeypatch.setattr(KokoroTTSClient, "is_ready", classmethod(lambda cls: False))
        assert voice_commands.run_voice_action("tts_engines", {})["kokoro"]["ready"] is False

    def test_the_new_actions_are_routed(self):
        assert "tts_engines" in voice_commands.VOICE_ACTIONS and "tts_install_kokoro" in voice_commands.VOICE_ACTIONS

    def test_a_kokoro_preview_goes_to_the_kokoro_client(self, monkeypatch, tmp_path):
        seen = {}

        async def speak(self, text, filename=None):
            seen.update(type=type(self).__name__, voice=self.config.voice, speed=self.config.speed, filename=filename)
            return str(tmp_path / "x.wav")

        monkeypatch.setattr(KokoroTTSClient, "generate_speech", speak)
        result = voice_commands.run_voice_action("tts_voice_preview", {"engine": "kokoro", "voice": "jf_nezumi", "speed": 1.1})
        assert result["success"], result
        assert seen == {"type": "KokoroTTSClient", "voice": "jf_nezumi", "speed": 1.1, "filename": "kokoro_jf_nezumi.wav"}

    def test_an_irodori_preview_still_needs_the_voice_file(self, voice_lib):
        result = voice_commands.run_voice_action("tts_voice_preview", {"voice": "nobody"})
        assert result["success"] is False and "nobody" in result["error"]


class TestServerWav:
    def test_the_worker_script_has_no_navivi_imports_so_the_kokoro_venv_can_run_it(self):
        source = (ttsengine.Path(ttsengine.__file__).with_name("kokoro_server.py")).read_text(encoding="utf-8")
        assert "from services" not in source and "import services" not in source
