import math
import json
from pathlib import Path
from typing import Optional, Any

import numpy as np
import pyproj

from services.gps_parser import convert_gps_file, clean_gps_data, haversine_vectorized
from services.mapfetcher import MapFetcher
from services.route2vdo import RouteAnimator
from services.localization import format_waypoint_label
from services.job_config import JobConfigManager

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_FRONTEND_CONFIG = (
    BASE_DIR
    / "data"
    / "inputs"
    / "gpsdata"
    / "processdata"
    / "json"
    / "example_frontend.json"
)
DEFAULT_MAP_BACKGROUND = (
    BASE_DIR / "data" / "inputs" / "fullmap_image" / "map_background.png"
)

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
    w, e, s, n = extent
    merc_x, merc_y = _WGS84_TO_WEBMERCATOR.transform(lons, lats)
    px = (np.asarray(merc_x) - w) / (e - w) * img_width_px
    py = (n - np.asarray(merc_y)) / (n - s) * img_height_px
    return [[float(x), float(y)] for x, y in zip(px, py)]


def generate_navigation_video(
    cleaned_route: dict,
    project_config_path: str = str(DEFAULT_FRONTEND_CONFIG),
    output_video_dir: str = str(BASE_DIR / "data" / "outputs" / "video"),
    map_output_path: str = str(DEFAULT_MAP_BACKGROUND),
    audio_durations: Optional[list[float]] = None,
    audio_pauses: Optional[list[Any]] = None,
) -> list[str]:

    audio_durations = audio_durations or []
    audio_pauses = audio_pauses or []
    route_df = cleaned_route["route"]
    summary = cleaned_route.get("summary", {})

    if route_df.empty:
        raise ValueError("Cannot render a navigation video from an empty route.")

    fetcher = MapFetcher()
    bbox = fetcher.get_bounding_box(route_df, padding_factor=0.15)
    map_output_path, extent, (img_w, img_h) = fetcher.fetch_image(
        bbox, output_filename=map_output_path
    )

    if map_output_path is None:
        raise RuntimeError(
            "Map fetch failed - cannot render video without background map."
        )

    route_points = _project_route_to_pixels(
        route_df["latitude"].to_numpy(),
        route_df["longitude"].to_numpy(),
        extent,
        img_w,
        img_h,
    )
    route_labels = [
        (row["store_name"] if row.get("is_landmarked") else None)
        for _, row in route_df.iterrows()
    ]
    route_popups = [None] * len(route_points)

    project_config = {}
    config_path = Path(project_config_path)
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            project_config = json.load(f)

    waypoints = project_config.get("waypoints", []) if project_config else []
    wp_indices = MapFetcher.build_waypoint_index(route_df, waypoints)
    subtitle_lang = project_config.get("settings", {}).get("subtitle_language", "en")

    if waypoints:
        print(f"Injecting {len(waypoints)} custom waypoints from JSON config...")
        for idx, wp in enumerate(waypoints):
            closest_idx = wp_indices[idx]
            raw_label = wp.get("label", "Waypoint")
            formatted_label = format_waypoint_label(raw_label, subtitle_lang)

            if idx == 0:
                wp_label = f"Start: {formatted_label}" if formatted_label else "Start"
            elif idx == len(waypoints) - 1:
                wp_label = f"Stop: {formatted_label}" if formatted_label else "Stop"
            else:
                wp_label = formatted_label

            route_labels[closest_idx] = wp_label
            raw_popup = wp.get("popup_image")
            popup_img = (
                str(raw_popup[0])
                if isinstance(raw_popup, list) and raw_popup
                else str(raw_popup) if raw_popup else None
            )
            route_popups[closest_idx] = {
                "freeze_seconds": float(wp.get("freeze_seconds", 3.0)),
                "popup_image": popup_img,
                "triggered": False,
            }

    image_output_dir = BASE_DIR / "data" / "inputs" / "res_images"
    sequence_data = MapFetcher.generate_residential_sequence(
        route_df,
        waypoints,
        image_output_dir,
        (img_w, img_h),
        max_chunk_distance_meters=math.inf,
        precomputed_indices=wp_indices,
    )

    seg_durations = (
        MapFetcher.compute_segment_durations(
            wp_indices, route_df, target_avg_seconds=20.0
        )
        if waypoints and len(wp_indices) > 1
        else []
    )

    res_sequence = []
    for seq_idx, item in enumerate(sequence_data):
        start_idx, end_idx = item["start_idx"], item["end_idx"]
        chunk = route_df.iloc[start_idx : end_idx + 1]
        chunk_points = _project_route_to_pixels(
            chunk["latitude"].to_numpy(),
            chunk["longitude"].to_numpy(),
            item["extent"],
            img_w,
            img_h,
        )

        real_time_sec = (
            (chunk["timestamp"].iloc[-1] - chunk["timestamp"].iloc[0]).total_seconds()
            if "timestamp" in chunk.columns and len(chunk) > 1
            else 0.0
        )
        lats_arr, lons_arr = item["lats"], item["lons"]
        seg_distance_km = (
            float(
                np.nansum(
                    haversine_vectorized(
                        lats_arr[:-1], lons_arr[:-1], lats_arr[1:], lons_arr[1:]
                    )
                )
            )
            if len(lats_arr) > 1
            else 0.0
        )

        distance_fallback = (
            seg_durations[seq_idx] if seq_idx < len(seg_durations) else 10.0
        )
        has_audio = (
            bool(audio_durations)
            and seq_idx < len(audio_durations)
            and audio_durations[seq_idx] > 0
        )
        active_pauses = (
            audio_pauses[seq_idx]
            if audio_pauses and seq_idx < len(audio_pauses)
            else []
        )

        travel_duration = total_time = (
            audio_durations[seq_idx] if has_audio else distance_fallback
        )
        raw_img_path = item.get("img_path")
        res_img = (
            str(raw_img_path[0])
            if isinstance(raw_img_path, list) and raw_img_path
            else str(raw_img_path) if raw_img_path else None
        )

        res_sequence.append(
            {
                "img_path": res_img,
                "extent": item["extent"],
                "lats": item["lats"],
                "lons": item["lons"],
                "points": chunk_points,
                "labels": route_labels[start_idx : end_idx + 1],
                "popups": route_popups[start_idx : end_idx + 1],
                "travel_duration": travel_duration,
                "segment_duration": total_time,
                "real_duration_seconds": real_time_sec,
                "distance_km": seg_distance_km,
                "pauses": active_pauses,
            }
        )

    animator_config = {
        "output_dir": output_video_dir,
        "fps": project_config.get("fps", 30),
        "duration": project_config.get("duration_seconds", 8.0),
        "line_color": project_config.get("line_color", (0, 200, 255)),
        "line_thickness": project_config.get("line_thickness", 10),
        "marker_color": project_config.get("marker_color", (0, 0, 255)),
        "marker_radius": project_config.get("marker_radius", 18),
        "pause": project_config.get("pause_seconds", 2.0),
        "summary_hold": project_config.get("summary_hold", 4.0),
        "summary_fade": project_config.get("summary_fade", 0.5),
        "res_duration": 12.0,
    }

    animator = RouteAnimator(animator_config)
    return animator.render(
        img_path=map_output_path,
        points=route_points,
        labels=route_labels,
        popups=route_popups,
        res_sequence=res_sequence,
        summary=summary,
    )


def run_full_pipeline(
    raw_source_path: str, output_video_dir: Optional[str] = None
) -> dict:
    source_path = Path(raw_source_path)
    project_dir = source_path.parent
    config_file_path = project_dir / "job_config.json"
    job_config = JobConfigManager(config_file_path)

    if not output_video_dir:
        base_path = Path(job_config.get("directory_path", project_dir))
        output_video_dir = str((base_path / "video").resolve())

    csv_path = convert_gps_file(
        input_file=raw_source_path,
        output_filename=source_path.with_suffix(".csv").name,
        output_format="iblue747",
    )
    cleaned_route = clean_gps_data(csv_path)

    video_paths = generate_navigation_video(
        cleaned_route=cleaned_route,
        project_config_path=str(config_file_path),
        output_video_dir=output_video_dir,
    )
    return {"video_paths": video_paths, "summary": cleaned_route.get("summary", {})}
