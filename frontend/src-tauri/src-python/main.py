"""
main.py
---------------------------------------------------------------------------
Entry point / orchestrator for the whole GPS-to-navigation-video pipeline.
---------------------------------------------------------------------------
"""

import sys
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pyproj

from services.gpsparser import GPSParser
from services.filehandler import FileHandler
from services.mapfetcher import MapFetcher
from services.route2vdo import render_route_animation
from services.job_config import JobConfigManager


def store_raw_file(input_file: str) -> str:
    stored_file_path = FileHandler.save_file_with_timestamp(
        file_name="raw_gps_data",
        file_type="txt",
        content=open(input_file, "r").read()
    )
    if stored_file_path:
        print(f"Raw file stored at: {stored_file_path}")
    else:
        print("Failed to store raw file.")
    return stored_file_path


_WGS84_TO_WEBMERCATOR = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)


def _project_route_to_pixels(lats, lons, extent: tuple[float, float, float, float], img_width_px: int, img_height_px: int) -> list[list[float]]:
    w, e, s, n = extent
    merc_x, merc_y = _WGS84_TO_WEBMERCATOR.transform(lons, lats)
    px = (np.asarray(merc_x) - w) / (e - w) * img_width_px
    py = (n - np.asarray(merc_y)) / (n - s) * img_height_px
    return [[float(x), float(y)] for x, y in zip(px, py)]


def generate_navigation_video(
    cleaned_route: dict,
    project_config_path: str,
    output_video_dir: str = "data\\outputs\\video",
    map_output_path: str = "data\\inputs\\fullmap_image\\map_background.png",
) -> list[str]:
    route_df = cleaned_route["route"]
    summary = cleaned_route.get("summary", {})

    if route_df.empty:
        raise ValueError("Cannot render a navigation video from an empty route.")

    # Dynamically detect coordinate column names to prevent KeyError
    lat_col = "latitude" if "latitude" in route_df.columns else "lat"
    lon_col = "longitude" if "longitude" in route_df.columns else "lng"

    config = JobConfigManager(project_config_path)
    
    fetcher = MapFetcher(config)
    bbox = fetcher.get_bounding_box(route_df, padding_factor=0.15)
    
    map_output_path, extent, (img_w, img_h) = fetcher.fetch_map(bbox, zoom=15)
    if map_output_path is None:
        raise RuntimeError("Map fetch failed - cannot render video without background map.")

    route_points = _project_route_to_pixels(route_df[lat_col].to_numpy(), route_df[lon_col].to_numpy(), extent, img_w, img_h)
    route_labels = [(row["store_name"] if row.get("is_landmarked") else None) for _, row in route_df.iterrows()]
    route_popups = [None] * len(route_points)

    waypoints = config.get_waypoints()
    wp_indices = MapFetcher.build_waypoint_index(route_df, waypoints)

    if waypoints:
        print(f"🗺️ Injecting {len(waypoints)} custom waypoints from JSON config...")
        for idx, wp in enumerate(waypoints):
            closest_idx = wp_indices[idx]
            raw_label = wp.get("label", "Waypoint")
            
            if idx == 0:
                wp_label = f"Start: {raw_label}" if raw_label else "Start"
            elif idx == len(waypoints) - 1:
                wp_label = f"Stop: {raw_label}" if raw_label else "Stop"
            else:
                wp_label = raw_label
            
            route_labels[closest_idx] = wp_label
            route_popups[closest_idx] = {
                "freeze_seconds": float(wp.get("freeze_seconds", 3.0)),
                "popup_image": wp.get("popup_image"),
                "triggered": False
            }

    image_output_dir = Path("data/inputs/res_images")
    sequence_data = MapFetcher.generate_residential_sequence(
        route_df, waypoints, image_output_dir, (img_w, img_h),
        max_chunk_distance_meters=math.inf, precomputed_indices=wp_indices,
    )

    seg_durations = MapFetcher.compute_segment_durations(waypoints, wp_indices, route_df, target_avg_seconds=10.0) if waypoints and len(wp_indices) > 1 else []

    res_sequence = []
    for seq_idx, item in enumerate(sequence_data):
        start_idx = item["start_idx"]
        end_idx = item["end_idx"]
        chunk = route_df.iloc[start_idx : end_idx + 1]

        chunk_points = _project_route_to_pixels(chunk[lat_col].to_numpy(), chunk[lon_col].to_numpy(), item["extent"], img_w, img_h)

        res_sequence.append({
            "img_path": item["img_path"],
            "extent": item["extent"],
            "lats": item["lats"],
            "lons": item["lons"],
            "points": chunk_points,
            "labels": route_labels[start_idx : end_idx + 1],
            "popups": route_popups[start_idx : end_idx + 1],
            "segment_duration": seg_durations[seq_idx] if seq_idx < len(seg_durations) else None,
        })

    return render_route_animation(
        img_path=map_output_path, points=route_points, labels=route_labels,
        popups=route_popups, output_dir=output_video_dir, summary=summary,
        res_sequence=res_sequence,
    )

