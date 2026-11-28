"""Leg framing keeps the path between the corner banners and the burned-in caption."""

import pytest

from services import tuning
from services.vdoprocessing.pydeckrecorder.leg_camera import (
    _LEG_TOP_MARGIN_PX,
    _fit_view_for_path,
    _leg_bottom_margin_px,
    _project_lonlat_to_px,
    _view_keeping_pin,
)
from services.vdoprocessing.vdoexporter import subtitle_band_px

SIZE = (1920, 1080)

PATHS = {
    "tall": ([135.170, 135.171, 135.172], [34.240, 34.246, 34.252]),
    "wide": ([135.160, 135.170, 135.180], [34.244, 34.245, 34.246]),
    "short": ([135.1700, 135.1704], [34.2450, 34.2453]),
}


def _screen_ys(lons, lats, view):
    lon, lat, zoom = view
    return [_project_lonlat_to_px(x, y, lon, lat, zoom, SIZE)[1] for x, y in zip(lons, lats)]


def test_band_covers_two_caption_lines():
    assert subtitle_band_px(1080, lines=2) > subtitle_band_px(1080, lines=1) > 150
    assert _leg_bottom_margin_px(0) == 100.0
    assert _leg_bottom_margin_px(272) == 272.0 + tuning.LEG_FRAME_BOTTOM_PIN_PX


@pytest.mark.parametrize("name", PATHS)
def test_path_stays_above_caption_band(name):
    lons, lats = PATHS[name]
    bottom = _leg_bottom_margin_px(subtitle_band_px(SIZE[1]))
    view = _fit_view_for_path(
        lons, lats, SIZE, padding_frac=0.15, bottom_margin_px=bottom, top_margin_px=_LEG_TOP_MARGIN_PX,
    )
    ys = _screen_ys(lons, lats, view)
    assert max(ys) <= SIZE[1] - bottom + 1
    assert min(ys) >= _LEG_TOP_MARGIN_PX - 1


@pytest.mark.parametrize("name", PATHS)
def test_default_margin_unchanged(name):
    lons, lats = PATHS[name]
    assert _fit_view_for_path(lons, lats, SIZE, padding_frac=0.15) == _fit_view_for_path(
        lons, lats, SIZE, padding_frac=0.15, bottom_margin_px=100.0
    )


@pytest.mark.parametrize("pin_y, kept_whole", [
    (60, True),     # the pin stands at the very top edge: the frame takes it in
    (-900, False),  # far off the frame: not part of this stretch
    (500, False),   # well inside already
])
def test_a_destination_pin_is_never_left_at_the_edge(pin_y, kept_whole):
    lons, lats = [135.170, 135.172, 135.176], [34.2400, 34.2410, 34.2420]  # the stretch walked first
    margins = {"bottom_margin_px": 250.0, "top_margin_px": 300.0}
    view = _fit_view_for_path(lons, lats, SIZE, **margins)
    y = lambda lat: _project_lonlat_to_px(135.173, lat, *view, SIZE)[1]
    pin = (135.173, 34.242 + 0.001 * (pin_y - y(34.242)) / (y(34.243) - y(34.242)))
    assert y(pin[1]) == pytest.approx(pin_y, abs=2)  # the case is the one meant

    shown = _view_keeping_pin(view, lons, lats, pin, SIZE, **margins)

    if kept_whole:
        assert _project_lonlat_to_px(*pin, *shown, SIZE)[1] >= 299 and shown[2] <= view[2]
    else:
        assert shown == view
