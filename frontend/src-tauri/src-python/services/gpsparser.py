"""
gpsparser.py (OOP Refactored)
---------------------------------------------------------------------------
Stage 1 of the pipeline: converts a raw GPS device file (GPX/KML/NMEA/FIT/
TCX/LOC/TXT) into CSV via the bundled GPSBabel binary, cleans data, 
detects stops/landmarks, and exports to frontend-compatible JSON.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Final, Optional, Dict, Any, List

import numpy as np
import pandas as pd

from services.job_config import JobConfigManager

logger = logging.getLogger(__name__)

# =============================================================================
# GEOMETRY & MATH UTILITIES
# =============================================================================

class GPSMath:
    """Handles vector-based spatial and geographic calculations."""

    @staticmethod
    def haversine_vectorized(lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray) -> np.ndarray:
        """Calculate the great circle distance between points using NumPy."""
        R = 6371.0
        lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
        
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = np.sin(dlat / 2.0)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0)**2
        c = 2 * np.arcsin(np.sqrt(a))
        return R * c

    @staticmethod
    def compute_route_summary(route_df: pd.DataFrame, waypoints_df: pd.DataFrame) -> Dict[str, Any]:
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
                lat2, lon2 = route_df["latitude"].shift(-1), route_df["longitude"].shift(-1)
                total_distance_km = float(
                    np.nansum(GPSMath.haversine_vectorized(
                                                            lat1.to_numpy(), 
                                                            lon1.to_numpy(), 
                                                            lat2.to_numpy(), 
                                                            lon2.to_numpy()
                                                        ))
                )

        duration_td = pd.Timedelta(seconds=total_duration_seconds)

        return {
            "total_route_points": len(route_df),
            "total_waypoints": len(waypoints_df),
            "total_landmarked_stops": (
                int(route_df["is_landmarked"].sum()) if "is_landmarked" in route_df.columns else 0
            ),
            "total_distance_km": round(total_distance_km, 3),
            "total_duration_seconds": total_duration_seconds,
            "total_distance_km_formatted": f"{total_distance_km:.2f} km",
            "total_duration_formatted": str(duration_td),
        }


# =============================================================================
# GPSBABEL CONVERTER ENGINE
# =============================================================================

class GPSBabelConverter:
    """Manages binary execution, format detection, and file conversion via GPSBabel."""

    GPSBABEL_BIN: Final[Path] = (
        Path(__file__).resolve().parent.parent / "bin" / "GPSBabel" / "gpsbabel.exe"
    )

    EXTENSION_TO_FORMAT: Final[Dict[str, str]] = {
        ".gpx": "gpx",
        ".kml": "kml",
        ".nmea": "nmea",
        ".fit": "garmin_fit",
        ".tcx": "gtrnctr",
        ".loc": "geo",
        ".txt": "nmea",
    }

    TIMEOUT_SECONDS: Final[int] = 120

    def __init__(self, binary_path: Optional[Path] = None, job_config=None):
        self.binary_path = binary_path if binary_path else self.GPSBABEL_BIN
        # Bring in the dynamic JobConfigManager just like mapfetcher
        self.config = job_config or JobConfigManager()

    def resolve_binary(self) -> str:
        if self.binary_path.exists():
            return str(self.binary_path)

        system_binary = shutil.which("gpsbabel")
        if system_binary is None:
            raise FileNotFoundError(
                f"gpsbabel not found. Expected bundled binary at '{self.binary_path}' or a PATH install."
            )
        return system_binary

    def detect_input_format(self, input_path: Path) -> str:
        ext = input_path.suffix.lower()
        fmt = self.EXTENSION_TO_FORMAT.get(ext)
        if fmt is None:
            raise ValueError(
                f"Could not auto-detect format for extension '{ext}'. "
                f"Supported: {sorted(self.EXTENSION_TO_FORMAT)}."
            )
        return fmt

    def generate_unique_output_path(self, target_dir: Path, stem: str, suffix: str) -> Path:
        target_dir.mkdir(parents=True, exist_ok=True)
        datetime_str = datetime.now().strftime("%Y%m%d_%H%M%S")

        for sequence in range(1, 100):
            candidate = target_dir / f"{stem}_raw_{datetime_str}_{sequence:02d}{suffix}"
            if not candidate.exists():
                return candidate

        raise FileExistsError(f"Could not generate unique filename; 99 files already exist for {datetime_str}.")

    def convert(self, input_file: str, output_filename: str, output_format: str, input_format: Optional[str] = None, extra_args: Optional[List[str]] = None) -> str:
        gpsbabel_cmd = self.resolve_binary()
        input_path = Path(input_file)
        
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_file}")

        if input_format is None:
            input_format = self.detect_input_format(input_path)

        # ---------------------------------------------------------------------
        # DYNAMIC PATH FIX: 
        # Resolves the base path from JobConfigManager, then appends "csv"
        # ---------------------------------------------------------------------
        base_path = Path(self.config.get("directory_path", "assets"))
        target_dir = (base_path / "csv").resolve()
        
        requested = Path(output_filename)
        output_path = self.generate_unique_output_path(target_dir, requested.stem, requested.suffix)

        cmd = [gpsbabel_cmd, "-i", input_format, "-f", str(input_path.resolve())]
        if extra_args:
            cmd.extend(extra_args)

        dummy_bin: Optional[Path] = None
        if output_format.lower() == "mtk-bin" and output_path.suffix.lower() == ".csv":
            cmd.extend(["-o", f"mtk-bin,csv={output_path.resolve()}"])
            dummy_bin = output_path.parent / "dummy.bin"
            cmd.extend(["-F", str(dummy_bin.resolve())])
        else:
            cmd.extend(["-o", output_format, "-F", str(output_path.resolve())])

        logger.info("Running gpsbabel: %s", " ".join(cmd))

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"gpsbabel timed out after {self.TIMEOUT_SECONDS}s for {input_file}") from exc
        finally:
            if dummy_bin and dummy_bin.exists():
                dummy_bin.unlink()

        if result.returncode != 0:
            raise RuntimeError(f"gpsbabel failed (exit {result.returncode}):\n{result.stderr.strip()}")

        logger.info("Converted '%s' -> '%s'", input_file, output_path)
        return str(output_path)


# =============================================================================
# DATA CLEANING & LANDMARK PROCESSOR
# =============================================================================

class GPSDataCleaner:
    """Cleans GPS dataframes, extracts waypoints, and flags long stops as landmarks."""

    STOP_DETECTION_PRECISION: Final[int] = 5
    LANDMARK_MIN_STOP_SECONDS: Final[int] = 300

    def __init__(self, precision: int = STOP_DETECTION_PRECISION, min_stop_sec: int = LANDMARK_MIN_STOP_SECONDS):
        self.precision = precision
        self.min_stop_sec = min_stop_sec

    def clean_file(self, csv_path: str, save_output: bool = True) -> Dict[str, Any]:
        df = pd.read_csv(csv_path)
        df.columns = [col.strip().lower() for col in df.columns]
        df = df.dropna(subset=['latitude', 'longitude'])

        if 'date' in df.columns and 'time' in df.columns:
            df['timestamp'] = pd.to_datetime(df['date'] + ' ' + df['time'], errors='coerce')

        if 'name' in df.columns:
            waypoints_df = df[df['name'].notna() & (df['name'] != '')].copy()
            route_df = df[df['name'].isna() | (df['name'] == '')].copy()
        else:
            waypoints_df = pd.DataFrame()
            route_df = df.copy()

        if 'timestamp' in route_df.columns:
            route_df = route_df.sort_values(by='timestamp').reset_index(drop=True)

        if 'timestamp' not in route_df.columns or route_df['timestamp'].isnull().all():
            logger.warning("No timestamps found! Generating artificial 1-second timeline...")
            start_time = pd.Timestamp.now()
            route_df['timestamp'] = pd.date_range(start=start_time, periods=len(route_df), freq='s')
        else:
            route_df['timestamp'] = route_df['timestamp'].ffill()

        if 'latitude' in route_df.columns and 'longitude' in route_df.columns:
            route_df['lat_round'] = route_df['latitude'].round(self.precision)
            route_df['lon_round'] = route_df['longitude'].round(self.precision)

            is_moving = (route_df['lat_round'] != route_df['lat_round'].shift()) | \
                        (route_df['lon_round'] != route_df['lon_round'].shift())

            route_df['stop_block'] = is_moving.cumsum()
            block_durations = route_df.groupby('stop_block')['timestamp'].transform(
                lambda x: (x.max() - x.min()).total_seconds()
            )
            route_df['stop_duration_sec'] = block_durations.fillna(0)

            route_df = route_df[is_moving].copy()

            route_df['store_name'] = None
            route_df['img_url'] = None
            route_df['is_landmarked'] = False

            long_stops = route_df['stop_duration_sec'] >= self.min_stop_sec
            mins_spent = (route_df.loc[long_stops, 'stop_duration_sec'] // 60).astype(int).astype(str)
            route_df.loc[long_stops, 'store_name'] = "Detected Stop (" + mins_spent + " mins)"
            route_df.loc[long_stops, 'img_url'] = ""
            route_df.loc[long_stops, 'is_landmarked'] = True

            route_df = route_df.drop(columns=['lat_round', 'lon_round', 'stop_block', 'stop_duration_sec'])

        summary = GPSMath.compute_route_summary(route_df, waypoints_df)
        logger.info(
            "Data cleaned: %d route points, %d waypoints, %.2f km, %s",
            summary["total_route_points"], summary["total_waypoints"],
            summary["total_distance_km"], summary["total_duration_formatted"],
        )

        saved_paths = {}
        if save_output:
            input_path = Path(csv_path)
            datetime_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            raw_stem = input_path.stem
            base_stem = raw_stem.split('_raw')[0] if '_raw' in raw_stem else raw_stem

            seq_num = None
            route_filepath = None
            for i in range(1, 100):
                route_filename = f"{base_stem}_cleaned_{datetime_str}_{i:02d}.csv"
                test_path = input_path.parent / route_filename
                if not test_path.exists():
                    seq_num = i
                    route_filepath = test_path
                    break

            if seq_num is None:
                raise FileExistsError(f"Could not generate unique filename; 99 files already exist for {datetime_str}.")

            route_df.to_csv(route_filepath, index=False)
            saved_paths["route_file"] = str(route_filepath)

            if not waypoints_df.empty:
                waypoints_filename = f"{base_stem}_cleaned_waypoints_{datetime_str}_{seq_num:02d}.csv"
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
# FRONTEND JSON EXPORTER
# =============================================================================

class GPSJsonExporter:
    """Handles serialization of cleaned GPS data into frontend-ready JSON configurations."""

    @staticmethod
    def export(cleaned_data: Dict[str, Any], original_input_path: str, project_name: str = "Untitled Project", save_json: bool = True) -> Dict[str, Any]:
        route_df = cleaned_data.get("route", pd.DataFrame())
        waypoints_df = cleaned_data.get("waypoints", pd.DataFrame())
        waypoints_list = []

        if not waypoints_df.empty:
            for _, row in waypoints_df.iterrows():
                lat = row.get("latitude") if "latitude" in row else row.get("lat")
                lng = row.get("longitude") if "longitude" in row else row.get("lng")
                
                if pd.notna(lat) and pd.notna(lng):
                    waypoints_list.append({
                        "lat": float(lat), "lng": float(lng),
                        "label": str(row["name"]) if pd.notna(row.get("name")) and row.get("name") != "" else "Waypoint",
                        "freeze_seconds": 3,
                        "popup_image": str(row["img_url"]) if pd.notna(row.get("img_url")) and row.get("img_url") != "" else None,
                        "narration": ""
                    })

        if not route_df.empty and "is_landmarked" in route_df.columns:
            landmarked_rows = route_df[route_df["is_landmarked"] == True]
            for _, row in landmarked_rows.iterrows():
                lat = row.get("latitude") if "latitude" in row else row.get("lat")
                lng = row.get("longitude") if "longitude" in row else row.get("lng")
                
                if pd.notna(lat) and pd.notna(lng):
                    label = str(row["store_name"]) if pd.notna(row.get("store_name")) and row.get("store_name") else "Landmark"
                    popup_img = str(row["img_url"]) if pd.notna(row.get("img_url")) and row.get("img_url") != "" else None
                    
                    waypoints_list.append({
                        "lat": float(lat), "lng": float(lng), "label": label,
                        "freeze_seconds": 3, "popup_image": popup_img, "narration": ""
                    })

        payload = {
            "project_name": project_name,
            "source_files": {"gps_route": str(original_input_path)},
            "waypoints": waypoints_list
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
                
            print(f"JSON config saved to: {json_filename}")

        return payload


# =============================================================================
# BACKWARDS-COMPATIBLE MODULE-LEVEL FUNCTIONS (FACADE)
# =============================================================================

def convert_gps_file(*args, **kwargs) -> str:
    return GPSBabelConverter().convert(*args, **kwargs)

def haversine_vectorized(*args, **kwargs):
    return GPSMath.haversine_vectorized(*args, **kwargs)

def _compute_route_summary(*args, **kwargs):
    return GPSMath.compute_route_summary(*args, **kwargs)

def clean_gps_data(*args, **kwargs):
    return GPSDataCleaner().clean_file(*args, **kwargs)

def summarize_gps_data(cleaned_data: dict) -> dict:
    return GPSMath.compute_route_summary(
        cleaned_data.get("route", pd.DataFrame()),
        cleaned_data.get("waypoints", pd.DataFrame()),
    )

def export_to_frontend_json(*args, **kwargs):
    return GPSJsonExporter.export(*args, **kwargs)

class GPSParser:
    @staticmethod
    def detect_format(input_path: Path) -> str:
        return GPSBabelConverter().detect_input_format(input_path)

    @staticmethod
    def haversine_vertorized(lat1, lon1, lat2, lon2):
        return GPSMath.haversine_vectorized(np.array([lat1]), np.array([lon1]), np.array([lat2]), np.array([lon2]))[0]

    @staticmethod
    def compute_summary_distance(df: pd.DataFrame, start_idx: int = 0, end_idx: Optional[int] = None) -> float:
        sub_df = df.iloc[start_idx:end_idx] if end_idx else df.iloc[start_idx:]
        summary = GPSMath.compute_route_summary(sub_df, pd.DataFrame())
        return summary["total_distance_km"]

    @staticmethod
    def detect_and_format_waypoint_stops(df: pd.DataFrame, job_config: dict) -> dict:
        cleaner = GPSDataCleaner()
        result = cleaner.clean_file(df) if isinstance(df, str) else {"route": df, "waypoints": pd.DataFrame()}
        return GPSJsonExporter.export(result, "mock_path", job_config.get("project_name", "Test"))

    @staticmethod
    def convert_gps_file(*args, **kwargs):
        return GPSBabelConverter().convert(*args, **kwargs)

    @staticmethod
    def clean_gps_data(*args, **kwargs):
        return GPSDataCleaner().clean_file(*args, **kwargs)

    @staticmethod
    def export_to_frontend_json(*args, **kwargs):
        return GPSJsonExporter.export(*args, **kwargs)