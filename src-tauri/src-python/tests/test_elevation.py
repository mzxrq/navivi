

def test_profile_card_marker_follows_the_walk():
    from services.vdoprocessing.pydeckrecorder.elevation import climb, profile_card

    pts = [(34.0 + i * 1e-4, 135.0) for i in range(50)]
    ele = [10 + i * 0.8 for i in range(25)] + [30 - i * 0.6 for i in range(25)]
    svg, marker = profile_card(pts, ele, (520, 190), "Elevation", {"text": "#222", "label": "#666", "fill": "#eee"})
    assert 'id="elev-marker"' in svg and "Elevation" in svg and "km · +" in svg
    (x0, y0), (xm, ym), (x1, _) = marker(0), marker(0.5), marker(1)
    assert x0 < xm < x1 and ym < y0  # left to right, the hilltop drawn higher
    assert profile_card(pts, None, (520, 190), "E", {"text": "", "label": "", "fill": ""}) is None
    assert climb([0, 5, 3, 8]) == (10, 2)


def test_return_stop_is_a_copy_of_an_earlier_spot():
    from services.vdoprocessing.videopipeline.render_step import _is_return_stop
    wps = [{"lat": 1, "lng": 2}, {"lat": 3, "lng": 4}, {"lat": 1, "lng": 2}]
    assert _is_return_stop(wps, 2) and not _is_return_stop(wps, 1) and not _is_return_stop(wps, 0)
