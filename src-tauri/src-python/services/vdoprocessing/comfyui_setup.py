"""Sets up the moving attraction videos: ComfyUI under bin/ComfyUI, its own venv, the GGUF node and the video models.

Two model families are needed because the editor's six camera presets run on LTX-Video (ltx_keyframed) and every other
clip runs on Wan2.2 (comfyui_i2v_client). Together that is about 26 GB of models plus about 3 GB for PyTorch, so the
checks happen before anything is downloaded: an NVIDIA GPU (Wan and LTX are unusable on a CPU) and enough free disk.

The source is a pinned ComfyUI release and a pinned ComfyUI-GGUF commit, fetched as zips (no git), because the workflow
graphs in comfyui_i2v_client / ltx_keyframed name nodes that newer releases may rename. Every model file is streamed to a
`.part` file, resumed with a Range request when a download was cut short, and checked against its sha256 before it is used.
Idempotent like the voice setups: finished steps are skipped, so a cancelled or failed run just continues next time.

Rust cancels a running sidecar call when another one starts, so the UI keeps the user on the Setup tab while this runs."""

import hashlib
import io
import shutil
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx

from services import install_progress, system_runtime, tuning
from services.logger.logger import setup_logger
from services.tts.irodori_setup import pick_backend
from services.tts.kokoro_setup import _run, find_uv
from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient

logger = setup_logger("ComfyUISetup")

COMFYUI_TAG = "v0.39.0"
COMFYUI_ZIP = f"https://github.com/comfyanonymous/ComfyUI/archive/refs/tags/{COMFYUI_TAG}.zip"
GGUF_COMMIT = "6ea2651e7df66d7585f6ffee804b20e92fb38b8a"
GGUF_ZIP = f"https://github.com/city96/ComfyUI-GGUF/archive/{GGUF_COMMIT}.zip"
PYTHON_VERSION = "3.12"
TORCH_INDEX = "https://download.pytorch.org/whl/cu128"

# What is free on the disk before a download starts: the models (about 25.8 GB), PyTorch and ComfyUI's packages.
REQUIRED_FREE_GB = 32

# The Wan2.2 files of tuning.COMFYUI_MODEL == "5b" (sizes and sha256 from the Hugging Face file listing, 2026-10-06).
WAN_FILES: Dict[str, Dict[str, Any]] = {
    "unet": {
        "folder": "diffusion_models", "file": tuning.COMFYUI_UNET_NAME, "bytes": 3437927136,
        "url": "https://huggingface.co/hum-ma/Wan2.2-TI2V-5B-Turbo-GGUF/resolve/main/Wan2_2-TI2V-5B-Turbo-Q4_K_M.gguf",
        "sha256": "13b3bee8fcafd9f9a3778ed1a0ca973f4a7d152094ea305f8384b0abd7e1ad51",
    },
    "text_encoder": {
        "folder": "text_encoders", "file": tuning.COMFYUI_CLIP_NAME, "bytes": 6735906897,
        "url": "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
        "sha256": "c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68",
    },
    "vae": {
        "folder": "vae", "file": tuning.COMFYUI_VAE_NAME, "bytes": 1409400960,
        "url": "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/vae/wan2.2_vae.safetensors",
        "sha256": "e40321bd36b9709991dae2530eb4ac303dd168276980d3e9bc4b6e2b75fed156",
    },
}
LTXV_SIZES = {"unet": 6506980352, "vae": 2493859452, "text_encoder": 5157348688}

Fetch = Callable[[str], bytes]


def model_files() -> List[Dict[str, Any]]:
    """Every model file the attraction clips can ask for, with where it goes."""
    if tuning.COMFYUI_MODEL != "5b":
        raise RuntimeError(f"The installer only knows the Wan2.2 5B models; tuning.COMFYUI_MODEL is {tuning.COMFYUI_MODEL!r}.")
    ltx = [{**spec, "bytes": LTXV_SIZES[key]} for key, spec in tuning.LTXV_FILES.items()]
    return [*WAN_FILES.values(), *ltx]


def _path(spec: Dict[str, Any]) -> Path:
    return ComfyUII2VClient._SERVER_DIR / "models" / spec["folder"] / spec["file"]


def source_present(directory: Path) -> bool:
    return (directory / "main.py").exists() and (directory / "comfy").is_dir()


def gguf_present(directory: Path) -> bool:
    return (directory / "custom_nodes" / "ComfyUI-GGUF" / "nodes.py").exists()


def missing_models() -> List[str]:
    """File names that are absent or the wrong size (a finished download always has the exact size)."""
    return [spec["file"] for spec in model_files() if not (_path(spec).is_file() and _path(spec).stat().st_size == spec["bytes"])]


def is_ready() -> bool:
    directory, python = ComfyUII2VClient._SERVER_DIR, ComfyUII2VClient._SERVER_VENV_PYTHON
    try:
        return source_present(directory) and gguf_present(directory) and python.exists() and not missing_models()
    except RuntimeError:
        return False


def fetch_zip(url: str) -> bytes:
    logger.info("ComfyUI setup: downloading %s", url)
    response = httpx.get(url, follow_redirects=True, timeout=300.0)
    response.raise_for_status()
    return response.content


