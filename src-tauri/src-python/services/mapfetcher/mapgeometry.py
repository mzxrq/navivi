"""
Map Geometry Service (map_geometry.py)
---------------------------------------------------------------------------
Handles geometry smoothing, time pacing, and downloading map tiles.
Extracted from mapfetcher.py to improve modularity.
---------------------------------------------------------------------------
"""
# [I/O] Import libraries for map fetching and geometry processing
from typing import Final, Tuple, List, Dict
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree  # type: ignore
from scipy.interpolate import make_interp_spline
import math

# [I/O] Import service dependencies for Integration
from services.logger.logger import setup_logger
from services.config.job_config import JobConfigManager

# [Utility] Log setup for debugging and monitoring
logger = setup_logger("MapEngine")

# [Final] Constants for map tile downloading and geometry processing
TARGET_ASPECT_RATIO: Final[float] = 16 / 9
MIN_MAP_WIDTH_PX: Final[int] = 800

# [Map] Map routing geometry smoothing and time pacing parameters
class RouteGeometryProcessor:
    """Processes route geometry for smoothing and time pacing."""

    # [Utility] Get bounding box for a set of lat/lon points
    @staticmethod
    def get_bounding_box(df : pd.DataFrame, padding_factor : float = 0.05, **kwargs) -> Dict[str, float]:
        """Calculate the bounding box with optional padding."""

        min_lat, max_lat = df["latitude"].min(), df["latitude"].max()
        min_lon, max_lon = df["longitude"].min(), df["longitude"].max()

        lat_padding = (max_lat - min_lat) * padding_factor
        lon_padding = (max_lon - min_lon) * padding_factor

        return {
            "min_lat": min_lat - lat_padding,
            "max_lat": max_lat + lat_padding,
            "min_lon": min_lon - lon_padding,
            "max_lon": max_lon + lon_padding,
        }

    # [Map] Project a list of lat/lon points to pixel coordinates based on map extent and image size
    @staticmethod
    def project_to_pixels(
       route_df: pd.DataFrame, waypoints: List[Dict]
    ) -> List[int]:
        """Project lat/lon points to pixel coordinates based on map extent and image size."""

        if route_df.empty or not waypoints:
            return []
        tree = cKDTree(route_df[["latitude", "longitude"]].to_numpy())
        _, indices = tree.query([[wp["lat"], wp["lng"]] for wp in waypoints])
        return np.atleast_1d(indices).tolist()

    # [Map] Find the nearest route_df row index for each waypoint (nearest-neighbor match)
    @staticmethod
    def build_waypoint_index(
        route_df: pd.DataFrame, waypoints: List[Dict]
    ) -> List[int]:
        """For each waypoint, finds the index of the closest point in `route_df`."""
        if route_df.empty or not waypoints:
            return []
        tree = cKDTree(route_df[["latitude", "longitude"]].to_numpy())
        _, indices = tree.query(
            [[wp["lat"], wp.get("lng", wp.get("lon"))] for wp in waypoints]
        )
        return np.atleast_1d(indices).tolist()

    # [Map] Douglas-Peucker algorithm for path simplification
    @staticmethod
    def douglas_peucker(points: List[Tuple[float, float]], tolerance: float, **kwargs) -> List[int]:
        if len(points) < 3:
            return list(range(len(points)))

        pts = np.array(points)
        keep = {0, len(points) - 1}

        def _dp(start, end):
            if end - start <= 1:
                return
            line = pts[end] - pts[start]
            line_len = np.hypot(*line)
            if line_len == 0:
                dists = np.hypot(*(pts[start + 1 : end] - pts[start]).T)
            else:
                norm = np.array([-line[1], line[0]]) / line_len
                dists = np.abs((pts[start + 1 : end] - pts[start]) @ norm)

            max_idx = np.argmax(dists)
            max_dist = dists[max_idx]
            mid = start + 1 + max_idx

            if max_dist > tolerance:
                keep.add(mid)
                _dp(start, mid)
                _dp(mid, end)

        _dp(0, len(points) - 1)
        return sorted(keep)

    # [Map] Easing function for smooth animations
    @staticmethod
    def ease_in_out_cubic(t: np.ndarray) -> np.ndarray:
        return np.where(t < 0.5, 4 * t**3, 1 - ((-2 * t + 2) ** 3) / 2)

    # [Map] Make a cubic B-spline interpolation for smooth path generation
    @staticmethod
    def make_cubic_b_spline(t: np.ndarray, values: np.ndarray, k: int = 3) -> np.ndarray:
        return make_interp_spline(t, values, k=k)

    # [Map] Generate an animated path between waypoints
    @staticmethod
    def get_smooth_path(
        points: List[Tuple[float, float]],
        num_frames: int,
        simplify_tolerance_px: float = 3.0,
        ease: bool = True,
        curve: bool = False,
        **kwargs,
    ) -> np.ndarray:
        """
        Process Description & Calculation Logic:
        1. Noise Reduction: Filters out redundant consecutive points where the Euclidean
           distance is less than 0.1 units to eliminate jitter.
        2. Geometry Simplification: Applies the Douglas-Peucker algorithm to reduce
           unnecessary vertex density along straight segments based on the tolerance threshold.
        3. Edge Case Handling: Returns a static array or zero-matrix if the resulting
           points fall below the minimum threshold required for interpolation.
        4. Cumulative Distance Parameterization: Computes point-to-point Euclidean distances
           via `np.hypot` and builds a cumulative distance array ($cum\_dists$) to map
           out the true spatial length of the route.
        5. Temporal Pacing & Easing: Normalizes path progress into a progress domain ($t$),
           generates linear frame markers across the requested `num_frames`, and optionally
           applies a cubic easing function (`ease_in_out_cubic`) to simulate natural
           acceleration and deceleration curves.
        6. Position Evaluation: By default (`curve=False`) walks the eased frame timestamps
           along the piecewise-STRAIGHT polyline through the simplified points via linear
           interpolation, so the animated position always sits exactly on the real route —
           never bulging outside a sharp turn the way a curve fit through sparse points can.
           Pass `curve=True` to fit a cubic B-spline through the points instead for a
           rounded, cinematic path (at the cost of sometimes cutting corners).
        """

        filtered_pts = [points[0]]
        for p in points[1:]:
            if np.hypot(p[0] - filtered_pts[-1][0], p[1] - filtered_pts[-1][1]) > 0.1:
                filtered_pts.append(p)

        if len(filtered_pts) > 2:
            keep_idx = RouteGeometryProcessor.douglas_peucker(
                filtered_pts, tolerance=simplify_tolerance_px
            )
            filtered_pts = [filtered_pts[i] for i in keep_idx]

        pts = np.array(filtered_pts, dtype=float)
        n = len(pts)
        if n < 2:
            if len(points) > 0:
                return np.array([points[0]] * num_frames)
            return np.zeros((num_frames, 2))

        diffs = np.diff(pts, axis=0)
        dists = np.hypot(diffs[:, 0], diffs[:, 1])
        cum_dists = np.concatenate(([0], np.cumsum(dists)))

        total_dist = cum_dists[-1]
        t = cum_dists / total_dist if total_dist > 0 else np.linspace(0, 1, n)
        t_linear = np.linspace(0, 1, num_frames)
        t_fine = RouteGeometryProcessor.ease_in_out_cubic(t_linear) if ease else t_linear

        if curve:
            k = min(3, n - 1)
            sx = RouteGeometryProcessor.make_cubic_b_spline(t, pts[:, 0], k=k)
            sy = RouteGeometryProcessor.make_cubic_b_spline(t, pts[:, 1], k=k)
            return np.vstack([sx(t_fine), sy(t_fine)]).T

        x = np.interp(t_fine, t, pts[:, 0])
        y = np.interp(t_fine, t, pts[:, 1])
        return np.vstack([x, y]).T

    # [Map] Project a single lat/lon coordinate to pixel coordinates based on map extent and image size
    @staticmethod
    def project_latlon_to_pixel(lat: float, lon: float,extent: Tuple[float, float, float, float],img_w: int,img_h: int) -> List[float]:
        """
        Projects a real-world coordinate to a specific pixel location on a map image.
        
        Calculation Process:
        1. Geographic Projection (Web Mercator EPSG:3857):
           - Flattens the Earth's curved surface onto a 2D plane using a standard radius (6,378,137m).
           - X-axis ($m_x$): Converts longitude to radians and multiplies by the Earth radius.
           - Y-axis ($m_y$): Applies the Mercator logarithm tangent formula to latitude.
        2. Pixel Scaling:
           - X-axis ($p_x$): Finds the horizontal percentage of $m_x$ within the map's bounding box 
             (`extent`) and multiplies by the image width (`img_w`).
           - Y-axis ($p_y$): Finds the vertical percentage of $m_y$, but inverts the axis 
             (subtracting from `max_y`) because computer graphic pixels increment downwards, 
             while geographic coordinates increment upwards (North).
        """

        min_x, max_x, min_y, max_y = extent
        r = 6378137.0
        mx = lon * (r * np.pi / 180.0)
        my = np.log(np.tan((90.0 + lat) * np.pi / 360.0)) * r
        px = (mx - min_x) / (max_x - min_x) * img_w
        py = (max_y - my) / (max_y - min_y) * img_h

        return [float(px), float(py)]

    @staticmethod
    def point_to_segment_distance(
        px: float, py: float, ax: float, ay: float, bx: float, by: float
    ) -> float:
        abx, aby = bx - ax, by - ay
        seg_len_sq = abx * abx + aby * aby
        if seg_len_sq < 1e-9:
            return float(np.hypot(px - ax, py - ay))
        t = max(0.0, min(1.0, ((px - ax) * abx + (py - ay) * aby) / seg_len_sq))
        closest_x, closest_y = ax + t * abx, ay + t * aby
        return float(np.hypot(px - closest_x, py - closest_y))

    @staticmethod
    def is_real_label(lbl: Any) -> bool:
        if lbl is None:
            return False
        if isinstance(lbl, float) and math.isnan(lbl):
            return False
        return str(lbl).strip() != ""