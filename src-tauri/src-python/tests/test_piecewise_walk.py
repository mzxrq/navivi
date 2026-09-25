"""Per-piece walk timing for a leg cut at connected stop-bys, and the attraction rules."""

import pandas as pd
import pytest

from services.vdoprocessing.pydeckrecorder.pedestrian import _segment_plan
from services.vdoprocessing.pydeckrecorder.routedata import interpolate_route_data
from services.vdoprocessing.videopipeline.attraction_step import is_unvisited_stopby


def _line(n=11):
    # a straight west-to-east path, 1 point per 0.001 deg
    df = pd.DataFrame({"lon": [135.0 + i * 0.001 for i in range(n)], "lat": [34.0] * n})
    dist = [i * 0.09 for i in range(n)]  # km, evenly spaced
    return df, dist


def _time_at(smooth, lon):
    row = (smooth["lon"] - lon).abs().idxmin()
    return row


def test_each_segment_takes_its_own_time():
    df, dist = _line()
    # stop-by at point 5 reached after 4s, then the last 5 points take 16s.
    smooth = interpolate_route_data(df, 20.0, 200, dist[-1], dist, segment_plan=[(5, 4.0), (10, 16.0)])
    assert len(smooth) == 200
    # frame index / 200 * 20s = time; the stop-by longitude (135.005) is hit at ~4s
    t_stop = _time_at(smooth, 135.005) / 200 * 20.0
    assert t_stop == pytest.approx(4.0, abs=0.3)


def test_no_plan_is_constant_speed():
    df, dist = _line()
    smooth = interpolate_route_data(df, 20.0, 200, dist[-1], dist)
    assert _time_at(smooth, 135.005) / 200 * 20.0 == pytest.approx(10.0, abs=0.3)


def test_segment_plan_from_landmarks():
    df, _ = _line()
    df = df.rename(columns={})
    lm = [{"connect_to_route": True, "popup_image": "x.jpg", "lat": 34.0, "lon": 135.005, "walk_seconds": 4.0}]
    plan = _segment_plan(df, [], lm, 20.0)
    assert plan == [(5, 4.0), (10, 16.0)]


def test_segment_plan_is_none_when_it_cannot_be_planned():
    df, _ = _line()
    assert _segment_plan(df, [], [], 20.0) is None
    no_time = [{"connect_to_route": True, "popup_image": "x.jpg", "lat": 34.0, "lon": 135.005}]
    assert _segment_plan(df, [], no_time, 20.0) is None
    unconnected = [{"connect_to_route": False, "popup_image": "x.jpg", "lat": 34.0, "lon": 135.005, "walk_seconds": 4}]
    assert _segment_plan(df, [], unconnected, 20.0) is None


def test_only_unconnected_stopbys_have_no_attraction_video():
    assert is_unvisited_stopby({"isStopBy": True})
    assert not is_unvisited_stopby({"isStopBy": True, "connectToRoute": True})
    assert not is_unvisited_stopby({"isStopBy": False})
    assert not is_unvisited_stopby({})
