"""
main.py
---------------------------------------------------------------------------
Entry point / orchestrator for the whole GPS-to-navigation-video pipeline.

PIPELINE OVERVIEW (this is the "first run" you asked for - one raw GPS
file in, one finished MP4 out):

    raw file (.TXT/.GPX/...)
        │
        ▼  store_raw_file_with_datetime()        [filehandler.py]
    timestamped copy in rawdata/
        │
        ▼  convert_gps_file()                    [gpsparser.py]
    CSV (via gpsbabel)
        │
        ▼  clean_gps_data()                      [gpsparser.py]
    cleaned route_df + waypoints_df + summary (distance/duration)
        │
        ├──▶  export_to_frontend_json()          [gpsparser.py]
        │     frontend JSON payload (lat/lon waypoints + summary)
        │
        └──▶  calculate_bounding_box() + save_map_image()   [mapfetcher.py]
              16:9 background map PNG + its geographic extent
                  │
                  ▼  _project_route_to_pixels()   (NEW, this file)
              route/waypoints converted from lat/lon -> pixel coords
                  │
                  ▼  render_route_animation()      [route2vdo.py]
              final navigation MP4 with the distance/time summary card

Everything below `_project_route_to_pixels` and `run_full_pipeline` is
NEW wiring for this "first run." Everything else (store_raw_file,
handle_incoming_gps_upload, data_pipeline_process, and the CLI's
`process_gps` command) is UNCHANGED from before - preserved as-is since
it isn't part of what you asked me to touch.
---------------------------------------------------------------------------
"""

import sys
import json
from pathlib import Path

import numpy as np
import pyproj

from services.gpsparser import convert_gps_file, clean_gps_data, export_to_frontend_json
from services.filehandler import store_raw_file_with_datetime
from services.mapfetcher import MapFetcher, get_residential_map
from services.route2vdo import render_route_animation


# =======================================================================
# EXISTING / UNRELATED FUNCTIONS — preserved exactly as they were.
# =======================================================================

def data_pipeline_process(input_file: str, output_format: str = "iblue747") -> str:
    print(f"🔄 Processing file: {input_file}")
    route = convert_gps_file(input_file=input_file, output_filename=input_file.replace(".TXT", ".csv"), output_format=output_format)
    cleaned_route = clean_gps_data(route)
    json_route = export_to_frontend_json(cleaned_route, original_input_path=input_file, project_name="Untitled Project")
    print(f"✅ Pipeline completed successfully!")
    return json.dumps(json_route, ensure_ascii=False)


def store_raw_file(input_file: str) -> str:
    stored_file_path = store_raw_file_with_datetime(input_file)
    if stored_file_path:
        print(f"Raw file stored at: {stored_file_path}")
    else:
        print("Failed to store raw file.")
    return stored_file_path


def handle_incoming_gps_upload(raw_source_path: str) -> str:
    stored_path = store_raw_file(raw_source_path)
    if not stored_path:
        raise ValueError(f"Failed to store raw file from: {raw_source_path}")
    return data_pipeline_process(input_file=stored_path, output_format="iblue747")


# =======================================================================
# NEW: lat/lon -> pixel projection
# ---------------------------------------------------------------------
# route2vdo.py works entirely in PIXEL space (it draws directly onto the
# map PNG's canvas), but gpsparser.py's cleaned route/waypoints are in
# lat/lon (WGS84 degrees). mapfetcher.save_map_image() already hands us
# exactly what's needed to bridge the two: an `extent` tuple (w, e, s, n)
# in Web Mercator (EPSG:3857) *meters*, plus the exact pixel size of the
# saved image. This function is the missing link the route2vdo.py
# docstring referenced but that didn't exist yet in gpsparser.py.
# =======================================================================

# Built once at import time and reused for every point - constructing a
# pyproj.Transformer involves parsing CRS definitions and building an
# internal projection pipeline, which is comparatively expensive. Doing
# that once per call (or worse, once per point) would dominate the cost
# of an otherwise O(n) vectorizable operation.
_WGS84_TO_WEBMERCATOR = pyproj.Transformer.from_crs(
    "EPSG:4326", "EPSG:3857", always_xy=True
)


