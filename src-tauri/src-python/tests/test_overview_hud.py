"""The overview's top bar (docs/OVERVIEW_RULES.md 8.14): the project's title on the left; what is left of the route
over the whole route on the right. The same in every style."""
from types import SimpleNamespace

import numpy as np

from services import tuning, video_text
from services.mapfetcher.graphicengine import GraphicsEngine
from services.vdoprocessing.spatial_renderer.course import _CourseOverviewMixin

W, H = 1920, 1080
TOTALS = {"remaining_km": 14.3, "remaining_seconds": 600, "total_km": 23.9, "total_seconds": 13680}


def _engine():
    engine = GraphicsEngine()
    engine.theme, engine.ui = "light", tuning.UI_THEMES["light"]
    return engine


def _hud(**kwargs):
    frame = np.full((H, W, 3), 200, np.uint8)
    return frame, _engine().render_overview_hud(frame, **kwargs)


def test_hud_draws_both_corners_and_nothing_else():
    frame, out = _hud(title="Trip", **TOTALS)
    changed = out != frame
    assert changed[:200, :500].any() and changed[:200, -500:].any()
    assert not changed[200:, :].any() and not changed[:, 700:1200].any()


def test_hud_skips_missing_pieces():
    frame, out = _hud()
    assert not (out != frame).any()


def test_missing_totals_draw_the_title_only():
    left, right = _engine().overview_hud_panels(W, "Trip", None, None, None, None)
    assert left is not None and right is None


def test_the_right_panel_is_what_is_left_over_the_whole_route_in_one_format():
    engine = _engine()
    engine.overview_hud_panels(W, None, **TOTALS)
    labels = video_text.current_labels()
    rows = [(labels[key].format(distance=d, duration=engine._format_duration_ja(s)), 20, False)
            for key, d, s in (("overview_remaining_hud", "14.3 km", 600), ("overview_total_hud", "23.9 km", 13680))]
    assert tuple(rows) in [key[0] for key in engine._hud_panels]


def test_nothing_left_reads_as_zero_minutes_not_one_second():
    engine = _engine()
    engine.overview_hud_panels(W, None, 0.0, 0.0, 23.9, 13680)
    labels = video_text.current_labels()
    row = labels["overview_remaining_hud"].format(distance="0 m", duration=labels["duration_minutes"].format(m=0))
    assert any(key[0][0][0] == row for key in engine._hud_panels)


def test_a_long_title_stays_inside_its_panel_and_clear_of_the_right_one():
    left, right = _engine().overview_hud_panels(W, "和歌山市の友ヶ島をめぐる葛城修験の道" * 4, **TOTALS)
    assert left.size[0] <= W * tuning.OVERVIEW_HUD_TITLE_MAX_WIDTH
    assert left.size[0] + right.size[0] + 3 * 32 <= W


def test_the_course_top_bar_counts_down_with_the_trace():
    seen = {}
    course = _CourseOverviewMixin()
    course.graphics = SimpleNamespace(render_overview_hud=lambda frame, **kwargs: seen.update(kwargs) or frame)
    panels = SimpleNamespace(title="Trip", total_km=20.0, total_seconds=1000.0, margin=32, rail_marks=[],
                             summary_card=None, closed=[])
    timing = SimpleNamespace(route_at=0.0, extras_at=None, closed=[], closed_at=None)
    trace = SimpleNamespace(modes=["walking"], cum=np.array([0.0, 200.0]))
    # the rail's own total is a hair longer than the traced path: the bar once ended on "0 m ・ 1 s left"
    course._composite_course_panels(np.zeros((H, W, 3), np.uint8), 0, 5.0, 50.0, 0, trace, timing, panels, 200.4)
    assert seen["title"] == "Trip" and (seen["total_km"], seen["total_seconds"]) == (20.0, 1000.0)
    assert (seen["remaining_km"], seen["remaining_seconds"]) == (15.0, 750.0)  # a quarter of the way
    course._composite_course_panels(np.zeros((H, W, 3), np.uint8), 0, 9.0, 200.0, 0, trace, timing, panels, 200.4)
    assert (seen["remaining_km"], seen["remaining_seconds"]) == (0.0, 0.0)
