import math
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from services import tuning
from services.mapfetcher.graphicengine import GraphicsEngine
from services.vdoprocessing.spatial_renderer.course import (
    _CourseOverviewMixin, _drawn_path, _pin_head_box, _Trace, dense_zooms, gl_view_state, zoom_view)
from services.vdoprocessing.spatial_renderer.popups import _PopupMixin

W, H = 1920, 1080


def _route():
    """A long straight run, then four stops packed into a small loop at its far end."""
    pts = [(100, 540), (1400, 540), (1500, 500), (1560, 560), (1500, 620), (1440, 560)]
    path, cum, total = _drawn_path(pts)
    anchors = [(2.0, 0.0), (20.0, total)]  # the trace runs the whole route from 2 s to 20 s
    return path, cum, anchors


def _stops(cum, idx):
    return [float(cum[i]) for i in idx]


def test_the_trace_zooms_in_on_a_tight_group_of_stops_only():
    path, cum, anchors = _route()
    (t_in, t_out, s, x0, y0), = dense_zooms(_stops(cum, [0, 1, 2, 3, 4]), path, cum, anchors, W, H)
    assert s == tuning.COURSE_DENSE_ZOOM_MAX
    assert 2.0 < t_in < t_out < 20.0
    w, h = W / s, H / s  # the crop shows every stop of the group and stays inside the frame
    assert 0 <= x0 and x0 + w <= W and 0 <= y0 and y0 + h <= H
    assert all(x0 <= x <= x0 + w and y0 <= y <= y0 + h for x, y in path[1:])


def test_a_small_route_in_a_roomy_frame_is_not_one_big_group():
    """The course map leaves room around the route for the badges: a route filling only the middle of the
    frame would fit at 1.5x as a whole. Only a group much smaller than the ROUTE zooms."""
    pts = [(700, 400), (900, 450), (1100, 500), (1200, 600)]  # evenly spread, small in the frame
    path, cum, _ = _drawn_path(pts)
    assert dense_zooms(_stops(cum, range(4)), path, cum, [(2.0, 0.0), (20.0, float(cum[-1]))], W, H) == []


def test_the_map_is_back_to_whole_once_the_trace_has_left():
    path, cum, anchors = _route()
    zooms = dense_zooms(_stops(cum, [1, 2, 3, 4]), path, cum, anchors, W, H)
    t_out = zooms[0][1]
    assert zoom_view(t_out, zooms, W, H) == zooms[0][2:]
    assert zoom_view(t_out + tuning.COURSE_DENSE_EASE_SECONDS + 0.01, zooms, W, H) is None


def test_the_gl_camera_shows_the_same_crop_the_frame_would():
    """A view's GL camera centres on the crop's middle and zooms in by its factor, so the real map lines up with
    the route drawn from the base frame's pixels."""
    from services.mapfetcher.mapgeometry import RouteGeometryProcessor, extent_for_view
    from services.mapfetcher.pydeck_overview import compute_pydeck_view

    bbox = {"min_lat": 34.24, "max_lat": 34.30, "min_lon": 135.02, "max_lon": 135.14}
    lon, lat, zoom, extent = compute_pydeck_view(bbox, (W, H))
    assert gl_view_state((1.0, 0.0, 0.0), extent, zoom, W, H) == pytest.approx((lon, lat, zoom))
    view = (1.5, 400.0, 200.0)
    c_lon, c_lat, c_zoom = gl_view_state(view, extent, zoom, W, H)
    assert c_zoom == pytest.approx(zoom + np.log2(1.5))
    # A point at base pixel (700, 500) shows at ((700-400)*1.5, (500-200)*1.5) in the zoomed GL frame.
    ext = extent_for_view(c_lon, c_lat, c_zoom, (W, H))
    p_lat, p_lon = 34.27, 135.07
    bx, by = RouteGeometryProcessor.project_latlon_to_pixel(p_lat, p_lon, extent, W, H)
    zx, zy = RouteGeometryProcessor.project_latlon_to_pixel(p_lat, p_lon, ext, W, H)
    assert (zx, zy) == pytest.approx(((bx - 400) * 1.5, (by - 200) * 1.5), abs=1.0)


def test_zoom_lets_go_before_the_trace_head_leaves_the_view():
    import numpy as np
    from services.vdoprocessing.spatial_renderer.course import release_zooms_before_exit

    path = np.array([[500.0, 500.0], [500.0, 100.0]])  # runs out of the 1.5x view that starts at (400, 300)
    cum = np.array([0.0, 400.0])
    anchors = [(0.0, 0.0), (10.0, 400.0)]
    (t_in, t_out, *_), = release_zooms_before_exit([(1.0, 8.0, 1.5, 400.0, 300.0)], path, cum, anchors, 1920, 1080)
    assert t_in == 1.0 and t_out < 8.0


