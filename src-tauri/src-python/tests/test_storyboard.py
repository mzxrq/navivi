"""The overview storyboards (services/vdoprocessing/storyboards/*.json)."""
from services.vdoprocessing.storyboard import of


def test_each_style_reads_its_own_file():
    assert [of(s).name for s in ("walk", "map", "course")] == ["walk", "map", "course"]
    assert of("map").leg_cards and not of("walk").leg_cards
    assert of("course").traced_route and not of("course").pydeck_allowed
    assert of("course").arrival_slow_seconds == 3.0


def test_unset_or_unknown_style_is_walk():
    assert of(None) is not None and of(None).name == of("nope").name == "walk"
