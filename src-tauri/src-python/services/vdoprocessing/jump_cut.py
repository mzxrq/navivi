"""Zoom In / Zoom Out as a jump cut: a wide shot, then a hard cut to the photo
full frame (reversed for Zoom Out). The wide shot is the photo in the middle
with SDXL-outpainted surroundings (ATTRACTION_AI_SURROUNDINGS), else a crop."""

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


def _outpaint_file(photo_path: str, out_w: int, out_h: int, out_path: str) -> None:
    with Image.open(photo_path) as im:
        photo = ImageOps.exif_transpose(im).convert("RGB")
    outpaint_wide(photo, out_w, out_h).save(out_path)


def _run_outpaint(photo_path: str, out_w: int, out_h: int, out_path: str) -> None:
    """In a child process: SDXL's RAM only comes back to Windows when it exits
    (in-process, 7.5 GB stayed held and starved the LTXV walk after it)."""
    import sys

    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-m", "services.vdoprocessing.jump_cut", photo_path, str(out_w), str(out_h), out_path],
        cwd=root, capture_output=True, encoding="utf-8", errors="replace", timeout=1800,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "").strip()[-800:] or f"exit {result.returncode}")


def ai_wide_path(photo_path: str, out_w: int, out_h: int) -> Path:
    """Where the photo's AI wide frame is kept (one per photo, size and settings)."""
    import hashlib

    digest = hashlib.sha1(Path(photo_path).read_bytes())
    digest.update(f"{out_w}x{out_h}|{tuning.ATTRACTION_JUMP_CUT_TIGHT}|{tuning.ATTRACTION_JUMP_CUT_AI_SIZE}"
                  f"|{tuning.ATTRACTION_JUMP_CUT_AI_STRENGTH}".encode("utf-8"))
    return Path(photo_path).parent / "ai_wide" / f"{Path(photo_path).stem}.{digest.hexdigest()[:10]}.png"


def ai_wide(photo_path: str, out_w: int, out_h: int) -> Optional[Image.Image]:
    """The photo's outpainted wide frame at out_w x out_h, None when off or on
    any failure. Kept once per photo at LTXV size (a rerun skips SDXL); other
    sizes are scaled from it with the real photo pasted back sharp."""
    if not tuning.ATTRACTION_AI_SURROUNDINGS:
        return None
    try:
        kw, kh = tuning.LTXV_WIDTH, tuning.LTXV_HEIGHT
        path = ai_wide_path(photo_path, kw, kh)
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            part = path.with_name(f"_part_{path.name}")
            _run_outpaint(photo_path, kw, kh, str(part))
            part.replace(path)
        with Image.open(path) as im:
            wide = im.convert("RGB")
        if (out_w, out_h) == (kw, kh):
            return wide
        wide = wide.resize((out_w, out_h), Image.LANCZOS)
        with Image.open(photo_path) as im:
            photo = ImageOps.exif_transpose(im).convert("RGB")
        x, y, iw, ih = _inner_box(out_w, out_h)
        sharp = Image.new("RGB", (out_w, out_h))
        sharp.paste(_cover(photo, iw, ih), (x, y))
        feather = round(tuning.ATTRACTION_JUMP_CUT_AI_FEATHER * out_w / tuning.ATTRACTION_JUMP_CUT_AI_SIZE[0])
        return Image.composite(sharp, wide, ImageOps.invert(_ring_mask(out_w, out_h, feather)))
    except Exception as exc:
        logger.warning("AI outpaint failed for %s (%s: %s).", photo_path, type(exc).__name__, exc)
        return None


def _ai_wide_png(photo_path: str, output_path: str) -> Optional[str]:
    """The outpainted wide frame saved beside the clip, None on failure."""
    wide = ai_wide(photo_path, tuning.COMFYUI_WIDTH, tuning.COMFYUI_HEIGHT)
    if wide is None:
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


if __name__ == "__main__":
    import sys

    _outpaint_file(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4])
