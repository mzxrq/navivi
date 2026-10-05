"""The narration engine switch: Irodori (clones a voice, slow) or Kokoro (fixed Japanese voices, fast)."""

import asyncio
import io
import wave

import pytest

from services import tuning
from services.cli import voice_commands
from services.tts import phrase_cache, ttsengine, voices
from services.tts.ttsengine import (
    IrodoriTTSClient, KokoroTTSClient, Qwen3TTSClient, _atempo_filter, apply_speed, make_tts_client, tts_config_from_settings,
)


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

    def test_stop_all_stops_every_engine(self, monkeypatch):
        stopped = []
        for cls, name in ((IrodoriTTSClient, "irodori"), (KokoroTTSClient, "kokoro"), (Qwen3TTSClient, "qwen3")):
            monkeypatch.setattr(cls, "stop_server", classmethod(lambda c, name=name: stopped.append(name)))
        ttsengine.stop_all_tts_servers()
        assert sorted(stopped) == ["irodori", "kokoro", "qwen3"]


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


class TestQwen3Config:
    def test_it_uses_the_same_voice_library_as_irodori(self, voice_lib):
        config = tts_config_from_settings({"tts": {"engine": "qwen3", "voice": "alice", "kokoro_voice": "jf_alpha"}})
        assert (config.engine, config.voice, config.model, config.caption) == ("qwen3", "alice", "qwen3", None)

    def test_it_cannot_use_no_reference_so_it_falls_back_to_a_real_voice(self, voice_lib):
        assert tts_config_from_settings({"tts": {"engine": "qwen3", "voice": "none"}}).voice == tuning.TTS_VOICE
        assert tts_config_from_settings({"tts": {"engine": "irodori", "voice": "none"}}).voice == "none"

    def test_a_voice_that_is_gone_falls_back(self, voice_lib):
        assert tts_config_from_settings({"tts": {"engine": "qwen3", "voice": "nobody"}}).voice == tuning.TTS_VOICE

    def test_the_balanced_voice_is_in_the_engine_list(self):
        assert tuning.TTS_ENGINES == ("irodori", "qwen3", "kokoro")


class TestQwen3Fingerprint:
    def test_the_engine_and_the_recording_both_count(self, voice_lib):
        irodori = voices.voice_fingerprint("alice", 1.0, "calm")
        qwen = voices.voice_fingerprint("alice", 1.0, "calm", engine="qwen3")
        assert qwen["engine"] == "qwen3" and qwen["sha256"] == irodori["sha256"] and qwen["sha256"]
        assert not voices.fingerprints_match(irodori, qwen)
        assert voices.fingerprints_match(qwen, qwen)
        (voice_lib / "alice.wav").write_bytes((voice_lib / "alice.wav").read_bytes() + b"\0\0")
        assert not voices.fingerprints_match(qwen, voices.voice_fingerprint("alice", 1.0, "calm", engine="qwen3"))

    def test_the_irodori_style_caption_does_not_apply(self, voice_lib):
        assert voices.voice_fingerprint("alice", 1.0, "calm", engine="qwen3")["caption"] is None


