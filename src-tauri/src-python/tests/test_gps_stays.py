import numpy as np

from services.gpsparser.stays import detect_stays

DEG_M = 111_320.0


def _track(segments):
    lat, lon, t = [], [], []
    now = 0.0
    for points, step in segments:
        for la, lo in points:
            lat.append(la)
            lon.append(lo)
            t.append(now)
            now += step
    t = np.array(t)
    return np.array(lat), np.array(lon), t, t.copy()


def _walk(start, n, d_lat=10 / DEG_M, d_lon=0.0):
    return [(start[0] + i * d_lat, start[1] + i * d_lon) for i in range(n)]


def test_jittery_stay_is_found_at_its_centre():
    rng = np.random.default_rng(0)
    centre = (35.0 + 60 * 10 / DEG_M, 135.0)
    jitter = [(centre[0] + rng.uniform(-15, 15) / DEG_M, centre[1] + rng.uniform(-15, 15) / DEG_M) for _ in range(100)]
    lat, lon, start, end = _track([(_walk((35.0, 135.0), 60), 5), (jitter, 6), (_walk(centre, 60, 0, 10 / DEG_M), 5)])

    stays = detect_stays(lat, lon, start, end, radius_m=50, min_stay_sec=300)

    assert len(stays) == 1
    assert abs(stays[0]["lat"] - centre[0]) * DEG_M < 10
    assert 600 <= stays[0]["end_sec"] - stays[0]["start_sec"] <= 700


def test_moving_track_has_no_stays():
    lat, lon, start, end = _track([(_walk((35.0, 135.0), 300), 5)])
    assert detect_stays(lat, lon, start, end) == []


def test_dwell_on_one_point_counts():
    lat, lon, start, _ = _track([(_walk((35.0, 135.0), 3), 5)])
    end = start.copy()
    end[1] += 900  # the logger sat on point 1 for 15 minutes and logged it once
    stays = detect_stays(lat, lon, start, end, radius_m=50, min_stay_sec=300)
    assert len(stays) == 1 and stays[0]["end_sec"] - stays[0]["start_sec"] >= 900


def test_short_wander_between_two_halves_of_a_stay_merges():
    spot = (35.0, 135.0)
    away = (35.0 + 120 / DEG_M, 135.0)
    lat, lon, start, end = _track([([spot] * 40, 10), ([away] * 3, 10), ([spot] * 40, 10)])
    stays = detect_stays(lat, lon, start, end, radius_m=50, min_stay_sec=300)
    assert len(stays) == 1
    assert stays[0]["end_sec"] - stays[0]["start_sec"] >= 800
