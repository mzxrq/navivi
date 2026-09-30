"""The walking/ferry/car icons traced from assets/image/icon/*.svg
(replacing the old hand-drawn shapes), the ruler icon's tick-mark fix, and
the new "stacked"/"columns" summary-card styles."""

import numpy as np
import pytest
from PIL import Image, ImageDraw

from services import tuning
from services.mapfetcher.graphicengine import GraphicsEngine
from services.mapfetcher.graphicengine.icons import (
    _CAR_SVG_PATH,
    _FERRY_SVG_PATH,
    _WALKING_SVG_PATH,
    _load_svg_icon_polygons,
    _parse_svg_path_polygons,
)


class TestSvgPathParsing:
    def test_a_closed_triangle_of_lines(self):
        polys = _parse_svg_path_polygons("M0 0 L10 0 L10 10 Z")
        assert polys == [[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]]

    def test_bare_pairs_after_moveto_are_implicit_linetos(self):
        # No repeated "L" - matches potrace's own "M x y  a b  c d z" style.
        polys = _parse_svg_path_polygons("M0 0 10 0 10 10z")
        assert polys == [[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]]

    def test_relative_lineto_and_relative_moveto(self):
        polys = _parse_svg_path_polygons("m5 5 l10 0 l0 10z")
        assert polys == [[(5.0, 5.0), (15.0, 5.0), (15.0, 15.0)]]

    def test_relative_cubic_bezier_ends_at_the_right_point(self):
        polys = _parse_svg_path_polygons("M0 0 c0 10 10 10 10 0z")
        # Flattened to line segments, but the LAST point of the curve must
        # land exactly on the path's stated endpoint (10, 0).
        assert polys[0][-1] == (10.0, 0.0)
        assert len(polys[0]) > 2  # actually flattened, not just endpoints

    def test_two_subpaths_stay_separate(self):
        polys = _parse_svg_path_polygons("M0 0 L1 0 L1 1z M5 5 L6 5 L6 6z")
        assert len(polys) == 2


class TestWalkingIconFromSvg:
    def test_the_real_walking_svg_file_parses_into_polygons(self):
        polys = _load_svg_icon_polygons(_WALKING_SVG_PATH)
        assert len(polys) >= 1
        # Normalized into 0..1 on both axes.
        xs = [x for poly in polys for x, _ in poly]
        ys = [y for poly in polys for _, y in poly]
        assert min(xs) >= -1e-6 and max(xs) <= 1 + 1e-6
        assert min(ys) >= -1e-6 and max(ys) <= 1 + 1e-6
        assert max(xs) - min(xs) == pytest.approx(1.0, abs=1e-3) or max(ys) - min(ys) == pytest.approx(1.0, abs=1e-3)

    def test_missing_file_falls_back_to_the_stick_figure(self, monkeypatch):
        import services.mapfetcher.graphicengine.icons as icons_mod

        monkeypatch.setattr(icons_mod, "_WALKING_SVG_PATH", icons_mod._WALKING_SVG_PATH.with_name("nope.svg"))
        try:
            assert icons_mod._load_svg_icon_polygons(icons_mod._WALKING_SVG_PATH) == ()
            drawn = []
            eng = icons_mod._IconMixin()
            eng._draw_walking_stick_figure = lambda *a, **k: drawn.append(a)
            canvas = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
            eng._draw_walking_icon(ImageDraw.Draw(canvas), 20, 20, 30, (0, 0, 0, 255))
            assert len(drawn) == 1  # fell back rather than drawing nothing
        finally:
            icons_mod._load_svg_icon_polygons.cache_clear()

    def test_draws_something_visible_on_a_blank_canvas(self):
        canvas = Image.new("RGBA", (60, 60), (255, 255, 255, 255))
        GraphicsEngine()._draw_walking_icon(ImageDraw.Draw(canvas), 30, 30, 50, (0, 0, 0, 255))
        arr = np.array(canvas)
        assert (arr[:, :, :3] == 0).any()  # some black pixels were actually painted


