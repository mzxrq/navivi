"""Where a project keeps the files the app and the pipeline generate for it.

A project folder holds the user's own work at the top (job_config.json, timeline.json, thumbnail.png,
raw_track.gpx, assets/); everything generated for bookkeeping lives in `.navivi/`. Files used to sit in
the root (`.routecache.json`, `.narration_cues.json`, ...): readers fall back to those names so a project
that has not been tidied yet still works, writers always use the new place.
"""

import json
import os
import time
from pathlib import Path
from typing import Any, Union

META_DIR = ".navivi"

ROUTE_CACHE = ("routecache.json", ".routecache.json")
NARRATION_CUES = ("narration_cues.json", ".narration_cues.json")
OVERVIEW_NARRATION = ("overview_narration.json", ".overview_narration.json")
CLIP_INPUTS = ("clip_inputs.json", ".clip_inputs.json")

PathLike = Union[str, os.PathLike]


def meta_dir(project_dir: PathLike) -> Path:
    return Path(project_dir) / META_DIR


def meta_path(project_dir: PathLike, names: tuple) -> Path:
    """Where `names` is written: always in .navivi (the folder is created)."""
    folder = meta_dir(project_dir)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / names[0]


def meta_file(project_dir: PathLike, names: tuple) -> Path:
    """Where `names` is read from: .navivi, else the old name in the project root."""
    current = meta_dir(project_dir) / names[0]
    if current.exists():
        return current
    legacy = Path(project_dir) / names[1]
    return legacy if legacy.exists() else current


def gps_data_dir(project_dir: PathLike) -> Path:
    return meta_dir(project_dir) / "gpsdata"


def _shared_cache_base() -> Path:
    override = os.environ.get("NAVIVI_CACHE_DIR")
    return Path(override) if override else Path.home() / "Documents" / "Navivi" / "Cache"


def tts_cache_dir() -> Path:
    """Narration lines already spoken, shared by every project."""
    return _shared_cache_base() / "tts"


def dictionary_cache_dir() -> Path:
    """Downloaded dictionaries (JMnedict), shared by every project."""
    return _shared_cache_base() / "dictionaries"


def tile_cache_dir() -> Path:
    """Map tiles are shared by every project (and never archived with one)."""
    return _shared_cache_base() / "tiles"


def write_atomic(path: "PathLike", data: Union[str, bytes]) -> None:
    """`data` written beside `path` first, then swapped in: a cancel or crash mid-write leaves the old
    file (or none), never a cut-off one that is trusted later. Retries the swap briefly while another
    process (the app reading it) has the file open, which Windows refuses."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.part")
    try:
        if isinstance(data, bytes):
            tmp.write_bytes(data)
        else:
            tmp.write_text(data, encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.1 * (attempt + 1))
    finally:
        tmp.unlink(missing_ok=True)


def write_json_atomic(path: "PathLike", obj: Any, **dump_kwargs: Any) -> None:
    write_atomic(path, json.dumps(obj, **{"ensure_ascii": False, "indent": 2, **dump_kwargs}))


def save_image_atomic(image: Any, path: "PathLike") -> None:
    """A PIL image saved like write_atomic, in the format its file extension names."""
    import io

    from PIL import Image

    buf = io.BytesIO()
    image.save(buf, format=Image.registered_extensions()[Path(path).suffix.lower()])
    write_atomic(path, buf.getvalue())


def replace_into(tmp: "PathLike", path: "PathLike") -> None:
    """A finished file written beside `path` (by ffmpeg, say) swapped in, with write_atomic's retry."""
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.1 * (attempt + 1))
