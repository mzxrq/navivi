"""Where each themed card goes, and in which style: built-in defaults, then the theme's "layout", then the
project's hud.json (see docs/themed-card-styles.md). hud.json is its own file because the app rewrites
job_config.json from its database on every save.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Dict, NamedTuple, Optional, Tuple

from services.hudtheme import model, styles
from services.logger.logger import setup_logger

logger = setup_logger(__name__)

FILE_NAME = "hud.json"
# Bump when the themed look changes, so themed projects render again.
RENDER_VERSION = 1
MIN_SCALE, MAX_SCALE = 0.5, 2.0
_NOTICE_EDGE = (18 * 568 / 1080, 28 * 568 / 1080)  # where the app itself puts its banners
BOTH_AXES = [f"{v}-{h}" for v in ("top", "middle", "bottom") for h in ("left", "center", "right")]


class Entry(NamedTuple):
    anchor: str
    x: float  # artboard px from the anchored edge (from the middle for center / middle)
    y: float
    show: bool = True
    scale: float = 1.0
    style: str = styles.DEFAULT


# Frame heights of the artboards the x / y numbers are in.
OVERVIEW_HEIGHT = 568
LEG_HEIGHT = 600
DEFAULTS: Dict[str, Entry] = {
    # the course overview
    "title": Entry("top-left", 16, 14),
    "totals": Entry("top-right", 16, 14),
    "modes": Entry("top-right", 16, 96),
    "strip": Entry("bottom-right", 16, 14),
    "notices": Entry("bottom-left", *_NOTICE_EDGE),
    # the walking legs
    "next": Entry("top-left", 16, 14),
    "leg_banner": Entry("top-right", 16, 14),
    "compass": Entry("top-right", 16, 100),
    "leg_rail": Entry("bottom-left", 16, 14),
    "remaining": Entry("bottom-right", 16, 14),
    # the attraction clips (on the walking legs' artboard)
    "place": Entry("top-left", 16, 14),
}
_FIXED = {"notices": ("scale", "style")}  # the app draws its banners itself


def _field(name: str, key: str, value):
    """`value` checked for entry `name`'s field `key`, or None (with a warning) when it cannot be used."""
    if key not in Entry._fields or key in _FIXED.get(name, ()):
        logger.warning("%s: '%s' has no setting '%s'; ignored.", FILE_NAME, name, key)
        return None
    if key == "show" and isinstance(value, bool):
        return value
    if key == "anchor" and value in BOTH_AXES:
        return value
    if key == "style" and isinstance(value, str):
        return value
    if key in ("x", "y", "scale") and isinstance(value, (int, float)) and not isinstance(value, bool) \
            and math.isfinite(value):
        return min(MAX_SCALE, max(MIN_SCALE, float(value))) if key == "scale" else float(value)
    logger.warning("%s: '%s.%s' cannot be %r; using the default.", FILE_NAME, name, key, value)
    return None


def merge(*layouts) -> Dict[str, Entry]:
    """DEFAULTS with each of `layouts` ({card: {field: value}}) laid over them in turn."""
    out = dict(DEFAULTS)
    for layout in layouts:
        if not layout:
            continue
        if not isinstance(layout, dict):
            logger.warning("%s: \"layout\" must be an object; ignored.", FILE_NAME)
            continue
        for name, fields in layout.items():
            if name not in out or not isinstance(fields, dict):
                logger.warning("%s: unknown card or bad value '%s'; ignored.", FILE_NAME, name)
                continue
            checked = {key: _field(name, key, value) for key, value in fields.items()}
            out[name] = out[name]._replace(**{k: v for k, v in checked.items() if v is not None})
    return out


def place(entry: Entry, size: Tuple[float, float], frame: Tuple[float, float], unit: float) -> Tuple[float, float]:
    """Top-left corner, in video px, of a card `size` video px big on a `frame` that has `unit` video px per
    artboard px. Never off the frame."""
    vertical, horizontal = entry.anchor.split("-")
    dx, dy, (w, h), (width, height) = entry.x * unit, entry.y * unit, size, frame
    x = dx if horizontal == "left" else width - w - dx if horizontal == "right" else (width - w) / 2 + dx
    y = dy if vertical == "top" else height - h - dy if vertical == "bottom" else (height - h) / 2 + dy
    return max(0.0, min(x, width - w)), max(0.0, min(y, height - h))


def read(project_dir) -> Optional[Dict]:
    """The project's hud.json as {"theme", "layout"}; None (the classic look) when it is absent, unreadable or
    names no theme."""
    path = Path(project_dir) / FILE_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        logger.warning("%s cannot be read (%s); using the classic look.", path, error)
        return None
    if not isinstance(data, dict) or not isinstance(data.get("theme"), str) or data["theme"] == "classic":
        if not isinstance(data, dict) or data.get("theme") != "classic":
            logger.warning("%s names no theme; using the classic look.", path)
        return None
    if data["theme"] != "auto" and data["theme"] not in model.theme_ids():
        logger.warning("%s: no theme '%s' (have %s); using the classic look.", path, data["theme"],
                       ", ".join(model.theme_ids()))
        return None
    return {"theme": data["theme"], "layout": data.get("layout") or {}}


def fingerprint(project_dir) -> Optional[str]:
    """Changes whenever a themed video would look different: hud.json, any style or theme file. None when the
    project is not themed."""
    if read(project_dir) is None:
        return None
    digest = hashlib.sha256(str(RENDER_VERSION).encode())
    files = [Path(project_dir) / FILE_NAME]
    for folder in (styles.BUILTIN_DIR, styles.user_dir(), model.THEMES_DIR):
        files += sorted(p for p in folder.rglob("*") if p.suffix in (".html", ".svg", ".css", ".json")
                        and p.parent.name != "outro")  # the outro is remade every render; its look is not a leg's
    for path in files:
        try:
            digest.update(path.name.encode("utf-8") + path.read_bytes())
        except OSError:
            continue
    return digest.hexdigest()[:16]


def project_hud(project_dir, settings: Dict, title: str) -> Optional[Dict]:
    """What the renderers need for a themed project, or None."""
    found = read(project_dir)
    if found is None:
        return None
    return {**found, "title": title, "dark": model.is_dark(settings or {}),
            "fingerprint": fingerprint(project_dir)}
