"""
GPS Parser Service (gpsparser.py)
"""
'''
This module provides a service for parsing GPS data from various formats. It is designed to be used within the Tauri application framework, allowing for seamless integration with the frontend.

How to use:
"""
from gpsparser import GPSParser

# Convert a GPX file to CSV format
success = GPSParser.convert_gps_file(
    input_file="my_activity.gpx",
    output_file_name="morning_run",
    output_format="csv"
)

if success:
    print("GPS file converted and saved successfully!")
else:
    print("Conversion failed. Check logs for details.")
------------------------------------------------------------------
import json

# Load your job config file
with open("job_config.json", "r", encoding="utf-8") as f:
    config_data = json.load(f)

# Assume route_df is your cleaned DataFrame from cleanup_data_for_processing
# Generate the dynamic JSON report for the frontend
frontend_json_payload = GPSParser.detect_and_format_waypoint_stops(route_df, config_data)

print(frontend_json_payload)
"""
'''

# Import necessary modules
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Final, Optional
import numpy as np
import pandas as pd
import json
import sys

# Add the directory containing main.py to the Python path
script_dir = Path(__file__).resolve().parent
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

#Import another module from the same package
from filehandler import FileHandler

# Logging configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Define GPS Babel executable path
GPS_BABEL_PATH: Final[Path] = Path(__file__).parent / "bin" / "GPSBabel"  / "gpsbabel.exe"

# Define Extension mapping for supported GPS data formats
EXTENSION_MAPPING: Final[dict[str, str]] = {
    ".gpx": "gpx",
    ".kml": "kml",
    ".nmea": "nmea",
    ".fit": "garmin_fit",
    ".tcx": "gtrnctr",
    ".loc": "geo",
    ".txt": "nmea",
}

# Define the GPSParser timeout in seconds
GPS_PARSER_TIMEOUT: Final[int] = 30

