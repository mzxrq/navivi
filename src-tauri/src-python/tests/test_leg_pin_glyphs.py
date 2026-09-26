"""A leg's map shows the overview's own pin glyphs: S, 1, 2 ... E."""

from services import tuning
from services.vdoprocessing.videopipeline.render_step import _leg_pin, overview_pin_glyphs


def _wps(*stopby_flags):
    return [{"id": str(i), "isStopBy": f} for i, f in enumerate(stopby_flags)]


def test_numbers_skip_the_start_and_stop_bys():
    glyphs = overview_pin_glyphs(_wps(False, True, True, False, False, True, False))
    assert [glyphs[i] for i in range(7)] == ["S", "・", "・", "1", "2", "・", "E"]


def test_a_single_stop_route_keeps_its_number():
    glyphs = overview_pin_glyphs(_wps(False, False))
    assert glyphs == {0: "S", 1: "1"}


def test_colors_match_the_overview():
    assert _leg_pin("S", {}, arrived=True)["color"] == tuning.START_PIN_COLOR
    assert _leg_pin("E", {}, arrived=False)["color"] == tuning.END_PIN_COLOR
    assert _leg_pin("・", {}, arrived=False)["color"] == tuning.STOPBY_PIN_COLOR
    departed, ahead = _leg_pin("3", {}, arrived=True), _leg_pin("3", {}, arrived=False)
    assert departed["glyph"] == ahead["glyph"] == "3"
    assert departed["color"] != ahead["color"]  # the visited pin is the darker shade


def test_no_glyph_no_pin():
    assert _leg_pin(None, {}, arrived=True) is None
