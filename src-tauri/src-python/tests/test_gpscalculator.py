"""Unit tests for services/gpsparser/gpscalculator.py."""

import numpy as np
import pandas as pd
import pytest

from services.gpsparser.gpscalculator import GPSMath


class TestHaversineVectorized:
    def test_same_point_is_zero_distance(self):
        result = GPSMath.haversine_vectorized(
            np.array([35.0]), np.array([139.0]), np.array([35.0]), np.array([139.0])
        )
        assert result[0] == pytest.approx(0.0, abs=1e-9)

    def test_known_distance_tokyo_to_osaka_roughly_400km(self):
        # Tokyo Station ~ Osaka Station, great-circle distance is ~400km.
        result = GPSMath.haversine_vectorized(
            np.array([35.6812]), np.array([139.7671]),
            np.array([34.7024]), np.array([135.4959]),
        )
        assert 390 < result[0] < 410

    def test_vectorized_over_multiple_points(self):
        lat1 = np.array([0.0, 0.0])
        lon1 = np.array([0.0, 0.0])
        lat2 = np.array([0.0, 1.0])
        lon2 = np.array([1.0, 0.0])
        result = GPSMath.haversine_vectorized(lat1, lon1, lat2, lon2)
        assert len(result) == 2
        assert result[0] > 0
        assert result[1] > 0


class TestComputeRouteSummary:
    def test_empty_route_returns_zeroed_summary(self):
        route_df = pd.DataFrame(columns=["timestamp", "latitude", "longitude"])
        waypoints_df = pd.DataFrame(columns=["label"])
        summary = GPSMath.compute_route_summary(route_df, waypoints_df)
        assert summary["total_route_points"] == 0
        assert summary["total_waypoints"] == 0
        assert summary["total_distance_km"] == 0.0
        assert summary["total_duration_seconds"] == 0.0

    def test_computes_distance_and_duration(self):
        route_df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(
                    ["2026-01-01T00:00:00", "2026-01-01T00:10:00"]
                ),
                "latitude": [35.0, 35.01],
                "longitude": [139.0, 139.01],
            }
        )
        waypoints_df = pd.DataFrame({"label": ["a", "b"]})
        summary = GPSMath.compute_route_summary(route_df, waypoints_df)
        assert summary["total_route_points"] == 2
        assert summary["total_waypoints"] == 2
        assert summary["total_duration_seconds"] == 600.0
        assert summary["total_distance_km"] > 0
        assert summary["total_distance_km_formatted"].endswith(" km")

    def test_counts_landmarked_stops_when_column_present(self):
        route_df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(["2026-01-01T00:00:00"]),
                "latitude": [35.0],
                "longitude": [139.0],
                "is_landmarked": [True],
            }
        )
        waypoints_df = pd.DataFrame({"label": ["a"]})
        summary = GPSMath.compute_route_summary(route_df, waypoints_df)
        assert summary["total_landmarked_stops"] == 1

    def test_missing_landmarked_column_defaults_to_zero(self):
        route_df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(["2026-01-01T00:00:00"]),
                "latitude": [35.0],
                "longitude": [139.0],
            }
        )
        waypoints_df = pd.DataFrame({"label": ["a"]})
        summary = GPSMath.compute_route_summary(route_df, waypoints_df)
        assert summary["total_landmarked_stops"] == 0
