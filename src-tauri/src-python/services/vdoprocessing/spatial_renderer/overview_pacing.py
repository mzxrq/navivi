"""Mode-breakpoint lookup and speed-weighted path building for the overview
animation — split out of overview.py (render_overview itself) since this is
a self-contained "given the route + per-point travel modes, produce the
animated path" step with no dependency on the frame-by-frame rendering loop
that follows it."""

import math
from typing import List, Optional, Tuple

import numpy as np

from services.mapfetcher.mapfetcher import MapFetcher


class _OverviewPacingMixin:
    @staticmethod
    def _build_mode_breakpoints(points: List, point_modes: List[str]) -> List[Tuple[float, str]]:
        """Cumulative-distance fractions (0..1 along the route) at which the
        travel mode changes, so the animated trail/icon can react to
        routeMode transitions (e.g. walking -> ferry)."""
        if not points or not point_modes:
            return []
        if len(points) != len(point_modes):
            # Resample by proportional index rather than bailing out
            # entirely — a length mismatch here (points resampled/trimmed
            # somewhere upstream of this call) used to silently disable
            # per-mode line coloring for the WHOLE route, which read as
            # every leg (walking, ferry, ...) drawn in the same flat
            # line_color with no visible mode distinction at all.
            n = len(points)
            m = len(point_modes)
            point_modes = [point_modes[min(m - 1, int(i * m / n))] for i in range(n)]

        cum = [0.0]
        for i in range(1, len(points)):
            cum.append(
                cum[-1]
                + math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1])
            )
        total = cum[-1] or 1.0

        breakpoints = [(0.0, point_modes[0])]
        for i in range(1, len(points)):
            if point_modes[i] != breakpoints[-1][1]:
                breakpoints.append((cum[i] / total, point_modes[i]))
        return breakpoints

    @staticmethod
    def _mode_at_fraction(breakpoints: List[Tuple[float, str]], frac: float) -> str:
        if not breakpoints:
            return "walking"
        mode = breakpoints[0][1]
        for bp_frac, bp_mode in breakpoints:
            if frac >= bp_frac:
                mode = bp_mode
            else:
                break
        return mode

    def _build_overview_path(
        self, points: List, point_modes: Optional[List[str]], num_frames: int
    ) -> Tuple[np.ndarray, List[Tuple[float, str]], Optional[np.ndarray], float]:
        """Builds the animated overview path and, when point_modes is given,
        speed-weights it so faster real-world modes (ferry, car) cover
        ground quicker on screen than a walking leg of the same length.
        Returns (smooth_path, mode_breakpoints, cum_smooth_dist,
        total_smooth_dist) — the latter two are None/1.0 when there's no
        mode data to weight by."""
        # Light dedup only — drop literal near-duplicate points so the spline
        # fit doesn't choke on zero-length segments. We deliberately do NOT
        # thin more aggressively than this by raw distance: a tight turn has
        # its points close together too, and stripping those is exactly what
        # let the smoothed path swing wide of sharp corners (cutting across
        # ground the real road never touches). get_smooth_path's own
        # Douglas-Peucker pass below reduces density based on actual
        # curvature (perpendicular deviation), which is the correct signal.
        filtered_points = [points[0]]
        for pt in points[1:]:
            if (
                math.hypot(
                    pt[0] - filtered_points[-1][0], pt[1] - filtered_points[-1][1]
                )
                > 0.5
            ):
                filtered_points.append(pt)
        # Ensure the final destination is always included
        if filtered_points[-1] != points[-1]:
            filtered_points.append(points[-1])

        mode_breakpoints = self._build_mode_breakpoints(points, point_modes) if point_modes else []

        if mode_breakpoints:
            # Faster real-world modes (ferry, car) should visually cover
            # ground quicker on screen than a walking leg of the same
            # length — sample the path densely first, then pick out
            # `num_frames` of those samples spaced by "speed-weighted"
            # distance rather than raw pixel distance. That compresses the
            # frame budget spent on fast legs and leaves more of it for
            # walking ones, instead of moving at one constant on-screen
            # speed regardless of travel mode.
            dense_n = max(num_frames * 4, 400)
            dense_arr = np.asarray(
                MapFetcher.get_smooth_path(
                    filtered_points, dense_n, ease=True, simplify_tolerance_px=2.2
                ),
                dtype=float,
            )
            seg_lens = np.hypot(np.diff(dense_arr[:, 0]), np.diff(dense_arr[:, 1]))
            cum_dense = np.concatenate([[0.0], np.cumsum(seg_lens)])
            total_dense = cum_dense[-1] or 1.0
            fracs = cum_dense / total_dense
            speeds = np.array(
                [
                    self._mode_speed_factor.get(
                        self._mode_at_fraction(mode_breakpoints, f), 1.0
                    )
                    for f in fracs
                ]
            )
            seg_speed = (speeds[:-1] + speeds[1:]) / 2.0
            virtual_seg = np.where(seg_speed > 0, seg_lens / seg_speed, seg_lens)
            virtual_cum = np.concatenate([[0.0], np.cumsum(virtual_seg)])
            total_virtual = virtual_cum[-1] or 1.0

            target = np.linspace(0.0, total_virtual, num_frames)
            idx = np.clip(np.searchsorted(virtual_cum, target), 1, len(virtual_cum) - 1)
            v0, v1 = virtual_cum[idx - 1], virtual_cum[idx]
            t = np.where(v1 > v0, (target - v0) / (v1 - v0), 0.0)
            smooth_path = dense_arr[idx - 1] + (dense_arr[idx] - dense_arr[idx - 1]) * t[:, None]

            smooth_arr = smooth_path
            final_seg_lens = np.hypot(
                np.diff(smooth_arr[:, 0]), np.diff(smooth_arr[:, 1])
            )
            total_smooth_dist = float(final_seg_lens.sum()) or 1.0
            cum_smooth_dist = np.concatenate([[0.0], np.cumsum(final_seg_lens)])
        else:
            smooth_path = MapFetcher.get_smooth_path(
                filtered_points, num_frames, ease=True, simplify_tolerance_px=2.2
            )
            cum_smooth_dist, total_smooth_dist = None, 1.0

        return smooth_path, mode_breakpoints, cum_smooth_dist, total_smooth_dist
