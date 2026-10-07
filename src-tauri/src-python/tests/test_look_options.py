"""The "Look of the video" settings: every key reaches the renderer config, defaults equal the old rendering."""
import json
from pathlib import Path


from services import tuning
from services.vdoprocessing.videopipeline import outro_step
from services.vdoprocessing.videopipeline.render_step import (
    _LOOK_OPTION_DEFAULTS,
    _leg_pin,
    look_options,
)

# What the readers in spatial_renderer/* and route2vdo.py fall back to when the key is missing.
OLD_READER_DEFAULTS = {
    "show_compass": True,
    "waypoint_map_border": True,
    "waypoint_intro_freeze": 2.0,
    "show_leg_wide_intro": False,
    "res_follow_pitch": 0.0,
    "overview_max_leg_seconds": 10.0,
    "overview_intro_card_scale": 1.3,
    "overview_intro_clean_hold_seconds": 1.5,
    "overview_title": None,
    "enable_ending_highlight": True,
}


def test_defaults_equal_the_readers_fallbacks():
    assert look_options({}) == OLD_READER_DEFAULTS
    assert {k for k, _ in _LOOK_OPTION_DEFAULTS} == set(OLD_READER_DEFAULTS)


def test_project_values_are_forwarded():
    settings = {
        "show_compass": False,
        "waypoint_map_border": False,
        "waypoint_intro_freeze": 0.5,
        "show_leg_wide_intro": True,
        "res_follow_pitch": 30,
        "overview_max_leg_seconds": 6,
        "overview_intro_card_scale": 1.0,
        "overview_intro_clean_hold_seconds": 0,
        "overview_title": "My trip",
        "enable_ending_highlight": False,
        "unrelated": 1,
    }
    out = look_options(settings)
    assert out == {k: settings[k] for k in OLD_READER_DEFAULTS}


def test_leg_pins_use_project_colors_only_when_set():
    assert _leg_pin("S", {}, False)["color"] == tuple(tuning.START_PIN_COLOR)
    assert _leg_pin("E", {}, False)["color"] == tuple(tuning.END_PIN_COLOR)
    assert _leg_pin("・", {}, False)["color"] == tuple(tuning.STOPBY_PIN_COLOR)
    # The app writes RGB; the renderer draws BGR.
    assert _leg_pin("S", {"start_pin_color": [1, 2, 3]}, False)["color"] == (3, 2, 1)
    assert _leg_pin("E", {"end_pin_color": [1, 2, 3]}, False)["color"] == (3, 2, 1)
    assert _leg_pin("・", {"stopby_pin_color": [1, 2, 3]}, False)["color"] == (3, 2, 1)


def _outro(tmp_path: Path, settings: dict, monkeypatch):
    cfg = tmp_path / "job_config.json"
    cfg.write_text(json.dumps({"project_name": "p", "waypoints": [], "settings": settings}), encoding="utf-8")
    calls = []

    def fake_generate(**kwargs):
        calls.append(kwargs)
        return str(tmp_path / "outro.mp4")

    import services.vdoprocessing.outrocard as outrocard

    monkeypatch.setattr(outrocard, "generate_outro_clip", fake_generate)
    monkeypatch.setattr(outro_step, "_route_frame_size", lambda _d: None)
    return outro_step.render_outro_clip(str(cfg)), calls


def test_outro_on_by_default_and_style_forwarded(tmp_path, monkeypatch):
    path, calls = _outro(tmp_path, {"outro_route_info": False}, monkeypatch)
    assert path and calls[0]["style"] == tuning.DEFAULT_OUTRO_STYLE
    path, calls = _outro(tmp_path, {"outro_style": "grid", "outro_route_info": False}, monkeypatch)
    assert calls[0]["style"] == "grid"


def test_outro_can_be_switched_off(tmp_path, monkeypatch):
    path, calls = _outro(tmp_path, {"enable_outro": False}, monkeypatch)
    assert path is None and calls == []


def test_animator_config_spreads_look_options():
    from services.vdoprocessing.videopipeline import render_step

    assert "**look_options(settings)" in Path(render_step.__file__).read_text(encoding="utf-8")
