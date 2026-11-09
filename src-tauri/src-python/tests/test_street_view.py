from pathlib import Path

from services.localization.cues import clean_text, strip_cues
from services.mapfetcher.street_photos import street_view_landmarks, view_cue_spans

# Two legs: one going east from (35.0, 135.0), one going north from its end.
EAST = [[35.0, 135.0 + i * 0.0002] for i in range(11)]
NORTH = [[35.0 + i * 0.0002, 135.002] for i in range(11)]


def test_view_cues_are_never_spoken_and_close_with_their_sentence():
    clean, cues = strip_cues("この先の角を{view}右に曲がります。郵便局が目印です。{/view}次へ。")
    assert clean == "この先の角を右に曲がります。郵便局が目印です。次へ。"
    assert [(c.tag, c.char_index) for c in cues] == [("view1", 6), ("viewend1", 23)]
    _, cues = strip_cues("角を{view}右へ。次は{view}左へ")
    assert {c.tag: c.char_index for c in cues} == {"view1": 2, "viewend1": 5, "view2": 7, "viewend2": 9}
    assert clean_text("{view}右へ{/view}") == "右へ"


def test_cue_spans_are_kept_in_range_and_never_overlap():
    spans = view_cue_spans({"view1": 2.0, "viewend1": 2.3, "view2": 5.0, "viewend2": 30.0, "view3": 9.0}, piece=1)
    assert spans == [(1, 2.0, 3.2), (1, 5.0, 9.0), (1, 9.0, 10.2)]


def test_each_street_view_goes_to_its_nearest_leg_in_walk_order(tmp_path):
    views = [
        {"id": "b", "lat": 35.0003, "lng": 135.0016, "image": "assets/image/b.jpg"},  # east leg, later
        {"id": "a", "lat": 35.0003, "lng": 135.0004, "image": "assets/image/a.jpg"},  # east leg, earlier
        {"id": "c", "lat": 35.0010, "lng": 135.0023, "image": "assets/image/c.jpg"},  # north leg
        {"id": "far", "lat": 35.02, "lng": 135.02, "image": "assets/image/far.jpg"},  # ~2 km away: dropped
        {"id": "nophoto", "lat": 35.0, "lng": 135.0, "image": ""},
    ]
    legs = street_view_landmarks(views, [EAST, NORTH], tmp_path, cues=[[(0, 1.0, 3.0)], []])
    east, north = legs
    assert [Path(c["popup_image"]).name for c in east] == ["a.jpg", "b.jpg"]
    assert [Path(c["popup_image"]).name for c in north] == ["c.jpg"]
    assert Path(east[0]["popup_image"]).is_absolute() and east[0]["passing"]
    assert (east[0]["piece"], east[0]["show_seconds"], east[0]["hide_seconds"]) == (0, 1.0, 3.0)  # 1st {view} = 1st passed
    assert "show_seconds" not in east[1]  # no cue left: pops in at its spot for the usual short time


def test_view_wait_cue_stops_the_walker_at_the_card():
    import pandas as pd

    from services.vdoprocessing.pydeckrecorder.pedestrian import _wait_view_plan

    clean, cues = strip_cues("角を{view wait}右へ曲がります。{/view}次へ。")
    assert clean == "角を右へ曲がります。次へ。"
    assert [c.tag for c in cues] == ["view1", "viewwait1", "viewend1"]
    assert view_cue_spans({"view1": 2.0, "viewwait1": 2.0, "viewend1": 5.0}, 0) == [(0, 2.0, 5.0, True)]
    assert view_cue_spans({"view1": 2.0, "viewend1": 5.0}, 0) == [(0, 2.0, 5.0)]  # plain {view}: unchanged

    df = pd.DataFrame({"lat": [lat for lat, _ in EAST], "lon": [lon for _, lon in EAST]})
    card = {"lat": EAST[4][0], "lon": EAST[4][1], "wait": True, "piece": 0, "show_seconds": 3.0, "hide_seconds": 5.0}
    km = [i * 0.1 for i in range(11)]
    plan, spots, held = _wait_view_plan(df, km, [(10, 12.0)], [card])
    assert plan == [(4, 3.0), (10, 7.0)]  # walks 3 s to the spot, waits 2 s, then the rest: the piece is still 12 s
    assert spots == [(3.0, card, 2.0)] and held == 2.0
    # The cue opens the script: the walker can't be there yet, so it walks there first and waits the rest.
    early = dict(card, show_seconds=0.2, hide_seconds=8.0)
    assert _wait_view_plan(df, km, [(10, 12.0)], [early]) == ([(4, 4.0), (10, 4.0)], [(4.0, early, 4.0)], 4.0)
    late = dict(card, show_seconds=11.0, hide_seconds=13.0)
    assert _wait_view_plan(df, km, [(10, 12.0)], [late]) == ([(10, 12.0)], [], 0.0)  # doesn't fit: a plain view
