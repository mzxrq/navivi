"""Local (no ComfyUI/video-diffusion) image-to-video generator for attraction
clips: an AI-outpainted, auto-captioned still image panned/zoomed with plain
OpenCV crop-and-resize. Replaces the ComfyUI/LTX-2 image+audio-to-video path.

Why: LTX-2 (run via ComfyUI, at the low step counts / Q2_K quantization an
8GB card forces) produced unreliable results — near-static output unless
heavily prompted, and prone to "melting"/temporal drift over longer clips.
This module instead does one static AI generation (outpainting the frame's
edges, no per-frame video diffusion) plus deterministic pan/zoom — no
melting risk, and comfortably fits an 8GB card. See src-python/services/model/
(outpaint_pan.py, classic_pan.py, zoom_out_pan.py) for the exploration that
led here.
"""

import os
import uuid
import cv2
import numpy as np
import torch
from PIL import Image, ImageFilter
from diffusers import AutoPipelineForInpainting
from transformers import BlipForConditionalGeneration, BlipProcessor

from services import tuning
from services.logger.logger import setup_logger

logger = setup_logger("LocalPanGenerator")

# [HACK] [Animation] Loaded once and reused across every waypoint in a batch, instead of a fresh
# from_pretrained() + del per call. Reloading per waypoint (the original
# design) turned out to both balloon system RAM over a run — accelerate's
# enable_model_cpu_offload() hooks leave reference cycles that `del` +
# empty_cache() don't fully release, so each reload leaked on top of the
# last — and made later waypoints dramatically slower (one call went from
# ~20s to ~8 minutes partway through a 15-waypoint run), consistent with the
# CUDA/CPU allocators fighting fragmentation from the repeated churn. A
# single long-lived pipeline avoids both.
_pipe = None
_blip_model = None
_blip_processor = None
_MEMORY_FRACTION_SET = False


def _cap_memory_fraction() -> None:
    """Caps PyTorch's own CUDA allocator once per process so it raises a
    clean, catchable torch.cuda.OutOfMemoryError instead of the point where
    Windows' WDDM driver would otherwise silently spill into slow/unstable
    shared system memory — cheap insurance against a repeat of the VRAM-
    linked instability seen during earlier exploration."""
    global _MEMORY_FRACTION_SET
    if not _MEMORY_FRACTION_SET and torch.cuda.is_available():
        torch.cuda.set_per_process_memory_fraction(0.85, 0)
        _MEMORY_FRACTION_SET = True


def _get_pipe():
    global _pipe
    if _pipe is None:
        _cap_memory_fraction()
        logger.info("Loading SDXL inpainting pipeline (once, reused for the whole batch)...")
        _pipe = AutoPipelineForInpainting.from_pretrained(
            "diffusers/stable-diffusion-xl-1.0-inpainting-0.1",
            torch_dtype=torch.bfloat16,
        )
        # enable_model_cpu_offload() shuttles modules between CPU and GPU
        # VRAM as each is needed — meaningless (and raises "requires
        # accelerator, but not found") with no CUDA device to offload TO.
        # Observed in the wild: ComfyUI's own subprocess had a rough run
        # (a stalled/reset connection — see comfyui_i2v_client.py's
        # _wait_for_result) right before this fallback kicked in, and by
        # the time it did, torch.cuda.is_available() came back False here —
        # this used to hard-fail the outpaint step outright (silently
        # degrading to a plain, non-outpainted pan) instead of just running
        # the pipeline directly on whatever device is actually available.
        if torch.cuda.is_available():
            _pipe.enable_model_cpu_offload()
        else:
            logger.warning(
                "No CUDA device available — running the SDXL inpainting "
                "pipeline on CPU directly (slow) instead of GPU-offloaded."
            )
            _pipe.to("cpu")
        _pipe.vae.enable_slicing()
    return _pipe


def _get_blip():
    global _blip_model, _blip_processor
    if _blip_model is None:
        _cap_memory_fraction()
        logger.info("Loading BLIP captioner (once, reused for the whole batch)...")
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _blip_processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
        _blip_model = BlipForConditionalGeneration.from_pretrained(
            "Salesforce/blip-image-captioning-base"
        ).to(device)
    return _blip_model, _blip_processor

# --- Outpaint settings (see services/model/outpaint_pan.py for the tuning history) ---
WORK_H = 512                   # lower than the 688 used during exploration — keeps this
                                # fast enough for a per-waypoint production step
EXTEND_LEFT_FRAC = 0.35
EXTEND_RIGHT_FRAC = 0.35
STEPS = 30
GUIDANCE = 8.0
STRENGTH = 0.75                 # <1.0 so the model respects the mirrored seed instead of
                                 # generating from scratch (a flat fill reads as "wall")
