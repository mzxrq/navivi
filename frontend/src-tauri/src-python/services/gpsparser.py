"""
gpsparser.py (convert_gps_file, refactored)
---------------------------------------------------------------------------
Stage 1 of the pipeline: converts a raw GPS device file (GPX/KML/NMEA/FIT/
TCX/LOC/TXT) into CSV via the bundled GPSBabel binary.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Final, Optional

import numpy as np
import pandas as pd
import json

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Anchored to THIS file's location, not the process CWD. This mirrors
# the pattern used by mapfetcher.CACHE_DIR and route2vdo.FFMPEG_BIN so
# every module resolves paths identically regardless of how/where the
# Tauri sidecar process is launched from.
# ------------------------------------------------------------------
GPSBABEL_BIN: Final[Path] = (
    Path(__file__).resolve().parent.parent / "bin" / "GPSBabel" / "gpsbabel.exe"
)

# Module-level constant: built once at import time, not re-allocated
# on every convert_gps_file() call. Also doubles as documentation of
# which input formats this pipeline officially supports.
EXTENSION_TO_FORMAT: Final[dict[str, str]] = {
    ".gpx": "gpx",
    ".kml": "kml",
    ".nmea": "nmea",
    ".fit": "garmin_fit",
    ".tcx": "gtrnctr",
    ".loc": "geo",
    ".txt": "nmea",
}

# Bound how long we'll let gpsbabel run before giving up. Corrupt or
# unusually large device dumps can otherwise hang the subprocess
# indefinitely, blocking the whole pipeline with no recovery path.
GPSBABEL_TIMEOUT_SECONDS: Final[int] = 120


def _resolve_gpsbabel_binary() -> str:
    """Locate the gpsbabel executable: prefer the bundled binary,
    fall back to a system PATH install. Raises if neither exists."""
    if GPSBABEL_BIN.exists():
        return str(GPSBABEL_BIN)

    system_binary = shutil.which("gpsbabel")
    if system_binary is None:
        raise FileNotFoundError(
            "gpsbabel not found. Expected a bundled binary at "
            f"'{GPSBABEL_BIN}' or a PATH install."
        )
    return system_binary

def _detect_input_format(input_path: Path) -> str:
    """Maps a file extension to its gpsbabel format identifier."""
    ext = input_path.suffix.lower()
    fmt = EXTENSION_TO_FORMAT.get(ext)
    if fmt is None:
        raise ValueError(
            f"Could not auto-detect gpsbabel format for extension '{ext}'. "
            f"Supported: {sorted(EXTENSION_TO_FORMAT)}. "
            "Pass 'input_format' explicitly to override."
        )
    return fmt

def _generate_unique_output_path(target_dir: Path, stem: str, suffix: str) -> Path:
    """
    Finds a non-colliding filename of the form
    '<stem>_raw_<YYYYMMDD_HHMMSS>_<01-99><suffix>'.

    Linear probing over a 2-digit sequence is intentionally simple: the
    timestamp already gives second-level uniqueness, so collisions only
    happen when multiple files land in the same second (rapid batch
    uploads). 99 slots per second is a generous ceiling for that case;
    a UUID would remove the (tiny) collision-scan cost entirely but at
    the expense of human-readable, sortable filenames — a trade-off not
    worth making here since this isn't a hot path (one call per upload).
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    datetime_str = datetime.now().strftime("%Y%m%d_%H%M%S")

    for sequence in range(1, 100):
        candidate = target_dir / f"{stem}_raw_{datetime_str}_{sequence:02d}{suffix}"
        if not candidate.exists():
            return candidate

    raise FileExistsError(
        f"Could not generate a unique filename; 99 files already exist "
        f"for timestamp {datetime_str}."
    )

