"""Per-clip timing sidecar shared by the render and export steps.

A residential leg clip opens with a silent lead-in (warm-up, start photo,
intro zoom) before the walker starts moving. pedestrian.py measures that
lead-in while rendering and writes it next to the clip; everything after
(leg padding, subtitle burn, timeline.json, final export) reads it back here
so the leg's narration — and its subtitles — start WITH the walk instead of
at the clip's first frame. Clips with no sidecar (overview, attraction,
intro/outro, 2D-fallback legs, legs cut into pieces) read as offset 0.

Kept dependency-free on purpose: pedestrian.py can't import from
videopipeline (circular), and the export side shouldn't import pydeck.
"""

import json
import os
from typing import Optional

_DERIVATIVE_SUFFIXES = ("_subtitled", "_padded")


def timing_sidecar_path(clip_path: str) -> str:
    """Sidecar path for a clip: next to it, named after its stem with any
    "_padded"/"_subtitled" derivative suffix stripped, so a padded or
    subtitle-burned copy finds the original render's sidecar."""
    stem, _ = os.path.splitext(str(clip_path))
    stripped = True
    while stripped:
        stripped = False
        for suffix in _DERIVATIVE_SUFFIXES:
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
                stripped = True
    return f"{stem}.timing.json"


def read_audio_offset(clip_path: Optional[str]) -> float:
    """Seconds the clip's narration should be delayed by (0.0 if the clip
    has no sidecar, or it's unreadable)."""
    if not clip_path:
        return 0.0
    try:
        with open(timing_sidecar_path(clip_path), "r", encoding="utf-8") as f:
            value = float(json.load(f).get("audio_offset_seconds", 0.0))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return 0.0
    return value if value > 0 else 0.0


def write_audio_offset(clip_path: str, seconds: float) -> None:
    """Records how long the clip's narration must be delayed (see module docstring)."""
    try:
        with open(timing_sidecar_path(clip_path), "w", encoding="utf-8") as f:
            json.dump({"audio_offset_seconds": round(float(seconds), 3)}, f)
    except OSError:
        pass
