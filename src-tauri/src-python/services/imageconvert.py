"""HEIC/HEIF photos (what iPhones save) to JPEG.

The webview cannot show HEIC and the pipeline reads photos with Pillow/OpenCV, so a HEIC photo is converted when it
is imported. The EXIF block is kept (the app reads each photo's GPS position from it) and the pixels are rotated
upright, with the orientation tag reset so nothing turns it a second time."""

from pathlib import Path
from typing import Dict, Iterable

HEIF_SUFFIXES = {".heic", ".heif"}
JPEG_QUALITY = 92

# Exif sub-directories Pillow only writes back once they have been read.
_EXIF_IFD = 0x8769
_GPS_IFD = 0x8825
_ORIENTATION = 0x0112


class HeifUnavailable(RuntimeError):
    pass


def is_heif(path) -> bool:
    return Path(path).suffix.lower() in HEIF_SUFFIXES


def _register_heif() -> None:
    try:
        import pillow_heif
    except ImportError as exc:
        raise HeifUnavailable(
            "HEIC photos need the pillow-heif package. Install it with: pip install pillow-heif"
        ) from exc
    pillow_heif.register_heif_opener()


def _free_name(out_dir: Path, stem: str) -> Path:
    candidate = out_dir / f"{stem}.jpg"
    n = 2
    while candidate.exists():
        candidate = out_dir / f"{stem}_{n}.jpg"
        n += 1
    return candidate


def convert_to_jpeg(src, out_dir) -> Path:
    """Writes `src` as a JPEG into `out_dir` (never over an existing file) and returns its path."""
    from PIL import Image, ImageOps

    _register_heif()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as opened:
        image = ImageOps.exif_transpose(opened)  # applies the orientation tag, and drops it from the copy
        exif = image.getexif()
        exif.get_ifd(_EXIF_IFD)
        exif.get_ifd(_GPS_IFD)
        exif[_ORIENTATION] = 1
        dest = _free_name(out_dir, Path(src).stem)
        image.convert("RGB").save(dest, "JPEG", quality=JPEG_QUALITY, exif=exif)
    return dest


def convert_images(paths: Iterable[str], out_dir) -> Dict[str, Dict[str, str]]:
    """Converts every HEIC/HEIF file in `paths`. Returns {"images": {source: jpeg}, "failed": {source: reason}};
    files that are not HEIC are left out of both."""
    images: Dict[str, str] = {}
    failed: Dict[str, str] = {}
    for path in paths:
        if not is_heif(path):
            continue
        try:
            images[str(path)] = str(convert_to_jpeg(path, out_dir))
        except HeifUnavailable:
            raise
        except Exception as exc:  # a damaged photo should not stop the others
            failed[str(path)] = f"{type(exc).__name__}: {exc}"
    return {"images": images, "failed": failed}