def convert_gps_file(
    input_file: str,
    output_filename: str,
    output_format: str,
    input_format: Optional[str] = None,
    extra_args: Optional[list[str]] = None,
) -> str:
    """
    Convert a GPS file to any format supported by gpsbabel.

    Output is written to data/inputs/gpsdata/processdata/csv/, named
    '<stem>_raw_<timestamp>_<seq><ext>' to guarantee uniqueness across
    concurrent/rapid uploads.

    Returns the absolute path to the converted file as a string.
    """
    gpsbabel_cmd = _resolve_gpsbabel_binary()

    input_path = Path(input_file)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    if input_format is None:
        input_format = _detect_input_format(input_path)

    # Anchored relative to this module's file, not the process CWD —
    # see the GPSBABEL_BIN comment above for why this matters.
    target_dir = (
        Path(__file__).resolve().parent.parent
        / "data" / "inputs" / "gpsdata" / "processdata" / "csv"
    )
    requested = Path(output_filename)
    output_path = _generate_unique_output_path(target_dir, requested.stem, requested.suffix)

    cmd = [gpsbabel_cmd, "-i", input_format, "-f", str(input_path.resolve())]
    if extra_args:
        cmd.extend(extra_args)

    dummy_bin: Optional[Path] = None

    # gpsbabel's mtk-bin writer always requires a binary firmware-format
    # target via -F, even when the CSV output (the thing we actually
    # want) is produced as a side-effect via the 'csv=' sub-option. We
    # give it a throwaway file and delete it immediately after — this
    # is a gpsbabel CLI quirk, not something our own design chose.
    if output_format.lower() == "mtk-bin" and output_path.suffix.lower() == ".csv":
        cmd.extend(["-o", f"mtk-bin,csv={output_path.resolve()}"])
        dummy_bin = output_path.parent / "dummy.bin"
        cmd.extend(["-F", str(dummy_bin.resolve())])
    else:
        cmd.extend(["-o", output_format, "-F", str(output_path.resolve())])

    logger.info("Running gpsbabel: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=GPSBABEL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"gpsbabel timed out after {GPSBABEL_TIMEOUT_SECONDS}s "
            f"(input possibly corrupt or unusually large: {input_file})"
        ) from exc
    finally:
        # Clean up the throwaway binary regardless of success/failure —
        # a `finally` here (rather than only on the success path) avoids
        # leaking dummy.bin files on repeated failed conversions.
        if dummy_bin and dummy_bin.exists():
            dummy_bin.unlink()

    if result.returncode != 0:
        raise RuntimeError(
            f"gpsbabel failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )

    logger.info("Converted '%s' -> '%s'", input_file, output_path)
    return str(output_path)

# ------------------------------------------
# Constants
# ------------------------------------------

# How many decimal places of lat/lon define "the same spot" for stop
# detection. 5 decimals ≈ 1.1 meters of grid resolution — tight enough
# that GPS drift while stationary won't fragment a real stop into many
# tiny blocks, but coarse enough that walking across a parking lot still
# registers as movement. Previously this was silently 3 decimals
# (≈111m) inside the function body, contradicting the docstring — now
# it's a single named constant so "what counts as stationary" is a
# deliberate, visible, tunable decision instead of a magic number.
STOP_DETECTION_PRECISION: Final[int] = 5

# Stops shorter than this aren't "landmarks" — just normal traffic
# stops, red lights, etc. 300s = 5 minutes, matching the original spec.
LANDMARK_MIN_STOP_SECONDS: Final[int] = 300

def haversine_vectorized(lat1, lon1, lat2, lon2):
    """
    Calculate the great circle distance between two points 
    on the earth (specified in decimal degrees) using NumPy.
    """
    # Earth radius in kilometers
    R = 6371.0
    
    # Convert decimal degrees to radians
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    
    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2.0)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0)**2
    c = 2 * np.arcsin(np.sqrt(a))
    
    return R * c

