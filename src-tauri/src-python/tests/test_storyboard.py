"""The overview storyboards (services/vdoprocessing/storyboards/*.json)."""
import re
from pathlib import Path
from types import SimpleNamespace

from services.vdoprocessing.spatial_renderer import overview
from services.vdoprocessing.storyboard import of
from services.vdoprocessing.videopipeline.render_look import look_options


def test_each_style_reads_its_own_file():
    assert [of(s).name for s in ("walk", "map", "course")] == ["walk", "map", "course"]
    assert of("map").leg_cards and not of("walk").leg_cards
    assert of("course").traced_route
    assert of("course").arrival_slow_seconds == 3.0
    assert of("course").cards_stay and not any(k.startswith("pass_card") for k in of("course").timings)


def test_each_style_has_its_beat_timings():
    assert of("course").timings["open_zoom_seconds"] == 1.2
    assert of("map").timings["map_min_stop_seconds"] == 3.5


def test_a_project_setting_beats_the_storyboard_default():
    assert look_options({})["overview_max_leg_seconds"] == of("walk").timings["max_leg_seconds"]
    assert look_options({"overview_max_leg_seconds": 6})["overview_max_leg_seconds"] == 6


def test_the_renderer_takes_a_timing_from_the_setting_else_the_storyboard(monkeypatch):
    slow = SimpleNamespace(timings={"max_leg_seconds": 4.0})
    monkeypatch.setattr(overview, "storyboard_for", lambda config: slow)
    assert overview._timing({}, "max_leg_seconds") == 4.0
    assert overview._timing({"overview_max_leg_seconds": 6}, "max_leg_seconds") == 6.0
    source = Path(overview.__file__).read_text(encoding="utf-8")
    assert not re.findall(r'get\("overview_(?:max_leg|intro_clean_hold|cue_wait)_seconds"', source)


def test_unset_or_unknown_style_is_walk():
    assert of(None) is not None and of(None).name == of("nope").name == "walk"
