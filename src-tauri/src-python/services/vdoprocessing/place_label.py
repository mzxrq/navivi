"""An attraction clip's place-name label, recorded beside the clip as <clip>.label.json.

When the label rides on the editor's text track (tuning.ATTRACTION_LABEL_ON_TEXT_TRACK)
the clip is finalized without it and the sidecar says so; build_timeline then
adds a text item for it. Clips finalized before that have no sidecar and keep
their burned-in label, so they never get a second one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


def label_sidecar(video_path) -> Path:
    return Path(video_path).with_suffix(".label.json")


def record_place_label(video_path, text: Optional[str], burned: bool) -> None:
    sidecar = label_sidecar(video_path)
    if not text:
        sidecar.unlink(missing_ok=True)
        return
    sidecar.write_text(json.dumps({"text": text, "burned": burned}, ensure_ascii=False), encoding="utf-8")


def unburned_place_label(video_path) -> Optional[str]:
    """The label to show on the text track, or None (no sidecar, or already burned in)."""
    try:
        data = json.loads(label_sidecar(video_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("burned") or not str(data.get("text") or "").strip():
        return None
    return str(data["text"])


# The look of today's burned label (tuning.ATTRACTION_LABEL_*: libass 288-line
# units x 3.75 = 1080p px): top-left, bold, thin outline, shown the whole clip.
DEFAULT_PLACE_LOOK = {
    "position": "top",
    "margin_v": 10,
    "align": "left",
    "margin_h": 22,
    "animation": "none",
    "title_style": {"font_size": 98, "bold": True, "outline_width": 3, "shadow": 3.75},
}
_LOOK_KEYS = ("position", "margin_v", "align", "margin_h", "animation")


def place_text_item(text: str, look: Optional[dict] = None) -> dict:
    """A text-track item for a place name, in the project's saved look
    (settings.place_label_look, set by the editor's "Apply to all") or the default."""
    look = {**DEFAULT_PLACE_LOOK, **(look if isinstance(look, dict) else {})}
    item = {"kind": "place", **{k: look[k] for k in _LOOK_KEYS if k in look}}
    item["title"] = {"text": text}
    item["subtitle"] = {"text": ""}
    for line in ("title", "subtitle"):
        if isinstance(look.get(f"{line}_style"), dict):
            item[line]["style"] = look[f"{line}_style"]
        if look.get(f"{line}_animation") is not None:
            item[line]["animation"] = look[f"{line}_animation"]
        if isinstance(look.get(f"{line}_delay"), (int, float)):
            item[line]["delay"] = look[f"{line}_delay"]
    return item
