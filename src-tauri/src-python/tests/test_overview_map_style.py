from types import SimpleNamespace

import numpy as np
import pytest

from services.mapfetcher.graphicengine import GraphicsEngine
from services.vdoprocessing.spatial_renderer.pins import _PinMixin
from services.vdoprocessing.spatial_renderer.popups import _PopupMixin
from services.vdoprocessing.storyboard import of


class _Layout(_PopupMixin, _PinMixin):
    _is_loop_route = False


def test_map_popup_shows_the_photo_then_slides_to_the_leg_card():
    g = GraphicsEngine()
    g.slide_fps = 10
    photo = np.full((90, 160, 3), 50, np.uint8)
    card = np.full((90, 160, 3), 200, np.uint8)
    data = {"leg_card_bgr": card}
    timings = of("map").timings
    photo_frames = int(timings["map_photo_seconds"] * 10)
    shown = [g.slide_to_card(data, photo) for _ in range(photo_frames + int(timings["map_slide_seconds"] * 10) + 2)]
    assert (shown[0] == 50).all() and (shown[photo_frames - 1] == 50).all()  # the photo first
    mid = shown[photo_frames + 1]
    assert mid[:, 0].mean() == 50 and mid[:, -1].mean() == 200  # photo leaving left, card coming in from the right
    assert (shown[-1] == 200).all()  # then the card alone


def test_plain_popup_never_slides():
    photo = np.full((9, 16, 3), 50, np.uint8)
    assert GraphicsEngine().slide_to_card({}, photo) is photo


def _map_popup(**extra):
    return {"x": 900, "y": 500, "index": 1, "order": 1, "stay_box": (700, 200), "stay_scale": 1.0, "card_scale": 2.6,
            "beside_box": (100, 100), "data": {"popup_image": "p.png"}, **extra}


def _layout(config=None):
    layout = _Layout()
    layout.config = {"overview_style": "map", **(config or {})}
    layout.graphics = SimpleNamespace(marker_radius=20, beside_card_footprint=lambda *a, **k: (210, 170),
                                      render_popup_box=lambda frame, info, **k: frame)
    layout._draw_pin = lambda *a, **k: None
    return layout


def test_a_map_stop_keeps_its_big_card_until_it_closes_then_stands_at_its_spot():
    layout = _layout()
    big = layout.walk_card_hud(_map_popup(), 1920, 1080, None, lambda other: [], big=True)
    assert (big["beside_box"], big["card_scale"]) == ((100, 100), 2.6) and big.get("leg_card", True)
    standing = layout.walk_card_hud(_map_popup(), 1920, 1080, None, lambda other: [])
    assert (standing["beside_box"], standing["card_scale"]) == ((700, 200), 1.0)
    assert standing["leg_card"] is False  # the photo stays, not the leg card


@pytest.mark.parametrize("switch, left", [(True, 1), (False, 0)])
def test_the_standing_card_takes_over_when_the_big_one_closes(switch, left):
    layout = _layout({"overview_cards_stay": switch})
    popup = _map_popup(big=True)
    live = [{"popup": popup, "frames_left": 1, "total_frames": 30, "fade_frames": 5}]
    frame = np.zeros((1080, 1920, 3), np.uint8)
    layout._layout_recap_popups = lambda *a, **k: None
    _, live = layout._composite_baked_popups(frame, live, 1920, 1080, None, active_popups=[], total_points=3, fps=30)
    assert len(live) == left and "big" not in popup
    if left:
        assert live[0]["popup"] is popup and live[0]["frames_left"] == live[0]["total_frames"]


def test_the_slide_to_the_leg_card_only_happens_on_the_big_card(tmp_path):
    photo = tmp_path / "p.png"
    photo.write_bytes(b"x")  # only its presence is checked: the read is replaced below
    g = GraphicsEngine()
    slid = []
    g.slide_to_card = lambda data, picture: slid.append(data) or picture
    g.read_image_safe = lambda *a, **k: np.full((90, 160, 3), 50, np.uint8)
    for info in ({"leg_card": False}, {}):
        g.render_popup_box(np.zeros((1080, 1920, 3), np.uint8),
                           {"x": 500, "y": 500, "beside_box": (200, 200), "data": {"popup_image": str(photo)}, **info})
    assert len(slid) == 1


def test_route_map_cards_stay():
    assert of("map").cards_stay


def test_route_map_stop_line_says_the_leg_distance():
    from services.localization.overview_script import leg_facts_line

    assert leg_facts_line({"km": 3.32, "minutes": 86}) == "ここまで3.3キロの道のりでした。"
    assert leg_facts_line({"km": 0.13, "minutes": 3}) == "ここまで130メートルの道のりでした。"
