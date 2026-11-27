"""The overview's cards: one spot and one size per place (docs/OVERVIEW_RULES.md 8.18)."""
from types import SimpleNamespace

import numpy as np
import pytest

from services import tuning
from services.mapfetcher.graphicengine.popup_box import _PopupBoxMixin, fill_card_shape
from services.vdoprocessing.spatial_renderer import SpatialRenderer, popups as popups_module
from services.vdoprocessing.spatial_renderer.overview import _standing_cards
from services.vdoprocessing.spatial_renderer.pins import _PinMixin
from services.vdoprocessing.spatial_renderer.popups import _PopupMixin, zoom_card_alphas


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
        route_progress_rail_height=lambda h: 73,
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
    renderer = _renderer({})
    renderer.graphics.overview_hud_panels = lambda *a, **k: (SimpleNamespace(size=(300, 70)),
                                                            SimpleNamespace(size=(420, 110)))
    _card, reserved = renderer._ov_reserved_boxes(None, 1920, 1080)
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


@pytest.mark.parametrize("config", [{}, {"overview_cards_stay": False}])
def test_the_recap_draws_each_card_where_it_stood(config):
    renderer, popups = _laid_out(config)
    cards = renderer._recap_cards(popups)
    assert [(c["beside_box"], c["card_scale"]) for c in cards] == [
        (p["stay_box"], p["stay_scale"]) for p in popups if p.get("stay_box")]
    assert not any(c.get("is_pill_badge") for c in cards)


@pytest.mark.parametrize("photos", [True, False])
def test_the_recap_marks_every_place_with_its_pin_and_draws_cards_as_the_walk_did(photos):
    renderer, popups = _renderer({}), _stops()
    if not photos:
        for p in popups:
            p["data"].pop("popup_image", None)
    renderer._ov_layout_stay_cards(popups, popups[-1], 1920, 1080, [], None)
    pins, cards = [], []
    renderer._draw_pin = lambda frame, wp, n, **k: pins.append(wp["index"])
    renderer.graphics.render_popup_box = lambda frame, info, **k: cards.append(info) or frame
    renderer._render_recap_frame(np.zeros((1080, 1920, 3), np.uint8), popups, group_popups=renderer._recap_cards(popups))
    assert pins == [0, 1, 2, 3, 4]  # the stop-by with no photo too
    assert len(cards) == (6 if photos else 0)  # three cards, line then box
    assert not any("leader_line_color" in c for c in cards)  # no recap restyling


