import numpy as np

from services import tuning
from services.mapfetcher.graphicengine import GraphicsEngine
from services.vdoprocessing.pydeckrecorder.leg_hud import _hud_css


def _banner_columns(**kwargs):
    frame = np.zeros((300, 1000, 3), dtype=np.uint8)
    out = GraphicsEngine().render_top_banner(frame, "寺田橋から歩いてめぐる道", top_margin=20, **kwargs)
    return np.flatnonzero((out != 0).any(axis=(0, 2)))


def test_a_left_banner_starts_at_the_left_margin_and_a_default_one_is_centred():
    left = _banner_columns(align="left", left_margin=32)
    assert left[0] == 32
    centred = _banner_columns()
    assert abs((centred[0] + centred[-1]) / 2 - 500) < 3


def test_the_banner_width_helper_matches_the_drawn_pill():
    engine = GraphicsEngine()
    drawn = _banner_columns(align="left", left_margin=0)
    assert abs(engine.top_banner_width("寺田橋から歩いてめぐる道", 22) - (drawn[-1] - drawn[0] + 1)) <= 3


def test_the_leg_hud_card_takes_its_margins_from_tuning():
    css = _hud_css()
    assert f"bottom: {tuning.LEG_CARD_MARGIN_BOTTOM_PX}px; right: {tuning.LEG_CARD_MARGIN_PX}px" in css
