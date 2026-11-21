import math

import pytest

from services.vdoprocessing.videopipeline.overview_framing import _reserve_overview_bands

R = 6378137.0


def _y(lat):
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * R


@pytest.mark.parametrize("route", [
    {"min_lat": 35.60, "max_lat": 35.70, "min_lon": 139.60, "max_lon": 139.65},  # tall
    {"min_lat": 35.68, "max_lat": 35.69, "min_lon": 139.60, "max_lon": 139.80},  # wide
])
def test_route_sits_between_bands(route):
    top, bottom = 154.0, 300.0
    box = _reserve_overview_bands(route, (1920, 1080), top, bottom)

    x_span = math.radians(box["max_lon"] - box["min_lon"]) * R
    y_span = _y(box["max_lat"]) - _y(box["min_lat"])
    assert x_span / y_span == pytest.approx(1920 / 1080, rel=1e-6)

    px = lambda lat: (_y(box["max_lat"]) - _y(lat)) / y_span * 1080
    assert px(route["max_lat"]) >= top - 1e-6
    assert px(route["min_lat"]) <= 1080 - bottom + 1e-6
    assert box["min_lon"] <= route["min_lon"] and box["max_lon"] >= route["max_lon"]


def test_the_course_map_is_widened_about_its_middle():
    """The course video opens on the middle 1/COURSE_OPEN_ZOOM of the map: the old box must be that middle."""
    from services.vdoprocessing.videopipeline.overview_framing import _widen

    box = {"min_lat": 34.2, "max_lat": 34.3, "min_lon": 135.0, "max_lon": 135.2}
    wide = _widen(box, 1.12)
    assert abs((wide["max_lon"] - wide["min_lon"]) / 0.2 - 1.12) < 1e-9
    assert abs((wide["min_lon"] + wide["max_lon"]) / 2 - 135.1) < 1e-9
    assert wide["min_lat"] < box["min_lat"] < box["max_lat"] < wide["max_lat"]


def test_the_course_opening_zoom_ends_on_the_whole_map():
    import numpy as np

    from services import tuning
    from services.vdoprocessing.spatial_renderer.course import _open_zoom

    frame = np.random.default_rng(0).integers(0, 255, (108, 192, 3), dtype=np.uint8)
    assert np.array_equal(_open_zoom(frame, tuning.COURSE_OPEN_ZOOM_SECONDS), frame)
    assert not np.array_equal(_open_zoom(frame, 0.0), frame)
