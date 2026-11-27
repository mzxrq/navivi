"""Overview cards placed freely round their pins (docs/OVERVIEW_RULES.md 8.18)."""
import math
import time

import numpy as np
import pytest

from services import tuning
from services.vdoprocessing.spatial_renderer.card_spots import crossing, place_cards

W, H, R = 1920, 1080, 20.0
CW, CH = 120, 100
ISLAND = [(444, 515), (382, 510), (403, 537), (405, 553), (426, 570), (525, 550), (533, 480), (485, 490), (440, 505),
          (377, 500)]  # the Tomogashima island stops, 2026-11-26
HARBOUR = [(1331, 693), (1377, 690), (1390, 660), (1547, 668), (1478, 656), (1474, 645), (1454, 666), (1453, 670)]
FERRY = np.column_stack([np.linspace(440, 1390, 300), 330 + 330 * np.linspace(0, 1, 300) ** 2])  # a line across
PANELS = [(0, 0, 660, 110), (1450, 0, W, 300), (0, 975, W, H)]


def _layout(pins=ISLAND + HARBOUR, route=FERRY, reserved=PANELS):
    boxes = place_cards(pins, W, H, reserved, route, R, CW, CH)
    assert boxes is not None and len(boxes) == len(pins)
    return boxes


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _end(pin, box):
    return min(max(pin[0], box[0]), box[2]), min(max(pin[1], box[1]), box[3])


def test_no_card_overlaps_a_card_a_panel_or_the_frame_edge():
    boxes = _layout()
    for i, a in enumerate(boxes):
        assert a[0] >= 0 and a[1] >= 0 and a[2] <= W and a[3] <= H
        assert not any(_overlap(a, b) for b in boxes[:i]) and not any(_overlap(a, p) for p in PANELS)


def test_no_card_covers_the_route_or_a_pin():
    boxes = _layout()
    for x0, y0, x1, y1 in boxes:
        assert not ((FERRY[:, 0] >= x0) & (FERRY[:, 0] <= x1) & (FERRY[:, 1] >= y0) & (FERRY[:, 1] <= y1)).any()
        for px, py in ISLAND + HARBOUR:
            assert not _overlap((x0, y0, x1, y1), (px - R, py - 2.5 * R, px + R, py))


def test_no_leader_crosses_another_or_passes_under_a_card():
    pins = ISLAND + HARBOUR
    boxes = _layout()
    lines = [(p, _end(p, b)) for p, b in zip(pins, boxes)]
    for i, (p, q) in enumerate(lines):
        t = np.linspace(0.02, 0.96, 80)[:, None]
        points = np.asarray(p) + (np.asarray(q) - p) * t
        for j, (x0, y0, x1, y1) in enumerate(boxes):
            if j != i:
                assert not ((points[:, 0] > x0) & (points[:, 0] < x1) & (points[:, 1] > y0) & (points[:, 1] < y1)).any()
        for j, (r, s) in enumerate(lines[:i]):
            if math.dist(p, r) >= 26:  # pins on one spot share their start
                assert not _cross(p, q, r, s), (i, j)


def _cross(p, q, r, s):
    def side(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return side(p, q, r) * side(p, q, s) < 0 and side(r, s, p) * side(r, s, q) < 0


def test_no_leader_is_longer_than_the_limit():
    for p, box in zip(ISLAND + HARBOUR, _layout()):
        assert math.dist(p, _end(p, box)) <= tuning.OVERVIEW_CARD_MAX_LEADER_PX + 1e-6


def test_the_limit_follows_the_frame_height():
    pins = [(x * 2 / 3, y * 2 / 3) for x, y in ISLAND + HARBOUR]
    boxes = place_cards(pins, 1280, 720, [], None, R * 2 / 3, 80, 66)
    assert boxes is not None
    longest = max(math.dist(p, _end(p, b)) for p, b in zip(pins, boxes))
    assert longest <= tuning.OVERVIEW_CARD_MAX_LEADER_PX * 2 / 3 + 1e-6


def test_no_leader_passes_over_another_pin():
    pins = ISLAND + HARBOUR
    for i, (p, box) in enumerate(zip(pins, _layout())):
        q = _end(p, box)
        d = math.dist(p, q)
        if d <= 65:
            continue
        points = np.asarray(p) + (np.asarray(q) - p) * np.linspace(45 / d, 1, 200)[:, None]
        for j, (x, y) in enumerate(pins):
            if j != i:
                assert np.hypot(points[:, 0] - x, points[:, 1] - (y - 1.8 * R)).min() >= R - 0.5, (i, j)


def test_cards_sit_on_the_far_side_of_their_pin_from_the_group():
    pins = [(900, 500), (1020, 500), (900, 620), (1020, 620)]
    for p, b in zip(pins, place_cards(pins, W, H, [], None, R, CW, CH)):
        assert math.dist((960, 560), ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)) > math.dist((960, 560), p)


def test_a_pin_with_no_room_within_the_limit_gives_no_layout():
    assert place_cards([(960, 540)], W, H, [(600, 180, 1320, 900)], None, R, CW, CH) is None


def test_two_pins_on_one_spot_both_get_a_card():
    boxes = place_cards([(960, 540)] * 2, W, H, [], None, R, CW, CH)
    assert boxes is not None and not _overlap(*boxes)


def test_no_pins_need_no_cards():
    assert place_cards([], W, H, [], None, R, CW, CH) == []


def test_the_layout_is_the_same_every_time():
    assert _layout() == _layout()


def test_leaders_and_cards_keep_off_a_pin_that_has_no_card():
    pin, other, panel = (960, 540), (960, 660), [(0, 0, W, 700)]

    def over(box):
        q = np.array(_end(pin, box))
        points = pin + (q - pin) * np.linspace(0.2, 1, 200)[:, None]
        return np.hypot(points[:, 0] - other[0], points[:, 1] - (other[1] - 1.8 * R)).min() < R - 0.5

    assert over(place_cards([pin], W, H, panel, None, R, CW, CH)[0])  # or the test proves nothing
    assert not over(place_cards([pin], W, H, panel, None, R, CW, CH, others=[other])[0])


def test_a_card_less_pin_on_the_same_spot_does_not_block_the_card():
    # the card can only go straight up, over the shared spot's own head
    walls = [(0, 400, W, H), (0, 0, 880, H), (1040, 0, W, H)]
    assert place_cards([(960, 540)], W, H, walls, None, R, CW, CH, others=[(960, 540)]) is not None


def test_a_group_too_big_gives_up_at_once():
    pins = [(900 + (i % 8) * 8, 500 + (i // 8) * 8) for i in range(40)]  # giving up by search took 78 s
    started = time.perf_counter()
    assert place_cards(pins, W, H, [], None, R, 40, 30) is None
    assert time.perf_counter() - started < 1.0


def test_cards_too_big_for_the_frame_give_no_layout():
    assert place_cards(ISLAND + HARBOUR, W, H, PANELS, FERRY, R, 700, 600) is None


@pytest.mark.parametrize("a, b, bad", [
    (((0, 0), (100, 100)), ((100, 0), (0, 100)), True),  # an X
    (((0, 0), (100, 0)), ((40, 3), (140, 3)), True),  # running on top of each other
    (((0, 0), (100, 0)), ((0, 60), (100, 60)), False),
    (((50, 50), (200, 50)), ((55, 50), (55, 200)), False),  # two pins on one spot leaving two ways
])
def test_which_leaders_clash(a, b, bad):
    assert crossing(*a, *b) is bad
