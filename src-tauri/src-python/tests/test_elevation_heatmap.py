"""Elevation heatmap in the video: slope maths, colours, per-segment features and the leg wiring."""

import json

import pytest

from services.vdoprocessing.pydeckrecorder import elevation as el
from services.vdoprocessing.pydeckrecorder.recorder import _route_gradient_feature

# ~11.1 m per 0.0001 degree of latitude
LINE = [(35.0 + i * 0.0003, 135.0) for i in range(30)]  # ~1 km straight north


def _ele(slope_pct):
    dist = el.cumulative_m(LINE)
    return [d * slope_pct / 100 for d in dist]


def test_gradient_colors_match_the_editor_ramp():
    assert el.gradient_color(0) == [0x10, 0xB9, 0x81]
    assert el.gradient_color(10) == [0xEF, 0x44, 0x44]
    assert el.gradient_color(-10) == [0x25, 0x63, 0xEB]
    assert el.gradient_color(99) == el.gradient_color(10)
    assert el.gradient_color(None) == el.gradient_color(0)


@pytest.mark.parametrize("slope,expected", [(0, 0), (10, 10), (-6, -6)])
def test_constant_slope_is_recovered(slope, expected):
    dist = el.cumulative_m(LINE)
    pct = el.segment_gradients(dist, el.smooth(dist, _ele(slope)))
    assert all(abs(p - expected) < 0.5 for p in pct)


def test_slope_is_capped():
    dist = el.cumulative_m(LINE)
    assert max(el.segment_gradients(dist, _ele(300))) == el.SLOPE_CAP_PCT


def test_fill_gaps_interpolates_and_holds_the_ends():
    assert el.fill_gaps([None, 10, None, 20, None]) == [10, 10, 15, 20, 20]
    assert el.fill_gaps([None, float("nan")]) is None


def test_usable_heights_ignores_flat_constant_and_misaligned_data():
    assert el.usable_heights([35] * 10, 10) is None  # the app's "no elevation" filler
    assert el.usable_heights([0, 5, 10], 4) is None
    assert el.usable_heights([0, 5, 10], 3) == [0, 5, 10]
    assert el.usable_heights(None, 3) is None


def test_leg_segment_colors_runs_from_blue_to_red():
    half = len(LINE) // 2
    d = el.cumulative_m(LINE)
    ele = [-(x * 0.1) for x in d[:half]] + [-(d[half - 1] * 0.1) + (x - d[half - 1]) * 0.1 for x in d[half:]]
    colors = el.leg_segment_colors(LINE, ele, alpha=200)
    assert len(colors) == len(LINE) - 1
    assert colors[2][:3] == el.gradient_color(-10) and colors[-3][:3] == el.gradient_color(10)
    assert all(c[3] == 200 for c in colors)
    assert el.leg_segment_colors(LINE, None) is None
    assert el.leg_segment_colors(LINE, [1, 2]) is None


def test_gradient_feature_merges_runs_and_keeps_the_line_connected():
    coords = [[0, 0], [0, 1], [0, 2], [0, 3], [0, 4]]
    red, blue = [255, 0, 0, 255], [0, 0, 255, 255]
    fc = _route_gradient_feature(coords, [red, red, blue, blue])
    feats = fc["features"]
    assert [f["properties"]["line_color"] for f in feats] == [red, blue]
    assert feats[0]["geometry"]["coordinates"][-1] == feats[1]["geometry"]["coordinates"][0]
    assert sum(len(f["geometry"]["coordinates"]) - 1 for f in feats) == 4
    json.dumps(fc)  # goes straight into the page's JS


def test_gradient_feature_reuses_last_color_and_handles_degenerate_input():
    fc = _route_gradient_feature([[0, 0], [0, 1], [0, 2]], [[1, 2, 3, 255]])
    assert [f["properties"]["line_color"] for f in fc["features"]] == [[1, 2, 3, 255]]
    assert _route_gradient_feature([[0, 0]], [[1, 2, 3, 255]])["features"] == []
    assert _route_gradient_feature([[0, 0], [0, 1]], [])["features"] == []


def test_quantize_makes_neighbours_equal():
    a, b = el.quantize([[16, 185, 129, 255], [17, 184, 130, 255]])
    assert a == b


def test_heatmap_wiring_is_in_the_leg_checkpoint():
    from services.vdoprocessing import route2vdo

    assert "kw.leg_elevations" in route2vdo._LEG_CHECKPOINT_PARTS
