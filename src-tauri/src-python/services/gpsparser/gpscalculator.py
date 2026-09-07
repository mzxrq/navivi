"""
GPS Calculator
-------------------------------------------
This module provides a utility class for calculating distances and bearings between GPS coordinates.
It includes methods for calculating the distance between two points using the Haversine formula and for calculating
bearings between points.
--------------------------------------------
"""

# [I/O] Import dependencies for GPS calculations
import numpy as np
import pandas as pd
from typing import Dict, Any

class GPSMath:
    """Handles vector-based spatial and geographic calculations."""

    # [GPS] Haversine formula for distance between two lat/lon points
    @staticmethod
    def haversine_vectorized(
        lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray
    ) -> np.ndarray:
        """Calculate the great circle distance between points using NumPy."""
        R = 6371.0
        lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])

        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = (
            np.sin(dlat / 2.0) ** 2
            + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
        )
        c = 2 * np.arcsin(np.sqrt(a))
        return R * c

    # [GPS] Compute total distance and duration from a route DataFrame
    @staticmethod
    def compute_route_summary(
        route_df: pd.DataFrame, waypoints_df: pd.DataFrame
    ) -> Dict[str, Any]:
        """Single source of truth for route-level distance and duration metrics."""
        total_distance_km = 0.0
        total_duration_seconds = 0.0

        if not route_df.empty:
            if "timestamp" in route_df.columns:
                ordered = route_df.sort_values("timestamp")
                total_duration_seconds = (
                    ordered["timestamp"].max() - ordered["timestamp"].min()
                ).total_seconds()

            if "latitude" in route_df.columns and "longitude" in route_df.columns:
                lat1, lon1 = route_df["latitude"], route_df["longitude"]
                lat2, lon2 = route_df["latitude"].shift(-1), route_df[
                    "longitude"
                ].shift(-1)
                total_distance_km = float(
                    np.nansum(
                        GPSMath.haversine_vectorized(
                            lat1.to_numpy(),
                            lon1.to_numpy(),
                            lat2.to_numpy(),
                            lon2.to_numpy(),
                        )
                    )
                )

        duration_td = pd.Timedelta(seconds=total_duration_seconds)

        return {
            "total_route_points": len(route_df),
            "total_waypoints": len(waypoints_df),
            "total_landmarked_stops": (
                int(route_df["is_landmarked"].sum())
                if "is_landmarked" in route_df.columns
                else 0
            ),
            "total_distance_km": round(total_distance_km, 3),
            "total_duration_seconds": total_duration_seconds,
            "total_distance_km_formatted": f"{total_distance_km:.2f} km",
            "total_duration_formatted": str(duration_td),
        }