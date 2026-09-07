"""Shared setup for SpatialRenderer: __init__, mode-speed config, small job-config
and heading helpers used across the overview/waypoint renderers."""

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.mapfetcher.graphicengine import GraphicsEngine
from services.logger.logger import setup_logger
from services import tuning

logger = setup_logger("SpatialRenderer")


class _SpatialRendererBase:
    # Fallback real-world average speed (km/h) per travel mode — overridable
    # per-project via job_config.json's settings.mode_speeds_kmh, e.g.
    # {"walking": 3, "car": 70, "ferry": 36}. This is the REPORTED speed —
    # what a leg's summary-card "time" is estimated from when real GPS
    # timestamps are missing — not what drives the on-screen animation
    # pace (see _DEFAULT_ANIMATION_SPEED_KMH below). Values live in
    # services/tuning.py, the shared home for every hand-tunable constant
    # across spatial_renderer + graphicengine.
    _DEFAULT_MODE_SPEED_KMH = tuning.REPORTED_MODE_SPEED_KMH
    # Speeds that drive the on-screen ANIMATION pace (_mode_speed_factor),
    # kept deliberately separate from the reported speeds above. Walking's
    # honest real-world pace (~3 km/h) reads fine as a stat on a card, but
    # animating literally at that pace relative to a 70+ km/h ferry/car
    # leg makes every walking segment crawl by comparison — so walking
    # animates faster than its own reported speed would imply. Every other
    # mode reuses its reported speed (no similar complaint there).
    # Overridable via settings.animation_speeds_kmh.
    _DEFAULT_ANIMATION_SPEED_KMH = tuning.ANIMATION_MODE_SPEED_KMH
    # Fixed anchor "1x" pace that every mode's factor (including walking's
    # own) is computed against — NOT whatever "walking" happens to be
    # configured as. Self-normalizing against walking would make walking's
    # own configured speed a no-op (any value divided by itself is always
    # 1.0), which defeats the point of it being a tunable setting.
    _REFERENCE_KMH = tuning.REFERENCE_SPEED_KMH

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
        # Kept (not just the derived factor below) so a leg missing real
        # timestamp data can still estimate a real-world travel time from
        # distance/speed for its summary card, instead of showing nothing.
        self.mode_speed_kmh = mode_speed_kmh
        # How much faster each travel mode's leg is animated on screen —
        # derived from animation_speed_kmh (a separate dict from the
        # reported mode_speed_kmh above — see _DEFAULT_ANIMATION_SPEED_KMH)
        # so "car: 70 km/h" vs "walking" produces a genuinely proportionate
        # speed-up without tying the on-screen pace to whatever realistic
        # (and much slower) speed the summary card reports for walking.
        # Clamped so no leg is compressed to a barely-visible handful of
        # frames or, at the other extreme, made slower than a near-standstill.
        animation_speed_kmh = {
            **mode_speed_kmh,
            **self._DEFAULT_ANIMATION_SPEED_KMH,
            **{
                str(k).lower(): float(v)
                for k, v in (config.get("animation_speeds_kmh") or {}).items()
            },
        }
        self._mode_speed_factor = {
            mode: max(0.3, min(60.0, kmh / self._REFERENCE_KMH))
            for mode, kmh in animation_speed_kmh.items()
        }

        self.trigger_radius_padding = {
            # "overview" was generous enough (marker_radius + 25px) that a
            # waypoint's pin/popup could fire while the traveler was still
            # visibly short of it — tightened so arrival reads as actually
            # reaching the pin, not just passing near it. Both remain
            # overridable per-project via job_config.json's settings.
            **tuning.TRIGGER_RADIUS_PADDING_DEFAULTS,
            **config.get("trigger_radius_padding", {}),
        }
        # How long the popup card takes to confirm its position (a brief
        # static hold on the small card) before it starts growing, then how
        # long the grow-to-fullscreen itself takes — slow and deliberate
        # (2-3s) rather than a snap cut, so the viewer can actually track
        # the photo scaling up rather than it just appearing full-frame,
        # then a progressive blur once fullscreen, then cut — reads as a
        # deliberate close instead of an abrupt jump into whatever plays
        # next. Defaults in services/tuning.py, overridable per-project via
        # job_config.json's settings.fullscreen_transition.
        self.transition_cfg = {
            **tuning.FULLSCREEN_TRANSITION_DEFAULTS,
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
    _START_PIN_COLOR = tuning.START_PIN_COLOR
    _END_PIN_COLOR = tuning.END_PIN_COLOR

    @staticmethod
    def _initial_heading(path: List) -> float:
        """Bearing to start _smoothed_heading's blend from, computed from
        the path itself (first point to the first later point far enough
        away for a stable direction, falling back to point 0 -> the last
        point for a very short path) — rather than a hardcoded 0.0 (due
        east), which made the transport icon visibly point the wrong way
        for the first several frames of a leg, until _smoothed_heading's
        own blend caught up with the real direction of travel."""
        if len(path) < 2:
            return 0.0
        x0, y0 = path[0][0], path[0][1]
        for pt in path[1:]:
            if math.hypot(pt[0] - x0, pt[1] - y0) >= 1.5:
                return math.degrees(math.atan2(pt[1] - y0, pt[0] - x0))
        x1, y1 = path[-1][0], path[-1][1]
        return math.degrees(math.atan2(y1 - y0, x1 - x0))

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
