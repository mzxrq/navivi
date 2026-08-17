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
import pyproj

from services.gpsparser import convert_gps_file, clean_gps_data, export_to_frontend_json
from services.filehandler import initialize_new_project, save_project_asset_image, store_raw_file_with_datetime, generate_and_save_audio
from services.mapfetcher import MapFetcher
from services.route2vdo import render_route_animation
from services.tts import (
    get_irodori_speech, analyze_wav_pauses, concatenate_audio_files,
    assemble_final_deliverable, get_audio_format, resolve_ffmpeg_bin as _resolve_ffmpeg_binary,
)


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
    audio_durations: list = None,
    audio_pauses: list = None
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

    # Calculate physical travel times based on distance — used ONLY as a
    # fallback pacing for legs that have NO narration audio at all (a
    # waypoint with empty narration text). This heuristic must never be
    # allowed to override real audio timing (see bug note below).
    seg_durations = MapFetcher.compute_segment_durations(waypoints, wp_indices, route_df, target_avg_seconds=20.0) if waypoints and len(wp_indices) > 1 else []

    res_sequence = []
    for seq_idx, item in enumerate(sequence_data):
        start_idx = item["start_idx"]
        end_idx = item["end_idx"]
        chunk = route_df.iloc[start_idx : end_idx + 1]
        chunk_points = _project_route_to_pixels(chunk["latitude"].to_numpy(), chunk["longitude"].to_numpy(), item["extent"], img_w, img_h)

        distance_fallback = seg_durations[seq_idx] if seq_idx < len(seg_durations) else 10.0
        has_audio = bool(audio_durations) and seq_idx < len(audio_durations) and audio_durations[seq_idx] > 0
        active_pauses = audio_pauses[seq_idx] if audio_pauses and seq_idx < len(audio_pauses) else []

        # -------------------------------------------------------------
        # AUDIO-FIRST DURATION MODEL (fixes "route line finishes before
        # the video/audio ends"):
        #
        # The OLD logic set travel_duration = physical_travel (a fixed
        # "~10s average" distance heuristic) and segment_duration =
        # max(physical_travel, audio_time). Whenever narration ran LONGER
        # than that heuristic (very common — text length has nothing to
        # do with route distance), the marker finished drawing the line
        # at physical_travel seconds, then the clip just sat frozen for
        # the remaining, often-long, silent tail while narration kept
        # playing. Visually: "the line is over before the route/video
        # ends."
        #
        # NEW rule: when real narration exists for this leg, audio is the
        # single source of truth for BOTH the total clip length AND the
        # pacing of the line-drawing animation. travel_duration is set to
        # the same audio-derived duration (not the distance heuristic),
        # so the marker consumes the ENTIRE clip and reaches the end of
        # the line at (or a few frames before, via a short intentional
        # freeze-frame tail) the moment the narration finishes. The
        # distance heuristic is used ONLY when a leg genuinely has no
        # narration audio, where there is nothing else to sync against.
        # -------------------------------------------------------------
        if has_audio:
            audio_time = audio_durations[seq_idx]
            travel_duration = distance_fallback 
            total_time = max(distance_fallback, audio_time)
        else:
            total_time = distance_fallback
            travel_duration = distance_fallback

        res_sequence.append({
            "img_path": item["img_path"],
            "extent": item["extent"],
            "lats": item["lats"],
            "lons": item["lons"],
            "points": chunk_points,
            "labels": route_labels[start_idx : end_idx + 1],
            "popups": route_popups[start_idx : end_idx + 1],
            "travel_duration": travel_duration,   # Normal physical speed
            "segment_duration": total_time,       # Stretches if audio is longer
            "pauses": active_pauses
        })
    
    return render_route_animation(
        img_path=map_output_path, points=route_points, labels=route_labels,
        popups=route_popups, output_dir=output_video_dir, summary=summary,
        res_sequence=res_sequence,
    )


