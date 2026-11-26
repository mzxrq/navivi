"""Each overview style renders a finished video end to end (tiny, CPU, no map download)."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from services import tuning
from services.mapfetcher.graphicengine import GraphicsEngine
from services.vdoprocessing.spatial_renderer import SpatialRenderer


@pytest.mark.parametrize("style", tuning.OVERVIEW_STYLES)
def test_an_overview_style_renders_a_finished_video(style, tmp_path):
    background, photo = tmp_path / "background.png", tmp_path / "photo.png"
    cv2.imwrite(str(background), np.full((360, 640, 3), 200, np.uint8))
    cv2.imwrite(str(photo), np.full((90, 160, 3), 90, np.uint8))
    points = [(80, 180), (240, 110), (400, 200), (560, 180)]
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