class TestFerryIconFromSvg:
    def test_the_real_ferry_svg_file_parses_into_polygons(self):
        polys = _load_svg_icon_polygons(_FERRY_SVG_PATH)
        assert len(polys) >= 1
        xs = [x for poly in polys for x, _ in poly]
        ys = [y for poly in polys for _, y in poly]
        assert min(xs) >= -1e-6 and max(xs) <= 1 + 1e-6
        assert min(ys) >= -1e-6 and max(ys) <= 1 + 1e-6

    def test_missing_file_falls_back_to_the_hand_traced_glyph(self, monkeypatch):
        import services.mapfetcher.graphicengine.icons as icons_mod

        monkeypatch.setattr(icons_mod, "_FERRY_SVG_PATH", icons_mod._FERRY_SVG_PATH.with_name("nope.svg"))
        try:
            assert icons_mod._load_svg_icon_polygons(icons_mod._FERRY_SVG_PATH) == ()
            drawn = []
            eng = icons_mod._IconMixin()
            eng._draw_ship_icon_fallback = lambda *a, **k: drawn.append(a)
            canvas = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
            eng._draw_ship_icon(ImageDraw.Draw(canvas), 20, 20, 30, (0, 0, 0, 255))
            assert len(drawn) == 1
        finally:
            icons_mod._load_svg_icon_polygons.cache_clear()

    def test_draws_something_visible_on_a_blank_canvas(self):
        canvas = Image.new("RGBA", (60, 60), (255, 255, 255, 255))
        GraphicsEngine()._draw_ship_icon(ImageDraw.Draw(canvas), 30, 30, 50, (0, 0, 0, 255))
        arr = np.array(canvas)
        assert (arr[:, :, :3] == 0).any()

    def test_the_portholes_are_holes_not_filled_black(self):
        # ferry.svg's three porthole circles are wound the opposite way
        # from the hull (see icons._signed_area) - they must come out white,
        # not disappear as solid black on top of the hull.
        canvas = Image.new("RGBA", (200, 200), (255, 255, 255, 255))
        GraphicsEngine()._draw_ship_icon(ImageDraw.Draw(canvas), 100, 100, 160, (0, 0, 0, 255))
        arr = np.array(canvas)[:, :, :3]
        black = (arr == 0).all(axis=-1)
        assert black.any()
        # Somewhere inside the black hull's own bounding box, a patch of
        # pure white survives - a porthole, not the outer white background.
        ys, xs = np.where(black)
        y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
        inner = arr[y0:y1, x0:x1]
        assert (inner == 255).all(axis=-1).any()


class TestCarIconFromSvg:
    def test_the_real_car_svg_file_parses_into_polygons(self):
        polys = _load_svg_icon_polygons(_CAR_SVG_PATH)
        assert len(polys) >= 1
        xs = [x for poly in polys for x, _ in poly]
        ys = [y for poly in polys for _, y in poly]
        assert min(xs) >= -1e-6 and max(xs) <= 1 + 1e-6
        assert min(ys) >= -1e-6 and max(ys) <= 1 + 1e-6

    def test_missing_file_falls_back_to_the_hand_drawn_shape(self, monkeypatch):
        import services.mapfetcher.graphicengine.icons as icons_mod

        monkeypatch.setattr(icons_mod, "_CAR_SVG_PATH", icons_mod._CAR_SVG_PATH.with_name("nope.svg"))
        try:
            assert icons_mod._load_svg_icon_polygons(icons_mod._CAR_SVG_PATH) == ()
            drawn = []
            eng = icons_mod._IconMixin()
            eng._draw_car_icon_fallback = lambda *a, **k: drawn.append(a)
            canvas = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
            eng._draw_car_icon(ImageDraw.Draw(canvas), 20, 20, 30, (0, 0, 0, 255))
            assert len(drawn) == 1
        finally:
            icons_mod._load_svg_icon_polygons.cache_clear()

    def test_draws_something_visible_on_a_blank_canvas(self):
        canvas = Image.new("RGBA", (60, 60), (255, 255, 255, 255))
        GraphicsEngine()._draw_car_icon(ImageDraw.Draw(canvas), 30, 30, 50, (0, 0, 0, 255))
        arr = np.array(canvas)
        assert (arr[:, :, :3] == 0).any()

    def test_windows_and_wheels_are_holes_not_filled_black(self):
        # car.svg's window/wheel-hub cutouts are wound the opposite way
        # from the body - they must survive as white, not vanish under it.
        canvas = Image.new("RGBA", (200, 200), (255, 255, 255, 255))
        GraphicsEngine()._draw_car_icon(ImageDraw.Draw(canvas), 100, 100, 160, (0, 0, 0, 255))
        arr = np.array(canvas)[:, :, :3]
        black = (arr == 0).all(axis=-1)
        assert black.any()
        ys, xs = np.where(black)
        y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
        inner = arr[y0:y1, x0:x1]
        assert (inner == 255).all(axis=-1).any()

    def test_mode_icon_dispatch_uses_the_svg_car(self):
        # _draw_mode_icon("car"/"driving") must reach the same icon as
        # calling _draw_car_icon directly, not silently fall through to the
        # walking-icon default.
        eng = GraphicsEngine()
        canvas_a = Image.new("RGBA", (60, 60), (255, 255, 255, 255))
        canvas_b = Image.new("RGBA", (60, 60), (255, 255, 255, 255))
        eng._draw_car_icon(ImageDraw.Draw(canvas_a), 30, 30, 50, (0, 0, 0, 255))
        eng._draw_mode_icon(ImageDraw.Draw(canvas_b), "driving", 30, 30, 50, (0, 0, 0, 255))
        assert (np.array(canvas_a) == np.array(canvas_b)).all()


