"""Cinematic 3D camera move over the real photo: nothing is generated, so
nothing can appear, move or warp, and signs stay sharp.

Depth-Anything-V2 (tuning.PARALLAX_DEPTH_MODEL) estimates depth once and the
photo is split into depth layers, far to near. Each layer keeps its own
per-pixel depth and has what nearer layers hid filled in (classical
inpainting), so a near object can slide past without stretching. Every frame
re-projects the layers through a camera that trucks/dollies (near things move
and grow more), with motion blur, a focus pull from the foreground onto the
subject, a light vignette and film grain. Prototype:
services/model/depth_parallax_pan.py.
"""

import math
import subprocess
import tempfile
from typing import Callable, List, Optional, Tuple

import cv2
import numpy as np

from services import tuning
from services.logger.logger import setup_logger
from services.vdoprocessing.camera_pan import normalize_camera_pan
from services.vdoprocessing.clip_qc import read_image

logger = setup_logger("ParallaxGenerator")

OUT_W, OUT_H = 1920, 1080
_DEPTH_INPUT = 518
_PANS = ("panright", "panleft", "panup", "pandown")
_depth_pipe = None


def estimate_depth(photo_bgr: np.ndarray) -> np.ndarray:
    """0 = far, 1 = near, same size as the photo."""
    global _depth_pipe
    from PIL import Image

    if _depth_pipe is None:
        from transformers import pipeline

        logger.info("Loading %s on %s...", tuning.PARALLAX_DEPTH_MODEL, tuning.PARALLAX_DEVICE)
        _depth_pipe = pipeline(
            task="depth-estimation", model=tuning.PARALLAX_DEPTH_MODEL,
            device=0 if tuning.PARALLAX_DEVICE == "cuda" else -1,
        )
    h, w = photo_bgr.shape[:2]
    scale = _DEPTH_INPUT / max(h, w)
    small = cv2.resize(photo_bgr, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    depth = np.asarray(_depth_pipe(Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB)))["depth"], np.float32)
    depth = cv2.resize(depth, (w, h), interpolation=cv2.INTER_CUBIC)
    lo, hi = np.percentile(depth, 2), np.percentile(depth, 98)
    return np.clip((depth - lo) / max(hi - lo, 1e-6), 0, 1)


def _ease(t: float) -> float:
    """Smootherstep: gentle start and landing, like a camera on a slider."""
    t = min(max(t, 0.0), 1.0)
    return t * t * t * (t * (6 * t - 15) + 10)


def camera(preset: str, p: float) -> Tuple[float, float, float]:
    """(tx, ty, tz) at eased progress p: truck in frame widths/heights for a
    depth weight of 1, dolly as extra scale for a depth weight of 1."""
    a, z, drift = tuning.PARALLAX_PAN, tuning.PARALLAX_ZOOM, tuning.PARALLAX_ARC
    push = tuning.PARALLAX_PAN_PUSH * p
    if preset == "panright":
        return (p - 0.5) * a, 0.0, push
    if preset == "panleft":
        return (0.5 - p) * a, 0.0, push
    if preset == "panup":
        return 0.0, (0.5 - p) * a, push
    if preset == "pandown":
        return 0.0, (p - 0.5) * a, push
    if preset == "zoomout":
        return drift * (1 - p), 0.0, z * (1 - p)
    return drift * p, 0.0, z * p  # zoomin


def walk_camera(t: float, seconds: float) -> Tuple[float, float, float, float]:
    """(tx, ty, tz, roll degrees) at time share t of a POV walk: a steady dolly
    forward, the view dipping on every step, swaying and rolling every two."""
    steps = math.pi * tuning.PARALLAX_WALK_STEPS_PER_SEC * seconds * t
    p = t * t / 0.3 if t < 0.15 else t - 0.075  # brief start-up, then a steady pace
    return (
        tuning.PARALLAX_WALK_SWAY * math.sin(steps / 2),
        tuning.PARALLAX_WALK_BOB * (abs(math.sin(steps)) - 0.5),
        tuning.PARALLAX_WALK_DOLLY * p / 0.925,
        tuning.PARALLAX_WALK_ROLL_DEG * math.sin(steps / 2),
    )