def unpack_source(archive: bytes, directory: Path) -> None:
    """Extracts a GitHub source zip (one top folder) into `directory`. Models, input and output stay as they are."""
    directory.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        for info in zf.infolist():
            parts = Path(info.filename).parts[1:]
            if not parts or info.is_dir():
                continue
            target = directory.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(info))


def check_requirements(directory: Path, free_gb: Optional[float] = None) -> None:
    """Refuses before any download when the PC cannot run the models or the disk is too small."""
    if pick_backend() != "cu128":
        raise RuntimeError("Moving attraction videos need an NVIDIA graphics card. Without one, the clips pan across the photo instead.")
    directory.mkdir(parents=True, exist_ok=True)
    if free_gb is None:
        free_gb = shutil.disk_usage(directory).free / 1024 ** 3
    # What is already downloaded does not count against the space still needed.
    have = sum(_path(s).stat().st_size for s in model_files() if _path(s).is_file()) / 1024 ** 3
    if free_gb + have < REQUIRED_FREE_GB:
        raise RuntimeError(f"Moving attraction videos need about {REQUIRED_FREE_GB} GB of free disk space; {free_gb:.0f} GB is free.")


def download_model(spec: Dict[str, Any], client: Optional[httpx.Client] = None) -> None:
    """Downloads one model file, resuming a `.part` file, and keeps it only if its sha256 matches."""
    final = _path(spec)
    if final.is_file() and final.stat().st_size == spec["bytes"]:
        return
    part = final.with_name(final.name + ".part")
    final.parent.mkdir(parents=True, exist_ok=True)
    have = part.stat().st_size if part.exists() else 0
    if have > spec["bytes"]:
        part.unlink()
        have = 0
    own = client is None
    client = client or httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60.0, read=120.0))
    try:
        if have < spec["bytes"]:
            headers = {"Range": f"bytes={have}-"} if have else {}
            with client.stream("GET", spec["url"], headers=headers) as response:
                response.raise_for_status()
                if have and response.status_code != 206:
                    have = 0  # the server ignored the Range header and is sending the whole file
                done, next_log = have, have
                with open(part, "ab" if have else "wb") as f:
                    for chunk in response.iter_bytes(1 << 20):
                        f.write(chunk)
                        done += len(chunk)
                        if done - next_log >= spec["bytes"] // 20:
                            next_log = done
                            logger.info("ComfyUI setup: %s %d%%", spec["file"], 100 * done // spec["bytes"])
    finally:
        if own:
            client.close()
    digest = hashlib.sha256()
    with open(part, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            digest.update(chunk)
    if digest.hexdigest() != spec["sha256"]:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"{spec['file']} was damaged in the download (checksum mismatch). Try again.")
    part.replace(final)


def _imports_work(python: Path) -> bool:
    import subprocess

    check = subprocess.run([str(python), "-c", "import torch, gguf, yaml; assert torch.cuda.is_available()"], capture_output=True, encoding="utf-8", errors="replace")
    return check.returncode == 0


def install_comfyui(fetch: Optional[Fetch] = None, download: Optional[Callable[[Dict[str, Any]], None]] = None, free_gb: Optional[float] = None) -> Dict[str, Any]:
    directory, python = ComfyUII2VClient._SERVER_DIR, ComfyUII2VClient._SERVER_VENV_PYTHON
    fetch = fetch or fetch_zip
    download = download or download_model
    try:
        needed = system_runtime.missing_runtime_message("Moving attraction videos")
        if needed:
            raise RuntimeError(needed)
        check_requirements(directory, free_gb)
        install_progress.begin(5 + len(model_files()))
        if not source_present(directory):
            install_progress.step("downloading ComfyUI")
            unpack_source(fetch(COMFYUI_ZIP), directory)
        if not gguf_present(directory):
            unpack_source(fetch(GGUF_ZIP), directory / "custom_nodes" / "ComfyUI-GGUF")
        if not (python.exists() and _imports_work(python)):
            uv = find_uv()
            if not uv:
                raise RuntimeError("Setting up the moving attraction videos needs uv (https://docs.astral.sh/uv/). Install it, then try again.")
            if not python.exists():
                _run([uv, "venv", "--python", PYTHON_VERSION, str(directory / ".venv")], "creating the environment")
            # PyTorch first, all three together, from the CUDA index: otherwise uv may take a CPU build from PyPI for the requirements.
            _run([uv, "pip", "install", "--python", str(python), "--index-url", TORCH_INDEX, "torch", "torchvision", "torchaudio"], "installing PyTorch (CUDA build)")
            _run([uv, "pip", "install", "--python", str(python), "-r", str(directory / "requirements.txt")], "installing ComfyUI's packages")
            _run([uv, "pip", "install", "--python", str(python), "-r", str(directory / "custom_nodes" / "ComfyUI-GGUF" / "requirements.txt")], "installing the GGUF node's packages")
            if not _imports_work(python):
                raise RuntimeError("The packages installed, but PyTorch cannot use the graphics card. Update the NVIDIA driver and try again.")
        for spec in model_files():
            install_progress.step(f"downloading {spec['file']}")
            download(spec)
    except (RuntimeError, httpx.HTTPError, zipfile.BadZipFile, OSError) as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "ready": True}
