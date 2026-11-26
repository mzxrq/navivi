"""The storyboard of each overview style: one config file per style in storyboards/ (walk.json, map.json, course.json).
The renderers read these flags instead of comparing the style name, so a style's storyboard is changed in its file.
An unset or unknown style uses walk. A value that is a tuning constant's name is read from services/tuning.py."""
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from services import tuning

_DIR = Path(__file__).parent / "storyboards"
STYLE_NAMES = ("walk", "map", "course")


@dataclass(frozen=True)
class Storyboard:
    name: str
    passby_stopbys: bool
    passby_closed: bool
    cards_stay: bool
    big_stop_card: bool
    one_card_at_a_time: bool
    leg_cards: bool
    ending_zoom_after_summary: bool
    pydeck_allowed: bool
    traced_route: bool
    course_brief_legs: bool
    arrival_slow_seconds: Optional[float]
    course_frame: bool
    script_intro_in_key: bool
    visit_all_stopbys: bool


def _load(style: str) -> Storyboard:
    data: Dict[str, Any] = json.loads((_DIR / f"{style}.json").read_text(encoding="utf-8"))
    slow = data.get("arrival_slow_seconds")
    if isinstance(slow, str):
        slow = getattr(tuning, slow)
    return Storyboard(**{**data, "arrival_slow_seconds": slow})


@lru_cache(maxsize=None)
def of(style: Optional[str]) -> Storyboard:
    return _load(style if style in STYLE_NAMES else "walk")


def for_config(config: Dict[str, Any]) -> Storyboard:
    return of(config.get("overview_style"))
