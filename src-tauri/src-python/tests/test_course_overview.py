"""The "Whole route first" (course) type: overview timing, legs, stop-bys."""

import pytest

from services import tuning
from services.localization.overview_script import course_summary, course_taglines
from services.vdoprocessing.pydeckrecorder.routedata import arrival_time_fraction
from services.vdoprocessing.spatial_renderer.course import distance_at, tagline_at, trace_anchors
from services.vdoprocessing.stopby_visits import set_visit_all_stopbys, visits_stopby


@pytest.fixture(autouse=True)
def _reset_visits():
    yield
    set_visit_all_stopbys(False)


class TestTrace:
    def test_the_trace_reaches_each_cued_stop_on_its_cue(self):
        anchors = trace_anchors([(10.0, 100.0), (None, 150.0), (20.0, 300.0)], 400.0, 2.0, 30.0, 4)
        # the last stretch goes at the pace so far (at most 4 s) and rests there until the end cue
        assert anchors == [(2.0, 0.0), (10.0, 100.0), (20.0, 300.0), (24.0, 400.0)]
        assert distance_at(anchors, 0.0) == 0.0
        assert distance_at(anchors, 10.0) == 100.0
        assert distance_at(anchors, 99.0) == 400.0
        samples = [distance_at(anchors, t / 10) for t in range(0, 320)]
        assert samples == sorted(samples)  # never goes back

    def test_a_passed_place_is_crossed_at_speed(self):
        anchors = trace_anchors([(6.0, 100.0, False), (10.0, 200.0, True)], 200.0, 2.0, None, 3)
        assert anchors[1] == (6.0, 100.0, False)
        assert distance_at(anchors, 6.0) == 100.0  # reached on its cue
        before, after = distance_at(anchors, 5.9), distance_at(anchors, 6.1)
        assert after - before > 1.0  # still moving there, not settling
        assert distance_at(anchors, 9.9) > 199.0  # but it settles on the stop

    def test_without_cues_it_runs_per_leg(self):
        anchors = trace_anchors([(None, 50.0)], 100.0, 1.5, None, 4)
        assert anchors[-1] == (1.5 + 4 * tuning.COURSE_SECONDS_PER_LEG, 100.0)

    def test_a_cue_out_of_order_is_ignored(self):
        anchors = trace_anchors([(10.0, 100.0), (9.0, 200.0)], 300.0, 2.0, 20.0, 3)
        assert [d for _, d in anchors] == [0.0, 100.0, 300.0]


def test_taglines_cycle_and_fade():
    lines = ["A", "B"]
    assert tagline_at(lines, 2.0) == ("A", 1.0)
    assert tagline_at(lines, tuning.COURSE_TAGLINE_SECONDS + 2.0)[0] == "B"
    assert tagline_at(lines, 0.0)[1] == 0.0
    assert tagline_at([], 3.0) == ("", 0.0)


def _brief():
    walk = {"mode": "walking", "km": 1.0, "minutes": 20}
    boat = {"mode": "ferry", "km": 7.0, "minutes": 20}
    return {
        "start": "加太駅",
        "legs": [
            {"from": "加太駅", "to": "加太港", "mode": "walking", "pieces": [walk], "from_at": [35.0, 139.0],
             "to_at": [35.0, 139.01], "is_return": False, "km": 1.0, "minutes": 20},
            {"from": "加太港", "to": "野奈浦桟橋", "mode": "ferry", "pieces": [boat], "from_at": [35.0, 139.01],
             "to_at": [35.0, 139.1], "is_return": False, "km": 7.0, "minutes": 20},
            {"from": "野奈浦桟橋", "to": "加太駅", "mode": "walking", "pieces": [boat, walk], "from_at": [35.0, 139.1],
             "to_at": [35.0, 139.0], "is_return": True, "km": 8.0, "minutes": 40},
        ],
    }


def test_taglines_come_from_the_route():
    lines = course_taglines({"video_title": "友ヶ島をめぐる道", "settings": {"intro_location": "和歌山県 和歌山市"}}, _brief())
    assert lines[0] == "友ヶ島をめぐる道"
    assert "海をわたり、野奈浦桟橋へ" in lines
    assert "加太駅から歩いてめぐる道" in lines
    assert lines[-1] == "和歌山県 和歌山市"
    assert "Untitled Project" not in course_taglines({"video_title": "Untitled Project"}, _brief())