class GPSParser:
    """
    A class to handle GPS data parsing and conversion using GPS Babel.
    """

    # ==========================
    # Initialization
    # ==========================
    def __init__(self, gps_babel_path: Path = GPS_BABEL_PATH):
        self.gps_babel_path = gps_babel_path

    # ==========================
    # GPS Babel check
    # ==========================
    @staticmethod
    def check_gps_babel() -> bool:
        """
        Check if GPS Babel is available and executable.
        Returns True if GPS Babel is found and executable, False otherwise.
        """
        if not GPS_BABEL_PATH.exists():
            logging.error(f"GPS Babel executable not found at {GPS_BABEL_PATH}")
            return False
        if not os.access(GPS_BABEL_PATH, os.X_OK):
            logging.error(f"GPS Babel executable is not executable: {GPS_BABEL_PATH}")
            return False
        logging.info(f"GPS Babel executable is available and executable: {GPS_BABEL_PATH}")
        return True

    @staticmethod
    def detect_format(file_path: Path) -> Optional[str]:
        """
        Detect the GPS data format based on the file extension.
        Returns the corresponding format string for GPS Babel or None if unsupported.
        """
        ext = file_path.suffix.lower()
        return EXTENSION_MAPPING.get(ext, None)

    @staticmethod
    def convert_gps_file(
        input_file: str,
        output_file_name: str,
        output_format: str = "csv"
    ) -> bool:
        """
        Convert a GPS file from one format to another using GPS Babel.
        Returns True if the conversion is successful, False otherwise.
        """
        # 1. Check if GPS Babel is available (Call via class name or directly)
        if not GPSParser.check_gps_babel():
            logging.error("GPS Babel is not available.")
            return False

        # 2. Detect the input file format
        file_format = GPSParser.detect_format(Path(input_file))
        if not file_format:
            logging.error(f"Unsupported file format: {input_file}")
            return False

        # 3. Setup output directory using FileHandler
        target_directory = FileHandler.get_directory_path() / output_format
        target_directory.mkdir(parents=True, exist_ok=True)

        # 4. Generate the timestamped file path
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        final_output_path = target_directory / f"{output_file_name}_{timestamp}.{output_format}"

        try:
            # 5. Pass the specific file path to GPSBabel
            subprocess.run(
                [
                    str(GPS_BABEL_PATH),
                    "-i", file_format,
                    "-f", input_file,
                    "-o", output_format,
                    "-F", str(final_output_path)
                ],
                check=True,
                timeout=GPS_PARSER_TIMEOUT
            )
            logging.info(f"File converted successfully: {input_file} -> {final_output_path}")
            return True

        except subprocess.CalledProcessError as e:
            logging.error(f"Error occurred while converting file: {e}")
            return False
        except subprocess.TimeoutExpired:
            logging.error("Timeout occurred while converting file.")
            return False

    # ==========================
    # Cleanup Data for Processing
    # ==========================
    @staticmethod
    def compute_waypoint_segments(route_df: pd.DataFrame, waypoints_list: list) -> list:
        """
        Splits the main route DataFrame into segments between consecutive waypoints
        and computes individual summary statistics for each leg.
        """
        segments = []
        
        # Loop through waypoints to create pairs (Leg 1: index 0->1, Leg 2: index 1->2, etc.)
        for i in range(len(waypoints_list) - 1):
            start_wp = waypoints_list[i]
            end_wp = waypoints_list[i + 1]
            
            # Strategy: Find the closest route points to the waypoint coordinates 
            # or slice chronologically if timestamps match.
            # Here is a simple spatial bounding/nearest-index approach:
            start_idx = ((route_df['lat'] - start_wp['lat'])**2 + (route_df['lng'] - start_wp['lng'])**2).idxmin()
            end_idx = ((route_df['lat'] - end_wp['lat'])**2 + (route_df['lng'] - end_wp['lng'])**2).idxmin()
            
            # Ensure correct forward ordering
            if start_idx > end_idx:
                start_idx, end_idx = end_idx, start_idx
                
            segment_df = route_df.loc[start_idx:end_idx]
            
            if len(segment_df) < 2:
                continue
                
            # Calculate stats for this specific leg
            lat1 = segment_df['lat'].values[:-1]
            lon1 = segment_df['lng'].values[:-1]
            lat2 = segment_df['lat'].values[1:]
            lon2 = segment_df['lng'].values[1:]
            
            distances = GPSParser.haversine_vertorized(lat1, lon1, lat2, lon2)
            leg_distance = np.sum(distances)
            
            leg_duration = (segment_df['timestamp'].max() - segment_df['timestamp'].min()).total_seconds()
            
            segments.append({
                "leg_index": i,
                "from_label": start_wp['label'],
                "to_label": end_wp['label'],
                "route_mode": end_wp.get('routeMode', 'walking'),
                "freeze_seconds": end_wp.get('freeze_seconds', 3),
                "distance_km": leg_distance,
                "duration_sec": leg_duration,
                "data": segment_df
            })
            
        return segments

    # ==========================
    # Detect and format GPS data
    # ==========================
    @staticmethod
    def detect_and_format_waypoint_stops(route_df: pd.DataFrame, job_config: dict, radius_meters: float = 35.0) -> str:
        """
        Checks route points against job config waypoints to find where the user 
        stood still for a prolonged duration, and returns a JSON payload for the frontend.
        """
        waypoints_data = job_config.get("waypoints", [])
        dynamic_stops_report = []

        for idx, wp in enumerate(waypoints_data):
            wp_lat = float(wp.get("lat") or wp.get("latitude") or 0.0)
            wp_lng = float(wp.get("lng") or wp.get("lon") or wp.get("longitude") or 0.0)
            wp_label = wp.get("label", "")      

            # 1. Find points within proximity of this waypoint (Rough Haversine or simple distance filter)
            # Using a quick approximation filter or Haversine vector
            lat_diff = route_df['lat'] - wp_lat
            lon_diff = route_df['lng'] - wp_lng
            # Approx degrees to meters conversion (1 deg lat ~= 111,000 meters)
            distance_approx_m = np.sqrt(lat_diff**2 + lon_diff**2) * 111000
            
            nearby_points = route_df[distance_approx_m <= radius_meters]

            if not nearby_points.empty and 'timestamp' in nearby_points.columns:
                # 2. Calculate total dwell time at this waypoint
                start_time = nearby_points['timestamp'].min()
                end_time = nearby_points['timestamp'].max()
                duration_seconds = (end_time - start_time).total_seconds()
                duration_minutes = round(duration_seconds / 60, 1)

                # 3. Check if they stood still long enough (e.g., 5 to 10 mins)
                is_significant_stop = duration_seconds >= 300  # 300 seconds = 5 minutes

                dynamic_stops_report.append({
                    "waypoint_index": idx,
                    "label": wp_label,
                    "target_lat": wp_lat,
                    "target_lng": wp_lng,
                    "dwell_time_seconds": duration_seconds,
                    "dwell_time_minutes": duration_minutes,
                    "is_extended_stop": is_significant_stop,
                    "route_mode": wp.get("routeMode", "walking"),
                    "freeze_seconds": wp.get("freeze_seconds", 3)
                })
            else:
                # If no dense cluster found near this specific coordinate
                dynamic_stops_report.append({
                    "waypoint_index": idx,
                    "label": wp_label,
                    "dwell_time_seconds": 0,
                    "dwell_time_minutes": 0,
                    "is_extended_stop": False
                })

        # 4. Serialize into a JSON string to pass smoothly through the Tauri bridge
        return json.dumps(dynamic_stops_report, indent=2, ensure_ascii=False)
   
   
   

    # ==========================
    # Additional utility methods can be added here
    # ==========================

    # ==========================
    # Haversine formula for distance calculation
    # ==========================
    @staticmethod
    def haversine_vertorized(lat1, lon1, lat2, lon2):
        """
        Calculate the great-circle distance between two points on the Earth using the Haversine formula.
        This version is vectorized for performance with numpy arrays.

        Args:
            lat1, lon1: lat and lng of point 1 in decimal degrees.
            lat2, lon2: lat and lng of point 2 in decimal degrees.
        Returns:
            The distance between the two points in kilometers.
        """
        
        # 1. Define the radius of the Earth
        R = 6371.0

        # 2. Convert lat and lng from degrees to radians
        lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])

        # 3. Compute the differences
        dlat = lat2 - lat1
        dlon = lon2 - lon1

        # 4. Apply the Haversine formula
        a = np.sin(dlat / 2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2)**2
        c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))

        return R * c

    # ==========================
    # Compute total distance from a DataFrame of GPS points
    # ==========================
    @staticmethod
    def compute_summary_distance(df: pd.DataFrame, start_idx: int = 0, end_idx: int = 0) -> float:
        """
        Compute the total distance covered based on a DataFrame of GPS points,
        with optional slice range support.

        Args:
            df (pd.DataFrame): DataFrame containing GPS points with 'lat' and 'lng'.
            start_idx (int): Starting row index for calculation (default 0).
            end_idx (int): Ending row index for calculation (default 0).
        Returns:
            Total distance in kilometers.
        """

        # 1. Validate the DataFrame and indices
        if df.empty or 'lat' not in df.columns or 'lng' not in df.columns:
            logging.error("DataFrame is empty or missing required columns.")
            return 0.0

        # 2. Slice the DataFrame according to the requested range
        df_subset = df.iloc[start_idx:end_idx]

        if len(df_subset) < 2:
            logging.warning("Not enough points in the specified range to compute distance.")
            return 0.0

        # 3. Shift the lat and lng to get the next point
        lat1 = df_subset['lat'].values[:-1]
        lon1 = df_subset['lng'].values[:-1]
        lat2 = df_subset['lat'].values[1:]
        lon2 = df_subset['lng'].values[1:]

        # 4. Calculate distances between consecutive points
        distances = GPSParser.haversine_vertorized(lat1, lon1, lat2, lon2)

        # 5. Sum the distances to get the total distance
        total_distance = np.sum(distances)
        
        logging.info(f"Total distance computed for range [{start_idx}:{end_idx}]: {total_distance:.2f} km")
        return total_distance

