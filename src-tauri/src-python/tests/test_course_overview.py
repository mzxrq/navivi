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
        assert anchors == [(2.0, 0.0), (10.0, 100.0), (20.0, 300.0), (30.0, 400.0)]
        assert distance_at(anchors, 0.0) == 0.0
        assert distance_at(anchors, 10.0) == 100.0
        assert distance_at(anchors, 99.0) == 400.0
        samples = [distance_at(anchors, t / 10) for t in range(0, 320)]
        assert samples == sorted(samples)  # never goes back

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