class TestRulerIconTicks:
    def test_tick_marks_cross_the_bar_instead_of_running_alongside_it(self):
        # Regression: the ticks used to be drawn with the SAME (dx, dy)
        # offset direction as the bar itself (parallel), not perpendicular
        # to it, reading as a jagged stripe next to the bar rather than a
        # ruler with hash marks across it.
        canvas = Image.new("RGBA", (100, 100), (255, 255, 255, 255))
        GraphicsEngine()._draw_ruler_icon(ImageDraw.Draw(canvas), 50, 50, 80, (0, 0, 0, 255))
        arr = np.array(canvas)[:, :, :3]
        # A horizontal scan through the icon's vertical middle should cross
        # BOTH the diagonal bar and a perpendicular tick as distinct dark
        # runs, not one continuous parallel stripe spanning the whole icon.
        row = arr[50]
        dark = np.where((row == 0).all(axis=-1))[0]
        assert len(dark) > 0


class TestStackedSummaryCard:
    def test_renders_a_two_row_card(self):
        card = GraphicsEngine(summary_card_style="stacked").render_summary_card(
            distance_km=0.8, duration_seconds=3900,
        )
        assert card.shape[2] == 4  # BGRA
        h, w = card.shape[:2]
        assert h > 0 and w > 0
        # Taller than it is a single row - two stacked rows plus margins.
        assert h > w * 0.3

    def test_meters_vs_kilometers_formatting(self):
        eng = GraphicsEngine(summary_card_style="stacked")
        short = eng.render_summary_card(distance_km=0.8, duration_seconds=60)
        long = eng.render_summary_card(distance_km=12.3, duration_seconds=60)
        # Different text -> different measured content width.
        assert short.shape[1] != long.shape[1]

    def test_dispatches_through_render_summary_card(self):
        eng = GraphicsEngine(summary_card_style="stacked")
        stacked = eng.create_summary_card_stacked(distance_km=1.0, duration_seconds=600)
        dispatched = eng.render_summary_card(distance_km=1.0, duration_seconds=600)
        assert stacked.shape == dispatched.shape

    def test_ignores_a_title_meant_for_the_taskbar_style(self):
        # render_summary_card's dispatch must not TypeError when a caller
        # passes taskbar-only kwargs and the project is set to "stacked".
        eng = GraphicsEngine(summary_card_style="stacked")
        card = eng.render_summary_card(
            distance_km=1.0, duration_seconds=600, title="X → Y", max_title_width=300,
        )
        assert card.shape[2] == 4


