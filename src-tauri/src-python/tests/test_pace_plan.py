from services.localization.cues import strip_cues
from services.vdoprocessing.pydeckrecorder.pedestrian import _paced_plan
from services.vdoprocessing.videopipeline.narration_step import pace_spans

KM = [i / 100 for i in range(101)]  # a 1 km leg, a route point every 10 m


def test_pace_cues_are_never_spoken_and_close_with_their_sentence():
    clean, cues = strip_cues("Walk on {slow}past the old houses.{/slow} Then {stop}look up. {fast}Hurry on.")
    assert clean == "Walk on past the old houses. Then look up. Hurry on."
    assert [c.tag for c in cues] == ["slow1", "slowend1", "stop1", "fast1", "stopend1", "fastend1"]
    times = {"slow1": 1.0, "slowend1": 3.0, "stop1": 4.0, "stopend1": 5.0, "fast1": 4.5, "fastend1": 7.0}
    assert pace_spans(times, 0) == [(0, "slow", 1.0, 3.0), (0, "stop", 4.0, 4.5), (0, "fast", 4.5, 7.0)]  # no overlap


def test_slow_halves_the_pace_and_the_piece_keeps_its_length():
    plan, stops, held = _paced_plan(KM, [(100, 10.0)], [(0, "slow", 2.0, 6.0)])
    assert plan == [(25, 2.0), (50, 4.0), (100, 4.0)]  # 25 points in 2 s, 25 in 4 s (half), 50 in 4 s
    assert stops == [] and held == 0.0


def test_stop_holds_without_a_card_and_the_arrival_stays():
    plan, stops, held = _paced_plan(KM, [(100, 10.0)], [(0, "stop", 4.0, 6.0)])
    assert plan == [(50, 4.0), (100, 4.0)] and stops == [(4.0, "stop", 2.0)] and held == 2.0
    plan, stops, held = _paced_plan(KM, [(100, 10.0)], [(0, "stop", 8.0, 10.0)])  # stands at the end
    assert plan == [(100, 8.0)] and stops == [(8.0, "stop", 2.0)]


def test_cue_times_count_from_start_and_short_stops_are_ignored():
    assert _paced_plan(KM, [(100, 10.0)], [(0, "slow", 5.0, 9.0)], start_cue_seconds=3.0)[0] == [(25, 2.0), (50, 4.0), (100, 4.0)]
    assert _paced_plan(KM, [(100, 10.0)], [(0, "stop", 4.0, 4.5)]) == ([(100, 10.0)], [], 0.0)


def test_a_later_piece_is_paced_on_its_own_and_every_piece_ends_where_it_did():
    plan, _, _ = _paced_plan(KM, [(50, 5.0), (100, 5.0)], [(1, "fast", 1.0, 3.0)])
    assert plan[0] == (50, 5.0) and plan[-1][0] == 100 and abs(sum(s for _, s in plan) - 10.0) < 1e-9
    (i1, _), (i2, fast_s), (i3, after_s) = plan[1:]
    assert fast_s == 2.0 and after_s == 2.0
    assert 1.4 < (i2 - i1) / (i3 - i2) < 1.8  # ~1.6x the points per second of the rest (snapped to route points)


def test_adding_or_removing_pace_cues_re_renders_the_leg():
    from services.vdoprocessing.route2vdo import leg_changed_parts

    base = {"route_inputs": "r", "render_version": "v"}
    assert "kw.pace_cues" in leg_changed_parts({**base, "kw.pace_cues": "x"}, base)
    assert "kw.pace_cues" in leg_changed_parts(base, {**base, "kw.pace_cues": "x"})
    assert leg_changed_parts(base, base) == []
