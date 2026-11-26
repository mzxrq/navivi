from types import SimpleNamespace

import numpy as np

from services.vdoprocessing.route2vdo import RouteAnimator


def test_the_leg_card_ends_its_countdown_on_zero_when_arrived():
    """On arrival the card holds 0 left, not the leg's full distance again (that read as the counter resetting)."""
    drawn = []
    animator = RouteAnimator.__new__(RouteAnimator)
    animator.graphics = SimpleNamespace(
        render_summary_card=lambda **kw: drawn.append(kw) or np.zeros((4, 4, 3), np.uint8))
    render = animator._leg_hud_card_png("walking", (1.8, 2220.0), (22.5, 12000.0))

    render(0.9, 1110.0, False, 0.5)
    render(1.8, 2220.0, True, 1.0)  # what the arrival hold used to send: the whole leg
    walking, arrived = drawn
    assert (walking["distance_km"], walking["total_km"]) == (0.9, 0.9 + 22.5)
    assert (arrived["distance_km"], arrived["duration_seconds"], arrived["total_km"]) == (0.0, 0.0, 22.5)


def test_the_leg_cards_second_column_says_what_is_left_not_the_total():
    from services.mapfetcher.graphicengine import GraphicsEngine

    g = GraphicsEngine()
    left = g._columns_spec(0.9, 600.0, {"walking": 0.9}, {"walking": 600.0}, 22.0, 9000.0, False, remaining=True)
    whole = g._columns_spec(0.9, 600.0, {"walking": 0.9}, {"walking": 600.0}, 22.0, 9000.0, False)
    assert left[-1][0] == g.summary_card_labels["remaining_label"] != whole[-1][0] == g.summary_card_labels["total_label"]
