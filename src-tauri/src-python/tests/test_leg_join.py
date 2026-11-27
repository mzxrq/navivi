import json
from types import SimpleNamespace

import pytest

from services.vdoprocessing.pydeckrecorder import pedestrian
from services.vdoprocessing.pydeckrecorder.leg_camera import _recenter_view_for_target_px
from services.vdoprocessing.pydeckrecorder.pedestrian import _joined_zoom, _opening_marker_px, _piece_glide
from services.vdoprocessing.route2vdo import (
    RouteAnimator, _leg_fingerprint_parts, _LegReuse, _legs_join, leg_changed_parts,
)


@pytest.mark.parametrize("fit, prev, expected", [
    (16.0, 16.0, 16.0),  # same size
    (16.0, 15.0, 15.0),  # exactly one level smaller: still a pure slide
    (16.0, 15.5, 15.5),
    (16.0, 14.9, 16.0),  # too small: zoom in
    (14.0, 16.0, 14.0),  # does not fit: zoom out
])
def test_joined_zoom(fit, prev, expected):
    assert _joined_zoom(fit, prev) == expected


A = {"lats": [34.000, 34.001], "lons": [135.0, 135.0]}
B = {"lats": [34.001, 34.002], "lons": [135.0, 135.0]}
FAR = {"lats": [34.010, 34.011], "lons": [135.0, 135.0]}
VIEW = {"lon": 135.0, "lat": 34.001, "zoom": 16.0, "pitch": 0.0}


def test_legs_join():
    assert _legs_join(A, B)
    assert not _legs_join(A, FAR)
    assert not _legs_join(A, {**B, "mode": "airplane"})
    assert not _legs_join({**A, "mode": "airplane"}, B)
    assert not _legs_join(A, {})
    assert not _legs_join({"lats": None, "lons": None}, B)


def _joins(tmp_path, i, seq, config=None, prev_view=None):
    kwargs = {}
    animator = SimpleNamespace(config=config or {}, out_dir=tmp_path)
    photos = SimpleNamespace(dest_quiet=False, dest_image="d.jpg", start_image="s.jpg")
    RouteAnimator._add_leg_joins(animator, kwargs, SimpleNamespace(wp_by_id={}), i, seq[i], seq,
                                 photos, prev_view, "02_waypoint_02_")
    return kwargs


def _view_file(tmp_path):
    path = tmp_path / "02_waypoint_01_endview.json"
    path.write_text(json.dumps(VIEW), encoding="utf-8")
    return str(path)


def test_narrated_stop_joins_both_sides(tmp_path):
    seq = [A, B, {"lats": [34.002, 34.003], "lons": [135.0, 135.0]}]
    kwargs = _joins(tmp_path, 1, seq, prev_view=_view_file(tmp_path))
    assert kwargs["opening_view"] == VIEW
    assert kwargs["prior_trail"] == [[34.000, 135.0], [34.001, 135.0]]
    assert kwargs["end_view_path"].endswith("02_waypoint_02_endview.json")
    assert "opening_photo" not in kwargs and "hold_end_card" not in kwargs
    assert "prior_pin" not in kwargs  # the leg before has no pin of its own to keep


def test_the_pin_of_the_leg_before_comes_along_with_its_line(tmp_path):
    pin = {"glyph": "5", "color": [200, 100, 0]}
    kwargs = _joins(tmp_path, 1, [{**A, "start_pin": pin, "labels": ["Fort", "Deck"]}, B],
                    prev_view=_view_file(tmp_path))
    assert kwargs["prior_pin"] == pin and kwargs["prior_label"] == "Fort"
    for added in ({"prior_pin": pin}, {"prior_label": "Fort"}):
        old, new = (_leg_fingerprint_parts([], "d", kw, route_inputs="r")
                    for kw in ({"opening_view": VIEW}, {"opening_view": VIEW, **added}))
        assert leg_changed_parts(new, old) == ["join"]


def test_the_leg_storyboard_turns_off_what_comes_along(tmp_path, monkeypatch):
    from services.vdoprocessing import route2vdo, storyboard

    assert storyboard.leg() == storyboard.LegBoard("leg", True, True, True)  # the shipped file
    monkeypatch.setattr(route2vdo, "leg_board", lambda: storyboard.LegBoard("leg", False, False, False))
    prev = {**A, "start_pin": {"glyph": "5", "color": [0, 0, 0]}, "labels": ["Fort", "Deck"]}
    kwargs = _joins(tmp_path, 1, [prev, B], prev_view=_view_file(tmp_path))
    assert kwargs["prior_line"] is False and "prior_trail" in kwargs  # still slides
    assert "prior_pin" not in kwargs and "prior_label" not in kwargs
    old, new = (_leg_fingerprint_parts([], "d", kw, route_inputs="r")
                for kw in ({"opening_view": VIEW}, {"opening_view": VIEW, "prior_line": False}))
    assert leg_changed_parts(new, old) == ["join"]


def test_first_and_last_leg(tmp_path):
    assert "opening_view" not in _joins(tmp_path, 0, [A, B])
    assert "end_view_path" not in _joins(tmp_path, 1, [A, B], prev_view=_view_file(tmp_path))


def test_unjoined_leg_opens_as_before(tmp_path):
    broken = tmp_path / "bad.json"
    broken.write_text("{", encoding="utf-8")
    for prev_view in (None, str(tmp_path / "missing.json"), str(broken)):
        kwargs = _joins(tmp_path, 1, [A, B], prev_view=prev_view)
        assert "opening_view" not in kwargs and "prior_trail" not in kwargs
    kwargs = _joins(tmp_path, 1, [A, FAR], prev_view=_view_file(tmp_path))
    assert "opening_view" not in kwargs and "prior_trail" not in kwargs