def test_the_stats_card_counts_what_the_script_says():
    summary = course_summary(_brief())
    assert list(summary["mode_breakdown"]) == ["walking", "ferry"]  # walking first, as on the card
    assert summary["mode_breakdown"] == {"walking": 2.0, "ferry": 14.0}
    assert summary["total_distance_km"] == 16.0


def test_the_walker_slows_before_arriving_but_arrives_on_time():
    assert arrival_time_fraction(0.5, 20.0, 0.0) == 0.5
    assert arrival_time_fraction(1.0, 20.0, 3.0) == 1.0
    times = [arrival_time_fraction(f / 100, 20.0, 3.0) for f in range(101)]
    assert times == sorted(times)
    # the last 5% of the distance takes longer than the first 5%
    assert times[100] - times[95] > 1.5 * (times[5] - times[0])


class TestStopbyVisits:
    def test_only_connected_ones_by_default(self):
        loose = {"isStopBy": True, "popup_image": ["a.jpg"]}
        assert not visits_stopby(loose)
        assert visits_stopby({**loose, "connectToRoute": True})
        assert not visits_stopby({"label": "a stop"})

    def test_the_course_type_visits_every_stopby_with_a_photo(self):
        from services.vdoprocessing.videopipeline.audio_step import is_passed_only

        set_visit_all_stopbys(True)
        assert visits_stopby({"isStopBy": True, "popup_image": ["a.jpg"]})
        assert not is_passed_only({"isStopBy": True, "popup_image": ["a.jpg"]})
        assert is_passed_only({"isStopBy": True})  # nothing to show
        assert is_passed_only({"isStopBy": True, "popup_image": ["a.jpg"], "skipAssetGeneration": True})


def test_a_stopby_photo_stays_still_unless_a_camera_move_is_picked():
    from services.vdoprocessing.videopipeline.attraction_step import _resolve_attraction_prompt

    stopby = {"isStopBy": True, "images": ["a.jpg", "b.jpg"]}
    assert _resolve_attraction_prompt(stopby) == ["none", "none"]
    assert _resolve_attraction_prompt({**stopby, "imagePans": ["zoom-in"]}) == ["zoom-in", "none"]
    assert _resolve_attraction_prompt({"images": ["a.jpg"]}) == ["panright"]  # an ordinary stop, as before


def test_passed_places_are_reached_within_the_cue_window_and_settling_stops_exactly():
    from services import tuning

    stops = [(29.0, 3.4, False), (33.6, 5.7, False), (36.2, 5.9, False), (41.7, 7.1), (54.4, 13.6)]
    anchors = trace_anchors(stops, 14.2, 25.2, 60.7, 6)
    cues = {round(d, 1): t for t, d, *_ in [(29.0, 3.4), (33.6, 5.7), (36.2, 5.9), (41.7, 7.1), (54.4, 13.6)]}
    seen = set()
    for t, d, *rest in anchors[1:-1]:
        if round(d, 1) in seen:  # a wait there before going on (hold_before_slow_stretches)
            continue
        seen.add(round(d, 1))
        late = t - cues[round(d, 1)]
        assert -1e-9 <= late <= tuning.COURSE_CUE_WINDOW_SECONDS + 1e-9
        if round(d, 1) in (7.1, 13.6):  # stops it settles on
            assert late == 0
    times = [a[0] for a in anchors]
    assert times == sorted(times)


def test_go_stop_is_reached_when_named_then_waits():
    from services.vdoprocessing.spatial_renderer.course import distance_at, trace_anchors

    anchors = trace_anchors([(2.0, 100.0, True, 6.0)], 200.0, 0.0, 9.0, 2)
    assert distance_at(anchors, 2.0) == 100.0 and distance_at(anchors, 5.0) == 100.0
    assert distance_at(anchors, 6.5) > 100.0


