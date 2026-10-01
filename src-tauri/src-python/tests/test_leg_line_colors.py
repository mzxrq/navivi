from services.mapfetcher.graphicengine.drawing import _DrawingMixin
from services.vdoprocessing.spatial_renderer.overview_pacing import _OverviewPacingMixin
from services.vdoprocessing.videopipeline.helpers import _build_point_colors, leg_line_color_rgb


class _Engine(_DrawingMixin):
    MODE_COLORS = {"walking": (1, 1, 1), "ferry": (2, 2, 2)}
    line_color = (9, 9, 9)


def test_leg_line_color_reads_rgb_and_ignores_junk():
    assert leg_line_color_rgb({"lineColor": [10, 20, 300]}) == [10, 20, 255]
    assert leg_line_color_rgb({"lineColor": "red"}) is None
    assert leg_line_color_rgb({}) is None


def test_point_colors_follow_the_departing_waypoint_as_bgr():
    waypoints = [{"lineColor": [10, 20, 30]}, {}, {"lineColor": [1, 2, 3]}]
    colors = _build_point_colors(7, [0, 2, 4], waypoints)
    assert colors[:3] == [None, (30, 20, 10), (30, 20, 10)]
    assert colors[3:5] == [None, None]
    assert colors[5:] == [None, None]  # nothing departs the last waypoint


def test_drawing_uses_leg_color_over_mode_color():
    path = [(0, 0), (1, 1), (2, 2), (3, 3)]
    history = ["walking", "walking", ("walking", (50, 60, 70)), ("walking", (50, 60, 70))]
    segments = _Engine()._mode_segments(path, history)
    assert [color for color, _ in segments] == [(1, 1, 1), (50, 60, 70)]


def test_color_breakpoints_reuse_the_mode_breakpoint_rules():
    points = [(0, 0), (1, 0), (2, 0), (3, 0)]
    colors = [None, None, (5, 5, 5), (5, 5, 5)]
    breakpoints = _OverviewPacingMixin._build_mode_breakpoints(points, colors)
    assert _OverviewPacingMixin._mode_at_fraction(breakpoints, 0.1) is None
    assert _OverviewPacingMixin._mode_at_fraction(breakpoints, 0.9) == (5, 5, 5)
