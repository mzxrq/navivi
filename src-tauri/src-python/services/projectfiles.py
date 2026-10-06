"""Where a project keeps the files the app and the pipeline generate for it.

A project folder holds the user's own work at the top (job_config.json, timeline.json, thumbnail.png,
raw_track.gpx, assets/); everything generated for bookkeeping lives in `.navivi/`. Files used to sit in
the root (`.routecache.json`, `.narration_cues.json`, ...): readers fall back to those names so a project
that has not been tidied yet still works, writers always use the new place.
"""

import os
from pathlib import Path
from typing import Union

META_DIR = ".navivi"

ROUTE_CACHE = ("routecache.json", ".routecache.json")
NARRATION_CUES = ("narration_cues.json", ".narration_cues.json")
OVERVIEW_NARRATION = ("overview_narration.json", ".overview_narration.json")

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
