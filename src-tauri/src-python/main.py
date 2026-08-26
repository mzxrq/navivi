"""
main.py (Clean Architecture)
---------------------------------------------------------------------------
Lightweight CLI Entry point for the GPS-to-navigation-video pipeline.
Imports all core orchestration logic from the dedicated services modules.
---------------------------------------------------------------------------
"""

import sys
import json
import asyncio
import traceback

# Import from the newly extracted pipeline files
from services.data_upload_pipeline import (
    handle_incoming_gps_upload,
    generate_attraction_videos,
)
from services.video_pipeline import run_full_pipeline
from services.tts_pipeline import run_synced_tts_pipeline

from services.file_handler import (
    initialize_new_project,
    save_project_asset_image,
    generate_and_save_audio,
)
from services.job_config import JobConfigManager
from services.llmscript import (
    analyze_travel_image,
    generate_voiceover_script,
    generate_overview_script,
)

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
                print(
                    json.dumps(
                        {
                            "success": True,
                            "video_paths": result["video_paths"],
                            "summary": result["summary"],
                        },
                        ensure_ascii=False,
                    )
                )

            elif command == "init_project":
                project_name = sys.argv[3] if len(sys.argv) > 3 else "Untitled Project"
                config_path = initialize_new_project(
                    user_id=payload, project_name=project_name
                )
                print(
                    json.dumps(
                        {"success": True, "config_path": config_path},
                        ensure_ascii=False,
                    )
                )

            elif command == "save_asset":
                source_image_path = sys.argv[3] if len(sys.argv) > 3 else ""
                asset_path = save_project_asset_image(
                    project_dir=payload, source_image_path=source_image_path
                )
                print(
                    json.dumps(
                        {"success": True, "asset_path": asset_path}, ensure_ascii=False
                    )
                )

            elif command == "generate_speech":
                output_path = sys.argv[3] if len(sys.argv) > 3 else "output.mp3"
                saved_path = generate_and_save_audio(
                    text=payload, output_path=output_path
                )
                print(
                    json.dumps(
                        {"success": True, "audio_path": saved_path}, ensure_ascii=False
                    )
                )

            elif command == "synced_tts_pipeline":
                output_arg = sys.argv[3] if len(sys.argv) > 3 else None
                result = asyncio.run(
                    run_synced_tts_pipeline(
                        project_config_path=payload, output_video_dir=output_arg
                    )
                )
                print(json.dumps({"success": True, **result}, ensure_ascii=False))

            elif command == "save_config":
                config = JobConfigManager(payload)
                config.save()
                print(json.dumps({"success": True}, ensure_ascii=False))

            elif command == "analyze_image":
                analysis_result = analyze_travel_image(payload)
                print(
                    json.dumps(
                        {"success": True, "data": analysis_result}, ensure_ascii=False
                    )
                )

            elif command == "generate_attraction_videos":
                video_outputs = asyncio.run(generate_attraction_videos(payload))
                print(
                    json.dumps(
                        {"success": True, "video_outputs": video_outputs},
                        ensure_ascii=False,
                    )
                )

            elif command == "generate_script":
                data = json.loads(payload)
                script = generate_voiceover_script(
                    prompt=data.get("prompt", ""),
                    location_name=data.get("locationName", ""),
                    lat=data.get("lat", 0.0),
                    lng=data.get("lng", 0.0),
                    engine=data.get("engine", "ollama"),
                )
                print(
                    json.dumps({"success": True, "script": script}, ensure_ascii=False)
                )

            elif command == "generate_overview":
                data = json.loads(payload)
                script = generate_overview_script(
                    waypoints=data.get("waypoints", []),
                    engine=data.get("engine", "ollama"),
                )
                print(
                    json.dumps({"success": True, "script": script}, ensure_ascii=False)
                )

            else:
                print(
                    json.dumps(
                        {"success": False, "error": f"Unknown command '{command}'"},
                        ensure_ascii=False,
                    )
                )
                sys.exit(1)

        except Exception as e:
            error_res = {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__,
                "traceback": traceback.format_exc(),
            }
            print(json.dumps(error_res, ensure_ascii=False))
            sys.exit(1)
