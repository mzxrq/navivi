"""The overview's bottom bar (docs/OVERVIEW_RULES.md 8.15): notices at the bottom left, side by side, and the
progress rail in the room to their right - in every style."""
import numpy as np
import pytest

from services import tuning, video_text
from services.mapfetcher.graphicengine import GraphicsEngine
from services.mapfetcher.graphicengine.cards import rail_left
from services.vdoprocessing.spatial_renderer import SpatialRenderer

W, H, GAP = 1920, 1080, tuning.NOTICE_RAIL_GAP
MARKS = [(0.0, "S", (0, 128, 0)), (0.5, "1", (200, 100, 0)), (1.0, "E", (0, 0, 200))]


@pytest.mark.parametrize("notices, left", [
    ([], None),
    ([(500, 0.0)], None),
    ([(500, 1.0)], 500 + GAP),
    ([(500, 0.5)], 32 + (500 + GAP - 32) / 2),  # eases in with the notice
    ([(500, 1.0), (1000, 1.0)], 1000 + GAP),
    ([(500, 1.0), (1000, 0.0)], 500 + GAP),
])
def test_the_rail_starts_after_the_last_visible_notice(notices, left):
    assert rail_left(32, notices) == (None if left is None else round(left))


def test_a_rail_with_no_room_left_is_not_drawn():
    frame = np.full((H, W, 3), 200, np.uint8)
    engine = GraphicsEngine()
    assert (engine.render_route_progress_rail(frame, 0.5, MARKS, left=W - 100) == frame).all()
    assert (engine.render_route_progress_rail(frame, 0.5, MARKS, left=2 * W) == frame).all()  # never negative
    assert (engine.render_route_progress_rail(frame, 0.5, MARKS, left=600) != frame).any()


def test_a_notice_is_as_wide_as_its_text(monkeypatch):
    labels = dict(video_text.current_labels(), stopby_notice_title="x", stopby_notice_body="y")
    monkeypatch.setattr(video_text, "current_labels", lambda: labels)
    x0, _, x1, _ = GraphicsEngine().stopby_notice_box(W, H)
    assert x1 - x0 < 200


def _walk():
    renderer = SpatialRenderer.__new__(SpatialRenderer)
    renderer.config = {}
    renderer.graphics = GraphicsEngine()
    return renderer


def test_walk_shows_both_notices_side_by_side_and_moves_its_rail_past_them():
    renderer = _walk()
    for kind in ("stopby", "closed"):
        renderer._start_stopby_notice(30, 8.0, kind=kind)
    for notice in renderer._stopby_notices.values():
        notice["i"] = notice["fade"]  # fully in
    renderer._apply_stopby_notice(np.zeros((H, W, 3), np.uint8))
    (first, a), (second, b) = renderer._notice_edges
    wide = renderer.graphics.stopby_notice_box(W, H, "closed")
    assert a == b == 1.0 and second - first > wide[2] - wide[0]  # beside it, not on it
    boxes = renderer._stopby_notice_reserved(W, H)
    assert len(boxes) == 2 and boxes[1][0] >= boxes[0][2]


def test_walk_draws_the_rail_and_keeps_its_cards_off_it():
    renderer = _walk()
    renderer._rail_marks, renderer._hud_progress_frac = MARKS, 0.5
    frame = np.full((H, W, 3), 200, np.uint8)
    assert (renderer._apply_rail(frame)[H - 120:] != 200).any()
    _card, reserved = renderer._ov_reserved_boxes(None, W, H)
    assert any(x0 == 0 and x1 == W and y1 == H for x0, y0, x1, y1 in reserved)  # the rail's band
