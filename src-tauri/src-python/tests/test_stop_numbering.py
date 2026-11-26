import json

import pandas as pd

from services.vdoprocessing.outrocard import _route_badges
from services.vdoprocessing.route_inputs import stop_is_numbered
from services.vdoprocessing.videopipeline.render_look import overview_pin_glyphs


def test_outro_badges_number_stops_as_the_overview_pins_do():
    wps = [
        {"label": "S"},
        {"label": "a"},
        {"label": "linked to the route", "isStopBy": True, "connectToRoute": True},
        {"label": "linked, no pause", "isStopBy": True, "connectToRoute": True, "pauseAtWaypoint": False},
        {"label": "closed", "inaccessible": True},
        {"label": "b"},
        {"label": "side trip", "isStopBy": True},
        {"label": "E"},
    ]
    # The walker passes every stop-by, connected or not, so none of them takes a number.
    assert [b for b, _ in _route_badges(wps)] == ["S", "1", "・", "・", "×", "3", "E"]  # a=1, closed=2, b=3
    assert not stop_is_numbered(wps, 2)  # a stop-by, connected to the route
    assert not stop_is_numbered([{}, {"skipAssetGeneration": True}, {}], 1)


def test_a_return_stop_shows_the_number_it_comes_back_to():
    wps = [
        {"label": "S", "lat": 35.0, "lng": 139.0},
        {"label": "a", "lat": 35.1, "lng": 139.1},
        {"label": "b", "lat": 35.2, "lng": 139.2},
        {"label": "a (Return)", "lat": 35.1, "lng": 139.1},
        {"label": "c", "lat": 35.3, "lng": 139.3},
        {"label": "E", "lat": 35.4, "lng": 139.4},
    ]
    # The return to "a" shows 1 again and doesn't push "c" to 4; the glyphs the legs draw agree.
    assert [b for b, _ in _route_badges(wps)] == ["S", "1", "2", "1", "3", "E"]
    assert not stop_is_numbered(wps, 3) and stop_is_numbered(wps, 4)
    assert overview_pin_glyphs(wps) == {0: "S", 1: "1", 2: "2", 3: "1", 4: "3", 5: "E"}


def test_a_leg_only_change_keeps_the_overview(tmp_path):
    from services.vdoprocessing.videopipeline import render_checkpoint

    route = {"route": pd.DataFrame({"latitude": [35.0, 35.1], "longitude": [139.0, 139.1]}), "summary": {}}
    cfg = tmp_path / "job_config.json"
    cfg.write_text(json.dumps({"waypoints": [], "settings": {}}), encoding="utf-8")
    out = tmp_path / "02_waypoint_01_a.mp4"
    out.write_bytes(b"x" * 20000)
    parts = render_checkpoint._checkpoint_parts(str(cfg), route, [], [])
    manifest = tmp_path / ".render_manifest.json"

    def stale(changed: dict) -> bool:
        old = {**parts, **changed}
        manifest.write_text(json.dumps({"output_paths": [str(out)], "input_hash": "x", "input_parts": old}), encoding="utf-8")
        return render_checkpoint.reuse_render_manifest(manifest, "y", parts, str(cfg))[1]

    assert not stale({"route.leg_voice": "old"})
