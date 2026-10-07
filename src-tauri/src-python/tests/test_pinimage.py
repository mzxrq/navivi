"""The user's own pin picture in the video (pinimage.py and where it is wired)."""

import base64

import cv2
import numpy as np
import pytest

from services.mapfetcher.graphicengine import GraphicsEngine
from services.mapfetcher.graphicengine import pinimage
from services.vdoprocessing.pydeckrecorder import pedestrian
from services.vdoprocessing.spatial_renderer.pins import _PinMixin
from services.vdoprocessing.videopipeline.render_step import _leg_pin

RED = (0, 0, 255)  # BGR
GREEN = (0, 200, 0)


def _write_png(path, bgra):
    ok, buf = cv2.imencode(".png", bgra)
    assert ok
    path.write_bytes(buf.tobytes())
    return str(path)


@pytest.fixture
def icon(tmp_path):
    """A 64x64 transparent PNG with a solid red square in the middle."""
    img = np.zeros((64, 64, 4), dtype=np.uint8)
    img[16:48, 16:48] = (*RED, 255)
    return _write_png(tmp_path / "icon.png", img)


@pytest.fixture
def photo(tmp_path):
    """A 100x80 opaque green picture (no transparency at all)."""
    img = np.zeros((80, 100, 4), dtype=np.uint8)
    img[:, :] = (*GREEN, 255)
    return _write_png(tmp_path / "photo.png", img)


def _canvas(w=300, h=300):
    return np.full((h, w, 3), 90, dtype=np.uint8)


def test_marker_for_prefers_the_stops_own_image(icon, photo):
    wp = {"customMarker": icon}
    assert pinimage.marker_for(wp, {"routeMarker": photo}) == icon
    assert pinimage.marker_for({}, {"routeMarker": photo}) == photo


def test_marker_for_builtins_and_missing_files_stay_the_teardrop(icon, tmp_path):
    assert pinimage.marker_for({}, {}) is None
    assert pinimage.marker_for({"customMarker": ""}, {"routeMarker": "/defaults/markers/car.svg"}) is None
    # A stop that picked a preset keeps the teardrop even when the project has an image.
    assert pinimage.marker_for({"customMarker": "/defaults/markers/car.svg"}, {"routeMarker": icon}) is None
    assert pinimage.marker_for({"customMarker": str(tmp_path / "gone.png")}, {"routeMarker": icon}) is None
    assert pinimage.marker_for(None, None) is None


def test_marker_for_resolves_relative_paths_against_the_project(icon, tmp_path):
    assert pinimage.marker_for({"customMarker": "icon.png"}, {}, str(tmp_path)) == icon