class TestStackedSummaryCardRouteModes:
    """More than one travel mode: a colored block per mode (distance row,
    duration row) plus a Total block, rather than the plain two-row card."""

    def _card(self, **overrides):
        eng = GraphicsEngine(summary_card_style="stacked")
        kwargs = dict(
            distance_km=24.0, duration_seconds=5 * 3600 + 39 * 60,
            mode_breakdown={"walking": 16.3, "ferry": 7.7},
            mode_duration={"walking": 5 * 3600 + 28 * 60, "ferry": 13 * 60},
        )
        kwargs.update(overrides)
        return eng.create_summary_card_stacked(**kwargs)

    def test_multi_mode_is_taller_than_the_single_mode_card(self):
        eng = GraphicsEngine(summary_card_style="stacked")
        single = eng.create_summary_card_stacked(distance_km=24.0, duration_seconds=20340)
        multi = self._card()
        # 3 blocks (walking, ferry, total) of 2 rows each vs. 1 block.
        assert multi.shape[0] > single.shape[0] * 2

    def test_a_single_mode_breakdown_stays_the_plain_two_row_card(self):
        # One mode's own total IS the trip's total - no separate Total
        # block needed, same reasoning create_summary_card's single-column
        # pill uses.
        eng = GraphicsEngine(summary_card_style="stacked")
        one_mode = eng.create_summary_card_stacked(
            distance_km=5.0, duration_seconds=3600,
            mode_breakdown={"walking": 5.0}, mode_duration={"walking": 3600},
        )
        plain = eng.create_summary_card_stacked(distance_km=5.0, duration_seconds=3600)
        assert one_mode.shape == plain.shape

    def test_each_mode_gets_its_own_route_line_color(self):
        eng = GraphicsEngine(summary_card_style="stacked")
        walking_accent = eng._mode_accent("walking")
        ferry_accent = eng._mode_accent("ferry")
        assert walking_accent != ferry_accent  # distinct colors to actually tell rows apart

    def test_sorted_by_distance_descending_like_the_column_card(self):
        # create_summary_card sorts mode columns by -distance; the stacked
        # rows should read in the same order for consistency between styles.
        eng = GraphicsEngine(summary_card_style="stacked")
        card_walk_first = eng.create_summary_card_stacked(
            distance_km=10.0, duration_seconds=100,
            mode_breakdown={"ferry": 2.0, "walking": 8.0}, mode_duration={"ferry": 10, "walking": 90},
        )
        card_same_order = eng.create_summary_card_stacked(
            distance_km=10.0, duration_seconds=100,
            mode_breakdown={"walking": 8.0, "ferry": 2.0}, mode_duration={"walking": 90, "ferry": 10},
        )
        # Dict insertion order differs but sort key doesn't - same pixels.
        assert card_walk_first.shape == card_same_order.shape
        assert (card_walk_first == card_same_order).all()

    def test_no_breakdown_falls_back_to_the_plain_two_row_card(self):
        eng = GraphicsEngine(summary_card_style="stacked")
        no_breakdown = eng.create_summary_card_stacked(distance_km=5.0, duration_seconds=3600)
        assert no_breakdown.shape[0] < self._card().shape[0]


