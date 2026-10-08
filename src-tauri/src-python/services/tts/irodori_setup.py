"""Sets up the natural voice (Irodori-TTS): the server's source under bin/Irodori-TTS-Server, its own venv and the model.

The source is the upstream project (https://github.com/Aratako/Irodori-TTS-Server) fetched as a zip, so git is not needed. The
environment is made by `uv sync` with the PyTorch build that fits the PC (CUDA when an NVIDIA GPU is there, CPU otherwise).
Recorded voices in `voices/` are never overwritten. Idempotent, like kokoro_setup, so it also repairs a half-finished setup."""

import io
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from services import install_progress, system_runtime
from services.logger.logger import setup_logger
from services.tts.kokoro_setup import _run, find_uv
from services.tts.ttsengine import IrodoriTTSClient

logger = setup_logger("IrodoriSetup")

SOURCE_ZIP = "https://github.com/Aratako/Irodori-TTS-Server/archive/refs/heads/main.zip"
MODEL_REPO = "Aratako/Irodori-TTS-v4-Small"
PYTHON_VERSION = "3.10"
KEEP = {"voices"}  # the user's own folder inside the project


def pick_backend() -> str:
    """The PyTorch extra of the project: CUDA 12.8 with an NVIDIA GPU, else CPU."""
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            if subprocess.run([smi, "-L"], capture_output=True, timeout=15).returncode == 0:
                return "cu128"
        except (OSError, subprocess.SubprocessError):
            pass
    return "cpu"


def source_present(directory: Path) -> bool:
    return (directory / "pyproject.toml").exists() and (directory / "src").is_dir()


def fetch_zip(url: str = SOURCE_ZIP) -> bytes:
    logger.info("Irodori setup: downloading the server source")
    response = httpx.get(url, follow_redirects=True, timeout=120.0)
    response.raise_for_status()
    return response.content


def unpack_source(archive: bytes, directory: Path) -> None:
    """Extracts a GitHub source zip (one top folder) into `directory`, leaving anything already in `voices/` as it is."""
    directory.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        for info in zf.infolist():
            parts = Path(info.filename).parts[1:]  # drop the "<repo>-main/" prefix
            if not parts or info.is_dir():
                continue
            target = directory.joinpath(*parts)
            if parts[0] in KEEP and target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(info))


def _imports_work(python: Path) -> bool:
    check = subprocess.run(
        [str(python), "-c", "import irodori_openai_tts, torch"], capture_output=True, encoding="utf-8", errors="replace"
    )
    return check.returncode == 0


def install_irodori(fetch: Optional[Any] = None) -> Dict[str, Any]:
    directory, python = IrodoriTTSClient._SERVER_DIR, IrodoriTTSClient._SERVER_VENV_PYTHON
    needed = system_runtime.missing_runtime_message("The natural voice")
    if needed:
        return {"success": False, "error": needed}
    install_progress.begin(3)
    try:
        if not source_present(directory):
            install_progress.step("downloading the server source")
            unpack_source((fetch or fetch_zip)(), directory)
        if not (python.exists() and _imports_work(python)):
            uv = find_uv()
            if not uv:
                raise RuntimeError("Setting up the natural voice needs uv (https://docs.astral.sh/uv/). Install it, then try again.")
            backend = pick_backend()
            _run(
                [uv, "sync", "--project", str(directory), "--python", PYTHON_VERSION, "--extra", backend],
                f"installing Irodori-TTS ({'GPU' if backend != 'cpu' else 'CPU'} build)",
            )
            if not _imports_work(python):
                raise RuntimeError(system_runtime.import_failure(python, "import irodori_openai_tts, torch", "Irodori-TTS"))
        _run(
            [str(python), "-c", f"from huggingface_hub import snapshot_download as d; d({MODEL_REPO!r})"],
            "downloading the model",
        )
    except (RuntimeError, httpx.HTTPError, zipfile.BadZipFile, OSError) as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "ready": True}
