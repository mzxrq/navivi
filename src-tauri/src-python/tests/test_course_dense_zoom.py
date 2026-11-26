import numpy as np
import pytest

from services import tuning
from services.vdoprocessing.spatial_renderer.course import _drawn_path, dense_zooms, gl_view_state, zoom_view
from services.vdoprocessing.storyboard import of

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


def test_a_passing_card_hangs_at_its_pin_even_over_the_route():
    """The start's card went 300 px out over the water because any corner at its pin covered some route line.
    A corner at the pin wins; covering less route only decides between spots at the same distance."""
    from types import SimpleNamespace

    from services.vdoprocessing.spatial_renderer.course import _CourseOverviewMixin
    from services.vdoprocessing.spatial_renderer.popups import _PopupMixin

    class _Course(_CourseOverviewMixin, _PopupMixin):
        pass

    course = _Course()
    course.config = {}
    course.graphics = SimpleNamespace(marker_radius=20, beside_card_footprint=lambda *a, **k: (300, 240))
    stop = {"x": 960, "y": 540, "index": 0, "course_at": 1.0, "label": "S", "data": {}}
    # The route crosses the pin both ways, so every corner at the pin covers some of it.
    route = np.array([(x, 540) for x in range(0, 1920, 6)] + [(960, y) for y in range(0, 1080, 6)], dtype=float)
    course._course_pass_cards([stop], [stop], [], route, W, H)
    x, y = stop["pass_box"]
    cx, cy = x + 150, y + 120  # the card's middle sits within one card of the pin
    assert abs(cx - 960) <= 300 and abs(cy - 540) <= 240


def test_cards_of_stops_passed_in_quick_succession_shrink_and_do_not_overlap():
    from types import SimpleNamespace

    from services.vdoprocessing.spatial_renderer.course import _CourseOverviewMixin
    from services.vdoprocessing.spatial_renderer.popups import _PopupMixin

    class _Course(_CourseOverviewMixin, _PopupMixin):
        pass

    course = _Course()
    course.config = {}
    course.graphics = SimpleNamespace(
        marker_radius=20, beside_card_footprint=lambda scale=1.0, **k: (int(170 * scale), int(130 * scale)))
    stops = [{"x": 900 + 60 * i, "y": 540, "index": i, "course_at": 5.0 + 0.3 * i, "label": str(i), "data": {}}
             for i in range(3)]
    course._course_pass_cards(stops, stops, [], None, W, H)
    scales = {s["pass_scale"] for s in stops}
    assert len(scales) == 1 and scales.pop() < tuning.COURSE_PASS_CARD_SCALE  # one smaller size for the whole crowd
    assert all(s["pass_until"] - s["course_at"] >= of("course").timings["pass_card_min_seconds"] - 1e-9 for s in stops)
    boxes = [(*s["pass_box"], s["pass_box"][0] + int(170 * s["pass_scale"]), s["pass_box"][1] + int(130 * s["pass_scale"]))
             for s in stops]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert not (a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3])


def test_cards_up_together_share_one_size_and_a_lone_card_keeps_the_full_one():
    from services.vdoprocessing.spatial_renderer.course import pass_crowd_scales

    spans = [(1.0, 3.0), (5.0, 7.0), (5.5, 7.5), (6.0, 8.0), (20.0, 22.0)]  # lone, a crowd of three, lone
    s = pass_crowd_scales(spans, 2.0)
    assert s[0] == s[4] == 2.0
    assert s[1] == s[2] == s[3] == pytest.approx(2.0 / 3 ** 0.5)
    many = pass_crowd_scales([(t, t + 2.0) for t in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5)], 2.0)
    assert set(many) == {2.0 * tuning.COURSE_PASS_CARD_CROWD_MIN_SCALE}  # never below the floor


def test_a_passing_card_covers_no_pin_its_own_or_a_neighbours():
    from types import SimpleNamespace

    from services.vdoprocessing.spatial_renderer.course import _CourseOverviewMixin, _pin_head_box
    from services.vdoprocessing.spatial_renderer.popups import _PopupMixin

    class _Course(_CourseOverviewMixin, _PopupMixin):
        pass

    course = _Course()
    course.config = {}
    course.graphics = SimpleNamespace(marker_radius=20, beside_card_footprint=lambda scale=1.0, **k: (300, 240))
    stop = {"x": 960, "y": 540, "index": 0, "course_at": 1.0, "label": "S", "data": {}}
    neighbour = {"x": 1010, "y": 560, "index": 1, "course_at": 30.0, "label": "1", "data": {}}  # right beside it
    course._course_pass_cards([stop], [stop, neighbour], [], None, W, H)
    x, y = stop["pass_box"]
    for p in (stop, neighbour):
        b = _pin_head_box(course.graphics, p["x"], p["y"])
        assert not (x < b[2] and b[0] < x + 300 and y < b[3] and b[1] < y + 240)
    assert abs(x + 150 - 960) <= 400 and abs(y + 120 - 540) <= 340  # and still right by its own pin


