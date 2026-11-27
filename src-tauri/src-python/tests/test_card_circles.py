"""Overview cards on a circle round each group of pins (docs/OVERVIEW_RULES.md 8.18)."""
import math
import time

import numpy as np
import pytest

from services import tuning
from services.vdoprocessing.spatial_renderer.card_circles import circle_layout, crossing

W, H, R = 1920, 1080, 20.0
CW, CH = 120, 100
ISLAND = [(444, 515), (382, 510), (403, 537), (405, 553), (426, 570), (525, 550), (533, 480), (485, 490), (440, 505),
          (377, 500)]  # the Tomogashima island stops, 2026-11-26
HARBOUR = [(1331, 693), (1377, 690), (1390, 660), (1547, 668), (1478, 656), (1474, 645), (1454, 666), (1453, 670)]
FERRY = np.column_stack([np.linspace(440, 1390, 300), 330 + 330 * np.linspace(0, 1, 300) ** 2])  # a line across
PANELS = [(0, 0, 660, 110), (1450, 0, W, 300), (0, 975, W, H)]


def _layout(pins=ISLAND + HARBOUR, route=FERRY, reserved=PANELS):
    boxes = circle_layout(pins, W, H, reserved, route, R, CW, CH)
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


def test_each_group_of_pins_has_its_cards_round_it():
    boxes = _layout()
    for group in (range(len(ISLAND)), range(len(ISLAND), len(ISLAND + HARBOUR))):
        centres = np.array([((boxes[i][0] + boxes[i][2]) / 2, (boxes[i][1] + boxes[i][3]) / 2) for i in group])
        middle = np.mean([(ISLAND + HARBOUR)[i] for i in group], axis=0)
        angles = np.sort(np.arctan2(centres[:, 1] - middle[1], centres[:, 0] - middle[0]))
        gaps = np.diff(np.append(angles, angles[0] + 2 * math.pi))
        assert gaps.max() < math.pi  # all round it, not heaped on one side
        radius = np.hypot(*(centres - middle).T)
        assert radius.max() <= tuning.OVERVIEW_CARD_CIRCLE_ROUNDNESS * radius.min()  # at much the same distance


def test_an_arrangement_that_is_not_a_circle_is_not_accepted(monkeypatch):
    # a bigger card with a loose shape was preferred to the round one (Tomogashima, 2026-11-26)
    monkeypatch.setattr(tuning, "OVERVIEW_CARD_CIRCLE_ROUNDNESS", 1.0)
    assert circle_layout(ISLAND, W, H, PANELS, FERRY, R, CW, CH) is None


def test_the_layout_is_the_same_every_time():
    assert _layout() == _layout()


def test_a_group_too_big_for_one_circle_gives_up_at_once():
    pins = [(900 + (i % 8) * 8, 500 + (i // 8) * 8) for i in range(40)]  # searching it took a minute
    started = time.perf_counter()
    assert circle_layout(pins, W, H, [], None, R, 40, 30) is None
    assert time.perf_counter() - started < 1.0


def test_cards_too_big_for_the_frame_give_no_layout():
    assert circle_layout(ISLAND + HARBOUR, W, H, PANELS, FERRY, R, 700, 600) is None


@pytest.mark.parametrize("a, b, bad", [
    (((0, 0), (100, 100)), ((100, 0), (0, 100)), True),  # an X
    (((0, 0), (100, 0)), ((40, 3), (140, 3)), True),  # running on top of each other
    (((0, 0), (100, 0)), ((0, 60), (100, 60)), False),
    (((50, 50), (200, 50)), ((55, 50), (55, 200)), False),  # two pins on one spot leaving two ways
])
def test_which_leaders_clash(a, b, bad):
    assert crossing(*a, *b) is bad