def _project_route_to_pixels(
    lats,
    lons,
    extent: tuple[float, float, float, float],
    img_width_px: int,
    img_height_px: int,
) -> list[list[float]]:
    """
    Projects arrays of latitude/longitude (WGS84 degrees) into pixel
    coordinates on the saved map image, using the same Web Mercator
    extent mapfetcher.save_map_image() returned for that image.

    extent is (w, e, s, n) in EPSG:3857 meters - w/e are the left/right
    (longitude-axis) bounds, s/n are the bottom/top (latitude-axis)
    bounds. Image pixel (0, 0) is the TOP-LEFT corner, so the vertical
    axis has to be flipped relative to the north-up meters axis: pixel
    y increases downward while northing increases upward.

    Vectorized via pyproj's array-input transform - a single batched
    call handles the whole route in one pass rather than one Python-
    level Transformer.transform() call per point, which matters once
    routes have thousands of GPS samples.
    """
    w, e, s, n = extent
    # `always_xy=True` above guarantees (lon, lat) -> (x, y) input/output
    # order regardless of the underlying CRS's native axis order.
    merc_x, merc_y = _WGS84_TO_WEBMERCATOR.transform(lons, lats)

    px = (np.asarray(merc_x) - w) / (e - w) * img_width_px
    py = (n - np.asarray(merc_y)) / (n - s) * img_height_px  # flipped: north is up, pixel-y is down

    return [[float(x), float(y)] for x, y in zip(px, py)]


# =======================================================================
# NEW: full end-to-end pipeline - "first run" from raw file to final MP4
# =======================================================================

def generate_navigation_video(
    cleaned_route: dict,
    output_video_path: str = "data\\outputs\\video\\route_animation.mp4",
    map_output_path: str = "data\\inputs\\fullmap_image\\map_background.png",
) -> str:
    """
    Takes the dict returned by clean_gps_data() and drives it through the map-fetch,
    pixel-projection, and video-render stages. 
    """
    route_df = cleaned_route["route"]
    waypoints_df = cleaned_route.get("waypoints")
    summary = cleaned_route.get("summary", {})

    if route_df.empty:
        raise ValueError("Cannot render a navigation video from an empty route.")

    # ---- 1. Bounding box + background map image ----
    fetcher = MapFetcher()
    bbox = fetcher.get_bounding_box(route_df, padding_factor=0.15)
    map_output_path, extent, (img_w, img_h) = fetcher.fetch_image(
        bbox, output_filename=map_output_path
    )
    if map_output_path is None:
        raise RuntimeError("Map fetch failed - cannot render video without background map.")

    # ---- 2. Project the cleaned route into pixel space (Main Map) ----
    route_points = _project_route_to_pixels(
        route_df["latitude"].to_numpy(),
        route_df["longitude"].to_numpy(),
        extent, img_w, img_h,
    )
    
    route_labels = [(row["store_name"] if row.get("is_landmarked") else None) for _, row in route_df.iterrows()]
    route_popups = [None] * len(route_points)

    # ---- 3. Project waypoints for popups (Main Map) ----
    if waypoints_df is not None and not waypoints_df.empty:
        wp_points = _project_route_to_pixels(
            waypoints_df["latitude"].to_numpy(),
            waypoints_df["longitude"].to_numpy(),
            extent, img_w, img_h,
        )
        wp_labels = [(str(name) if str(name).strip() else "Waypoint") for name in waypoints_df.get("name", ["Waypoint"] * len(wp_points))]
        wp_popups = [{"freeze_seconds": 3.0, "popup_image": img_url or None, "triggered": False} for img_url in waypoints_df.get("img_url", [None] * len(wp_points))]
        
        route_points += wp_points
        route_labels += wp_labels
        route_popups += wp_popups

    # ---- 3.5 Generate Residential Maps (Phase 3 Prep) ----
    res_sequence = []
    
    if waypoints_df is not None and not waypoints_df.empty:
        print(f" Generating {len(waypoints_df)} residential map(s) for waypoints...")
        for i, wp in waypoints_df.iterrows():
            lbl = "".join(c for c in str(wp.get("name", f"WP_{i}")) if c.isalnum() or c in (' ', '_')).rstrip()
            res_map_path = str(Path(map_output_path).parent / f"res_map_{lbl}.png")

            res_extent = get_residential_map(wp["latitude"], wp["longitude"], 400, res_map_path, (img_w, img_h))
            
            # Project only the points that exist close to this waypoint to avoid off-screen animation
            res_route_points = _project_route_to_pixels(route_df["latitude"].to_numpy(), route_df["longitude"].to_numpy(), res_extent, img_w, img_h)
            res_sequence.append({"img_path": res_map_path, "points": res_route_points, "labels": route_labels[:len(route_df)]})
            
    else:
        print(" No waypoints found! Falling back to route chunking...")
        points_per_slice = 500 # Adjust this to change chunk size
        chunks = [route_df.iloc[i : i + points_per_slice] for i in range(0, len(route_df), points_per_slice)]
        
        for i, chunk in enumerate(chunks):
            # Find the center of the chunk
            center_lat, center_lon = chunk["latitude"].mean(), chunk["longitude"].mean()
            res_map_path = str(Path(map_output_path).parent / f"res_map_chunk_{i+1}.png")

            # Fetch the map
            res_extent = get_residential_map(center_lat, center_lon, 300, res_map_path, (img_w, img_h))
            
            # Pass ONLY the points for this chunk so the dot animates properly across the screen
            chunk_points = _project_route_to_pixels(chunk["latitude"].to_numpy(), chunk["longitude"].to_numpy(), res_extent, img_w, img_h)
            
            res_sequence.append({"img_path": res_map_path, "points": chunk_points, "labels": [None] * len(chunk_points)})

    # ---- 4. Render the final video ----
    return render_route_animation(
        img_path=map_output_path,
        points=route_points,
        labels=route_labels,
        popups=route_popups,
        output_path=output_video_path,
        summary=summary,
        res_sequence=res_sequence,
    )