async def run_synced_tts_pipeline(project_config_path: str, output_video_dir: str = "data\\outputs\\video") -> dict:
    """
    Orchestrates upstream TTS synthesis, exact audio duration and pause analysis,
    full navigation video rendering, and — new — final assembly into ONE combined
    video+audio deliverable:

      1. Render per-phase video segments + synthesize narration audio (as before).
      2. Combine ALL video segments -> one full video file.
         Combine ALL audio (narration + timed silence for silent phases) -> one
         full, timeline-accurate audio file.
      3. Combine the full video + full audio -> one final playable clip.
    """
    config_path = Path(project_config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Project config not found: {project_config_path}")

    with open(config_path, 'r', encoding='utf-8') as f:
        project_config = json.load(f)

    waypoints = project_config.get("waypoints", [])
    audio_paths = []
    audio_durations = []
    audio_pauses = []

    print("🎙️ Generating Irodori-TTS narration audio for waypoints...")
    for wp in waypoints:
        text = wp.get("narration", "").strip()
        if text:
            path = await get_irodori_speech(text)
            audio_paths.append(path)
            analysis = analyze_wav_pauses(path)
            audio_durations.append(analysis['duration_seconds'])
            audio_pauses.append(analysis['pauses'])
            print(f"   -> Generated {path} (Duration: {analysis['duration_seconds']}s, Pauses: {len(analysis['pauses'])})")
        else:
            audio_paths.append(None)
            audio_durations.append(0.0)
            audio_pauses.append([])

    valid_audio_paths = [p for p in audio_paths if p]
    master_audio = None
    if valid_audio_paths:
        master_audio = concatenate_audio_files(valid_audio_paths, "outputs/master_navigation_audio.wav")

    csv_path = project_config.get("source_files", {}).get("gps_route")
    if not csv_path:
        raise ValueError("GPS route source file not specified in configuration.")

    cleaned_route = clean_gps_data(csv_path)

    # 1. Generate the video files with the exact audio timings
    video_paths = generate_navigation_video(
        cleaned_route=cleaned_route,
        project_config_path=project_config_path,
        output_video_dir=output_video_dir,
        audio_durations=audio_durations,
        audio_pauses=audio_pauses
    )

    # 2. Mux (merge) the audio files into the waypoint video segments, and
    #    track, in the SAME order as video_paths, which phase had narration
    #    and its intended duration — needed later to build a timeline-accurate
    #    master audio track that stays aligned with the concatenated video.
    final_video_paths = []
    segment_has_narration = []
    segment_narration_audio = []
    segment_durations = []

    has_summary = len(video_paths) > 0 and "summary" in video_paths[-1]

    # Overview phase duration = the draw time + the hold/pause tacked onto
    # the same file by render_route_animation (see route2vdo docstring:
    # "Phase 2 (pause) rides in the SAME file as Phase 1"). These mirror
    # the defaults render_route_animation/generate_navigation_video use
    # since generate_navigation_video doesn't currently forward custom
    # duration/pause/summary settings through to render_route_animation.
    DEFAULT_OVERVIEW_DURATION = 8.0
    DEFAULT_PAUSE_SECONDS = 2.0
    DEFAULT_SUMMARY_HOLD = 4.0

    for i, vid_path in enumerate(video_paths):
        # The first video is the Overview (no audio), the last is Summary (no audio)
        # Waypoint legs align with audio_paths
        is_waypoint_leg = (i > 0) if not has_summary else (0 < i < len(video_paths) - 1)
        audio_idx = i - 1

        if is_waypoint_leg and audio_idx < len(audio_paths) and audio_paths[audio_idx]:
            print(f"🎵 Merging audio into segment {i}...")
            muxed_path = vid_path.replace(".mp4", "_with_audio.mp4")

            # Pin -ar/-ac EXPLICITLY to the source narration's real format
            # rather than letting the AAC encoder infer them. This closes
            # the last remaining "chipmunk" risk: without an explicit -ar,
            # some encoder/container combinations can end up with a
            # sample-rate mismatch between the encoded stream and what the
            # container header declares, which plays back sped-up/
            # pitch-shifted. Forcing it removes the ambiguity entirely.
            src_rate, src_channels = get_audio_format(audio_paths[audio_idx])
            cmd = [
                _resolve_ffmpeg_binary(), "-y", "-i", vid_path, "-i", audio_paths[audio_idx],
                "-c:v", "copy", "-c:a", "aac", "-ar", str(src_rate), "-ac", str(src_channels),
                "-map", "0:v:0", "-map", "1:a:0",
                "-shortest", muxed_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                # Fail loudly instead of DEVNULL-swallowing the error — a
                # silently broken per-leg mux would otherwise only surface
                # once someone opens the final concatenated file.
                raise RuntimeError(f"Failed to mux audio into segment {i} ({vid_path}): {result.stderr.strip()}")

            final_video_paths.append(muxed_path)
            segment_has_narration.append(True)
            segment_narration_audio.append(audio_paths[audio_idx])
            # Real segment duration was already computed to match audio in
            # generate_navigation_video (max(physical_travel, audio_time)) —
            # audio_durations is the tightest, most accurate figure we have
            # for how long this leg's narration actually runs.
            segment_durations.append(audio_durations[audio_idx])

            # Clean up the original silent video file
            if os.path.exists(vid_path):
                os.remove(vid_path)
        else:
            final_video_paths.append(vid_path)
            segment_has_narration.append(False)
            segment_narration_audio.append(None)
            if i == 0:
                segment_durations.append(DEFAULT_OVERVIEW_DURATION + DEFAULT_PAUSE_SECONDS)
            elif has_summary and i == len(video_paths) - 1:
                segment_durations.append(DEFAULT_SUMMARY_HOLD)
            else:
                # Silent waypoint leg with no narration text provided.
                segment_durations.append(audio_durations[audio_idx] if audio_idx < len(audio_durations) else 0.0)

    # 3. Final assembly: concat all video -> one file, concat all audio
    #    (narration + timed silence) -> one file, then mux the two together
    #    into the single combined deliverable.
    print("🎬 Assembling final combined video + audio...")
    assembly = assemble_final_deliverable(
        video_segment_paths=final_video_paths,
        segment_has_narration=segment_has_narration,
        segment_durations=segment_durations,
        segment_narration_audio=segment_narration_audio,
        output_dir="outputs",
    )

    return {
        "video_paths": final_video_paths,                       # per-segment files (kept for legacy consumers)
        "master_audio_path": master_audio,                      # narration-only concat (kept, unchanged behavior)
        "final_video_path": assembly["full_video_path"],        # NEW: single concatenated video (own inline audio)
        "full_master_audio_path": assembly["full_audio_path"],  # NEW: single timeline-accurate audio (narration + silence)
        "final_combined_path": assembly["final_combined_path"], # NEW: single final video, driven by the full master audio
        "summary": cleaned_route.get("summary", {})
    }


def run_full_pipeline(raw_source_path: str, output_video_dir: str = "data\\outputs\\video") -> dict:
    csv_path = convert_gps_file(input_file=raw_source_path, output_filename=Path(raw_source_path).with_suffix(".csv").name, output_format="iblue747")
    cleaned_route = clean_gps_data(csv_path)
    base_dir = Path(__file__).resolve().parent
    config_path = base_dir / "data" / "inputs" / "gpsdata" / "processdata" / "json" / "example_frontend.json"

    video_paths = generate_navigation_video(cleaned_route=cleaned_route, project_config_path=str(config_path), output_video_dir=output_video_dir)
    return {"video_paths": video_paths, "summary": cleaned_route.get("summary", {})}


if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1]
        payload = sys.argv[2] if len(sys.argv) > 2 else ""
        try:
            if command == "process_gps":
                print(handle_incoming_gps_upload(payload))
                
            elif command == "full_pipeline":
                output_arg = sys.argv[3] if len(sys.argv) > 3 else "data\\outputs\\video"
                result = run_full_pipeline(payload, output_video_dir=output_arg)
                print(json.dumps({"video_paths": result["video_paths"], "summary": result["summary"]}, ensure_ascii=False))
                
            elif command == "init_project":
                project_name = sys.argv[3] if len(sys.argv) > 3 else "Untitled Project"
                config_path = initialize_new_project(user_id=payload, project_name=project_name)
                print(json.dumps({"config_path": config_path}, ensure_ascii=False))
                
            elif command == "save_asset":
                source_image_path = sys.argv[3] if len(sys.argv) > 3 else ""
                asset_path = save_project_asset_image(project_dir=payload, source_image_path=source_image_path)
                print(json.dumps({"asset_path": asset_path}, ensure_ascii=False))
                
            elif command == "generate_speech":
                output_path = sys.argv[3] if len(sys.argv) > 3 else "output.mp3"
                saved_path = generate_and_save_audio(text=payload, output_path=output_path)
                print(json.dumps({"audio_path": saved_path}, ensure_ascii=False))

            elif command == "synced_tts_pipeline":
                output_arg = sys.argv[3] if len(sys.argv) > 3 else "data\\outputs\\video"
                result = asyncio.run(run_synced_tts_pipeline(project_config_path=payload, output_video_dir=output_arg))
                print(json.dumps(result, ensure_ascii=False))
                
            else:
                print(f"Error: Unknown command '{command}'", file=sys.stderr)
                sys.exit(1)
                
        except Exception as e:
            print(f"Error: {str(e)}", file=sys.stderr)
            sys.exit(1)