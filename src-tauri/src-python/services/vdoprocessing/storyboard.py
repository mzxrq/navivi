"""The storyboard of each overview style: one config file per style in storyboards/ (walk.json, map.json, course.json).
The renderers read these flags and beat timings instead of comparing the style name, so a style's storyboard is
changed in its file. An unset or unknown style uses walk.

ending_pin_shape: the pins in the ending zoom into the start (or end) point - "dot", or "teardrop" (with the
overview's S / 1 / +1 labels). Any other value is a dot.
cluster_min_stops: this many stops or more, each within a pin's width of the next on screen, make a cluster the
camera zooms in on while the trace or the walker passes it.
sub_course_slot: where the sub course plays - "after_totals", or "before_stopbys" (Whole route first, whose
stop-bys then wait for it). Both come after the totals card.

timings, in seconds (a project setting of the same overview_* name, where there is one, wins):
  all     sub_course_seconds (the sub course's walk), cue_wait_seconds (wait at a stop whose cue starts a
          sentence), max_leg_seconds (longest leg on screen), intro_clean_hold_seconds (clean map before the card)
  map     map_photo_seconds (the big photo), map_slide_seconds (its slide to the leg card), map_min_stop_seconds
          (shortest stand at a stop: photo, slide, then time to read the card)
  course  open_zoom_seconds (ease out to the whole map), stats_slide_seconds (totals card slides in)"""
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
    traced_route: bool
    course_brief_legs: bool
    arrival_slow_seconds: Optional[float]
    course_frame: bool
    script_intro_in_key: bool
    visit_all_stopbys: bool
    timings: Mapping[str, float]
    ending_pin_shape: str
    sub_course_slot: str
    cluster_min_stops: int


def _load(style: str) -> Storyboard:
    data: Dict[str, Any] = json.loads((_DIR / f"{style}.json").read_text(encoding="utf-8"))
    # Read-only: the loaded storyboard is cached and shared.
    return Storyboard(**{**data, "timings": MappingProxyType(data["timings"])})


@lru_cache(maxsize=None)
def of(style: Optional[str]) -> Storyboard:
    return _load(style if style in STYLE_NAMES else "walk")


def for_config(config: Dict[str, Any]) -> Storyboard:
    return of(config.get("overview_style"))


@dataclass(frozen=True)
class FinaleBoard:
    """storyboards/finale.json: pin_shape "teardrop" / "dot", card_style "pill" / "popup", shrink_without_voice
    (false: with no finale narration the pull-back cuts in without the photo shrinking onto its pin) and hud
    "overview" (the overview recap's title, totals, travel modes and route strip, for a project with a hud.json)
    or "summary" (the plain totals card). include_stopby_waypoint / include_closed_waypoint: whether every
    stop-by / closed place gets its pin and card, on the route or off it."""
    name: str
    pin_shape: str
    card_style: str
    shrink_without_voice: bool
    hud: str
    include_stopby_waypoint: bool
    include_closed_waypoint: bool


_FINALE_CHOICES = {"pin_shape": ("teardrop", "dot"), "card_style": ("pill", "popup"),
                   "shrink_without_voice": (True, False), "hud": ("overview", "summary"),
                   "include_stopby_waypoint": (True, False), "include_closed_waypoint": (True, False)}


def finale(settings: Optional[Dict[str, Any]] = None) -> FinaleBoard:
    """The finale's storyboard; a project setting finale_<key> with a known value wins over the file."""
    data: Dict[str, Any] = {"name": "finale", "pin_shape": "teardrop", "card_style": "pill",
                            "shrink_without_voice": True, "hud": "overview",
                            "include_stopby_waypoint": False, "include_closed_waypoint": False}
    data.update(json.loads((_DIR / "finale.json").read_text(encoding="utf-8")))
    for key, allowed in _FINALE_CHOICES.items():
        value = (settings or {}).get(f"finale_{key}")
        if type(value) is type(allowed[0]) and value in allowed:
            data[key] = value
    return FinaleBoard(**data)
