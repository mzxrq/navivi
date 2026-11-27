"""An attraction clip's place name as a themed card: a picture kept in the project, which the timeline's place
item carries so the editor shows it and the export lays it over the clip."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image

from services.hudtheme import cards, layout, model, render
from services.logger.logger import setup_logger
from services.projectfiles import meta_dir

logger = setup_logger(__name__)

FRAME_HEIGHT = 1080  # the card's place and size are in the px of a frame this high, like the other text items


def stop_glyph(waypoints: List[dict], index: int) -> str:
    """What the stop's map pin shows: its number, "+n" for a stop-by, S / E, "×" for a closed place."""
    from services.vdoprocessing.videopipeline.render_look import overview_pin_glyphs

    if not 0 <= index < len(waypoints):
        return ""
    if waypoints[index].get("inaccessible"):
        return "×"
    return overview_pin_glyphs(waypoints).get(index, "")


def _settings(project_dir: Path) -> Dict:
    try:
        return json.loads((project_dir / "job_config.json").read_text(encoding="utf-8")).get("settings") or {}
    except (OSError, ValueError):
        return {}


def _draw(card: cards.Card, scale: float, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial.png")
    render.render_cards([card], scale)[0].save(partial)
    os.replace(partial, path)


def place_picture(project_dir, name: str, glyph: str, frame: Tuple[int, int]) -> Optional[Dict]:
    """{"path", "x", "y", "width", "height", "text"} of the card for a clip `frame` px big; {} when the layout
    hides it; None when the name stays plain text (a classic project, or the card could not be drawn)."""
    project_dir = Path(project_dir)
    hud = layout.read(project_dir)
    if hud is None:
        return None
    try:
        theme_id = model.resolve_theme(hud["theme"], [], 0.0)
        theme = model.load_theme(theme_id, model.is_dark(_settings(project_dir)))
        entry = layout.merge(theme["layout"], hud.get("layout"))["place"]
        if not entry.show:
            return {}
        unit = FRAME_HEIGHT / layout.LEG_HEIGHT
        scale = unit * entry.scale
        card = cards.place_card(theme, glyph, name, style=entry.style)
        key = hashlib.sha256(f"{layout.RENDER_VERSION}|{scale}|{card.html}".encode("utf-8")).hexdigest()[:16]
        path = meta_dir(project_dir) / "hud" / f"place_{key}.png"
        if not path.is_file():  # shortcut: one browser start per new card; batch them if timelines get slow
            _draw(card, scale, path)
        with Image.open(path) as picture:
            width, height = picture.size
        pad = render.PAD * scale  # the picture's margin round the card, for its shadow
        frame_width = FRAME_HEIGHT * frame[0] / frame[1]
        x, y = layout.place(entry, (width - 2 * pad, height - 2 * pad), (frame_width, FRAME_HEIGHT), unit)
        return {"path": path.relative_to(project_dir).as_posix(), "x": round(x - pad), "y": round(y - pad),
                "width": width, "height": height, "text": name}
    except Exception as error:  # a themed look must never fail a render
        logger.warning("Place card for '%s' not drawn (%s); the name stays plain text.", name, error)
        return None
