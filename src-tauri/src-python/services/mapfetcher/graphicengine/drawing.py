"""Route line and waypoint pin drawing."""

import math
from typing import Any, List, Optional, Tuple

import cv2
import numpy as np

from services import tuning


def _pin_silhouette(cx: int, head_cy: int, radius: float, tip_y: int) -> np.ndarray:
    """A classic teardrop/balloon-pin outline: the round head plus the two
    lines TANGENT to it down to the tip, rather than a separate triangle
    drawn from the head's bottom edge — a tangent-line tail meets the
    circle smoothly (no visible seam/notch at the neck), reading as one
    continuous teardrop shape instead of a circle with a triangle stuck
    onto it."""
    d = max(tip_y - head_cy, radius + 1)
    angle_c = math.degrees(math.acos(radius / d))
    arc_pts = cv2.ellipse2Poly(
        (cx, head_cy), (int(radius), int(radius)), 0,
        int(90 + angle_c), int(90 - angle_c + 360), 2,
    )
    return np.array(list(arc_pts) + [(cx, tip_y)], dtype=np.int32)


class _DrawingMixin:
    def draw_path(
        self,
        frame: np.ndarray,
        path_history: List[Tuple[int, int]],
        mode_history: Optional[List[str]] = None,
    ):
        if len(path_history) < 2:
            return

        # Group consecutive points into same-mode runs so each leg (e.g. a
        # ferry crossing) can be drawn in its own color, matching the
        # transport icon shown for that leg.
        # [NOTE] [Animation] Groups consecutive same-mode points into segments so each leg (e.g. a ferry crossing) draws in its own color.
        if mode_history and len(mode_history) == len(path_history):
            segments: List[Tuple[str, List[Tuple[int, int]]]] = []
            for point, mode in zip(path_history, mode_history):
                if segments and segments[-1][0] == mode:
                    segments[-1][1].append(point)
                else:
                    # Include the last point of the previous segment so the
                    # drawn line has no gap at the mode boundary.
                    prev_point = segments[-1][1][-1] if segments else None
                    seg_points = [prev_point, point] if prev_point else [point]
                    segments.append((mode, seg_points))
        else:
            segments = [("walking", list(path_history))]

        for mode, seg_points in segments:
            if len(seg_points) < 2:
                continue
            color = self.MODE_COLORS.get(mode, self.line_color)
            pts = np.array(seg_points, dtype=np.int32)
            if self.line_border_thickness:
                cv2.polylines(
                    frame,
                    [pts],
                    False,
                    self.line_border_color,
                    self.line_thickness + self.line_border_thickness * 2,
                    cv2.LINE_AA,
                )
            cv2.polylines(
                frame,
                [pts],
                False,
                color,
                self.line_thickness,
                cv2.LINE_AA,
            )

    def draw_marker(
        self,
        frame: np.ndarray,
        cx: int,
        cy: int,
        number: Optional[Any] = None,
        color: Optional[Tuple[int, int, int]] = None,
    ):
        """Draws a classic Google-Maps-style teardrop map-pin marker with
        its TIP anchored at (cx, cy) — the actual waypoint coordinate —
        and the round head above it: one continuous teardrop silhouette
        (round head + tail TANGENT to it, see _pin_silhouette) rather than
        a circle with a separate triangle stuck onto it. The head's
        center always shows a white circle with `number` (if given —
        usually a 1-based visit order, or "S"/"E" for the route's actual
        start/end) drawn inside it in dark, readable text. Pass `color`
        to override self.marker_color for this pin only (e.g. arrived
        waypoints, or one of tuning.py's
        START/END/DRAWN/STOPBY_PIN_COLOR)."""
        pin_color = color if color is not None else self.marker_color
        radius = int(self.marker_radius)
        head_cy = cy - int(radius * 1.5)

        # White halo (slightly larger all round, including a bit past the
        # tip) so the pin reads against busy map tiles.
        cv2.fillPoly(
            frame, [_pin_silhouette(cx, head_cy, radius + 4, cy + 4)],
            (255, 255, 255), cv2.LINE_AA,
        )

        # Colored pin body.
        cv2.fillPoly(
            frame, [_pin_silhouette(cx, head_cy, radius, cy)],
            pin_color, cv2.LINE_AA,
        )

        # White center — always drawn (not just when there's no number) so
        # every numbered pin gets the same dark-on-white number. Smaller
        # than before (0.65 vs 0.8) so more of the pin's own color shows
        # through around it.
        # [HACK] [Animation] Hole/font ratios (0.65, radius/26.0) are hand-tuned magic numbers to keep two-digit labels and "S"/"E" from overflowing the white center.
        hole_radius = max(2, int(radius * 0.65))
        cv2.circle(frame, (cx, head_cy), hole_radius, (255, 255, 255), -1, cv2.LINE_AA)

        if number is not None:
            label = str(number)
            # radius/26 — sized back down to fit the smaller white center
            # above (was radius/22, tuned for the previous 0.8 hole).
            font_scale = max(0.45, radius / 26.0)
            thickness = max(2, round(radius / 7))
            # Two-plus-character labels ("10", "11", ...) are visibly
            # wider than a single digit/letter at the same font_scale —
            # shrinking both a notch keeps them from crowding the white
            # center's edge the way a single character never does.
            if len(label) > 1:
                font_scale *= 0.7
                thickness = max(2, round(thickness * 0.75))
            (tw, th), baseline = cv2.getTextSize(label, self.font_cv, font_scale, thickness)
            # Center on the glyph's own visual bounding box (th tall, plus
            # baseline for any descenders) rather than assuming no
            # descenders — round() instead of integer-divide keeps this
            # accurate at small radii too. getTextSize's box alone still
            # measurably undershoots upward — cv2.LINE_AA's stroke
            # rendering bleeds the visible ink down by roughly half the
            # stroke thickness beyond what getTextSize accounts for
            # (verified empirically across marker sizes 14-44px: without
            # this the number sits ~1-5px below true center, scaling with
            # thickness) — so pull it back up by that amount too.
            text_x = cx - round(tw / 2)
            text_y = head_cy + round((th - baseline) / 2) - round(thickness / 2)
            cv2.putText(
                frame,
                label,
                (text_x, text_y),
                self.font_cv,
                font_scale,
                tuning.PIN_NUMBER_TEXT_COLOR,
                thickness,
                cv2.LINE_AA,
            )

    def draw_frame_border(
        self,
        frame: np.ndarray,
        color: Tuple[int, int, int] = (255, 255, 255),
        thickness: int = 4,
    ) -> None:
        """Draws a solid frame border inset from the image edges — used to
        give a zoomed-in residential map a distinct "picture frame" look
        rather than bleeding to the video's own edges. Drawn in-place,
        directly on the background, so it's automatically present on every
        frame copied from it afterward."""
        h, w = frame.shape[:2]
        half = max(1, thickness // 2)
        cv2.rectangle(
            frame,
            (half, half),
            (w - half - 1, h - half - 1),
            color,
            thickness,
            cv2.LINE_AA,
        )
