"""Each overview style renders a finished video end to end (tiny, CPU, no map download)."""

from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from services import tuning
from services.mapfetcher.graphicengine import GraphicsEngine
from services.vdoprocessing.route2vdo import RouteAnimator
from services.vdoprocessing.spatial_renderer import SpatialRenderer


# 640x360 has no room for any stop badge; 1280x720 lays them out.
@pytest.mark.parametrize("size", [(640, 360), (1280, 720)])
@pytest.mark.parametrize("style", tuning.OVERVIEW_STYLES)
def test_an_overview_style_renders_a_finished_video(style, size, tmp_path):
    w, h = size
    background, photo = tmp_path / "background.png", tmp_path / "photo.png"
    cv2.imwrite(str(background), np.full((h, w, 3), 200, np.uint8))
    cv2.imwrite(str(photo), np.full((90, 160, 3), 90, np.uint8))
    points = [(w * x // 16, h * y // 18) for x, y in ((2, 9), (6, 6), (10, 10), (14, 9))]
    names = ["S", "A", "stop-by", "E"]
    popups = [{"label": n, "triggered": False, "arrived": False, "popup_image": str(photo)} for n in names]
    popups[2]["is_stopby"] = True
    config = {"overview_style": style, "duration": 2.0, "enable_ending_highlight": False, "pause": 0.5,
              "summary_hold": 0.5}
    renderer = SpatialRenderer(config, GraphicsEngine(), tmp_path / "out")
    (tmp_path / "out").mkdir()

    result = renderer.render_overview(str(background), points, names, popups, 10)

    assert result and Path(result).stat().st_size > 0
    assert renderer.last_rendered_seconds > 0


def test_a_project_still_carrying_the_old_3d_setting_renders_the_cue_driven_overview():
    animator = RouteAnimator.__new__(RouteAnimator)
    animator.config = {"use_pydeck_overview": True, "overview_style": "walk"}
    animator.spatial_renderer = SimpleNamespace(render_overview=lambda *a, **k: "01_overview.mp4")
    assert animator._overview_clip("bg.png", [], [], [], 30, None, None, None, {}) == "01_overview.mp4"