def test_zoom_setting_turns_sliding_off(tmp_path):
    old = tmp_path / "02_waypoint_02_endview.json"
    old.write_text("{}", encoding="utf-8")
    assert _joins(tmp_path, 0, [A, B], config={"quiet_stop_transition": "zoom"}) == {}
    assert old.exists()  # still there to be stashed with the clip it belongs to


@pytest.mark.parametrize("before, after", [
    ({}, {"end_view_path": "v.json"}),
    ({"opening_view": VIEW}, {}),
    ({"opening_view": VIEW}, {"opening_view": {**VIEW, "zoom": 15.0}}),  # the leg before ends elsewhere now
])
def test_changed_join_renders_the_leg_again(before, after):
    old, new = (_leg_fingerprint_parts([(34.0, 135.0), (34.001, 135.0)], "d", kw, route_inputs="r")
                for kw in (before, after))
    assert leg_changed_parts(new, old) == ["join"]
    assert leg_changed_parts(new, new) == []


def test_unjoined_render_removes_the_old_view(tmp_path, monkeypatch):
    clip = tmp_path / "02_waypoint_02_b.mp4"
    monkeypatch.setattr(pedestrian, "render_residential_leg_pydeck", lambda *a, **k: [str(clip)])
    old = tmp_path / "02_waypoint_02_endview.json"
    old.write_text("{}", encoding="utf-8")
    animator = SimpleNamespace(
        out_dir=tmp_path, _reusable_leg_files=lambda *a: _LegReuse([], [], [], {}),
        _leg_hud_card_png=lambda *a, **k: None, _mapbox_token=lambda: "", _write_piece_plan=lambda *a: None,
    )
    plan = SimpleNamespace(kwargs={"mode": "walking"}, num=2, prefix="02_waypoint_02_", output_path=str(clip),
                           themed=None)
    RouteAnimator._run_leg(animator, SimpleNamespace(leg_totals=[(1.0, 1.0)]), 0, plan, {}, [(34.0, 135.0)], "d")
    assert not old.exists()


def test_opening_card_points_at_the_start_pin_of_a_joined_leg():
    size, target = (1920, 1080), (960.0, 669.6)  # where the leg before left its destination pin
    lon, lat = _recenter_view_for_target_px(135.0, 34.001, target, 135.0, 34.0, 16.0, size)
    view = {"lon": lon, "lat": lat, "zoom": 16.0, "pitch": 0.0}
    assert _opening_marker_px((135.0, 34.001), view, size) == pytest.approx(target, abs=2)
    assert _opening_marker_px((135.0, 34.001), None, size) is None  # unjoined: the frame's centre, as before


def test_slide_join_cuts_between_clips(tmp_path):
    marker = tmp_path / "02_waypoint_02_nofade"
    _joins(tmp_path, 0, [A, B])
    assert marker.exists()  # same frame on both sides: a dissolve would also ghost a split leg's own pieces
    _joins(tmp_path, 0, [A, B], config={"quiet_stop_transition": "zoom"})
    assert not marker.exists()


def test_return_stops_join_as_before(tmp_path):
    out, back = {**A, "dest_is_return": True}, {**B, "start_is_return": True}
    assert "end_view_path" in _joins(tmp_path, 0, [out, back])
    assert not (tmp_path / "02_waypoint_02_nofade").exists()  # the dissolve that swaps the route lines
    kwargs = _joins(tmp_path, 1, [out, back], prev_view=_view_file(tmp_path))
    assert kwargs["opening_view"] == VIEW and "prior_trail" not in kwargs
    assert "end_view_path" not in _joins(tmp_path, 0, [A, back])
    assert "prior_trail" not in _joins(tmp_path, 1, [A, back], prev_view=_view_file(tmp_path))


def test_piece_glide_keeps_the_zoom_when_the_next_stretch_suits_it():
    views = _piece_glide((135.0, 34.0, 16.0), (135.01, 34.01, 16.4), 30)
    assert all(v[2] == 16.0 for v in views)  # no extra zoom-out on the way
    assert views[-1][:2] == pytest.approx((135.01, 34.01))


def test_piece_glide_zooms_out_only_as_far_as_the_next_stretch_needs():
    zooms = [v[2] for v in _piece_glide((135.0, 34.0, 17.0), (135.1, 34.1, 13.0), 30)]  # a ferry crossing
    assert zooms == sorted(zooms, reverse=True)
    assert min(zooms) == zooms[-1] == pytest.approx(13.0)


@pytest.mark.parametrize("stopby", [
    {"connect_to_route": True},
    {"walk_seconds": 4.0},  # walked past without being connected: it cuts the leg too
])
def test_legs_cut_at_a_stop_by_carry_the_piece_glide_key(stopby):
    kwargs = {"landmarks": [{"label": "Gate", "popup_image": "a.jpg", **stopby}]}
    assert "stopby_reopen" in _leg_fingerprint_parts([], "X", kwargs, "r")


def test_the_line_of_the_leg_before_fades_away_as_the_camera_settles():
    from services.vdoprocessing.pydeckrecorder.pedestrian import _prior_trail_opacity

    shown = [_prior_trail_opacity(i, 30) for i in range(30)]

    assert shown[:15] == [1.0] * 15  # whole while the camera sets off: the join reads as one walk
    assert shown == sorted(shown, reverse=True) and 0.0 < shown[22] < 1.0
    assert shown[-1] == 0.0  # gone before the walk starts
    assert _prior_trail_opacity(0, 1) == 0.0
