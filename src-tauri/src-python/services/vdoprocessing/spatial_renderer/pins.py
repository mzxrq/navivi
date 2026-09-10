"""Waypoint pin coloring, declutter fan-out, and drawing."""

import math
from typing import Dict, List

import cv2
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
            if wp["data"].get("triggered"):
                self._draw_pin(base, wp, total_points)
        return base

    def _pin_color(self, wp: Dict):
        """Arrived waypoints get GraphicsEngine.arrived_marker_color; ones
        still ahead keep the default marker_color (return None so
        draw_marker falls back to it)."""
        return self.graphics.arrived_marker_color if wp["data"].get("triggered") else None

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
            fan_radius = min_gap * 0.8
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
        """Draws one waypoint's pin at its (possibly decluttered) position
        — see _declutter_pins. No connector line back to the true spot is
        drawn when the two differ; that reads as visual clutter/confusion
        on a route with several nearby stops, and the fanned-out position
        alone is still close enough to the cluster to be legible.

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
        label, pin_color = self._pin_label_and_color(wp, total_points)
        px, py = int(wp.get("pin_x", wp["x"])), int(wp.get("pin_y", wp["y"]))
        self.graphics.draw_marker(frame, px, py, number=label, color=pin_color)

    def _pin_label_and_color(self, wp: Dict, total_points: int):
        """Factored out of _draw_pin so other frame elements (e.g. the
        end-of-video recap's leader lines, see _render_recap_frame) can be
        colored to match a waypoint's own pin without duplicating its
        S/E/stop-by precedence rules."""
        if wp["data"].get("is_stopby"):
            return "・", self._STOPBY_PIN_COLOR
        if wp["index"] == 0:
            return "S", self._START_PIN_COLOR
        if wp["index"] == total_points - 1:
            # A short route where the route's literal last point is ALSO
            # its first real numbered stop (order 1 — e.g. start -> one
            # stop with no separate end popup) keeps showing "1" instead
            # of being overwritten to "E"; the number is more useful here
            # than a redundant end marker.
            if wp.get("order") == 1:
                return 1, self._END_PIN_COLOR
            return "E", self._END_PIN_COLOR
        return wp.get("order"), self._pin_color(wp)
