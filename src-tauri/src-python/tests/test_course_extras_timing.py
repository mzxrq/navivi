"""The course overview's stop-bys and closed places come one at a time across their own sentence."""

from services.vdoprocessing.spatial_renderer.course import _Timing, _set_reveal_times


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
