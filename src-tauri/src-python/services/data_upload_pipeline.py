import sys
import json
from pathlib import Path
from typing import Optional

from services.gps_parser import (
    convert_gps_file,
    clean_gps_data,
    export_to_frontend_json,
)
from services.file_handler import store_raw_file_with_datetime, generate_and_save_audio
from services.job_config import JobConfigManager
from services.tts import IrodoriTTSClient, AudioProcessor
from services.img2vdo import AttractionVideoGenerator


async def generate_attraction_videos(project_config_path: str) -> list[Optional[str]]:
    job_config = JobConfigManager(project_config_path)
    project_dir = Path(
        job_config.get("directory_path", Path(project_config_path).parent)
    )
    audio_output_dir = project_dir / "audio"
    audio_output_dir.mkdir(parents=True, exist_ok=True)

    tts_client = IrodoriTTSClient(output_dir=audio_output_dir)
    audio_processor = AudioProcessor(output_dir=audio_output_dir)
    video_generator = AttractionVideoGenerator(job_config=job_config)

    waypoints = job_config.get_waypoints()
    audio_paths, audio_durations = [], []

    print(
        "Step 1: Generating Irodori-TTS narration audio for attractions...",
        file=sys.stderr,
    )
    for i, wp in enumerate(waypoints):
        text = wp.get("video_narration") or wp.get("narration") or ""
        if text:
            audio_path = await tts_client.generate_speech(text)
            audio_paths.append(audio_path)
            analysis = audio_processor.analyze_pauses(audio_path)
            audio_durations.append(analysis["duration_seconds"])
            print(
                f"   -> Waypoint {i}: Audio generated ({analysis['duration_seconds']}s)",
                file=sys.stderr,
            )
        else:
            audio_paths.append(None)
            audio_durations.append(0.0)
            print(f"   -> Waypoint {i}: No narration text provided.", file=sys.stderr)

    print("\n Step 2: Generating AI Video Clips from Images...", file=sys.stderr)
    waypoint_video_outputs = []
    for i, wp in enumerate(waypoints):
        popup_image = wp.get("popup_image")
        prompt = (
            wp.get("video_narration") or wp.get("narration") or "Cinematic slow pan"
        )
        audio_path = audio_paths[i]
        target_dur = (
            audio_durations[i]
            if audio_durations[i] > 0
            else float(wp.get("freeze_seconds", 3.0))
        )

        if popup_image:
            out_filename = f"attraction_wp_{i:02d}.mp4"
            print(f"\n--- Processing Waypoint {i} ---", file=sys.stderr)
            video_result = video_generator.process_attraction_video(
                popup_image_entry=popup_image,
                prompt_text=prompt,
                target_audio_duration=target_dur,
                audio_path=audio_path,
                output_filename=out_filename,
            )
            waypoint_video_outputs.append(video_result)
        else:
            print(f"Skipping Waypoint {i}: No popup image found.", file=sys.stderr)
            waypoint_video_outputs.append(None)

    return waypoint_video_outputs


def data_pipeline_process(input_file: str, output_format: str = "iblue747") -> str:
    print(f"Processing file: {input_file}")
    route = convert_gps_file(
        input_file=input_file,
        output_filename=input_file.replace(".TXT", ".csv"),
        output_format=output_format,
    )
    cleaned_route = clean_gps_data(route)
    json_route = export_to_frontend_json(
        cleaned_route, original_input_path=input_file, project_name="Untitled Project"
    )
    print("Pipeline completed successfully!")
    return json.dumps(json_route, ensure_ascii=False)


def generate_audio_tts(text: str, output_path: str = "output.mp3") -> Optional[str]:
    return generate_and_save_audio(text, output_path)


def store_raw_file(input_file: str) -> Optional[str]:
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
