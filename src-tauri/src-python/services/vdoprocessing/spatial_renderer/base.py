"""Shared setup for SpatialRenderer: __init__, mode-speed config, small job-config
and heading helpers used across the overview/waypoint renderers."""

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.mapfetcher.graphicengine import GraphicsEngine
from services.logger.logger import setup_logger

logger = setup_logger("SpatialRenderer")


class _SpatialRendererBase:
    # Fallback real-world average speed (km/h) per travel mode — overridable
    # per-project via job_config.json's settings.mode_speeds_kmh, e.g.
    # {"walking": 3, "car": 70, "ferry": 36}. These are what the on-screen
    # speed-up between modes is actually computed from (see
    # _mode_speed_factor below), not arbitrary multipliers.
    _DEFAULT_MODE_SPEED_KMH = {
        "walking": 6.0,
        "ferry": 75.0,
        "car": 70.0,
        "driving": 70.0,
        "airplane": 500.0,
    }
    # Fixed anchor "1x" pace that every mode's factor (including walking's
    # own) is computed against — NOT whatever "walking" happens to be
    # configured as. Self-normalizing against walking would make walking's
    # own configured speed a no-op (any value divided by itself is always
    # 1.0), which defeats the point of it being a tunable setting.
    _REFERENCE_KMH = 3.0

    def __init__(self, config: Dict[str, Any], graphics: GraphicsEngine, out_dir: Path):
        self.config = config
        self.graphics = graphics
        self.out_dir = out_dir

        mode_speed_kmh = {
            **self._DEFAULT_MODE_SPEED_KMH,
            **{
                str(k).lower(): float(v)
                for k, v in (config.get("mode_speeds_kmh") or {}).items()
            },
        }
        # How much faster each travel mode's leg is animated on screen —
        # derived from the configured real-world speeds rather than a
        # hand-picked ratio, so "car: 70 km/h" vs "walking: 4.5 km/h"
        # produces a genuinely proportionate speed-up, and tuning walking's
        # own speed actually changes its own on-screen pace too. Clamped so
        # no leg is compressed to a barely-visible handful of frames or, at
        # the other extreme, made slower than a near-standstill.
        self._mode_speed_factor = {
            mode: max(0.3, min(60.0, kmh / self._REFERENCE_KMH))
            for mode, kmh in mode_speed_kmh.items()
        }

        self.trigger_radius_padding = {
            # "overview" was generous enough (marker_radius + 25px) that a
            # waypoint's pin/popup could fire while the traveler was still
            # visibly short of it — tightened so arrival reads as actually
            # reaching the pin, not just passing near it. Both remain
            # overridable per-project via job_config.json's settings.
            **{"overview": 10, "waypoint": 15},
            **config.get("trigger_radius_padding", {}),
        }
        self.transition_cfg = {
            **{
                "scale_seconds": 0.8,
                "fade_out_seconds": 0.5,
                "hold_ratio_of_freeze": 0.4,
                "min_hold_seconds": 0.5,
                "min_small_hold_seconds": 0.1,
            },
            **config.get("fullscreen_transition", {}),
        }
        self.post_arrival_hold_seconds: float = config.get(
            "post_arrival_hold_seconds", 1.0
        )
        # Global kill switch for the "scale up to fill the screen" popup
        # style — when off, every waypoint (regardless of its own
        # image_display setting) uses the small pip card instead.
        self.enable_fullscreen_popups: bool = bool(
            config.get("enable_fullscreen_popups", True)
        )
        # When True, the route line is hidden (only pins/points stay visible)
        # for the duration a popup card is frozen on screen.
        self.hide_route_on_popup: bool = bool(config.get("hide_route_on_popup", False))
        # When True, only already-arrived waypoint pins are drawn during the
        # arrival pause/popup — with many stops on screen, every not-yet-
        # reached pin competing for attention makes it hard to tell which
        # one just triggered.
        self.hide_upcoming_pins_on_popup: bool = bool(
            config.get("hide_upcoming_pins_on_popup", False)
        )
        self.last_frame = None
        # Set by render_overview() after each run — True when the video
        # already ended on its own blur-out (see _render_ending_highlight),
        # so callers (route2vdo.py) know not to bolt an extra frozen hold
        # onto a clip that was deliberately built to end right there.
        self.last_ending_hard_ended = False

    # Start/end pins get a fixed, conventional color (green/red, matching
    # standard map-app iconography) regardless of arrival state — every
    # other pin still uses _pin_color's default/arrived coloring. Shared by
    # both _PinMixin and _TransitionMixin, so it lives here rather than in
    # either leaf mixin.
    _START_PIN_COLOR = (60, 180, 60)  # green (BGR)
    _END_PIN_COLOR = (0, 0, 220)  # red (BGR)

    @staticmethod
    def _smoothed_heading(
        prev_angle: float,
        cx: int,
        cy: int,
        prev_cx: Optional[int],
        prev_cy: Optional[int],
        min_dist: float = 1.5,
        alpha: float = 0.35,
    ) -> float:
        """Blends the new frame-to-frame heading into the previous smoothed
        heading, and ignores movement smaller than `min_dist` outright.

        The animated path is now straight-line interpolation between the
        real (simplified) route points, so through a winding, non-straight
        stretch the true heading changes abruptly at every vertex — and
        `path_history` stores rounded integer pixel coordinates, so on a
        short step the raw atan2 direction is dominated by rounding noise
        rather than the actual travel direction. Both together make the
        travel icon visibly shake as it moves. Blending (circularly, via
        the sin/cos components — angles can't be linearly averaged across
        the 359°/0° wrap) trades a little turning responsiveness for a
        stable-looking heading.
        """
        if prev_cx is None or prev_cy is None:
            return prev_angle
        if math.hypot(cx - prev_cx, cy - prev_cy) < min_dist:
            return prev_angle
        raw_angle = math.degrees(math.atan2(cy - prev_cy, cx - prev_cx))
        prev_rad, raw_rad = math.radians(prev_angle), math.radians(raw_angle)
        x = math.cos(prev_rad) * (1 - alpha) + math.cos(raw_rad) * alpha
        y = math.sin(prev_rad) * (1 - alpha) + math.sin(raw_rad) * alpha
        return math.degrees(math.atan2(y, x))

    def _get_job_config(self) -> Optional[Dict]:
        for p in [self.out_dir] + list(self.out_dir.parents):
            potential_path = p / "job_config.json"
            if potential_path.exists():
                try:
                    with open(potential_path, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    pass
        return None

    def _get_job_waypoints(self) -> List[Dict]:
        return (self._get_job_config() or {}).get("waypoints", [])
