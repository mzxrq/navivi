"""
Route Pacing Service (map_pacing.py)
--------------------------------------------------------------------------- 
Handles route pacing and time interpolation for map rendering.
----------------------------------------------------------------------------
"""

# [I/O] Import libraries for map pacing and time interpolation
from typing import List, Dict
import numpy as np
import pandas as pd

# [I/O] Import service dependencies for Integration
from services.gpsparser.gpscalculator import GPSMath
from services.logger.logger import setup_logger

# [Utility] Log setup for debugging and monitoring
logger = setup_logger("MapPacing")

class RoutePacingProcessor:
    """Processes route pacing and time interpolation for map rendering."""

    # [Map] Interpolate timestamps for a route based on distance and speed
    @staticmethod
    def compute_segment_durations(wp_indices: List[int], route_df: pd.DataFrame, target_avg_seconds: float = 10.0, min_segment_seconds: float = 3.0) -> List[float]:
        """ Compute segment durations based on waypoints and route geometry. """

        n_segments = len(wp_indices) - 1
        if n_segments <= 0: return []

        seg_distances = []
        
        for i in range(n_segments):
            start_idx, end_idx = wp_indices[i], wp_indices[i + 1]
            chunk = route_df.iloc[start_idx : end_idx + 1]
            if len(chunk) > 1:
                lat1, lon1 = (
                    chunk["latitude"].to_numpy()[:-1],
                    chunk["longitude"].to_numpy()[:-1],
                )
                lat2, lon2 = (
                    chunk["latitude"].to_numpy()[1:],
                    chunk["longitude"].to_numpy()[1:],
                )

                seg_distances.append(float(np.nansum(GPSMath.haversine_vectorized(lat1, lon1, lat2, lon2))))

            else:
                seg_distances.append(0.0)

        total_distance = sum(seg_distances)
        total_target_time = n_segments * target_avg_seconds

        if total_distance <= 0:
            return [target_avg_seconds] * n_segments

        return [
            max(min_segment_seconds, total_target_time * (d / total_distance))
            for d in seg_distances
        ]

    # [Map] Compute chunked timestamps for a route based on segment durations
    @staticmethod
    def compute_chunk_durations(
        sequence_data: List[Dict],
        target_avg_seconds: float = 10.0,
        min_chunk_seconds: float = 3.0,
    ) -> List[float]:
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
                a = (
                    np.sin(dlat / 2.0) ** 2
                    + np.cos(np.radians(lat1))
                    * np.cos(np.radians(lat2))
                    * np.sin(dlon / 2.0) ** 2
                )
                chunk_distances.append(
                    float(np.nansum(6371000.0 * 2.0 * np.arcsin(np.sqrt(a))))
                )
            else:
                chunk_distances.append(0.0)

        total_distance = sum(chunk_distances)
        total_target_time = n_chunks * target_avg_seconds

        if total_distance <= 0:
            return [target_avg_seconds] * n_chunks

        return [
            max(min_chunk_seconds, total_target_time * (d / total_distance))
            for d in chunk_distances
        ]
    