def test_a_zoom_is_held_until_its_last_card_has_been_shown_in_full():
    from services.vdoprocessing.spatial_renderer.course import hold_zooms_for_cards

    zooms = [(10.0, 20.0, 1.5, 0.0, 0.0), (30.0, 40.0, 1.5, 0.0, 0.0)]
    # a card popped at 19.5 s shows until 22 s: the first zoom waits for it; a card of the second zoom shows to 45 s,
    # but is cut at the next zoom's own ease (none here); a card popped between the zooms holds neither
    held = hold_zooms_for_cards(zooms, [(19.5, 22.0), (35.0, 41.0), (25.0, 27.0)])
    shrink = tuning.COURSE_PASS_CARD_SHRINK_SECONDS  # held until the card has shrunk away, not just started to
    assert held[0][1] == pytest.approx(22.0 + shrink) and held[1][1] == pytest.approx(41.0 + shrink)
    # and never into the next zoom's ease
    squeezed = hold_zooms_for_cards(zooms, [(19.5, 29.5)])
    assert squeezed[0][1] <= zooms[1][0] - 2 * 0.8 + 1e-9
    assert hold_zooms_for_cards(zooms, []) == zooms


def test_zoom_lets_go_before_the_trace_head_leaves_the_view():
    import numpy as np
    from services.vdoprocessing.spatial_renderer.course import release_zooms_before_exit

    path = np.array([[500.0, 500.0], [500.0, 100.0]])  # runs out of the 1.5x view that starts at (400, 300)
    cum = np.array([0.0, 400.0])
    anchors = [(0.0, 0.0), (10.0, 400.0)]
    (t_in, t_out, *_), = release_zooms_before_exit([(1.0, 8.0, 1.5, 400.0, 300.0)], path, cum, anchors, 1920, 1080)
    assert t_in == 1.0 and t_out < 8.0


def test_a_card_hold_never_runs_the_zoom_out_past_the_trace_leaving_the_view():
    import numpy as np
    from services.vdoprocessing.spatial_renderer.course import (
        hold_zooms_for_cards, release_zooms_before_exit, zoom_exit_limits)

    path = np.array([[500.0, 500.0], [500.0, 100.0]])  # leaves the 1.5x view that starts at (400, 300) at about 4 s
    cum = np.array([0.0, 400.0])
    anchors = [(0.0, 0.0), (10.0, 400.0)]
    zooms = [(1.0, 2.0, 1.5, 400.0, 300.0)]
    limits = zoom_exit_limits(zooms, path, cum, anchors, 1920, 1080)
    released = release_zooms_before_exit(zooms, path, cum, anchors, 1920, 1080)
    held = hold_zooms_for_cards(released, [(1.5, 9.0)], limits)  # a card held to 9 s must not hold the zoom past the exit
    assert held[0][1] <= limits[0] + 1e-9
    assert held[0][1] < 9.0


