"""
main.py
---------------------------------------------------------------------------
Entry point / orchestrator for the whole GPS-to-navigation-video pipeline,
integrated with Irodori-TTS speech synthesis and audio-video synchronization.
---------------------------------------------------------------------------
"""

import sys
import json
import math
import asyncio
import subprocess
import os
from pathlib import Path

import numpy as np
from typing import Optional
import pyproj

from services.gpsparser import convert_gps_file, clean_gps_data, export_to_frontend_json, haversine_vectorized
from services.filehandler import initialize_new_project, save_project_asset_image, store_raw_file_with_datetime, generate_and_save_audio
from services.mapfetcher import MapFetcher
from services.route2vdo import RouteAnimator
from services.tts import (
    get_irodori_speech, 
    analyze_wav_pauses, 
    concatenate_audio_files,
    assemble_final_deliverable
)
from services.job_config import JobConfigManager
from services.vdoeditor import VideoEditor
from typing import List, Dict, Any, Optional
from services.llmscript import analyze_travel_image


def data_pipeline_process(input_file: str, output_format: str = "iblue747") -> str:
    print(f"📁 Processing file: {input_file}")
    route = convert_gps_file(input_file=input_file, output_filename=input_file.replace(".TXT", ".csv"), output_format=output_format)
    cleaned_route = clean_gps_data(route)
    json_route = export_to_frontend_json(cleaned_route, original_input_path=input_file, project_name="Untitled Project")
    print(f"✅ Pipeline completed successfully!")
    return json.dumps(json_route, ensure_ascii=False)

def generate_audio_tts(text: str, output_path: str = "output.mp3") -> str | None:
    """Backwards-compatibility alias for legacy tests."""
    return generate_and_save_audio(text, output_path)

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
    audio_durations: Optional[list] = None,
    audio_pauses: Optional[list] = None
) -> list[str]:

    audio_durations = audio_durations or []
    audio_pauses = audio_pauses or []
    
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
    route_popups: List[Optional[Dict[str, Any]]] = [None] * len(route_points)

    project_config = {}
    config_path = Path(project_config_path)
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            project_config = json.load(f)

    waypoints = project_config.get("waypoints", []) if project_config else []
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

    seg_durations = MapFetcher.compute_segment_durations(waypoints, wp_indices, route_df, target_avg_seconds=20.0) if waypoints and len(wp_indices) > 1 else []

    res_sequence = []
    for seq_idx, item in enumerate(sequence_data):
        start_idx = item["start_idx"]
        end_idx = item["end_idx"]
        chunk = route_df.iloc[start_idx : end_idx + 1]
        chunk_points = _project_route_to_pixels(chunk["latitude"].to_numpy(), chunk["longitude"].to_numpy(), item["extent"], img_w, img_h)

        # --- NEW: Calculate the real GPS travel time for this specific clip ---
        real_time_sec = 0.0
        if "timestamp" in chunk.columns and len(chunk) > 1:
            real_time_sec = (chunk["timestamp"].iloc[-1] - chunk["timestamp"].iloc[0]).total_seconds()
        # ----------------------------------------------------------------------
        
        # --- RESTORED ORIGINAL LOGIC ---
        lats_arr, lons_arr = item["lats"], item["lons"]
        if len(lats_arr) > 1:
            seg_distance_km = float(np.nansum(
                haversine_vectorized(lats_arr[:-1], lons_arr[:-1], lats_arr[1:], lons_arr[1:])
            ))
        else:
            seg_distance_km = 0.0

        distance_fallback = seg_durations[seq_idx] if seq_idx < len(seg_durations) else 10.0
        has_audio = bool(audio_durations) and seq_idx < len(audio_durations) and audio_durations[seq_idx] > 0
        active_pauses = audio_pauses[seq_idx] if audio_pauses and seq_idx < len(audio_pauses) else []

        if has_audio:
            audio_time = audio_durations[seq_idx]
            travel_duration = audio_time
            total_time = audio_time
        else:
            total_time = distance_fallback
            travel_duration = distance_fallback
        # --------------------------------

        res_sequence.append({
            "img_path": item["img_path"],
            "extent": item["extent"],
            "lats": item["lats"],
            "lons": item["lons"],
            "points": chunk_points,
            "labels": route_labels[start_idx : end_idx + 1],
            "popups": route_popups[start_idx : end_idx + 1],
            "travel_duration": travel_duration,
            "segment_duration": total_time,
            "real_duration_seconds": real_time_sec, # <-- Safely added!
            "distance_km": seg_distance_km,  
            "pauses": active_pauses
        })

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
        "res_duration": 12.0
    }

    animator = RouteAnimator(animator_config)
    return animator.render(
        img_path=map_output_path, points=route_points, labels=route_labels,
        popups=route_popups, res_sequence=res_sequence, summary=summary
    )