MASK_FEATHER_PX = 12

CAPTION_SUFFIX = (
    ", open sky, natural daylight, wide-angle travel photography, the same scene "
    "continuing seamlessly to the left and right, photorealistic, matching lighting "
    "and perspective of the original photo"
)
NEGATIVE_PROMPT = (
    "wall, concrete wall, stone wall, brick wall, building, building facade, "
    "door, doorway, pillar, column, wooden frame, indoor, interior, room, "
    "furniture, architecture close-up, museum wall, gallery wall, "
    "duplicate object, duplicate vehicle, second train, extra train, "
    "disconnected object, floating debris, malformed, deformed, mangled, "
    "seam, border, collage, watermark, text, blurry, distorted, "
    "different lighting, different style, low quality"
)

# --- Pan/render settings ---
OUT_W, OUT_H = 1280, 704   # divisible by 32, matches the existing ComfyUI attraction
                            # clip resolution noted in img2vdo.py (upscaled later anyway)
FPS = 30


def _describe_scene(pil_img: Image.Image) -> str:
    """One-shot BLIP captioning so the outpaint prompt is grounded in
    whatever is actually in THIS photo, not a hand-written/stale prompt."""
    model, processor = _get_blip()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    inputs = processor(pil_img, return_tensors="pt").to(device)
    out = model.generate(**inputs, max_new_tokens=40)
    return processor.decode(out[0], skip_special_tokens=True).strip()


