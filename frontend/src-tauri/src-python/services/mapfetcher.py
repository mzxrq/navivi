"""
mapfetcher.py
---------------------------------------------------------------------------
Fetches static background map images (via contextily/OSM-style tiles)
for a given route's bounding box and handles geographic route slicing.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Final

import contextily as cx
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image
from scipy.interpolate import make_interp_spline
from scipy.spatial import cKDTree

TARGET_ASPECT_RATIO: Final[float] = 16 / 9
MIN_MAP_WIDTH_PX: Final[int] = 1280
CACHE_DIR: Final[Path] = Path("data\\caches\\contextily")


class MapFetcher:
    def __init__(self, provider=None):
        self.provider = provider if provider else cx.providers.CartoDB.Voyager  # type: ignore

    def get_bounding_box(self, df: pd.DataFrame, padding_factor: float = 0.05) -> dict:
        if df.empty or "latitude" not in df.columns or "longitude" not in df.columns:
            raise ValueError("DataFrame must contain 'latitude' and 'longitude' columns.")

        min_lat = df["latitude"].min()
        max_lat = df["latitude"].max()
        min_lon = df["longitude"].min()
        max_lon = df["longitude"].max()

        lat_padding = (max_lat - min_lat) * padding_factor
        lon_padding = (max_lon - min_lon) * padding_factor

        return {
            "w": min_lon - lon_padding,
            "s": min_lat - lat_padding,
            "e": max_lon + lon_padding,
            "n": max_lat + lat_padding,
        }

    @staticmethod
    def douglas_peucker(points: list, tolerance: float) -> list[int]:
        """
        Returns indices of points to KEEP from the original list.
        Higher tolerance = more aggressive smoothing (fewer points).
        """
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
    def _ease_in_out_cubic(t: np.ndarray) -> np.ndarray:
        """
        Cubic ease-in-out time-warp: remaps a linear [0,1] parameter so
        motion decelerates approaching t=1 and accelerates leaving t=0.
        This is what actually reads as "slow, deliberate" navigation —
        a marker that eases into each waypoint instead of arriving at
        constant speed and stopping abruptly. Applied to the SAMPLING
        parameter only; the underlying spline geometry is unaffected.
        """
        return np.where(t < 0.5, 4 * t ** 3, 1 - ((-2 * t + 2) ** 3) / 2)

    @staticmethod
    def get_smooth_path(points: list, num_frames: int, simplify_tolerance_px: float = 3.0, ease: bool = True) -> np.ndarray:
        filtered_pts = [points[0]]
        for p in points[1:]:
            if np.hypot(p[0] - filtered_pts[-1][0], p[1] - filtered_pts[-1][1]) > 0.1:
                filtered_pts.append(p)

        # Douglas-Peucker pass: keeps only the points that are
        # geometrically necessary (turns, curves) and drops GPS-noise
        # points that sit within `simplify_tolerance_px` of the straight
        # line between their neighbors. Runs AFTER the exact-duplicate
        # filter above and BEFORE the spline fit, so the spline gets
        # clean control points instead of raw jitter to interpolate
        # through — this is what actually makes the rendered line look
        # smooth on straightaways rather than wobbly.
        if len(filtered_pts) > 2:
            keep_idx = MapFetcher.douglas_peucker(filtered_pts, tolerance=simplify_tolerance_px)
            filtered_pts = [filtered_pts[i] for i in keep_idx]

        pts = np.array(filtered_pts, dtype=float)
        n = len(pts)
        if n < 2:
            if len(points) > 0:
                return np.array([points[0]] * num_frames)
            else:
                return np.zeros((num_frames, 2))

        diffs = np.diff(pts, axis=0)
        dists = np.hypot(diffs[:, 0], diffs[:, 1])
        cum_dists = np.concatenate(([0], np.cumsum(dists)))

        total_dist = cum_dists[-1]
        t = cum_dists / total_dist if total_dist > 0 else np.linspace(0, 1, n)

        t_linear = np.linspace(0, 1, num_frames)
        # Warp the sampling parameter through the ease curve instead of
        # sampling at constant-speed intervals — spline shape unchanged,
        # only traversal speed along it changes.
        t_fine = MapFetcher._ease_in_out_cubic(t_linear) if ease else t_linear

        k = min(3, n - 1)
        sx = make_interp_spline(t, pts[:, 0], k=k)
        sy = make_interp_spline(t, pts[:, 1], k=k)
        return np.vstack([sx(t_fine), sy(t_fine)]).T

    @staticmethod
    def compute_segment_durations(waypoints: list, wp_indices: list, route_df: pd.DataFrame, target_avg_seconds: float = 10.0, min_segment_seconds: float = 3.0) -> list[float]:
        """
        Allocates animation time per waypoint-to-waypoint segment so the
        AVERAGE across all segments equals target_avg_seconds, weighted
        by each segment's real-world (haversine) distance. A long
        segment gets proportionally more screen time than a short one,
        but the mean over the whole route stays pinned to
        target_avg_seconds — "average 10s per waypoint" while still
        giving long stretches room to breathe and short hops a quick
        beat instead of a wasted lingering shot.
        """
        n_segments = len(wp_indices) - 1
        if n_segments <= 0:
            return []

        # Reuses the single source of truth for haversine distance that
        # already lives in gpsparser.py rather than reimplementing it.
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
            # Degenerate case (all segments effectively zero-length):
            # split time evenly rather than dividing by zero.
            return [target_avg_seconds] * n_segments

        # Proportional allocation with a floor so no segment animates in
        # an imperceptibly short window regardless of how tiny it is.
        return [max(min_segment_seconds, total_target_time * (d / total_distance)) for d in seg_distances]

    @staticmethod
    def compute_chunk_durations(sequence_data: list[dict], target_avg_seconds: float = 10.0, min_chunk_seconds: float = 3.0) -> list[float]:
        """
        Same distance-proportional/averaging idea as
        compute_segment_durations, but operates directly on the ALREADY
        RENDERED chunks from generate_residential_sequence(). That
        function can split one waypoint-to-waypoint segment into several
        sub-chunks (max_chunk_distance_meters), so allocating time per
        raw waypoint pair and per rendered chunk are not the same thing
        — this keeps "average N seconds" honest against what's actually
        shown on screen, by averaging over the rendered chunk count.
        """
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

    @staticmethod
    def build_waypoint_index(route_df: pd.DataFrame, waypoints: list) -> list[int]:
        """
        Single source of truth for 'which route row is closest to each
        waypoint'. Previously this exact computation — an O(n) linear
        np.hypot(...).argmin() scan PER waypoint — was duplicated
        verbatim in generate_residential_sequence() and in
        main.py::generate_navigation_video(), so a route with n points
        and m waypoints paid O(n*m) work TWICE per pipeline run for an
        identical result.

        A cKDTree amortizes an O(n log n) build once, then answers each
        waypoint query in O(log n) instead of O(n). Callers should build
        this ONCE per route_df and thread the result through both call
        sites rather than letting each recompute it independently.
        """
        if route_df.empty or not waypoints:
            return []
        tree = cKDTree(route_df[["latitude", "longitude"]].to_numpy())
        _, indices = tree.query([[wp["lat"], wp["lng"]] for wp in waypoints])
        # cKDTree.query returns a scalar (not an array) when there's a
        # single query point — normalize to a list either way.
        return np.atleast_1d(indices).tolist()

    def fetch_image(
        self,
        bounding_box: dict,
        output_filename: str = "data\\inputs\\imagemap_background.png",
        output_size: tuple[int, int] = (1920, 1080),
        max_zoom: int = 19,
    ) -> tuple[str, tuple[float, float, float, float], tuple[int, int]]:
        out_w, out_h = output_size
        w = bounding_box.get("w", bounding_box.get("min_lon"))
        s = bounding_box.get("s", bounding_box.get("min_lat"))
        e = bounding_box.get("e", bounding_box.get("max_lon"))
        n = bounding_box.get("n", bounding_box.get("max_lat"))

        center_lat = (s + n) / 2.0
        lat_span = n - s
        lon_span = e - w
        target_ratio = out_w / out_h
        lon_scale = math.cos(math.radians(center_lat))
        current_ratio = (lon_span * lon_scale) / lat_span

        if current_ratio < target_ratio:
            new_lon_span = (lat_span * target_ratio) / lon_scale
            expansion = (new_lon_span - lon_span) / 2.0
            w -= expansion
            e += expansion
        else:
            new_lat_span = (lon_span * lon_scale) / target_ratio
            expansion = (new_lat_span - lat_span) / 2.0
            s -= expansion
            n += expansion
        
        cache_dir = Path("data\\caches\\contextily")
        cache_dir.mkdir(exist_ok=True) 
        cx.set_cache_dir(str(cache_dir))

        optimal_zoom = max_zoom
        for z in range(max_zoom, 0, -1):
            if cx.howmany(w, s, e, n, z, ll=True) <= 30:
                optimal_zoom = z
                break

        img, extent = None, None
        while optimal_zoom > 0:
            try:
                img, extent = cx.bounds2img(w, s, e, n, ll=True, source=self.provider, zoom=optimal_zoom, use_cache=str(cache_dir)) 
                break  
            except Exception:
                optimal_zoom -= 1

        if img is None or extent is None:
            raise RuntimeError("Failed to download map tiles at any zoom level.")

        cropped_img, new_extent = MapFetcher._crop_to_aspect_ratio(img, extent, target_ratio)
        Image.fromarray(cropped_img).resize(output_size, Image.LANCZOS).convert("RGB").save(output_filename)

        return output_filename, new_extent, (out_w, out_h)

    @staticmethod
    def _crop_to_aspect_ratio(img: np.ndarray, ext: tuple, target_ratio: float) -> tuple[np.ndarray, tuple]:
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

    @staticmethod
    def get_residential_map(chunk_df: pd.DataFrame, output_filename: str = "residential_map.png", output_size: tuple[int, int] = (1920, 1080)):
        if chunk_df.empty:
            raise ValueError("Chunk DataFrame is empty.")

        start_lat, start_lon = float(chunk_df["latitude"].iloc[0]), float(chunk_df["longitude"].iloc[0])
        end_lat, end_lon = float(chunk_df["latitude"].iloc[-1]), float(chunk_df["longitude"].iloc[-1])

        min_lat = min(chunk_df["latitude"].min(), start_lat, end_lat)
        max_lat = max(chunk_df["latitude"].max(), start_lat, end_lat)
        min_lon = min(chunk_df["longitude"].min(), start_lon, end_lon)
        max_lon = max(chunk_df["longitude"].max(), start_lon, end_lon)

        center_lat = (min_lat + max_lat) / 2.0
        lat_span = max_lat - min_lat
        lon_span = max_lon - min_lon

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
            w -= expansion
            e += expansion
        else:
            new_lat_span = ((e - w) * lon_scale) / target_ratio
            expansion = (new_lat_span - (n - s)) / 2.0
            s -= expansion
            n += expansion

        os.makedirs(CACHE_DIR, exist_ok=True)
        cx.set_cache_dir(str(CACHE_DIR))

        img, extent = None, None
        while optimal_zoom > 0:
            try:
                img, extent = cx.bounds2img(w, s, e, n, ll=True, zoom=optimal_zoom, source=cx.providers.CartoDB.Voyager, use_cache=str(CACHE_DIR))
                break
            except Exception:
                optimal_zoom -= 1

        if img is None or extent is None:
            raise RuntimeError("Failed to download map tiles for chunk.")

        cropped_img, new_extent = MapFetcher._crop_to_aspect_ratio(img, extent, target_ratio)
        Image.fromarray(cropped_img).resize(output_size, Image.LANCZOS).convert("RGB").save(output_filename)
        return new_extent

    @staticmethod
    def generate_residential_sequence(route_df: pd.DataFrame, waypoints: list, output_dir: Path, output_size: tuple[int, int] = (1920, 1080), max_chunk_distance_meters: float = 1000.0, precomputed_indices: list[int] | None = None) -> list[dict]:
        sequence_data = []
        os.makedirs(output_dir, exist_ok=True)
        if route_df.empty or not waypoints:
            return sequence_data

        # Accept caller-supplied indices (e.g. already computed once in
        # main.py) to avoid a second O(n log n)/O(n*m) pass over the same
        # route_df/waypoints pair; only fall back to computing them here
        # if this is called standalone.
        wp_indices = precomputed_indices if precomputed_indices is not None else MapFetcher.build_waypoint_index(route_df, waypoints)
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
                res_map_path = str(output_dir / f"res_map_{lbl}.png")

                res_extent = MapFetcher.get_residential_map(chunk, res_map_path, output_size)
                img_w, img_h = output_size
                min_x, max_x, min_y, max_y = res_extent
                r = 6378137.0

                chunk_points, chunk_labels, chunk_popups = [], [], []
                for row_idx, row in chunk.iterrows():
                    mx = row["longitude"] * (r * np.pi / 180.0)
                    my = np.log(np.tan((90.0 + row["latitude"]) * np.pi / 360.0)) * r
                    px = (mx - min_x) / (max_x - min_x) * img_w
                    py = (max_y - my) / (max_y - min_y) * img_h
                    chunk_points.append([float(px), float(py)])

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