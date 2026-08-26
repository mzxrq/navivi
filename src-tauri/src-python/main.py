"""
main.py (Clean Architecture — Command Registry Edition)
---------------------------------------------------------------------------
Lightweight CLI Entry point for the GPS-to-navigation-video pipeline.
Each pipeline operation is an isolated, independently-editable handler
function registered in COMMAND_REGISTRY. To add or modify a step, touch
only that step's function — nothing else in this file needs to change.
---------------------------------------------------------------------------
"""

import sys
import json
import asyncio
import traceback
from pathlib import Path
from typing import Callable, Dict, Any, List

from services.data_upload_pipeline import (
    handle_incoming_gps_upload,
    generate_attraction_videos,
)
from services.video_pipeline import (
    run_full_pipeline,
    render_from_timeline,
    process_gps as vp_process_gps,
    render_route_video,
    render_attraction_videos as vp_render_attraction_videos,
    burn_subtitles as vp_burn_subtitles,
)

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

# =============================================================================
# [Core] PER-OPERATION HANDLERS
# -----------------------------------------------------------------------------
# Contract: every handler takes the raw `argv` list (sys.argv) and returns a
# JSON-serializable dict. The __main__ block below is responsible ONLY for
# dispatch + printing + the top-level error envelope — it has zero knowledge
# of any individual step's internals. This isolates blast radius: editing
# "render_route_video" behavior can never accidentally break dispatch logic
# or any unrelated command.
# =============================================================================


def _cmd_process_gps(argv: List[str]) -> Dict[str, Any]:
    """Full raw-file ingestion: store raw GPS upload, convert, clean, export JSON."""
    payload = argv[2] if len(argv) > 2 else ""
    return {"success": True, "data": handle_incoming_gps_upload(payload)}


def _cmd_full_pipeline(argv: List[str]) -> Dict[str, Any]:
    """Runs the entire GPS -> video pipeline end to end in one call."""
    payload = argv[2] if len(argv) > 2 else ""
    output_arg = argv[3] if len(argv) > 3 else None
    result = run_full_pipeline(payload, output_video_dir=output_arg)
    return {
        "success": True,
        "video_paths": result["video_paths"],
        "summary": result["summary"],
    }


def _cmd_init_project(argv: List[str]) -> Dict[str, Any]:
    """Creates a new project folder structure and initial job_config.json."""
    payload = argv[2] if len(argv) > 2 else ""
    project_name = argv[3] if len(argv) > 3 else "Untitled Project"
    config_path = initialize_new_project(user_id=payload, project_name=project_name)
    return {"success": True, "config_path": config_path}


def _cmd_save_asset(argv: List[str]) -> Dict[str, Any]:
    """Copies an uploaded image into the project's assets directory."""
    payload = argv[2] if len(argv) > 2 else ""
    source_image_path = argv[3] if len(argv) > 3 else ""
    asset_path = save_project_asset_image(
        project_dir=payload, source_image_path=source_image_path
    )
    return {"success": True, "asset_path": asset_path}


def _cmd_generate_speech(argv: List[str]) -> Dict[str, Any]:
    """Generates a single TTS audio file from raw text."""
    payload = argv[2] if len(argv) > 2 else ""
    output_path = argv[3] if len(argv) > 3 else "output.mp3"
    saved_path = generate_and_save_audio(text=payload, output_path=output_path)
    return {"success": True, "audio_path": saved_path}


def _cmd_synced_tts_pipeline(argv: List[str]) -> Dict[str, Any]:
    """Runs the full audio-synced TTS + video generation pipeline."""
    payload = argv[2] if len(argv) > 2 else ""
    output_arg = argv[3] if len(argv) > 3 else None
    result = asyncio.run(
        run_synced_tts_pipeline(
            project_config_path=payload, output_video_dir=output_arg
        )
    )
    return {"success": True, **result}


def _cmd_save_config(argv: List[str]) -> Dict[str, Any]:
    """Persists the current JobConfigManager singleton state to disk."""
    payload = argv[2] if len(argv) > 2 else ""
    config = JobConfigManager(payload)
    config.save()
    return {"success": True}


def _cmd_analyze_image(argv: List[str]) -> Dict[str, Any]:
    """Runs the Ollama vision model over a map/attraction image."""
    payload = argv[2] if len(argv) > 2 else ""
    return {"success": True, "data": analyze_travel_image(payload)}


def _cmd_generate_attraction_videos(argv: List[str]) -> Dict[str, Any]:
    """Generates ComfyUI attraction clips via the data_upload_pipeline path."""
    payload = argv[2] if len(argv) > 2 else ""
    video_outputs = asyncio.run(generate_attraction_videos(payload))
    return {"success": True, "video_outputs": video_outputs}


def _cmd_generate_script(argv: List[str]) -> Dict[str, Any]:
    """Generates a single-waypoint voiceover script via the configured LLM engine."""
    payload = argv[2] if len(argv) > 2 else ""
    data = json.loads(payload)
    script = generate_voiceover_script(
        prompt=data.get("prompt", ""),
        location_name=data.get("locationName", ""),
        lat=data.get("lat", 0.0),
        lng=data.get("lng", 0.0),
        engine=data.get("engine", "ollama"),
    )
    return {"success": True, "script": script}


