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
    def _draw_polyline_segments(
        self, frame: np.ndarray, segments: List[Tuple[Tuple[int, int, int], List[Tuple[int, int]]]]
    ) -> None:
        for color, seg_points in segments:
            if len(seg_points) < 2:
                continue
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

    def _mode_segments(
        self, path_history: List[Tuple[int, int]], mode_history: Optional[List[str]]
    ) -> List[Tuple[Tuple[int, int, int], List[Tuple[int, int]]]]:
        # Group consecutive points into same-mode runs so each leg (e.g. a
        # ferry crossing) can be drawn in its own color, matching the
        # transport icon shown for that leg.
        # [NOTE] [Animation] Groups consecutive same-mode points into segments so each leg (e.g. a ferry crossing) draws in its own color.
        if mode_history and len(mode_history) == len(path_history):
            raw_segments: List[Tuple[str, List[Tuple[int, int]]]] = []
            for point, mode in zip(path_history, mode_history):
                if raw_segments and raw_segments[-1][0] == mode:
                    raw_segments[-1][1].append(point)
                else:
                    # Include the last point of the previous segment so the
                    # drawn line has no gap at the mode boundary.
                    prev_point = raw_segments[-1][1][-1] if raw_segments else None
                    seg_points = [prev_point, point] if prev_point else [point]
                    raw_segments.append((mode, seg_points))
        else:
            raw_segments = [("walking", list(path_history))]
        return [
            (self.MODE_COLORS.get(mode, self.line_color), seg_points)
            for mode, seg_points in raw_segments
        ]

    @staticmethod
    def _offset_polyline(points_arr: np.ndarray, offset: float) -> np.ndarray:
        """Shifts every point perpendicular to the path's own local
        direction by `offset` pixels — a signed side-shift, not a fixed
        axis, so the offset stripe stays a consistent distance from the
        original line through every turn instead of just being nudged in
        one fixed screen direction (which would drift away from the path
        on a corner). Direction at each point is the CENTRAL difference
        (next point minus previous) rather than only the forward
        difference, so the offset direction doesn't visibly kink at each
        vertex the way a purely forward-looking normal would."""
        n = len(points_arr)
        if n < 2:
            return points_arr
        tangents = np.empty_like(points_arr, dtype=float)
        tangents[1:-1] = points_arr[2:] - points_arr[:-2]
        tangents[0] = points_arr[1] - points_arr[0]
        tangents[-1] = points_arr[-1] - points_arr[-2]
        lengths = np.hypot(tangents[:, 0], tangents[:, 1])
        lengths[lengths == 0] = 1.0
        tangents /= lengths[:, None]
        # Perpendicular to (tx, ty) is (-ty, tx).
        normals = np.stack([-tangents[:, 1], tangents[:, 0]], axis=1)
        return points_arr + normals * offset

    def _draw_dual_stripe(
        self, frame: np.ndarray, path_history: List[Tuple[int, int]], first_mode: str
    ) -> None:
        """The dual-color look for a shared corridor on a loop route: two
        stripes (outbound color + loop_return_color) running along
        `path_history`, each at the SAME thickness as the normal single
        line (self.line_thickness, straight from job_config), sitting
        directly side by side (touching, not overlapping) so both are
        equally, fully visible at their real thickness — an overlapping
        layout (tried before) let whichever stripe got drawn second paint
        over part of the first one's fill, making that one look thinner
        and harder to see despite being the same thickness underneath.

        The border/outline is drawn ONCE, centered on the original
        (unsplit) path at the combined width of both stripes together,
        BEFORE either fill — a border drawn separately around each
        individual stripe instead left a visible dark seam running down
        the middle, between the two colors. Drawing one border for the
        whole two-tone line, then both fills side by side on top with no
        border of their own, keeps a single clean outline around the
        whole thing with nothing between the two colors. Only an
        actually-shared stretch of a loop route gets this look;
        job_config's configured thickness still applies unchanged
        everywhere else (a single-pass leg, a non-loop route, every
        per-leg residential clip)."""
        if len(path_history) < 2:
            return
        pts = np.array(path_history, dtype=float)
        stripe_thickness = max(2, int(round(self.line_thickness)))
        half_gap = stripe_thickness / 2.0
        if self.line_border_thickness:
            centerline = pts.astype(np.int32)
            cv2.polylines(
                frame, [centerline], False, self.line_border_color,
                stripe_thickness * 2 + self.line_border_thickness * 2, cv2.LINE_AA,
            )
        inner = self._offset_polyline(pts, -half_gap).astype(np.int32)
        outer = self._offset_polyline(pts, half_gap).astype(np.int32)
        outbound_color = self.MODE_COLORS.get(first_mode, self.line_color)
        for stripe_pts, color in ((inner, outbound_color), (outer, self.loop_return_color)):
            cv2.polylines(frame, [stripe_pts], False, color, stripe_thickness, cv2.LINE_AA)

    def draw_path(
        self,
        frame: np.ndarray,
        path_history: List[Tuple[int, int]],
        mode_history: Optional[List[str]] = None,
    ):
        if len(path_history) < 2:
            return

        # A loop route (start_point == end_point — see overview.py's
        # render_overview setup, which computes loop_shared_mask) draws a
        # normal single line wherever the route is walked only once, and
        # switches to the two-stripe dual-color look (_draw_dual_stripe)
        # wherever THIS stretch of the corridor is walked TWICE (most
        # commonly a ferry crossing or a spur used both out and back) —
        # from the very first time it's walked, not only once it's later
        # retraced, since a shared stretch is shared on both passes. A
        # route can alternate between shared and single-pass stretches
        # more than once (e.g. crossing out, a single-pass island loop,
        # then crossing back over the SAME water), so this groups
        # path_history into however many shared/single-pass runs it
        # actually has, rather than assuming just one switch.
        #
        # A single-pass run that comes AFTER the first shared (retraced)
        # run is itself part of the return trip — a street used only on
        # the way back, not the same one walked out on — and is drawn as
        # a plain single RED line (loop_return_color) instead of the
        # normal outbound color, so it still reads as "returning" even
        # though it's not literally the same corridor as any earlier
        # stretch. A single-pass run BEFORE the first shared run is
        # genuinely still outbound and keeps the normal per-mode color.
        mask = getattr(self, "loop_shared_mask", None)
        if mask is not None and len(mask) >= len(path_history):
            m = mask[: len(path_history)]
            first_mode = mode_history[0] if mode_history else "walking"
            outbound_color = self.MODE_COLORS.get(first_mode, self.line_color)
            return_started = False
            run_start = 0
            for i in range(1, len(m) + 1):
                if i == len(m) or bool(m[i]) != bool(m[run_start]):
                    # Extend one point back into the PREVIOUS run (except
                    # for the very first run) so consecutive runs share a
                    # boundary point — otherwise there'd be a visible gap
                    # where the line style switches.
                    seg_start = run_start - 1 if run_start > 0 else run_start
                    seg = path_history[seg_start:i]
                    if bool(m[run_start]):
                        self._draw_dual_stripe(frame, seg, first_mode)
                        return_started = True
                    else:
                        color = self.loop_return_color if return_started else outbound_color
                        seg_pts = np.array(seg, dtype=np.int32)
                        if self.line_border_thickness:
                            cv2.polylines(
                                frame, [seg_pts], False, self.line_border_color,
                                self.line_thickness + self.line_border_thickness * 2,
                                cv2.LINE_AA,
                            )
                        cv2.polylines(
                            frame, [seg_pts], False, color, self.line_thickness, cv2.LINE_AA
                        )
                    run_start = i
            return

        self._draw_polyline_segments(frame, self._mode_segments(path_history, mode_history))

    def draw_marker(
        self,
        frame: np.ndarray,
        cx: int,
        cy: int,
        number: Optional[Any] = None,
        color: Optional[Tuple[int, int, int]] = None,
        split_color: Optional[Tuple[int, int, int]] = None,
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
        START/END/DRAWN/STOPBY_PIN_COLOR).

        `split_color`, if given, fills the RIGHT half of the pin body with
        this color instead of `color` (the left half) — used for a loop
        route's "E" pin, which sits on the exact same spot as "S": half
        `color` (the start's green) and half `split_color` (the end's
        red) reads as "this one point is both" instead of just showing
        one color and losing that it's the same place as the departure."""
        pin_color = color if color is not None else self.marker_color
        radius = int(self.marker_radius)
        head_cy = cy - int(radius * 1.5)

        # White halo (slightly larger all round, including a bit past the
        # tip) so the pin reads against busy map tiles.
        cv2.fillPoly(
            frame, [_pin_silhouette(cx, head_cy, radius + 4, cy + 4)],
            (255, 255, 255), cv2.LINE_AA,
        )

        if split_color is not None:
            # Fill the WHOLE silhouette with the left color first, then
            # overwrite only the right half (x >= cx) with the split
            # color — via a mask rather than two separately-clipped
            # fillPoly calls, so the teardrop's own curved/tapered outline
            # (not a plain rectangle) is respected on both halves without
            # having to intersect it with a half-plane by hand.
            silhouette = [_pin_silhouette(cx, head_cy, radius, cy)]
            mask = np.zeros(frame.shape[:2], dtype=np.uint8)
            cv2.fillPoly(mask, silhouette, 255, cv2.LINE_AA)
            cv2.fillPoly(frame, silhouette, pin_color, cv2.LINE_AA)
            right_mask = mask.copy()
            right_mask[:, :cx] = 0
            frame[right_mask > 0] = split_color
        else:
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

    def draw_compass(
        self,
        frame: np.ndarray,
        margin: int = 24,
        radius: int = 34,
    ) -> None:
        """Draws a static north-up compass badge in the top-right corner
        — a white circular disc, a red/gray "N"-up needle, and the four
        cardinal tick marks. Static (never rotates) because every map
        this renders is itself always north-up (pitch=0/bearing=0
        throughout this codebase — see pydeck_overview.py's own comment
        on why), so there's nothing for it to actually track; it's purely
        an orientation cue for the viewer, the same static role a
        Google-Maps-style compass plays when north-up lock is on. Drawn
        in-place, directly on the background, so it's automatically
        present on every frame copied from it afterward — same
        convention draw_frame_border uses."""
        h, w = frame.shape[:2]
        cx, cy = w - margin - radius, margin + radius

        overlay = frame.copy()
        cv2.circle(overlay, (cx, cy), radius, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.88, frame, 0.12, 0, frame)
        cv2.circle(frame, (cx, cy), radius, (210, 210, 210), 2, cv2.LINE_AA)

        # Cardinal ticks — short lines just inside the disc's own edge at
        # N/E/S/W, N drawn slightly bolder/longer than the other three so
        # it still reads as "the important one" even though the needle
        # itself already points there.
        for angle_deg, is_north in ((270, True), (0, False), (90, False), (180, False)):
            rad = math.radians(angle_deg)
            outer = (cx + radius * 0.92 * math.cos(rad), cy + radius * 0.92 * math.sin(rad))
            inner_r = radius * (0.68 if is_north else 0.76)
            inner = (cx + inner_r * math.cos(rad), cy + inner_r * math.sin(rad))
            cv2.line(
                frame, (int(inner[0]), int(inner[1])), (int(outer[0]), int(outer[1])),
                (150, 150, 150), 2 if is_north else 1, cv2.LINE_AA,
            )

        # The needle itself: a two-tone diamond (red tip pointing north,
        # gray tail pointing south) — the classic compass-rose needle
        # silhouette, rather than a plain arrow.
        needle_len = radius * 0.62
        needle_w = radius * 0.16
        north_tip = (cx, int(cy - needle_len))
        south_tip = (cx, int(cy + needle_len))
        left_pt = (int(cx - needle_w), cy)
        right_pt = (int(cx + needle_w), cy)
        cv2.fillConvexPoly(
            frame, np.array([north_tip, right_pt, south_tip, left_pt], dtype=np.int32),
            (60, 60, 60), cv2.LINE_AA,
        )
        cv2.fillConvexPoly(
            frame, np.array([north_tip, right_pt, left_pt], dtype=np.int32),
            (60, 55, 210), cv2.LINE_AA,
        )
        cv2.circle(frame, (cx, cy), max(2, int(radius * 0.08)), (255, 255, 255), -1, cv2.LINE_AA)

        # "N" label above the disc.
        label = "N"
        font_scale = radius / 34.0 * 0.55
        (label_w, label_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_DUPLEX, font_scale, 2)
        cv2.putText(
            frame, label, (cx - label_w // 2, cy - radius - 8),
            cv2.FONT_HERSHEY_DUPLEX, font_scale, (60, 60, 60), 2, cv2.LINE_AA,
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
