import numpy as np

from services import tuning
from services.mapfetcher.graphicengine import GraphicsEngine


def _hud(**kwargs):
    engine = GraphicsEngine()
    engine.theme, engine.ui = "light", tuning.UI_THEMES["light"]
    frame = np.full((1080, 1920, 3), 200, np.uint8)
    return frame, engine.render_overview_hud(frame, **kwargs)


def test_hud_draws_both_corners_and_nothing_else():
    frame, out = _hud(
        title="Trip", mode_duration={"walking": 3600},
        remaining_km=14.3, remaining_seconds=600, stops=(3, 9), next_stop="Stop", progress=0.3,
    )
    changed = out != frame
    assert changed[:200, :500].any() and changed[:200, -500:].any()
    assert not changed[300:, :].any()  # no scale bar / nothing below the HUD


def test_hud_skips_missing_pieces():
    frame, out = _hud()
    assert not (out != frame).any()