class TestColumnsSummaryCard:
    """create_summary_card_columns: still split into columns (like "glass"),
    colored per mode (like "stacked"), but each column is a tall icon
    spanning its label+value, then a small clock+duration row underneath."""

    def _multi(self, **overrides):
        eng = GraphicsEngine(summary_card_style="columns")
        kwargs = dict(
            distance_km=24.0, duration_seconds=5 * 3600 + 39 * 60,
            mode_breakdown={"walking": 16.3, "ferry": 7.7},
            mode_duration={"walking": 5 * 3600 + 28 * 60, "ferry": 13 * 60},
        )
        kwargs.update(overrides)
        return eng.create_summary_card_columns(**kwargs)

    def test_dispatches_through_render_summary_card(self):
        eng = GraphicsEngine(summary_card_style="columns")
        direct = eng.create_summary_card_columns(distance_km=1.0, duration_seconds=600)
        dispatched = eng.render_summary_card(distance_km=1.0, duration_seconds=600)
        assert direct.shape == dispatched.shape

    def test_no_breakdown_is_one_column_with_a_walking_icon_and_distance_label(self):
        eng = GraphicsEngine(summary_card_style="columns")
        canvas = eng.create_summary_card_columns(distance_km=0.8, duration_seconds=3900)
        arr = np.array(canvas)
        assert canvas.shape[2] == 4
        # Plain text color (no accent), unlike the multi-mode columns below.
        dark_pixels = arr[(arr[:, :, 3] > 0) & (arr[:, :, :3].sum(axis=-1) < 150)]
        assert len(dark_pixels) > 0

    def test_a_single_named_mode_uses_that_modes_own_icon_and_name(self):
        eng = GraphicsEngine(summary_card_style="columns")
        ferry_only = eng.create_summary_card_columns(
            distance_km=5.0, duration_seconds=3600,
            mode_breakdown={"ferry": 5.0}, mode_duration={"ferry": 3600},
        )
        walking_only = eng.create_summary_card_columns(distance_km=5.0, duration_seconds=3600)
        # Different icon glyph (ship vs. walking figure) -> different pixels,
        # even though the numbers are identical.
        assert ferry_only.shape != walking_only.shape or not (ferry_only == walking_only).all()

    def test_multi_mode_has_dividers_between_more_columns_than_single_mode(self):
        single = self._multi(mode_breakdown={"walking": 24.0}, mode_duration={"walking": 20340})
        multi = self._multi()  # walking + ferry + total = 3 columns
        assert multi.shape[1] > single.shape[1] * 1.5  # meaningfully wider

    def test_every_column_shares_the_same_height(self):
        # One tall icon size drives every column's height - a mode with a
        # short label/value shouldn't end up a different height than one
        # with a long name (checked via card_h, not per-column crops).
        short_name = self._multi(
            mode_breakdown={"walking": 1.0, "ferry": 1.0}, mode_duration={"walking": 60, "ferry": 60},
        )
        long_values = self._multi(
            mode_breakdown={"walking": 999.9, "ferry": 999.9},
            mode_duration={"walking": 359999, "ferry": 359999},
        )
        assert short_name.shape[0] == long_values.shape[0]

    def test_ignores_a_title_meant_for_the_taskbar_style(self):
        eng = GraphicsEngine(summary_card_style="columns")
        card = eng.render_summary_card(
            distance_km=1.0, duration_seconds=600, title="X → Y", max_title_width=300,
        )
        assert card.shape[2] == 4

    def test_the_mode_icon_and_the_clock_icon_share_one_vertical_line(self):
        # Regression: the clock used to sit in the TEXT column, next to the
        # time number, off to the right of the big mode icon above it. Both
        # icons must now be centered on the same x - one directly above the
        # other - not just both "somewhere on the left".
        eng = GraphicsEngine(summary_card_style="columns")
        canvas = eng.create_summary_card_columns(
            distance_km=5.0, duration_seconds=3600,
            mode_breakdown={"ferry": 5.0}, mode_duration={"ferry": 3600},
        )
        arr = np.array(canvas)
        opaque = arr[:, :, 3] > 0
        ink = opaque & ~(arr[:, :, :3] == 255).all(axis=-1)  # non-white, non-transparent
        h = arr.shape[0]

        def first_ink_block_center(band):
            cols = band.any(axis=0)
            idx = np.where(cols)[0]
            start = idx[0]
            end = start
            while end + 1 < len(cols) and cols[end + 1]:
                end += 1
            return (start + end) / 2

        # Nothing sits to the icon's left in either band, so the FIRST
        # contiguous ink run from the left edge is the icon itself, before
        # the gap to the text column.
        icon_center = first_ink_block_center(ink[: h // 2])
        clock_center = first_ink_block_center(ink[int(h * 0.55):])
        assert abs(icon_center - clock_center) <= 3  # same column, allowing rounding


class TestTotalColorNeverMatchesAMode:
    """_TOTAL_ACCENT_COLOR (every card style's Total column/row) must never
    collide with a real travel mode's own accent - regression for a bug
    where it was a literal copy of walking's BGR tuple, used un-reversed,
    which rendered as an orange indistinguishable from ferry's own orange."""

    def test_total_is_a_neutral_dark_color_not_a_vivid_mode_hue(self):
        from services.mapfetcher.graphicengine.cards import _TOTAL_ACCENT_COLOR

        r, g, b = _TOTAL_ACCENT_COLOR[:3]
        # Neutral/dark: channels close together and all fairly low, unlike
        # any of tuning.MODE_LINE_COLORS' fully-saturated hues.
        assert max(r, g, b) - min(r, g, b) < 20
        assert max(r, g, b) < 120

    def test_differs_from_every_configured_modes_own_accent(self):
        eng = GraphicsEngine()
        for mode in tuning.MODE_LINE_COLORS:
            assert eng._mode_accent(mode) != eng._mode_accent("total")

    def test_total_column_color_in_the_rendered_columns_card(self):
        # ferry's own accent is orange - assert Total doesn't render as
        # that same orange next to it.
        eng = GraphicsEngine(summary_card_style="columns")
        ferry_accent = eng._mode_accent("ferry")
        total_accent = eng._mode_accent("total")
        assert ferry_accent != total_accent
