"""The waypoint editor's camera presets (WaypointEditor.tsx cameraPans:
none, pan-left, pan-right, pan-up, pan-down, zoom-in, zoom-out) as one
normalised key, shared by every attraction clip generator."""

from typing import Any

# "none" is not a camera move: the attraction clip is the photo itself, held
# still until its narration ends - no ComfyUI/Wan and no pan/zoom generation.
STILL_PRESET = "none"


def normalize_camera_pan(hint: Any) -> str:
    """"pan-right" / "Pan Right" / "pan_right" / "panright" -> "panright".
    A list (one entry per image) gives its first entry; nothing gives ""."""
    if isinstance(hint, list):
        hint = hint[0] if hint else None
    if not hint:
        return ""
    return str(hint).strip().lower().replace("-", "").replace("_", "").replace(" ", "")
