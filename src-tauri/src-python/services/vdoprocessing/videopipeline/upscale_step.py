"""Step 2c: upscales waypoint photos smaller than the video frame, so the
fullscreen pop-ups and Wan's input aren't soft.

ESRGAN in the bundled ComfyUI, one photo per job. Kept inside 8 GB of VRAM:
the input is shrunk to IMAGE_UPSCALE_MAX_SIDE / scale first, the node tiles
at 512 px and assembles its output on the CPU, and a photo goes to a CPU
Lanczos resize instead when free VRAM is under IMAGE_UPSCALE_MIN_FREE_VRAM_MB
or the model can't be had (tuning.IMAGE_UPSCALE_MODEL, downloaded on first
use from tuning.IMAGE_UPSCALE_MODELS). Results are cached by content under
assets/image/upscaled/ and listed in map.json; the originals are untouched
(services/config/upscaled_images.py swaps the paths on load)."""

import hashlib
import json
import subprocess
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image, ImageFilter, ImageOps

from services import tuning
from services.config.upscaled_images import IMAGE_KEYS, map_path, upscale_dir, upscale_enabled
from services.logger.progress import tracker

from .helpers import logger, output_is_valid

_OUTPUT_NODE = "save"


def free_vram_mb() -> Optional[int]:
    """Free VRAM of the first GPU in MB, or None without nvidia-smi."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        return int(out.stdout.strip().splitlines()[0])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def needs_upscale(path: str) -> bool:
    if Path(path).suffix.lower() == ".svg":
        return False
    try:
        with Image.open(path) as im:
            w, h = ImageOps.exif_transpose(im).size
    except (OSError, ValueError):
        return False
    return w < tuning.IMAGE_UPSCALE_MIN_W or h < tuning.IMAGE_UPSCALE_MIN_H


def cover_size(w: int, h: int) -> tuple:
    """Smallest size covering MIN_W x MIN_H at the photo's aspect, longest side capped at MAX_SIDE."""
    scale = max(tuning.IMAGE_UPSCALE_MIN_W / w, tuning.IMAGE_UPSCALE_MIN_H / h)
    scale = min(scale, tuning.IMAGE_UPSCALE_MAX_SIDE / max(w, h))
    return max(1, round(w * scale)), max(1, round(h * scale))


def cached_path(project_dir, src: str) -> Path:
    digest = hashlib.sha1(Path(src).read_bytes())
    digest.update(f"{tuning.IMAGE_UPSCALE_MODEL}@{tuning.IMAGE_UPSCALE_KEEP_SCALE}".encode())
    digest.update(f"{tuning.IMAGE_UPSCALE_MIN_W}x{tuning.IMAGE_UPSCALE_MIN_H}".encode())
    return upscale_dir(project_dir) / f"{Path(src).stem}.{digest.hexdigest()[:10]}.png"


def _model_path() -> Path:
    from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient

    return ComfyUII2VClient._SERVER_DIR / "models" / "upscale_models" / tuning.IMAGE_UPSCALE_MODEL


def model_scale() -> int:
    return int(tuning.IMAGE_UPSCALE_MODELS.get(tuning.IMAGE_UPSCALE_MODEL, {}).get("scale", 4))


def _download(url: str, dest: Path) -> None:
    import httpx

    with httpx.stream(
        "GET", url, follow_redirects=True, timeout=tuning.IMAGE_UPSCALE_DOWNLOAD_TIMEOUT_SECONDS
    ) as response:
        response.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in response.iter_bytes(1 << 20):
                f.write(chunk)


def ensure_model() -> Optional[Path]:
    """The upscale model's path, downloading it first if it's missing.
    None when it can't be had (unknown name, offline, bad checksum)."""
    path = _model_path()
    if path.is_file():
        return path
    spec = tuning.IMAGE_UPSCALE_MODELS.get(tuning.IMAGE_UPSCALE_MODEL)
    if not spec:
        logger.warning(
            "Step 2c: %s isn't in tuning.IMAGE_UPSCALE_MODELS and isn't in %s.",
            tuning.IMAGE_UPSCALE_MODEL, path.parent,
        )
        return None
    part = path.with_name(path.name + ".part")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tracker.show(f"Downloading upscale model {tuning.IMAGE_UPSCALE_MODEL}...")
        logger.info("Step 2c: downloading %s from %s", tuning.IMAGE_UPSCALE_MODEL, spec["url"])
        _download(spec["url"], part)
        digest = hashlib.sha256()
        with open(part, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
        if spec.get("sha256") and digest.hexdigest() != spec["sha256"].lower():
            raise ValueError(f"sha256 mismatch ({digest.hexdigest()})")
        part.replace(path)
        return path
    except Exception as exc:
        logger.warning("Step 2c: could not download %s (%s).", tuning.IMAGE_UPSCALE_MODEL, exc)
        part.unlink(missing_ok=True)
        return None


def _build_graph(uploaded_name: str) -> dict:
    return {
        "load": {"class_type": "LoadImage", "inputs": {"image": uploaded_name}},
        "model": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": tuning.IMAGE_UPSCALE_MODEL}},
        "upscale": {
            "class_type": "ImageUpscaleWithModel",
            "inputs": {"upscale_model": ["model", 0], "image": ["load", 0]},
        },
        _OUTPUT_NODE: {
            "class_type": "SaveImage",
            "inputs": {"images": ["upscale", 0], "filename_prefix": f"upscale/{uuid.uuid4().hex[:8]}"},
        },
    }


def _upright_rgb(src: str) -> Image.Image:
    with Image.open(src) as im:
        return ImageOps.exif_transpose(im).convert("RGB")


def _cpu_upscale(src: str, out: Path) -> None:
    im = _upright_rgb(src)
    im = im.resize(cover_size(*im.size), Image.LANCZOS)
    im.filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2)).save(out)


