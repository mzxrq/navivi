"""
run_pipeline.py
---------------------------------------------------------------------------
One-pass GPS -> map -> video pipeline.
"""

from pathlib import Path
import pandas as pd

from services.gpsparser import clean_gps_data, convert_nmea, convert_gps_to_pixels, export_pixels_to_json
from services.mapfetcher import calculate_bounding_box, save_map_image, generate_residential_map_series
# --- NEW: Import load_route so we can read the JSON for testing ---
from services.route2vdo import render_route_animation, load_route

def run_pipeline(
    nmea_file: str,
    device_format: str = "iblue747",
    csv_path: str = "src-tauri\\src-python\\data\\inputs\\gpsdata\\processdata\\csv\\gps_log.csv",
    map_image_path: str = "src-tauri\\src-python\\data\\inputs\\image\\final_map.jpeg",
    json_path: str = "src-tauri\\src-python\\data\\inputs\\gpsdata\\processdata\\json\\route.json",
    output_video: str = "src-tauri\\src-python\\data\\outputs\\final_route_video.mp4",
    padding_percent: float = 0.15,
    output_size: tuple[int, int] = (1920, 1080),
    max_zoom: int = 19,
    duration_seconds: float = 10.0,
    fps: int = 30,
    line_thickness: int = 8,
    marker_radius: int = 15,
) -> str:
    
    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    Path(map_image_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_video).parent.mkdir(parents=True, exist_ok=True)

    # # =========================================================================
    # # 🟢 FULL PIPELINE MODE: Uncomment this block to run GPS -> Map -> Video
    # # =========================================================================

    # # 1-3. Data Cleaning and Bounding Box
    # track_csv = convert_nmea(nmea_file, csv_path, device_format)
    # gps_data = clean_gps_data(track_csv)
    # route_df = gps_data["route"]
    
    # padded_box = calculate_bounding_box(route_df, padding_percent=padding_percent)

    # # 4-5. BIG PICTURE MAP
    # map_extent, img_w, img_h = save_map_image(
    #     bounding_box=padded_box,
    #     output_filename=map_image_path,
    #     output_size=output_size,
    #     max_zoom=max_zoom,
    # )

    # big_pixel_points = convert_gps_to_pixels(
    #     route_df=route_df,
    #     extent=map_extent,
    #     image_path=map_image_path,
    # )

    # if "store_name" in route_df.columns:
    #     big_labels = [None if pd.isna(v) else str(v) for v in route_df["store_name"].tolist()]
    # else:
    #     big_labels = [None] * len(route_df)

    # big_popups = []
    # for index, row in route_df.iterrows():
    #     if "store_name" in route_df.columns and not pd.isna(row["store_name"]) and str(row["store_name"]).strip() != "":
    #         big_popups.append({
    #             "freeze_seconds": 3.0,
    #             "popup_image": str(row["img_url"]) if not pd.isna(row.get("img_url")) else ""
    #         })
    #     else:
    #         big_popups.append(None)

    # print("\n🗺️ Generating Residential Map Slices...")
    # res_slices = generate_residential_map_series(
    #     route_df=route_df,
    #     points_per_slice=500, 
    #     output_dir="src-tauri\\src-python\\data\\outputs\\res_maps",
    #     output_prefix="res_map",
    #     output_size=output_size
    # )

    # res_video_sequence = []
    # for slice_data in res_slices:
    #     chunk_df = slice_data["chunk_df"]
    #     chunk_pixels = convert_gps_to_pixels(route_df=chunk_df, extent=slice_data["extent"], image_path=slice_data["map_file"])
        
    #     if "store_name" in chunk_df.columns:
    #         chunk_labels = [None if pd.isna(v) else str(v) for v in chunk_df["store_name"].tolist()]
    #     else:
    #         chunk_labels = [None] * len(chunk_df)
            
    #     chunk_popups = []
    #     for index, row in chunk_df.iterrows():
    #         if "store_name" in chunk_df.columns and not pd.isna(row["store_name"]) and str(row["store_name"]).strip() != "":
    #             chunk_popups.append({"freeze_seconds": 3.0, "popup_image": str(row["img_url"]) if not pd.isna(row.get("img_url")) else ""})
    #         else:
    #             chunk_popups.append(None)
                
    #     res_video_sequence.append({
    #         "img_path": slice_data["map_file"],
    #         "points": [list(p) for p in chunk_pixels],
    #         "labels": chunk_labels,
    #         "popups": chunk_popups
    #     })

    # export_pixels_to_json(big_pixel_points, big_labels, popups=big_popups, output_json_path=json_path)

    # =========================================================================
    # 🟡 TEST MODE (JSON -> VIDEO ONLY): Uncomment this block to test video
    # =========================================================================
    print("🟡 TEST MODE: Loading data directly from JSON...")
    # Load your manually edited or pre-generated JSON file
    loaded_points, loaded_labels, loaded_popups, loaded_settings = load_route(json_path)
    
    # Assign the loaded JSON data to the variables the video renderer expects
    big_pixel_points = loaded_points
    big_labels = loaded_labels
    big_popups = loaded_popups
    
    # For testing just the big picture map, we use an empty residential sequence
    res_video_sequence = []

    # =========================================================================
    # 🔴 VIDEO RENDERING: Keep this block UNCOMMENTED at all times
    # =========================================================================
    print(f"\n🎬 Sending Big Picture + {len(res_video_sequence)} Residential Slices to video renderer...")
    
    result = render_route_animation(
        img_path=map_image_path, 
        points=[list(p) for p in big_pixel_points], 
        labels=big_labels,
        popups=big_popups,  
        output_path=output_video,
        duration_seconds=duration_seconds,
        fps=fps,
        line_thickness=line_thickness,
        marker_radius=marker_radius,
        res_sequence=res_video_sequence,
        res_duration_per_slice=5.0,  
        pause_seconds=2.0
    )

    print(f" Pipeline complete → {result}")
    return result