def test_transparent_icon_is_trimmed_and_haloed(icon):
    sprite = pinimage.load_pin(icon)
    assert sprite is not None
    h, w = sprite.bgra.shape[:2]
    assert 32 < w < 50 and 32 < h < 50  # the 32px square plus a small halo, not the 64px canvas
    assert tuple(sprite.bgra[h // 2, w // 2, :3]) == RED
    assert sprite.bgra[0, 0, 3] < 255  # the corner of the halo is not solid


def test_opaque_picture_becomes_a_round_photo_pin(photo):
    sprite = pinimage.load_pin(photo).bgra
    s = sprite.shape[0]
    assert sprite.shape[0] == sprite.shape[1]
    assert sprite[s // 2, s // 2, 3] == 255 and tuple(sprite[s // 2, s // 2, :3]) == GREEN
    assert sprite[0, 0, 3] == 0  # the square's corner is cut away


def test_unreadable_file_returns_none_and_is_remembered(tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image at all")
    assert pinimage.load_pin(str(bad)) is None
    assert pinimage.load_pin(str(bad)) is None
    assert pinimage.load_pin(str(tmp_path / "missing.png")) is None
    assert pinimage.load_pin(None) is None


def test_cache_follows_the_file(tmp_path):
    path = tmp_path / "p.png"
    img = np.zeros((20, 20, 4), dtype=np.uint8)
    img[5:15, 5:15] = (*RED, 255)
    _write_png(path, img)
    first = pinimage.load_pin(str(path))
    assert pinimage.load_pin(str(path)) is first
    img[5:15, 5:15] = (*GREEN, 255)
    img = np.pad(img, ((0, 10), (0, 10), (0, 0)))
    _write_png(path, img)
    again = pinimage.load_pin(str(path))
    assert again is not first


def test_deck_icon_is_a_transparent_384x512_canvas_with_the_tip_at_the_bottom(icon):
    deck = pinimage.deck_icon(icon)
    assert (deck["width"], deck["height"], deck["anchorY"]) == (384, 512, 512)
    raw = base64.b64decode(deck["url"].split(",", 1)[1])
    canvas = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_UNCHANGED)
    assert canvas.shape == (512, 384, 4)
    assert canvas[0, 0, 3] == 0
    assert canvas[511 - 3, 192, 3] > 0  # the pin touches the bottom edge, centred
    assert pinimage.deck_icon(None) is None


def test_draw_marker_with_image_puts_the_picture_on_the_tip(icon):
    g = GraphicsEngine()
    frame = _canvas()
    g.draw_marker(frame, 150, 200, number="S", color=(0, 128, 0), image=icon)
    head = frame[200 - int(g.marker_radius * 1.4), 150]
    assert tuple(head) == RED
    plain = _canvas()
    g.draw_marker(plain, 150, 200, number="S", color=(0, 128, 0))
    assert not np.array_equal(frame, plain)
    assert tuple(frame[2, 2]) == (90, 90, 90)  # nothing drawn far from the pin


def test_draw_marker_falls_back_to_the_teardrop(tmp_path):
    g = GraphicsEngine()
    expected = _canvas()
    g.draw_marker(expected, 150, 200, number=3)
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"garbage")
    for image in (None, "", str(bad), str(tmp_path / "gone.png")):
        got = _canvas()
        g.draw_marker(got, 150, 200, number=3, image=image)
        assert np.array_equal(got, expected), image


def test_stopby_dot_ignores_the_image(icon):
    g = GraphicsEngine()
    with_image, without = _canvas(), _canvas()
    g.draw_marker(with_image, 150, 200, number="x", is_circle=True, image=icon)
    g.draw_marker(without, 150, 200, number="x", is_circle=True)
    assert np.array_equal(with_image, without)


def test_image_pin_is_clipped_at_the_frame_edge(icon):
    g = GraphicsEngine()
    frame = _canvas(60, 60)
    g.draw_marker(frame, 2, 5, image=icon)  # tip near a corner; must not raise
    g.draw_marker(frame, 500, 500, image=icon)  # fully outside


def test_draw_pin_passes_the_stops_image():
    seen = {}

    class Graphics:
        def draw_marker(self, frame, px, py, **kw):
            seen.update(kw)

    class Renderer(_PinMixin):
        graphics = Graphics()
        _STOPBY_PIN_COLOR = (1, 1, 1)
        _START_PIN_COLOR = (2, 2, 2)
        _END_PIN_COLOR = (3, 3, 3)
        _is_loop_route = False

        def _pin_color(self, wp):
            return None

    wp = {"x": 5, "y": 6, "index": 1, "order": 1, "data": {"pin_image": "/a/b.png"}}
    Renderer()._draw_pin(None, wp, 5)
    assert seen["image"] == "/a/b.png"
    wp["data"] = {}
    Renderer()._draw_pin(None, wp, 5)
    assert seen["image"] is None


def test_pydeck_leg_pin_uses_the_image_and_falls_back(icon, tmp_path):
    fallback = "data:image/svg+xml;fallback"
    pin = {"glyph": "2", "color": (1, 2, 3)}
    assert pedestrian._leg_pin_url(pin, fallback).startswith("data:image/svg+xml")
    with_image = pedestrian._leg_pin_url({**pin, "image": icon}, fallback)
    assert with_image.startswith("data:image/png;base64,")
    broken = pedestrian._leg_pin_url({**pin, "image": str(tmp_path / "gone.png")}, fallback)
    assert broken == pedestrian._leg_pin_url(pin, fallback)
    assert pedestrian._leg_pin_url(None, fallback) == fallback


def test_pydeck_overview_icons(icon):
    wps = [
        {"lon": 1, "lat": 2, "order": 1, "pin_glyph": "S", "pin_color": (1, 2, 3), "pin_image": icon},
        {"lon": 3, "lat": 4, "order": 2, "pin_glyph": "E", "pin_color": (1, 2, 3)},
    ]
    rows = pedestrian._overview_pin_icons(wps)
    assert rows[0]["icon"]["url"].startswith("data:image/png")
    assert rows[1]["icon"]["url"].startswith("data:image/svg+xml")


def test_leg_pin_carries_the_image_but_not_for_a_stopby():
    assert "image" not in _leg_pin("2", {}, arrived=False)
    assert _leg_pin("2", {}, arrived=False, image="/x.png")["image"] == "/x.png"
    assert "image" not in _leg_pin("・", {}, arrived=False, image="/x.png")


def test_checkpoint_part_only_exists_with_a_marker(icon, tmp_path):
    assert pinimage.marker_inputs_hash({"settings": {}, "waypoints": [{"label": "a"}]}) is None
    assert pinimage.marker_inputs_hash({"settings": {"routeMarker": "/defaults/markers/car.svg"}}) is None
    cfg = {"settings": {}, "waypoints": [{"customMarker": icon}]}
    first = pinimage.marker_inputs_hash(cfg)
    assert first and first == pinimage.marker_inputs_hash(cfg)
    other = _write_png(tmp_path / "other.png", np.full((8, 8, 4), 255, np.uint8))
    assert pinimage.marker_inputs_hash({"settings": {"routeMarker": other}}) != first
