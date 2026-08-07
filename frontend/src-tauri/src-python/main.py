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

if __name__ == "__main__":
    run_pipeline("src-tauri\\src-python\\data\\inputs\\gpsdata\\rawdata\\LOG00002.TXT", device_format="iblue747")