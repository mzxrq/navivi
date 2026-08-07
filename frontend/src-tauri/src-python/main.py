"""
run_pipeline.py
---------------------------------------------------------------------------
One-pass GPS -> map -> video pipeline. Fetches the map ONCE and reuses the
same pixel_points computed via gpsparser.convert_gps_to_pixels — no
redundant tile downloads, no discarded work.

Import and call `run_pipeline(...)` from any other file:

    from run_pipeline import run_pipeline
    run_pipeline("backend\\data\\LOG00001.TXT", device_format="iblue747")
"""

from pathlib import Path

import pandas as pd

from services.gpsparser import clean_gps_data, convert_nmea, convert_gps_to_pixels, export_pixels_to_json
from services.mapfetcher import calculate_bounding_box, save_map_image
from services.route2vdo import render_route_animation

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
    """
    Runs the full GPS-log -> video pipeline in a single pass:

      1. NMEA -> CSV                     (convert_nmea, gpsbabel)
      2. CSV  -> cleaned route DataFrame  (clean_gps_data)
      3. route DataFrame -> bounding box  (calculate_bounding_box)
      4. bounding box -> 16:9 HD map      (save_map_image)  [fetched ONCE]
      5. route DataFrame -> pixel points  (convert_gps_to_pixels, using the
         SAME extent/image from step 4 — no second map fetch)
      6. pixel points -> route.json       (export_pixels_to_json) [optional,
         handy for inspecting/re-running the video step without repeating
         steps 1-5]
      7. map + pixel points -> MP4        (render_route_animation)

    Returns the output video path.
    """
    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    Path(map_image_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_video).parent.mkdir(parents=True, exist_ok=True)

    # 1. Convert the raw NMEA text file to CSV
    track_csv = convert_nmea(nmea_file, csv_path, device_format)

    # 2. Clean the data and extract the route DataFrame
    gps_data = clean_gps_data(track_csv)
    route_df = gps_data["route"]
    waypoints_df = gps_data["waypoints"]

    # NOTE: clean_gps_data splits named points into `waypoints_df` and
    # puts everything else (usually unnamed) into `route_df`. If you want
    # checkpoint labels to show up on the video, route_df needs a "name"
    # (or "label") column with values on the points you want marked — as
    # written, route_df's names will mostly be empty since named points
    # were pulled out into waypoints_df. Merge waypoints back in by
    # timestamp/position first if you want them to appear as markers.

    # 3. Calculate the padded bounding box for the map
    padded_box = calculate_bounding_box(route_df, padding_percent=padding_percent)

    # 4. Fetch and save the high-resolution map image — ONCE.
    #    save_map_image returns 3 values: unpack all of them.
    map_extent, img_w, img_h = save_map_image(
        bounding_box=padded_box,
        output_filename=map_image_path,
        output_size=output_size,
        max_zoom=max_zoom,
    )

    # 5. Convert every route point to pixel coordinates on that SAME image,
    #    reusing map_extent from step 4 (no second tile fetch).
    pixel_points = convert_gps_to_pixels(
        route_df=route_df,
        extent=map_extent,
        image_path=map_image_path,
    )
    print("First 5 pixel locations:", pixel_points[:5])

    # Labels: pull from a "name" column if present, else no labels.
    # route_df["name"] comes straight from pandas, where missing values are
    # NaN (a float) rather than None — sanitize here so downstream code
    # never has to special-case NaN vs None vs "".
    if "name" in route_df.columns:
        labels = [None if pd.isna(v) else str(v) for v in route_df["name"].tolist()]
    else:
        labels = [None] * len(route_df)

    # 6. (Optional) export to route.json — useful if you want to re-render
    #    the video later with different settings without repeating 1-5.
    export_pixels_to_json(pixel_points, labels, output_json_path=json_path)

    # 7. Render the final video directly from the pixel points we already
    #    have — no second bounding-box/map/pixel pass.
    print(f"🎬 Sending {len(pixel_points)} points to the video renderer...")
    result = render_route_animation(
        img_path=map_image_path, # type: ignore
        points=[list(p) for p in pixel_points], # type: ignore
        labels=labels,
        output_path=output_video,
        duration_seconds=duration_seconds,
        fps=fps,
        line_thickness=line_thickness,
        marker_radius=marker_radius,
    )

    print(f"✅ Pipeline complete → {result}")
    return result


if __name__ == "__main__":
    run_pipeline("src-tauri\\src-python\\data\\inputs\\gpsdata\\rawdata\\LOG00002.TXT", device_format="iblue747")