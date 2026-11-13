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
    # A {start} cue 8 s in: the walk starts there, so voice 11-13 s is walk 3-5 s, the same as `card`.
    assert _wait_view_plan(df, km, [(10, 12.0)], [late], start_cue_seconds=8.0) == ([(4, 3.0), (10, 7.0)], [(3.0, late, 2.0)], 2.0)


def test_a_placed_street_view_replaces_the_auto_turn_photo_near_it():
    from services.mapfetcher.street_photos import clear_of

    view = {"lat": 34.45, "lon": 135.73}
    near = {"lat": 34.45 + 30 / 110540, "lon": 135.73}  # 30 m away
    far = {"lat": 34.45 + 200 / 110540, "lon": 135.73}  # 200 m away
    assert clear_of([near, far], [view], 50.0) == [far]
    assert clear_of([near, far], [], 50.0) == [near, far]


def test_a_named_street_view_card_shows_its_name_an_automatic_one_does_not():
    from services.mapfetcher.street_photos import card_title

    assert card_title("高札場") == "高札場"
    assert card_title("Street view 3") == "" and card_title("ストリートビュー 1") == "" and card_title(None) == ""


def test_a_street_view_midway_along_a_long_straight_stretch_is_on_the_leg(tmp_path):
    from services.mapfetcher.street_photos import street_view_landmarks

    # Two track points 400 m apart; the view sits on the road halfway, 200 m from either point.
    leg = [[35.0, 135.0], [35.0 + 400 / 110540, 135.0]]
    sv = {"id": "v", "lat": 35.0 + 200 / 110540, "lng": 135.0, "image": "a.jpg"}
    assert len(street_view_landmarks([sv], [leg], tmp_path)[0]) == 1


def test_turn_cues_time_the_automatic_turn_photos_like_view_cues_time_street_views():
    from services.localization.cues import strip_cues
    from services.mapfetcher.street_photos import attach_cue_spans, view_cue_spans

    clean, cues = strip_cues("角を{turn wait}右へ。{/turn}道なりに{view}郵便局。{turn}次の角です。")
    tags = [c.tag for c in cues]
    assert {"turn1", "turnwait1", "turnend1", "turn2", "turnend2", "view1", "viewend1"} <= set(tags)
    assert "{" not in clean
    times = {c.tag: float(c.char_index) for c in cues}
    spans = view_cue_spans(times, 0, "turn")
    assert len(spans) == 2 and spans[0][3] is True  # {turn wait}: the walker stops at the first
    cards = attach_cue_spans([{"lat": 0, "lon": 0}, {"lat": 1, "lon": 1}, {"lat": 2, "lon": 2}], spans)
    assert cards[0]["wait"] and "show_seconds" in cards[1] and "show_seconds" not in cards[2]  # 3rd: at its spot


def test_a_named_view_cue_pops_the_street_view_with_that_name():
    from services.localization.cues import strip_cues
    from services.mapfetcher.street_photos import attach_cue_spans, view_cue_spans

    clean, cues = strip_cues("この先は{view}坂道。{view wait:白壁の町}白壁の町です。")
    assert "{" not in clean
    assert [c.tag for c in cues if "name" in c.tag] == ["viewname2:白壁の町"]

    times = {"view1": 1.0, "viewend1": 3.0, "view2": 4.0, "viewwait2": 4.0, "viewname2:白壁の町": 4.0, "viewend2": 7.0}
    spans = view_cue_spans(times, 0)
    assert spans == [(0, 1.0, 3.0), (0, 4.0, 7.0, True, "白壁の町")]
    cards = [{"label": "白壁の町並み"}, {"label": "高札場"}]  # walk order: the named one comes first
    attach_cue_spans(cards, spans)
    assert cards[0]["show_seconds"] == 4.0 and cards[0]["wait"]
    assert cards[1]["show_seconds"] == 1.0 and "wait" not in cards[1]


def test_view_wait_slow_eases_the_walker_into_the_spot_and_still_arrives_on_the_cue():
    import pandas as pd

    from services import tuning
    from services.mapfetcher.street_photos import attach_cue_spans
    from services.vdoprocessing.pydeckrecorder.pedestrian import _wait_view_plan
    from services.vdoprocessing.pydeckrecorder.routedata import interpolate_route_data

    clean, cues = strip_cues("Walk on {view wait slow:Gate}to the gate.{/view} Then on.")
    assert clean == "Walk on to the gate. Then on."
    assert [c.tag for c in cues] == ["view1", "viewwait1", "viewwaitslow1", "viewname1:Gate", "viewend1"]
    spans = view_cue_spans({"view1": 6.0, "viewwait1": 6.0, "viewwaitslow1": 6.0, "viewend1": 8.0}, 0)
    assert spans == [(0, 6.0, 8.0, "slow")]
    (card,) = attach_cue_spans([{"lat": EAST[4][0], "lon": EAST[4][1]}], spans)
    assert card["wait"] and card["wait_slow"]

    df = pd.DataFrame({"lat": [lat for lat, _ in EAST], "lon": [lon for _, lon in EAST]})
    km = [i * 0.1 for i in range(11)]
    plan, spots, held = _wait_view_plan(df, km, [(10, 12.0)], [card])
    assert plan == [(4, 6.0, tuning.VIEW_WAIT_SLOW_SECONDS), (10, 4.0)] and held == 2.0
    smooth = interpolate_route_data(df.copy(), 10.0, 101, 1.0, km, segment_plan=plan)
    # Reaches the spot (0.4 km) at 6 s either way, but covers less ground in the last second before it than an even pace.
    step = lambda t: abs(float(smooth["lon"].iloc[int(t * 10)]) - float(smooth["lon"].iloc[int(t * 10) - 10]))  # noqa: E731
    assert abs(float(smooth["lon"].iloc[60]) - EAST[4][1]) < 2e-5
    assert step(6.0) < 0.7 * step(3.0)
