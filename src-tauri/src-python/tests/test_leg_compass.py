from services.vdoprocessing.pydeckrecorder.pedestrian import _heading_label, _walk_headings


def _near(a, b, tol=2.0):
    return abs((a - b + 180.0) % 360.0 - 180.0) < tol


def test_straight_lines():
    lats = [35.0 + i * 0.0001 for i in range(20)]
    assert all(_near(h, 0.0) for h in _walk_headings([135.0] * 20, lats, 20.0))
    lons = [135.0 + i * 0.0001 for i in range(20)]
    assert all(_near(h, 90.0) for h in _walk_headings(lons, [35.0] * 20, 20.0))
    lats_s = list(reversed(lats))
    assert all(_near(h, 180.0) for h in _walk_headings([135.0] * 20, lats_s, 20.0))


def test_turn_and_standstill():
    # East 300 m, then north 300 m, then stand still at the end.
    lons = [135.0 + i * 0.0003 for i in range(10)] + [135.0027] * 10 + [135.0027] * 5
    lats = [35.0] * 10 + [35.0 + i * 0.0003 for i in range(1, 11)] + [35.003] * 5
    h = _walk_headings(lons, lats, 20.0)
    assert _near(h[2], 90.0)
    assert _near(h[15], 0.0)
    assert _near(h[-1], 0.0)


def test_degenerate():
    assert _walk_headings([], [], 20.0) == []
    assert _walk_headings([135.0] * 3, [35.0] * 3, 20.0) == [0.0, 0.0, 0.0]


def test_heading_label():
    assert _heading_label(0.2) == "N 0°"
    assert _heading_label(47.3) == "NE 47°"
    assert _heading_label(180.0) == "S 180°"
    assert _heading_label(289.6) == "W 290°"
    assert _heading_label(300.0) == "NW 300°"
    assert _heading_label(359.7) == "N 0°"
