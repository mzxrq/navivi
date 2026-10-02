"""Sets up the fast voice (Kokoro): its own venv under bin/Kokoro-TTS, the packages, and the model files.

Why a venv of its own: the Japanese text analysis (pyopenjtalk) has no ready-made wheel for current Python on Windows, only the prebuilt
fork, which needs NumPy 1.x; the Irodori venv has NumPy 2. The pins below are what was tested together (without the transformers and
huggingface_hub pins uv resolves transformers 4.12.2, which cannot work).

Needs `uv` (https://docs.astral.sh/uv/). Idempotent: steps that are already done are skipped, so it can also repair a half-finished setup."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from services import tuning
from services.logger.logger import setup_logger
from services.tts.ttsengine import KokoroTTSClient

logger = setup_logger("KokoroSetup")

PYTHON_VERSION = "3.10"
TORCH_INDEX = "https://download.pytorch.org/whl/cpu"
PACKAGES = [
    "kokoro", "transformers<5", "huggingface_hub<1", "numpy<2",
    "jaconv", "mojimoji", "fugashi", "unidic-lite", "pyopenjtalk-prebuilt", "soundfile",
]
MODEL_FILES = ["config.json", "kokoro-v1_0.pth"]


def find_uv() -> Optional[str]:
    found = shutil.which("uv")
    if found:
        return found
    for candidate in (Path.home() / ".local" / "bin" / ("uv.exe" if os.name == "nt" else "uv"), Path.home() / ".cargo" / "bin" / "uv"):
        if candidate.exists():
            return str(candidate)
    return None


def _run(cmd: List[str], what: str) -> None:
    logger.info("Kokoro setup: %s", what)
    result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"{what} failed:\n{(result.stderr or result.stdout)[-600:]}")


def _imports_work(python: Path) -> bool:
    check = subprocess.run(
        [str(python), "-c", "import torch, kokoro, pyopenjtalk, soundfile"], capture_output=True, encoding="utf-8", errors="replace"
    )
    return check.returncode == 0


def install_kokoro() -> Dict[str, Any]:
    directory, python = KokoroTTSClient._SERVER_DIR, KokoroTTSClient._SERVER_VENV_PYTHON
    directory.mkdir(parents=True, exist_ok=True)
    try:
        if not (python.exists() and _imports_work(python)):
            uv = find_uv()
            if not uv:
                raise RuntimeError("Setting up the fast voice needs uv (https://docs.astral.sh/uv/). Install it, then try again.")
            if not python.exists():
                _run([uv, "venv", "--python", PYTHON_VERSION, str(directory / ".venv")], "creating the environment")
            _run([uv, "pip", "install", "--python", str(python), "--index-url", TORCH_INDEX, "torch", "numpy<2"], "installing torch (CPU)")
            _run([uv, "pip", "install", "--python", str(python), *PACKAGES], "installing Kokoro and the Japanese text tools")
            if not _imports_work(python):
                raise RuntimeError("The packages installed, but Kokoro could not be imported. See the log above.")
        files = MODEL_FILES + [f"voices/{name}.pt" for name in tuning.KOKORO_VOICES]
        _run(
            [str(python), "-c",
             "from huggingface_hub import hf_hub_download as d\n"
             f"for f in {files!r}: d('hexgrad/Kokoro-82M', f)"],
            "downloading the model and the voices",
        )
        KokoroTTSClient._READY_FILE.write_text("ok", encoding="utf-8")
    except RuntimeError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "ready": True}