def test_close_places_wait_then_walk_instead_of_crawling():
    from services.vdoprocessing.spatial_renderer.course import distance_at, hold_before_slow_stretches

    # 1000 px in 10 s on average, but the last 20 px take 5 s: wait, then go at >= half the average pace
    anchors = hold_before_slow_stretches([(0.0, 0.0), (5.0, 980.0, False), (10.0, 1000.0)], 0.5)
    assert distance_at(anchors, 9.0) == 980.0 and distance_at(anchors, 10.0) == 1000.0
    assert anchors[-2][0] >= 9.5


def test_go_then_next_name_at_once_still_stops_at_the_next_place():
    from services.vdoprocessing.spatial_renderer.course import distance_at

    # "{go}{2}": stop 1's {go} and stop 2's name at the same second (52.8); stop 2's {go} at 56.5
    anchors = trace_anchors([(49.9, 100.0, True, 52.8), (52.8, 160.0, True, 56.5)], 400.0, 40.0, 60.0, 3)
    assert distance_at(anchors, 52.8) == 100.0 and distance_at(anchors, 55.0) == 160.0
    assert distance_at(anchors, 56.5) == 160.0


def test_a_pier_passed_twice_is_matched_to_the_pass_in_route_order():
    import numpy as np
    from services.vdoprocessing.spatial_renderer.course import stop_distances

    # pier (0,0) -> loop out to (100,0) and back to the pier -> on to (0,100)
    path = np.array([[0, 0], [50, 0], [100, 0], [50, 0], [0, 0], [0, 50], [0, 100]], float)
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(path, axis=0).T))])
    pier, far, back, end = (0, 0), (100, 0), (0, 0), (0, 100)
    assert stop_distances(path, cum, [pier, far, back, end]) == [0.0, 100.0, 200.0, 300.0]


def test_a_stop_passed_twice_matches_its_first_pass():
    import pandas as pd
    from services.mapfetcher.mapgeometry import RouteGeometryProcessor

    # pier (0,0) -> island point (0.01,0) -> back to the pier, a hair closer -> mainland (0,0.01)
    df = pd.DataFrame({"latitude": [0.0, 0.005, 0.01, 0.005, 0.0, 0.0], "longitude": [0.00001, 0, 0, 0, 0.0, 0.01]})
    wps = [{"lat": 0.0, "lng": 0.0}, {"lat": 0.01, "lng": 0.0}, {"lat": 0.0, "lng": 0.0}, {"lat": 0.0, "lng": 0.01}]
    assert RouteGeometryProcessor.build_waypoint_index(df, wps) == [0, 2, 4, 5]


def test_an_off_track_stop_by_does_not_push_later_stops_ahead():
    import pandas as pd
    from services.mapfetcher.mapgeometry import RouteGeometryProcessor

    df = pd.DataFrame({"latitude": [0.0, 0.0, 0.0, 0.0, 0.0], "longitude": [0.0, 0.01, 0.02, 0.03, 0.04]})
    # a stop-by 1 km north of the track's end, listed before the stop at 0.02
    wps = [{"lat": 0.0, "lng": 0.0}, {"lat": 0.01, "lng": 0.04}, {"lat": 0.0, "lng": 0.02}, {"lat": 0.0, "lng": 0.04}]
    assert RouteGeometryProcessor.build_waypoint_index(df, wps) == [0, 1, 2, 4]


def test_a_stop_by_near_the_leg_line_is_walked_to_and_a_far_one_is_not():
    from services.vdoprocessing.videopipeline.leg_sequence import closest_leg_index, stopbys_near_the_route

    lats, lons = [35.0] * 5, [135.0, 135.001, 135.002, 135.003, 135.004]  # ~90 m apart, east-west
    wps = [
        {"lat": 35.0, "lng": 135.0},
        {"lat": 35.0003, "lng": 135.003, "isStopBy": True},  # ~33 m off the line, near point 3
        {"lat": 35.01, "lng": 135.001, "isStopBy": True},  # ~1.1 km off
        {"lat": 35.0, "lng": 135.002, "isStopBy": True, "connectToRoute": True},  # already walked to
    ]
    assert stopbys_near_the_route(wps, [1, 2, 3], lats, lons) == {1: 3}
    assert closest_leg_index(wps[2], lats, lons) == 1
