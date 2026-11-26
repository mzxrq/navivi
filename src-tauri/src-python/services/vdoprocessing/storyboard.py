"""The storyboard of each overview style: one config file per style in storyboards/ (walk.json, map.json, course.json).
The renderers read these flags and beat timings instead of comparing the style name, so a style's storyboard is
changed in its file. An unset or unknown style uses walk.

ending_pin_shape: the pins in the ending zoom into the start (or end) point - "dot", or "teardrop" (with the
overview's S / 1 / +1 labels). Any other value is a dot.

timings, in seconds (a project setting of the same overview_* name, where there is one, wins):
  all     sub_course_seconds (the sub course's walk), cue_wait_seconds (wait at a stop whose cue starts a
          sentence), max_leg_seconds (longest leg on screen), intro_clean_hold_seconds (clean map before the card)
  map     map_photo_seconds (the big photo), map_slide_seconds (its slide to the leg card), map_min_stop_seconds
          (shortest stand at a stop: photo, slide, then time to read the card)
  course  open_zoom_seconds (ease out to the whole map), pass_card_seconds / pass_card_min_seconds (a passed
          stop's photo card; 0.9 flashed past where stops come a fraction of a second apart),
          stats_slide_seconds (totals card slides in)"""
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional

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
    timings: Mapping[str, float]
    ending_pin_shape: str


def _load(style: str) -> Storyboard:
    data: Dict[str, Any] = json.loads((_DIR / f"{style}.json").read_text(encoding="utf-8"))
    # Read-only: the loaded storyboard is cached and shared.
    return Storyboard(**{**data, "timings": MappingProxyType(data["timings"])})


@lru_cache(maxsize=None)
def of(style: Optional[str]) -> Storyboard:
    return _load(style if style in STYLE_NAMES else "walk")


def for_config(config: Dict[str, Any]) -> Storyboard:
    return of(config.get("overview_style"))