"""
main.py
---------------------------------------------------------------------------
The main entry point for the GPS Video Engine.
Triggered by the Tauri frontend via: python main.py --config temp_job_config.json
"""

import argparse
import json
import sys
from pathlib import Path

# Import the core engine functions from Dev 1's modules
from services.gpsparser import (
    convert_nmea, 
    clean_gps_data, 
    convert_gps_to_pixels, 
    export_pixels_to_json, 
    inject_waypoints
)
from services.mapfetcher import calculate_bounding_box, save_map_image
from services.route2vdo import load_route, render_route_animation

def process_job(config_json_path: str):
    print(f"🚀 Initializing Video Engine with config: {config_json_path}")
    
    # 1. Read the JSON config passed by the React frontend
    try:
        with open(config_json_path, 'r', encoding='utf-8') as f:
            job = json.load(f)
    except Exception as e:
        print(f"❌ Error: Could not read config file: {e}")
        sys.exit(1)

    project_settings = job.get("project_settings", {})
    waypoints = job.get("waypoints", [])
    
    input_gps = project_settings.get("input_gps_file")
    output_mp4 = project_settings.get("output_video_file", "output.mp4")
    
    if not input_gps or not Path(input_gps).exists():
        print(f"❌ Error: Input GPS file not found at {input_gps}")
        sys.exit(1)

    # Prepare a directory to store the output and intermediate cache files
    output_dir = Path(output_mp4).parent
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # ---------------------------------------------------------
    # PHASE 1: Data Parsing & Cleaning
    # ---------------------------------------------------------
    input_path = Path(input_gps)
    csv_path = input_gps
    
    # If the user uploaded a .gpx or .fit, we convert it to .csv first using GPSBabel
    if input_path.suffix.lower() != '.csv':
        print(f"🔄 Converting {input_path.suffix} to CSV...")
        csv_path = str(output_dir / "converted_route.csv")
        
        # Dynamically guess the input format for GPSBabel based on file extension
        in_fmt = "gpx" if input_path.suffix.lower() == ".gpx" else "nmea"
        
        convert_nmea(
            input_file=input_gps, 
            output_file=csv_path, 
            output_format="csv", 
            input_format=in_fmt
        )

    print("🧹 Cleaning GPS data...")
    data = clean_gps_data(csv_path)
    route_df = data["route"]
    
    if route_df.empty:
        print("❌ Error: No valid GPS coordinates found after cleaning.")
        sys.exit(1)

    # ---------------------------------------------------------
    # PHASE 2: Map Fetching & Projection
    # ---------------------------------------------------------
    print("🗺️ Fetching OpenStreetMap background...")
    bbox = calculate_bounding_box(route_df)
    map_bg_path = str(output_dir / "map_bg.png")
    
    # Generate the 16:9 background map image
    extent, img_w, img_h = save_map_image(bbox, output_filename=map_bg_path)

    print("📐 Converting Latitude/Longitude to Image Pixels...")
    pixel_points = convert_gps_to_pixels(route_df, extent, map_bg_path)

    # ---------------------------------------------------------
    # PHASE 3: Waypoint Injection & JSON Export
    # ---------------------------------------------------------
    print(f"📍 Injecting {len(waypoints)} landmarks/popups from frontend...")
    # This requires the inject_waypoints function we wrote earlier inside gpsparser.py
    labels, popups = inject_waypoints(route_df, waypoints)

    final_route_json = str(output_dir / "final_route.json")
    print("💾 Exporting animation math to JSON...")
    export_pixels_to_json(
        pixel_points=pixel_points,
        labels=labels,
        popups=popups,
        output_json_path=final_route_json,
        settings={
            "fps": project_settings.get("fps", 30),
            "duration_seconds": 10.0 # You can make this dynamic later
        }
    )

    # ---------------------------------------------------------
    # PHASE 4: Video Rendering
    # ---------------------------------------------------------
    print("🎬 Starting video render using OpenCV and FFmpeg...")
    points, loaded_labels, loaded_popups, settings = load_route(final_route_json)
    
    render_route_animation(
        img_path=map_bg_path,
        points=points,
        labels=loaded_labels,
        popups=loaded_popups,
        output_path=output_mp4,
        fps=settings.get("fps", 30),
        duration_seconds=settings.get("duration_seconds", 10.0),
        pause_seconds=2.0  # Time to pause at the very end of the video
    )

    print("✅ Render Complete! Video saved successfully.")


