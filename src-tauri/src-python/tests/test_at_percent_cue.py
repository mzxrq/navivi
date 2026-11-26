import pandas as pd

from services.localization.cues import strip_cues
from services.vdoprocessing.pydeckrecorder.pedestrian import _at_points_plan
from services.vdoprocessing.videopipeline.narration_step import at_spans

KM = [i / 100 for i in range(101)]  # a straight 1 km leg, a point every 10 m
DF = pd.DataFrame({"lat": [35.0 + i * 0.00009 for i in range(101)], "lon": [135.0] * 101})


def test_at_percent_is_a_cue_never_spoken():
    clean, cues = strip_cues("Walk west.{at 50%} Pass the shrine.{at 1} Turn.")
    assert clean == "Walk west. Pass the shrine. Turn."
    assert [c.tag for c in cues] == ["at1:50%", "at2:1"]
    assert sorted(at_spans({"at1:50%": 3.0, "at2:1": 5.0}, 2), key=lambda s: s[1]) == [(2, 3.0, "50%"), (2, 5.0, 1)]


def test_the_walker_is_halfway_when_the_voice_reaches_at_50_percent():
    assert _at_points_plan(DF, KM, [(100, 10.0)], [(0, 7.0, "50%")]) == [(50, 7.0, 0.0, 0), (100, 3.0, 0.0, 0)]


def test_percent_counts_within_its_own_piece_and_from_its_start():
    plan = _at_points_plan(DF, KM, [(50, 5.0), (100, 10.0)], [(1, 6.0, "50%")], start_cue_seconds=[None, 2.0])
    assert plan == [(50, 5.0, 0.0, 0), (75, 4.0, 0.0, 1), (100, 6.0, 0.0, 1)]


def test_out_of_order_or_out_of_range_percent_is_skipped():
    plan = [(100, 10.0)]
    assert _at_points_plan(DF, KM, plan, [(0, 3.0, "60%"), (0, 6.0, "30%")]) == [(60, 3.0, 0.0, 0), (100, 7.0, 0.0, 0)]
    assert _at_points_plan(DF, KM, plan, [(0, 3.0, "100%")]) == [(100, 10.0, 0.0, 0)]
