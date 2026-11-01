"""The static-tile ending highlight zooms toward the stop where it sits on the highlight image, not on the overview map."""

from unittest.mock import MagicMock

import numpy as np

from services.vdoprocessing.spatial_renderer import SpatialRenderer


def test_static_highlight_zooms_toward_the_stop_on_the_highlight_image(monkeypatch):
    r = SpatialRenderer.__new__(SpatialRenderer)
    r.graphics = MagicMock()
    r.graphics.read_image_safe.return_value = np.zeros((90, 160, 3), np.uint8)
    r.graphics.beside_card_footprint.return_value = (10, 10)
    r.graphics.render_popup_box.side_effect = lambda frame, *a, **k: frame
    r.config, r.transition_cfg, r.last_frame = {}, {}, np.zeros((90, 160, 3), np.uint8)
    r._get_job_config = lambda: {"start_point": {"lat": 35.0, "lng": 139.0}}
    r._fetch_highlight_image = lambda *a, **k: ("h.png", (0, 0, 1, 1))
    r._layout_recap_popups = r._place_cards_above_pins = lambda *a, **k: None
    r._draw_route_line_on_extent = r._draw_nearby_waypoints = lambda *a, **k: None
    monkeypatch.setattr(
        "services.vdoprocessing.spatial_renderer.transitions.RouteGeometryProcessor.project_latlon_to_pixel",
        lambda *a: (120.0, 30.0),
    )
    centres = []
    r._ken_burns_hold = lambda video, frame, fps, sec, cx, cy, **k: centres.append((cx, cy)) or frame
    r.transition_cfg = {"scale_seconds": 0.1, "min_hold_seconds": 0.1, "fade_out_seconds": 0.1}
    r.graphics.generate_fullscreen_popup_transition.return_value = []
    stop = {"index": 3, "x": 10, "y": 80, "data": {}}  # where the stop sits on the overview map
    r._render_ending_highlight(MagicMock(frames_written=0), 160, 90, 10, stop)
    assert centres[0] == (10, 80)  # the lead-in still pushes in on the overview
    assert centres[1:] == [(120, 30), (120, 30)]
