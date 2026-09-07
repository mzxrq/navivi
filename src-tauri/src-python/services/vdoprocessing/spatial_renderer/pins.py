"""Waypoint pin coloring, declutter fan-out, and drawing."""

import math
from typing import Any, Dict, List

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
        for order, wp in enumerate(active_popups, start=1):
            if wp["data"].get("triggered"):
                self._draw_pin(base, wp, order, total_points)
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
        stays visible; _draw_pin then draws a short connector line back to
        the true spot for any pin that got moved."""
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
            for k, idx in enumerate(
                sorted(members, key=lambda i: active_popups[i]["order"])
            ):
                angle = 2 * math.pi * k / len(members)
                active_popups[idx]["pin_x"] = cx + fan_radius * math.cos(angle)
                active_popups[idx]["pin_y"] = cy + fan_radius * math.sin(angle)

    def _draw_pin(
        self, frame: np.ndarray, wp: Dict, order: int, total_points: int
    ) -> None:
        """Draws one waypoint's pin at its (possibly decluttered) position,
        with a thin connector line back to its true spot when the two
        differ — see _declutter_pins. The very first and last points of the
        route (the trip's actual start/end) are labeled "S"/"E" instead of
        a visit number, even when a waypoint happens to share that exact
        coordinate with the configured start_point/end_point."""
        pin_color = self._pin_color(wp)
        if wp["index"] == 0:
            label: Any = "S"
            pin_color = self._START_PIN_COLOR
        elif wp["index"] == total_points - 1:
            label = "E"
            pin_color = self._END_PIN_COLOR
        else:
            label = order
        px, py = int(wp.get("pin_x", wp["x"])), int(wp.get("pin_y", wp["y"]))
        tx, ty = int(wp["x"]), int(wp["y"])
        if (px, py) != (tx, ty):
            cv2.line(frame, (px, py), (tx, ty), (150, 150, 150), 2, cv2.LINE_AA)
            cv2.circle(frame, (tx, ty), 3, (150, 150, 150), -1, cv2.LINE_AA)
        self.graphics.draw_marker(frame, px, py, number=label, color=pin_color)
