"""A repeated overview {n}: the voice names stop n again on the way back, timing the return stop there."""

import numpy as np

from services.localization.cues import cue_times, strip_cues
from services.vdoprocessing.spatial_renderer.course import (
    _course_timing, _set_reveal_times, _split_popups, distance_at,
)

SCRIPT = "{start}行きます。{route}{4}桟橋です。{go}{5}砲台跡へ。{4}桟橋に戻ります。{go}{end}終わりです。"


def test_a_repeated_number_and_its_go_are_cues_of_their_own():
    clean, cues = strip_cues(SCRIPT)

    assert [c.tag for c in cues] == ["start", "route", "4", "go4", "5", "4#2", "go4#2", "end"]
    times = cue_times(cues, clean, 30.0)
    assert times["4"] < times["go4"] <= times["5"] < times["4#2"] < times["go4#2"]  # "{go}{5}": one moment


def test_a_third_visit_counts_on_and_other_numbers_start_at_their_first():
    assert [c.tag for c in strip_cues("{3}a{4}b{3}c{3}d")[1]] == ["3", "4", "3#2", "3#3"]


# The route goes out along y=0 past stop 4 (the pier) and 5, and comes back over the pier to the end.
PATH = np.array([(0, 0), (100, 0), (200, 0), (100, 0), (0, 40)], dtype=float)


def _stops():
    def popup(index, order, x, y, **more):
        return {"index": index, "order": order, "x": x, "y": y, "data": {}, **more}

    return [popup(0, 0, 0, 0), popup(1, 4, 100, 0), popup(2, 5, 200, 0),
            popup(3, 4, 100, 0, is_return=True), popup(4, 6, 0, 40)]


def _timed(cues):
    popups = _stops()
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(PATH, axis=0).T))])
    on_route, extras, end = _split_popups(popups, len(popups), PATH, cum, float(cum[-1]))
    numbered = [ap for ap in on_route if ap["index"] != 0 and ap is not end]
    timing = _course_timing(cues, 40.0, numbered, extras, float(cum[-1]))
    _set_reveal_times(on_route, end, cues, timing, 30)
    return popups, timing


CUES = {"start": 0.0, "route": 1.0, "4": 5.0, "go4": 8.0, "5": 12.0, "4#2": 22.0, "go4#2": 26.0, "end": 34.0}


def test_the_second_cue_times_the_return_stop_and_leaves_the_first_alone():
    (_, first, _, back, _), timing = _timed(CUES)

    assert (first["course_dist"], back["course_dist"]) == (100.0, 300.0)
    assert distance_at(timing.anchors, 5.0) == 100.0 == distance_at(timing.anchors, 8.0)  # waits for {go}
    assert distance_at(timing.anchors, 22.0) == 300.0 == distance_at(timing.anchors, 26.0)  # and again
    assert distance_at(timing.anchors, 24.0) == 300.0
    assert first["course_at"] <= 5.0 + 1e-6 and 22.0 - 1e-6 <= back["course_at"] <= 23.0 + 1e-6


def test_without_a_second_cue_the_return_stop_is_passed_not_timed_by_the_first():
    (_, first, _, back, _), timing = _timed({k: v for k, v in CUES.items() if "#" not in k})

    assert distance_at(timing.anchors, 5.0) == 100.0
    assert back["course_at"] > 12.0  # revealed when the trace gets there, not when the first visit was named
