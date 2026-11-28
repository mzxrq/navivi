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


def test_the_figures_left_are_drawn_in_coarse_steps():
    hud = _hud()
    hud.places, hud.labels = hud.places_of(BANNER, "加太港", ("S", "2"), set()), video_text.labels_for("ja")

    card = lambda share: hud._card("remaining", share, 0.0, (0, 1)).html

    assert card(0.500) == card(0.504)  # each new figure card costs render time


def _figures(leg, after, shares):
    """Per share: the remaining card's font sizes and where its units stand, as drawn."""
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from services.hudtheme import render

    hud = ThemedLegHud({"layout": {}}, "sea", "walking", leg, after)
    hud.places, hud.labels = hud.places_of(BANNER, "加太港", ("S", "2"), set()), video_text.labels_for("ja")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-gpu"])
        page = render._new_page(browser, 1.0)
        found = []
        for share in shares:
            page.evaluate("html => { document.body.innerHTML = html; }", hud._card("remaining", share, 0.0, (0, 1)).html)
            page.evaluate(render._FIT_JS)
            found.append(page.evaluate("""() => {
                const shown = [...document.querySelectorAll('.num')].filter(n => n.checkVisibility({visibilityProperty: true}));
                return { sizes: shown.map(n => getComputedStyle(n).fontSize),
                         units: shown.flatMap(n => [...n.querySelectorAll('.u')].map(u => u.getBoundingClientRect().x)) };
            }"""))
        browser.close()
    return found


def test_only_the_digits_move_as_the_figures_left_count_down():
    # 12.8 km 2h18 down to 11.1 km 2h05: as many digits all the way.
    found = _figures((1.7, 780), (11.1, 7500), [i / 12 for i in range(13)])

    assert all(f == found[0] for f in found), found


def test_the_figures_keep_their_size_when_they_lose_a_digit():
    found = _figures((3.0, 3000), (8.0, 1500), [0.0, 0.5, 1.0])  # 11.0 km 1h15 down to 8.0 km 25 min

    assert len({size for f in found for size in f["sizes"]}) == 1, found


def test_one_traveller_slides_along_a_bar_drawn_once(monkeypatch):
    monkeypatch.setattr(video_text, "current_labels", lambda: video_text.labels_for("ja"))
    hud = _prepared(_hud())

    at = lambda share: {i[0]: i for i in hud.items(share, 0.0, (0, 1)) if i[0].startswith("leg_rail")}
    first, near, further = at(0.5), at(0.501), at(0.502)

    assert set(first) == {"leg_rail", "leg_rail_walked", "leg_rail_walker"}
    assert set(near) == {"leg_rail_walked", "leg_rail_walker"}  # the bar itself never changes
    step = near["leg_rail_walker"][2] - first["leg_rail_walker"][2]
    assert 0 < step < 1.5 and further["leg_rail_walker"][2] - near["leg_rail_walker"][2] == pytest.approx(step, abs=0.02)
    assert near["leg_rail_walked"][7] == pytest.approx(first["leg_rail_walked"][7] - step, abs=0.02)
    rail_pictures = {card for html, card in hud._pictures.items() if "data-rail" in html}
    assert len(rail_pictures) == 3  # the empty bar, the walked bar, the traveller


def test_a_users_rail_style_without_layers_is_still_drawn_step_by_step(monkeypatch, tmp_path):
    monkeypatch.setattr(video_text, "current_labels", lambda: video_text.labels_for("ja"))
    monkeypatch.setenv("NAVIVI_STYLES_DIR", str(tmp_path))
    (tmp_path / "leg_rail").mkdir()
    (tmp_path / "leg_rail" / "mine.html").write_text(
        '<div class="card" style="width:636px;height:82px">{{ (share * 100)|f1 }}</div>', encoding="utf-8")
    hud = _prepared(_hud({"leg_rail": {"style": "mine"}}))

    assert [i[0] for i in hud.items(0.5, 0.0, (0, 1)) if i[0].startswith("leg_rail")] == ["leg_rail"]


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

    layers = {"leg_rail_walked", "leg_rail_walker"}
    assert {i[0] for i in first} == set(CARDS) | layers and same == []
    assert {i[0] for i in walked} == {"next", "compass", "remaining"} | layers
    assert hud.items(1.0, 91.0, (1, 2))  # every state asked for during the walk was drawn beforehand
    boxes = {i[0]: (i[2], i[3], i[2] + i[4], i[3] + i[5]) for i in first}
    assert boxes["leg_rail"][2] <= boxes["leg_banner"][0]
    assert all(0 <= x0 and x1 <= 1280 and 0 <= y0 and y1 <= 720 for x0, y0, x1, y1 in boxes.values())


def test_hidden_cards_are_neither_drawn_nor_kept_clear_of():
    hud = _hud({"compass": {"show": False}, "leg_rail": {"anchor": "top-center"}})

    assert len(hud.room((1280, 720))) == len(CARDS) - 1
    _prepared(hud)
    assert "compass" not in {i[0] for i in hud.items(0.0, 0.0, (0, 1))}
    assert hud.rail_top() is None  # not at the foot: nothing has to sit above it


def test_the_walks_totals_sit_on_top_and_this_legs_figures_below():
    entries = _hud().entries

    assert entries["remaining"].anchor == "top-right" and entries["leg_banner"].anchor == "bottom-right"
    assert entries["compass"].anchor == "top-right" and entries["compass"].y > entries["remaining"].y + 76


def test_a_themed_leg_renders_again_when_the_figures_on_its_cards_change():
    config = {"layout": {}, "fingerprint": "abc"}
    made = lambda after: ThemedLegHud(config, "sea", "walking", (2.0, 1800), after).fingerprint

    assert made((8.0, 7200)) != made((8.0, 7600))  # a later leg takes longer: this one's time left changes
    assert made((8.0, 7200)) == made((8.0001, 7200.3))


def test_a_ferry_route_renders_again_when_the_ferry_speed_changes(tmp_path, monkeypatch):
    import json

    from services import tuning
    from services.vdoprocessing.videopipeline.render_checkpoint import _checkpoint_parts, _route_changes

    def parts(mode):
        config = tmp_path / "job_config.json"
        config.write_text(json.dumps({"waypoints": [{"routeMode": mode}]}), encoding="utf-8")
        return _checkpoint_parts(str(config), {}, None, None), str(config)

    new, path = parts("ferry")
    monkeypatch.setitem(tuning.REPORTED_MODE_SPEED_KMH, "ferry", 99.0)
    old, _ = parts("ferry")

    assert "route.speeds" in _route_changes(old, "k", "k2", new, path)
    del old["route.speeds"]  # a render from before this was recorded
    assert "route.speeds" in _route_changes(old, "k", "k2", new, path)
    assert "route.speeds" not in parts("walking")[0]


def test_a_themed_look_change_renders_the_route_again():
    from services.vdoprocessing.videopipeline.render_checkpoint import _route_changes

    old = {"route.waypoints": "w", "route.hud": "before"}

    assert "route.hud" in _route_changes(old, "k", "k2", {**old, "route.hud": "after"}, "missing.json")
    assert "route.hud" not in _route_changes(old, "k", "k2", dict(old), "missing.json")
