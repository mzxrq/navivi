"""_place_cards_above_pins: an intro photo card sits straight above its pin,
unless there's no room above it or the spot is already taken."""

from types import SimpleNamespace

from services.vdoprocessing.spatial_renderer.pins import _PinMixin
from services.vdoprocessing.spatial_renderer.popups import _PopupMixin


class _Layout(_PopupMixin, _PinMixin):
    pass


def _layout():
    layout = _Layout()
    layout.graphics = SimpleNamespace(marker_radius=20)
    return layout


def test_card_moves_from_below_to_above_the_pin():
    card = {"x": 1400, "y": 620, "beside_box": (1300, 660)}  # hanging below the pin
    _layout()._place_cards_above_pins([card], 1920, 1080, card_w=200, card_h=180)
    bx, by = card["beside_box"]
    assert by + 180 <= 620 - 2.5 * 20  # bottom edge above the pin's head
    assert bx == 1300  # centred on the pin


def test_pin_near_the_top_keeps_its_spot():
    card = {"x": 900, "y": 100, "beside_box": (800, 140)}
    _layout()._place_cards_above_pins([card], 1920, 1080, card_w=200, card_h=180)
    assert card["beside_box"] == (800, 140)


def test_card_is_kept_inside_the_frame():
    card = {"x": 1900, "y": 600, "beside_box": (1500, 650)}
    _layout()._place_cards_above_pins([card], 1920, 1080, card_w=200, card_h=180)
    assert card["beside_box"][0] + 200 <= 1920 - 20


def test_second_card_does_not_land_on_the_first():
    a = {"x": 1000, "y": 600, "beside_box": (0, 0)}
    b = {"x": 1010, "y": 600, "beside_box": (1300, 700)}
    _layout()._place_cards_above_pins([a, b], 1920, 1080, card_w=200, card_h=180)
    assert b["beside_box"] == (1300, 700)


def _beside_layout():
    layout = _layout()
    layout.graphics.beside_card_footprint = lambda *a: (200, 180)
    return layout


def test_walk_card_goes_above_its_pin_even_over_the_route_line():
    import numpy as np

    layout = _beside_layout()
    layout._layout_pin_obstacles = layout._pin_obstacle_points([{"x": 900, "y": 700}])
    route = np.array([[x, 560.0] for x in range(0, 1920, 10)])  # runs right through the spot above
    popup = {"x": 900, "y": 700, "order": 1}
    layout._layout_beside_popups([{"popup": popup}], 1920, 1080, card_w=200, card_h=180,
                                 route_obstacles=np.vstack([route, layout._layout_pin_obstacles]))
    bx, by = popup["beside_box"]
    assert by + 180 < 700 - 2.5 * 20  # above the pin's head
    assert abs(bx + 100 - 900) < 1  # centred on it


def test_walk_card_does_not_cover_another_pin():

    layout = _beside_layout()
    pins = [{"x": 900, "y": 700}, {"x": 900, "y": 560}]  # a neighbour right above
    layout._layout_pin_obstacles = layout._pin_obstacle_points(pins)
    popup = {"x": 900, "y": 700, "order": 1}
    layout._layout_beside_popups([{"popup": popup}], 1920, 1080, card_w=200, card_h=180,
                                 route_obstacles=layout._layout_pin_obstacles)
    bx, by = popup["beside_box"]
    covers_neighbour = bx <= 900 <= bx + 200 and by <= 560 <= by + 180
    assert not covers_neighbour
