"""Setting up the moving attraction videos (services/vdoprocessing/comfyui_setup.py) without a network, uv, GPU or 26 GB."""

import hashlib
import io
import zipfile

import httpx
import pytest

from services.vdoprocessing import comfyui_setup
from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient


def _zip(files, top="ComfyUI-v0"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, data in files.items():
            zf.writestr(f"{top}/{name}", data)
    return buffer.getvalue()


COMFY = {"main.py": "print()", "comfy/__init__.py": "", "requirements.txt": "torch"}
GGUF = {"nodes.py": "", "requirements.txt": "gguf"}


@pytest.fixture
def engine(tmp_path, monkeypatch):
    directory = tmp_path / "ComfyUI"
    python = directory / ".venv" / "Scripts" / "python.exe"
    monkeypatch.setattr(ComfyUII2VClient, "_SERVER_DIR", directory)
    monkeypatch.setattr(ComfyUII2VClient, "_SERVER_VENV_PYTHON", python)
    monkeypatch.setattr(comfyui_setup, "find_uv", lambda: "uv")
    monkeypatch.setattr(comfyui_setup, "pick_backend", lambda: "cu128")
    return directory, python


def _fetch(url):
    return _zip(COMFY) if url == comfyui_setup.COMFYUI_ZIP else _zip(GGUF, "ComfyUI-GGUF-x")


class TestModelList:
    def test_it_lists_both_families_with_pinned_checksums(self):
        files = comfyui_setup.model_files()
        names = {f["file"] for f in files}
        assert len(files) == 6 and len(names) == 6
        assert all(len(f["sha256"]) == 64 and f["bytes"] > 10 ** 6 and f["url"].startswith("https://") for f in files)

    def test_another_model_choice_fails_clearly(self, monkeypatch):
        monkeypatch.setattr(comfyui_setup.tuning, "COMFYUI_MODEL", "a14b")
        with pytest.raises(RuntimeError, match="5B"):
            comfyui_setup.model_files()
        assert comfyui_setup.is_ready() is False


class TestRequirements:
    def test_no_nvidia_gpu_stops_before_anything_is_downloaded(self, engine, monkeypatch):
        monkeypatch.setattr(comfyui_setup, "pick_backend", lambda: "cpu")
        result = comfyui_setup.install_comfyui(fetch=lambda url: pytest.fail("nothing should be fetched"), free_gb=500)
        assert result["success"] is False and "NVIDIA" in result["error"]

    def test_too_little_disk_is_reported_with_the_free_amount(self, engine):
        result = comfyui_setup.install_comfyui(fetch=lambda url: pytest.fail("nothing should be fetched"), free_gb=10)
        assert result["success"] is False and "32 GB" in result["error"] and "10 GB" in result["error"]

    def test_files_already_downloaded_count_towards_the_space(self, engine):
        directory, _ = engine
        spec = comfyui_setup.model_files()[1]  # the 6.7 GB text encoder
        path = comfyui_setup._path(spec)
        path.parent.mkdir(parents=True)
        with open(path, "wb") as f:
            f.truncate(spec["bytes"])
        comfyui_setup.check_requirements(directory, free_gb=26)  # 26 + 6.3 >= 32


class TestDownload:
    SPEC = {"folder": "vae", "file": "tiny.safetensors", "url": "https://example.test/tiny", "bytes": 10, "sha256": hashlib.sha256(b"0123456789").hexdigest()}

    def _client(self, requests):
        body = b"0123456789"

        def handler(request):
            requests.append(request.headers.get("range"))
            start = int(request.headers["range"].split("=")[1].rstrip("-")) if request.headers.get("range") else 0
            return httpx.Response(206 if start else 200, content=body[start:])

        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_a_whole_download_is_verified_and_moved_into_place(self, engine):
        requests = []
        comfyui_setup.download_model(self.SPEC, self._client(requests))
        final = comfyui_setup._path(self.SPEC)
        assert final.read_bytes() == b"0123456789" and not final.with_name(final.name + ".part").exists()
        assert requests == [None]

    def test_a_cut_short_download_resumes_from_where_it_stopped(self, engine):
        final = comfyui_setup._path(self.SPEC)
        final.parent.mkdir(parents=True)
        final.with_name(final.name + ".part").write_bytes(b"0123")
        requests = []
        comfyui_setup.download_model(self.SPEC, self._client(requests))
        assert requests == ["bytes=4-"] and final.read_bytes() == b"0123456789"

    def test_a_finished_file_is_not_fetched_again(self, engine):
        final = comfyui_setup._path(self.SPEC)
        final.parent.mkdir(parents=True)
        final.write_bytes(b"0123456789")
        requests = []
        comfyui_setup.download_model(self.SPEC, self._client(requests))
        assert requests == []

    def test_a_damaged_download_is_discarded(self, engine):
        spec = {**self.SPEC, "sha256": "0" * 64}
        with pytest.raises(RuntimeError, match="checksum"):
            comfyui_setup.download_model(spec, self._client([]))
        final = comfyui_setup._path(spec)
        assert not final.exists() and not final.with_name(final.name + ".part").exists()


class TestInstall:
    def _fake_env(self, python, calls):
        def run(cmd, what):
            calls.append((cmd, what))
            if cmd[1] == "venv":
                python.parent.mkdir(parents=True, exist_ok=True)
                python.write_text("")

        return run

    def test_it_installs_source_node_environment_and_every_model(self, engine, monkeypatch):
        directory, python = engine
        calls, downloaded = [], []
        monkeypatch.setattr(comfyui_setup, "_run", self._fake_env(python, calls))
        monkeypatch.setattr(comfyui_setup, "_imports_work", lambda p: python.exists())
        result = comfyui_setup.install_comfyui(fetch=_fetch, download=lambda spec: downloaded.append(spec["file"]), free_gb=100)
        assert result == {"success": True, "ready": True}
        assert comfyui_setup.source_present(directory) and comfyui_setup.gguf_present(directory)
        whats = [w for _, w in calls]
        assert whats == ["creating the environment", "installing PyTorch (CUDA build)", "installing ComfyUI's packages", "installing the GGUF node's packages"]
        torch = calls[1][0]
        assert torch[torch.index("--index-url") + 1] == comfyui_setup.TORCH_INDEX
        assert {"torch", "torchvision", "torchaudio"} <= set(torch)
        assert len(downloaded) == 6

    def test_a_finished_install_only_checks_the_downloads(self, engine, monkeypatch):
        directory, python = engine
        comfyui_setup.unpack_source(_zip(COMFY), directory)
        comfyui_setup.unpack_source(_zip(GGUF), directory / "custom_nodes" / "ComfyUI-GGUF")
        python.parent.mkdir(parents=True)
        python.write_text("")
        monkeypatch.setattr(comfyui_setup, "_run", lambda cmd, what: pytest.fail(what))
        monkeypatch.setattr(comfyui_setup, "_imports_work", lambda p: True)
        result = comfyui_setup.install_comfyui(fetch=lambda url: pytest.fail("already there"), download=lambda spec: None, free_gb=100)
        assert result["success"] is True

    def test_without_uv_the_message_says_so(self, engine, monkeypatch):
        monkeypatch.setattr(comfyui_setup, "find_uv", lambda: None)
        result = comfyui_setup.install_comfyui(fetch=_fetch, free_gb=100)
        assert result["success"] is False and "uv" in result["error"]

    def test_a_failed_step_comes_back_as_a_readable_error(self, engine, monkeypatch):
        def run(cmd, what):
            raise RuntimeError(f"{what} failed:\nboom")

        monkeypatch.setattr(comfyui_setup, "_run", run)
        result = comfyui_setup.install_comfyui(fetch=_fetch, free_gb=100)
        assert result["success"] is False and "boom" in result["error"]

    def test_a_broken_source_download_is_reported_not_raised(self, engine):
        result = comfyui_setup.install_comfyui(fetch=lambda url: b"not a zip", free_gb=100)
        assert result["success"] is False

    def test_ready_means_source_node_environment_and_all_models(self, engine, monkeypatch):
        real_files = comfyui_setup.model_files()
        monkeypatch.setattr(comfyui_setup, "model_files", lambda: [{**spec, "bytes": 64} for spec in real_files])
        directory, python = engine
        assert comfyui_setup.is_ready() is False
        comfyui_setup.unpack_source(_zip(COMFY), directory)
        comfyui_setup.unpack_source(_zip(GGUF), directory / "custom_nodes" / "ComfyUI-GGUF")
        python.parent.mkdir(parents=True)
        python.write_text("")
        for spec in comfyui_setup.model_files():
            path = comfyui_setup._path(spec)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                f.truncate(spec["bytes"])
        assert comfyui_setup.is_ready() is True
        assert comfyui_setup.missing_models() == []


def test_the_action_is_routed_and_engines_reports_it(monkeypatch):
    from services.cli import voice_commands

    assert "comfyui_install" in voice_commands.VOICE_ACTIONS
    monkeypatch.setattr(comfyui_setup, "is_ready", lambda: False)
    monkeypatch.setattr("services.tts.irodori_setup.pick_backend", lambda: "cu128")
    assert voice_commands.run_voice_action("tts_engines", {})["comfyui"] == {"ready": False, "nvidia": True}
