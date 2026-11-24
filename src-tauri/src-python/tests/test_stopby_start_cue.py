from services.vdoprocessing.pydeckrecorder.pedestrian import _paced_plan, _piece_lead
from services.vdoprocessing.videopipeline.leg_sequence import _plan_pieces
from services.vdoprocessing.videopipeline.narration_step import CueStore

KM = [i / 100 for i in range(101)]


def test_a_connected_stopby_piece_keeps_its_own_start_cue(tmp_path):
    store = CueStore(tmp_path)
    for key in ("a", "b", "c"):
        store.set_cue_times(key, {"start": 2.0})
    waypoints = [{"id": "s"}, {"id": "a"}, {"id": "b"}, {"id": "c"}]
    plans, _, _ = _plan_pieces(store, waypoints, 0, [1, 2, 3], [0, 10.0, 10.0, 10.0], [5.0] * 3, True, 3.0, at_start={2})
    assert plans[1][1] == 2.0  # the leg's first piece, as before
    assert plans[2][1] is None  # pops up without walking: nothing to start
    assert plans[3][1] == 2.0  # the piece after the stop-by now waits for its {start}


def test_piece_lead_takes_one_value_per_piece_or_the_first_only():
    assert _piece_lead([1.0, None, 3.0], 2) == 3.0 and _piece_lead([1.0, None], 1) == 0.0 and _piece_lead([1.0], 5) == 0.0
    assert _piece_lead(4.0, 0) == 4.0 and _piece_lead(4.0, 1) == 0.0 and _piece_lead(None, 0) == 0.0


def test_a_later_pieces_pace_cues_count_from_its_start():
    plan, _, _ = _paced_plan(KM, [(50, 5.0), (100, 10.0)], [(1, "slow", 5.0, 9.0)], start_cue_seconds=[None, 3.0])
    assert plan[1][1] == 2.0 and plan[1][3] == 1  # slow from voice 5 s = 2 s after the piece's {start} at 3 s
    assert plan[-1][0] == 100 and abs(sum(e[1] for e in plan) - 15.0) < 1e-9
