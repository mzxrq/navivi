"""Sets up the fast voice (Kokoro): its own venv under bin/Kokoro-TTS, the packages, and the model files.

Why a venv of its own: the Japanese text analysis (pyopenjtalk) has no ready-made wheel for current Python on Windows, only the prebuilt
fork, which needs NumPy 1.x; the Irodori venv has NumPy 2. The pins below are what was tested together (without the transformers and
huggingface_hub pins uv resolves transformers 4.12.2, which cannot work).

Needs `uv` (https://docs.astral.sh/uv/). Idempotent: steps that are already done are skipped, so it can also repair a half-finished setup."""

import hashlib
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from services import install_progress, runtime_paths, system_runtime, tuning
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
# English voices need the English language data (spaCy's small model). misaki would fetch it with pip, which this venv does not have, so
# it is downloaded here, checked against this hash and installed with uv. The venv's spaCy is 3.8: the model must be the 3.8 build (the copy
# on Hugging Face is 3.7.1) and the file must keep its release name, which pip and uv read the version from.
ENGLISH_DATA_URL = "https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
ENGLISH_DATA_SHA256 = "1932429db727d4bff3deed6b34cfc05df17794f4a52eeb26cf8928f7c1a0fb85"


def find_uv() -> Optional[str]:
    return runtime_paths.uv_exe()


def _run(cmd: List[str], what: str) -> None:
    logger.info("Kokoro setup: %s", what)
    install_progress.step(what)
    result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"{what} failed:\n{(result.stderr or result.stdout)[-600:]}")


def _imports_work(python: Path) -> bool:
    check = subprocess.run(
        [str(python), "-c", "import torch, kokoro, pyopenjtalk, soundfile"], capture_output=True, encoding="utf-8", errors="replace"
    )
    return check.returncode == 0


def _english_data_installed(python: Path) -> bool:
    check = subprocess.run(
        [str(python), "-c", "import spacy, sys; sys.exit(0 if spacy.util.is_package('en_core_web_sm') else 1)"], capture_output=True, encoding="utf-8", errors="replace"
    )
    return check.returncode == 0


def _download_english_data(folder: Path) -> Path:
    install_progress.step("downloading the English language data")
    target = folder / ENGLISH_DATA_URL.rsplit("/", 1)[-1]
    try:
        with urllib.request.urlopen(ENGLISH_DATA_URL, timeout=120) as response:
            data = response.read()
    except OSError as exc:
        raise RuntimeError(f"downloading the English language data failed: {exc}") from exc
    if hashlib.sha256(data).hexdigest() != ENGLISH_DATA_SHA256:
        raise RuntimeError("The English language data did not match its checksum and was not installed.")
    target.write_bytes(data)
    return target


def _install_english_data(python: Path, uv: str) -> None:
    if _english_data_installed(python):
        return
    with tempfile.TemporaryDirectory() as tmp:
        wheel = _download_english_data(Path(tmp))
        _run([uv, "pip", "install", "--no-deps", "--python", str(python), str(wheel)], "installing the English language data")
    if not _english_data_installed(python):
        raise RuntimeError("The English language data was installed but cannot be loaded.")


def install_kokoro() -> Dict[str, Any]:
    needed = system_runtime.missing_runtime_message("The fast voice")
    if needed:
        return {"success": False, "error": needed}
    directory, python = KokoroTTSClient._SERVER_DIR, KokoroTTSClient._SERVER_VENV_PYTHON
    directory.mkdir(parents=True, exist_ok=True)
    install_progress.begin(6)
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
                raise RuntimeError(system_runtime.import_failure(python, "import torch, kokoro, pyopenjtalk, soundfile", "Kokoro"))
        files = MODEL_FILES + [f"voices/{name}.pt" for name in tuning.KOKORO_VOICES]
        _run(
            [str(python), "-c",
             "from huggingface_hub import hf_hub_download as d\n"
             f"for f in {files!r}: d('hexgrad/Kokoro-82M', f)"],
            "downloading the model and the voices",
        )
        KokoroTTSClient._READY_FILE.write_text("ok", encoding="utf-8")
        uv = find_uv()
        if not uv:
            raise RuntimeError("Adding the English voices needs uv (https://docs.astral.sh/uv/). Install it, then try again.")
        _install_english_data(python, uv)
        KokoroTTSClient._ENGLISH_READY_FILE.write_text("ok", encoding="utf-8")
    except RuntimeError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "ready": True}
