"""Waypoint pin coloring and drawing."""

import math
from typing import Dict, List

import numpy as np


class _PinMixin:
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

    def _declutter_pins(self, active_popups: List[Dict]) -> None:
        """When two or more waypoints sit within a marker's width of each
        other (a cluster of stops on the same small island, say), their
        pins fully overlap when drawn at their real pixel position — the
        later one painted on top completely hides the earlier one, not
        just crowds it. This fans clustered pins out in a small circle
        around their shared center (storing the result as "pin_x"/"pin_y",
        separate from the pin's real "x"/"y" — trigger detection, popup
        placement, etc. all keep using the real position) so every pin
        stays visible."""
        # [NOTE] [Animation] Union-find groups pins transitively (A near B, B near C => one cluster of 3) rather than only pairwise-adjacent ones.
        n = len(active_popups)
        parent = list(range(n))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(i: int, j: int) -> None:
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[ri] = rj

        min_gap = self.graphics.marker_radius * 2.4
        for i in range(n):
            for j in range(i + 1, n):
                dx = active_popups[i]["x"] - active_popups[j]["x"]
                dy = active_popups[i]["y"] - active_popups[j]["y"]
                if math.hypot(dx, dy) < min_gap:
                    union(i, j)

        clusters: Dict[int, List[int]] = {}
        for i in range(n):
            clusters.setdefault(find(i), []).append(i)

        for members in clusters.values():
            if len(members) == 1:
                idx = members[0]
                active_popups[idx]["pin_x"] = active_popups[idx]["x"]
                active_popups[idx]["pin_y"] = active_popups[idx]["y"]
                continue

            cx = sum(active_popups[i]["x"] for i in members) / len(members)
            cy = sum(active_popups[i]["y"] for i in members) / len(members)
            # Evenly spacing `len(members)` pins on a circle of radius R
            # puts adjacent ones 2*R*sin(pi/k) apart — a FIXED radius
            # (the old min_gap*0.8, sized for a pair or trio) shrinks that
            # spacing as the cluster grows, so a real cluster of 5+ nearby
            # waypoints (a small island with several stops, say) still
            # overlapped after "fanning out" instead of actually
            # separating. Solving for R keeps every cluster — regardless
            # of how many pins share it — at least min_gap apart; the old
            # constant is kept as a floor so a small cluster (2-4) isn't
            # fanned out any tighter than before.
            fan_radius = min_gap * 0.8
            if len(members) >= 3:
                fan_radius = max(
                    fan_radius, min_gap / (2 * math.sin(math.pi / len(members)))
                )
            # [NOTE] [Animation] Stop-by waypoints never get an "order" (they
            # render as a "・" dot, not a number — see overview.py), so fall
            # back to 0 for them: any stable position in the fan-out works
            # since their draw order doesn't need to match a visit number.
            for k, idx in enumerate(
                sorted(members, key=lambda i: active_popups[i].get("order", 0))
            ):
                angle = 2 * math.pi * k / len(members)
                active_popups[idx]["pin_x"] = cx + fan_radius * math.cos(angle)
                active_popups[idx]["pin_y"] = cy + fan_radius * math.sin(angle)

    def _draw_pin(
        self, frame: np.ndarray, wp: Dict, total_points: int
    ) -> None:
        """Draws one waypoint's pin at its real position (wp["x"]/wp["y"]
        — "pin_x"/"pin_y" is the same point now, see _declutter_pins).

        Label/color precedence matches the map editor's own MapArea.tsx
        exactly: a stop-by waypoint (wp["data"]["is_stopby"]) ALWAYS renders
        as a "・" dot in STOPBY_PIN_COLOR — even if it happens to be the
        route's literal first/last point — since the frontend's isStopBy
        branch is checked before start/end labeling and returns
        unconditionally. Otherwise the very first/last points of the route
        (the trip's actual start/end) are labeled "S"/"E"; every other pin
        shows its precomputed visit order (wp["order"] — assigned once in
        overview.py's active_popups setup, skipping stop-by waypoints in the
        count the same way MapArea.tsx's normalIndex does)."""
        label, pin_color, split_color = self._pin_label_and_color(wp, total_points)
        px, py = int(wp.get("pin_x", wp["x"])), int(wp.get("pin_y", wp["y"]))
        is_circle = bool(wp.get("data", {}).get("is_stopby"))
        self.graphics.draw_marker(
            frame, px, py, number=label, color=pin_color, split_color=split_color, is_circle=is_circle
        )

    def _pin_label_and_color(self, wp: Dict, total_points: int):
        """Factored out of _draw_pin so other frame elements (e.g. the
        end-of-video recap's leader lines, see _render_recap_frame) can be
        colored to match a waypoint's own pin without duplicating its
        S/E/stop-by precedence rules. Returns (label, color, split_color)
        — split_color is None for every pin except a loop route's "E"."""
        if wp["data"].get("is_stopby"):
            return "・", self._STOPBY_PIN_COLOR, None
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
        return wp.get("order"), self._pin_color(wp), None