def run_full_pipeline(project_config_path: str, output_video_dir: str = "data\\outputs\\video") -> dict:
    config = JobConfigManager(project_config_path)
    config.set("status", "processing")
    config.save()

    source_files = config.get("source_files", {})
    raw_source_path = source_files.get("gps_route")
    
    if not raw_source_path or not Path(raw_source_path).exists():
        raise FileNotFoundError(f"GPS route source file not found: {raw_source_path}")

    # 3. Parse and Clean GPS Data
    csv_path = GPSParser.convert_gps_file(input_file=raw_source_path, output_file_name=Path(raw_source_path).stem, output_format="iblue747")
    if not csv_path:
        raise RuntimeError("Failed to convert GPS file via GPSBabel.")
        
    df = pd.read_csv(csv_path)
    
    # --- NEW: Standardize column names to prevent KeyError ---
    # 1. Convert all column headers to lowercase
    df.columns = df.columns.str.lower()
    # 2. Rename common shorthand names to the required full names
    df = df.rename(columns={"lat": "latitude", "lon": "longitude", "lng": "longitude"})
    
    # Double-check that the required columns actually exist now
    if not {'latitude', 'longitude'}.issubset(df.columns):
        raise ValueError(f"Could not find latitude/longitude data in the GPS file. Available columns: {df.columns.tolist()}")

    cleaned_route = {"route": df, "summary": {"total_distance_km": 1.5, "total_duration_seconds": 300}}

    video_paths = generate_navigation_video(cleaned_route=cleaned_route, project_config_path=project_config_path, output_video_dir=output_video_dir)
    
    config.set("status", "completed")
    config.save()

    return {"video_paths": video_paths, "summary": cleaned_route.get("summary", {})}


def save_frontend_config(json_payload: str) -> str:
    # 1. Parse the incoming JSON payload from the frontend
    config_data = json.loads(json_payload)
    project_name = config_data.get("directory_path", "default_project")
    
    # 2. Determine file paths
    project_dir = FileHandler.get_project_directory(project_name)
    config_path = project_dir / "job_config.json"

    # 3. Ensure the directory and base file exist so JobConfigManager.load() doesn't fail
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        config_path.write_text("{}", encoding="utf-8")

    # 4. Initialize the manager (this loads the existing or blank file)[cite: 1]
    config = JobConfigManager(config_path)

    # 5. Update the manager's data with the payload from the frontend[cite: 1]
    for key, value in config_data.items():
        config.set(key, value)

    # 6. Save changes back to the file[cite: 1]
    config.save()

    # 7. Return the path as a string (or a success message)
    return str(config_path)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1]
        payload = sys.argv[2] if len(sys.argv) > 2 else ""
        try:    
            if command == "full_pipeline":
                output_arg = sys.argv[3] if len(sys.argv) > 3 else "data\\outputs\\video"
                result = run_full_pipeline(payload, output_video_dir=output_arg)
                print(json.dumps({"video_paths": result["video_paths"], "summary": result["summary"]}, ensure_ascii=False))            
                
            elif command == "save_config":
                saved_path = save_frontend_config(payload)
                print(json.dumps({"config_path": saved_path}, ensure_ascii=False))
                
            else:
                print(f"Error: Unknown command '{command}'", file=sys.stderr)
                sys.exit(1)
                
        except Exception as e:
            print(f"Error: {str(e)}", file=sys.stderr)
            sys.exit(1)