def run_full_pipeline(raw_source_path: str, output_video_path: str = "data\\outputs\\video\\route_animation.mp4") -> dict:
    """
    THE FIRST RUN: one call that takes a raw GPS device file all the way
    to a finished navigation MP4.

        raw file -> store -> convert -> clean -> map -> project -> video

    Returns a dict with the frontend JSON payload AND the final video
    path, so a caller (e.g. the Tauri command layer) gets everything it
    needs in one response instead of having to re-derive it.
    """
    # Stages 1-2: store + convert, reusing the existing helpers exactly
    # as they already work - no need to reinvent filename handling or
    # gpsbabel invocation here.
    stored_path = store_raw_file(raw_source_path)
    if not stored_path:
        raise ValueError(f"Failed to store raw file from: {raw_source_path}")

    csv_path = convert_gps_file(
        input_file=stored_path,
        output_filename=Path(stored_path).with_suffix(".csv").name,
        output_format="iblue747",
    )

    # Stage 3: clean + summarize (summary is now baked into this call's
    # return value - see the clean_gps_data() rewrite from earlier).
    cleaned_route = clean_gps_data(csv_path)

    # Stage 3b: frontend JSON (unchanged responsibility, still lat/lon -
    # this is what a map UI would consume, separate from the pixel-space
    # video renderer).
    frontend_json = export_to_frontend_json(
        cleaned_route, original_input_path=stored_path, project_name="Untitled Project"
    )

    # Stages 4-6: map fetch, pixel projection, video render.
    video_path = generate_navigation_video(cleaned_route, output_video_path=output_video_path)

    return {
        "frontend_json": frontend_json,
        "video_path": video_path,
        "summary": cleaned_route.get("summary", {}),
    }


# =======================================================================
# CLI — `process_gps` is unchanged; `full_pipeline` is the new command
# that drives the entire first run described above.
# =======================================================================
if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1]
        payload = sys.argv[2] if len(sys.argv) > 2 else ""

        try:
            if command == "process_gps":
                # Unchanged: JSON-only pipeline, no map/video generation.
                result_json = handle_incoming_gps_upload(payload)
                print(result_json)

            elif command == "full_pipeline":
                # New: raw file -> finished navigation MP4, in one shot.
                output_arg = sys.argv[3] if len(sys.argv) > 3 else "data\\outputs\\videoroute_animation.mp4"
                result = run_full_pipeline(payload, output_video_path=output_arg)
                print(json.dumps({
                    "video_path": result["video_path"],
                    "summary": result["summary"],
                }, ensure_ascii=False))

            else:
                print(f"Error: Unknown command '{command}'", file=sys.stderr)
                sys.exit(1)
        except Exception as e:
            print(f"Error: {str(e)}", file=sys.stderr)
            sys.exit(1)