def _gpu_upscale(client, src: str, out: Path) -> None:
    im = _upright_rgb(src)
    in_max = tuning.IMAGE_UPSCALE_MAX_SIDE // model_scale()
    if max(im.size) > in_max:
        im.thumbnail((in_max, in_max), Image.LANCZOS)
    staged = out.with_name(f"_in_{out.name}")
    raw = out.with_name(f"_raw_{out.name}")
    im.save(staged)
    try:
        client.run_image_graph(
            _build_graph, str(staged), _OUTPUT_NODE, str(raw),
            timeout=tuning.IMAGE_UPSCALE_TIMEOUT_SECONDS,
        )
        with Image.open(raw) as up:
            up = up.convert("RGB")
            keep = tuning.IMAGE_UPSCALE_KEEP_SCALE
            if keep and keep < model_scale():
                up = up.resize((im.width * keep, im.height * keep), Image.LANCZOS)
            up.resize(cover_size(*up.size), Image.LANCZOS).save(out)
    finally:
        for tmp in (staged, raw):
            tmp.unlink(missing_ok=True)


def _waypoint_images(config: dict, anchor: Path) -> List[str]:
    seen: Dict[str, str] = {}
    for wp in config.get("waypoints") or []:
        if not isinstance(wp, dict):
            continue
        for key in IMAGE_KEYS:
            value = wp.get(key)
            for p in value if isinstance(value, list) else [value]:
                if not isinstance(p, str) or not p.strip():
                    continue
                path = Path(p).expanduser()
                path = path if path.is_absolute() else (anchor / path)
                if path.is_file():
                    seen.setdefault(str(path.resolve()).lower(), str(path.resolve()))
    return list(seen.values())


def upscale_waypoint_images(config_file_path: str, force: bool = False) -> dict:
    """Writes upscaled copies of the project's small waypoint photos and
    map.json. Returns counts plus the original -> upscaled map."""
    config_path = Path(config_file_path)
    project_dir = config_path.parent
    config = json.loads(config_path.read_text(encoding="utf-8"))
    result = {"gpu": 0, "cpu": 0, "cached": 0, "skipped": 0, "failed": 0, "map": {}}
    if not upscale_enabled(config.get("settings", {})):
        logger.info("Step 2c: photo upscale is off for this project.")
        return result

    images = _waypoint_images(config, project_dir)
    todo = [p for p in images if needs_upscale(p)]
    result["skipped"] = len(images) - len(todo)
    out_dir = upscale_dir(project_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    use_gpu = bool(todo) and ensure_model() is not None
    if todo and not use_gpu:
        logger.warning(
            "Step 2c: no upscale model %s — resizing on the CPU instead.", tuning.IMAGE_UPSCALE_MODEL
        )
    client = None
    if use_gpu and todo:
        from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient

        client = ComfyUII2VClient()
        client.clear_queue()

    tracker.begin_substeps(len(todo))
    for i, src in enumerate(todo, start=1):
        tracker.show_item(i, f"Upscaling photo {i}/{len(todo)}: {Path(src).name}")
        out = cached_path(project_dir, src)
        if not force and output_is_valid(out):
            result["cached"] += 1
            result["map"][src] = str(out)
            continue
        try:
            done = False
            if client is not None:
                from services.gpu_cooldown import wait_for_gpu_cooldown

                wait_for_gpu_cooldown(f"upscale {Path(src).name}")
                free = free_vram_mb()
                if free is not None and free < tuning.IMAGE_UPSCALE_MIN_FREE_VRAM_MB:
                    logger.warning(
                        "Step 2c: only %d MB VRAM free (< %d) — CPU resize for %s.",
                        free, tuning.IMAGE_UPSCALE_MIN_FREE_VRAM_MB, src,
                    )
                else:
                    try:
                        _gpu_upscale(client, src, out)
                        result["gpu"] += 1
                        done = True
                    except Exception as exc:
                        logger.warning("Step 2c: ComfyUI upscale failed for %s (%s) — CPU resize.", src, exc)
            if not done:
                _cpu_upscale(src, out)
                result["cpu"] += 1
            result["map"][src] = str(out)
        except Exception as exc:
            logger.warning("Step 2c: could not upscale %s (%s) — keeping the original.", src, exc)
            out.unlink(missing_ok=True)
            result["failed"] += 1

    if client is not None:
        client.free_memory()

    map_path(project_dir).write_text(
        json.dumps(result["map"], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info(
        "Step 2c: %d upscaled on GPU, %d on CPU, %d cached, %d already large enough, %d failed.",
        result["gpu"], result["cpu"], result["cached"], result["skipped"], result["failed"],
    )
    return result
