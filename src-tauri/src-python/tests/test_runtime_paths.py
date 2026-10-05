"""Where the tools live: next to the code in development, in the folders the Rust shell names when installed."""

import os

import pytest

from services import runtime_paths


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("NAVIVI_BIN_DIR", "NAVIVI_TOOLS_DIR", "NAVIVI_UV"):
        monkeypatch.delenv(name, raising=False)


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def test_development_uses_the_bin_folder_beside_the_code():
    assert runtime_paths.bin_dir() == runtime_paths.SRC_PYTHON / "bin"
    assert runtime_paths.tools_dir() is None
    assert runtime_paths.engine_dir("Kokoro-TTS") == runtime_paths.SRC_PYTHON / "bin" / "Kokoro-TTS"


def test_the_shell_can_move_the_engines_somewhere_writable(monkeypatch, tmp_path):
    monkeypatch.setenv("NAVIVI_BIN_DIR", str(tmp_path / "data" / "bin"))
    assert runtime_paths.engine_dir("Qwen3-TTS") == tmp_path / "data" / "bin" / "Qwen3-TTS"


def test_the_engine_python_is_inside_its_venv(tmp_path):
    expected = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    assert runtime_paths.venv_python(tmp_path / "E") == tmp_path / "E" / ".venv" / expected


def test_ffmpeg_prefers_the_installers_copy_then_bin_then_path(monkeypatch, tmp_path):
    exe = runtime_paths.EXE
    monkeypatch.setenv("NAVIVI_BIN_DIR", str(tmp_path / "bin"))
    monkeypatch.setenv("NAVIVI_TOOLS_DIR", str(tmp_path / "tools"))
    monkeypatch.setattr(runtime_paths.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert runtime_paths.ffmpeg_exe() == "/usr/bin/ffmpeg"
    in_bin = _touch(tmp_path / "bin" / "FFmpeg" / "bin" / f"ffmpeg{exe}")
    assert runtime_paths.ffmpeg_exe() == str(in_bin)
    shipped = _touch(tmp_path / "tools" / "ffmpeg" / "bin" / f"ffmpeg{exe}")
    assert runtime_paths.ffmpeg_exe() == str(shipped)
    probe = _touch(tmp_path / "tools" / "ffmpeg" / "bin" / f"ffprobe{exe}")
    assert runtime_paths.ffprobe_exe() == str(probe)


def test_gpsbabel_falls_back_to_where_it_is_expected(monkeypatch, tmp_path):
    exe = runtime_paths.EXE
    monkeypatch.setenv("NAVIVI_BIN_DIR", str(tmp_path / "bin"))
    monkeypatch.setenv("NAVIVI_TOOLS_DIR", str(tmp_path / "tools"))
    assert runtime_paths.gpsbabel_exe() == tmp_path / "bin" / "GPSBabel" / f"gpsbabel{exe}"
    shipped = _touch(tmp_path / "tools" / "gpsbabel" / f"gpsbabel{exe}")
    assert runtime_paths.gpsbabel_exe() == shipped


def test_uv_is_the_one_in_the_installer_or_named_by_the_shell(monkeypatch, tmp_path):
    exe = runtime_paths.EXE
    monkeypatch.setattr(runtime_paths.shutil, "which", lambda name: None)
    monkeypatch.setattr(runtime_paths.Path, "home", classmethod(lambda cls: tmp_path / "nohome"))
    assert runtime_paths.uv_exe() is None
    shipped = _touch(tmp_path / "tools" / f"uv{exe}")
    monkeypatch.setenv("NAVIVI_TOOLS_DIR", str(tmp_path / "tools"))
    assert runtime_paths.uv_exe() == str(shipped)
    named = _touch(tmp_path / "elsewhere" / f"uv{exe}")
    monkeypatch.setenv("NAVIVI_UV", str(named))
    assert runtime_paths.uv_exe() == str(named)