async def run_synced_tts_pipeline(project_config_path: str, output_video_dir: Optional[str] = None) -> dict:
    """
    Orchestrates upstream TTS synthesis, exact audio duration and pause analysis,
    full navigation video rendering, and final assembly into a combined deliverable
    ensuring every active waypoint clip has its corresponding narration audio.
    """
    config_path = Path(project_config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Project config not found: {project_config_path}")

    # 1. Initialize the global JobConfigManager singleton store[cite: 9, 16]
    job_config = JobConfigManager(config_path)

    # Resolve project centralized directories from config
    project_dir = Path(job_config.get("directory_path", config_path.parent))
    audio_output_dir = project_dir / "audio"
    audio_output_dir.mkdir(parents=True, exist_ok=True)

    if not output_video_dir:
        output_video_dir = str((project_dir / "video").resolve())

    waypoints = job_config.get_waypoints()
    audio_paths = []
    audio_durations = []
    audio_pauses = []

    # 2. Instantiate TTS client targeting the project's audio folder[cite: 13]
    from services.tts import IrodoriTTSClient, AudioProcessor
    tts_client = IrodoriTTSClient(output_dir=audio_output_dir)
    audio_processor = AudioProcessor(output_dir=audio_output_dir)

    print("🎙️ Generating Irodori-TTS narration audio for waypoints...", file=sys.stderr)
    for wp in waypoints:
        text = wp.get("narration", "").strip()
        if text:
            # Generates and saves each individual audio file in the project's audio folder[cite: 13]
            path = await tts_client.generate_speech(text)
            audio_paths.append(path)
            analysis = audio_processor.analyze_pauses(path)
            audio_durations.append(analysis['duration_seconds'])
            audio_pauses.append(analysis['pauses'])
            print(f"   -> Generated {path} (Duration: {analysis['duration_seconds']}s, Pauses: {len(analysis['pauses'])})", file=sys.stderr)
        else:
            audio_paths.append(None)
            audio_durations.append(0.0)
            audio_pauses.append([])

    valid_audio_paths = [p for p in audio_paths if p]
    master_audio = None
    if valid_audio_paths:
        master_audio_path = audio_output_dir / "master_navigation_audio.wav"
        master_audio = audio_processor.concatenate_files(valid_audio_paths, str(master_audio_path))

    # 3. Retrieve and convert the raw GPS route to CSV so latitude/longitude columns exist[cite: 8]
    raw_gps_path = job_config.get("source_files", {}).get("gps_route")
    if not raw_gps_path:
        raise ValueError("GPS route source file not specified in configuration.")

    csv_output_filename = f"{Path(raw_gps_path).stem}_converted.csv"
    csv_path = convert_gps_file(
        input_file=raw_gps_path,
        output_filename=csv_output_filename,
        output_format="iblue747"
    )
    cleaned_route = clean_gps_data(csv_path)

    # 4. Generate the video files with exact audio timings injected
    base_dir = Path(__file__).resolve().parent
    frontend_config_path = base_dir / "data" / "inputs" / "gpsdata" / "processdata" / "json" / "example_frontend.json"

    video_paths = generate_navigation_video(
        cleaned_route=cleaned_route,
        project_config_path=str(frontend_config_path),
        output_video_dir=output_video_dir,
        audio_durations=audio_durations,
        audio_pauses=audio_pauses
    )

    editor = VideoEditor(job_config=job_config)

    final_video_paths = []
    segment_has_narration = []
    segment_narration_audio = []
    segment_durations = []

    has_summary = len(video_paths) > 0 and "summary" in video_paths[-1]

    DEFAULT_OVERVIEW_DURATION = 8.0
    DEFAULT_PAUSE_SECONDS = 2.0
    DEFAULT_SUMMARY_HOLD = 4.0

    # 5. Mux audio into every respective segment cleanly using VideoEditor
    for i, vid_path in enumerate(video_paths):
        audio_idx = i  # Direct 1-to-1 mapping!

        if audio_idx < len(audio_paths) and audio_paths[audio_idx]:
            print(f"🎵 Muxing audio into segment {i}...", file=sys.stderr)
            
            base_name = Path(vid_path).stem
            muxed_filename = f"{base_name}_with_audio.mp4"
            
            try:
                muxed_path = editor.mux_audio_to_video(
                    video_path=vid_path, 
                    audio_path=audio_paths[audio_idx], 
                    output_filename=muxed_filename
                )
            except Exception as e:
                raise RuntimeError(f"Failed to mux audio into segment {i} ({vid_path}): {e}")

            final_video_paths.append(muxed_path)
            segment_has_narration.append(True)
            segment_narration_audio.append(audio_paths[audio_idx])
            segment_durations.append(audio_durations[audio_idx])

            if os.path.exists(vid_path):
                os.remove(vid_path)
        else:
            final_video_paths.append(vid_path)
            segment_has_narration.append(False)
            segment_narration_audio.append(None)
            
            # Padding durations if no audio exists
            if i == 0:
                segment_durations.append(DEFAULT_OVERVIEW_DURATION + DEFAULT_PAUSE_SECONDS + DEFAULT_SUMMARY_HOLD)
            else:
                segment_durations.append(12.0)  # Default fallback for waypoint legs

    # 6. Final assembly of all video segments and timeline audio[cite: 13]
    print("🎬 Assembling final combined video + audio...", file=sys.stderr)
    assembly = assemble_final_deliverable(
        video_segment_paths=final_video_paths,
        segment_has_narration=segment_has_narration,
        segment_durations=segment_durations,
        segment_narration_audio=segment_narration_audio,
        output_dir=output_video_dir,
    )

    return {
        "video_paths": final_video_paths,                          
        "master_audio_path": master_audio,                          
        "final_video_path": assembly["full_video_path"],        
        "full_master_audio_path": assembly["full_audio_path"],  
        "final_combined_path": assembly["final_combined_path"], 
        "summary": cleaned_route.get("summary", {})
    }


def run_full_pipeline(raw_source_path: str, output_video_dir: Optional[str] = None) -> dict:
    # 1. Automatically find the project directory from the input file path
    source_path = Path(raw_source_path)
    project_dir = source_path.parent
    config_file_path = project_dir / "job_config.json"

    # 2. Initialize the global JobConfigManager singleton with the correct project config path
    job_config = JobConfigManager(config_file_path)

    # 3. Dynamically fall back to the project's video directory if none is provided
    if not output_video_dir:
        base_path = Path(job_config.get("directory_path", project_dir))
        output_video_dir = str((base_path / "video").resolve())

    csv_path = convert_gps_file(
        input_file=raw_source_path, 
        output_filename=Path(raw_source_path).with_suffix(".csv").name, 
        output_format="iblue747"
    )
    cleaned_route = clean_gps_data(csv_path)
    
    # Use the job config's frontend template path if available
    base_dir = Path(__file__).resolve().parent
    config_path = base_dir / "data" / "inputs" / "gpsdata" / "processdata" / "json" / "example_frontend.json"

    video_paths = generate_navigation_video(
        cleaned_route=cleaned_route, 
        project_config_path=str(config_path), 
        output_video_dir=output_video_dir
    )
    return {"video_paths": video_paths, "summary": cleaned_route.get("summary", {})}


if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1]
        payload = sys.argv[2] if len(sys.argv) > 2 else ""
        try:
            if command == "process_gps":
                print(handle_incoming_gps_upload(payload))
                
            elif command == "full_pipeline":
                output_arg = sys.argv[3] if len(sys.argv) > 3 else None
                result = run_full_pipeline(payload, output_video_dir=output_arg)
                print(json.dumps({"success": True, "video_paths": result["video_paths"], "summary": result["summary"]}, ensure_ascii=False))
                
            elif command == "init_project":
                project_name = sys.argv[3] if len(sys.argv) > 3 else "Untitled Project"
                config_path = initialize_new_project(user_id=payload, project_name=project_name)
                print(json.dumps({"success": True, "config_path": config_path}, ensure_ascii=False))
                
            elif command == "save_asset":
                source_image_path = sys.argv[3] if len(sys.argv) > 3 else ""
                asset_path = save_project_asset_image(project_dir=payload, source_image_path=source_image_path)
                print(json.dumps({"success": True, "asset_path": asset_path}, ensure_ascii=False))
                
            elif command == "generate_speech":
                output_path = sys.argv[3] if len(sys.argv) > 3 else "output.mp3"
                saved_path = generate_and_save_audio(text=payload, output_path=output_path)
                print(json.dumps({"success": True, "audio_path": saved_path}, ensure_ascii=False))

            elif command == "synced_tts_pipeline":
                output_arg = sys.argv[3] if len(sys.argv) > 3 else None
                result = asyncio.run(run_synced_tts_pipeline(project_config_path=payload, output_video_dir=output_arg))
                print(json.dumps({"success": True, **result}, ensure_ascii=False))

            elif command == "save_config":
                # 1. This initializes the global singleton instance in memory
                config = JobConfigManager(payload)
                
                # 2. Saves any pending state back to disk
                config.save()
                
                print(json.dumps({"success": True}, ensure_ascii=False))

            elif command == "analyze_image":
                # payload is the target image path passed from Tauri
                analysis_result = analyze_travel_image(payload)
                print(json.dumps({
                    "success": True, 
                    "data": analysis_result
                }, ensure_ascii=False))

            else:
                error_res = {"success": False, "error": f"Unknown command '{command}'"}
                print(json.dumps(error_res, ensure_ascii=False))
                sys.exit(1)
                
        except Exception as e:
            error_res = {"success": False, "error": str(e)}
            print(json.dumps(error_res, ensure_ascii=False))
            sys.exit(1)


# =============================================================================
# TEST BLOCK
# =============================================================================
"""
    py main.py process_gps "data/inputs/gpsdata/raw/LOG00002.TXT"
    py main.py full_pipeline "C:\\Users\\user1\\Documents\\Navivi\\Projects\\proj_2026_very_cool_tomogashima_islands\\log.txt"
    py main.py init_project "local_user" "My Cool Project"
    py main.py save_asset "data/projects/proj_2026_very_cool_tomogashima_islands" "assets/images/custom_marker.png"
    py main.py generate_speech "Welcome to the navigation video!" "data/projects/proj_2026_very_cool_tomogashima_islands/audio/welcome.mp3"
    py main.py synced_tts_pipeline "C:\\Users\\user1\\Documents\\Navivi\\Projects\\proj_2026_very_cool_tomogashima_islands\\log.txt"
    py main.py save_config "C:\\Users\\user1\\Documents\\Navivi\\Projects\\proj_2026_very_cool_tomogashima_islands\\job_config.json"
    python main.py analyze_image "test_map.png"
"""