def _compute_route_summary(route_df: pd.DataFrame, waypoints_df: pd.DataFrame) -> dict:
    """
    Single source of truth for route-level statistics: total distance
    (haversine sum over consecutive cleaned points) and total duration
    (max timestamp - min timestamp). Shared by both clean_gps_data()
    (so every cleaned route ships with its own stats automatically) and
    the standalone summarize_gps_data() utility, so there is exactly
    one implementation of "how we compute distance" in the codebase.
    """
    total_distance_km = 0.0
    total_duration_seconds = 0.0

    if not route_df.empty:
        if "timestamp" in route_df.columns:
            # Sort defensively — this function may be called on data
            # that wasn't guaranteed sorted by an upstream caller.
            ordered = route_df.sort_values("timestamp")
            total_duration_seconds = (
                ordered["timestamp"].max() - ordered["timestamp"].min()
            ).total_seconds()

        if "latitude" in route_df.columns and "longitude" in route_df.columns:
            # Vectorized consecutive-point distance: shift(-1) pairs each
            # row with its successor in a single O(n) pass, no Python-level
            # loop over rows. The trailing NaN from the last row's shift
            # is handled by nansum, not by an explicit branch.
            lat1, lon1 = route_df["latitude"], route_df["longitude"]
            lat2, lon2 = route_df["latitude"].shift(-1), route_df["longitude"].shift(-1)
            total_distance_km = float(
                np.nansum(haversine_vectorized(lat1, lon1, lat2, lon2))
            )

    duration_td = pd.Timedelta(seconds=total_duration_seconds)

    return {
        "total_route_points": len(route_df),
        "total_waypoints": len(waypoints_df),
        "total_landmarked_stops": (
            int(route_df["is_landmarked"].sum()) if "is_landmarked" in route_df.columns else 0
        ),
        # Raw numeric values — safe for the frontend to do further math/
        # charting on without re-parsing a display string.
        "total_distance_km": round(total_distance_km, 3),
        "total_duration_seconds": total_duration_seconds,
        # Presentation-layer strings — separated from the raw values so
        # neither consumer (charting code vs. display label) has to
        # convert the other's format.
        "total_distance_km_formatted": f"{total_distance_km:.2f} km",
        "total_duration_formatted": str(duration_td),
    }

