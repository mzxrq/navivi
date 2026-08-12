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
import pyproj

from services.gpsparser import convert_gps_file, clean_gps_data, export_to_frontend_json
from services.filehandler import store_raw_file_with_datetime
from services.mapfetcher import MapFetcher
from services.route2vdo import render_route_animation


def data_pipeline_process(input_file: str, output_format: str = "iblue747") -> str:
    print(f"📁 Processing file: {input_file}")
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


_WGS84_TO_WEBMERCATOR = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)


def _project_route_to_pixels(lats, lons, extent: tuple[float, float, float, float], img_width_px: int, img_height_px: int) -> list[list[float]]:
    w, e, s, n = extent
    merc_x, merc_y = _WGS84_TO_WEBMERCATOR.transform(lons, lats)
    px = (np.asarray(merc_x) - w) / (e - w) * img_width_px
    py = (n - np.asarray(merc_y)) / (n - s) * img_height_px
    return [[float(x), float(y)] for x, y in zip(px, py)]


def generate_navigation_video(
    cleaned_route: dict,
    project_config_path: str = "data\\inputs\\gpsdata\\processdata\\json\\example_frontend.json",
    output_video_dir: str = "data\\outputs\\video",
    map_output_path: str = "data\\inputs\\fullmap_image\\map_background.png",
) -> list[str]:
    route_df = cleaned_route["route"]
    summary = cleaned_route.get("summary", {})

    if route_df.empty:
        raise ValueError("Cannot render a navigation video from an empty route.")

    fetcher = MapFetcher()
    bbox = fetcher.get_bounding_box(route_df, padding_factor=0.15)
    map_output_path, extent, (img_w, img_h) = fetcher.fetch_image(bbox, output_filename=map_output_path)
    if map_output_path is None:
        raise RuntimeError("Map fetch failed - cannot render video without background map.")

    route_points = _project_route_to_pixels(route_df["latitude"].to_numpy(), route_df["longitude"].to_numpy(), extent, img_w, img_h)
    route_labels = [(row["store_name"] if row.get("is_landmarked") else None) for _, row in route_df.iterrows()]
    route_popups = [None] * len(route_points)

    project_config = {}
    config_path = Path(project_config_path)
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            project_config = json.load(f)

    waypoints = project_config.get("waypoints", []) if project_config else []

    # Built once via a shared KDTree (O(n log n) build + O(m log n) query)
    # instead of the old per-waypoint O(n) linear scan repeated again
    # inside generate_residential_sequence() below — see
    # MapFetcher.build_waypoint_index for the full rationale.
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

    # Residential maps grouped strictly by waypoint: one zoomed-in chunk
    # per waypoint-to-waypoint segment (max_chunk_distance_meters=inf
    # disables the distance-based sub-splitting that generate_residential_
    # sequence() would otherwise do, so chunk count == number of waypoint
    # legs, not an arbitrary number of ~1km slices).
    image_output_dir = Path("data/inputs/res_images")
    sequence_data = MapFetcher.generate_residential_sequence(
        route_df, waypoints, image_output_dir, (img_w, img_h),
        max_chunk_distance_meters=math.inf, precomputed_indices=wp_indices,
    )

    # Distance-proportional durations averaging 10s per waypoint segment.
    # Because chunking is 1:1 with waypoint pairs now (no sub-splitting),
    # this maps directly onto sequence_data in order — segment i's
    # duration belongs to chunk i.
    seg_durations = MapFetcher.compute_segment_durations(waypoints, wp_indices, route_df, target_avg_seconds=10.0) if waypoints and len(wp_indices) > 1 else []

    res_sequence = []
    for seq_idx, item in enumerate(sequence_data):
        start_idx = item["start_idx"]
        end_idx = item["end_idx"]
        chunk = route_df.iloc[start_idx : end_idx + 1]

        chunk_points = _project_route_to_pixels(chunk["latitude"].to_numpy(), chunk["longitude"].to_numpy(), item["extent"], img_w, img_h)

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

    # Big-picture overview keeps its own flat duration (Phase 1) —
    # the per-waypoint 10s-average pacing applies to the residential
    # legs (Phase 3), which is where "navigating between waypoints"
    # actually happens.
    # Returns a LIST of file paths now — one for the overview, one per
    # waypoint residential leg, one for the summary card — instead of a
    # single combined MP4. See render_route_animation's docstring.
    return render_route_animation(
        img_path=map_output_path, points=route_points, labels=route_labels,
        popups=route_popups, output_dir=output_video_dir, summary=summary,
        res_sequence=res_sequence,
    )


def run_full_pipeline(raw_source_path: str, output_video_dir: str = "data\\outputs\\video") -> dict:
    csv_path = convert_gps_file(input_file=raw_source_path, output_filename=Path(raw_source_path).with_suffix(".csv").name, output_format="iblue747")
    cleaned_route = clean_gps_data(csv_path)
    base_dir = Path(__file__).resolve().parent
    config_path = base_dir / "data" / "inputs" / "gpsdata" / "processdata" / "json" / "example_frontend.json"

    # video_paths is now a LIST (overview + per-waypoint legs + summary),
    # not a single path — see generate_navigation_video/render_route_animation.
    video_paths = generate_navigation_video(cleaned_route=cleaned_route, project_config_path=str(config_path), output_video_dir=output_video_dir)
    return {"video_paths": video_paths, "summary": cleaned_route.get("summary", {})}


if __name__ == "__main__":
    if len(sys.argv) > 1:
        command, payload = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "")
        try:
            if command == "process_gps":
                print(handle_incoming_gps_upload(payload))
            elif command == "full_pipeline":
                # NOTE: this arg is now an output DIRECTORY (multiple
                # files get written into it), not a single .mp4 path.
                output_arg = sys.argv[3] if len(sys.argv) > 3 else "data\\outputs\\video"
                result = run_full_pipeline(payload, output_video_dir=output_arg)
                print(json.dumps({"video_paths": result["video_paths"], "summary": result["summary"]}, ensure_ascii=False))
            else:
                print(f"Error: Unknown command '{command}'", file=sys.stderr)
                sys.exit(1)
        except Exception as e:
            print(f"Error: {str(e)}", file=sys.stderr)
            sys.exit(1)