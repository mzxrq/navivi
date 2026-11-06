"""A photo's credit over the attraction clip while that photo is on screen: a text-track item (editable in the
editor) in a small dark box at the bottom left or right. The credit is typed per photo in the stop editor
(waypoint imageCredits[path].text, corner); a photo found online without one shows its author and license."""

from pathlib import Path
from typing import List, Optional

from services import tuning


def credit_text(credit: Optional[dict]) -> str:
    if not isinstance(credit, dict):
        return ""
    typed = str(credit.get("text") or "").strip()
    return typed or " · ".join(str(credit.get(k) or "").strip() for k in ("author", "license") if credit.get(k))


def credit_text_item(text: str, corner: str = "right", look: Optional[dict] = None) -> dict:
    """look: settings.photo_credit_look (the editor's "Apply to all photo credits"): its size, box and margins."""
    look = look if isinstance(look, dict) else {}
    item = {
        "kind": "credit", "position": "bottom", "align": "left" if corner == "left" else "right",
        "margin_v": tuning.PHOTO_CREDIT_MARGIN_PX, "margin_h": tuning.PHOTO_CREDIT_MARGIN_PX, "animation": "none",
        "title": {"text": tuning.PHOTO_CREDIT_PREFIX + text, "style": {
            "font_size": tuning.PHOTO_CREDIT_FONT_PX, "bold": False, "color": "#FFFFFF", "shadow": 0,
            "background": True, "background_color": "#000000", "background_opacity": tuning.PHOTO_CREDIT_BOX_OPACITY,
            "outline_color": "#000000", "outline_width": tuning.PHOTO_CREDIT_PADDING_PX,
        }},
        "subtitle": {"text": ""},
    }
    for key in ("position", "margin_v", "margin_h", "animation"):
        if look.get(key) is not None:
            item[key] = look[key]
    if isinstance(look.get("title_style"), dict):
        item["title"]["style"] = {**item["title"]["style"], **look["title_style"]}
    return item


def credit_items(
    waypoint: dict, clip_seconds: float, look: Optional[dict] = None, cuts: Optional[List[float]] = None,
) -> List[dict]:
    """One item per credited photo of a stop's attraction clip, over that photo's part of it: from one {next} cue
    (`cuts`, as img2vdo.photo_shares cuts the clip) to the next, else an equal share. A stop with its own footage shows none."""
    if not isinstance(waypoint, dict) or waypoint.get("videos"):
        return []
    images = [p for p in waypoint.get("images") or [] if p]
    credits = waypoint.get("imageCredits") or {}
    # The pipeline hands photos over as absolute (or upscaled) paths; the credits are keyed by the saved relative one.
    by_name = {Path(k).name.lower(): v for k, v in credits.items()}
    by_stem = {Path(k).stem.lower(): v for k, v in credits.items()}
    share = clip_seconds / len(images) if images else 0.0
    edges = [share * i for i in range(len(images) + 1)]
    if cuts and len(cuts) == len(images) - 1:
        cued = [0.0, *[float(c) for c in cuts], clip_seconds]
        if min(b - a for a, b in zip(cued, cued[1:])) >= tuning.ATTRACTION_MIN_PHOTO_SECONDS:
            edges = cued
    items = []
    for i, path in enumerate(images):
        p = Path(path)
        credit = credits.get(path) or by_name.get(p.name.lower()) or next(
            (v for stem, v in by_stem.items() if p.stem.lower().startswith(stem)), None)
        text = credit_text(credit)
        if text and share > 0:
            items.append({"start": round(edges[i], 3), "end": round(edges[i + 1], 3),
                          **credit_text_item(text, credit.get("corner") or "right", look)})
    return items
