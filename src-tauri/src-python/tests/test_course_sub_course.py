"""Whole route first draws the sub course after the totals card and before the stop-bys (OVERVIEW_RULES 8.17)."""
from types import SimpleNamespace

import numpy as np
import pytest

from services.vdoprocessing.spatial_renderer.course import _course_timing, _CourseOverviewMixin
from services.vdoprocessing.storyboard import of

FPS = 30
PLACES = [{"data": {}}, {"data": {"inaccessible": True}}]  # a stop-by, a closed place


def _timing(sub, extras=12.0, closed=16.0):
    cues = {"end": 9.0, "distance": 10.0, "extras": extras, "closed": closed}
    return _course_timing(cues, 14.0, [], PLACES, 100.0, 3.0, sub)


def test_the_stopbys_wait_for_the_sub_course_to_finish():
    timing = _timing(sub=9.0)
    assert timing.sub_at == 13.0  # the totals card, held 3 s
    assert (timing.extras_at, timing.closed_at) == (22.0, 26.0)  # both pushed back alike
    assert timing.end_at >= timing.closed_at + 3.0


def test_a_late_extras_cue_is_not_moved():
    assert (_timing(sub=9.0, extras=30.0, closed=40.0).extras_at, _timing(sub=9.0).sub_at) == (30.0, 13.0)


def test_without_a_sub_course_nothing_moves():
    timing = _timing(sub=0.0)
    assert timing.sub_at is None and (timing.extras_at, timing.closed_at) == (12.0, 16.0)


def test_with_no_stopby_cue_the_video_still_runs_to_the_end_of_the_sub_course():
    timing = _course_timing({"distance": 10.0}, 11.0, [], PLACES, 100.0, 3.0, 9.0)
    assert timing.sub_at == 13.0 and timing.end_at >= 22.0


def test_the_storyboards_say_where_the_sub_course_goes():
    assert [of(s).sub_course_slot for s in ("walk", "map", "course")] == [
        "after_totals", "after_totals", "before_stopbys"]


@pytest.mark.parametrize("sub_at", [None, 2.0])
def test_the_sub_course_takes_the_place_of_course_frames(sub_at):
    written = []

    class _Video:
        frames_written = property(lambda self: len(written))
        write = staticmethod(written.append)

    video = _Video()
    course = _CourseOverviewMixin()
    course._course_zooms = []
    course._course_plate_state = lambda *a, **k: ()
    course._course_overlay = lambda *a, **k: (None, None)
    course._course_ripples = lambda *a: []
    course._initial_heading = lambda path: 0.0
    course._course_frame = lambda *a, **k: "course"
    course._render_sub_course_part = lambda v, fps, bg, frame: [v.write("sub") for _ in range(45)]
    timing = SimpleNamespace(end_at=6.0, sub_at=sub_at, extras_at=None, trace_end=1.0)
    scene = SimpleNamespace(fps=FPS)
    course._course_play(video, scene, np.zeros((4, 4, 3), np.uint8), SimpleNamespace(path=None), timing,
                        SimpleNamespace(reserved=[]), 1.0, np.zeros((4, 4, 3), np.uint8))
    assert len(written) == 6 * FPS  # the same length either way
    assert written.count("sub") == (0 if sub_at is None else 45)
    if sub_at is not None:
        assert written[int(sub_at * FPS)] == "sub" and written[int(sub_at * FPS) - 1] == "course"
