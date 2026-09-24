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

    # Clamp bounds for every derived on-screen speed factor below — see the
    # "Clamped so no leg is compressed..." comment in __init__ for why.
    _MIN_SPEED_FACTOR = 0.3
    _MAX_SPEED_FACTOR = 60.0

    # Minimum on-screen pixel movement between two heading samples for the
    # direction to be trusted rather than treated as rounding noise — shared
    # by _initial_heading and _smoothed_heading below.
    _MIN_HEADING_SAMPLE_DIST_PX = 1.5

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
        # walking and ferry are the two modes that don't share the flat
        # baseline pace by default (see tuning.py's WALKING/FERRY_
        # ANIMATION_SPEED_FACTOR) — ferry's own default is derived from
        # walking's (already-slowed) pace, not the base one, so it stays
        # visibly faster than a walking leg rather than both landing back
        # at the same speed. A project's explicit animation_speeds_kmh
        # override (below) still wins over either of these.
        _walking_default_kmh = self._DEFAULT_ANIMATION_SPEED_KMH * tuning.WALKING_ANIMATION_SPEED_FACTOR
        _default_kmh_by_mode = {
            "walking": _walking_default_kmh,
            "ferry": _walking_default_kmh * tuning.FERRY_ANIMATION_SPEED_FACTOR,
        }
        animation_speed_kmh = {
            **{
                mode: _default_kmh_by_mode.get(mode, self._DEFAULT_ANIMATION_SPEED_KMH)
                for mode in mode_speed_kmh
            },
            **animation_overrides,
        }
        self._mode_speed_factor = {
            mode: max(self._MIN_SPEED_FACTOR, min(self._MAX_SPEED_FACTOR, kmh / self._REFERENCE_KMH))
            for mode, kmh in animation_speed_kmh.items()
        }
        # Fallback factor for a mode key with no entry above at all (e.g. a
        # mode string not present in mode_speed_kmh) — same uniform default
        # pace as every listed mode, not a hardcoded "1.0" that would give
        # it yet another, different speed of its own.
        self._default_mode_speed_factor = max(
            self._MIN_SPEED_FACTOR,
            min(self._MAX_SPEED_FACTOR, self._DEFAULT_ANIMATION_SPEED_KMH / self._REFERENCE_KMH),
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
        # Per-project pin colors: shadow the class defaults above with
        # whatever this project configured (already normalized to BGR by
        # render_step.py). Set as INSTANCE attributes, so a key the
        # project didn't set simply leaves the class default visible
        # rather than needing a copy of it here.
        for attr, key in (
            ("_START_PIN_COLOR", "start_pin_color"),
            ("_END_PIN_COLOR", "end_pin_color"),
            ("_DRAWN_PIN_COLOR", "drawn_pin_color"),
            ("_STOPBY_PIN_COLOR", "stopby_pin_color"),
        ):
            configured = config.get(key)
            if configured:
                setattr(self, attr, tuple(configured))

        self.last_frame = None
        # Set by render_overview() after each run — True when the video
        # already ended on its own blur-out (see _render_ending_highlight),
        # so callers (route2vdo.py) know not to bolt an extra frozen hold
        # onto a clip that was deliberately built to end right there.
        self.last_ending_hard_ended = False

    # Start/end pins get a conventional color (green/red, matching standard
    # map-app iconography) regardless of arrival state — every other pin
    # still uses _pin_color's default/arrived coloring. Shared by both
    # _PinMixin and _TransitionMixin, so these live here rather than in
    # either leaf mixin. "S" is always plain green — a loop route
    # (start==end) signals itself instead via the "E" pin's half green/red
    # split (see pins.py's _pin_label_and_color and _is_loop_route below),
    # not by recoloring S itself.
    #
    # These are the DEFAULTS. Each is overridable per project through
    # job_config.json's settings (start_pin_color / end_pin_color /
    # drawn_pin_color / stopby_pin_color, alongside marker_color and
    # arrived_marker_color, which reach the GraphicsEngine instead) — see
    # the instance attributes set in __init__ below and render_step.py's
    # _project_color, which is where a project's own RGB values are
    # converted to the BGR the renderer draws in.
    _START_PIN_COLOR = tuning.START_PIN_COLOR
    _END_PIN_COLOR = tuning.END_PIN_COLOR
    _DRAWN_PIN_COLOR = tuning.DRAWN_PIN_COLOR
    _STOPBY_PIN_COLOR = tuning.STOPBY_PIN_COLOR

    @property
    def _is_loop_route(self) -> bool:
        """True when this project's start_point and end_point are (near-)
        identical real-world coordinates — an out-and-back or round trip
        that returns to exactly where it began, rather than two distinct
        places that just happen to be close. Cached on the instance since
        _get_job_config re-reads job_config.json from disk every call and
        this is checked on every pin draw."""
        cached = getattr(self, "_is_loop_route_cache", None)
        if cached is not None:
            return cached
        job_config = self._get_job_config() or {}
        start = job_config.get("start_point") or {}
        end = job_config.get("end_point") or {}
        s_lat, s_lng = start.get("lat"), start.get("lng", start.get("lon"))
        e_lat, e_lng = end.get("lat"), end.get("lng", end.get("lon"))
        result = False
        if None not in (s_lat, s_lng, e_lat, e_lng):
            result = (
                abs(s_lat - e_lat) <= tuning.LOOP_ROUTE_MATCH_DEGREES
                and abs(s_lng - e_lng) <= tuning.LOOP_ROUTE_MATCH_DEGREES
            )
        self._is_loop_route_cache = result
        return result

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
            if math.hypot(pt[0] - x0, pt[1] - y0) >= _SpatialRendererBase._MIN_HEADING_SAMPLE_DIST_PX:
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
        min_dist: float = _MIN_HEADING_SAMPLE_DIST_PX,
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
        for search_dir in [self.out_dir] + list(self.out_dir.parents):
            potential_path = search_dir / "job_config.json"
            if potential_path.exists():
                try:
                    with open(potential_path, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    pass
        return None

    def _get_job_waypoints(self) -> List[Dict]:
        return (self._get_job_config() or {}).get("waypoints", [])
