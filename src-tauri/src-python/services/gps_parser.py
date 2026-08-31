"""
GPS Parser (gpsparser.py)
---------------------------------------------------------------------------
Cleans GPS data, detects stops/landmarks, and exports to JSON.
Imports conversion and math logic from gps_converter.py.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Final, Optional, Dict, Any

import numpy as np
import pandas as pd

from services.gps_converter import GPSMath, GPSBabelConverter
from services.logger import setup_logger

logger = setup_logger("GPSDataCleaner")

# =============================================================================
# [Core] DATA CLEANING & LANDMARK PROCESSOR
# =============================================================================


class GPSDataCleaner:
    """Cleans GPS dataframes, extracts waypoints, and flags long stops as landmarks."""

    STOP_DETECTION_PRECISION: Final[int] = 5
    LANDMARK_MIN_STOP_SECONDS: Final[int] = 300

    # [Config/IO] Initialize with precision, minimum stop duration, and fallback speed
    def __init__(
        self,
        precision: int = STOP_DETECTION_PRECISION,
        min_stop_sec: int = LANDMARK_MIN_STOP_SECONDS,
        fallback_speed_m_s: float = 1.4,
    ):
        self.precision = precision
        self.min_stop_sec = min_stop_sec
        self.fallback_speed_m_s = fallback_speed_m_s

    # [GPS] Cleans a GPS CSV file, detects stops, and optionally saves cleaned data and waypoints
    def clean_file(self, csv_path: str, save_output: bool = True) -> Dict[str, Any]:
        df = pd.read_csv(csv_path)
        df.columns = [col.strip().lower() for col in df.columns]
        df = df.dropna(subset=["latitude", "longitude"])

        if "date" in df.columns and "time" in df.columns:
            df["timestamp"] = pd.to_datetime(
                df["date"] + " " + df["time"], errors="coerce"
            )

        if "name" in df.columns:
            waypoints_df = df[df["name"].notna() & (df["name"] != "")].copy()
            route_df = df[df["name"].isna() | (df["name"] == "")].copy()
        else:
            waypoints_df = pd.DataFrame()
            route_df = df.copy()

        if "timestamp" in route_df.columns:
            route_df = route_df.sort_values(by="timestamp").reset_index(drop=True)

        if "timestamp" not in route_df.columns or route_df["timestamp"].isnull().all():
            logger.warning(
                "No timestamps found! Generating timeline based on physical distance..."
            )

            # 1. Get physical distance between consecutive points
            lat1 = route_df["latitude"].shift().fillna(route_df["latitude"]).to_numpy()
            lon1 = (
                route_df["longitude"].shift().fillna(route_df["longitude"]).to_numpy()
            )
            lat2 = route_df["latitude"].to_numpy()
            lon2 = route_df["longitude"].to_numpy()

            distances_m = GPSMath.haversine_vectorized(lat1, lon1, lat2, lon2) * 1000.0

            # 2. Calculate time per segment (distance / fallback_speed). Minimum 1 second.
            dt_seconds = (distances_m / self.fallback_speed_m_s).clip(1.0)

            # 3. Create the timeline
            start_time = pd.Timestamp.now()
            route_df["timestamp"] = start_time + pd.to_timedelta(
                np.cumsum(dt_seconds) - dt_seconds[0], unit="s"
            )
        else:
            route_df["timestamp"] = route_df["timestamp"].ffill()

            # --- Existing Time-by-Distance Fallback ---
            dt = route_df["timestamp"].diff().dt.total_seconds().fillna(1.0)
            if (dt <= 0).any():
                logger.warning(
                    "Detected 0 or negative time deltas. Averaging time by distance..."
                )

                lat1 = (
                    route_df["latitude"].shift().fillna(route_df["latitude"]).to_numpy()
                )
                lon1 = (
                    route_df["longitude"]
                    .shift()
                    .fillna(route_df["longitude"])
                    .to_numpy()
                )
                lat2 = route_df["latitude"].to_numpy()
                lon2 = route_df["longitude"].to_numpy()
                distances_m = (
                    GPSMath.haversine_vectorized(lat1, lon1, lat2, lon2) * 1000.0
                )

                valid_mask = dt > 0
                valid_dist = distances_m[valid_mask].sum()
                valid_time = dt[valid_mask].sum()

                # Use dynamic class variable
                avg_speed_m_s = (
                    (valid_dist / valid_time)
                    if (valid_time > 0 and valid_dist > 0)
                    else self.fallback_speed_m_s
                )

                invalid_mask = dt <= 0
                dt[invalid_mask] = (distances_m[invalid_mask] / avg_speed_m_s).clip(1.0)

                start_time = route_df["timestamp"].iloc[0]
                route_df["timestamp"] = start_time + pd.to_timedelta(
                    dt.cumsum() - dt.iloc[0], unit="s"
                )

        if "timestamp" not in route_df.columns or route_df["timestamp"].isnull().all():
            logger.warning(
                "No timestamps found! Generating artificial 1-second timeline..."
            )
            start_time = pd.Timestamp.now()
            route_df["timestamp"] = pd.date_range(
                start=start_time, periods=len(route_df), freq="s"
            )
        else:
            # 1. Forward-fill any completely missing timestamp cells
            route_df["timestamp"] = route_df["timestamp"].ffill()

            # --- NEW VALIDATION: Time-by-Distance Fallback ---
            # Calculate time differences in seconds
            dt = route_df["timestamp"].diff().dt.total_seconds().fillna(1.0)

            # Check for 0 or negative time jumps (duplicates or rollovers)
            if (dt <= 0).any():
                logger.warning(
                    "Detected 0 or negative time deltas. Averaging time by distance..."
                )

                # A. Get physical distance in meters between consecutive points
                lat1 = (
                    route_df["latitude"].shift().fillna(route_df["latitude"]).to_numpy()
                )
                lon1 = (
                    route_df["longitude"]
                    .shift()
                    .fillna(route_df["longitude"])
                    .to_numpy()
                )
                lat2 = route_df["latitude"].to_numpy()
                lon2 = route_df["longitude"].to_numpy()

                distances_m = (
                    GPSMath.haversine_vectorized(lat1, lon1, lat2, lon2) * 1000.0
                )

                # B. Calculate average speed from the valid segments of the route
                valid_mask = dt > 0
                valid_dist = distances_m[valid_mask].sum()
                valid_time = dt[valid_mask].sum()

                # Default to the fallback speed if there are no valid times at all
                avg_speed_m_s = (
                    (valid_dist / valid_time)
                    if (valid_time > 0 and valid_dist > 0)
                    else self.fallback_speed_m_s
                )

                # C. Replace invalid times with calculated time (Distance / Average Speed)
                invalid_mask = dt <= 0

                # Apply fallback, ensuring at least 1 second passes to prevent overlapping timestamps
                dt[invalid_mask] = (distances_m[invalid_mask] / avg_speed_m_s).clip(1.0)

                # D. Reconstruct the timeline safely using cumulative sum
                start_time = route_df["timestamp"].iloc[0]
                route_df["timestamp"] = start_time + pd.to_timedelta(
                    dt.cumsum() - dt.iloc[0], unit="s"
                )

        if "latitude" in route_df.columns and "longitude" in route_df.columns:
            route_df["lat_round"] = route_df["latitude"].round(self.precision)
            route_df["lon_round"] = route_df["longitude"].round(self.precision)

            is_moving = (route_df["lat_round"] != route_df["lat_round"].shift()) | (
                route_df["lon_round"] != route_df["lon_round"].shift()
            )

            route_df["stop_block"] = is_moving.cumsum()
            block_durations = route_df.groupby("stop_block")["timestamp"].transform(
                lambda x: (x.max() - x.min()).total_seconds()
            )
            route_df["stop_duration_sec"] = block_durations.fillna(0)

            route_df = route_df[is_moving].copy()

            route_df["store_name"] = None
            route_df["img_url"] = None
            route_df["is_landmarked"] = False

            long_stops = route_df["stop_duration_sec"] >= self.min_stop_sec
            mins_spent = (
                (route_df.loc[long_stops, "stop_duration_sec"] // 60)
                .astype(int)
                .astype(str)
            )
            route_df.loc[long_stops, "store_name"] = (
                "Detected Stop (" + mins_spent + " mins)"
            )
            route_df.loc[long_stops, "img_url"] = ""
            route_df.loc[long_stops, "is_landmarked"] = True

            route_df = route_df.drop(
                columns=["lat_round", "lon_round", "stop_block", "stop_duration_sec"]
            )

        summary = GPSMath.compute_route_summary(route_df, waypoints_df)
        logger.info(
            "Data cleaned: %d route points, %d waypoints, %.2f km, %s",
            summary["total_route_points"],
            summary["total_waypoints"],
            summary["total_distance_km"],
            summary["total_duration_formatted"],
        )

        saved_paths = {}
        if save_output:
            input_path = Path(csv_path)
            datetime_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            raw_stem = input_path.stem
            base_stem = raw_stem.split("_raw")[0] if "_raw" in raw_stem else raw_stem

            # 1. Find and delete any previously saved cleaned files for this route
            for old_file in input_path.parent.glob(f"{base_stem}_cleaned_*.csv"):
                old_file.unlink(missing_ok=True)

            # 2. Save the new route file with the current timestamp (No sequence numbers)
            route_filename = f"{base_stem}_cleaned_{datetime_str}.csv"
            route_filepath = input_path.parent / route_filename
            route_df.to_csv(route_filepath, index=False)
            saved_paths["route_file"] = str(route_filepath)

            # 3. Handle waypoints file similarly by deleting the old one and saving the new one
            if not waypoints_df.empty:
                for old_wp in input_path.parent.glob(
                    f"{base_stem}_cleaned_waypoints_*.csv"
                ):
                    old_wp.unlink(missing_ok=True)

                waypoints_filename = f"{base_stem}_cleaned_waypoints_{datetime_str}.csv"
                waypoints_filepath = input_path.parent / waypoints_filename
                waypoints_df.to_csv(waypoints_filepath, index=False)
                saved_paths["waypoints_file"] = str(waypoints_filepath)

        return {
            "route": route_df,
            "waypoints": waypoints_df,
            "saved_paths": saved_paths,
            "summary": summary,
        }


# =============================================================================
# [Util] FRONTEND JSON EXPORTER
# =============================================================================


class GPSJsonExporter:
    """Handles serialization of cleaned GPS data into frontend-ready JSON configurations."""

    # [Util/IO] Exports cleaned GPS data and waypoints to a structured JSON format for frontend consumption
    @staticmethod
    def export(
        cleaned_data: Dict[str, Any],
        original_input_path: str,
        project_name: str = "Untitled Project",
        save_json: bool = True,
    ) -> Dict[str, Any]:
        route_df = cleaned_data.get("route", pd.DataFrame())
        waypoints_df = cleaned_data.get("waypoints", pd.DataFrame())
        waypoints_list = []

        if not waypoints_df.empty:
            for _, row in waypoints_df.iterrows():
                lat = row.get("latitude") if "latitude" in row else row.get("lat")
                lng = row.get("longitude") if "longitude" in row else row.get("lng")

                if pd.notna(lat) and pd.notna(lng):
                    waypoints_list.append(
                        {
                            "lat": float(lat),
                            "lng": float(lng),
                            "label": (
                                str(row["name"])
                                if pd.notna(row.get("name")) and row.get("name") != ""
                                else "Waypoint"
                            ),
                            "freeze_seconds": 3,
                            "popup_image": (
                                str(row["img_url"])
                                if pd.notna(row.get("img_url"))
                                and row.get("img_url") != ""
                                else None
                            ),
                            "narration": "",
                        }
                    )

        if not route_df.empty and "is_landmarked" in route_df.columns:
            landmarked_rows = route_df[route_df["is_landmarked"] == True]
            for _, row in landmarked_rows.iterrows():
                lat = row.get("latitude") if "latitude" in row else row.get("lat")
                lng = row.get("longitude") if "longitude" in row else row.get("lng")

                if pd.notna(lat) and pd.notna(lng):
                    label = (
                        str(row["store_name"])
                        if pd.notna(row.get("store_name")) and row.get("store_name")
                        else "Landmark"
                    )
                    popup_img = (
                        str(row["img_url"])
                        if pd.notna(row.get("img_url")) and row.get("img_url") != ""
                        else None
                    )

                    waypoints_list.append(
                        {
                            "lat": float(lat),
                            "lng": float(lng),
                            "label": label,
                            "freeze_seconds": 3,
                            "popup_image": popup_img,
                            "narration": "",
                        }
                    )

        payload = {
            "project_name": project_name,
            "source_files": {"gps_route": str(original_input_path)},
            "waypoints": waypoints_list,
        }

        if save_json:
            json_dir = Path("data/inputs/gpsdata/processdata/json")
            json_dir.mkdir(parents=True, exist_ok=True)

            saved_paths = cleaned_data.get("saved_paths", {})
            if "route_file" in saved_paths:
                route_path = Path(saved_paths["route_file"])
                json_filename = json_dir / route_path.with_suffix(".json").name
            else:
                input_path = Path(original_input_path)
                json_filename = json_dir / input_path.with_suffix(".json").name

            with open(json_filename, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)

            logger.info(f"JSON config saved to: {json_filename}")

        return payload


# =============================================================================
# [Config] BACKWARDS-COMPATIBLE MODULE-LEVEL FUNCTIONS (FACADE)
# =============================================================================


def convert_gps_file(*args, **kwargs) -> str:
    return GPSBabelConverter().convert(*args, **kwargs)


def haversine_vectorized(*args, **kwargs):
    return GPSMath.haversine_vectorized(*args, **kwargs)


def clean_gps_data(*args, **kwargs):
    return GPSDataCleaner().clean_file(*args, **kwargs)


def summarize_gps_data(cleaned_data: dict) -> dict:
    return GPSMath.compute_route_summary(
        cleaned_data.get("route", pd.DataFrame()),
        cleaned_data.get("waypoints", pd.DataFrame()),
    )


def export_to_frontend_json(*args, **kwargs):
    return GPSJsonExporter.export(*args, **kwargs)


# [Core] GPSParser class provides a unified interface for GPS data operations
class GPSParser:
    @staticmethod
    def detect_format(input_path: Path) -> str:
        return GPSBabelConverter().detect_input_format(input_path)

    @staticmethod
    def haversine_vertorized(lat1, lon1, lat2, lon2):
        return GPSMath.haversine_vectorized(
            np.array([lat1]), np.array([lon1]), np.array([lat2]), np.array([lon2])
        )[0]

    @staticmethod
    def compute_summary_distance(
        df: pd.DataFrame, start_idx: int = 0, end_idx: Optional[int] = None
    ) -> float:
        sub_df = df.iloc[start_idx:end_idx] if end_idx else df.iloc[start_idx:]
        summary = GPSMath.compute_route_summary(sub_df, pd.DataFrame())
        return summary["total_distance_km"]

    @staticmethod
    def detect_and_format_waypoint_stops(df: pd.DataFrame, job_config: dict) -> dict:
        cleaner = GPSDataCleaner()
        result = (
            cleaner.clean_file(df)
            if isinstance(df, str)
            else {"route": df, "waypoints": pd.DataFrame()}
        )
        return GPSJsonExporter.export(
            result, "mock_path", job_config.get("project_name", "Test")
        )

    @staticmethod
    def convert_gps_file(*args, **kwargs):
        return GPSBabelConverter().convert(*args, **kwargs)

    @staticmethod
    def clean_gps_data(*args, **kwargs):
        return GPSDataCleaner().clean_file(*args, **kwargs)

    @staticmethod
    def export_to_frontend_json(*args, **kwargs):
        return GPSJsonExporter.export(*args, **kwargs)
