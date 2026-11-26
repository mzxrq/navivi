import math
from types import SimpleNamespace

import numpy as np
import pytest

from services import tuning
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


def test_zoomed_cards_keep_their_size_and_stay_in_the_frame_then_return_to_their_spots():
    inside, outside = _card(0, 900, 540, (100, 100)), _card(1, 100, 100, (300, 800))  # the second pin is off view
    course, scene = _course([inside, outside], [(4.0, 9.0, *VIEW)])
    places = [course._zoom_card_place(c, scene, 6.0, VIEW, [], W, H) for c in (inside, outside)]
    assert [p[2] for p in places] == [1.4, 1.4]
    assert all(0 <= x0 and x1 <= W and 0 <= y0 and y1 <= H for x0, y0, x1, y1 in _boxes(places))
    assert not _overlap(*_boxes(places))
    drawn = []
    course.graphics.render_popup_box = lambda frame, info, **k: drawn.append((info["index"], info["beside_box"])) or frame
    course._course_layer(scene, course._course_plate_state(scene, 12.0), np.zeros((H, W, 3), np.uint8))
    assert set(drawn) == {(0, (100, 100)), (1, (300, 800))}


def test_the_zoomed_map_moves_every_card_up_to_its_zoomed_place():
    cards = [_card(0, 900, 540, (100, 100)), _card(1, 100, 100, (300, 800))]
    course, scene = _course(cards, [(4.0, 9.0, *VIEW)])
    drawn = []
    course.graphics.render_popup_box = lambda frame, info, **k: drawn.append((info["index"], info["beside_box"])) or frame
    trace = _Trace(np.array([[0.0, 0.0], [10.0, 10.0]]), np.array([0.0, 14.0]), [(0, 0), (10, 10)],
                   ["walking", "walking"], (0, 0, 0), 4, 0)
    timing = SimpleNamespace(route_at=100.0, trace_end=200.0)
    course._course_zoomed_map(180, 6.0, VIEW, np.zeros((H, W, 3), np.uint8), scene,
                              course._course_plate_state(scene, 6.0), trace, timing, None, 0, np.array([0.0, 0.0]))
    assert set(drawn) == {(c["index"], course._zoom_card_place(c, scene, 6.0, VIEW, [], W, H)[:2]) for c in cards}


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
