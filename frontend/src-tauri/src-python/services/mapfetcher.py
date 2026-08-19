"""
mapfetcher.py (OOP Refactored)
---------------------------------------------------------------------------
Fetches static background map images (via contextily/OSM-style tiles)
for a given route's bounding box and handles geographic route slicing.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Final, Dict, List, Tuple, Optional, Any

import contextily as cx
import numpy as np
import pandas as pd
from PIL import Image
from scipy.interpolate import make_interp_spline
from scipy.spatial import cKDTree  # type: ignore

from services.job_config import JobConfigManager

# =============================================================================
# CONSTANTS
# =============================================================================

TARGET_ASPECT_RATIO: Final[float] = 16 / 9
MIN_MAP_WIDTH_PX: Final[int] = 1280

# =============================================================================
# GEOMETRY & MATH ENGINE
# =============================================================================

class RouteGeometry:
    """Handles spatial mathematics, index building, smoothing, and projections."""

    @staticmethod
    def get_bounding_box(df: pd.DataFrame, padding_factor: float = 0.05) -> Dict[str, float]:
        if df.empty or "latitude" not in df.columns or "longitude" not in df.columns:
            raise ValueError("DataFrame must contain 'latitude' and 'longitude' columns.")

        min_lat, max_lat = df["latitude"].min(), df["latitude"].max()
        min_lon, max_lon = df["longitude"].min(), df["longitude"].max()

        lat_padding = (max_lat - min_lat) * padding_factor
        lon_padding = (max_lon - min_lon) * padding_factor

        return {
            "w": min_lon - lon_padding,
            "s": min_lat - lat_padding,
            "e": max_lon + lon_padding,
            "n": max_lat + lat_padding,
        }

    @staticmethod
    def build_waypoint_index(route_df: pd.DataFrame, waypoints: List[Dict]) -> List[int]:
        if route_df.empty or not waypoints:
            return []
        tree = cKDTree(route_df[["latitude", "longitude"]].to_numpy())
        _, indices = tree.query([[wp["lat"], wp["lng"]] for wp in waypoints])
        return np.atleast_1d(indices).tolist()

    @staticmethod
    def douglas_peucker(points: List[Tuple[float, float]], tolerance: float) -> List[int]:
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
                dists = np.hypot(*(pts[start+1:end] - pts[start]).T)
            else:
                norm = np.array([-line[1], line[0]]) / line_len
                dists = np.abs((pts[start+1:end] - pts[start]) @ norm)

            max_idx = np.argmax(dists)
            max_dist = dists[max_idx]
            mid = start + 1 + max_idx

            if max_dist > tolerance:
                keep.add(mid)
                _dp(start, mid)
                _dp(mid, end)

        _dp(0, len(points) - 1)
        return sorted(keep)

    @staticmethod
    def ease_in_out_cubic(t: np.ndarray) -> np.ndarray:
        return np.where(t < 0.5, 4 * t ** 3, 1 - ((-2 * t + 2) ** 3) / 2)

    @staticmethod
    def get_smooth_path(points: List[Tuple[float, float]], num_frames: int, simplify_tolerance_px: float = 3.0, ease: bool = True) -> np.ndarray:
        filtered_pts = [points[0]]
        for p in points[1:]:
            if np.hypot(p[0] - filtered_pts[-1][0], p[1] - filtered_pts[-1][1]) > 0.1:
                filtered_pts.append(p)

        if len(filtered_pts) > 2:
            keep_idx = RouteGeometry.douglas_peucker(filtered_pts, tolerance=simplify_tolerance_px)
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
        t_fine = RouteGeometry.ease_in_out_cubic(t_linear) if ease else t_linear

        k = min(3, n - 1)
        sx = make_interp_spline(t, pts[:, 0], k=k)
        sy = make_interp_spline(t, pts[:, 1], k=k)
        return np.vstack([sx(t_fine), sy(t_fine)]).T

    @staticmethod
    def project_latlon_to_pixel(lat: float, lon: float, extent: Tuple[float, float, float, float], img_w: int, img_h: int) -> List[float]:
        """Projects a single real-world coordinate to a pixel on the generated map tile."""
        min_x, max_x, min_y, max_y = extent
        r = 6378137.0
        mx = lon * (r * np.pi / 180.0)
        my = np.log(np.tan((90.0 + lat) * np.pi / 360.0)) * r
        px = (mx - min_x) / (max_x - min_x) * img_w
        py = (max_y - my) / (max_y - min_y) * img_h
        return [float(px), float(py)]


# =============================================================================
# TIME ALLOCATION & PACING
# =============================================================================

class RoutePacing:
    """Calculates temporal durations based on physical geographic distances."""

    @staticmethod
    def compute_segment_durations(waypoints: List[Dict], wp_indices: List[int], route_df: pd.DataFrame, target_avg_seconds: float = 10.0, min_segment_seconds: float = 3.0) -> List[float]:
        n_segments = len(wp_indices) - 1
        if n_segments <= 0:
            return []

        from services.gpsparser import haversine_vectorized

        seg_distances = []
        for i in range(n_segments):
            start_idx, end_idx = wp_indices[i], wp_indices[i + 1]
            chunk = route_df.iloc[start_idx:end_idx + 1]
            if len(chunk) > 1:
                lat1, lon1 = chunk["latitude"].to_numpy()[:-1], chunk["longitude"].to_numpy()[:-1]
                lat2, lon2 = chunk["latitude"].to_numpy()[1:], chunk["longitude"].to_numpy()[1:]
                seg_distances.append(float(np.nansum(haversine_vectorized(lat1, lon1, lat2, lon2))))
            else:
                seg_distances.append(0.0)

        total_distance = sum(seg_distances)
        total_target_time = n_segments * target_avg_seconds

        if total_distance <= 0:
            return [target_avg_seconds] * n_segments

        return [max(min_segment_seconds, total_target_time * (d / total_distance)) for d in seg_distances]

    @staticmethod
    def compute_chunk_durations(sequence_data: List[Dict], target_avg_seconds: float = 10.0, min_chunk_seconds: float = 3.0) -> List[float]:
        n_chunks = len(sequence_data)
        if n_chunks == 0:
            return []

        chunk_distances = []
        for item in sequence_data:
            lats, lons = item.get("lats"), item.get("lons")
            if lats is not None and len(lats) > 1:
                lat1, lon1 = np.asarray(lats)[:-1], np.asarray(lons)[:-1]
                lat2, lon2 = np.asarray(lats)[1:], np.asarray(lons)[1:]
                dlat, dlon = np.radians(lat2 - lat1), np.radians(lon2 - lon1)
                a = np.sin(dlat / 2.0) ** 2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon / 2.0) ** 2
                chunk_distances.append(float(np.nansum(6371000.0 * 2.0 * np.arcsin(np.sqrt(a)))))
            else:
                chunk_distances.append(0.0)

        total_distance = sum(chunk_distances)
        total_target_time = n_chunks * target_avg_seconds

        if total_distance <= 0:
            return [target_avg_seconds] * n_chunks

        return [max(min_chunk_seconds, total_target_time * (d / total_distance)) for d in chunk_distances]


# =============================================================================
# TILE DOWNLOADER
# =============================================================================

class TileDownloader:
    """Manages contextily maps, cache directories, zoom logic, and image cropping."""

    def __init__(self, job_config=None, provider=None):
        self.config = job_config or JobConfigManager()
        
        base_path = Path(self.config.get("directory_path", "data/caches/contextily"))
        self.cache_dir = (base_path / "cache").resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        cx.set_cache_dir(str(self.cache_dir))
        self.provider = provider if provider else cx.providers.CartoDB.Voyager # pyright: ignore[reportAttributeAccessIssue]

    def _force_png_path(self, filepath: str) -> Path:
        """Ensures the file is saved inside a 'png' directory and creates it if missing."""
        path = Path(filepath)
        if path.parent.name.lower() != "png":
            path = path.parent / "png" / path.name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def fetch_overview_image(self, bbox: Dict[str, float], output_filename: str, output_size: Tuple[int, int] = (1920, 1080), max_zoom: int = 19) -> Tuple[str, Tuple[float, float, float, float], Tuple[int, int]]:
        out_w, out_h = output_size
        w, s = bbox.get("w", bbox.get("min_lon")), bbox.get("s", bbox.get("min_lat"))
        e, n = bbox.get("e", bbox.get("max_lon")), bbox.get("n", bbox.get("max_lat"))

        if s is not None and n is not None and e is not None and w is not None:
            center_lat = (s + n) / 2.0
            lat_span, lon_span = n - s, e - w
        else:
            pass

        target_ratio = out_w / out_h
        lon_scale = math.cos(math.radians(center_lat))
        current_ratio = (lon_span * lon_scale) / lat_span

        if s is not None and n is not None and e is not None and w is not None:
            center_lat = (s + n) / 2.0
            lat_span, lon_span = n - s, e - w

            if current_ratio < target_ratio:
                    new_lon_span = (lat_span * target_ratio) / lon_scale
                    expansion = (new_lon_span - lon_span) / 2.0
                    w, e = w - expansion, e + expansion
            else:
                    new_lat_span = (lon_span * lon_scale) / target_ratio
                    expansion = (new_lat_span - lat_span) / 2.0
                    s, n = s - expansion, n + expansion
        
        optimal_zoom = max_zoom
        for z in range(max_zoom, 0, -1):
            if cx.howmany(w, s, e, n, z, ll=True) <= 30:
                optimal_zoom = z
                break

        img, extent = None, None
        while optimal_zoom > 0:
            try:
                img, extent = cx.bounds2img(w, s, e, n, ll=True, source=self.provider, zoom=optimal_zoom, use_cache=str(self.cache_dir)) # pyright: ignore[reportArgumentType]
                break  
            except Exception:
                optimal_zoom -= 1

        if img is None or extent is None:
            raise RuntimeError("Failed to download map tiles at any zoom level.")

        # Force the output to go to a /png/ directory
        final_path = self._force_png_path(output_filename)
        
        cropped_img, new_extent = self._crop_to_aspect_ratio(img, extent, target_ratio)
        Image.fromarray(cropped_img).resize(output_size, Image.Resampling.LANCZOS).convert("RGB").save(final_path)

        return str(final_path), new_extent, (out_w, out_h)

    def fetch_residential_chunk(self, chunk_df: pd.DataFrame, output_filename: str, output_size: Tuple[int, int] = (1920, 1080)) -> Tuple[float, float, float, float]:
        if chunk_df.empty:
            raise ValueError("Chunk DataFrame is empty.")

        start_lat, start_lon = float(chunk_df["latitude"].iloc[0]), float(chunk_df["longitude"].iloc[0])
        end_lat, end_lon = float(chunk_df["latitude"].iloc[-1]), float(chunk_df["longitude"].iloc[-1])

        min_lat = min(chunk_df["latitude"].min(), start_lat, end_lat)
        max_lat = max(chunk_df["latitude"].max(), start_lat, end_lat)
        min_lon = min(chunk_df["longitude"].min(), start_lon, end_lon)
        max_lon = max(chunk_df["longitude"].max(), start_lon, end_lon)

        center_lat = (min_lat + max_lat) / 2.0
        lat_span, lon_span = max_lat - min_lat, max_lon - min_lon

        meters_per_deg_lat = 111_320.0
        meters_per_deg_lon = 111_320.0 * math.cos(math.radians(center_lat))
        span_meters = max(lat_span * meters_per_deg_lat, lon_span * meters_per_deg_lon)

        optimal_zoom = 19 if span_meters <= 300 else (18 if span_meters <= 600 else (17 if span_meters <= 1200 else (16 if span_meters <= 2500 else 15)))

        s, n = min_lat - lat_span * 0.03, max_lat + lat_span * 0.03
        w, e = min_lon - lon_span * 0.03, max_lon + lon_span * 0.03

        out_w, out_h = output_size
        target_ratio = out_w / out_h
        lon_scale = math.cos(math.radians(center_lat))
        current_ratio = ((e - w) * lon_scale) / (n - s)

        if current_ratio < target_ratio:
            new_lon_span = ((n - s) * target_ratio) / lon_scale
            expansion = (new_lon_span - (e - w)) / 2.0
            w, e = w - expansion, e + expansion
        else:
            new_lat_span = ((e - w) * lon_scale) / target_ratio
            expansion = (new_lat_span - (n - s)) / 2.0
            s, n = s - expansion, n + expansion

        img, extent = None, None
        while optimal_zoom > 0:
            try:
                img, extent = cx.bounds2img(w, s, e, n, ll=True, zoom=optimal_zoom, source=self.provider, use_cache=str(self.cache_dir)) # pyright: ignore[reportArgumentType]
                break
            except Exception:
                optimal_zoom -= 1

        if img is None or extent is None:
            raise RuntimeError("Failed to download map tiles for chunk.")

        # Force the output to go to a /png/ directory
        final_path = self._force_png_path(output_filename)

        cropped_img, new_extent = self._crop_to_aspect_ratio(img, extent, target_ratio)
        Image.fromarray(cropped_img).resize(output_size, Image.Resampling.LANCZOS).convert("RGB").save(final_path)
        return new_extent

    def _crop_to_aspect_ratio(self, img: np.ndarray, ext: Tuple, target_ratio: float) -> Tuple[np.ndarray, Tuple]:
        h, w = img.shape[:2]
        min_x, max_x, min_y, max_y = ext
        current_ratio = w / h
        if abs(current_ratio - target_ratio) < 1e-6:
            return img, ext

        if current_ratio > target_ratio:
            target_w = int(round(h * target_ratio))
            x0 = (w - target_w) // 2
            meters_per_px_x = (max_x - min_x) / w
            return img[:, x0:x0 + target_w], (min_x + x0 * meters_per_px_x, max_x - (w - target_w - x0) * meters_per_px_x, min_y, max_y)
        else:
            target_h = int(round(w / target_ratio))
            y0 = (h - target_h) // 2
            meters_per_px_y = (max_y - min_y) / h
            return img[y0:y0 + target_h, :], (min_x, max_x, max_y - y0 * meters_per_px_y, min_y + (h - target_h - y0) * meters_per_px_y)


# =============================================================================
# FACADE & ORCHESTRATOR
# =============================================================================

class MapFetcher:
    """Orchestrates geographic data parsing and image downloading."""

    def __init__(self, provider=None, job_config=None):
        # 1. Bring in JobConfigManager just like the other modules
        self.config = job_config or JobConfigManager()
        self.downloader = TileDownloader(job_config=self.config, provider=provider)

    def fetch_image(self, bounding_box: Dict[str, float], output_filename: str, output_size: Tuple[int, int] = (1920, 1080), max_zoom: int = 19):
        """Instance method mapping for overview maps."""
        # ---------------------------------------------------------------------
        # DYNAMIC PATH FIX: Route the overview map to the central png directory
        # ---------------------------------------------------------------------
        base_path = Path(self.config.get("directory_path", "assets"))
        png_dir = (base_path / "png").resolve()
        png_dir.mkdir(parents=True, exist_ok=True)
        
        # Override the filename path to sit correctly in the png folder
        final_filename = str(png_dir / Path(output_filename).name)
        
        return self.downloader.fetch_overview_image(bounding_box, final_filename, output_size, max_zoom)

    def process_residential_sequence(
        self, route_df: pd.DataFrame, waypoints: List[Dict], output_dir: Path, 
        output_size: Tuple[int, int] = (1920, 1080), 
        max_chunk_distance_meters: float = 1000.0, 
        precomputed_indices: Optional[List[int]] = None
    ) -> List[Dict]:
        """Core orchestrator logic utilizing the dedicated Downloader and Geometry classes."""
        sequence_data = []
        
        # ---------------------------------------------------------------------
        # DYNAMIC PATH FIX: Route all residential chunks to the central png directory
        # ---------------------------------------------------------------------
        base_path = Path(self.config.get("directory_path", "assets"))
        png_dir = (base_path / "png").resolve()
        png_dir.mkdir(parents=True, exist_ok=True)
        
        if route_df.empty or not waypoints:
            return sequence_data

        wp_indices = precomputed_indices if precomputed_indices is not None else RouteGeometry.build_waypoint_index(route_df, waypoints)
        sorted_wps = sorted(zip(wp_indices, waypoints), key=lambda x: x[0])
        wp_indices = [x[0] for x in sorted_wps]
        waypoints = [x[1] for x in sorted_wps]

        segments = [(wp_indices[i], wp_indices[i+1], waypoints[i+1]) for i in range(len(wp_indices) - 1)]

        for seg_start, seg_end, wp in segments:
            chunk_starts = [seg_start]
            accumulated_distance = 0.0

            for i in range(seg_start, seg_end):
                lat1, lon1 = route_df.iloc[i][["latitude", "longitude"]]
                lat2, lon2 = route_df.iloc[i+1][["latitude", "longitude"]]
                dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
                a = math.sin(dlat / 2.0)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2.0)**2
                accumulated_distance += 6371000.0 * (2.0 * math.asin(math.sqrt(a)))

                if accumulated_distance >= max_chunk_distance_meters:
                    chunk_starts.append(i + 1)
                    accumulated_distance = 0.0

            if chunk_starts[-1] != seg_end:
                chunk_starts.append(seg_end)

            for chunk_idx in range(len(chunk_starts) - 1):
                chunk_start, chunk_end = chunk_starts[chunk_idx], chunk_starts[chunk_idx + 1]
                if chunk_start >= chunk_end:
                    continue

                chunk = route_df.iloc[chunk_start : chunk_end + 1]
                lbl_base = "".join(c for c in str(wp.get("label", "Segment")) if c.isalnum() or c in (' ', '_')).rstrip()
                lbl = f"{lbl_base}_part{chunk_idx + 1}" if len(chunk_starts) > 2 else lbl_base
                
                # Update file path to use the absolute, centralized png directory
                res_map_path = str(png_dir / f"res_map_{lbl}.png")

                res_extent = self.downloader.fetch_residential_chunk(chunk, res_map_path, output_size)
                
                chunk_points, chunk_labels, chunk_popups = [], [], []
                for row_idx, row in chunk.iterrows():
                    px, py = RouteGeometry.project_latlon_to_pixel(row["latitude"], row["longitude"], res_extent, output_size[0], output_size[1])
                    chunk_points.append([px, py])

                    if row_idx == seg_end:
                        chunk_labels.append(wp.get("label"))
                        chunk_popups.append({"freeze_seconds": float(wp.get("freeze_seconds", 3.0)), "popup_image": wp.get("popup_image"), "triggered": False})
                    else:
                        chunk_labels.append(None)
                        chunk_popups.append(None)

                sequence_data.append({
                    "start_idx": chunk_start, "end_idx": chunk_end,
                    "img_path": res_map_path, "extent": res_extent,
                    "lats": chunk["latitude"].to_numpy(),
                    "lons": chunk["longitude"].to_numpy(),
                    "points": chunk_points, "labels": chunk_labels, "popups": chunk_popups
                })

        return sequence_data

    # --- Backwards Compatibility Wrappers ---
    @staticmethod
    def get_bounding_box(*args, **kwargs):
        return RouteGeometry.get_bounding_box(*args, **kwargs)

    @staticmethod
    def build_waypoint_index(*args, **kwargs):
        return RouteGeometry.build_waypoint_index(*args, **kwargs)

    @staticmethod
    def douglas_peucker(*args, **kwargs):
        return RouteGeometry.douglas_peucker(*args, **kwargs)

    @staticmethod
    def get_smooth_path(*args, **kwargs):
        return RouteGeometry.get_smooth_path(*args, **kwargs)

    @staticmethod
    def compute_segment_durations(*args, **kwargs):
        return RoutePacing.compute_segment_durations(*args, **kwargs)

    @staticmethod
    def compute_chunk_durations(*args, **kwargs):
        return RoutePacing.compute_chunk_durations(*args, **kwargs)

    @staticmethod
    def generate_residential_sequence(*args, **kwargs):
        return MapFetcher().process_residential_sequence(*args, **kwargs)