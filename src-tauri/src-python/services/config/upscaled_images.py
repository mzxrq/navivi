"""Points waypoint photo paths at their upscaled copies (see
videopipeline/upscale_step.py), in memory only. map.json lists original ->
upscaled; job_config.json itself always keeps the original paths."""

import json
from pathlib import Path
from typing import Any, Dict

from services import tuning

IMAGE_KEYS = ("popup_image", "images")


def upscale_dir(project_dir) -> Path:
    return Path(project_dir) / "assets" / "image" / "upscaled"


def map_path(project_dir) -> Path:
    return upscale_dir(project_dir) / "map.json"


def upscale_enabled(settings: Dict[str, Any]) -> bool:
    settings = settings or {}
    if settings.get("skip_rich_media", False):
        return False
    return bool(settings.get("upscale_popup_images", tuning.DEFAULT_UPSCALE_POPUP_IMAGES))


def _norm(path: str, anchor: Path) -> str:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = anchor / p
    return str(p.resolve()).lower()


def load_map(project_dir) -> Dict[str, str]:
    try:
        raw = json.loads(map_path(project_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def apply_upscaled_images(data: Dict[str, Any], project_dir) -> Dict[str, str]:
    """Swaps each waypoint photo for its upscaled copy where one exists.
    Returns {upscaled: original} so the caller can undo it before saving."""
    if not isinstance(data, dict) or not upscale_enabled(data.get("settings", {})):
        return {}
    anchor = Path(project_dir)
    mapping = {_norm(k, anchor): v for k, v in load_map(project_dir).items()}
    if not mapping:
        return {}

    reverse: Dict[str, str] = {}

    def swap(value):
        if not isinstance(value, str) or not value.strip():
            return value
        target = mapping.get(_norm(value, anchor))
        if target and Path(target).is_file():
            reverse[target] = value
            return target
        return value

    for wp in data.get("waypoints") or []:
        if not isinstance(wp, dict):
            continue
        for key in IMAGE_KEYS:
            value = wp.get(key)
            if isinstance(value, list):
                wp[key] = [swap(v) for v in value]
            elif value:
                wp[key] = swap(value)
    return reverse


def restore_original_images(data: Dict[str, Any], reverse: Dict[str, str]) -> Dict[str, Any]:
    """A copy of `data` with the photo paths apply_upscaled_images swapped put back."""
    if not reverse:
        return data
    out = dict(data)
    waypoints = []
    for wp in data.get("waypoints") or []:
        if isinstance(wp, dict):
            wp = dict(wp)
            for key in IMAGE_KEYS:
                value = wp.get(key)
                if isinstance(value, list):
                    wp[key] = [reverse.get(v, v) if isinstance(v, str) else v for v in value]
                elif isinstance(value, str):
                    wp[key] = reverse.get(value, value)
        waypoints.append(wp)
    out["waypoints"] = waypoints
    return out
