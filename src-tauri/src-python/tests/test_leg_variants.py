"""A leg's earlier render is kept, so switching a setting back restores it instead of rendering again."""

import json

from services.vdoprocessing.route2vdo import restore_leg, stash_leg

ON = {"route_inputs": "r1", "render_version": "9", "kw.leg_elevations": "aaa"}
OFF = {"route_inputs": "r1", "render_version": "9"}


def _leg(folder, parts, body):
    clip, inputs = folder / "02_waypoint_01_A.mp4", folder / "02_waypoint_01_inputs.json"
    clip.write_bytes(body * 2048)
    inputs.write_text(json.dumps({"parts": parts}), encoding="utf-8")
    return [clip, inputs]


def test_switching_back_restores_the_kept_render(tmp_path):
    out, variants = tmp_path / "route", tmp_path / "route/.variants/02_waypoint_01"
    out.mkdir()
    stash_leg(_leg(out, ON, b"h"), variants)  # heatmap render kept aside, then rendered without it
    current = _leg(out, OFF, b"p")

    assert restore_leg(variants, "02_waypoint_01_inputs.json", OFF, current, out) == []  # same inputs: nothing to swap
    restored = restore_leg(variants, "02_waypoint_01_inputs.json", ON, current, out)
    assert restored == [out / "02_waypoint_01_A.mp4"] and restored[0].read_bytes()[:1] == b"h"
    assert json.loads((out / "02_waypoint_01_inputs.json").read_text(encoding="utf-8"))["parts"] == ON
    # The plain render is now the kept one: switching off again swaps it back.
    again = restore_leg(variants, "02_waypoint_01_inputs.json", OFF, [restored[0], out / "02_waypoint_01_inputs.json"], out)
    assert again[0].read_bytes()[:1] == b"p"


def test_only_legs_with_a_stop_chain_rerender_for_its_new_fit(monkeypatch):
    from services.vdoprocessing import route2vdo

    parts = lambda kw: route2vdo._leg_fingerprint_parts([(34.0, 135.0)], "B", kw, route_inputs="r1")  # noqa: E731
    with_chain, plain = parts({"route_chain": ["A", "B"]}), parts({})
    monkeypatch.setattr(route2vdo, "LEG_CHAIN_FIT_VERSION", 99)
    assert parts({"route_chain": ["A", "B"]})["kw.route_chain"] != with_chain["kw.route_chain"]
    assert parts({}) == plain


def test_leg_clips_play_order_without_padded_copies(tmp_path, monkeypatch):
    from services.vdoprocessing import route2vdo

    monkeypatch.setattr(route2vdo, "_output_is_valid", lambda p: True)
    for name in ("L.mp4", "L_cont2.mp4", "L_cont10.mp4", "L_cont3.mp4", "L_cont2_padded.mp4"):
        (tmp_path / name).write_bytes(b"x")
    assert [p.name for p in route2vdo.leg_clips(tmp_path)] == ["L.mp4", "L_cont2.mp4", "L_cont3.mp4", "L_cont10.mp4"]
