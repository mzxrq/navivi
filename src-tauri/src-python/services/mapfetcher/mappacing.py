"""
Route Pacing Service (map_pacing.py)
---------------------------------------------------------------------------
Handles route pacing and time interpolation for map rendering.
----------------------------------------------------------------------------
"""

# [I/O] Import libraries for map pacing and time interpolation
from typing import List, Dict, Optional
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
    def compute_segment_durations(
        wp_indices: List[int],
        route_df: pd.DataFrame,
        target_avg_seconds: float = 10.0,
        min_segment_seconds: float = 3.0,
        max_segment_seconds: Optional[float] = None,
        seg_modes: Optional[List[str]] = None,
        mode_speeds_kmh: Optional[Dict[str, float]] = None,
    ) -> List[float]:
        """Compute segment durations based on waypoints and route geometry.

        Without seg_modes/mode_speeds_kmh, each leg's on-screen time is
        purely proportional to its GPS distance — a long, fast ferry
        crossing then gets allocated MORE time than a short walking leg,
        the opposite of how it actually feels in real life. When both are
        given, each leg is weighted by distance/speed (i.e. its real-world
        travel time) instead of raw distance, so a fast leg is compressed
        on screen relative to a slow one of similar length.

        max_segment_seconds caps any single leg's on-screen time — the
        proportional split above is relative to the OTHER legs in this
        route, so one unusually long-distance leg (a multi-km walking
        stretch, say) can still end up dragging on for a very long time
        even after the mode weighting, simply because it's much longer
        than its neighbors. The cap keeps navigation feeling brisk
        regardless of how any one leg's distance compares to the rest."""

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

        if seg_modes and mode_speeds_kmh and len(seg_modes) == n_segments:
            fallback_speed = mode_speeds_kmh.get("walking", 5.0) or 5.0
            seg_weights = [
                d / max(0.1, mode_speeds_kmh.get(str(m).lower(), fallback_speed) or fallback_speed)
                for d, m in zip(seg_distances, seg_modes)
            ]
        else:
            seg_weights = seg_distances

        total_weight = sum(seg_weights)
        total_target_time = n_segments * target_avg_seconds

        if total_weight <= 0:
            return [target_avg_seconds] * n_segments

        durations = [
            max(min_segment_seconds, total_target_time * (wt / total_weight))
            for wt in seg_weights
        ]
        if max_segment_seconds is not None:
            durations = [min(d, max_segment_seconds) for d in durations]
        return durations

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
    