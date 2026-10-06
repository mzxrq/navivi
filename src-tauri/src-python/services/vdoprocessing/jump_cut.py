"""Zoom In / Zoom Out as a jump cut: a wide shot, then a hard cut to the photo
full frame (reversed for Zoom Out). The wide shot is the photo in the middle
with SDXL-outpainted surroundings (ATTRACTION_JUMP_CUT_AI), else a crop."""

import subprocess
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image, ImageFilter, ImageOps

from services import tuning
from services.logger.logger import setup_logger

logger = setup_logger("JumpCut")

_AI_SUFFIX = (
    ", the same place continuing naturally in every direction around it, wide-angle travel photography, "
    "photorealistic, natural daylight, matching lighting and perspective"
)


def upscaled_photo(image_path: str, config_path: Optional[Path]) -> str:
    """The photo's upscaled copy, upscaling it first if it hasn't been yet.
    The photo itself when it is big enough, upscale is off, or it fails."""
    from services.vdoprocessing.videopipeline.helpers import output_is_valid
    from services.vdoprocessing.videopipeline.upscale_step import (
        cached_path, needs_upscale, upscale_waypoint_images,
    )

    if not needs_upscale(image_path) or config_path is None:
        return image_path
    out = cached_path(config_path.parent, image_path)
    if not output_is_valid(out):
        upscale_waypoint_images(str(config_path))
    if output_is_valid(out):
        return str(out)
    logger.warning("No upscaled copy of %s - jump cut from the original.", image_path)
    return image_path


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    return ImageOps.fit(img, (w, h), Image.LANCZOS)


def _inner_box(w: int, h: int) -> tuple:
    iw, ih = round(w * tuning.ATTRACTION_JUMP_CUT_TIGHT), round(h * tuning.ATTRACTION_JUMP_CUT_TIGHT)
    return (w - iw) // 2, (h - ih) // 2, iw, ih


def _ring_mask(w: int, h: int, feather: int) -> Image.Image:
    """255 outside the inner box, 0 inside, softened across its edge."""
    x, y, iw, ih = _inner_box(w, h)
    mask = Image.new("L", (w, h), 255)
    mask.paste(0, (x + feather, y + feather, x + iw - feather, y + ih - feather))
    return mask.filter(ImageFilter.GaussianBlur(feather / 2))


def outpaint_wide(photo: Image.Image, out_w: int, out_h: int) -> Image.Image:
    """out_w x out_h: the photo (cover-framed) at JUMP_CUT_TIGHT in the middle,
    SDXL fills the ring, then the real photo is pasted back over the middle.
    Raises on any failure."""
    from services.vdoprocessing import local_pan_generator as lpg

    if not lpg._cuda_available():
        raise RuntimeError("no CUDA for the SDXL outpaint")
    cw, ch = tuning.ATTRACTION_JUMP_CUT_AI_SIZE
    x, y, iw, ih = _inner_box(cw, ch)
    inner = np.array(_cover(photo, iw, ih))
    seed = cv2.copyMakeBorder(inner, y, ch - ih - y, x, cw - iw - x, cv2.BORDER_REFLECT)
    mask = _ring_mask(cw, ch, tuning.ATTRACTION_JUMP_CUT_AI_FEATHER)

    prompt = lpg._describe_scene(photo) + _AI_SUFFIX
    logger.info("Jump cut outpaint prompt: %s", prompt)
    result = lpg._get_pipe()(
        prompt=prompt, negative_prompt=lpg.NEGATIVE_PROMPT, image=Image.fromarray(seed), mask_image=mask,
        width=cw, height=ch, num_inference_steps=lpg.STEPS, guidance_scale=lpg.GUIDANCE,
        strength=tuning.ATTRACTION_JUMP_CUT_AI_STRENGTH,
    ).images[0]
    lpg._free_gpu_memory()

    wide = result.convert("RGB").resize((out_w, out_h), Image.LANCZOS)
    x, y, iw, ih = _inner_box(out_w, out_h)
    sharp = Image.new("RGB", (out_w, out_h))
    sharp.paste(_cover(photo, iw, ih), (x, y))
    feather = round(tuning.ATTRACTION_JUMP_CUT_AI_FEATHER * out_w / cw)
    keep = ImageOps.invert(_ring_mask(out_w, out_h, feather))
    return Image.composite(sharp, wide, keep)


def _ai_wide_png(photo_path: str, output_path: str) -> Optional[str]:
    """The outpainted wide frame saved beside the clip, None on failure."""
    if not tuning.ATTRACTION_JUMP_CUT_AI:
        return None
    try:
        with Image.open(photo_path) as im:
            photo = ImageOps.exif_transpose(im).convert("RGB")
        wide = outpaint_wide(photo, tuning.COMFYUI_WIDTH, tuning.COMFYUI_HEIGHT)
    except Exception as exc:
        logger.warning("Jump cut outpaint failed for %s (%s: %s) - cropping instead.",
                       photo_path, type(exc).__name__, exc)
        return None
    path = str(Path(output_path).with_suffix(".wide.png"))
    wide.save(path)
    return path


def generate_jump_cut(image_path: str, output_path: str, duration_sec: float, preset: str) -> Optional[str]:
    """Wide then tight ("zoomin"), or tight then wide ("zoomout"); the cut lands
    at ATTRACTION_JUMP_CUT_AT of the clip. None if ffmpeg fails."""
    from services.tts.ttsengine import FFmpegManager

    w, h = tuning.COMFYUI_WIDTH, tuning.COMFYUI_HEIGHT
    total = max(1.0, duration_sec)
    first = total * tuning.ATTRACTION_JUMP_CUT_AT
    shot = "scale={}:{}:force_original_aspect_ratio=increase:flags=lanczos,crop={}:{}".format
    wide_png = _ai_wide_png(image_path, output_path)
    if wide_png:
        inputs, pre = [wide_png, image_path], ""
        wide, tight = f"[0:v]{shot(w, h, w, h)}", f"[1:v]{shot(w, h, w, h)}"
    else:
        # The punch-in is cropped from the full-size photo, not the wide frame.
        tw, th = round(w / tuning.ATTRACTION_JUMP_CUT_TIGHT), round(h / tuning.ATTRACTION_JUMP_CUT_TIGHT)
        inputs, pre = [image_path], "[0:v]split[p0][p1];"
        wide, tight = f"[p0]{shot(w, h, w, h)}", f"[p1]{shot(tw, th, tw, th)},crop={w}:{h}"
    a, b = (tight, wide) if preset == "zoomout" else (wide, tight)
    graph = (
        f"{pre}{a},trim=duration={first:.3f},setpts=PTS-STARTPTS[s0];"
        f"{b},trim=duration={total - first:.3f},setpts=PTS-STARTPTS[s1];"
        f"[s0][s1]concat=n=2:v=1,fps={tuning.COMFYUI_FPS},format=yuv420p[v]"
    )
    cmd = [FFmpegManager.resolve_ffmpeg_bin(), "-y", *tuning.ffmpeg_log_args()]
    for path in inputs:
        cmd += ["-loop", "1", "-framerate", str(tuning.COMFYUI_FPS), "-i", path]
    cmd += [
        "-filter_complex", graph, "-map", "[v]", "-t", f"{total:.3f}",
        "-c:v", "libx264", *tuning.ffmpeg_thread_args(), "-crf", "18", "-preset", "fast",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        logger.error("Jump cut failed for %s: %s", image_path, result.stderr.strip())
        return None
    logger.info("Jump cut (%s%s) for %s -> %s", preset, ", AI wide" if wide_png else "",
                Path(image_path).name, output_path)
    return output_path
