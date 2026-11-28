"""The walking leg's themed HUD: what each card says, which pictures are drawn and when they change."""

import pytest

from services import video_text
from services.vdoprocessing.pydeckrecorder.themed_leg import CARDS, ThemedLegHud

# (text, badge, is stop-by), as the leg's banner lists them
BANNER = [("加太駅", "S", False), ("番所", None, True), ("加太港", "2", False)]


def _hud(layout=None, **more):
    return ThemedLegHud({"layout": layout or {}, "fingerprint": "abc"}, "sea", "walking", (2.0, 1800), (8.0, 7200),
                        **more)


def test_stop_bys_wear_the_number_their_map_pin_shows():
    places = _hud(stopby_glyphs=["+3"]).places_of(BANNER, "加太港", ("S", "2"), {"番所"})

    assert [(p.name, p.glyph, p.off_route) for p in places] == [
        ("加太駅", "S", False), ("番所", "+3", True), ("加太港", "2", False)]


def test_a_leg_with_no_chain_shows_its_destination():
    assert _hud().places_of([], "加太港", (None, "2"), set())[0][:2] == ("加太港", "2")


def test_a_legs_stop_by_numbers_come_from_the_map_not_from_counting():
    from types import SimpleNamespace

    from services.vdoprocessing.route2vdo import RouteAnimator

    # An earlier leg's stop-bys are not counted: stop-bys +4 (a return to an earlier one) and an unnumbered one.
    leg = {"labels": ["加太駅", "番所", None, "寄り道", "加太港"], "stopbys": [False, True, True, True, True],
           "stopby_labels": [None, "+4", "+8", None, "+9"], "mode": "walking"}
    animator = SimpleNamespace(config={"hud": {"theme": "sea", "layout": {}}})
    ctx = SimpleNamespace(leg_totals=[(1.0, 60), (2.0, 120)])

    hud = RouteAnimator._themed_leg_hud(animator, ctx, 1, "walking", [{"mode": "walking"}, leg])

    # In banner order; the destination is the banner's last place (its own pin glyph), not one of these.
    assert hud.stopby_glyphs == ["+4", "・"]


def _prepared(hud, frame=(1280, 720)):
    pytest.importorskip("playwright")
    places = hud.places_of(BANNER, "加太港", ("S", "2"), set())
    hud.prepare(frame, places, [(0.5, "+1")], [i / 10 for i in range(11)], [0.0, 91.0, 92.0],
                [(0, 1), (1, 2)])
    return hud


def test_only_the_cards_that_changed_are_swapped(monkeypatch):
    monkeypatch.setattr(video_text, "current_labels", lambda: video_text.labels_for("ja"))
    hud = _prepared(_hud())

    first = hud.items(0.0, 0.0, (0, 1))
    same = hud.items(0.0, 1.0, (0, 1))  # one degree: the same compass picture
    walked = hud.items(0.5, 91.0, (1, 2))

    assert {i[0] for i in first} == set(CARDS) and same == []
    assert {i[0] for i in walked} == {"next", "compass", "leg_rail", "remaining"}
    assert hud.items(1.0, 91.0, (1, 2))  # every state asked for during the walk was drawn beforehand
    boxes = {i[0]: (i[2], i[3], i[2] + i[4], i[3] + i[5]) for i in first}
    assert boxes["leg_rail"][2] <= boxes["remaining"][0]
    assert all(0 <= x0 and x1 <= 1280 and 0 <= y0 and y1 <= 720 for x0, y0, x1, y1 in boxes.values())


def test_hidden_cards_are_neither_drawn_nor_kept_clear_of():
    hud = _hud({"compass": {"show": False}, "leg_rail": {"anchor": "top-center"}})

    assert len(hud.room((1280, 720))) == len(CARDS) - 1
    _prepared(hud)
    assert "compass" not in {i[0] for i in hud.items(0.0, 0.0, (0, 1))}
    assert hud.rail_top() is None  # not at the foot: nothing has to sit above it
