"""A sharpened copy of a photo, for the picture ComfyUI animates (settings.upscale_popup_images,
the editor's "Sharpen photos"). A photo the upscale step already enlarged is sharp enough and is
left alone; a photo that was big enough to skip it is only sharpened here."""

import hashlib
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

from services import tuning
from services.config.upscaled_images import upscale_dir
from services.logger.logger import setup_logger

logger = setup_logger("PhotoSharpen")


def sharpened_dir(project_dir) -> Path:
    return Path(project_dir) / "assets" / "image" / "sharpened"


def sharpened_photo(path: str, project_dir) -> str:
    """The cached sharpened PNG of `path`, made first if needed; `path` itself when it is already an
    upscaled copy or anything goes wrong."""
    source = Path(path)
    try:
        if upscale_dir(project_dir) in source.resolve().parents:
            return path
        stat = source.stat()
        tag = f"{source.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{tuning.PHOTO_SHARPEN_MAX_SIDE}"
        tag += f"|{tuning.PHOTO_SHARPEN_RADIUS}|{tuning.PHOTO_SHARPEN_PERCENT}"
        out = sharpened_dir(project_dir) / f"{hashlib.sha1(tag.encode('utf-8')).hexdigest()[:16]}.png"
        if out.is_file() and out.stat().st_size > 0:
            return str(out)
        with Image.open(source) as im:
            image = ImageOps.exif_transpose(im).convert("RGB")
        longest = max(image.size)
        if longest > tuning.PHOTO_SHARPEN_MAX_SIDE:
            scale = tuning.PHOTO_SHARPEN_MAX_SIDE / longest
            image = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
        image = image.filter(ImageFilter.UnsharpMask(
            radius=tuning.PHOTO_SHARPEN_RADIUS, percent=tuning.PHOTO_SHARPEN_PERCENT, threshold=2,
        ))
        out.parent.mkdir(parents=True, exist_ok=True)
        part = out.with_suffix(".part")
        image.save(part, format="PNG")
        part.replace(out)  # whole file or nothing
        return str(out)
    except Exception as exc:  # the photo is still usable as it is
        logger.warning("Could not sharpen %s (%s); using it as it is.", path, exc)
        return path
