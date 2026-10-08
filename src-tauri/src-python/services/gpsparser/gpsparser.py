"""
GPS Parser (gpsparser.py)
---------------------------------------------------------------------------
Cleans GPS data, detects stops/landmarks, and exports to JSON.
Unified class handling GPSBabel conversion, data cleaning, and math analysis.
---------------------------------------------------------------------------
"""

# [I/O] Import libraries for GPS data parsing and cleaning
import pandas as pd
import numpy as np
from typing import Dict, Final, Optional, List, Any
import subprocess
from pathlib import Path

# [I/O] Import service dependencies for Integration
from services import runtime_paths
from services.logger.logger import setup_logger
from services.config.job_config import JobConfigManager
from services.projectfiles import gps_data_dir
from services.gpsparser.gpscalculator import GPSMath

# [Utility] Log setup for debugging and monitoring
logger = setup_logger("GPSParser")  

# [I/O] Initialize the GPSBabel from abs path
GPS_BABEL_PATH = runtime_paths.gpsbabel_exe()

class GPSParser:
    """ Unified class to handle GPS file conversion, cleaning, stop detection, and metrics. """

    # [Final] Mapping of file extensions to GPSBabel input formats
    EXTENSION_TO_FORMAT: Final[Dict[str, str]] = {
        ".gpx": "gpx",
        ".kml": "kml",
        ".nmea": "nmea",
        ".fit": "garmin_fit",
        ".tcx": "gtrnctr",
        ".loc": "geo",
        ".txt": "nmea",
    }

    TIMEOUT_SECONDS: Final[int] = 30

    def __init__(self, gps_babel_path: Optional[str] = GPS_BABEL_PATH, job_config = None):
        self.gps_babel_path = gps_babel_path
        self.config = job_config or JobConfigManager()
        
        # Cleaning and Stop Detection parameters
        self.fallback_speed_m_s = 1.4  # ~5 km/h walking speed fallback
        self.precision = 5             # Coordinate rounding precision
        self.min_stop_sec = 180        # Min duration (seconds) to flag a stop as a landmark
        self.has_real_time = False     # Set by clean_data: False when the timeline was synthesized

    def _config_anchors(self) -> List[Path]:
        """Directories a RELATIVE path in job_config.json is resolved
        against, most authoritative first: the folder holding
        job_config.json itself, then the project's own recorded
        directory_path, then the process working directory.

        The config file's own folder leads because it's the one anchor
        that is always correct and always available — a project folder
        that was renamed or moved still resolves, whereas directory_path
        is a value written at save time that can be stale (and the CWD is
        wherever the command happened to be run from, which for
        `py main.py <config>` is not the project at all)."""
        anchors: List[Path] = []
        config_path = getattr(self.config, "config_path", None)
        if config_path:
            anchors.append(Path(config_path).resolve().parent)
        recorded_dir = (
            self.config.data.get("directory_path")
            if self.config and hasattr(self.config, "data") else None
        )
        if recorded_dir:
            anchors.append(Path(recorded_dir))
        anchors.append(Path.cwd())
        return anchors

    def resolve_config_path(self, value: str) -> Path:
        """Resolves a path read out of job_config.json, accepting either an
        absolute path or one relative to the project (see _config_anchors).

        job_config.json is written with absolute paths, but it is also a
        file people hand-edit and move between machines, where absolute
        paths from another user's Documents folder are worse than useless
        — a relative "raw_track.gpx" beside the config is the portable
        spelling and now works. A relative value used to be resolved
        against the process CWD, which is why running the renderer from
        src-python looked for the track in src-python.

        Returns the first candidate that exists; with none existing,
        returns the first candidate anyway so the caller's error names the
        path it actually expected rather than the bare relative string."""
        raw = Path(str(value)).expanduser()
        if raw.is_absolute():
            return raw
        candidates = [anchor / raw for anchor in self._config_anchors()]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0] if candidates else raw

    def get_input_file_path(self) -> Optional[Path]:
        """ Get the input raw file path from the configuration. """
        if self.config and hasattr(self.config, 'data'):
            source_files = self.config.data.get("source_files", {})
            input_file = source_files.get("gps_route") or self.config.data.get("input_file")
            if input_file:
                return self.resolve_config_path(input_file)

        logger.warning("Input file not specified in configuration.")
        return None

    def detect_format(self, input_file: str) -> str:
        """ Detect the format of the input file based on its extension. """
        ext = Path(input_file).suffix.lower()
        if ext in self.EXTENSION_TO_FORMAT:
            return self.EXTENSION_TO_FORMAT[ext]
        else:
            logger.error(f"Unsupported file extension: {ext}")
            raise ValueError(f"Unsupported file extension: {ext}")

    def convert(self, output_format: str = "csv", extra_args: Optional[List[str]] = None) -> Path:
        """ Convert raw GPS data into standard format using GPSBabel. """
        # [NOTE] [GPS] Shells out to the bundled GPSBabel binary to normalize arbitrary GPS formats into CSV.
        input_file = self.get_input_file_path()
        if not input_file or not input_file.exists():
            raise FileNotFoundError(f"Input file could not be resolved or found: {input_file}")

        input_format = self.detect_format(str(input_file))

        # Same relative-or-absolute treatment as the input file: a project
        # that records a relative (or no) directory_path writes its
        # gpsdata/ beside its own job_config.json, not into whatever
        # directory the command was launched from.
        raw_dir = (
            self.config.data.get("directory_path")
            if self.config and hasattr(self.config, "data") else None
        )
        if raw_dir:
            output_file_directory = gps_data_dir(self.resolve_config_path(raw_dir))
        else:
            output_file_directory = gps_data_dir(self._config_anchors()[0])
        output_file_directory.mkdir(parents=True, exist_ok=True)

        output_algorithm = "iblue747" 
        output_filename = f"gpsdata.{output_format}"
        output_file_path = output_file_directory / output_filename

        command = [
            str(self.gps_babel_path), 
            "-i", input_format, 
            "-f", str(input_file)
        ]

        if extra_args: 
            command.extend(extra_args)

        command.extend([
            "-o", output_algorithm, 
            "-F", str(output_file_path.resolve())
        ])

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired: 
            logger.error(f"GPSBabel conversion timed out for file: {input_file}")
            raise TimeoutError(f"GPSBabel conversion timed out for file: {input_file}")

        if result.returncode != 0:
            logger.error(f"GPSBabel conversion failed: {result.stderr}")
            raise RuntimeError(f"GPSBabel conversion failed: {result.stderr}")

        logger.info(f"Successfully converted {input_file.name} to {output_format} format at {output_file_path}")
        return output_file_path

    def clean_data(self, converted_csv_path: Optional[Path] = None) -> Dict[str, Any]:
        """ Clean GPS data, handle timestamps, detect stops/landmarks, and summarize. """
        target_path = converted_csv_path or self.convert("csv")

        try:
            if not target_path.exists():
                raise FileNotFoundError(f"CSV data file not found at: {target_path}")

            dataframe = pd.read_csv(target_path)

            # [NOTE] [GPS] GPSBabel output column names vary by source device/format, so aliases are normalized here.
            # Normalize columns and map coordinate aliases
            dataframe.columns = [col.strip().lower() for col in dataframe.columns]
            dataframe = dataframe.rename(columns={
                "lat": "latitude", "lon": "longitude", "lng": "longitude", "long": "longitude"
            })
            
            dataframe = dataframe.dropna(subset=["latitude", "longitude"])

            if "date" in dataframe.columns and "time" in dataframe.columns:
                dataframe["timestamp"] = pd.to_datetime(dataframe["date"] + " " + dataframe["time"], errors="coerce")

            # Separate waypoints and route data
            if "name" in dataframe.columns:
                waypoints_df = dataframe[dataframe["name"].notna() & (dataframe["name"] != "")].copy()
                route_df = dataframe[dataframe["name"].isna() | (dataframe["name"] == "")].copy()
            else:
                waypoints_df = pd.DataFrame()
                route_df = dataframe.copy()

            # [HACK] [GPS] Some GPX files name every track point, so none looked like a plain route point; use them all.
            if route_df.empty and not dataframe.empty:
                route_df = dataframe.copy()
            if route_df.empty:
                raise ValueError("The GPS file has no usable points (no latitude/longitude rows).")

            if "timestamp" in route_df.columns:
                # Stable: the CSV's whole-second times tie for nearby points, and an
                # unstable sort reordered them differently for each sub-second start time.
                route_df = route_df.sort_values(by="timestamp", kind="stable").reset_index(drop=True)

            # [HACK] [GPS] Timestamps & Time-by-Distance Fallbacks: when a GPS log has no usable timestamps,
            # a synthetic timeline is derived from point-to-point distance and a fixed walking speed.
            self.has_real_time = "timestamp" in route_df.columns and not route_df["timestamp"].isnull().all()
            if not self.has_real_time:
                logger.warning("No timestamps found! Generating timeline based on physical distance...")
                lat1, lon1 = route_df["latitude"].shift().fillna(route_df["latitude"]).to_numpy(), route_df["longitude"].shift().fillna(route_df["longitude"]).to_numpy()
                lat2, lon2 = route_df["latitude"].to_numpy(), route_df["longitude"].to_numpy()

                distances_m = GPSMath.haversine_vectorized(lat1, lon1, lat2, lon2) * 1000.0
                dt_seconds = (distances_m / self.fallback_speed_m_s).clip(1.0)
                route_df["timestamp"] = pd.Timestamp.now() + pd.to_timedelta(np.cumsum(dt_seconds) - dt_seconds[0], unit="s")
            else:
                route_df["timestamp"] = route_df["timestamp"].ffill()
                dt = route_df["timestamp"].diff().dt.total_seconds().fillna(1.0)

                # [HACK] [GPS] Some devices log duplicate/out-of-order timestamps producing zero or negative deltas;
                # those gaps are patched using an average speed derived from the rest of the valid samples.
                if (dt <= 0).any():
                    logger.warning("Detected 0 or negative time deltas. Averaging time by distance...")
                    lat1, lon1 = route_df["latitude"].shift().fillna(route_df["latitude"]).to_numpy(), route_df["longitude"].shift().fillna(route_df["longitude"]).to_numpy()
                    lat2, lon2 = route_df["latitude"].to_numpy(), route_df["longitude"].to_numpy()
                    distances_m = GPSMath.haversine_vectorized(lat1, lon1, lat2, lon2) * 1000.0

                    valid_mask = dt > 0
                    valid_dist = distances_m[valid_mask].sum()
                    valid_time = dt[valid_mask].sum()
                    avg_speed_m_s = (valid_dist / valid_time) if (valid_time > 0 and valid_dist > 0) else self.fallback_speed_m_s

                    dt[dt <= 0] = (distances_m[dt <= 0] / avg_speed_m_s).clip(1.0)
                    route_df["timestamp"] = route_df["timestamp"].iloc[0] + pd.to_timedelta(dt.cumsum() - dt.iloc[0], unit="s")

            # [NOTE] [GPS] Detect Stops and Landmarks: coordinates are rounded to a fixed precision so that
            # consecutive points at effectively the same spot collapse into one "stop block" for duration checks.
            if "latitude" in route_df.columns and "longitude" in route_df.columns:
                route_df["lat_round"] = route_df["latitude"].round(self.precision)
                route_df["lon_round"] = route_df["longitude"].round(self.precision)

                is_moving = (route_df["lat_round"] != route_df["lat_round"].shift()) | (route_df["lon_round"] != route_df["lon_round"].shift())
                route_df["stop_block"] = is_moving.cumsum()
                route_df["stop_duration_sec"] = route_df.groupby("stop_block")["timestamp"].transform(lambda x: (x.max() - x.min()).total_seconds()).fillna(0)

                route_df = route_df[is_moving].copy()
                route_df["store_name"] = None
                route_df["img_url"] = None
                route_df["is_landmarked"] = False

                long_stops = route_df["stop_duration_sec"] >= self.min_stop_sec
                mins_spent = (route_df.loc[long_stops, "stop_duration_sec"] // 60).astype(int).astype(str)
                route_df.loc[long_stops, "store_name"] = "Detected Stop (" + mins_spent + " mins)"
                route_df.loc[long_stops, "img_url"] = ""
                route_df.loc[long_stops, "is_landmarked"] = True

                # dwell_sec: how long the GPS sat on this point before the duplicates were dropped.
                route_df = route_df.rename(columns={"stop_duration_sec": "dwell_sec"})
                route_df = route_df.drop(columns=["lat_round", "lon_round", "stop_block"])

            # Summarize Route
            summary = GPSMath.compute_route_summary(route_df, waypoints_df)
            logger.info(
                "Data cleaned: %d route points, %d waypoints, %.2f km, %s",
                summary["total_route_points"], summary["total_waypoints"], summary["total_distance_km"], summary["total_duration_formatted"]
            )

            dataframe.to_csv(target_path, index=False)
            saved_paths = {"cleaned_csv": str(target_path)}

        except Exception as e:
            logger.error(f"Failed to process GPS data: {e}")
            raise

        return {
            "route": route_df,
            "waypoints": waypoints_df,
            "saved_paths": saved_paths,
            "summary": summary,
        }