def clean_gps_data(csv_path: str, save_output: bool = True) -> dict:
    """
    Reads a GPSBabel-generated CSV, cleans the data, separates track
    points from waypoints, flags landmarks (stops >= 5 mins at the same
    lat/long, rounded to STOP_DETECTION_PRECISION decimal places), and
    saves them using the _cleaned suffix with date and time.

    Returns a dict with 'route', 'waypoints', 'saved_paths', AND now
    'summary' (total distance/duration/landmark counts) — computed
    automatically so callers can never forget to compute it.
    """
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
        logger.warning("No timestamps found in raw data! Generating artificial 1-second timeline...")
        start_time = pd.Timestamp.now()
        route_df['timestamp'] = pd.date_range(start=start_time, periods=len(route_df), freq='s')
    else:
        route_df['timestamp'] = route_df['timestamp'].ffill()

    if 'latitude' in route_df.columns and 'longitude' in route_df.columns:
        # Fixed precision (was silently 3 decimals ≈111m; docstring
        # promised 5 ≈1.1m — see STOP_DETECTION_PRECISION comment above).
        route_df['lat_round'] = route_df['latitude'].round(STOP_DETECTION_PRECISION)
        route_df['lon_round'] = route_df['longitude'].round(STOP_DETECTION_PRECISION)

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

        long_stops = route_df['stop_duration_sec'] >= LANDMARK_MIN_STOP_SECONDS
        mins_spent = (route_df.loc[long_stops, 'stop_duration_sec'] // 60).astype(int).astype(str)
        route_df.loc[long_stops, 'store_name'] = "Detected Stop (" + mins_spent + " mins)"
        route_df.loc[long_stops, 'img_url'] = ""
        route_df.loc[long_stops, 'is_landmarked'] = True

        route_df = route_df.drop(columns=['lat_round', 'lon_round', 'stop_block', 'stop_duration_sec'])

    # Compute stats BEFORE saving so they can be persisted alongside the
    # CSVs if you later want a sidecar summary.json — cheap to do now
    # since route_df/waypoints_df are already fully in memory.
    summary = _compute_route_summary(route_df, waypoints_df)
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
            raise FileExistsError(f"Could not generate a unique filename; 99 files already exist for {datetime_str}.")

        route_df.to_csv(route_filepath, index=False)
        saved_paths["route_file"] = str(route_filepath)
        logger.info("Route saved to: %s", route_filepath)

        if not waypoints_df.empty:
            waypoints_filename = f"{base_stem}_cleaned_waypoints_{datetime_str}_{seq_num:02d}.csv"
            waypoints_filepath = input_path.parent / waypoints_filename
            waypoints_df.to_csv(waypoints_filepath, index=False)
            saved_paths["waypoints_file"] = str(waypoints_filepath)
            logger.info("Waypoints saved to: %s", waypoints_filepath)

    return {
        "route": route_df,
        "waypoints": waypoints_df,
        "saved_paths": saved_paths,
        "summary": summary,  # <-- now always present, no separate call needed
    }

def summarize_gps_data(cleaned_data: dict) -> dict:
    """
    Standalone summary utility — kept for callers who already have a
    `cleaned_data` dict (e.g. a frontend 'recompute stats' action) and
    don't want to re-run the full clean pipeline. Delegates to the same
    _compute_route_summary() helper clean_gps_data() uses internally,
    so there's zero risk of the two ever disagreeing on the math.
    """
    return _compute_route_summary(
        cleaned_data.get("route", pd.DataFrame()),
        cleaned_data.get("waypoints", pd.DataFrame()),
    )

# ------------------------------------------
# JSON Conversion Function
# ------------------------------------------
def export_to_frontend_json(
    cleaned_data: dict,
    original_input_path: str,
    project_name: str = "Untitled Project",
    save_json: bool = True
) -> dict:
    """
    Converts cleaned GPS route and waypoints DataFrames into a 
    frontend-compatible JSON payload, turning landmarked stops into waypoints.
    """
    route_df = cleaned_data.get("route", pd.DataFrame())
    waypoints_df = cleaned_data.get("waypoints", pd.DataFrame())
    
    waypoints_list = []

    # 1. Process explicitly defined waypoints (if any exist)
    if not waypoints_df.empty:
        for _, row in waypoints_df.iterrows():
            lat = row.get("latitude") if "latitude" in row else row.get("lat")
            lng = row.get("longitude") if "longitude" in row else row.get("lng")
            
            if pd.notna(lat) and pd.notna(lng):
                waypoints_list.append({
                    "lat": float(lat),
                    "lng": float(lng),
                    "label": str(row["name"]) if pd.notna(row.get("name")) and row.get("name") != "" else "Waypoint",
                    "freeze_seconds": 3,
                    "popup_image": str(row["img_url"]) if pd.notna(row.get("img_url")) and row.get("img_url") != "" else None,
                    "narration": ""
                })

    # 2. Process detected landmarks / long stops from the route and add them to waypoints
    if not route_df.empty and "is_landmarked" in route_df.columns:
        landmarked_rows = route_df[route_df["is_landmarked"] == True]
        
        for _, row in landmarked_rows.iterrows():
            lat = row.get("latitude") if "latitude" in row else row.get("lat")
            lng = row.get("longitude") if "longitude" in row else row.get("lng")
            
            if pd.notna(lat) and pd.notna(lng):
                label = str(row["store_name"]) if pd.notna(row.get("store_name")) and row.get("store_name") else "Landmark"
                popup_img = str(row["img_url"]) if pd.notna(row.get("img_url")) and row.get("img_url") != "" else None
                
                waypoints_list.append({
                    "lat": float(lat),
                    "lng": float(lng),
                    "label": label,
                    "freeze_seconds": 3,
                    "popup_image": popup_img,
                    "narration": ""
                })

    # 3. Construct the JSON structure
    payload = {
        "project_name": project_name,
        "source_files": {
            "gps_route": str(original_input_path)
        },
        "waypoints": waypoints_list
    }

    # 4. Save JSON to the target directory: src-tauri/src-python/data/inputs/gpsdata/processdata/json
    if save_json:
        json_dir = Path("src-tauri/src-python/data/inputs/gpsdata/processdata/json")
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
