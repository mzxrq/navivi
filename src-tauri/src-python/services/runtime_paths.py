"""Where the app's tools and engines live.

From the repo (development) everything sits next to the code in `src-python/bin`. In the installed app the code is in the
read-only install folder, so the Rust shell sets two variables for the Python it starts:

  NAVIVI_BIN_DIR    a writable folder in the user's local app data: the voice engines, ComfyUI, Ollama, recorded voices
  NAVIVI_TOOLS_DIR  the tools shipped inside the installer: ffmpeg/, gpsbabel/ and uv.exe

Nothing else should build a path to `bin` itself; ask here.
"""

import os
import shutil
from pathlib import Path
from typing import Iterable, Optional

SRC_PYTHON = Path(__file__).resolve().parents[1]
EXE = ".exe" if os.name == "nt" else ""


def bin_dir() -> Path:
    override = os.environ.get("NAVIVI_BIN_DIR")
    return Path(override) if override else SRC_PYTHON / "bin"


def tools_dir() -> Optional[Path]:
    override = os.environ.get("NAVIVI_TOOLS_DIR")
    return Path(override) if override else None


def engine_dir(name: str) -> Path:
    """A downloaded engine, e.g. `Kokoro-TTS`, `Qwen3-TTS`, `Irodori-TTS-Server`, `ComfyUI`."""
    return bin_dir() / name


def venv_python(directory: Path) -> Path:
    return directory / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _first_existing(candidates: Iterable[Optional[Path]]) -> Optional[Path]:
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    return None


def _from_tools(*parts: str) -> Optional[Path]:
    tools = tools_dir()
    return tools.joinpath(*parts) if tools else None


def ffmpeg_exe() -> Optional[str]:
    """The installer's ffmpeg, else one in `bin/FFmpeg`, else the one on PATH."""
    found = _first_existing([
        _from_tools("ffmpeg", "bin", f"ffmpeg{EXE}"),
        bin_dir() / "FFmpeg" / "bin" / f"ffmpeg{EXE}",
    ])
    return str(found) if found else shutil.which("ffmpeg")


def ffprobe_exe() -> Optional[str]:
    found = _first_existing([
        _from_tools("ffmpeg", "bin", f"ffprobe{EXE}"),
        bin_dir() / "FFmpeg" / "bin" / f"ffprobe{EXE}",
    ])
    return str(found) if found else shutil.which("ffprobe")


def gpsbabel_exe() -> Path:
    """The path GPSBabel is expected at (it may not exist; the caller reports that)."""
    found = _first_existing([
        _from_tools("gpsbabel", f"gpsbabel{EXE}"),
        bin_dir() / "GPSBabel" / f"gpsbabel{EXE}",
    ])
    return found or bin_dir() / "GPSBabel" / f"gpsbabel{EXE}"


def uv_exe() -> Optional[str]:
    """uv builds the engines' own Python environments. Shipped in the installer; otherwise one the user installed."""
    override = os.environ.get("NAVIVI_UV")
    found = _first_existing([
        Path(override) if override else None,
        _from_tools(f"uv{EXE}"),
    ])
    if found:
        return str(found)
    on_path = shutil.which("uv")
    if on_path:
        return on_path
    home = Path.home()
    found = _first_existing([home / ".local" / "bin" / f"uv{EXE}", home / ".cargo" / "bin" / f"uv{EXE}"])
    return str(found) if found else None