@pytest.mark.parametrize("count", [40, 80])
def test_a_tight_cluster_still_gets_every_card(count):
    pins = [{"x": 900 + (i % 8) * 8, "y": 500 + (i // 8) * 8, "index": i, "data": {}} for i in range(count)]
    cards = _layout()._layout_ring_cards(pins, 1920, 1080)
    assert len(cards) == count and len({c["card_scale"] for c in cards}) == 1 and not _overlapping(cards)


@pytest.mark.parametrize("ease, alphas", [(0.0, (1.0, 0.0)), (0.25, (0.5, 0.0)), (0.5, (0.0, 0.0)),
                                          (0.75, (0.0, 0.5)), (1.0, (0.0, 1.0))])
def test_cards_cross_fade_between_their_whole_map_and_zoomed_spots(ease, alphas):
    assert zoom_card_alphas(ease) == alphas  # never both layouts at once


def test_a_leader_is_a_straight_line_to_the_nearest_point_of_its_card():
    frame = np.zeros((400, 400, 3), np.uint8)
    _PopupBoxMixin._draw_leader_line(
        frame, {"x": 50, "y": 50, "leader_straight": True, "leader_line_color": (255, 255, 255)}, 250, 150, 100, 100)
    assert frame[95:112, 150].any()  # on the way from the pin to the card's near corner
    assert not frame[50, 150].any()  # no right-angle bend


@pytest.mark.parametrize("pin", [(50, 50), (450, 50), (50, 350), (450, 350)])
def test_a_leader_reaches_the_rounded_corner_of_its_card(pin):
    frame = np.zeros((400, 500, 3), np.uint8)
    _PopupBoxMixin._draw_leader_line(
        frame, {"x": pin[0], "y": pin[1], "leader_straight": True, "leader_line_color": (255, 255, 255)},
        200, 150, 100, 100)
    corner = (200 if pin[0] < 200 else 299, 150 if pin[1] < 150 else 249)
    inward = (6 if pin[0] < 200 else -6, 6 if pin[1] < 150 else -6)
    # 6 px in from both sides of the square corner is already on the rounded card: the line must get there.
    x, y = corner[0] + inward[0], corner[1] + inward[1]
    assert frame[y - 3:y + 4, x - 3:x + 4].any()


def test_the_course_cuts_leader_lines_only_under_the_rounded_card():
    cut = np.zeros((200, 300), np.uint8)
    fill_card_shape(cut, 50, 50, 100, 80)
    assert cut[90, 100] and cut[51, 100] and cut[90, 51]
    assert not cut[51, 51] and not cut[128, 148] and not cut[90, 151]  # the corners stay open, nothing outside


@pytest.mark.parametrize("style", ["walk", "map", "course"])
def test_every_overview_card_has_a_straight_leader(style):
    renderer, popups = _renderer({"overview_style": style}), _stops()
    renderer._pin_label_and_color = lambda wp, total: ("1", (0, 0, 0), None)
    renderer.graphics.marker_color = (0, 0, 0)
    renderer._ov_style_badges(popups, len(popups))
    assert all(p["leader_straight"] for p in popups)


def _under_another_card(cards):
    """(i, j) where the leader of card i passes under card j."""
    out = []
    for i, c in enumerate(cards):
        (x0, y0), (cw, ch), (px, py) = c["beside_box"], _size(c["card_scale"]), (c["x"], c["y"])
        ax, ay = min(max(px, x0), x0 + cw), min(max(py, y0), y0 + ch)
        for t in np.linspace(0.05, 0.95, 60):
            x, y = px + (ax - px) * t, py + (ay - py) * t
            for j, other in enumerate(cards):
                (ox, oy), (ow, oh) = other["beside_box"], _size(other["card_scale"])
                if j != i and ox < x < ox + ow and oy < y < oy + oh and (i, j) not in out:
                    out.append((i, j))
    return out


_ISLAND = [(444, 515), (382, 510), (403, 537), (405, 553), (426, 570), (525, 550), (533, 480), (485, 490), (440, 505),
           (377, 500)]  # the Tomogashima island stops, 2026-11-26
_HARBOUR = [(1331, 693), (1377, 690), (1390, 660), (1547, 668), (1478, 656), (1474, 645), (1454, 666), (1453, 670),
            (650, 360), (712, 382)]


@pytest.mark.parametrize("pins", [_ISLAND, _ISLAND + _HARBOUR])
def test_no_leader_passes_under_another_card(pins):
    popups = [{"x": x, "y": y, "index": i, "data": {}} for i, (x, y) in enumerate(pins)]
    cards = _layout()._layout_ring_cards(popups, 1920, 1080)
    assert len(cards) == len(pins) and not _overlapping(cards)
    assert _under_another_card(cards) == []


def test_clearing_the_leaders_never_shrinks_the_cards_to_stamps():
    pins = [(900 + 37 * (i % 5), 500 + 29 * (i // 5)) for i in range(15)]  # crossing-free only at 0.41
    popups = [{"x": x, "y": y, "index": i, "data": {}} for i, (x, y) in enumerate(pins)]
    cards = _layout()._layout_ring_cards(popups, 1920, 1080)
    assert len(cards) == 15 and not _overlapping(cards) and cards[0]["card_scale"] > 0.7


def test_whole_route_first_gives_each_place_with_a_photo_one_card():
    renderer, popups = _renderer({"overview_style": "course"}), _stops()
    on_route, extras = [popups[0], popups[1], popups[3], popups[4]], [popups[2]]
    laid, cards = renderer._course_cards(on_route, extras, {id(popups[3])}, popups[4], [], None, 1920, 1080)
    assert sorted(cards) == [0, 1, 4] and sorted(p["index"] for p in laid) == [0, 1, 4]
    assert all(cards[i] is popups[i] for i in cards)
    assert all(p["stay_box"] == p["beside_box"] and p["stay_scale"] == p["card_scale"] for p in laid)
    assert len({p["stay_scale"] for p in laid}) == 1


def test_cards_keep_off_a_route_drawn_between_two_far_apart_points():
    renderer, popups = _renderer({}), _stops()  # a ferry leg: only its two ends are in the path
    renderer._ov_layout_stay_cards(popups, popups[-1], 1920, 1080, [], None, route_path=[(0, 420), (1920, 420)])
    placed = [(p["stay_box"], _size(p["stay_scale"])) for p in popups if p.get("stay_box")]
    assert placed and not any(y <= 420 <= y + ch for (_, y), (_, ch) in placed)


def test_the_free_layout_is_used_where_it_fits(monkeypatch):
    seen = []
    monkeypatch.setattr(popups_module, "place_cards",
                        lambda pins, w, h, reserved, route, r, cw, ch, others=(): seen.append((cw, ch)) or [
                            (10.0 + 400 * i, 20.0, 10.0 + 400 * i + cw, 20.0 + ch) for i in range(len(pins))])
    cards = _layout()._layout_ring_cards(_pins(3), 1920, 1080)
    assert [c["beside_box"] for c in cards] == [(10, 20), (410, 20), (810, 20)]
    assert {c["card_scale"] for c in cards} == {tuning.OVERVIEW_CARD_MAX_SCALE}  # the largest size that works


def test_when_nothing_fits_freely_every_card_still_gets_a_spot(monkeypatch):
    monkeypatch.setattr(popups_module, "place_cards", lambda *a, **k: None)
    cards = _layout()._layout_ring_cards(_pins(24), 1920, 1080)
    assert len(cards) == 24 and not _overlapping(cards)


def test_the_largest_size_that_fits_wins_even_when_the_next_one_down_would_not(monkeypatch):
    calls = []

    def fake(pins, w, h, reserved, route, r, cw, ch, others=()):
        calls.append(cw)
        return [(10.0 + 400 * i, 20.0, 10.0 + 400 * i + cw, 20.0 + ch)
                for i in range(len(pins))] if len(calls) == 4 else None

    monkeypatch.setattr(popups_module, "place_cards", fake)
    cards = _layout()._layout_ring_cards(_pins(3), 1920, 1080)
    assert len(calls) == 4
    assert cards[0]["card_scale"] == pytest.approx(
        tuning.OVERVIEW_CARD_MAX_SCALE * tuning.OVERVIEW_CARD_FREE_SHRINK_STEP ** 3)


@pytest.mark.parametrize("style", ["walk", "course"])
def test_pins_without_a_photo_are_handed_to_the_layout(monkeypatch, style):
    seen = []

    def fake(pins, w, h, reserved, route, r, cw, ch, others=()):
        seen.append(list(others))
        return None

    monkeypatch.setattr(popups_module, "place_cards", fake)
    renderer, popups = _renderer({"overview_style": style}), _stops()
    del popups[0]["data"]["popup_image"]  # a numbered stop with no photo, besides the stop-by
    if style == "walk":
        renderer._ov_layout_stay_cards(popups, popups[-1], 1920, 1080, [], None)
    else:
        renderer._course_cards([popups[i] for i in (0, 1, 3, 4)], [popups[2]], {id(popups[3])}, popups[4],
                               [], None, 1920, 1080)
    assert (1100, 600) in seen[0] and (300, 300) in seen[0]


def test_the_size_stops_at_the_maximum_and_follows_the_frame_height():
    assert _layout()._layout_ring_cards(_pins(1), 1920, 1080)[0]["card_scale"] == tuning.OVERVIEW_CARD_MAX_SCALE
    small = _layout()._layout_ring_cards(_pins(1), 1280, 720)[0]["card_scale"]
    assert small == tuning.OVERVIEW_CARD_MAX_SCALE * 720 / 1080
