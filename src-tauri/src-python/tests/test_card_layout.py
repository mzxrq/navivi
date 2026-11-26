"""The overview's cards: one spot and one size per place (docs/OVERVIEW_RULES.md 8.18)."""
from types import SimpleNamespace

import pytest

from services import tuning
from services.vdoprocessing.spatial_renderer import SpatialRenderer
from services.vdoprocessing.spatial_renderer.overview import _standing_cards
from services.vdoprocessing.spatial_renderer.pins import _PinMixin
from services.vdoprocessing.spatial_renderer.popups import _PopupMixin


class _Layout(_PopupMixin, _PinMixin):
    _is_loop_route = False


def _size(scale=1.0, *a, **k):
    return int(210 * scale), int(170 * scale)


def _layout():
    layout = _Layout()
    layout.config = {}
    layout.graphics = SimpleNamespace(marker_radius=20, beside_card_footprint=_size)
    return layout


def _pins(n):
    return [{"x": 120 + (i % 10) * 180, "y": 120 + (i // 10) * 150, "index": i, "data": {}} for i in range(n)]


def _overlapping(cards):
    boxes = [(*c["beside_box"], *(a + b for a, b in zip(c["beside_box"], _size(c["card_scale"])))) for c in cards]
    return [(i, j) for i, a in enumerate(boxes) for j, b in enumerate(boxes[:i])
            if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]]


def test_all_cards_share_one_size_and_none_overlap():
    cards = _layout()._layout_ring_cards(_pins(24), 1920, 1080)
    assert len(cards) == 24 and len({c["card_scale"] for c in cards}) == 1 and not _overlapping(cards)


def test_fewer_places_get_bigger_cards():
    few = _layout()._layout_ring_cards(_pins(5), 1920, 1080)
    many = _layout()._layout_ring_cards(_pins(24), 1920, 1080)
    assert few[0]["card_scale"] > many[0]["card_scale"]


def test_sixty_places_all_get_a_card():
    cards = _layout()._layout_ring_cards(_pins(60), 1920, 1080)
    assert len(cards) == 60 and not _overlapping(cards)


def _renderer(config):
    renderer = SpatialRenderer.__new__(SpatialRenderer)
    renderer.config = config
    renderer.graphics = SimpleNamespace(
        marker_radius=20, beside_card_footprint=_size,
        stopby_notice_box=lambda w, h, kind="stopby", offset_x=0: (20, h - 120, 320, h - 20),
    )
    renderer._get_job_config = lambda: {}
    return renderer


def _stops():
    def stop(x, y, index, lat, **data):
        return {"x": x, "y": y, "index": index, "data": {"lat": lat, "lng": lat + 104.0, **data}}

    photo = {"popup_image": "p.png"}
    return [
        stop(300, 300, 0, 35.0, **photo),
        stop(700, 300, 1, 35.1, **photo),
        stop(1100, 600, 2, 35.2, is_stopby=True),
        stop(700, 300, 3, 35.1, **photo),  # return visit
        stop(1500, 800, 4, 35.4, **photo),
    ]


def _laid_out(config):
    renderer, popups = _renderer(config), _stops()
    renderer._ov_layout_stay_cards(popups, popups[-1], 1920, 1080, [], None)
    return renderer, popups


@pytest.mark.parametrize("switch", [True, False])
def test_each_place_with_a_photo_gets_one_spot_and_size(switch):
    _, popups = _laid_out({"overview_cards_stay": switch})
    assert [bool(p.get("stay_box")) for p in popups] == [True, True, False, False, True]
    # The stop-by with no photo and the return visit show their pin only.
    assert [bool(p.get("no_card")) for p in popups] == [False, False, True, True, False]  # 2: no photo
    assert len({p["stay_scale"] for p in popups if p.get("stay_box")}) == 1
    assert all("card_scale" not in p and "beside_box" not in p for p in popups)


def test_cards_keep_clear_of_the_top_panels():
    _card, reserved = _renderer({})._ov_reserved_boxes(None, 1920, 1080)
    assert any(top < 40 and left < 400 for left, top, right, bottom in reserved)  # title, top left
    assert any(top < 40 and right > 1500 for left, top, right, bottom in reserved)  # remaining, top right


def test_the_walk_draws_a_card_exactly_at_its_spot():
    popup = {"x": 900, "y": 500, "stay_box": (700, 200), "stay_scale": 1.4, "card_scale": 2.6, "data": {}}
    hud = _layout().walk_card_hud(popup, 1920, 1080, None, lambda other: [])
    assert hud["beside_box"] == (700, 200) and hud["card_scale"] == 1.4 and hud["draw_leader_line"]


def test_a_kept_card_reserves_the_space_it_is_drawn_in():
    popup = {"stay_box": (700, 200), "stay_scale": 2.0, "card_scale": 1.0, "beside_box": (0, 0), "data": {}}
    assert _layout()._active_card_boxes([{"popup": popup}]) == [(700, 200, 700 + 420, 200 + 340)]


def test_the_intro_cards_use_their_spots_and_stay_for_the_walk():
    renderer, popups = _laid_out({})
    cards = renderer._ov_make_intro_cards(popups[0], popups[-1], 1920, 1080, None)
    assert [c["beside_box"] for c in cards] == [popups[0]["stay_box"], popups[-1]["stay_box"]]
    assert [c["card_scale"] for c in cards] == [popups[0]["stay_scale"]] * 2
    assert _standing_cards(popups[0], popups[-1]) == [popups[0], popups[-1]]


def test_a_start_with_no_photo_gets_no_intro_card():
    renderer, popups = _renderer({}), _stops()
    del popups[0]["data"]["popup_image"]
    renderer._ov_layout_stay_cards(popups, popups[-1], 1920, 1080, [], None)
    cards = renderer._ov_make_intro_cards(popups[0], popups[-1], 1920, 1080, None)
    assert [c["beside_box"] for c in cards] == [popups[-1]["stay_box"]]


def test_a_standing_cards_pin_shows_before_the_walker_arrives():
    renderer, popups = _renderer({}), _stops()
    popups[-1]["standing"] = True
    drawn = []
    renderer._draw_pin = lambda frame, wp, n, **k: drawn.append(wp["index"])
    renderer._pin_pop_scale, renderer._pop_now = lambda *a: 1.0, 0
    renderer._draw_arrived_pins(SimpleNamespace(active_popups=popups, n_points=5, fps=30), None)
    assert drawn == [0, 4]


@pytest.mark.parametrize("count", [40, 80])
def test_a_tight_cluster_still_gets_every_card(count):
    pins = [{"x": 900 + (i % 8) * 8, "y": 500 + (i // 8) * 8, "index": i, "data": {}} for i in range(count)]
    cards = _layout()._layout_ring_cards(pins, 1920, 1080)
    assert len(cards) == count and len({c["card_scale"] for c in cards}) == 1 and not _overlapping(cards)


def test_the_size_stops_at_the_maximum_and_follows_the_frame_height():
    assert _layout()._layout_ring_cards(_pins(1), 1920, 1080)[0]["card_scale"] == tuning.OVERVIEW_CARD_MAX_SCALE
    small = _layout()._layout_ring_cards(_pins(1), 1280, 720)[0]["card_scale"]
    assert small == tuning.OVERVIEW_CARD_MAX_SCALE * 720 / 1080
