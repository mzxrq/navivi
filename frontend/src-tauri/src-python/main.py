"""
main.py
---------------------------------------------------------------------------
Entry point / orchestrator for the whole GPS-to-navigation-video pipeline,
integrated with Irodori-TTS speech synthesis and audio-video synchronization.
---------------------------------------------------------------------------
"""

import sys
import json
import asyncio
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pyproj
from scipy.spatial import cKDTree
import xml.etree.ElementTree as ET

# Add the directory containing main.py to the Python path
script_dir = Path(__file__).resolve().parent
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

# Import the refactored Object-Oriented Services
from services.gpsparser import GPSParser
from services.filehandler import FileHandler
from services.mapfetcher import MapFetcher
from services.route2vdo import Route2VDO
from services.tts import TTSService
from services.job_config import JobConfigManager

# Projections
_WGS84_TO_WEBMERCATOR = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)


def load_route_data(filepath: str) -> pd.DataFrame:
    """Safely loads GPS data from either GPX XML or CSV formats."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Route file not found: {filepath}")
    
    # 1. Parse GPX natively
    if path.suffix.lower() in [".gpx", ".xml"]:
        tree = ET.parse(path)
        root = tree.getroot()
        pts = []
        for elem in root.iter():
            if 'trkpt' in elem.tag or 'wpt' in elem.tag:
                try:
                    pts.append({
                        'lat': float(elem.attrib['lat']),
                        'lng': float(elem.attrib['lon'])
                    })
                except KeyError:
                    pass
        if not pts:
            raise ValueError(f"No trackpoints found in GPX file: {filepath}")
        return pd.DataFrame(pts)
        
    # 2. Parse CSV
    df = pd.read_csv(path)
    df.columns = df.columns.str.strip().str.lower()
    df = df.rename(columns={"latitude": "lat", "longitude": "lng", "lon": "lng"})
    
    # 3. Fallback for headerless CSVs
    if "lat" not in df.columns or "lng" not in df.columns:
        df = pd.read_csv(path, header=None)
        if df.shape[1] >= 2:
            df = df.rename(columns={0: "lat", 1: "lng"})
            
    if "lat" not in df.columns:
        raise KeyError(f"Could not parse lat/lng from {filepath}. Available columns: {list(df.columns)}")
        
    return df


def _project_route_to_pixels(lats: np.ndarray, lons: np.ndarray, extent: tuple, img_width_px: int, img_height_px: int) -> list:
    w, e, s, n = extent
    merc_x, merc_y = _WGS84_TO_WEBMERCATOR.transform(lons, lats)
    px = (np.asarray(merc_x) - w) / (e - w) * img_width_px
    py = (n - np.asarray(merc_y)) / (n - s) * img_height_px
    return [[float(x), float(y)] for x, y in zip(px, py)]


def generate_navigation_video(
    cleaned_route: pd.DataFrame,
    project_config_path: str,
    output_video_dir: str = "data/outputs/video",
    audio_durations: list = None,
    audio_pauses: list = None
) -> list[str]:
    
    if cleaned_route.empty:
        raise ValueError("Cannot render a navigation video from an empty route.")

    # 1. Initialize Services
    config = JobConfigManager(project_config_path)
    fetcher = MapFetcher(config)
    fh = FileHandler()
    r2v = Route2VDO(fetcher, fh)

    # 2. Get master map bounding box and fetch map
    bbox = fetcher.get_bounding_box(cleaned_route, padding=0.15)
    master_map_img = fetcher.fetch_map(bbox)
    
    out_dir = Path(output_video_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    map_output_path = str(out_dir / "master_background.png")
    master_map_img.save(map_output_path)
    
    img_w, img_h = master_map_img.size

    route_points_list = _project_route_to_pixels(
        cleaned_route["lat"].to_numpy(), 
        cleaned_route["lng"].to_numpy(), 
        bbox, img_w, img_h
    )
    
    # Convert the list to a NumPy array for MapFetcher compatibility
    route_points = np.array(route_points_list)
    
    route_labels = [None] * len(route_points)
    route_popups = [None] * len(route_points)

    waypoints = config.get_waypoints()
    wp_indices = []
    
    # 4. Map Waypoints to Route Indices
    if waypoints:
        print(f"🗺️ Injecting {len(waypoints)} custom waypoints from JSON config...")
        cleaned_wps = []
        for wp in waypoints:
            wp_lat = float(wp.get("lat") or wp.get("latitude") or 0)
            wp_lng = float(wp.get("lng") or wp.get("longitude") or wp.get("lon") or 0)
            cleaned_wps.append([wp_lat, wp_lng])
        
        tree = cKDTree(cleaned_route[["lat", "lng"]].to_numpy())
        _, indices = tree.query(cleaned_wps)
        wp_indices = np.atleast_1d(indices).tolist()

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

    # 5. Prepare Sequence Data for Residential Leg Pacing
    res_sequence = []
    if waypoints and len(wp_indices) > 1:
        for seq_idx in range(len(wp_indices) - 1):
            start_idx = wp_indices[seq_idx]
            end_idx = wp_indices[seq_idx + 1]
            
            if start_idx > end_idx:
                start_idx, end_idx = end_idx, start_idx
                
            chunk = cleaned_route.iloc[start_idx : end_idx + 1]
            chunk_points = _project_route_to_pixels(
                chunk["lat"].to_numpy(), chunk["lng"].to_numpy(), 
                bbox, img_w, img_h
            )
            
            distance_fallback = 10.0
            audio_durations_list = audio_durations or []
            audio_pauses_list = audio_pauses or []
            
            has_audio = seq_idx < len(audio_durations_list) and audio_durations_list[seq_idx] > 0
            active_pauses = audio_pauses_list[seq_idx] if seq_idx < len(audio_pauses_list) else []

            if has_audio:
                audio_time = audio_durations_list[seq_idx]
                travel_duration = distance_fallback 
                total_time = max(distance_fallback, audio_time)
            else:
                total_time = distance_fallback
                travel_duration = distance_fallback

            res_sequence.append({
                "img_path": map_output_path,
                "extent": bbox,
                "lats": chunk["lat"].to_numpy(),
                "lons": chunk["lng"].to_numpy(),
                "points": chunk_points,
                "labels": route_labels[start_idx : end_idx + 1],
                "popups": route_popups[start_idx : end_idx + 1],
                "travel_duration": travel_duration,
                "segment_duration": total_time,
                "pauses": active_pauses
            })
    
    # 6. Render the animation via the Route2VDO service
    video_paths = r2v.render_route_animation(
        img_path=map_output_path, 
        points=route_points, 
        labels=route_labels,
        popups=route_popups, 
        output_dir=output_video_dir, 
        fps=config.get_settings().get("fps", 30),
        duration_seconds=30.0,
        res_sequence=res_sequence,
        summary=config.get("summary", {})
    )
    
    return video_paths


async def run_synced_tts_pipeline(project_config_path: str, output_video_dir: str = "data/outputs/video") -> dict:
    """
    Orchestrates upstream TTS synthesis, audio/pause analysis, 
    video rendering, and final assembly.
    """
    config = JobConfigManager(project_config_path)
    tts = TTSService()
    waypoints = config.get_waypoints()
    
    audio_paths = []
    audio_durations = []
    audio_pauses = []

    print("🎙️ Generating Irodori-TTS narration audio for waypoints...")
    for wp in waypoints:
        text = wp.get("narration", "").strip()
        if text:
            try:
                path = await tts.get_irodori_speech(text)
                audio_paths.append(path)
                
                analysis = tts.analyze_wav_pauses(path)
                audio_durations.append(analysis['duration_seconds'])
                audio_pauses.append(analysis['pauses'])
                print(f"   -> Generated {path} (Duration: {analysis['duration_seconds']}s)")
            except Exception as e:
                print(f"   -> Warning: Failed to generate TTS for waypoint: {e}")
                audio_paths.append(None)
                audio_durations.append(0.0)
                audio_pauses.append([])
        else:
            audio_paths.append(None)
            audio_durations.append(0.0)
            audio_pauses.append([])

    # Concatenate master audio track
    valid_audio_paths = [p for p in audio_paths if p]
    master_audio = None
    if valid_audio_paths:
        master_audio = tts.concatenate_audio_files(valid_audio_paths, str(Path(output_video_dir) / "master_navigation_audio.wav"))

    csv_path = config.get("source_files", {}).get("gps_route")
    if not csv_path:
        raise ValueError("GPS route source file not specified in configuration.")

    # Load file safely using our new native parser
    cleaned_route = load_route_data(csv_path)

    # 1. Generate the video files
    video_paths = generate_navigation_video(
        cleaned_route=cleaned_route,
        project_config_path=project_config_path,
        output_video_dir=output_video_dir,
        audio_durations=audio_durations,
        audio_pauses=audio_pauses
    )

    # 2. Prepare tracking lists for TTS assembly
    segment_has_narration = []
    segment_narration_audio = []
    segment_durations = []

    has_summary = len(video_paths) > 0 and "03_summary" in video_paths[-1]

    DEFAULT_OVERVIEW_DURATION = 8.0
    DEFAULT_PAUSE_SECONDS = 2.0
    DEFAULT_SUMMARY_HOLD = 4.0

    for i, vid_path in enumerate(video_paths):
        is_waypoint_leg = (i > 0) if not has_summary else (0 < i < len(video_paths) - 1)
        audio_idx = i - 1

        if is_waypoint_leg and audio_idx < len(audio_paths) and audio_paths[audio_idx]:
            segment_has_narration.append(True)
            segment_narration_audio.append(audio_paths[audio_idx])
            segment_durations.append(audio_durations[audio_idx])
        else:
            segment_has_narration.append(False)
            segment_narration_audio.append(None)
            if i == 0:
                segment_durations.append(DEFAULT_OVERVIEW_DURATION + DEFAULT_PAUSE_SECONDS)
            elif has_summary and i == len(video_paths) - 1:
                segment_durations.append(DEFAULT_SUMMARY_HOLD)
            else:
                segment_durations.append(audio_durations[audio_idx] if audio_idx < len(audio_durations) else 0.0)

    # 3. Assemble final deliverable via TTSService
    print("🎬 Assembling final combined video + audio...")
    assembly = tts.assemble_final_deliverable(
        video_segment_paths=video_paths,
        segment_has_narration=segment_has_narration,
        segment_durations=segment_durations,
        segment_narration_audio=segment_narration_audio,
        output_dir=output_video_dir,
    )

    return {
        "video_paths": video_paths,
        "master_audio_path": master_audio,
        "final_video_path": assembly["full_video_path"],
        "full_master_audio_path": assembly["full_audio_path"],
        "final_combined_path": assembly["final_combined_path"],
        "summary": config.get("summary", {})
    }


def handle_incoming_gps_upload(raw_source_path: str, output_format: str = "csv") -> str:
    """Handles raw GPS file upload, converts it via GPSParser, and initializes output config."""
    print(f"📁 Processing file: {raw_source_path}")
    
    out_name = Path(raw_source_path).stem
    
    success = GPSParser.convert_gps_file(
        input_file=raw_source_path, 
        output_file_name=out_name, 
        output_format=output_format
    )
    
    if success:
        print(f"✅ Pipeline completed successfully!")
        return json.dumps({"status": "success", "file": raw_source_path}, ensure_ascii=False)
    else:
        raise ValueError("Failed to process GPS file via GPSBabel.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1]
        payload = sys.argv[2] if len(sys.argv) > 2 else ""
        
        # Removed the blanket try/except here so you can see real tracebacks if it crashes!
        if command == "process_gps":
            print(handle_incoming_gps_upload(payload))
            
        elif command == "init_project":
            project_name = sys.argv[3] if len(sys.argv) > 3 else "Untitled Project"
            project_dir = FileHandler.get_project_directory(project_name)
            print(json.dumps({"project_dir": str(project_dir)}, ensure_ascii=False))
            
        elif command == "generate_speech":
            output_path = sys.argv[3] if len(sys.argv) > 3 else "outputs/output.mp3"
            tts = TTSService()
            saved_path = asyncio.run(tts.get_irodori_speech(payload))
            print(json.dumps({"audio_path": saved_path}, ensure_ascii=False))

        elif command == "synced_tts_pipeline":
            output_arg = sys.argv[3] if len(sys.argv) > 3 else "data/outputs/video"
            result = asyncio.run(run_synced_tts_pipeline(project_config_path=payload, output_video_dir=output_arg))
            print(json.dumps(result, ensure_ascii=False))
            
        else:
            print(f"Error: Unknown command '{command}'", file=sys.stderr)
            sys.exit(1)