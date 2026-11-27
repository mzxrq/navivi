"""The ending zoom's pins: a dot or a teardrop, as the style's storyboard says (ending_pin_shape)."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from services.vdoprocessing.spatial_renderer import SpatialRenderer, overview, transitions
from services.vdoprocessing.storyboard import of
from services.vdoprocessing.videopipeline import render_checkpoint

WAYPOINTS = [
    {"lat": 35.0, "lng": 139.0},
    {"lat": 35.1, "lng": 139.1},
    {"lat": 35.2, "lng": 139.2, "isStopBy": True},
    {"lat": 35.3, "lng": 139.3},
    {"lat": 35.1, "lng": 139.1},  # back at the second pin: its number again
    {"lat": 35.4, "lng": 139.4},
]


def _renderer(monkeypatch, shape):
    r = SpatialRenderer.__new__(SpatialRenderer)
    r.graphics = MagicMock(marker_radius=1, marker_color=(1, 2, 3), arrived_marker_color=(4, 5, 6))
    r.config = {}
    r._START_PIN_COLOR, r._END_PIN_COLOR, r._STOPBY_PIN_COLOR = (1, 1, 1), (2, 2, 2), (3, 3, 3)
    r._get_job_config = lambda: {"waypoints": WAYPOINTS, "start_point": {"lat": 34.0, "lng": 138.0}}
    r._draw_recap_dot_color = MagicMock()
    r._pin_color = lambda wp: (4, 5, 6)
    monkeypatch.setattr(transitions, "storyboard_for", lambda config: SimpleNamespace(ending_pin_shape=shape))
    monkeypatch.setattr(
        "services.vdoprocessing.spatial_renderer.transitions.RouteGeometryProcessor.project_latlon_to_pixel",
        lambda lat, lng, *a: ((lng - 139.0) * 1000 + 50, (lat - 35.0) * 1000 + 50),
    )
    return r


def _draw(r):
    r._draw_nearby_waypoints(np.zeros((900, 900, 3), np.uint8), 900, 900, (0, 0, 1, 1), -999, -999)


def test_every_style_ends_on_dots_unless_its_file_says_otherwise():
    assert [of(s).ending_pin_shape for s in ("walk", "map", "course")] == ["dot"] * 3


@pytest.mark.parametrize("shape", ["dot", "unknown"])
def test_dots_carry_no_label(monkeypatch, shape):
    r = _renderer(monkeypatch, shape)
    _draw(r)
    assert r._draw_recap_dot_color.call_count == len(WAYPOINTS) and not r.graphics.draw_marker.called


def test_teardrops_show_the_overviews_own_pin_labels(monkeypatch):
    r = _renderer(monkeypatch, "teardrop")
    _draw(r)
    labels = [c.kwargs["number"] for c in r.graphics.draw_marker.call_args_list]
    assert labels == [1, 2, "+1", 3, 2, 4]
    assert not r._draw_recap_dot_color.called


@pytest.mark.parametrize("shape, drawn", [("dot", "dot"), ("teardrop", "S")])
def test_the_featured_start_takes_the_same_shape(monkeypatch, shape, drawn):
    r = _renderer(monkeypatch, shape)
    r._draw_ending_pin(np.zeros((90, 90, 3), np.uint8), {"index": 0, "data": {}}, 2, 10, 20, r._START_PIN_COLOR)
    if drawn == "dot":
        assert r._draw_recap_dot_color.call_args.args[1:] == (10, 20, r._START_PIN_COLOR)
    else:
        call = r.graphics.draw_marker.call_args
        assert call.args[1:3] == (10, 20) and call.kwargs["number"] == "S"


def test_editing_a_storyboard_renders_the_overview_again(monkeypatch, tmp_path):
    before = overview._overview_fingerprint_parts({}, None, tmp_path / "bg.png", {})
    edited = of("walk").__class__(**{**of("walk").__dict__, "ending_pin_shape": "teardrop"})
    monkeypatch.setattr(overview, "storyboard_for", lambda config: edited)
    after = overview._overview_fingerprint_parts({}, None, tmp_path / "bg.png", {})
    assert before["storyboard"] != after["storyboard"]


def test_a_finished_render_is_not_reused_after_a_storyboard_edit(tmp_path, monkeypatch):
    config = tmp_path / "job_config.json"
    config.write_text('{"waypoints": [], "settings": {}}', encoding="utf-8")
    before = render_checkpoint._checkpoint_parts(str(config), {}, [], [])
    edited = of("walk").__class__(**{**of("walk").__dict__, "ending_pin_shape": "teardrop"})
    monkeypatch.setattr(render_checkpoint, "storyboard_of", lambda style: edited)
    after = render_checkpoint._checkpoint_parts(str(config), {}, [], [])
    assert before["route.storyboard"] != after["route.storyboard"]
    assert "route.storyboard" in render_checkpoint.ROUTE_CHECKPOINT_PARTS
