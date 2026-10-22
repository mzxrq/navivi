import pandas as pd

from services.mapfetcher.maplanguage import needs_gl_labels
from services.vdoprocessing.pydeckrecorder.pedestrian import _framed_points
from services.vdoprocessing.spatial_renderer.course import pin_reveal_time


def _path():
    # a straight walk east, 0.001 deg (~91 m at 35N) per row
    return pd.DataFrame({"lat": [35.0] * 6, "lon": [139.0 + i * 0.001 for i in range(6)]})


class TestFramedPoints:
    def test_a_stopby_near_the_route_is_framed(self):
        lons, lats = _framed_points(_path(), 0, 6, [{"lat": 35.002, "lon": 139.002}])  # ~220 m north
        assert (139.002, 35.002) in zip(lons, lats)

    def test_a_far_stopby_is_left_out_so_the_walk_keeps_its_size(self):
        lons, _ = _framed_points(_path(), 0, 6, [{"lat": 35.03, "lon": 139.002}])  # ~3 km north
        assert len(lons) == 6

    def test_only_stopbys_beside_this_stretch_count(self):
        lons, _ = _framed_points(_path(), 0, 3, [{"lat": 35.001, "lon": 139.005}])  # nearest row is 5
        assert len(lons) == 3


class TestPinReveal:
    def test_the_pin_waits_for_the_voice(self):
        assert pin_reveal_time(reached=10.0, said=12.0, route_at=2.0) == 12.0

    def test_a_late_trace_is_not_waited_for_beyond_the_window(self):
        assert pin_reveal_time(reached=20.0, said=12.0, route_at=2.0, window=0.75) == 12.75

    def test_a_trace_inside_the_window_sets_the_time(self):
        assert pin_reveal_time(reached=12.4, said=12.0, route_at=2.0, window=0.75) == 12.4


class TestNeedsGlLabels:
    def test_japanese_without_its_own_style_uses_the_gl_page(self):
        assert needs_gl_labels({}, "ja", True)

    def test_english_a_missing_token_or_an_own_style_keep_the_raster_map(self):
        assert not needs_gl_labels({}, "en", True)
        assert not needs_gl_labels({}, "ja", False)
        assert not needs_gl_labels({"mapbox_style_id_ja": "me/ja"}, "ja", True)

    def test_a_chosen_background_is_never_switched(self):
        assert not needs_gl_labels({"overview_background": "raster"}, "ja", True)


def test_photo_card_moves_off_the_route_line():
    from services.vdoprocessing.pydeckrecorder.pedestrian import _clear_card_spot

    spot = lambda route: _clear_card_spot(route, 960, 540, 200, 112, 26, 16, 1920, 1080)  # noqa: E731
    vertical = [(960, y) for y in range(0, 1080, 4)]  # the route runs straight up through the marker
    left, top = spot(vertical)
    assert left > 960 or left + 200 < 960  # beside it, not above or below
    horizontal = [(x, 540) for x in range(0, 1920, 4)]
    assert spot(horizontal) == (960 - 100, 540 - 26 - 112)  # clear above: the old spot is kept
