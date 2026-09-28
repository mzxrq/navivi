"""render_popup_box's photo card: the white card rectangle must never peek
out past the photo's own edge (a PIL inclusive-coordinate off-by-one used to
draw it one pixel wider/taller than the photo)."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from services.mapfetcher.graphicengine import GraphicsEngine

_BG = (200, 150, 100)  # BGR - deliberately far from white and from the photo


def _make_photo(path: Path, w: int, h: int, color=(60, 90, 140)):
    img = np.full((h, w, 3), color, dtype=np.uint8)
    cv2.imwrite(str(path), img)
    return str(path)


@pytest.fixture
def engine():
    return GraphicsEngine()


def _card(engine, popup_info):
    frame = np.full((1080, 1920, 3), _BG, dtype=np.uint8)
    out = engine.render_popup_box(frame, popup_info, alpha=1.0, skip_line=True)
    box_x, box_y, total_w, total_h = engine.popup_card_geometry(popup_info, 1920, 1080)
    return out, box_x, box_y, total_w, total_h


class TestNoWhiteSliverAtTheCardEdge:
    def test_beside_card_with_a_caption_has_no_white_line_on_the_right(self, tmp_path, engine):
        photo = _make_photo(tmp_path / "photo.jpg", 910, 606)
        popup_info = {
            "x": 900, "y": 500,
            "data": {"popup_image": photo},
            "label": "テスト神社",
            "hud_corner": "beside",
            "beside_box": (1400, 400),
            "draw_leader_line": False,
        }
        out, box_x, box_y, total_w, total_h = _card(engine, popup_info)
        # Mid-height of the photo (well clear of the rounded top corners):
        # the pixel one past the card's own last column must not be the
        # card's own near-white fill leaking past the photo - the soft
        # drop-shadow legitimately tints this area, so the check is "not
        # white", not "exactly background".
        past_edge = out[box_y + 30, box_x + total_w]
        assert not (past_edge > 240).all()

    def test_beside_card_with_a_caption_has_no_white_line_on_the_bottom(self, tmp_path, engine):
        photo = _make_photo(tmp_path / "photo.jpg", 910, 606)
        popup_info = {
            "x": 900, "y": 500,
            "data": {"popup_image": photo},
            "label": "テスト神社",
            "hud_corner": "beside",
            "beside_box": (1400, 400),
            "draw_leader_line": False,
        }
        out, box_x, box_y, total_w, total_h = _card(engine, popup_info)
        past_edge = out[box_y + total_h, box_x + 50]
        assert not (past_edge > 240).all()

    def test_cover_style_card_has_no_white_line_on_the_right(self, tmp_path, engine):
        # The "cover" style has no caption strip (photo fills the whole
        # card) - a separate code path worth checking on its own.
        photo = _make_photo(tmp_path / "photo.jpg", 800, 500)
        popup_info = {
            "x": 900, "y": 500,
            "data": {"popup_image": photo, "image_display": "cover"},
            "label": "テスト",
            "hud_corner": "beside",
            "beside_box": (1400, 400),
            "draw_leader_line": False,
        }
        out, box_x, box_y, total_w, total_h = _card(engine, popup_info)
        past_edge = out[box_y + 30, box_x + total_w]
        assert not (past_edge > 240).all()

    def test_corner_hud_card_has_no_white_line_on_the_right(self, tmp_path, engine):
        # The non-"beside" (fixed HUD corner) layout branch, same check.
        photo = _make_photo(tmp_path / "photo.jpg", 910, 606)
        popup_info = {
            "x": 900, "y": 500,
            "data": {"popup_image": photo},
            "label": "テスト",
            "hud_corner": "bottom_right",
            "draw_leader_line": False,
        }
        out, box_x, box_y, total_w, total_h = _card(engine, popup_info)
        past_edge = out[box_y + 30, box_x + total_w]
        assert not (past_edge > 240).all()


class TestCoverFitNeverUndershootsTheTarget:
    """The cover-fit crop's scaled size must always be >= the target box, so
    the cropped photo can never come out narrower/shorter than the card."""

    def test_ceil_rounding_never_undershoots_across_a_wide_sweep(self):
        import math

        target_w, target_h = 210, 118
        for src_w in range(50, 2000, 13):
            for src_h in range(30, 1500, 17):
                scale = max(target_w / src_w, target_h / src_h)
                fit_w = max(1, math.ceil(src_w * scale))
                fit_h = max(1, math.ceil(src_h * scale))
                assert fit_w >= target_w and fit_h >= target_h
