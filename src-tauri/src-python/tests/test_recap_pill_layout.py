"""The recap's pill-badge layout: near pins share one leader line, drawn
from their shared point without moving either pin."""

from types import SimpleNamespace

from services.vdoprocessing.spatial_renderer.pins import _PinMixin
from services.vdoprocessing.spatial_renderer.popups import _PopupMixin


class _Layout(_PopupMixin, _PinMixin):
    _is_loop_route = False  # the real renderer reads it from the project (base.py)


def _layout():
    layout = _Layout()
    layout.config = {}
    layout.graphics = SimpleNamespace(
        marker_radius=20,
        beside_card_footprint=lambda *a, **k: (34, 180),
    )
    return layout


def _popup(x, y, label, order):
    return {"x": x, "y": y, "label": label, "order": order, "data": {"popup_image": "p.jpg"}}


def test_near_pins_share_one_leader_line():
    near_a, near_b = _popup(900, 600, "AB", 1), _popup(915, 606, "CD", 2)
    far = _popup(1500, 300, "EF", 3)
    laid = _layout()._layout_recap_cards([near_a, near_b, far], 1920, 1080)
    assert len(laid) == 3
    drawn = [p for p in (near_a, near_b) if not p.get("suppress_leader_line")]
    assert len(drawn) == 1
    assert not far.get("suppress_leader_line")  # a pin on its own keeps its own line


def test_the_shared_line_does_not_move_either_pin():
    near_a, near_b = _popup(900, 600, "AB", 1), _popup(915, 606, "CD", 2)
    _layout()._layout_recap_cards([near_a, near_b], 1920, 1080)
    for popup, spot in ((near_a, (900, 600)), (near_b, (915, 606))):
        assert (popup.get("pin_x", popup["x"]), popup.get("pin_y", popup["y"])) == spot
    shared = next(p for p in (near_a, near_b) if not p.get("suppress_leader_line"))
    assert shared["leader_from"] == (907.5, 603.0)  # the pair's own midpoint


def _card_layout():
    """A layout whose badge is 34x180 and whose full photo card is 210x190."""
    layout = _layout()
    layout.graphics.beside_card_footprint = (
        lambda card_scale=1.0, has_label=True, is_pill_badge=False,
        pill_name_chars=None, pill_scale=1.0: (34, 180) if is_pill_badge else (210, 190)
    )
    return layout


def test_the_walks_card_never_carries_the_recaps_badge_styling():
    """_layout_recap_cards stamps the badge style onto these dicts before the
    walk even starts, so any frame that builds a card straight from one draws
    a badge — every card on screen blinked into one on each arrival frame."""
    popup = {
        "x": 400, "y": 700, "order": 1, "label": "AB", "data": {"popup_image": "p.jpg"},
        "stay_box": (500, 300), "stay_scale": 1.0, "beside_box": (500, 300),
        "is_pill_badge": True, "suppress_leader_line": True, "leader_from": (1, 2),
    }
    hud = _card_layout().walk_card_hud(popup, 1920, 1080, None, lambda p: [])
    assert not any(hud.get(k) for k in ("is_pill_badge", "suppress_leader_line", "leader_from"))
    assert hud["draw_leader_line"] and hud["beside_box"] == popup["stay_box"]
    assert popup["is_pill_badge"]  # the popup itself still carries it, for the recap


def test_a_staying_card_fades_in_without_moving():
    """It is wired to its pin by a leader line, so it may not slide or grow
    into place — the line would sweep along with it."""
    import numpy as np

    seen = []
    layout = _card_layout()
    layout.graphics.render_popup_box = lambda frame, info, **kw: (
        seen.append((info.get("beside_box"), round(info.get("card_scale", 1.0), 3)))
        if not kw.get("line_only") else None
    ) or frame
    total = 3600 * 30
    bp = {
        "popup": {
            "x": 400, "y": 700, "order": 1, "label": "AB",
            "data": {"popup_image": "p.jpg"},
            "stay_box": (500, 300), "stay_scale": 1.0, "beside_box": (500, 300), "is_pill_badge": True,
        },
        "total_frames": total, "frames_left": total, "fade_frames": 9,
    }
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    live = [bp]
    for _ in range(14):
        _, live = layout._composite_baked_popups(
            frame, live, 1920, 1080, None, active_popups=[], total_points=3, fps=30,
        )
    assert len(set(seen)) == 1  # same spot, same size, every frame of its entrance


