"""Waypoint pin coloring and drawing."""

import math
from typing import Dict, List

import cv2
import numpy as np

from services import tuning


def _nearest_on_route(px: float, py: float, route: np.ndarray) -> tuple:
    """(x, y, distance) of the point on the polyline `route` (N x 2) closest to (px, py)."""
    a, ab = route[:-1], np.diff(route, axis=0)
    t = np.clip(((px - a[:, 0]) * ab[:, 0] + (py - a[:, 1]) * ab[:, 1]) / np.maximum((ab ** 2).sum(axis=1), 1e-9), 0.0, 1.0)
    q = a + ab * t[:, None]
    d2 = (q[:, 0] - px) ** 2 + (q[:, 1] - py) ** 2
    i = int(np.argmin(d2))
    return float(q[i, 0]), float(q[i, 1]), math.sqrt(float(d2[i]))


class _PinMixin:
    # The pins' role colours (base.py's renderer overrides them per project in __init__).
    _START_PIN_COLOR = tuning.START_PIN_COLOR
    _END_PIN_COLOR = tuning.END_PIN_COLOR
    _DRAWN_PIN_COLOR = tuning.DRAWN_PIN_COLOR
    _STOPBY_PIN_COLOR = tuning.STOPBY_PIN_COLOR

    def _build_freeze_frame(
        self,
        current_bg: np.ndarray,
        path_history: List,
        mode_history: List[str],
        last_leg_boundary: int,
        active_popups: List[Dict],
        total_points: int,
    ) -> np.ndarray:
        """Background + route line (respecting hide_route_on_popup) + pins
        for ONLY already-arrived waypoints — used for the arrival pause and
        popup when hide_upcoming_pins_on_popup is on, so a route with many
        stops doesn't bury the one that just triggered under a scatter of
        still-ahead pins."""
        base = current_bg.copy()
        if self.hide_route_on_popup:
            self.graphics.draw_path(
                base,
                path_history[: last_leg_boundary + 1],
                mode_history[: last_leg_boundary + 1],
            )
        else:
            self.graphics.draw_path(base, path_history, mode_history)
        for wp in active_popups:
            if wp["data"].get("arrived"):
                self._draw_pin(base, wp, total_points)
        return base

    def _pin_color(self, wp: Dict):
        """Arrived waypoints get GraphicsEngine.arrived_marker_color; ones
        still ahead keep the default marker_color (return None so
        draw_marker falls back to it). "arrived" (set the instant the
        traveler reaches the pin) rather than "triggered" (which only
        flips once this popup's card clears the overview's min-trigger-gap
        cooldown — see overview_animation.py) so the pin's own color
        change never lags behind the real arrival."""
        return self.graphics.arrived_marker_color if wp["data"].get("arrived") else None

    def _pin_obstacle_points(
        self, pins: List[Dict], cols: int = 3, rows: int = 4
    ) -> np.ndarray:
        """A grid of points covering each pin's DRAWN silhouette, for use as
        popup-layout obstacles (see popups.py's _layout_beside_popups, which
        rejects any candidate card box containing an obstacle point).

        Passing the route line alone isn't enough to keep a card off the
        map's content. A pin is drawn from its anchor UPWARD — the teardrop's
        tip sits on the coordinate and its head is ~2.5 radii above it (see
        drawing.py's _PIN_HEAD_OFFSET_RATIO) — so a card placed just above a
        waypoint lands squarely on the pin it belongs to, or on a
        neighbour's. Sampled as a grid rather than one point for that same
        reason: a single point at the anchor would only ever protect the tip.
        """
        if not pins:
            return np.empty((0, 2), dtype=float)
        radius = float(self.graphics.marker_radius)
        half_w = radius + 4.0
        points = []
        for wp in pins:
            cx = float(wp.get("pin_x", wp["x"]))
            cy = float(wp.get("pin_y", wp["y"]))
            x0, x1 = cx - half_w, cx + half_w
            y0, y1 = cy - (2.5 * radius + 4.0), cy + 4.0
            for i in range(cols):
                fx = i / (cols - 1) if cols > 1 else 0.5
                for j in range(rows):
                    fy = j / (rows - 1) if rows > 1 else 0.5
                    points.append((x0 + (x1 - x0) * fx, y0 + (y1 - y0) * fy))
        return np.asarray(points, dtype=float)

    # How far a pin may be nudged from its true position to stop it
    # hiding (or being hidden by) a neighbour, as a multiple of
    # marker_radius. Deliberately small: the reason decluttering was
    # switched off entirely once before is that fanning a cluster onto a
    # circle around its shared centre moved pins clear off the route line
    # they sit on, reading as "this stop isn't really on the path". Within
    # ~1.5 marker radii a pin still visibly belongs to the line it was
    # drawn on, which is enough to separate two dots that would otherwise
    # be exactly on top of each other.
    _PIN_DECLUTTER_MAX_SHIFT_RATIO = 1.5
    # Extra clear space between two pins' drawn silhouettes, in pixels.
    _PIN_DECLUTTER_PADDING = 2.0
    _PIN_DECLUTTER_ITERATIONS = 24
    # Below this separation (in pixels, measured on the pins' TRUE
    # positions) two pins are treated as one and the same place — see the
    # loop-route "S"/"E" case in the pair loop below.
    _PIN_SAME_PLACE_PX = 2.0
    # A stop this close to the drawn route (px) is on it, and its pin stays on it when nudged.
    _PIN_ON_ROUTE_PX = 12.0

    def _pin_draw_half_width(self, wp: Dict) -> float:
        """Half the width of this waypoint's DRAWN pin, matching
        drawing.py's draw_marker: a stop-by renders as a small dot
        (0.65 * marker_radius) inside a 3px white ring, everything else as
        a teardrop whose head is marker_radius plus a 4px white halo."""
        radius = float(self.graphics.marker_radius)
        return radius + 4.0

    def _declutter_pins(self, active_popups: List[Dict], route=None) -> None:
        """Nudges pins apart by the MINIMUM amount needed so no pin is
        drawn completely underneath another, storing the result as
        "pin_x"/"pin_y" (separate from the real "x"/"y", which trigger
        detection, popup placement and leader-line anchoring all keep
        using).

        Two waypoints only a few dozen metres apart — four stop-by
        landmarks around one small town, say — land on the same pixel at
        a whole-route zoom, and the one painted last hides the others
        outright: four stops in the data, three dots on screen.

        This is a pairwise relaxation, not the fan-out-onto-a-circle pass
        this function used to do. That version moved every member of a
        cluster a fixed radius away from their shared centre, which
        pushed pins clear off the route line they sit on (the reason it
        was disabled outright), and it moved pins that were merely close
        as readily as ones that genuinely overlapped. Here a pair is only
        touched when their drawn silhouettes actually collide, each is
        pushed out by half the penetration, and every pin's total shift
        from its true position is capped at
        _PIN_DECLUTTER_MAX_SHIFT_RATIO * marker_radius — so pins stay on
        their line, and a cluster too tight to fully separate within that
        cap ends up slightly offset (all of them visible) rather than
        perfectly spaced somewhere off-route.

        `route` (the drawn route's pixel points): a pin whose stop sits on it is slid back onto the line after each sweep,
        so it moves ALONG the route and never off it (a pin pushed up to 1.5 radii sideways looked unconnected to the line,
        worse once the course video zoomed in). A stop-by off the route is nudged freely as before."""
        n = len(active_popups)
        for wp in active_popups:
            wp["pin_x"], wp["pin_y"] = float(wp["x"]), float(wp["y"])
        if n < 2:
            return
        route = np.asarray(route, dtype=float) if route is not None and len(route) > 1 else None
        on_line = [
            route is not None and _nearest_on_route(wp["x"], wp["y"], route)[2] <= self._PIN_ON_ROUTE_PX
            for wp in active_popups
        ]

        half_w = [self._pin_draw_half_width(wp) for wp in active_popups]
        max_shift = float(self.graphics.marker_radius) * self._PIN_DECLUTTER_MAX_SHIFT_RATIO
        pad = self._PIN_DECLUTTER_PADDING

        for _ in range(self._PIN_DECLUTTER_ITERATIONS):
            moved = False
            for i in range(n):
                for j in range(i + 1, n):
                    a, b = active_popups[i], active_popups[j]
                    need = half_w[i] + half_w[j] + pad
                    dx = b["pin_x"] - a["pin_x"]
                    dy = b["pin_y"] - a["pin_y"]
                    dist = math.hypot(dx, dy)
                    if dist >= need:
                        continue
                    if (
                        math.hypot(a["x"] - b["x"], a["y"] - b["y"])
                        <= self._PIN_SAME_PLACE_PX
                    ):
                        # Two pins on (essentially) the same pixel are the
                        # same real-world place, not a cluster that needs
                        # separating — a loop route's "E" sits exactly on
                        # its "S" by definition, and _pin_label_and_color
                        # already handles that deliberately with a single
                        # half-green/half-red pin. Pushing them apart
                        # would replace that one honest marker with two
                        # markers for one place.
                        continue
                    push = (need - dist) / 2.0
                    ux, uy = dx / dist, dy / dist
                    a["pin_x"] -= ux * push
                    a["pin_y"] -= uy * push
                    b["pin_x"] += ux * push
                    b["pin_y"] += uy * push
                    moved = True
            # Re-clamp every pin back inside its own shift budget after
            # each sweep — applied here rather than inside the pair loop
            # so one pair's push can't be undone mid-sweep by a clamp
            # that a later pair would have relieved anyway.
            for wp, stays_on_line in zip(active_popups, on_line):
                ox, oy = wp["pin_x"] - wp["x"], wp["pin_y"] - wp["y"]
                shift = math.hypot(ox, oy)
                if shift > max_shift:
                    scale = max_shift / shift
                    wp["pin_x"] = wp["x"] + ox * scale
                    wp["pin_y"] = wp["y"] + oy * scale
                if stays_on_line and shift:
                    wp["pin_x"], wp["pin_y"], _ = _nearest_on_route(wp["pin_x"], wp["pin_y"], route)
            if not moved:
                break

    @staticmethod
    def _pin_pop_scale(wp: Dict, now_frame: int, fps: float) -> float:
        """Size of a pin that popped in at wp["pop_frame"] (the video frame the
        walker reached it), `now_frame` frames into the video: grows from
        nothing with a slight overshoot (ease-out-back) over
        tuning.PIN_POP_SECONDS, then stays at 1. 1 for a pin with no pop."""
        start = wp.get("pop_frame")
        if start is None:
            return 1.0
        duration = max(1.0, tuning.PIN_POP_SECONDS * fps)
        t = (now_frame - start) / duration
        if t >= 1.0:
            return 1.0
        t = max(0.0, t)
        c1 = 1.2  # gentler settle than the standard back-ease 1.70158 — less "app marker", more editorial
        return 1 + (c1 + 1) * (t - 1) ** 3 + c1 * (t - 1) ** 2

    def _draw_pin(
        self, frame: np.ndarray, wp: Dict, total_points: int, scale: float = 1.0,
    ) -> None:
        """Draws one waypoint's pin at its real position (wp["x"]/wp["y"]
        — "pin_x"/"pin_y" is the same point now, see _declutter_pins).

        Label/color precedence matches the map editor's own MapArea.tsx
        exactly: a stop-by waypoint (wp["data"]["is_stopby"]) ALWAYS renders
        with its "+N" (data["stopby_label"], else "・") in STOPBY_PIN_COLOR — even if it happens to be the
        route's literal first/last point — since the frontend's isStopBy
        branch is checked before start/end labeling and returns
        unconditionally. Otherwise the very first/last points of the route
        (the trip's actual start/end) are labeled "S"/"E"; every other pin
        shows its precomputed visit order (wp["order"] — assigned once in
        overview.py's active_popups setup, skipping stop-by waypoints in the
        count the same way MapArea.tsx's normalIndex does)."""
        label, pin_color, split_color = self._pin_label_and_color(wp, total_points)
        px, py = int(wp.get("pin_x", wp["x"])), int(wp.get("pin_y", wp["y"]))
        # A closed place is a circle, not a teardrop: it is not a stop on the
        # walk, and the recap marks every stop it did make with a dot.
        is_circle = bool(wp.get("data", {}).get("inaccessible"))
        self.graphics.draw_marker(
            frame, px, py, number=label, color=pin_color, split_color=split_color, is_circle=is_circle,
            scale=scale, image=wp.get("data", {}).get("pin_image"),
        )

    def _draw_recap_dot_color(
        self, frame: np.ndarray, px: int, py: int, color, scale: float = 1.0,
    ) -> None:
        """Plain color dot, no number and no teardrop tail — the recap
        family's marker shape (see _draw_recap_dot) for a caller that
        already has its own color/position rather than a waypoint dict
        (e.g. the ending highlight's own S/E marker, transitions.py)."""
        radius = max(2, int(self.graphics.marker_radius * 0.45 * scale))
        cv2.circle(frame, (int(px), int(py)), radius, color, -1, cv2.LINE_AA)
        cv2.circle(frame, (int(px), int(py)), radius, (255, 255, 255), 2, cv2.LINE_AA)

    def _draw_recap_dot(
        self, frame: np.ndarray, wp: Dict, total_points: int, scale: float = 1.0,
    ) -> None:
        """Plain color dot for the recap screen's "pill badge" style — no
        number, no teardrop tail. The number now lives in the badge card
        itself (see _render_pill_badge), so the pin only needs to carry
        its color; a numbered circle there would just repeat the badge.
        Unless the badge sat far from it (`badge_far`, see _layout_recap_cards): then the number
        on both is what ties them together."""
        if wp.get("badge_far"):
            self._draw_pin(frame, wp, total_points, scale=scale)
            return
        _, pin_color, _ = self._pin_label_and_color(wp, total_points)
        px, py = int(wp.get("pin_x", wp["x"])), int(wp.get("pin_y", wp["y"]))
        self._draw_recap_dot_color(frame, px, py, pin_color, scale)

    def _pin_label_and_color(self, wp: Dict, total_points: int):
        """Factored out of _draw_pin so other frame elements (e.g. the
        end-of-video recap's leader lines, see _render_recap_frame) can be
        colored to match a waypoint's own pin without duplicating its
        S/E/stop-by precedence rules. Returns (label, color, split_color)
        — split_color is None for every pin except a loop route's "E"."""
        if wp["data"].get("inaccessible"):
            return "×", tuning.CLOSED_PIN_COLOR, None
        if wp["data"].get("is_stopby"):
            return wp["data"].get("stopby_label") or "・", self._STOPBY_PIN_COLOR, None
        if wp["index"] == 0:
            return "S", self._START_PIN_COLOR, None
        if wp["index"] == total_points - 1:
            # A short route where the route's literal last point is ALSO
            # its first real numbered stop (order 1 — e.g. start -> one
            # stop with no separate end popup) keeps showing "1" instead
            # of being overwritten to "E"; the number is more useful here
            # than a redundant end marker.
            if wp.get("order") == 1:
                return 1, self._END_PIN_COLOR, None
            # A loop route's "E" sits on the exact same real-world spot as
            # "S" — a plain solid red pin there loses that it's also the
            # departure point. Half green (start)/half red (end) says
            # "you're back where you started" at a glance, on the one pin
            # that actually represents both.
            if self._is_loop_route:
                return "E", self._START_PIN_COLOR, self._END_PIN_COLOR
            return "E", self._END_PIN_COLOR, None
        # `pin_color`: its recap badge's own color (popups._recap_cards_match_pin_colors).
        return wp.get("order"), wp.get("pin_color") or self._pin_color(wp), None