def _roll(frame: np.ndarray, degrees: float) -> np.ndarray:
    """Turned about the centre, enlarged just enough to keep the corners filled."""
    if not degrees:
        return frame
    a = math.radians(abs(degrees))
    grow = math.cos(a) + math.sin(a) * max(OUT_W / OUT_H, OUT_H / OUT_W)
    m = cv2.getRotationMatrix2D((OUT_W / 2, OUT_H / 2), degrees, grow)
    return cv2.warpAffine(frame, m, (OUT_W, OUT_H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def margin_for(preset: str) -> float:
    if preset == "walk":
        return max(tuning.PARALLAX_WALK_SWAY, tuning.PARALLAX_WALK_BOB) + 0.02
    if preset in _PANS:
        return tuning.PARALLAX_PAN / 2 + 0.02
    return tuning.PARALLAX_ARC + 0.02


def _cover(photo: np.ndarray, depth: np.ndarray, margin: float):
    """Photo and depth scaled to cover the frame plus `margin` on every side."""
    h, w = photo.shape[:2]
    s = max(OUT_W * (1 + 2 * margin) / w, OUT_H * (1 + 2 * margin) / h)
    size = (math.ceil(w * s), math.ceil(h * s))
    return (
        cv2.resize(photo, size, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC),
        cv2.resize(depth, size, interpolation=cv2.INTER_LINEAR),
    )


_lama = None


def _lama_model():
    """The LaMa TorchScript model on the CPU, downloaded on first use; None
    when it can't be had."""
    global _lama
    if _lama is not None:
        return _lama or None
    import hashlib

    import torch

    from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient
    from services.vdoprocessing.videopipeline.upscale_step import _download

    spec = tuning.PARALLAX_LAMA
    path = ComfyUII2VClient._SERVER_DIR / "models" / "inpaint" / spec["file"]
    try:
        if not path.is_file():
            part = path.with_name(path.name + ".part")
            path.parent.mkdir(parents=True, exist_ok=True)
            logger.info("Downloading %s from %s", spec["file"], spec["url"])
            _download(spec["url"], part)
            digest = hashlib.sha256()
            with open(part, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    digest.update(chunk)
            if digest.hexdigest() != spec["sha256"]:
                part.unlink(missing_ok=True)
                raise ValueError(f"sha256 mismatch ({digest.hexdigest()})")
            part.replace(path)
        _lama = torch.jit.load(str(path), map_location="cpu").eval()
    except Exception as exc:
        logger.warning("LaMa unavailable (%s) - using the plain fill.", exc)
        _lama = False
    return _lama or None


def _lama_fill(image: np.ndarray, hole: np.ndarray) -> Optional[np.ndarray]:
    model = _lama_model()
    if model is None:
        return None
    import torch

    h, w = image.shape[:2]
    s = min(1.0, tuning.PARALLAX_LAMA_MAX_SIDE / max(h, w))
    sw, sh = max(8, round(w * s / 8) * 8), max(8, round(h * s / 8) * 8)
    img = cv2.resize(image, (sw, sh), interpolation=cv2.INTER_AREA)
    mask = (cv2.resize(hole, (sw, sh), interpolation=cv2.INTER_NEAREST) > 0).astype(np.float32)
    x = torch.from_numpy(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)).permute(2, 0, 1)[None].float() / 255
    m = torch.from_numpy(mask)[None, None]
    with torch.no_grad():
        y = model(x, m)[0].permute(1, 2, 0).numpy()
    if y.max() > 1.5:  # some exports return 0-255
        y = y / 255
    filled = cv2.cvtColor((np.clip(y, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
    return cv2.resize(filled, (w, h), interpolation=cv2.INTER_CUBIC)


def _fill(image: np.ndarray, hole: np.ndarray, learned: bool = False) -> np.ndarray:
    """image with `hole` (uint8 mask) filled from its surroundings. `learned`:
    LaMa when available (photo texture); otherwise OpenCV's Telea at a
    quarter size (fine for depth, smears on photos)."""
    h, w = image.shape[:2]
    if learned:
        filled = _lama_fill(image, hole)
        if filled is not None:
            out = image.copy()
            out[hole > 0] = filled[hole > 0]
            return out
    small = (max(1, w // 4), max(1, h // 4))
    filled = cv2.inpaint(
        cv2.resize(image, small, interpolation=cv2.INTER_AREA),
        cv2.resize(hole, small, interpolation=cv2.INTER_NEAREST), 5, cv2.INPAINT_TELEA,
    )
    filled = cv2.resize(filled, (w, h), interpolation=cv2.INTER_CUBIC)
    out = image.copy()
    out[hole > 0] = filled[hole > 0]
    return out


class _Layer:
    def __init__(self, texture, depth, alpha):
        self.texture, self.depth, self.alpha = texture, depth, alpha


def build_layers(image: np.ndarray, depth: np.ndarray, count: int) -> List[_Layer]:
    """Far to near. Layer k shows everything at least as near as its range
    (alpha), with anything nearer than its range filled in behind, so what a
    nearer layer reveals as it moves is layer k's own surroundings."""
    depth8 = (depth * 255).astype(np.uint8)
    if count == 2:
        # Split at the natural foreground/background break, so a pole or a
        # sign stays whole in one layer instead of being torn between two.
        # The sky (near 0) is left out, or the break found is sky vs scene.
        ground = depth8[depth8 > 20]
        if ground.size == 0 or ground.min() == ground.max():
            return [_Layer(image, depth, np.ones(depth.shape, np.float32))]  # nothing to split
        cut, _ = cv2.threshold(ground.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        edges = np.array([0.0, cut / 255.0, 1.0])
    else:
        edges = np.quantile(depth, np.linspace(0, 1, count + 1))
    # Generous fill margin: soft depth edges otherwise leave a ghost copy of
    # the near object in the layer behind it.
    pad = max(5, round(image.shape[1] / 120))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * pad + 1, 2 * pad + 1))
    layers = []
    for k in range(count):
        lo, hi = edges[k], edges[k + 1]
        alpha = np.ones(depth.shape, np.float32) if k == 0 else (depth >= lo).astype(np.float32)
        alpha = cv2.GaussianBlur(alpha, (0, 0), 1.2)
        if k < count - 1:
            hole = cv2.dilate((depth > hi - 0.03).astype(np.uint8) * 255, kernel)
            texture = _fill(image, hole, learned=True)
            layer_depth = _fill(depth8[..., None].repeat(3, 2), hole)[..., 0].astype(np.float32) / 255
            layer_depth = np.minimum(layer_depth, np.float32(hi))
        else:
            texture, layer_depth = image, depth
        layers.append(_Layer(texture, layer_depth, alpha))
    return layers


class _Projector:
    """Per-clip constants: each output pixel's spot in the covered photo, and
    each layer's depth weight there."""

    def __init__(self, layers: List[_Layer], rigid: bool = False):
        """rigid: each layer moves as one flat card at its median depth, so a
        sign spanning a depth gradient can't shear."""
        sh, sw = layers[0].depth.shape
        self.cx, self.cy = sw / 2, sh / 2
        u, v = np.meshgrid(np.arange(OUT_W, dtype=np.float32), np.arange(OUT_H, dtype=np.float32))
        self.bx, self.by = u + (self.cx - OUT_W / 2), v + (self.cy - OUT_H / 2)
        far = tuning.PARALLAX_FAR_WEIGHT
        if rigid:
            self.weights = [
                np.float32(far + (1 - far) * np.median(layer.depth[layer.alpha > 0.5] if k else layer.depth))
                for k, layer in enumerate(layers)
            ]
            return
        self.weights = [
            far + (1 - far) * cv2.remap(layer.depth, self.bx, self.by, cv2.INTER_LINEAR)
            for layer in layers
        ]

    def maps(self, k: int, cam: Tuple[float, ...]):
        """cam: (tx, ty, tz[, pan]) - pan shifts every depth alike (a turn)."""
        tx, ty, tz = cam[:3]
        pan = cam[3] if len(cam) > 3 else 0.0
        w = self.weights[k]
        s = 1 + tz * w
        return (
            self.cx + (self.bx - self.cx) / s + (tx * w + pan) * OUT_W,
            self.cy + (self.by - self.cy) / s + ty * OUT_H * w,
        )


def _render(layers: List[_Layer], proj: _Projector, cam) -> Tuple[np.ndarray, np.ndarray]:
    """(frame as float32 BGR, depth seen at each pixel)."""
    frame = depth = None
    for k, layer in enumerate(layers):
        mx, my = proj.maps(k, cam)
        tex = cv2.remap(layer.texture, mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT).astype(np.float32)
        d = cv2.remap(layer.depth, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        if frame is None:
            frame, depth = tex, d
            continue
        a = cv2.remap(layer.alpha, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        frame = frame + (tex - frame) * a[..., None]
        depth = depth + (d - depth) * a
    return frame, depth


def _focus_pull(frame: np.ndarray, depth: np.ndarray, focus: float) -> np.ndarray:
    """Out-of-focus blur growing with distance from the focus depth."""
    peak = tuning.PARALLAX_DOF_SIGMA
    if peak <= 0:
        return frame
    amount = np.clip(np.abs(depth - focus) / 0.5, 0, 1)[..., None]
    half = cv2.GaussianBlur(frame, (0, 0), peak / 2)
    full = cv2.GaussianBlur(frame, (0, 0), peak)
    low = frame + (half - frame) * np.clip(amount * 2, 0, 1)
    return low + (full - half) * np.clip(amount * 2 - 1, 0, 1)


def _finish(frame: np.ndarray, vignette: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    frame = frame * vignette[..., None]
    if tuning.PARALLAX_GRAIN > 0:
        grain = rng.normal(0, tuning.PARALLAX_GRAIN, (OUT_H // 2, OUT_W // 2)).astype(np.float32)
        frame = frame + cv2.resize(grain, (OUT_W, OUT_H), interpolation=cv2.INTER_LINEAR)[..., None]
    return np.clip(frame, 0, 255).astype(np.uint8)


def _vignette() -> np.ndarray:
    y, x = np.ogrid[-1:1:OUT_H * 1j, -1:1:OUT_W * 1j]
    r = np.sqrt(x * x + y * y) / math.sqrt(2)
    return (1 - tuning.PARALLAX_VIGNETTE * r ** 2.5).astype(np.float32)


def _focus_depths(depth: np.ndarray) -> Tuple[float, float]:
    """(start, end): the nearest things in view, then the subject - the
    middle of the frame, where the main building or sign usually sits."""
    h, w = depth.shape
    centre = depth[int(h * 0.3):int(h * 0.7), int(w * 0.3):int(w * 0.7)]
    return float(np.percentile(depth, 95)), float(np.median(centre))


def release_models() -> None:
    """Drops the depth and LaMa models (a few GB of RAM), e.g. before an LTXV job."""
    global _depth_pipe, _lama
    import gc

    _depth_pipe, _lama = None, None
    gc.collect()


def render_views(
    image_path: str, cams: List[Tuple[float, ...]], margin: float,
    depth_fn: Callable[[np.ndarray], np.ndarray] = estimate_depth,
) -> List[np.ndarray]:
    """The photo seen from each camera, OUT_W x OUT_H BGR, no film finish."""
    photo = read_image(image_path)
    if photo is None:
        raise RuntimeError(f"Cannot read {image_path}")
    image, depth = _cover(photo, depth_fn(photo), margin)
    layers = build_layers(image, depth, tuning.PARALLAX_LAYERS)
    proj = _Projector(layers, rigid=True)
    return [np.clip(_render(layers, proj, cam)[0], 0, 255).astype(np.uint8) for cam in cams]


def render_views_to_files(image_path: str, cams: List[Tuple[float, ...]], margin: float, out_paths: List[str]) -> None:
    """render_views in a child process, each view saved as a PNG: depth and LaMa
    RAM only goes back to Windows when the process exits (in the pipeline it
    stayed held, 7.6 GB, and starved the next LTXV shot - 2026-10-07)."""
    import json
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-m", "services.vdoprocessing.parallax_generator",
         json.dumps({"image": image_path, "cams": cams, "margin": margin, "out": out_paths})],
        cwd=root, capture_output=True, encoding="utf-8", errors="replace", timeout=1800,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "").strip()[-800:] or f"exit {result.returncode}")


def generate_parallax_clip(
    image_path: str,
    output_path: str,
    duration_sec: float,
    camera_pan_hint=None,
    depth_fn: Callable[[np.ndarray], np.ndarray] = estimate_depth,
    fps: Optional[float] = None,
) -> str:
    """A `duration_sec` 3D camera move over the photo, 1920x1080. Raises on failure."""
    from services.tts.ttsengine import FFmpegManager

    preset = normalize_camera_pan(camera_pan_hint)
    if preset not in _PANS + ("zoomin", "zoomout", "walk"):
        preset = "zoomin"
    photo = read_image(image_path)
    if photo is None:
        raise RuntimeError(f"Cannot read {image_path}")
    fps = fps or float(tuning.COMFYUI_FPS)
    frames = max(2, int(round(duration_sec * fps)))
    image, depth = _cover(photo, depth_fn(photo), margin_for(preset))
    layers = build_layers(image, depth, tuning.PARALLAX_LAYERS)
    proj = _Projector(layers)
    vignette = _vignette()
    focus_from, focus_to = _focus_depths(depth)
    rng = np.random.default_rng(0)
    # Shutter: sub-frames spread over this share of a frame, averaged.
    subs = max(1, tuning.PARALLAX_MOTION_BLUR_SAMPLES)
    shutter = 0.5 / max(1, frames - 1)

    # ffmpeg's messages go to a file, not a pipe that is only read at the end (a flood of warnings would fill it and hang).
    err = tempfile.TemporaryFile()
    proc = subprocess.Popen(
        [
            FFmpegManager.resolve_ffmpeg_bin(), "-y", *tuning.ffmpeg_pipe_log_args(),
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{OUT_W}x{OUT_H}", "-r", f"{fps:.3f}", "-i", "-",
            "-c:v", "libx264", *tuning.ffmpeg_thread_args(), "-crf", "17", "-preset", "fast",
            "-pix_fmt", "yuv420p", output_path,
        ],
        stdin=subprocess.PIPE, stderr=err,
    )
    try:
        for i in range(frames):
            t = i / (frames - 1)
            acc = seen = None
            for j in range(subs):
                ts = t - shutter * j / max(1, subs - 1) if subs > 1 else t
                if preset == "walk":
                    *cam, roll = walk_camera(max(ts, 0.0), duration_sec)
                    img, d = _render(layers, proj, tuple(cam))
                    img = _roll(img, roll)
                else:
                    img, d = _render(layers, proj, camera(preset, _ease(ts)))
                acc = img if acc is None else acc + img
                seen = d if seen is None else seen
            frame = acc / subs
            # Focus lands on the subject over the first half of the move.
            focus = focus_from + (focus_to - focus_from) * _ease(min(1.0, t * 2))
            frame = _focus_pull(frame, seen, focus)
            proc.stdin.write(_finish(frame, vignette, rng).tobytes())
        proc.stdin.close()
        if proc.wait() != 0:
            err.seek(0)
            raise RuntimeError(f"Parallax encode failed: {err.read().decode('utf-8', 'replace')}")
    except Exception:
        proc.kill()
        raise
    finally:
        err.close()
    logger.info("3D photo %s %.1fs over %s -> %s", preset, duration_sec, image_path, output_path)
    return output_path


if __name__ == "__main__":
    import json
    import sys

    job = json.loads(sys.argv[1])
    for path, view in zip(job["out"], render_views(job["image"], [tuple(c) for c in job["cams"]], job["margin"])):
        cv2.imencode(".png", view)[1].tofile(path)
