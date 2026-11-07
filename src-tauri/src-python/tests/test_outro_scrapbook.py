import pytest

from services.vdoprocessing.outrocard import scrapbook_layout


@pytest.mark.parametrize("count", [1, 5, 11, 20])
def test_cards_fit_the_frame_and_leave_the_stamp_its_own_corner(count):
    w, h = 1920, 1080
    card_w, cards, (sx, sy, sr) = scrapbook_layout(count, (w, h))
    assert len(cards) == count
    half = card_w * 0.75  # a tilted card is a little wider than itself
    for cx, cy, _ in cards:
        assert half * 0.6 < cx < w - half * 0.6 and half * 0.6 < cy < h - half * 0.6
        assert abs(cx - sx) > sr or abs(cy - sy) > sr  # no card under the stamp
    assert sx > w / 2 and sy >= h / 2 - 1  # the last cell: bottom-right
