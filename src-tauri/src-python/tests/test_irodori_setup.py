"""Setting up the natural voice (services/tts/irodori_setup.py) without a network, uv or GPU."""

import io
import zipfile

import pytest

from services.tts import irodori_setup
from services.tts.ttsengine import IrodoriTTSClient


def _zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, data in files.items():
            zf.writestr(f"Irodori-TTS-Server-main/{name}", data)
    return buffer.getvalue()


SOURCE = {"pyproject.toml": "[project]\nname='x'", "src/irodori_openai_tts/__init__.py": "", "voices/default.wav": "stock", "README.md": "hi"}


class TestBackend:
    def test_an_nvidia_gpu_gets_the_cuda_build(self, monkeypatch):
        monkeypatch.setattr(irodori_setup.shutil, "which", lambda name: "nvidia-smi")
        monkeypatch.setattr(irodori_setup.subprocess, "run", lambda *a, **k: type("R", (), {"returncode": 0})())
        assert irodori_setup.pick_backend() == "cu128"

    def test_no_gpu_tool_or_a_failing_one_means_cpu(self, monkeypatch):
        monkeypatch.setattr(irodori_setup.shutil, "which", lambda name: None)
        assert irodori_setup.pick_backend() == "cpu"
        monkeypatch.setattr(irodori_setup.shutil, "which", lambda name: "nvidia-smi")
        monkeypatch.setattr(irodori_setup.subprocess, "run", lambda *a, **k: type("R", (), {"returncode": 9})())
        assert irodori_setup.pick_backend() == "cpu"


class TestUnpackSource:
    def test_the_top_folder_is_dropped_and_files_land_in_the_engine_folder(self, tmp_path):
        irodori_setup.unpack_source(_zip(SOURCE), tmp_path / "engine")
        assert (tmp_path / "engine" / "pyproject.toml").exists()
        assert (tmp_path / "engine" / "src" / "irodori_openai_tts" / "__init__.py").exists()
        assert irodori_setup.source_present(tmp_path / "engine")

    def test_a_recorded_voice_is_not_overwritten_but_new_stock_ones_are_added(self, tmp_path):
        engine = tmp_path / "engine"
        (engine / "voices").mkdir(parents=True)
        (engine / "voices" / "default.wav").write_text("mine")
        irodori_setup.unpack_source(_zip({**SOURCE, "voices/extra.wav": "stock2"}), engine)
        assert (engine / "voices" / "default.wav").read_text() == "mine"
        assert (engine / "voices" / "extra.wav").read_text() == "stock2"

    def test_other_files_are_refreshed(self, tmp_path):
        engine = tmp_path / "engine"
        irodori_setup.unpack_source(_zip(SOURCE), engine)
        irodori_setup.unpack_source(_zip({**SOURCE, "README.md": "newer"}), engine)
        assert (engine / "README.md").read_text() == "newer"


class TestInstall:
    @pytest.fixture
    def engine(self, tmp_path, monkeypatch):
        directory = tmp_path / "Irodori-TTS-Server"
        python = directory / ".venv" / "Scripts" / "python.exe"
        monkeypatch.setattr(IrodoriTTSClient, "_SERVER_DIR", directory)
        monkeypatch.setattr(IrodoriTTSClient, "_SERVER_VENV_PYTHON", python)
        monkeypatch.setattr(irodori_setup, "find_uv", lambda: "uv")
        monkeypatch.setattr(irodori_setup, "pick_backend", lambda: "cpu")
        return directory, python

    def test_it_fetches_the_source_syncs_the_environment_and_downloads_the_model(self, engine, monkeypatch):
        directory, python = engine
        calls = []

        def run(cmd, what):
            calls.append((cmd, what))
            if cmd[1] == "sync":
                python.parent.mkdir(parents=True, exist_ok=True)
                python.write_text("")

        monkeypatch.setattr(irodori_setup, "_run", run)
        monkeypatch.setattr(irodori_setup, "_imports_work", lambda p: True)
        result = irodori_setup.install_irodori(fetch=lambda: _zip(SOURCE))
        assert result == {"success": True, "ready": True}
        assert irodori_setup.source_present(directory)
        sync = calls[0][0]
        assert sync[:2] == ["uv", "sync"] and "--extra" in sync and sync[sync.index("--extra") + 1] == "cpu"
        assert sync[sync.index("--project") + 1] == str(directory)
        assert "snapshot_download" in calls[1][0][2] and "Aratako/Irodori-TTS-v4-Small" in calls[1][0][2]
        assert IrodoriTTSClient.is_ready()

    def test_a_finished_setup_only_checks_the_model(self, engine, monkeypatch):
        directory, python = engine
        irodori_setup.unpack_source(_zip(SOURCE), directory)
        python.parent.mkdir(parents=True, exist_ok=True)
        python.write_text("")
        calls = []
        monkeypatch.setattr(irodori_setup, "_run", lambda cmd, what: calls.append(what))
        monkeypatch.setattr(irodori_setup, "_imports_work", lambda p: True)
        monkeypatch.setattr(irodori_setup, "fetch_zip", lambda: pytest.fail("the source is already there"))
        assert irodori_setup.install_irodori()["success"] is True
        assert calls == ["downloading the model"]

    def test_without_uv_the_message_says_so(self, engine, monkeypatch):
        monkeypatch.setattr(irodori_setup, "find_uv", lambda: None)
        result = irodori_setup.install_irodori(fetch=lambda: _zip(SOURCE))
        assert result["success"] is False and "uv" in result["error"]

    def test_a_failed_step_comes_back_as_a_readable_error(self, engine, monkeypatch):
        def run(cmd, what):
            raise RuntimeError(f"{what} failed:\nboom")

        monkeypatch.setattr(irodori_setup, "_run", run)
        result = irodori_setup.install_irodori(fetch=lambda: _zip(SOURCE))
        assert result["success"] is False and "boom" in result["error"]

    def test_a_broken_download_is_reported_not_raised(self, engine):
        result = irodori_setup.install_irodori(fetch=lambda: b"not a zip")
        assert result["success"] is False


def test_the_action_is_routed_and_engines_reports_it(monkeypatch):
    from services.cli import voice_commands

    assert "tts_install_irodori" in voice_commands.VOICE_ACTIONS
    monkeypatch.setattr(IrodoriTTSClient, "is_ready", classmethod(lambda cls: True))
    assert voice_commands.run_voice_action("tts_engines", {})["irodori"] == {"ready": True}
