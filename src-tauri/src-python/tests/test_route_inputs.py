from services.vdoprocessing.route_inputs import route_inputs_hash

WPS = [
    {"lat": 34.1, "lng": 135.1, "routeMode": "walking", "narration": "a", "popup_image": ["x.jpg"]},
    {"lat": 34.2, "lng": 135.2, "routeMode": "draw", "customRoute": [[34.15, 135.15]]},
]


def test_ignores_non_route_edits():
    edited = [dict(WPS[0], narration="b", popup_image=["y.jpg"], label="new"), WPS[1]]
    assert route_inputs_hash(edited) == route_inputs_hash(WPS)


def test_route_edits_change_it():
    base = route_inputs_hash(WPS)
    assert route_inputs_hash([dict(WPS[0], lat=34.11), WPS[1]]) != base
    assert route_inputs_hash([dict(WPS[0], routeMode="driving"), WPS[1]]) != base
    assert route_inputs_hash([WPS[0], dict(WPS[1], customRoute=[[34.16, 135.15]])]) != base
