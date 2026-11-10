import json

import pandas as pd

from services.vdoprocessing.outrocard import _route_badges
from services.vdoprocessing.route_inputs import stop_is_numbered


def test_outro_badges_number_stops_as_the_overview_pins_do():
    wps = [
        {"label": "S"},
        {"label": "a"},
        {"label": "linked, walker pauses", "isStopBy": True, "connectToRoute": True},
        {"label": "linked, no pause", "isStopBy": True, "connectToRoute": True, "pauseAtWaypoint": False},
        {"label": "closed", "inaccessible": True},
        {"label": "b"},
        {"label": "side trip", "isStopBy": True},
        {"label": "E"},
    ]
    assert [b for b, _ in _route_badges(wps)] == ["S", "1", "・", "・", "×", "4", "E"]  # a=1, paused link=2, closed=3, b=4
    assert not stop_is_numbered({"isStopBy": True, "connectToRoute": True}, course=True)
    assert not stop_is_numbered({"skipAssetGeneration": True})


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
    assert stale({"route.photos": "old"})
