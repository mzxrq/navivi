"""The editor's per-waypoint "Skip in Video Export" and "Pause at Location"."""

from services.localization.overview_script import visible_waypoints
from services.vdoprocessing.route_inputs import overview_flags_hash, route_inputs_hash
from services.vdoprocessing.videopipeline.audio_step import (
    has_own_attraction_clip,
    is_passed_only,
    passed_only_reason,
)
from services.vdoprocessing.videopipeline.render_look import overview_pin_glyphs

WP = {"lat": 34.1, "lng": 135.1, "attractionNarration": "x", "popup_image": ["1.jpg"]}


def test_skipped_gets_no_tts_or_attraction():
    skipped = dict(WP, skipAssetGeneration=True)
    assert is_passed_only(skipped) and not has_own_attraction_clip(skipped)
    assert passed_only_reason(skipped) == "skipped in video export"
    assert not is_passed_only(WP) and has_own_attraction_clip(WP)


def test_skipped_is_an_unnumbered_dot():
    wps = [dict(WP), dict(WP, skipAssetGeneration=True), dict(WP), dict(WP)]
    assert overview_pin_glyphs(wps)[1] == "・"
    assert visible_waypoints({"waypoints": wps}) == [wps[2]]


def test_skip_changes_the_route_but_pause_only_the_overview():
    wps = [WP, dict(WP, lat=34.2)]
    assert route_inputs_hash([WP, dict(wps[1], skipAssetGeneration=True)]) != route_inputs_hash(wps)
    paused_off = [WP, dict(wps[1], pauseAtWaypoint=False)]
    assert route_inputs_hash(paused_off) == route_inputs_hash(wps)
    assert overview_flags_hash(paused_off) != overview_flags_hash(wps)
    # unset means paused (the editor's default)
    assert overview_flags_hash([dict(w, pauseAtWaypoint=True) for w in wps]) == overview_flags_hash(wps)


def test_a_return_stop_gets_no_attraction_clip():
    from services.vdoprocessing.videopipeline.timeline_step import _unvisited_stopbys

    a = {"lat": 34.0, "lng": 135.0}
    wps = [{"lat": 33.0, "lng": 135.0}, a, dict(a, isStopBy=True, connectToRoute=True), dict(a, label="A (Return)"), dict(a, label="A again, the finish")]
    assert _unvisited_stopbys(wps) == {3}  # the stop-by beside A keeps its clip



def test_a_closed_place_keeps_its_attraction_video_but_is_never_walked_to():
    from services.vdoprocessing.videopipeline.audio_step import no_attraction
    from services.vdoprocessing.videopipeline.timeline_step import _unvisited_stopbys

    stopby = dict(WP, isStopBy=True, connectToRoute=False)
    closed = dict(stopby, inaccessible=True)
    assert is_passed_only(closed) and not no_attraction(closed) and has_own_attraction_clip(closed)
    assert no_attraction(stopby) and no_attraction(dict(closed, skipAssetGeneration=True))
    wps = [dict(WP), closed, dict(WP, lat=34.3), dict(WP, lat=34.5)]
    assert _unvisited_stopbys(wps) == set()


def test_a_leg_with_a_deleted_piece_is_rendered_again():
    from pathlib import Path

    from services.vdoprocessing.route2vdo import pieces_complete

    leg = [Path("02_waypoint_16_X.mp4")] + [Path(f"02_waypoint_16_X_cont{n}.mp4") for n in range(2, 6)]
    assert pieces_complete(leg) and pieces_complete(leg[:1])
    assert not pieces_complete(leg[1:]) and not pieces_complete(leg[:2] + leg[3:])


def test_the_arrived_map_hold_only_plays_when_there_is_no_arrival_photo():
    # A block put between `if dest_popup_image:` and its `else:` once moved the hold after the fullscreen photo.
    import inspect

    from services.vdoprocessing.pydeckrecorder import pedestrian

    src = inspect.getsource(pedestrian)
    between = src[src.index("cut_on_arrival = await _play_leg_photo_card("):src.index("hold_frames = max(0, int(")]
    assert between.rstrip().endswith("else:") and "\n                    if " not in between


def test_turning_a_stop_by_into_a_closed_place_changes_the_route_inputs():
    from services.vdoprocessing.route_inputs import route_inputs_hash

    stopby = {"lat": 34.0, "lng": 135.0, "isStopBy": True, "connectToRoute": False}
    assert route_inputs_hash([stopby]) != route_inputs_hash([{**stopby, "inaccessible": True}])
    assert route_inputs_hash([stopby]) == route_inputs_hash([{**stopby, "inaccessible": False}])  # old projects keep theirs


def test_a_leg_passing_a_place_turned_closed_is_rendered_again():
    from services.vdoprocessing.route2vdo import _leg_fingerprint_parts, leg_changed_parts

    lm = {"lat": 34.0, "lon": 135.0, "label": "経塚"}
    old = _leg_fingerprint_parts([(34.0, 135.0)], "B", {"landmarks": [lm]}, route_inputs="r")
    new = _leg_fingerprint_parts([(34.0, 135.0)], "B", {"landmarks": [{**lm, "inaccessible": True}]}, route_inputs="r")
    assert "closed" in leg_changed_parts(new, old)


def test_a_stop_by_now_walked_to_renders_its_leg_again():
    from services.vdoprocessing.route2vdo import _leg_fingerprint_parts, leg_changed_parts

    lm = {"lat": 34.0, "lon": 135.0, "label": "神社"}
    old = _leg_fingerprint_parts([(34.0, 135.0)], "B", {"landmarks": [{**lm, "pops_after": ""}]}, route_inputs="r")
    new = _leg_fingerprint_parts([(34.0, 135.0)], "B", {"landmarks": [{**lm, "walk_seconds": 5.0}]}, route_inputs="r")
    assert "pops_after" in leg_changed_parts(new, old)


def test_an_end_point_on_the_last_stop_gets_no_extra_leg():
    from services.vdoprocessing.videopipeline.leg_sequence import _same_spot

    last = {"label": "玉手駅", "lat": 34.45832512, "lng": 135.74841593}
    assert _same_spot({"lat": 34.45832512, "lng": 135.74841593, "label": "玉手駅"}, last)
    assert not _same_spot({"lat": 34.47, "lng": 135.76}, last)
    assert not _same_spot({"lat": 34.45, "lng": 135.74}, None)
