"""Sets up the balanced voice (Qwen3-TTS 0.6B Base): its own venv under bin/Qwen3-TTS, the packages, and the model files.

Its own venv because `qwen-tts` wants Python 3.12 (the Irodori venv is 3.10) and brings its own pinned transformers. Needs `uv`.
Idempotent, like kokoro_setup."""

from typing import Any, Dict

from services import tuning
from services.logger.logger import setup_logger
from services.tts.kokoro_setup import TORCH_INDEX, _run, find_uv
from services.tts.ttsengine import Qwen3TTSClient

logger = setup_logger("Qwen3Setup")

PYTHON_VERSION = "3.12"
PACKAGES = ["qwen-tts", "soundfile"]


def _imports_work(python) -> bool:
    import subprocess

    check = subprocess.run([str(python), "-c", "import torch, qwen_tts, soundfile"], capture_output=True, encoding="utf-8", errors="replace")
    return check.returncode == 0


def install_qwen3() -> Dict[str, Any]:
    directory, python = Qwen3TTSClient._SERVER_DIR, Qwen3TTSClient._SERVER_VENV_PYTHON
    directory.mkdir(parents=True, exist_ok=True)
    try:
        if not (python.exists() and _imports_work(python)):
            uv = find_uv()
            if not uv:
                raise RuntimeError("Setting up the balanced voice needs uv (https://docs.astral.sh/uv/). Install it, then try again.")
            if not python.exists():
                _run([uv, "venv", "--python", PYTHON_VERSION, str(directory / ".venv")], "creating the environment")
            _run([uv, "pip", "install", "--python", str(python), "--index-url", TORCH_INDEX, "torch"], "installing torch (CPU)")
            _run([uv, "pip", "install", "--python", str(python), *PACKAGES], "installing Qwen3-TTS")
            if not _imports_work(python):
                raise RuntimeError("The packages installed, but Qwen3-TTS could not be imported. See the log above.")
        _run(
            [str(python), "-c", f"from huggingface_hub import snapshot_download as d; d({tuning.QWEN3_MODEL!r})"],
            "downloading the model (about 2.5 GB)",
        )
        Qwen3TTSClient._READY_FILE.write_text("ok", encoding="utf-8")
    except RuntimeError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "ready": True}
