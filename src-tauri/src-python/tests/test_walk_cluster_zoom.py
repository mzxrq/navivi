"""Walk the route and Route map zoom in on a cluster of stops as the walker passes it (OVERVIEW_RULES 8.9, 8.18).
CPU only: no bounding box is captured, so the map is cropped."""
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from services import tuning
from services.mapfetcher.graphicengine import GraphicsEngine
from services.vdoprocessing.spatial_renderer import SpatialRenderer
from services.vdoprocessing.spatial_renderer.cluster_zoom import WalkCamera

W, H = 1280, 720
FULL = tuning.COURSE_DENSE_ZOOM_MAX
CLUSTERS = [(500.0, 560.0, 2.0, 100.0, 50.0), (1500.0, 1530.0, 2.0, 300.0, 80.0)]


def _levels(camera, cum, indexes):
    out = []
    for i in indexes:
        now = camera.step(cum, i)
        out.append(1.0 if now is None else now[1][0])
    return out


def test_the_walk_camera_eases_in_holds_over_the_cluster_and_eases_out_again():
    cum = np.arange(0.0, 2200.0, 5.0)
    camera = WalkCamera(CLUSTERS, 30, 45.0)
    levels = _levels(camera, cum, range(len(cum)))
    at = lambda d: levels[int(d // 5)]  # noqa: E731
    assert at(200) == 1.0 and at(1000) == 1.0 and levels[-1] == 1.0  # whole map before, between and after
    assert all(at(d) == 2.0 for d in (500, 530, 560, 1500, 1530))
    assert max(abs(a - b) for a, b in zip(levels, levels[1:])) < 0.1  # never a hard cut


def test_the_walk_camera_stays_in_while_the_walker_waits_at_a_stop_of_the_cluster():
    cum = np.arange(0.0, 2200.0, 5.0)
    camera = WalkCamera(CLUSTERS, 30, 45.0)
    walked_in = list(range(0, 113))  # to 560, the cluster's last stop
    assert _levels(camera, cum, walked_in + [112] * 90)[-1] == 2.0


def test_a_released_walk_camera_returns_to_the_whole_map():
    cum = np.arange(0.0, 2200.0, 5.0)
    camera = WalkCamera(CLUSTERS, 30, 45.0)
    _levels(camera, cum, range(0, 113))
    camera.released = True
    levels = _levels(camera, cum, [112] * camera.steps)
    assert 1.0 < levels[0] < 2.0 and levels[-1] == 1.0 and camera.k == 0


def _render(style, xs, tmp_path, monkeypatch, bounding_box=None):
    """A tiny finished video over a straight route through stops at `xs`: (the renderer, each camera step)."""
    background, photo = tmp_path / "background.png", tmp_path / "photo.png"
    cv2.imwrite(str(background), np.full((H, W, 3), 200, np.uint8))
    cv2.imwrite(str(photo), np.full((90, 160, 3), 90, np.uint8))
    points = [(x, 360) for x in xs]
    names = [f"stop {i}" for i in range(len(xs))]
    popups = [{"label": n, "triggered": False, "arrived": False, "popup_image": str(photo)} for n in names]
    steps = []
    real = WalkCamera.step

    def spy(camera, cum, index):
        now = real(camera, cum, index)
        steps.append((camera, None if now is None else now[1][0]))
        return now

    monkeypatch.setattr(WalkCamera, "step", spy)
    config = {"overview_style": style, "duration": 6.0, "enable_ending_highlight": False, "pause": 0.5,
              "summary_hold": 0.5}
    renderer = SpatialRenderer(config, GraphicsEngine(), tmp_path / "out")
    (tmp_path / "out").mkdir()
    renderer.render_overview(str(background), points, names, popups, 10, point_modes=["walking"] * len(points),
                             bounding_box=bounding_box)
    return renderer, steps


def _zoomed_runs(levels):
    runs, current = [], []
    for level in levels + [None]:
        if level is not None:
            current.append(level)
        elif current:
            runs.append(current)
            current = []
    return runs


@pytest.mark.parametrize("style", ["walk", "map"])
def test_a_walk_overview_zooms_over_a_cluster_of_three_and_of_two_and_ends_whole(style, tmp_path, monkeypatch):
    renderer, steps = _render(style, [60, 330, 355, 380, 900, 930, 1220], tmp_path, monkeypatch)
    levels = [level for _, level in steps]
    runs = _zoomed_runs(levels)
    assert len(runs) == 2 and all(max(run) == pytest.approx(FULL) for run in runs)
    assert levels[-1] is None and steps[-1][0].k == 0
    assert renderer._walk_zoom is None  # the recap and ending are never zoomed


@pytest.mark.parametrize("style", ["walk", "map"])
def test_a_walk_overview_with_spread_stops_never_zooms(style, tmp_path, monkeypatch):
    _, steps = _render(style, [60, 400, 800, 1220], tmp_path, monkeypatch)
    assert [level for _, level in steps if level is not None] == []


def test_the_gl_map_is_captured_once_for_every_view_the_walk_will_use(tmp_path, monkeypatch):
    asked = []
    monkeypatch.setattr(SpatialRenderer, "_gl_view_frames",
                        lambda self, views, box, w, h, out: asked.append((views, box)) or {})
    box = {"min_lat": 34.24, "max_lat": 34.30, "min_lon": 135.02, "max_lon": 135.14}
    _, steps = _render("walk", [60, 330, 355, 900, 1220], tmp_path, monkeypatch, bounding_box=box)
    camera = steps[0][0]
    assert asked == [(camera.views(), box)] and len(asked[0][0]) == camera.steps


def _zoomed_draws(ease):
    """The (index, box, alpha) of every visible card in a zoomed walk frame `ease` of the way in."""
    drawn = []

    def card(frame, info, alpha=1.0, line_only=False, **kwargs):
        if not line_only:
            drawn.append((info["index"], info["beside_box"], alpha))
        return frame

    renderer = SpatialRenderer.__new__(SpatialRenderer)
    renderer.config = {"overview_style": "walk"}
    renderer.graphics = SimpleNamespace(
        marker_radius=20, render_popup_box=card, draw_path=lambda *a, **k: None,
        draw_transport_icon=lambda *a, **k: None,
        beside_card_footprint=lambda scale=1.0, **k: (int(210 * scale), int(170 * scale)))
    renderer._draw_pin = lambda *a, **k: None
    popups = [
        {"index": i, "x": x, "y": y, "stay_box": box, "stay_scale": 1.4, "expected_frame": 0,
         "data": {"arrived": True}}
        for i, (x, y, box) in enumerate([(900, 400, (100, 100)), (60, 60, (300, 500))])  # the second is off view
    ]
    walk = SimpleNamespace(
        current_bg=np.zeros((H, W, 3), np.uint8), path_history=[(0, 0), (900, 400)], mode_history=["walking"] * 2,
        active_popups=popups, baked_popups=[{"popup": p, "frames_left": 50, "total_frames": 100, "fade_frames": 5}
                                            for p in popups],
        frozen_cards=[], last_beat=SimpleNamespace(index=1, cx=900, cy=400, mode="walking"), smoothed_angle=0.0,
        n_points=3, fps=30, route_obstacles=None, cum=np.array([0.0, 985.0]), video=SimpleNamespace(frames_written=100))
    zoom = (0.0, 985.0, 1.5, 400.0, 150.0)
    camera = WalkCamera([zoom], 30, 48.0)
    view = (1.0 + 0.5 * ease, 400.0 * ease, 150.0 * ease)
    renderer._walk_zoomed_frame(walk, camera, zoom, view, ease)
    return [d for d in drawn if d[2] > 0]


def test_fully_zoomed_only_a_card_whose_pin_is_in_view_shows_beside_its_zoomed_pin():
    (index, box, alpha), = _zoomed_draws(1.0)
    assert index == 0 and box != (100, 100) and alpha == pytest.approx(1.0)


def test_while_the_camera_starts_in_every_card_fades_out_at_its_own_spot():
    drawn = _zoomed_draws(0.25)
    assert {(i, b) for i, b, _ in drawn} == {(0, (100, 100)), (1, (300, 500))}
    assert all(a < 1 for _, _, a in drawn)


def test_the_route_maps_arriving_card_covers_no_zoomed_pin_or_card():
    """It stands at a spot chosen on the whole map; left there while zoomed, the pins moved under it."""
    drawn = []

    def card(frame, info, alpha=1.0, line_only=False, **kwargs):
        if not line_only:
            drawn.append((info["index"], info["beside_box"], info.get("card_scale", 1.0), alpha))
        return frame

    renderer = SpatialRenderer.__new__(SpatialRenderer)
    renderer.config = {"overview_style": "map"}
    renderer.graphics = GraphicsEngine()
    renderer.graphics.render_popup_box = card
    renderer._draw_pin = lambda *a, **k: None
    zoom = (0.0, 100.0, 1.5, 400.0, 150.0)
    pins = [(780, 440), (815, 430)]
    popups = [{"index": i, "x": x, "y": y, "stay_box": (100, 100 + 400 * i), "stay_scale": 1.0, "expected_frame": 0,
               "data": {"arrived": True}} for i, (x, y) in enumerate(pins)]
    over_the_pins = (500, 350)  # clear on the whole map, right over the zoomed pins
    popups[1].update(big=True, beside_box=over_the_pins, card_scale=1.6)
    walk = SimpleNamespace(
        current_bg=np.zeros((H, W, 3), np.uint8), path_history=[(700, 440), (815, 430)], mode_history=["walking"] * 2,
        active_popups=popups, baked_popups=[{"popup": p, "frames_left": 50, "total_frames": 100, "fade_frames": 5}
                                            for p in popups],
        frozen_cards=[], last_beat=SimpleNamespace(index=1, cx=815, cy=430, mode="walking"), smoothed_angle=0.0,
        n_points=3, fps=30, route_obstacles=None, cum=np.array([0.0, 100.0]))
    renderer._walk_zoomed_frame(walk, WalkCamera([zoom], 30, 48.0), zoom, zoom[2:], 1.0)
    boxes = {}
    for index, (x, y), scale, _alpha in drawn:
        cw, ch = renderer.graphics.beside_card_footprint(scale)
        boxes[index] = (x, y, x + cw, y + ch)
    big, stay = boxes[1], boxes[0]
    for x, y in pins:
        zx, zy = (x - 400) * 1.5, (y - 150) * 1.5
        assert not (big[0] <= zx <= big[2] and big[1] <= zy <= big[3])
    assert not (big[0] < stay[2] and stay[0] < big[2] and big[1] < stay[3] and stay[1] < big[3])
