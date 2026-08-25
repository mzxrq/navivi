"""
MapFetcher Service (mapfetcher.py)
---------------------------------------------------------------------------
Orchestrates geographic data parsing and image downloading.
Imports core geometry and tile downloading from map_engine.py.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import pandas as pd

from services.job_config import JobConfigManager
from services.map_engine import RouteGeometry, RoutePacing, TileDownloader
from services.logger import setup_logger

# Logging configuration
logger = setup_logger("MapFetcher")


# [Core] MapFetcher Class
class MapFetcher:
    """Orchestrates geographic data parsing and image downloading."""

    # [Config] Initialize with optional provider and JobConfigManager
    def __init__(self, provider=None, job_config=None):
        # Bring in JobConfigManager just like the other modules
        self.config = job_config or JobConfigManager()
        self.downloader = TileDownloader(job_config=self.config, provider=provider)

    # [Map] Fetch  image based on a bounding box and save it to a specified filename
    def fetch_image(
        self,
        bounding_box: Dict[str, float],
        output_filename: str,
        output_size: Tuple[int, int] = (1920, 1080),
        max_zoom: int = 19,
    ):
        """Instance method mapping for overview maps."""
        # ---------------------------------------------------------------------
        # DYNAMIC PATH FIX: Route the overview map to the central png directory
        # ---------------------------------------------------------------------
        base_path = Path(self.config.get("directory_path", "assets"))
        png_dir = (base_path / "png").resolve()
        png_dir.mkdir(parents=True, exist_ok=True)

        # Override the filename path to sit correctly in the png folder
        final_filename = str(png_dir / Path(output_filename).name)

        return self.downloader.fetch_overview_image(
            bounding_box, final_filename, output_size, max_zoom
        )

    # [Map] Process a residential sequence based on route DataFrame and waypoints
    def process_residential_sequence(
        self,
        route_df: pd.DataFrame,
        waypoints: List[Dict],
        output_dir: Path,
        output_size: Tuple[int, int] = (1920, 1080),
        max_chunk_distance_meters: float = 1000.0,
        precomputed_indices: Optional[List[int]] = None,
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

        wp_indices = (
            precomputed_indices
            if precomputed_indices is not None
            else RouteGeometry.build_waypoint_index(route_df, waypoints)
        )
        sorted_wps = sorted(zip(wp_indices, waypoints), key=lambda x: x[0])
        wp_indices = [x[0] for x in sorted_wps]
        waypoints = [x[1] for x in sorted_wps]

        segments = [
            (wp_indices[i], wp_indices[i + 1], waypoints[i + 1])
            for i in range(len(wp_indices) - 1)
        ]

        for seg_start, seg_end, wp in segments:
            chunk_starts = [seg_start]
            accumulated_distance = 0.0

            for i in range(seg_start, seg_end):
                lat1, lon1 = route_df.iloc[i][["latitude", "longitude"]]
                lat2, lon2 = route_df.iloc[i + 1][["latitude", "longitude"]]
                dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
                a = (
                    math.sin(dlat / 2.0) ** 2
                    + math.cos(math.radians(lat1))
                    * math.cos(math.radians(lat2))
                    * math.sin(dlon / 2.0) ** 2
                )
                accumulated_distance += 6371000.0 * (2.0 * math.asin(math.sqrt(a)))

                if accumulated_distance >= max_chunk_distance_meters:
                    chunk_starts.append(i + 1)
                    accumulated_distance = 0.0

            if chunk_starts[-1] != seg_end:
                chunk_starts.append(seg_end)

            for chunk_idx in range(len(chunk_starts) - 1):
                chunk_start, chunk_end = (
                    chunk_starts[chunk_idx],
                    chunk_starts[chunk_idx + 1],
                )
                if chunk_start >= chunk_end:
                    continue

                chunk = route_df.iloc[chunk_start : chunk_end + 1]
                lbl_base = "".join(
                    c
                    for c in str(wp.get("label", "Segment"))
                    if c.isalnum() or c in (" ", "_")
                ).rstrip()
                lbl = (
                    f"{lbl_base}_part{chunk_idx + 1}"
                    if len(chunk_starts) > 2
                    else lbl_base
                )

                # Update file path to use the absolute, centralized png directory
                res_map_path = str(png_dir / f"res_map_{lbl}.png")

                res_extent = self.downloader.fetch_residential_chunk(
                    chunk, res_map_path, output_size
                )

                chunk_points, chunk_labels, chunk_popups = [], [], []
                for row_idx, row in chunk.iterrows():
                    px, py = RouteGeometry.project_latlon_to_pixel(
                        row["latitude"],
                        row["longitude"],
                        res_extent,
                        output_size[0],
                        output_size[1],
                    )
                    chunk_points.append([px, py])

                    if row_idx == seg_end:
                        chunk_labels.append(wp.get("label"))
                        chunk_popups.append(
                            {
                                "freeze_seconds": float(wp.get("freeze_seconds", 3.0)),
                                "popup_image": wp.get("popup_image"),
                                "triggered": False,
                            }
                        )
                    else:
                        chunk_labels.append(None)
                        chunk_popups.append(None)

                sequence_data.append(
                    {
                        "start_idx": chunk_start,
                        "end_idx": chunk_end,
                        "img_path": res_map_path,
                        "extent": res_extent,
                        "lats": chunk["latitude"].to_numpy(),
                        "lons": chunk["longitude"].to_numpy(),
                        "points": chunk_points,
                        "labels": chunk_labels,
                        "popups": chunk_popups,
                    }
                )

        return sequence_data

    # [Util/Map] Static method wrappers for RouteGeometry and RoutePacing functionalities
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