def test_a_card_stays_a_card_for_the_whole_walk():
    """No stop turns into its badge while the walk is still running — they all
    do that together at the recap (see _render_recap_and_summary)."""
    import numpy as np

    drawn = []
    layout = _card_layout()
    layout.graphics.render_popup_box = lambda frame, info, **kw: (
        drawn.append("pill" if info.get("is_pill_badge") else "card")
        if not kw.get("line_only") else None
    ) or frame
    fps, total = 30, 3600 * 30
    bps = [
        {
            "popup": {
                "x": 400, "y": 700, "order": i, "label": f"P{i}",
                "data": {"popup_image": "p.jpg"},
                "stay_box": (400 + i * 400, 300), "stay_scale": 1.0, "beside_box": (400 + i * 400, 300),
                "is_pill_badge": True,  # the recap's own layout stamped this up front
            },
            "total_frames": total, "frames_left": total, "fade_frames": 9,
        }
        for i in range(2)
    ]
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    live = []
    for n in range(130):
        if n in (0, 18):
            live.append(bps[n // 18])
        drawn.clear()
        _, live = layout._composite_baked_popups(
            frame, live, 1920, 1080, None, active_popups=[], total_points=4, fps=fps,
        )
        assert "pill" not in drawn


def test_every_badge_is_the_same_width_whatever_its_name():
    short, long_name = _popup(400, 400, "A", 1), _popup(1400, 700, "A" * 12, 2)
    _layout()._layout_recap_cards([short, long_name], 1920, 1080)
    assert short["is_pill_badge"] and long_name["is_pill_badge"]
    assert "pill_scale" not in short and "pill_scale" not in long_name


def test_near_pins_get_neighbouring_slots():
    """Two stops a few metres apart share one leader line, so the member
    that draws none can only be read by what it sits beside: their badges
    have to end up next to each other. The pins are a real 11-stop route
    (katsuragi no michi) on which the old two-slots-per-card quota left the
    pair with no free slot of their own, stranding one across the frame
    beside a stop it has nothing to do with."""
    import math

    import numpy as np

    pins = [
        (186, 933), (743, 975), (745, 937), (618, 730), (1088, 941), (625, 462),
        (632, 197), (626, 151), (1251, 105), (1734, 212), (1720, 309),
    ]
    route = np.array(
        [
            (a[0] + (b[0] - a[0]) * t / 40.0, a[1] + (b[1] - a[1]) * t / 40.0)
            for a, b in zip(pins, pins[1:])
            for t in range(40)
        ]
    )
    pops = [_popup(x, y, "stop%d" % i, i + 1) for i, (x, y) in enumerate(pins)]
    layout = _layout()
    cw, ch = 60, 260  # a Japanese name's badge, the size that showed the bug
    layout.graphics.beside_card_footprint = lambda *a, **k: (cw, ch)
    laid = layout._layout_recap_cards(
        pops, 1920, 1080,
        reserved_boxes=[(1920 - 380, 1080 - 220, 1900.0, 1060.0)],
        route_obstacles=route,
    )
    assert len(laid) == len(pops)

    from services.vdoprocessing.spatial_renderer.popups import _PopupMixin

    pair = pops[1], pops[2]  # 38 px apart — the pair that shares a leader
    (ax, ay), (bx, by) = (p["beside_box"] for p in pair)
    # Neighbouring cells of the one lattice every badge sits on, nothing between them: one
    # badge's width plus whichever gap that lattice was cut at (see _layout_recap_cards).
    gaps = (_PopupMixin._RECAP_CARD_GAP, _PopupMixin._RECAP_BADGE_GAP)
    assert ay == by and abs(ax - bx) in {cw + g for g in gaps}

    # ...and no other badge is packed against them, or the pair stops reading
    # as a pair (寺田橋バス停, a kilometre up the road, was sitting right there).
    room = (cw + _PopupMixin._RECAP_BADGE_GAP) * 0.9
    for other in pops:
        if other in pair:
            continue
        assert min(math.dist(other["beside_box"], p["beside_box"]) for p in pair) > room

    # ...and each of the two takes the nearer of their two slots, so they
    # don't end up on opposite sides of their own pins.
    a, b = ((p["beside_box"][0] + cw / 2, p["beside_box"][1] + ch / 2) for p in pair)
    pins_of_pair = [(p["x"], p["y"]) for p in pair]

    def total(first, second):  # the matching's own measure: slot centre to pin, squared
        return (
            math.dist(first, pins_of_pair[0]) ** 2 + math.dist(second, pins_of_pair[1]) ** 2
        )

    assert total(a, b) <= total(b, a)


def _mixed_route():
    """Eight numbered stops across the frame with four stop-bys among the
    right-hand half of them — the shape that puts a stop-by's badge between
    two stops' badges, where it reads as one of them."""
    pops = [_popup(200 + i * 180, 520, "stop%d" % i, i + 1) for i in range(8)]
    for i in range(4):
        p = _popup(1000 + i * 150, 640, "near%d" % i, 20 + i)
        p["data"]["is_stopby"] = True
        pops.append(p)
    return pops


def test_a_leader_over_the_route_is_seen_as_such():
    """The grid the layout scores leader lines against (a slot whose line
    would run over the route is treated as much further away)."""
    import numpy as np

    from services.vdoprocessing.spatial_renderer.popups import (
        _ROUTE_CROSS_TOLERANCE_PX, _route_cells, _segment_hits_route,
    )

    route = np.array([[900.0, y] for y in range(200, 900, 4)])  # a wall down the middle
    cell = _ROUTE_CROSS_TOLERANCE_PX
    grid, gw, gh = _route_cells(route[:, 0], route[:, 1], cell)
    assert _segment_hits_route(grid, gw, gh, cell, 700, 500, 1100, 500)  # straight through
    assert not _segment_hits_route(grid, gw, gh, cell, 700, 500, 860, 520)  # stays left
    assert not _segment_hits_route(grid, gw, gh, cell, 700, 100, 1100, 120)  # above its top


def test_a_stop_near_a_pair_is_not_packed_flush_against_it():
    """Two stops that share a leader line read as a pair only if the next
    stop along keeps its distance — packed flush it looks like one of them.
    (中村家住宅 and 郵便名柄館 are the pair; 寺田橋バス停, a kilometre
    up the road, was sitting right against them.)"""
    import math

    near_a, near_b = _popup(900, 600, "AB", 1), _popup(915, 606, "CD", 2)
    along = _popup(980, 606, "EF", 3)  # just outside the pair's own link distance
    further = _popup(1050, 606, "GH", 4)
    layout = _layout()
    layout._layout_recap_cards([near_a, near_b, along, further], 1920, 1080)
    assert not along.get("suppress_leader_line")  # it is not one of the pair

    cw, ch = 34, 180

    def centre(p):
        return p["beside_box"][0] + cw / 2, p["beside_box"][1] + ch / 2

    # One slot pitch (58 px) would be flush; the cluster keeps more than that clear.
    assert min(math.dist(centre(along), centre(p)) for p in (near_a, near_b)) > 100


def test_no_leader_is_drawn_over_the_route_while_a_clear_slot_is_free():
    """Keeping off the route is a rule, not a preference: a badge takes a
    further slot rather than have its leader run across the line. Six stops
    crowded along one side of a straight stretch — on the shortest-leader
    placement alone, one of them reaches across it."""
    import numpy as np

    from services.vdoprocessing.spatial_renderer.popups import (
        _ROUTE_CROSS_TOLERANCE_PX, _anchor_point, _leader_over_route, _route_cells,
    )

    route = np.array([[960.0, y] for y in range(100, 980, 4)])
    pins = [(990, 200), (990, 400), (990, 600), (990, 800), (930, 300), (930, 500)]
    pops = [_popup(x, y, "s%d" % i, i + 1) for i, (x, y) in enumerate(pins)]
    layout = _layout()
    laid = layout._layout_recap_cards(pops, 1920, 1080, route_obstacles=route)
    assert len(laid) == len(pops)

    cell = _ROUTE_CROSS_TOLERANCE_PX
    grid, gw, gh = _route_cells(route[:, 0], route[:, 1], cell)
    skip = layout.graphics.marker_radius + cell
    cw, ch = 34, 180
    over = [
        p["label"] for p in pops
        if _leader_over_route(
            p["x"], p["y"], *_anchor_point(p["x"], p["y"], *p["beside_box"], cw, ch),
            grid, gw, gh, cell, skip,
        )
    ]
    assert not over


def test_a_stop_and_a_stopby_at_the_same_spot_are_not_a_pair():
    """A group is one kind only: a stop-by sitting on top of a numbered stop
    is not its pair, so they neither touch nor share a leader line."""
    stop = _popup(900, 600, "AB", 1)
    side = _popup(908, 604, "CD", 2)
    side["data"]["is_stopby"] = True
    _layout()._layout_recap_cards([stop, side], 1920, 1080)
    assert not stop.get("suppress_leader_line")
    assert not side.get("suppress_leader_line")  # each draws its own


def test_a_badge_rests_against_its_own_stop_even_on_the_route_line():
    """Every stop SITS on the route, so keeping badges off the line left no slot beside a pin at
    all on a route that hugs a coast: each badge went to the nearest open space instead - across
    the water - and the frame filled with long crossing leaders."""
    import math

    import numpy as np

    route = np.array([[x, 540.0] for x in range(100, 1800, 4)])
    pop = _popup(600, 540, "AB", 1)
    layout = _layout()
    assert len(layout._layout_recap_cards([pop], 1920, 1080, route_obstacles=route)) == 1
    bx, by = pop["beside_box"]
    cw, ch = 34, 180
    assert math.hypot(bx + cw / 2 - 600, by + ch / 2 - 540) <= ch * layout._BADGE_BESIDE_PIN


def test_badges_line_up_on_one_grid():
    """Badges all come off the same frame-wide lattice, so however they are matched their tops
    and left edges line up instead of sitting at whatever spot each pin happened to spiral into."""
    pops = [_popup(300 + 120 * i, 400 + 37 * i, "s%d" % i, i + 1) for i in range(6)]
    laid = _layout()._layout_recap_cards(pops, 1920, 1080)
    assert len(laid) == 6
    tops = {int(p["beside_box"][1]) for p in pops}
    lefts = sorted({int(p["beside_box"][0]) for p in pops})
    assert len(tops) <= 2  # one or two shared rows, not six different heights
    pitches = {lefts[i + 1] - lefts[i] for i in range(len(lefts) - 1)}
    assert all(p % 89 == 0 for p in pitches)  # 34px badge + _RECAP_BADGE_GAP


def test_a_run_of_touching_badges_never_mixes_kinds():
    """A block of badges sitting side by side shows its stops first, then its stop-bys: a
    stop-by between two numbered stops reads as one of them. Only badges that actually touch
    are ordered — an empty cell ends the run, so nothing travels the frame to join its kind.
    Stops and stop-bys interleaved along one stretch of route."""
    pops = []
    for i in range(8):
        p = _popup(260 + 100 * i, 520, "s%d" % i, i + 1)
        if i % 2:
            p["data"]["is_stopby"] = True
        pops.append(p)
    laid = _layout()._layout_recap_cards(pops, 1920, 1080)
    assert len(laid) == 8

    placed = sorted(pops, key=lambda p: (p["beside_box"][1], p["beside_box"][0]))
    xs = sorted({p["beside_box"][0] for p in pops})
    pitch = min((b - a for a, b in zip(xs, xs[1:])), default=1)
    run, runs = [], []
    for p in placed:
        if run and (p["beside_box"][1] != run[-1]["beside_box"][1]
                    or p["beside_box"][0] - run[-1]["beside_box"][0] > pitch):
            runs.append(run)
            run = []
        run.append(p)
    runs.append(run)
    assert any(len(r) > 1 for r in runs)  # they do pack together, or this proves nothing
    for r in runs:
        kinds = [bool(p["data"].get("is_stopby")) for p in r]
        assert kinds == sorted(kinds)  # every stop before every stop-by, never alternating


def test_a_badge_prefers_the_clear_half_of_the_map():
    """Of two cells about as far from the pin, the badge takes the one over flat map (open
    water, a quiet block) rather than the one over coastline, roads and place names."""
    import numpy as np

    rng = np.random.default_rng(0)
    background = np.full((1080, 1920, 3), 200, dtype=np.uint8)  # flat...
    background[:, 960:] = rng.integers(0, 255, (1080, 960, 3), dtype=np.uint8)  # ...busy right
    pop = _popup(960, 540, "AB", 1)
    laid = _layout()._layout_recap_cards([pop], 1920, 1080, background=background)
    assert len(laid) == 1
    assert pop["beside_box"][0] + 34 <= 960  # wholly on the flat side


def test_the_recap_draws_no_leader_lines():
    """The recap ties a badge to its stop by the number they share, not by a line: with
    leaders off nothing is kept clear for a line and every badge is marked to draw none."""
    pops = [_popup(300 + 90 * i, 500, "s%d" % i, i + 1) for i in range(5)]
    laid = _layout()._layout_recap_cards(pops, 1920, 1080, leaders=False)
    assert len(laid) == 5
    assert all(p.get("suppress_leader_line") for p in pops)
    assert not any(p.get("leader_via") or p.get("leader_from") for p in pops)


def test_the_course_style_badge_draws_no_leader_line():
    """Changing the video style doesn't change how pill badges are arranged: the course
    style lays its badges out leaderless too, and its per-frame hud honours that."""
    from services.vdoprocessing.spatial_renderer.course import _CourseOverviewMixin

    class _Course(_CourseOverviewMixin, _Layout):
        pass

    course = _Course()
    course.config = {}
    course.graphics = _layout().graphics
    course.graphics.marker_color = (0, 0, 0)
    pops = [_popup(300 + 90 * i, 500, "s%d" % i, i + 1) for i in range(4)]
    course._layout_recap_cards(pops, 1920, 1080, leaders=False)
    assert not any(course._course_hud(p)["draw_leader_line"] for p in pops)


def test_a_reserved_box_at_the_top_only_shortens_its_columns():
    """A box over the top of the badge band (the course style's headline, as wide as its
    longest line) must not cost its columns every row: that left the whole left half of
    the frame with no cell at all and crowded every badge into the right-hand columns."""
    layout = _layout()
    head = [(0.0, 0.0, 960.0, 150.0)]  # the headline, half the frame wide
    with_head = layout._recap_card_slots(1920, 1080, 34, 283, head)
    assert [x for x, _ in with_head if x < 960]
    assert len(with_head) > len(layout._recap_card_slots(1920, 1080, 34, 283, None)) / 2


def test_clear_space_moves_a_badge_but_only_within_reach():
    """The clear-space pull breaks ties nearby — the course style leans on it hard, since its
    map is never faded — but it can never drag a badge out of its own pin's neighbourhood:
    on a loop whose start sits apart from the stops around it, that split the block in two."""
    import numpy as np

    rng = np.random.default_rng(0)
    layout = _layout()

    near = np.full((1080, 1920, 3), 200, dtype=np.uint8)
    near[:, :700] = rng.integers(0, 255, (1080, 700, 3), dtype=np.uint8)  # busy left of the pin
    pop = _popup(700, 540, "AB", 1)
    busy = []
    for pull in (0.0, 2000.0):
        layout._layout_recap_cards([pop], 1920, 1080, background=near, clutter_pull=pull)
        busy.append(layout._clutter_cost(near, [pop["beside_box"]], 34, 180)[0])
    assert busy[1] < busy[0]  # quiet map a short step away: worth taking

    far = rng.integers(0, 255, (1080, 1920, 3), dtype=np.uint8)
    far[:, 1600:] = 200  # the only quiet map is right across the frame
    pop = _popup(300, 540, "AB", 1)
    layout._layout_recap_cards([pop], 1920, 1080, background=far, clutter_pull=2000.0)
    assert pop["beside_box"][0] < 300 + layout._CLUTTER_REACH_PX


def _ring_layout():
    """A layout whose card is 200x150 at scale 1.0 and shrinks with the scale."""
    layout = _layout()
    layout.graphics.beside_card_footprint = (
        lambda card_scale=1.0, **k: (int(200 * card_scale), int(150 * card_scale))
    )
    return layout


def _boxes(placed, layout):
    out = []
    for p in placed:
        bx, by = p["beside_box"]
        cw, ch = layout.graphics.beside_card_footprint(p["card_scale"])
        out.append((bx, by, bx + cw, by + ch))
    return out


def test_a_staying_card_sits_against_its_own_pin():
    """Cards that stay up through the walk ring their own pin instead of lining up at the
    edge of the frame — so none of them needs a leader line across the map."""
    import math

    layout = _ring_layout()
    pops = [_popup(400 + 320 * i, 540, "s%d" % i, i + 1) for i in range(4)]
    placed = layout._layout_ring_cards(pops, 1920, 1080)
    assert len(placed) == 4
    for p, (x0, y0, x1, y1) in zip(placed, _boxes(placed, layout)):
        reach = math.hypot((x0 + x1) / 2 - p["x"], (y0 + y1) / 2 - p["y"])
        assert reach < max(x1 - x0, y1 - y0)  # beside the pin, not across the frame


def test_every_staying_card_is_the_same_size():
    """One size for the whole set, the largest that places all of them: a stop's photo bigger
    than its neighbour's, for no reason a viewer can see, reads as a mistake. They never land
    on each other or on a reserved panel either."""
    layout = _ring_layout()
    hud = [(0.0, 0.0, 600.0, 140.0)]
    pops = [_popup(900 + 40 * i, 500 + 30 * (i % 3), "s%d" % i, i + 1) for i in range(14)]
    placed = layout._layout_ring_cards(pops, 1920, 1080, reserved_boxes=hud)
    assert len(placed) == 14
    assert len({p["card_scale"] for p in placed}) == 1
    boxes = _boxes(placed, layout)
    for i, a in enumerate(boxes):
        assert not (a[0] < hud[0][2] and hud[0][0] < a[2] and a[1] < hud[0][3] and hud[0][1] < a[3])
        for b in boxes[i + 1:]:
            assert not (a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3])


def test_the_start_badge_keeps_the_cell_nearest_its_pin():
    """Stops on both sides of the start (on a loop, also where the route ends) used to share out
    the cells beside it in the matching, and the start's badge was sent to the end of the row."""
    start = dict(_popup(1640, 560, "S", 0), index=0)
    crowd = [dict(_popup(x, 560, f"N{k}", k + 1), index=10 * (k + 1))
             for k, x in enumerate((1430, 1500, 1570, 1710, 1780, 1850))]
    laid = _layout()._layout_recap_cards([start] + crowd, 1920, 1080, leaders=False)
    centre = start["beside_box"][0] + 17
    assert all(abs(centre - 1640) <= abs(p["beside_box"][0] + 17 - 1640) for p in laid)


def test_the_start_badge_never_splits_a_row_of_stop_bys():
    """The start among stop-bys on both sides: it moves to the end of their block, so they stay together."""
    start = dict(_popup(1640, 560, "S", 0), index=0)
    sides = []
    for k, x in enumerate((1430, 1500, 1570, 1710, 1780, 1850)):
        p = dict(_popup(x, 560, f"B{k}", k + 1), index=10 * (k + 1))
        p["data"]["is_stopby"] = True
        sides.append(p)
    _layout()._layout_recap_cards([start] + sides, 1920, 1080, leaders=False)
    row = sorted((p for p in [start] + sides if p["beside_box"][1] == start["beside_box"][1]),
                 key=lambda p: p["beside_box"][0])
    assert len(row) > 2 and row.index(start) in (0, len(row) - 1)


def test_a_badge_leaves_a_dense_route_loop_clear():
    """Beside its pin a badge may rest on the line, but of two cells it takes the one that leaves it clear."""
    import numpy as np

    loop = np.array([[900 + 60 * np.cos(a), 600 + 60 * np.sin(a)] for a in np.linspace(0, 6.28, 300)])
    pin = _popup(900, 600, "AB", 1)
    _layout()._layout_recap_cards([pin], 1920, 1080, route_obstacles=loop, leaders=False)
    bx, by = pin["beside_box"]
    covered = (loop[:, 0] >= bx) & (loop[:, 0] <= bx + 34) & (loop[:, 1] >= by) & (loop[:, 1] <= by + 180)
    assert not covered.any()


def test_a_far_badge_brings_back_its_pins_number():
    calls = []
    layout = _layout()
    layout._draw_pin = lambda frame, wp, total, scale=1.0: calls.append("pin")
    layout._draw_recap_dot(None, {"x": 1, "y": 1, "badge_far": True, "data": {}}, 3)
    assert calls == ["pin"]


def test_a_numbered_pin_wears_its_badges_color_and_a_start_badge_the_start_pins():
    from services import tuning

    start = dict(_popup(300, 300, "S", 0), index=0)
    stops = [dict(_popup(700 + 200 * k, 500, f"N{k}", k + 1), index=10 * (k + 1)) for k in range(3)]
    laid = _layout()._layout_recap_cards([start] + stops, 1920, 1080, leaders=False, total_points=31)
    for p in laid:
        if p is start:
            assert tuple(p["recap_line_color"]) == tuple(tuning.START_PIN_COLOR) and "pin_color" not in p
        elif p is stops[-1]:  # the highest index is the route's end: the badge takes the E pin's red
            assert tuple(p["recap_line_color"]) == tuple(tuning.END_PIN_COLOR)
        else:
            assert p["pin_color"] == p["recap_line_color"]
            assert _layout()._pin_label_and_color(p, 100)[1] == p["recap_line_color"]


def test_on_a_loop_the_last_badge_is_a_numbered_stop_not_the_end():
    """A loop route's E has no badge of its own (it shares S's), so the last badge is a numbered stop."""
    start = dict(_popup(300, 300, "S", 0), index=0)
    stops = [dict(_popup(700 + 200 * k, 500, f"N{k}", k + 1), index=10 * (k + 1)) for k in range(3)]
    _layout()._layout_recap_cards([start] + stops, 1920, 1080, leaders=False, total_points=41)  # E is index 40
    assert stops[-1]["pin_color"] == stops[-1]["recap_line_color"]


def test_a_badge_stranded_across_the_route_comes_back_beside_its_pin():
    """The lattice cell is as tall as the longest name, so a stop in tight water can be left a badge across the route from
    it. That badge moves to clear space beside the pin; a badge merely far away (no route between) keeps its grid cell."""
    import numpy as np

    from services.vdoprocessing.spatial_renderer.popups import _RecapCardsGeom

    route = np.array([[x, 400.0] for x in range(0, 1900, 6)])  # a line between the pin and its badge
    pin = (300.0, 600.0)
    layout = _layout()

    def run(obstacles, kind=1):
        geom = _RecapCardsGeom([(1000, 60)], 34, 180, False, obstacles, 20)
        geom.card_hs = [180]
        slot_for = [0]
        layout._recap_cards_pull_in(geom, slot_for, [pin], set(), [kind], 1920, 1080, [], obstacles)
        return geom.slots[slot_for[0]]

    x, y = run(route)  # a stop-by
    assert abs(x + 17 - pin[0]) < 150 and abs(y + 90 - pin[1]) < 200
    assert not np.any((route[:, 0] >= x) & (route[:, 0] <= x + 34) & (route[:, 1] >= y) & (route[:, 1] <= y + 180))
    assert run(None) == (1000, 60)  # nothing between them: stays on the grid
    assert run(route, kind=0) == (1000, 60)  # a numbered stop keeps its place in the S, 1, 2 … run


def test_a_nudged_pin_slides_along_the_route_not_off_it():
    """Two stops a few px apart on one line are pushed apart ALONG it: pushed sideways (up to 1.5 radii), a pin read as
    unconnected to the route it sits on. A stop-by well off the route is still nudged freely."""
    import numpy as np

    route = np.array([[x, 500.0] for x in range(100, 900, 5)])
    a, b = _popup(400, 500, "a", 1), _popup(410, 500, "b", 2)
    near, off = _popup(300, 700, "n", 3), _popup(306, 700, "o", 4)  # 200 px off the route
    layout = _layout()
    layout._declutter_pins([a, b, near, off], route=route)
    assert abs(a["pin_y"] - 500) < 1 and abs(b["pin_y"] - 500) < 1
    assert b["pin_x"] - a["pin_x"] > 10  # still moved apart
    assert abs(off["pin_x"] - near["pin_x"]) > 6  # off the route: nudged as before


def test_a_closed_place_the_route_loops_around_still_gets_its_badge_beside_it():
    """神島: with no route-free spot anywhere near, the closed place's badge rests on the line beside its own pin
    (still off every pin) instead of staying across the map."""
    import numpy as np

    from services.vdoprocessing.spatial_renderer.popups import _RecapCardsGeom

    route = np.array([[x, y] for y in range(100, 1000, 40) for x in range(0, 1900, 6)], dtype=float)  # lines everywhere
    pin, other_pin = (300.0, 600.0), (300.0, 420.0)
    geom = _RecapCardsGeom([(1000, 60), (1400, 60)], 34, 180, False, route, 20)
    geom.card_hs = [180, 180]
    slot_for = [0, 1]
    _layout()._recap_cards_pull_in(geom, slot_for, [pin, other_pin], {1}, [2, 0], 1920, 1080, [], route)
    x, y = geom.slots[slot_for[0]]
    assert abs(x + 17 - pin[0]) < 150 and abs(y + 90 - pin[1]) < 250
    for qx, qy in (pin, other_pin):
        assert not (x - 20 <= qx <= x + 34 + 20 and y - 20 <= qy <= y + 180 + 20)



def test_pill_badges_lock_only_stopby_clusters_into_one_block():
    """Without leader lines a cluster of numbered stops is matched badge by badge (locked as one block, Tomogashima's
    8 stops only fitted in a row 300 px off); a cluster of stop-bys still claims its block together."""
    import numpy as np

    from services.vdoprocessing.spatial_renderer.popups import _RecapCardsGeom

    slots = [(100 + 48 * i, 60) for i in range(10)]
    pins = [(300.0, 600.0), (310.0, 600.0), (320.0, 600.0)]
    layout = _layout()

    def run(kind):
        geom = _RecapCardsGeom(slots, 34, 180, False, None, 20)
        geom.card_hs = [180] * 3
        return layout._recap_cards_lock_clusters(
            geom, [[0, 1, 2]], pins, [1, 2, 3], np.zeros(len(slots)), [0] * 3, 3, [kind] * 3)

    locked, free = run(0)
    assert locked == set() and len(free) == len(slots)
    locked, free = run(1)
    assert locked == {0, 1, 2} and len(free) == len(slots) - 3


def test_a_band_of_columns_slides_its_row_off_the_route():
    """One row fits under the headline with room to spare: centred it lies on a line across the band, so the whole
    band's row moves down below it, every column together so the badges stay in one row."""
    import numpy as np

    layout = _layout()
    head = [(0.0, 0.0, 1920.0, 185.0)]
    route = np.array([[x, 400.0] for x in range(0, 1920, 6)])  # crosses the centred row, clear of the bottom one
    slots = layout._recap_card_slots(1920, 1080, 34, 395, head, route)
    assert slots and len({y for _, y in slots}) == 1
    y = slots[0][1]
    assert y > 400  # below the line
