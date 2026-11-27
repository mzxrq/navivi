"""The course overview's stop-bys and closed places come one at a time across their own sentence."""

import pytest

from services.vdoprocessing.spatial_renderer.course import _course_timing, _set_reveal_times, _Timing


def _timing(stopbys, closed, extras_at, closed_at, end_at):
    return _Timing([(0.0, 0.0), (10.0, 1.0)], 0.0, 10.0, 12.0, extras_at, closed_at, end_at, stopbys, closed)


def test_stopbys_spread_across_their_sentence_and_closed_ones_across_theirs():
    stopbys = [{"data": {}} for _ in range(5)]
    closed = [{"data": {"inaccessible": True}} for _ in range(2)]
    _set_reveal_times([], None, {}, _timing(stopbys, closed, 20.0, 30.0, 40.0), 30)
    at = [ap["course_at"] for ap in stopbys]
    assert at[0] == 20.0 and at[-1] < 30.0
    assert all(b - a > 1.0 for a, b in zip(at, at[1:]))  # one at a time, not a burst
    assert closed[0]["course_at"] == 30.0 and closed[-1]["course_at"] <= 40.0 - 1.5


def test_a_short_sentence_still_shows_every_place():
    stopbys = [{"data": {}} for _ in range(10)]
    _set_reveal_times([], None, {}, _timing(stopbys, [], 20.0, None, 22.0), 30)
    assert stopbys[-1]["course_at"] - stopbys[0]["course_at"] >= 9 * 0.15 - 1e-9


@pytest.mark.parametrize("cues, shown", [
    ({}, []), ({"extras": 20.0}, [0]), ({"closed": 25.0}, [1]), ({"extras": 20.0, "closed": 25.0}, [0, 1])])
def test_a_group_shows_only_with_its_own_cue(cues, shown):
    places = [{"data": {}}, {"data": {"inaccessible": True}}]  # a stop-by, a closed place
    timing = _course_timing(cues, 10.0, [], places, 100.0)
    assert [id(p) for p in timing.stopbys + timing.closed] == [id(places[i]) for i in shown]
    assert (timing.extras_at, timing.closed_at) == (cues.get("extras"), cues.get("closed"))


def test_places_with_no_cue_do_not_lengthen_the_video():
    places = [{"data": {}}, {"data": {"inaccessible": True}}]
    assert _course_timing({}, 10.0, [], places, 100.0).end_at == _course_timing({}, 10.0, [], [], 100.0).end_at