class _Course(_CourseOverviewMixin, _PopupMixin):
    pass


def _course(cards, zooms):
    """A course renderer and scene holding `cards` (each already at its spot), with `zooms`; draws are stubbed."""
    course = _Course()
    course.config = {}
    course.graphics = SimpleNamespace(
        marker_radius=20, marker_color=(0, 0, 0), draw_path=lambda *a, **k: None,
        beside_card_footprint=lambda scale=1.0, **k: (int(210 * scale), int(170 * scale)))
    course._course_zooms = zooms
    scene = SimpleNamespace(
        on_route=cards, cards={c["index"]: c for c in cards}, laid_out=cards, extras=[], returns=set(), labels={},
        label_at={}, total_points=len(cards), fps=30, draw_marker=lambda *a, **k: None)
    return course, scene


def _card(index, x, y, stay_box, **extra):
    return {"index": index, "x": x, "y": y, "course_at": 5.0, "stay_box": stay_box, "stay_scale": 1.4, "data": {},
            **extra}


def _boxes(places):
    return [(x, y, x + int(210 * s), y + int(170 * s)) for x, y, s in places]


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


VIEW = (2.0, 480.0, 270.0)  # shows base x 480..1440, y 270..810


def test_a_zoomed_card_has_its_size_and_a_place_in_the_frame_and_the_whole_map_has_every_card_at_its_spot():
    inside, outside = _card(0, 900, 540, (100, 100)), _card(1, 100, 100, (300, 800))  # the second pin is off view
    course, scene = _course([inside, outside], [(4.0, 9.0, *VIEW)])
    x, y, sc = course._zoom_card_place(inside, scene, 6.0, VIEW, [], W, H)
    assert sc == 1.4 and 0 <= x <= W - int(210 * sc) and 0 <= y <= H - int(170 * sc)
    drawn = []
    course.graphics.render_popup_box = lambda frame, info, **k: drawn.append((info["index"], info["beside_box"])) or frame
    course._course_layer(scene, course._course_plate_state(scene, 12.0), np.zeros((H, W, 3), np.uint8))
    assert set(drawn) == {(0, (100, 100)), (1, (300, 800))}


def _zoomed_draws(t):
    """(course, scene, the (index, box, alpha) of every visible card draw in the zoomed frame at `t`)."""
    cards = [_card(0, 900, 540, (100, 100), course_at=1.0), _card(1, 100, 100, (300, 800), course_at=1.0)]
    course, scene = _course(cards, [(4.0, 9.0, *VIEW)])
    drawn = []

    def box(frame, info, alpha=1.0, **k):
        drawn.append((info["index"], info["beside_box"], alpha))
        return frame

    course.graphics.render_popup_box = box
    trace = _Trace(np.array([[0.0, 0.0], [10.0, 10.0]]), np.array([0.0, 14.0]), [(0, 0), (10, 10)],
                   ["walking", "walking"], (0, 0, 0), 4, 0)
    timing = SimpleNamespace(route_at=100.0, trace_end=200.0)
    course._course_zoomed_map(int(t * 30), t, VIEW, np.zeros((H, W, 3), np.uint8), scene,
                              course._course_plate_state(scene, t), trace, timing, None, 0, np.array([0.0, 0.0]))
    return course, scene, [d for d in drawn if d[2] > 0]


def test_fully_zoomed_only_a_card_whose_pin_is_in_view_shows_by_its_pin():
    course, scene, drawn = _zoomed_draws(6.0)
    x, y, _ = course._zoom_card_place(scene.cards[0], scene, 6.0, VIEW, [], W, H)
    assert {(i, b) for i, b, _ in drawn} == {(0, (x, y))}


def test_while_the_camera_starts_in_every_card_fades_out_at_its_own_spot():
    _, _, drawn = _zoomed_draws(3.4)  # a quarter of the way into the ease
    assert {(i, b) for i, b, _ in drawn} == {(0, (100, 100)), (1, (300, 800))}
    assert all(a < 1 for _, _, a in drawn)


def test_cards_up_together_while_zoomed_cover_no_card_and_no_pin():
    cards = [_card(i, 900 + 40 * i, 540 + 15 * i, (0, 0), course_at=5.0 + 0.3 * i) for i in range(4)]
    course, scene = _course(cards, [(4.0, 9.0, 1.0, 0.0, 0.0)])
    places = [course._zoom_card_place(c, scene, 6.0, (1.0, 0.0, 0.0), [], W, H) for c in cards]
    boxes = _boxes(places)
    for card in cards:
        pin = _pin_head_box(course.graphics, card["x"], card["y"])
        assert not any(_overlap(b, pin) for b in boxes)
    assert not any(_overlap(a, b) for i, a in enumerate(boxes) for b in boxes[:i])
    assert {p[2] for p in places} == {1.4}


