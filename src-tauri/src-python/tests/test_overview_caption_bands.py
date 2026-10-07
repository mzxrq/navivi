import math

import pytest

from services.vdoprocessing.videopipeline.render_step import _reserve_overview_bands

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
