"""The editor's per-waypoint "Skip in Video Export" and "Pause at Location"."""

from services.localization.overview_script import visible_waypoints
from services.vdoprocessing.route_inputs import overview_flags_hash, route_inputs_hash
from services.vdoprocessing.videopipeline.audio_step import (
    has_own_attraction_clip,
    is_passed_only,
    passed_only_reason,
)
from services.vdoprocessing.videopipeline.render_step import overview_pin_glyphs

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
