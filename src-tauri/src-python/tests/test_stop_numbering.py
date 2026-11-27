import json

import numpy as np
import pandas as pd
import pytest
from PIL import Image, ImageDraw

from services.mapfetcher.graphicengine import GraphicsEngine
from services.mapfetcher.mapfetcher import _stopby_marker
from services.vdoprocessing import outrocard
from services.vdoprocessing.outrocard import _draw_leg_ends, _polaroid, _route_badges
from services.vdoprocessing.pydeckrecorder.pedestrian import _pin_stop_number
from services.vdoprocessing.route_inputs import is_stopby_label, stop_is_numbered, stopby_labels
from services.vdoprocessing.spatial_renderer.pins import _PinMixin
from services.vdoprocessing.videopipeline.leg_sequence import _waypoint_popup, inject_waypoint_popups
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
    assert [b for b, _ in _route_badges(wps)] == ["S", "1", "+1", "+2", "×", "3", "E"]  # a=1, closed=2, b=3
    assert not stop_is_numbered(wps, 2)  # a stop-by, connected to the route
    assert not stop_is_numbered([{}, {"skipAssetGeneration": True}, {}], 1)
    # The unconnected side trip is off the outro's list but still the third stop-by of the route.
    assert stopby_labels(wps) == {2: "+1", 3: "+2", 6: "+3"}
    assert overview_pin_glyphs(wps)[6] == "+3"


def test_stop_by_numbers_count_the_whole_route_in_visit_order():
    wps = [{}, *({"isStopBy": True} for _ in range(12)), {}]
    assert stopby_labels(wps)[1] == "+1" and stopby_labels(wps)[12] == "+12"
    assert [b for b, _ in _route_badges([{**w, "connectToRoute": True} for w in wps])][-2] == "+12"


def test_closed_places_and_the_ends_take_no_stop_by_number():
    wps = [{"isStopBy": True}, {"isStopBy": True, "inaccessible": True}, {"skipAssetGeneration": True}, {"isStopBy": True}]
    assert stopby_labels(wps) == {2: "+1"}


def test_a_return_to_a_stop_by_shows_the_same_number():
    wps = [
        {"lat": 35.0, "lng": 139.0},
        {"lat": 35.1, "lng": 139.1, "skipAssetGeneration": True},
        {"lat": 35.2, "lng": 139.2, "isStopBy": True},
        {"lat": 35.1, "lng": 139.1},
        {"lat": 35.4, "lng": 139.4},
    ]
    assert stopby_labels(wps) == {1: "+1", 2: "+2", 3: "+1"}
    assert [overview_pin_glyphs(wps)[i] for i in (1, 3)] == ["+1", "+1"]


def test_only_a_stop_by_glyph_reads_as_a_stop_by():
    assert all(is_stopby_label(g) for g in ("+1", "+12", "・"))
    assert not any(is_stopby_label(g) for g in ("S", "E", "×", "3", "", None))
    # int("+2") is 2: a stop-by pin must not read as the leg's stop number.
    assert _pin_stop_number({"glyph": "+2"}, 9) is None
    assert [_pin_stop_number({"glyph": g}, 9) for g in ("S", "3", "E")] == [1, 3, 9]


def test_the_overview_pins_and_popups_carry_the_stop_by_number():
    popup = _waypoint_popup({"isStopBy": True, "_stopby_label": "+4"}, 2, 5, None, None)
    assert popup["stopby_label"] == "+4"
    assert _stopby_marker({"_stopby_label": "+4"}, 0)["stopby_label"] == "+4"
    pins = type("P", (_PinMixin,), {"_STOPBY_PIN_COLOR": (0, 0, 0)})()
    assert pins._pin_label_and_color({"index": 2, "data": popup}, 9)[0] == "+4"


def test_the_overview_counts_stop_bys_as_the_legs_do_with_a_separate_start():
    wps = [{"label": "x", "lat": 35.1, "lng": 139.1, "isStopBy": True}, {"label": "a", "lat": 35.2, "lng": 139.2},
           {"label": "y", "lat": 35.3, "lng": 139.3, "isStopBy": True}, {"label": "b", "lat": 35.4, "lng": 139.4}]
    popups = [None] * 10
    inject_waypoint_popups(
        audio_durations=[], marker_base_dir=".", project_config={"start_point": {"lat": 35.0, "lng": 139.0}},
        route_labels=[None] * 10, route_popups=popups, settings={}, subtitle_lang="en", waypoints=wps,
        wp_indices=[2, 4, 6, 9],
    )
    assert [popups[i].get("stopby_label") for i in (2, 4, 6, 9)] == ["+1", None, "+2", None]
    assert [wp["_stopby_label"] for wp in wps] == ["+1", None, "+2", None]