def _cmd_generate_overview(argv: List[str]) -> Dict[str, Any]:
    """Generates the opening/overview narration script for the whole route."""
    payload = argv[2] if len(argv) > 2 else ""
    data = json.loads(payload)
    script = generate_overview_script(
        waypoints=data.get("waypoints", []), engine=data.get("engine", "ollama")
    )
    return {"success": True, "script": script}


def _cmd_render_timeline(argv: List[str]) -> Dict[str, Any]:
    """Fast NLE re-render: rebuilds a final video from an existing timeline.json."""
    payload = argv[2] if len(argv) > 2 else ""
    output_arg = argv[3] if len(argv) > 3 else None
    rendered_path = render_from_timeline(payload, output_video_path=output_arg)
    return {"success": True, "final_video_path": rendered_path}


# -----------------------------------------------------------------------------
# [NEW] Granular per-stage commands.
# These expose each stage of run_full_pipeline() individually, so you can
# re-run or debug ONE step (e.g. re-render the map video after tuning
# line_color) without re-parsing GPS or re-generating attraction clips every
# single time. Edit one function here to change one stage's behavior.
# -----------------------------------------------------------------------------


def _cmd_process_gps_config(argv: List[str]) -> Dict[str, Any]:
    """Stage 1 only: parse+clean GPS data referenced inside a job_config.json."""
    payload = argv[2] if len(argv) > 2 else ""
    cleaned = vp_process_gps(payload)
    return {
        "success": True,
        "summary": cleaned.get("summary", {}),
        "route_rows": len(cleaned.get("route", [])),
    }


def _cmd_render_route_video(argv: List[str]) -> Dict[str, Any]:
    """Stage 3 only: render the map/route animation from a job_config.json."""
    config_payload = argv[2] if len(argv) > 2 else ""
    output_arg = argv[3] if len(argv) > 3 else None

    cleaned_route = vp_process_gps(config_payload)
    output_dir = output_arg or str(Path(config_payload).parent / "video")

    video_paths = render_route_video(
        cleaned_route=cleaned_route,
        project_config_path=config_payload,
        output_video_dir=output_dir,
    )
    return {"success": True, "video_paths": video_paths}


def _cmd_render_attraction_videos_full(argv: List[str]) -> Dict[str, Any]:
    """Stage 4 only: ComfyUI attraction clips via video_pipeline's variant."""
    payload = argv[2] if len(argv) > 2 else ""
    video_paths = vp_render_attraction_videos(project_config_path=payload)
    return {"success": True, "video_paths": video_paths}


def _cmd_burn_subtitles(argv: List[str]) -> Dict[str, Any]:
    """Stage 5 only: burn pre-existing .srt files onto already-rendered videos.

    Expects payload JSON shape:
        {
          "video_paths": [...],
          "subtitle_paths": [...],
          "output_dir": "..."
        }
    """
    payload = argv[2] if len(argv) > 2 else ""
    data = json.loads(payload)
    final_videos = vp_burn_subtitles(
        video_paths=data.get("video_paths", []),
        subtitle_paths=data.get("subtitle_paths", []),
        output_dir=data.get("output_dir", "."),
    )
    return {"success": True, "video_paths": final_videos}


# =============================================================================
# [Core] DISPATCH TABLE
# -----------------------------------------------------------------------------
# O(1) average-case command lookup versus an O(k) if/elif ladder, and —
# more importantly for maintenance — a single, obvious place to register a
# new operation. To add a new pipeline step:
#   1. Write one `_cmd_...` handler function above.
#   2. Add one line to this dict.
# No other code in this file needs to change.
# =============================================================================
COMMAND_REGISTRY: Dict[str, Callable[[List[str]], Dict[str, Any]]] = {
    "process_gps": _cmd_process_gps,
    "full_pipeline": _cmd_full_pipeline,
    "init_project": _cmd_init_project,
    "save_asset": _cmd_save_asset,
    "generate_speech": _cmd_generate_speech,
    "synced_tts_pipeline": _cmd_synced_tts_pipeline,
    "save_config": _cmd_save_config,
    "analyze_image": _cmd_analyze_image,
    "generate_attraction_videos": _cmd_generate_attraction_videos,
    "generate_script": _cmd_generate_script,
    "generate_overview": _cmd_generate_overview,
    "render_timeline": _cmd_render_timeline,
    # Granular, single-responsibility pipeline-stage commands:
    "process_gps_config": _cmd_process_gps_config,
    "render_route_video": _cmd_render_route_video,
    "render_attraction_videos_full": _cmd_render_attraction_videos_full,
    "burn_subtitles": _cmd_burn_subtitles,
}


if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1]
        handler = COMMAND_REGISTRY.get(command)

        if handler is None:
            print(
                json.dumps(
                    {"success": False, "error": f"Unknown command '{command}'"},
                    ensure_ascii=False,
                )
            )
            sys.exit(1)

        try:
            result = handler(sys.argv)
            print(json.dumps(result, ensure_ascii=False))

        except Exception as e:
            error_res = {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__,
                "traceback": traceback.format_exc(),
            }
            print(json.dumps(error_res, ensure_ascii=False))
            sys.exit(1)
