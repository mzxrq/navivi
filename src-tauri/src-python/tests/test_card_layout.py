"""The overview's cards: one spot and one size per place (docs/OVERVIEW_RULES.md 8.18)."""
from types import SimpleNamespace

import pytest

from services import tuning
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


@pytest.mark.parametrize("count", [40, 80])
def test_a_tight_cluster_still_gets_every_card(count):
    pins = [{"x": 900 + (i % 8) * 8, "y": 500 + (i // 8) * 8, "index": i, "data": {}} for i in range(count)]
    cards = _layout()._layout_ring_cards(pins, 1920, 1080)
    assert len(cards) == count and len({c["card_scale"] for c in cards}) == 1 and not _overlapping(cards)


def test_the_size_stops_at_the_maximum_and_follows_the_frame_height():
    assert _layout()._layout_ring_cards(_pins(1), 1920, 1080)[0]["card_scale"] == tuning.OVERVIEW_CARD_MAX_SCALE
    small = _layout()._layout_ring_cards(_pins(1), 1280, 720)[0]["card_scale"]
    assert small == tuning.OVERVIEW_CARD_MAX_SCALE * 720 / 1080
