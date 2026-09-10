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
    # [NOTE] [Config] Fallback real-world average speed (km/h) per travel mode — overridable
    # per-project via job_config.json's settings.mode_speeds_kmh, e.g.
    # {"walking": 3, "car": 70, "ferry": 36}. This is the REPORTED speed —
    # what a leg's summary-card "time" is estimated from when real GPS
    # timestamps are missing — not what drives the on-screen animation
    # pace (see _DEFAULT_ANIMATION_SPEED_KMH below). Values live in
    # services/tuning.py, the shared home for every hand-tunable constant
    # across spatial_renderer + graphicengine.
    _DEFAULT_MODE_SPEED_KMH = tuning.REPORTED_MODE_SPEED_KMH
    # [NOTE] [Animation] Single speed that drives the on-screen ANIMATION pace
    # (_mode_speed_factor) for EVERY travel mode by default, kept
    # deliberately separate from the reported (real-world) speeds above.
    # Animating each mode at its own real-world speed made a 70+ km/h
    # car/ferry leg zip by relative to a walking one purely because of
    # their real-world speed gap — so every mode now shares one display
    # pace instead, and only the REPORTED numbers still vary per mode for
    # actual distance/time calculations. Overridable per-mode via
    # settings.animation_speeds_kmh for a project that wants one mode to
    # stand out again.
    _DEFAULT_ANIMATION_SPEED_KMH = tuning.ANIMATION_SPEED_KMH
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
        # How fast each travel mode's leg is animated on screen — every mode
        # defaults to the SAME on-screen pace (_DEFAULT_ANIMATION_SPEED_KMH,
        # a single number, not a per-mode dict like mode_speed_kmh above),
        # so a real-world-fast car/ferry/flight leg doesn't visually zip by
        # relative to a walking one; only the real mode_speed_kmh numbers
        # still vary per mode, for distance/time calculations. A project can
        # still opt one specific mode into its own display pace via
        # settings.animation_speeds_kmh. Clamped so no leg is compressed to
        # a barely-visible handful of frames or, at the other extreme, made
        # slower than a near-standstill.
        animation_overrides = {
            str(k).lower(): float(v)
            for k, v in (config.get("animation_speeds_kmh") or {}).items()
        }
        animation_speed_kmh = {
            **{mode: self._DEFAULT_ANIMATION_SPEED_KMH for mode in mode_speed_kmh},
            **animation_overrides,
        }
        self._mode_speed_factor = {
            mode: max(0.3, min(60.0, kmh / self._REFERENCE_KMH))
            for mode, kmh in animation_speed_kmh.items()
        }
        # Fallback factor for a mode key with no entry above at all (e.g. a
        # mode string not present in mode_speed_kmh) — same uniform default
        # pace as every listed mode, not a hardcoded "1.0" that would give
        # it yet another, different speed of its own.
        self._default_mode_speed_factor = max(
            0.3, min(60.0, self._DEFAULT_ANIMATION_SPEED_KMH / self._REFERENCE_KMH)
        )

        self.trigger_radius_padding = {
            # [NOTE] [Animation] "overview" was generous enough (marker_radius + 25px) that a
            # waypoint's pin/popup could fire while the traveler was still
            # visibly short of it — tightened so arrival reads as actually
            # reaching the pin, not just passing near it. Both remain
            # overridable per-project via job_config.json's settings.
            **tuning.TRIGGER_RADIUS_PADDING_DEFAULTS,
            **config.get("trigger_radius_padding", {}),
        }
        # [NOTE] [Animation] How long the popup card takes to confirm its position (a brief
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
    _DRAWN_PIN_COLOR = tuning.DRAWN_PIN_COLOR
    _STOPBY_PIN_COLOR = tuning.STOPBY_PIN_COLOR

    @staticmethod
    def _initial_heading(path: List) -> float:
        # [NOTE] [Animation] Uses the path's own geometry rather than a fixed
        # default so the initial heading is already correct before
        # _smoothed_heading has any history to blend from.
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

        `alpha` scales up toward 1.0 as the raw-vs-previous angle gap
        widens, rather than staying fixed — a fixed low alpha smooths out
        rounding jitter fine on a gentle GPS track, but a hand-drawn
        "draw"-mode route can pack several sharp real switchbacks into
        just a few frames each; blending all of them at the same slow
        rate meant the icon was still easing toward one corner's true
        heading when the next corner already arrived, so it never
        actually lined up with the line it was following ("confused").
        A genuinely large angle change is a real vertex, not noise, and
        is now believed almost immediately; small changes still smooth
        at the original slow rate.

        That boost is itself scaled down for a short step (`dist` close
        to `min_dist`): a step's raw_angle comes from rounded integer
        pixel coordinates, and for a SHORT step a ±1px rounding wobble
        can swing atan2's result by a large angle despite barely any real
        movement — trusting that as "a real sharp corner" and snapping
        toward it produced the opposite problem: the icon occasionally
        flipping to face the wrong way for a frame or two on an
        unremarkable stretch. Only a long-enough (confidently measured)
        step now gets the full fast-turn response; a short one still
        blends at the original slow, stable rate regardless of how large
        its (unreliable) angle_diff looks.
        """
        if prev_cx is None or prev_cy is None:
            return prev_angle
        dist = math.hypot(cx - prev_cx, cy - prev_cy)
        if dist < min_dist:
            return prev_angle
        raw_angle = math.degrees(math.atan2(cy - prev_cy, cx - prev_cx))
        angle_diff = abs(((raw_angle - prev_angle + 180) % 360) - 180)
        # Below ~4px a step's direction is noisy; at/above it, trust the
        # angle fully.
        turn_confidence = min(1.0, dist / max(min_dist * 3, 4.0))
        turn_alpha = min(1.0, alpha + (angle_diff / 180.0) * (1.0 - alpha) * turn_confidence)
        prev_rad, raw_rad = math.radians(prev_angle), math.radians(raw_angle)
        x = math.cos(prev_rad) * (1 - turn_alpha) + math.cos(raw_rad) * turn_alpha
        y = math.sin(prev_rad) * (1 - turn_alpha) + math.sin(raw_rad) * turn_alpha
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