@pytest.mark.parametrize("switch, during, after", [(True, (0, 1), (0, 1)), (False, (1,), (0, 1))])
def test_the_cards_stay_up_switch_closes_a_course_card_when_the_next_pops_and_brings_all_back(switch, during, after):
    cards = [_card(0, 900, 540, (100, 100), course_at=5.0), _card(1, 100, 100, (300, 800), course_at=9.0)]
    course, scene = _course(cards, [])
    course.config = {"overview_style": "course", "overview_cards_stay": switch}

    def shown(t):
        return course._course_plate_state(scene, t, None, 20.0)[0]

    assert shown(6.0) == (0,)
    assert shown(15.0) == during
    assert shown(20.5) == after  # the trace is done: every card, at its spot


def test_a_closing_course_card_is_up_long_enough_to_be_seen():
    cards = [_card(0, 900, 540, (100, 100), course_at=5.0), _card(1, 100, 100, (300, 800), course_at=5.2)]
    course, scene = _course(cards, [])
    course.config = {"overview_style": "course", "overview_cards_stay": False}
    assert course._course_plate_state(scene, 5.0 + tuning.COURSE_CARD_MIN_SECONDS - 0.5, None, 20.0)[0] == (0, 1)
    assert course._course_plate_state(scene, 5.0 + tuning.COURSE_CARD_MIN_SECONDS + 0.1, None, 20.0)[0] == (1,)


@pytest.mark.parametrize("pin", [(505, 600), (900, 400), (150, 420), (505, 20)])
def test_a_course_leader_is_unbroken_from_its_pin_to_the_card_as_drawn(tmp_path, pin):
    """The lines were cut under the card's LAYOUT box (room for a two-line name), so one coming from below stopped
    about 17 px short of a one-line card (2026-11-26)."""
    photo = tmp_path / "p.png"
    cv2.imwrite(str(photo), np.full((90, 160, 3), 60, np.uint8))
    card = {"index": 0, "x": pin[0], "y": pin[1], "course_at": 1.0, "stay_box": (400, 100), "stay_scale": 1.0,
            "label": "神島", "leader_straight": True, "border_color": (0, 0, 255), "data": {"popup_image": str(photo)}}
    course = _Course()
    course.config = {"overview_style": "course"}
    course.graphics = GraphicsEngine()
    scene = SimpleNamespace(on_route=[], cards={0: card}, laid_out=[card], extras=[], returns=set(), labels={},
                            label_at={}, total_points=1, fps=30, draw_marker=lambda *a, **k: None)
    background = np.full((H, W, 3), 230, np.uint8)
    keep, layer = course._course_overlay(scene, course._course_plate_state(scene, 5.0), background)
    frame = np.clip(background * keep + layer, 0, 255)
    x, y, cw, ch = course.graphics.popup_card_geometry(course._recap_cards([card])[0], W, H)
    end = (min(max(pin[0], x + 18), x + cw - 18), min(max(pin[1], y + 18), y + ch - 18))  # toward the rounded card
    length = math.dist(pin, end)
    for step in range(8, int(length)):
        px, py = (pin[i] + (end[i] - pin[i]) * step / length for i in (0, 1))
        if math.dist((px, py), end) <= 19:  # from here on it is the card itself
            break
        b, g, r = frame[int(round(py)), int(round(px))]
        assert r > 150 and g < 170, (round(px), round(py), (b, g, r))  # still the red line


def test_a_zoomed_card_keeps_off_the_route_beside_its_pin():
    """The route runs through the pin left to right: the card goes above or below it, still right by the pin, instead of
    on the line (第三砲台跡 and 友ヶ島 小展望台 covered the walk, 2026-11-24)."""
    card = _card(0, 900, 540, (0, 0))
    course, scene = _course([card], [(4.0, 9.0, 1.0, 0.0, 0.0)])
    course._course_route_px = np.array([[x, 540.0] for x in range(0, 1920, 6)])
    x, y, sc = course._zoom_card_place(card, scene, 6.0, (1.0, 0.0, 0.0), [], W, H)
    cw, ch = course.graphics.beside_card_footprint(sc)
    assert not (y <= 540 <= y + ch)  # off the line
    assert math.hypot(max(x - 900, 0, 900 - x - cw), max(y - 540, 0, 540 - y - ch)) <= 120  # and by its pin