def test_cards_up_together_while_zoomed_never_cover_each_other():
    """Around a tight cluster the eight spots beside one pin cannot hold several big cards: the later ones take the
    rings further out instead of the least-bad near spot (第三砲台跡 covered タカノス山, 2026-11-24)."""
    import math
    from types import SimpleNamespace

    from services.vdoprocessing.spatial_renderer.course import _CourseOverviewMixin
    from services.vdoprocessing.spatial_renderer.popups import _PopupMixin

    class _Course(_CourseOverviewMixin, _PopupMixin):
        pass

    course = _Course()
    course.config = {}
    full = tuning.COURSE_PASS_CARD_SCALE
    course.graphics = SimpleNamespace(
        marker_radius=20, beside_card_footprint=lambda scale=1.0, **k: (int(300 * scale / full), int(240 * scale / full)))
    cards = {}
    for i in range(4):
        cards[i] = {"x": 900 + 40 * i, "y": 540 + 15 * i, "index": i, "course_at": 5.0 + 0.3 * i,
                    "pass_box": (0, 0), "pass_scale": full, "pass_until": 8.0 + 0.3 * i}
    scene = SimpleNamespace(on_route=list(cards.values()), cards=cards)
    view = (1.0, 0.0, 0.0)
    sizes = set()
    course._course_zooms = [(4.0, 9.0, 1.0, 0.0, 0.0)]
    boxes = []
    for card in cards.values():
        x, y, sc = course._zoom_card_place(card, scene, 6.0, view, [], W, H)
        cw, ch = course.graphics.beside_card_footprint(sc)
        boxes.append((x, y, x + cw, y + ch))
        # right by its own pin (smaller in the crowd), not sent across the map (第三砲台跡 ended up far off once)
        gap = math.hypot(max(x - card["x"], 0, card["x"] - x - cw), max(y - card["y"], 0, card["y"] - y - ch))
        assert gap <= 90, gap  # just past the teardrop above or beside it
        sizes.add(sc)
    from services.vdoprocessing.spatial_renderer.course import _pin_head_box

    for card in cards.values():  # out around the group, so no card sits on any pin of it
        p = _pin_head_box(course.graphics, card["x"], card["y"])
        assert not any(b[0] < p[2] and p[0] < b[2] and b[1] < p[3] and p[1] < b[3] for b in boxes)
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert not (a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3])
    assert len(sizes) == 1  # one size for the whole zoom (a lone smaller card read as a mistake)


def test_a_card_still_up_at_the_zoom_out_is_gone_from_that_moment():
    """No card is left on the whole map: one popped in a zoom and still up when the camera zooms out is cut there
    (no shrink); one done in time, or popped outside any zoom, plays as usual."""
    from types import SimpleNamespace

    from services.vdoprocessing.spatial_renderer.course import _CourseOverviewMixin, cut_cards_at_zoom_out

    zoom = [(2.0, 5.0, 1.5, 0.0, 0.0)]
    late = {"index": 1, "course_at": 4.5, "pass_until": 7.0}
    done = {"index": 2, "course_at": 2.5, "pass_until": 3.0}
    outside = {"index": 3, "course_at": 9.0, "pass_until": 11.0}
    cut_cards_at_zoom_out([late, done, outside], zoom)
    assert late["pass_cut"] == 5.0 and "pass_cut" not in done and "pass_cut" not in outside

    scene = SimpleNamespace(laid_out=[late], on_route=[], extras=[], fps=30)
    state = _CourseOverviewMixin._course_plate_state(SimpleNamespace(), scene, 5.2)
    shown, passing = state[0], state[5]
    assert shown == (1,) and passing == ()  # its badge, no card and no shrink

    # popped once the zoom-out has begun: never shown on the whole map either
    during = {"index": 6, "course_at": 5.2, "pass_until": 7.0}
    cut_cards_at_zoom_out([during], zoom)
    assert during["pass_cut"] == 5.2


def test_a_zoomed_card_keeps_off_the_route_beside_its_pin():
    """The route runs through the pin left to right: the card goes above or below it, still right by the pin, instead of
    on the line (第三砲台跡 and 友ヶ島 小展望台 covered the walk, 2026-11-24)."""
    import math
    from types import SimpleNamespace

    import numpy as np

    from services.vdoprocessing.spatial_renderer.course import _CourseOverviewMixin
    from services.vdoprocessing.spatial_renderer.popups import _PopupMixin

    class _Course(_CourseOverviewMixin, _PopupMixin):
        pass

    course = _Course()
    course.config = {}
    full = tuning.COURSE_PASS_CARD_SCALE
    course.graphics = SimpleNamespace(
        marker_radius=20, beside_card_footprint=lambda scale=1.0, **k: (int(300 * scale / full), int(240 * scale / full)))
    course._course_route_px = np.array([[x, 540.0] for x in range(0, 1920, 6)])
    card = {"x": 900, "y": 540, "index": 0, "course_at": 5.0, "pass_box": (0, 0), "pass_scale": full, "pass_until": 8.0}
    scene = SimpleNamespace(on_route=[card], cards={0: card})
    course._course_zooms = [(4.0, 9.0, 1.0, 0.0, 0.0)]
    x, y, sc = course._zoom_card_place(card, scene, 6.0, (1.0, 0.0, 0.0), [], W, H)
    assert sc == full  # alone: full size
    assert not (y <= 540 <= y + 240)  # off the line
    assert math.hypot(max(x - 900, 0, 900 - x - 300), max(y - 540, 0, 540 - y - 240)) <= 120  # and by its pin