import json
import argparse

def run_from_ui_config(config_path: str):
    """
    Reads the job_config.json generated by the Tauri React frontend, 
    processes the raw GPS file, maps the UI waypoints to the route, 
    and triggers the video renderer.
    """
    print(f"\n🚀 IGNITION SEQUENCE START: Loading config from {config_path}")
    
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    project_name = config.get("project_name", "Exported_Video")
    nmea_file = config["source_files"]["gps_route"]
    ui_waypoints = config.get("waypoints", [])

    # File paths for the intermediate processing
    csv_path = "data/temp/gps_log.csv"
    map_image_path = "data/temp/final_map.jpeg"
    output_video = f"data/outputs/{project_name.replace(' ', '_')}.mp4"
    
    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_video).parent.mkdir(parents=True, exist_ok=True)

    # 1. Process the raw GPS file (assuming GPX/NMEA)
    print("📍 Step 1: Parsing GPS File...")
    # NOTE: Dev 1 used "iblue747", but if you are dropping GPX files, gpsbabel format is "gpx"
    track_csv = convert_nmea(nmea_file, csv_path, "gpx") 
    gps_data = clean_gps_data(track_csv)
    route_df = gps_data["route"]

    # 2. Generate the background map
    print("🗺️ Step 2: Generating Map...")
    padded_box = calculate_bounding_box(route_df, padding_percent=0.15)
    map_extent, img_w, img_h = save_map_image(
        bounding_box=padded_box,
        output_filename=map_image_path,
        output_size=(1920, 1080),
        max_zoom=19,
    )

    # 3. Convert the entire route line into X/Y pixels
    print("📏 Step 3: Calculating pixel paths...")
    full_route_pixels = convert_gps_to_pixels(
        route_df=route_df,
        extent=map_extent,
        image_path=map_image_path,
    )

    # 4. Map our UI waypoints to the closest GPS point on the route
    print("🎯 Step 4: Aligning UI Waypoints...")
    labels = [None] * len(full_route_pixels)
    popups = [None] * len(full_route_pixels)

    for wp in ui_waypoints:
        # Find the point in the dataframe with the closest Lat/Lng to our click
        distances = ((route_df["latitude"] - wp["lat"])**2 + (route_df["longitude"] - wp["lng"])**2)
        closest_idx = distances.idxmin()
        
        labels[closest_idx] = wp.get("label")
        
        # Prepare the popup data if an image or freeze exists
        if wp.get("popup_image") or wp.get("freeze_seconds"):
            popups[closest_idx] = {
                "freeze_seconds": wp.get("freeze_seconds", 3.0),
                "popup_image": wp.get("popup_image", ""),
                "narration": wp.get("narration", "") # Saved for Dev 1's future audio integration!
            }

    # 5. Render the final video!
    print(f"🎬 Step 5: Rendering {project_name}...")
    result = render_route_animation(
        img_path=map_image_path,
        points=[list(p) for p in full_route_pixels],
        labels=labels,
        popups=popups,
        output_path=output_video,
        duration_seconds=10.0,
        fps=30
    )
    
    print(f"\n🎉 DONE! Video saved to {result}")

if __name__ == "__main__":
    # Setup argparse so Rust can call: python main.py --config job_config.json
    parser = argparse.ArgumentParser(description="GPS Studio Video Renderer")
    parser.add_argument("--config", type=str, help="Path to the job_config.json file")
    
    args = parser.parse_args()
    
    if args.config:
        run_from_ui_config(args.config)
    else:
        print("No config provided. Use --config path/to/job_config.json")