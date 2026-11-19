"""The recap's pill-badge layout: near pins share one leader line, drawn
from their shared point without moving either pin."""

from types import SimpleNamespace

from services.vdoprocessing.spatial_renderer.pins import _PinMixin
from services.vdoprocessing.spatial_renderer.popups import _PopupMixin


class _Layout(_PopupMixin, _PinMixin):
    pass


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


def test_the_full_card_hangs_off_its_badge_spot_away_from_the_route():
    import numpy as np

    route = np.array([[x, 560.0] for x in range(940, 1400, 5)])  # runs right of the spot
    popup = {"stay_box": (900, 500), "label": "AB", "card_scale": 1.0}
    x, _ = _card_layout()._card_box_beside_badge(popup, 1920, 1080, route, [])
    assert x + 210 <= 900 + 34  # spilled left instead, clear of the line


def test_the_full_card_keeps_off_a_card_already_on_screen():
    popup = {"stay_box": (900, 500), "label": "AB", "card_scale": 1.0}
    taken = [(1000, 500, 1210, 690)]
    x, y = _card_layout()._card_box_beside_badge(popup, 1920, 1080, None, taken)
    assert not (x < 1210 and x + 210 > 1000 and y < 690 and y + 190 > 500)


def test_cards_up_together_never_cover_each_other():
    """Every stop's card stays up for the whole walk, so they end up on screen
    all together — even with their badge spots piled together, no two overlap."""
    import numpy as np

    layout = _card_layout()
    layout.graphics.render_popup_box = lambda frame, info, **kw: frame
    fps, total, gap = 30, 3600 * 30, 18
    spots = [(300, 300), (340, 320), (380, 340), (900, 400), (930, 420), (960, 300)]
    pending = [
        {
            "popup": {
                "x": sx, "y": 700, "order": i, "label": f"P{i}",
                "data": {"popup_image": "p.jpg"},
                "stay_box": (sx, sy), "beside_box": (sx, sy), "is_pill_badge": True,
            },
            "total_frames": total, "frames_left": total, "fade_frames": 12,
        }
        for i, (sx, sy) in enumerate(spots)
    ]
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    live, most = [], 0
    for n in range(200):
        if n % gap == 0 and pending:
            live.append(pending.pop(0))
        _, live = layout._composite_baked_popups(
            frame, live, 1920, 1080, None, active_popups=[], total_points=8, fps=fps,
        )
        boxes = [
            (lambda x, y: (x, y, x + 210, y + 190))(*(bp["popup"].get("card_box") or bp["popup"]["beside_box"]))
            for bp in live
        ]
        most = max(most, len(boxes))
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                assert not (a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1])
    assert most == len(spots)  # all of them were up together by the end


def test_the_walks_card_never_carries_the_recaps_badge_styling():
    """_layout_recap_cards stamps the badge style onto these dicts before the
    walk even starts, so any frame that builds a card straight from one draws
    a badge — every card on screen blinked into one on each arrival frame."""
    popup = {
        "x": 400, "y": 700, "order": 1, "label": "AB", "data": {"popup_image": "p.jpg"},
        "stay_box": (500, 300), "beside_box": (500, 300),
        "is_pill_badge": True, "suppress_leader_line": True, "leader_from": (1, 2),
    }
    hud = _card_layout().walk_card_hud(popup, 1920, 1080, None, lambda p: [])
    assert not any(hud.get(k) for k in ("is_pill_badge", "suppress_leader_line", "leader_from"))
    assert hud["draw_leader_line"] and hud["beside_box"] == popup["card_box"]
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
            "stay_box": (500, 300), "beside_box": (500, 300), "is_pill_badge": True,
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
                "stay_box": (400 + i * 400, 300), "beside_box": (400 + i * 400, 300),
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