def _outpaint(raw: Image.Image) -> Image.Image:
    """SDXL inpainting checkpoint + mirror-seeded extension (see
    services/model/outpaint_pan.py). Returns a wider canvas; raises on any
    failure so the caller can fall back to a plain (non-outpainted) pan."""
    prompt = _describe_scene(raw) + CAPTION_SUFFIX
    logger.info("Outpaint prompt: %s", prompt)

    pipe = _get_pipe()

    src_aspect = raw.width / raw.height
    fit_h = WORK_H
    fit_w = int(fit_h * src_aspect)
    fitted = raw.resize((fit_w, fit_h), Image.LANCZOS)

    ext_l = int(fit_w * EXTEND_LEFT_FRAC)
    ext_r = int(fit_w * EXTEND_RIGHT_FRAC)
    canvas_w = fit_w + ext_l + ext_r
    canvas_h = fit_h

    # [NOTE] [Animation] Mirror-seeds the outpaint canvas by flipping strips
    # taken from the image's own left/right edges outward — gives SDXL a
    # coherent, non-blank starting point to inpaint from instead of a flat
    # fill, which the model otherwise tends to render as a wall (see
    # NEGATIVE_PROMPT above).
    fitted_np = np.array(fitted)
    parts = []
    if ext_l > 0:
        parts.append(fitted_np[:, :ext_l][:, ::-1])
    parts.append(fitted_np)
    if ext_r > 0:
        parts.append(fitted_np[:, -ext_r:][:, ::-1])
    canvas = Image.fromarray(np.concatenate(parts, axis=1))

    mask = Image.new("L", (canvas_w, canvas_h), 255)
    mask.paste(Image.new("L", (fit_w, fit_h), 0), (ext_l, 0))
    mask = mask.filter(ImageFilter.GaussianBlur(radius=MASK_FEATHER_PX))

    canvas_w8 = (canvas_w // 8) * 8
    canvas_h8 = (canvas_h // 8) * 8
    canvas = canvas.resize((canvas_w8, canvas_h8))
    mask = mask.resize((canvas_w8, canvas_h8))

    result = pipe(
        prompt=prompt,
        negative_prompt=NEGATIVE_PROMPT,
        image=canvas,
        mask_image=mask,
        width=canvas_w8,
        height=canvas_h8,
        num_inference_steps=STEPS,
        guidance_scale=GUIDANCE,
        strength=STRENGTH,
    ).images[0]

    # [NOTE] [Animation] Frees this generation's activations/latents (not the persistent pipe
    # itself) so peak VRAM doesn't creep up across waypoints.
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return result.convert("RGB").resize((canvas_w, canvas_h))


def _ease_in_out(t: float) -> float:
    return 0.5 - 0.5 * np.cos(np.pi * t)


def _contain_fit(sw: int, sh: int, out_aspect: float):
    if sw / sh > out_aspect:
        fit_h = sh
        fit_w = int(fit_h * out_aspect)
    else:
        fit_w = sw
        fit_h = int(fit_w / out_aspect)
    return fit_w, fit_h


def _crop_rect(cx: float, cy: float, half_w: float, half_h: float, sw: int, sh: int):
    half_w = min(half_w, sw / 2)
    half_h = min(half_h, sh / 2)
    cx = min(max(cx, half_w), sw - half_w)
    cy = min(max(cy, half_h), sh - half_h)
    return int(cx - half_w), int(cy - half_h), int(cx + half_w), int(cy + half_h)


# [NOTE] [Animation] Maps the job config's "camera_pans" hint strings (currently used as raw
# ComfyUI prompt text, e.g. "panright") to (pan_dx_sign, zoom_start, zoom_end).
# zoom<1 = zoomed in; zoom=1 = the widened canvas's own full "contain" fit.
_CAMERA_PAN_PRESETS = {
    "panright": (1, 0.85, 1.0),
    "panleft": (-1, 0.85, 1.0),
    "zoomin": (0, 1.0, 0.75),
    "zoomout": (0, 0.75, 1.0),
    "none": (0, 0.92, 0.92),
}
_DEFAULT_PRESET = (1, 0.85, 1.0)


def _resolve_camera_pan(camera_pan_hint) -> tuple:
    if isinstance(camera_pan_hint, list):
        camera_pan_hint = camera_pan_hint[0] if camera_pan_hint else None
    key = str(camera_pan_hint).strip().lower() if camera_pan_hint else ""
    return _CAMERA_PAN_PRESETS.get(key, _DEFAULT_PRESET)


def _render_pan(image: Image.Image, output_path: str, duration_sec: float, camera_pan_hint) -> None:
    pan_dx_sign, zoom_start, zoom_end = _resolve_camera_pan(camera_pan_hint)

    src = np.array(image.convert("RGB"))
    sh, sw = src.shape[:2]
    out_aspect = OUT_W / OUT_H
    fit_w, fit_h = _contain_fit(sw, sh, out_aspect)

    num_frames = max(1, int(duration_sec * FPS))
    raw_path = output_path + ".raw.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(raw_path, fourcc, FPS, (OUT_W, OUT_H))

    # [NOTE] [Animation] How far the crop center can drift across the pan —
    # scaled by the tightest zoom level so the crop rect never runs past the
    # source image edges regardless of pan direction.
    pan_budget = (sw - fit_w * min(zoom_start, zoom_end)) * 0.4
    cx0, cy0 = sw / 2, sh / 2

    for i in range(num_frames):
        t = _ease_in_out(i / max(1, num_frames - 1))
        zoom = zoom_start + (zoom_end - zoom_start) * t
        cx = cx0 + pan_dx_sign * pan_budget * t
        half_w, half_h = fit_w * zoom / 2, fit_h * zoom / 2
        x0, y0, x1, y1 = _crop_rect(cx, cy0, half_w, half_h, sw, sh)
        crop = src[y0:y1, x0:x1]
        frame = cv2.resize(crop, (OUT_W, OUT_H), interpolation=cv2.INTER_LANCZOS4)
        writer.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))

    writer.release()

    import subprocess
    subprocess.run(
        ["ffmpeg", "-y", "-i", raw_path, "-c:v", "libx264", *tuning.ffmpeg_thread_args(), "-crf", "20",
         "-preset", "medium", "-pix_fmt", "yuv420p", output_path],
        check=True, capture_output=True,
    )
    os.remove(raw_path)


def generate_local_clip(
    image_path: str,
    output_path: str,
    duration_sec: float,
    camera_pan_hint=None,
) -> str:
    """Generates one attraction clip locally: AI-outpaints the image's edges
    (auto-captioned prompt, mirror-seeded extension), then pans/zooms across
    the result per camera_pan_hint. Falls back to a plain (non-outpainted)
    pan over the original image on any outpaint failure — this step should
    never hard-fail a waypoint the way a ComfyUI/network issue could.
    """
    raw = Image.open(image_path).convert("RGB")

    try:
        wide = _outpaint(raw)
        logger.info("Outpaint succeeded for %s", image_path)
    except Exception as exc:
        logger.warning(
            "Outpaint failed for %s (%s: %s) - panning the plain image instead.",
            image_path, type(exc).__name__, exc,
        )
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        wide = raw

    _render_pan(wide, output_path, duration_sec, camera_pan_hint)
    return output_path


if __name__ == "__main__":
    import sys
    img = sys.argv[1] if len(sys.argv) > 1 else "test.jpg"
    out = sys.argv[2] if len(sys.argv) > 2 else f"local_clip_{uuid.uuid4().hex[:6]}.mp4"
    generate_local_clip(img, out, duration_sec=6.0, camera_pan_hint="panright")
    print(f"Saved {out}")