def test_a_two_digit_stop_by_fits_inside_its_pin():
    engine = GraphicsEngine()
    for radius in (14, 26, 44):
        frame = np.zeros((200, 200, 3), np.uint8)
        engine._draw_pin_label(frame, 100, 100, radius, "+12", (0, 0, 255))
        ys, xs = np.nonzero((frame[:, :, 2] > 128) & (frame[:, :, 1] < 128))  # the red text on the white centre
        assert len(xs) and np.hypot(xs - 100, ys - 100).max() <= int(radius * 0.65)


@pytest.fixture
def drawn(monkeypatch):
    """Every PIL circle and text drawn, in order: ("circle", box) or (the text, its box)."""
    calls = []
    text, ellipse = ImageDraw.ImageDraw.text, ImageDraw.ImageDraw.ellipse
    monkeypatch.setattr(ImageDraw.ImageDraw, "ellipse",
                        lambda self, xy, *a, **k: (calls.append(("circle", xy)), ellipse(self, xy, *a, **k))[1])
    monkeypatch.setattr(ImageDraw.ImageDraw, "text", lambda self, xy, s, *a, **k: (
        calls.append((s, self.textbbox(xy, s, font=k["font"], anchor=k.get("anchor")))),
        text(self, xy, s, *a, **k))[1])
    return calls


def _assert_inside_its_circle(calls, label):
    at = next(i for i, (kind, _) in enumerate(calls) if kind == label)
    left, top, right, bottom = calls[at][1]
    cx0, cy0, cx1, cy1 = next(box for kind, box in reversed(calls[:at]) if kind == "circle")
    assert cx0 <= left and right <= cx1 and cy0 <= top and bottom <= cy1


@pytest.mark.parametrize("scale", [0.6, 1.0])
def test_a_two_digit_stop_by_fits_inside_its_badge(drawn, scale):
    engine = GraphicsEngine()
    bw, bh = engine.beside_card_footprint(is_pill_badge=True, pill_name_chars=3, pill_scale=scale)
    engine._render_pill_badge(np.zeros((600, 600, 3), np.uint8),
                              {"badge_label": "+12", "label": "場所", "pill_scale": scale}, None, 100, 100, bw, bh)
    _assert_inside_its_circle(drawn, "+12")


def test_a_two_digit_stop_by_fits_the_outro_and_leg_card_circles(drawn, tmp_path):
    photo = tmp_path / "p.png"
    Image.new("RGB", (80, 60), (10, 20, 30)).save(photo)
    for card_w in (200, 420):
        drawn.clear()
        _polaroid(str(photo), "+12", "場所", card_w)
        _assert_inside_its_circle(drawn, "+12")
    drawn.clear()
    _draw_leg_ends(ImageDraw.Draw(Image.new("RGB", (768, 432))), (("+12", "a"), ("+3", "b")), 768, 1.0, (0, 0, 0))
    _assert_inside_its_circle(drawn, "+12")


def test_the_outro_route_page_numbers_a_stop_by_as_its_pin_does(monkeypatch):
    wps = [{"lat": 35.0, "lng": 139.0}, {"lat": 35.1, "lng": 139.1, "isStopBy": True, "connectToRoute": True},
           {"lat": 35.2, "lng": 139.2, "isStopBy": True}, {"lat": 35.3, "lng": 139.3}]
    numbers = []
    monkeypatch.setattr(outrocard, "_draw_stopby_card", lambda *a: numbers.append(a[-2]))
    # Only the unconnected stop-by has a card here, but it is the route's second stop-by.
    outrocard._draw_extra_rows(None, None, wps, [("stopbys", [("y", [35.2, 139.2], "")])], [0], 0, 10, 0, int,
                               None, None)
    assert numbers == ["+2"]


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
    assert stale({"route.photos": "old"})


def test_the_leg_hud_does_not_count_return_stops():
    """S -> A -> B -> back to A -> E: the counter reads 2, 3, 3, 4 of 4."""
    from services.vdoprocessing.videopipeline.leg_sequence import _Leg, _Pins, _leg_pin_fields, _place_numbers

    wps = [{"id": n, "label": n, "lat": 0.0, "lng": float(i)} for i, n in enumerate("SAB")]
    wps += [{"id": "A2", "label": "A", "lat": 0.0, "lng": 1.0}, {"id": "S2", "label": "S", "lat": 0.0, "lng": 0.0}]
    pins = _Pins({}, ["S", "1", "2", "1", "E"], {}, {}, {}, [])
    nums = _place_numbers([{}] * 4, wps, {})
    got = [
        _leg_pin_fields(_Leg({}, k, 0, 1, k, k + 1, None, "walking"), wps, {}, pins, 4, nums)
        for k in range(4)
    ]
    assert [(f["stop_number"], f["total_stops"]) for f in got] == [(2, 4), (3, 4), (3, 4), (4, 4)]
