"""Reuse of the intro/outro clips: each one is rebuilt only when what it is made from changed.

The fingerprint covers the inputs passed in, the size and mtime of every file they name (photos,
route clips) and of the code that draws the clip, so a code or tuning change rebuilds it too.
Stored in <project>/.navivi/clip_inputs.json, one entry per clip filename.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Optional

from services.projectfiles import CLIP_INPUTS, meta_file, meta_path

from .helpers import logger


def _file_stamp(path: Any) -> Optional[list]:
    try:
        st = Path(str(path)).stat()
        return [str(path), st.st_size, int(st.st_mtime)]
    except (OSError, ValueError):
        return [str(path), None, None]


def fingerprint(inputs: Any, files: Iterable[Any] = ()) -> str:
    stamps = [_file_stamp(f) for f in files if f]
    blob = json.dumps([inputs, stamps], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def _load(project_dir: Path) -> dict:
    path = meta_file(project_dir, CLIP_INPUTS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def reusable(project_dir: Path, clip: Path, key: str) -> bool:
    """True when `clip` exists and was built from the same inputs."""
    if not clip.exists() or clip.stat().st_size == 0:
        return False
    if _load(project_dir).get(clip.name) != key:
        return False
    logger.info("%s: inputs unchanged — reusing %s.", clip.stem, clip.name)
    return True


def remember(project_dir: Path, clip: Path, key: str) -> None:
    data = _load(project_dir)
    data[clip.name] = key
    try:
        path = meta_path(project_dir, CLIP_INPUTS)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:  # only costs a rebuild next time
        logger.warning("Could not record %s's inputs: %s", clip.name, exc)