class TestQwen3Client:
    @pytest.fixture
    def client(self, tmp_path, cache_dir, voice_lib, monkeypatch):
        sent = []

        async def post(self, payload):
            sent.append(payload)
            return b"WAV-" + payload["input"].encode("utf-8")

        monkeypatch.setattr(Qwen3TTSClient, "_post_speech", post)
        monkeypatch.setattr(ttsengine, "apply_speed", lambda audio, speed: audio + f"@{speed}".encode())
        c = make_tts_client({"tts": {"engine": "qwen3", "voice": "alice", "speed": 1.25}}, tmp_path / "out")
        c.sent = sent
        return c

    def test_it_sends_the_text_and_the_path_of_the_recording_and_applies_the_speed_after(self, client, voice_lib):
        audio = asyncio.run(client.call_api("こんにちは"))
        assert client.sent == [{"input": "こんにちは", "ref_audio": str(voice_lib / "alice.wav")}]
        assert audio == "WAV-こんにちは@1.25".encode("utf-8")

    def test_a_repeated_line_comes_from_the_cache_at_the_speed_it_was_made(self, client):
        asyncio.run(client.call_api("お疲れ様です"))
        assert asyncio.run(client.call_api("お疲れ様です")).endswith(b"@1.25")
        assert len(client.sent) == 1

    def test_a_forced_redo_skips_the_cache_and_stores_the_new_take(self, client):
        asyncio.run(client.call_api("もう一度"))
        client.bypass_cache = True
        asyncio.run(client.call_api("もう一度"))
        assert len(client.sent) == 2
        client.bypass_cache = False
        asyncio.run(client.call_api("もう一度"))
        assert len(client.sent) == 2

    def test_another_speed_or_recording_is_a_new_line(self, client, tmp_path, voice_lib):
        asyncio.run(client.call_api("一"))
        slower = make_tts_client({"tts": {"engine": "qwen3", "voice": "alice", "speed": 0.9}}, tmp_path / "o2")
        slower.sent = client.sent
        asyncio.run(slower.call_api("一"))
        assert len(client.sent) == 2
        (voice_lib / "alice.wav").write_bytes((voice_lib / "alice.wav").read_bytes() + b"\0\0")
        asyncio.run(client.call_api("一"))
        assert len(client.sent) == 3

    def test_its_cache_entries_are_not_irodoris_or_kokoros(self, client, tmp_path, voice_lib, monkeypatch):
        monkeypatch.setattr(ttsengine, "ensure_reference_latent", lambda voice: None)

        async def post(self, payload):
            return b"IRODORI"

        monkeypatch.setattr(IrodoriTTSClient, "_post_speech", post)
        asyncio.run(client.call_api("同じ文"))
        irodori = make_tts_client({"tts": {"voice": "alice", "speed": 1.25}}, tmp_path / "i")
        assert asyncio.run(irodori.call_api("同じ文")) == b"IRODORI"

    def test_a_voice_without_a_recording_says_what_to_do(self, client):
        client.config = ttsengine.TTSConfig(engine="qwen3", model="qwen3", voice="none", caption=None)
        with pytest.raises(FileNotFoundError, match="Choose a voice"):
            asyncio.run(client.call_api("一"))

    def test_it_has_its_own_server_and_is_stopped_with_the_others(self, monkeypatch):
        assert Qwen3TTSClient._server_process is None
        assert len({Qwen3TTSClient._PIDFILE, KokoroTTSClient._PIDFILE, IrodoriTTSClient._PIDFILE}) == 3
        assert len({Qwen3TTSClient._PROCESS_MARKER, KokoroTTSClient._PROCESS_MARKER, IrodoriTTSClient._PROCESS_MARKER}) == 3
        assert Qwen3TTSClient._SERVER_PORT not in (KokoroTTSClient._SERVER_PORT, 8088)
        stopped = []
        for cls in (IrodoriTTSClient, KokoroTTSClient, Qwen3TTSClient):
            monkeypatch.setattr(cls, "stop_server", classmethod(lambda c, name=cls.__name__: stopped.append(name)))
        ttsengine.stop_all_tts_servers()
        assert sorted(stopped) == ["IrodoriTTSClient", "KokoroTTSClient", "Qwen3TTSClient"]

    def test_the_factory_picks_it(self, tmp_path, voice_lib):
        assert type(make_tts_client({"tts": {"engine": "qwen3", "voice": "alice"}}, tmp_path / "q")) is Qwen3TTSClient

    def test_starting_without_setup_explains_what_to_do(self, client):
        assert "Set up balanced voice" in client._missing_server_message()


