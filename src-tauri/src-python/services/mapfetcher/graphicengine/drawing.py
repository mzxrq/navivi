"""Route line and waypoint pin drawing."""

from typing import Any, List, Optional, Tuple

import cv2
import numpy as np

from services import tuning


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
            cv2.polylines(
                frame,
                [pts],
                False,
                (255, 255, 255),
                self.line_thickness + 6,
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
        """Draws a classic map-pin (teardrop) marker with its TIP anchored at
        (cx, cy) — the actual waypoint coordinate — and the round head above
        it, matching standard map-pin iconography — proportioned to match
        the frontend's NaviPin.tsx (src/components/view/mapeditor/MapLayers/
        NaviPin.tsx: viewBox 191x275, head r=62 at cy=90, so tail length is
        ~2.98x the head radius) rather than an arbitrary shorter teardrop, so
        backend-rendered pins read as the same marker shape the map editor
        shows live. Pass `number` (usually a 1-based visit order, but any
        int/str — e.g. "S"/"E" for the route's actual start/end) to print it
        inside the head instead of a plain hole, so the route's stop
        sequence is readable at a glance. Pass `color` to override
        self.marker_color for this pin only (e.g. arrived waypoints, or one
        of tuning.py's START/END/DRAWN/STOPBY_PIN_COLOR)."""
        pin_color = color if color is not None else self.marker_color
        radius = int(self.marker_radius)
        head_cy = cy - int(radius * 2.98)
        neck_y = head_cy + radius
        tail_half = max(2, int(radius * 0.45))

        def _pin_poly(tail_w: int, tip_pad: int) -> np.ndarray:
            return np.array(
                [
                    [cx - tail_w, neck_y],
                    [cx + tail_w, neck_y],
                    [cx, cy + tip_pad],
                ],
                dtype=np.int32,
            )

        # White halo (slightly larger) so the pin reads against busy map tiles.
        cv2.circle(frame, (cx, head_cy), radius + 4, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.fillPoly(frame, [_pin_poly(tail_half + 3, 3)], (255, 255, 255), cv2.LINE_AA)

        # Colored pin body.
        cv2.circle(frame, (cx, head_cy), radius, pin_color, -1, cv2.LINE_AA)
        cv2.fillPoly(frame, [_pin_poly(tail_half, 0)], pin_color, cv2.LINE_AA)

        # NaviPin.tsx's head isn't a solid disc — its path is an evenodd
        # teardrop with a circular hole cut out of the middle (radius
        # ~63.06 against a ~95.5 head), revealing the white circle sat
        # behind it. That leaves only a thin colored ring, with the
        # number/letter (near-black #111) sitting on the white center
        # rather than white-on-color. Reproduced here as a white center
        # circle at the same ~0.66 ratio, drawn every time (not just when
        # there's no label) so numbered pins get the same ring look.
        hole_radius = max(2, int(radius * 0.66))
        cv2.circle(frame, (cx, head_cy), hole_radius, (255, 255, 255), -1, cv2.LINE_AA)

        if number is not None:
            label = str(number)
            font_scale = max(0.35, radius / 24.0)
            thickness = max(2, round(radius / 11))
            (tw, th), _ = cv2.getTextSize(label, self.font_cv, font_scale, thickness)
            cv2.putText(
                frame,
                label,
                (cx - tw // 2, head_cy + th // 2),
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