class TestSpeed:
    def test_a_normal_speed_returns_the_audio_untouched(self):
        assert apply_speed(b"RIFF", 1.0) == b"RIFF"
        assert apply_speed(b"RIFF", 1.005) == b"RIFF"

    def test_atempo_stays_inside_ffmpegs_range_per_stage(self):
        assert _atempo_filter(1.25) == "atempo=1.2500"
        assert _atempo_filter(2.0) == "atempo=2.0000"
        assert _atempo_filter(3.0) == "atempo=2.0,atempo=1.5000"
        assert _atempo_filter(0.4) == "atempo=0.5,atempo=0.8000"

    def test_a_real_ffmpeg_makes_a_line_faster(self, tmp_path):
        try:
            ffmpeg = ttsengine.FFmpegManager.resolve_ffmpeg_bin()
            import subprocess

            subprocess.run([ffmpeg, "-version"], capture_output=True, check=True)
        except Exception:
            pytest.skip("ffmpeg is not available")
        source = tmp_path / "in.wav"
        with wave.open(str(source), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes((1000).to_bytes(2, "little", signed=True) * 24000 * 2)  # 2 s
        faster = tmp_path / "out.wav"
        faster.write_bytes(apply_speed(source.read_bytes(), 2.0))
        assert ttsengine.FFmpegManager.get_media_duration(str(faster)) == pytest.approx(1.0, abs=0.1)
        # the header must be finished, not left at 0xFFFFFFFF as a pipe write does
        with wave.open(str(faster), "rb") as wf:
            assert wf.getnframes() == pytest.approx(24000, abs=1200)

    def test_the_phrase_cache_drops_a_line_with_an_unfinished_header(self, cache_dir):
        from services.tts import phrase_cache

        bad = b"RIFF\xff\xff\xff\xffWAVEdata"
        phrase_cache.put("k", bad)
        assert phrase_cache.get("k") is None
        phrase_cache.put("k", b"RIFF\x24\x00\x00\x00WAVEdata")
        assert phrase_cache.get("k") is not None


class TestQwen3Actions:
    def test_engines_reports_whether_it_is_set_up(self, monkeypatch):
        monkeypatch.setattr(Qwen3TTSClient, "is_ready", classmethod(lambda cls: True))
        assert voice_commands.run_voice_action("tts_engines", {})["qwen3"] == {"ready": True}
        monkeypatch.setattr(Qwen3TTSClient, "is_ready", classmethod(lambda cls: False))
        assert voice_commands.run_voice_action("tts_engines", {})["qwen3"] == {"ready": False}

    def test_the_setup_action_is_routed(self):
        assert "tts_install_qwen3" in voice_commands.VOICE_ACTIONS

    def test_a_preview_goes_to_the_qwen3_client_with_a_library_voice(self, monkeypatch, tmp_path, voice_lib):
        seen = {}

        async def speak(self, text, filename=None):
            seen.update(type=type(self).__name__, voice=self.config.voice, filename=filename)
            return str(tmp_path / "x.wav")

        monkeypatch.setattr(Qwen3TTSClient, "generate_speech", speak)
        result = voice_commands.run_voice_action("tts_voice_preview", {"engine": "qwen3", "voice": "alice", "speed": 1.1})
        assert result["success"], result
        assert seen == {"type": "Qwen3TTSClient", "voice": "alice", "filename": "qwen3_alice.wav"}

    def test_a_qwen3_preview_still_needs_the_voice_file(self, voice_lib):
        result = voice_commands.run_voice_action("tts_voice_preview", {"engine": "qwen3", "voice": "nobody"})
        assert result["success"] is False and "nobody" in result["error"]


class TestQwen3ServerScript:
    @staticmethod
    def source():
        return ttsengine.Path(ttsengine.__file__).with_name("qwen3_server.py").read_text(encoding="utf-8")

    def test_it_has_no_navivi_imports_so_its_venv_can_run_it(self):
        assert "from services" not in self.source() and "import services" not in self.source()

    def test_the_cut_off_check_sits_between_good_and_bad_endings(self):
        # measured: lines that end properly 0.00-0.12, cut-off ones 0.19-0.31
        threshold = float(next(line for line in self.source().splitlines() if line.startswith("TAIL_OK")).split("=")[1].split("#")[0])
        assert 0.12 < threshold < 0.19

    def test_it_ends_lines_with_a_full_stop_and_retries(self):
        source = self.source()
        assert "ADD_FULL_STOP = True" in source and "MAX_ATTEMPTS = 3" in source


def _load_qwen3_server():
    import importlib.util

    spec = importlib.util.spec_from_file_location("qwen3_server_under_test", ttsengine.Path(ttsengine.__file__).with_name("qwen3_server.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # only stdlib imports at the top: torch and qwen_tts load later, inside the functions
    return module


class TestQwen3ServerLogic:
    def test_a_long_recording_is_cut_to_its_first_seconds(self, tmp_path):
        pytest.importorskip("soundfile")  # the model's own venv has it
        server = _load_qwen3_server()
        path = tmp_path / "long.wav"
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(8000)
            wf.writeframes((500).to_bytes(2, "little", signed=True) * 8000 * 20)  # 20 s
        data, rate = server.reference_audio(str(path))
        assert rate == 8000 and len(data) == 8000 * server.REF_MAX_SECONDS

    def test_a_short_recording_is_used_whole(self, tmp_path):
        pytest.importorskip("soundfile")
        server = _load_qwen3_server()
        path = tmp_path / "short.wav"
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(8000)
            wf.writeframes((500).to_bytes(2, "little", signed=True) * 2 * 8000 * 3)  # 3 s, stereo
        data, rate = server.reference_audio(str(path))
        assert len(data) == 8000 * 3 and data.ndim == 1  # mixed down to mono

    def test_a_file_it_cannot_read_is_passed_on_as_it_is(self, tmp_path):
        server = _load_qwen3_server()
        path = tmp_path / "odd.m4a"
        path.write_bytes(b"not audio")
        assert server.reference_audio(str(path)) == str(path)

    def test_a_clip_that_ends_while_still_loud_is_told_from_one_that_fades_out(self):
        np = pytest.importorskip("numpy")

        server = _load_qwen3_server()
        rate = 24000
        t = np.arange(rate * 2) / rate
        tone = np.sin(2 * np.pi * 200 * t).astype(np.float32)
        cut_off = tone.copy()  # loud to the very last sample
        ends_properly = tone.copy()
        ends_properly[int(rate * 1.7):] = 0  # the voice stops, then a short silence, like a finished line
        assert server.tail_ratio(cut_off, rate) > server.TAIL_OK
        assert server.tail_ratio(ends_properly, rate) < server.TAIL_OK
