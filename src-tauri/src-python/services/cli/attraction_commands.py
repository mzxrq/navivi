"""Isolated CLI commands for pipeline Step 3 (attraction/pan-zoom video
generation from waypoint popup images) — thin wrappers over
services/vdoprocessing/videopipeline/attraction_step.py, the attraction
domain's core module."""

import json
from pathlib import Path
from typing import Any, Dict

from services.logger.progress import tracker as _tracker
from services.vdoprocessing.videopipeline.attraction_step import (
    generate_waypoint_attraction_video,
)
from services.vdoprocessing.videopipeline.helpers import (
    attraction_output_filename,
    output_is_valid,
    project_attraction_video_dir,
    project_audio_dir,
    waypoint_audio_filename,
)
from .helpers import _load_tts_waypoints


def _resolve_attraction_audio(
    config_path: Path, waypoint_index: int, label: Any
) -> Dict[str, Any]:
    """Looks up the waypoint's already-generated TTS audio (by the shared
    naming convention) and its duration, for the CLI's single-waypoint
    attraction test where a full audio_durations/audio_paths list from the
    TTS step isn't available."""
    audio_path = project_audio_dir(config_path.parent) / waypoint_audio_filename(waypoint_index, label)
    if not output_is_valid(audio_path):
        return {"audio_path": None, "duration_seconds": 0.0}

    from services.tts.ttsengine import AudioProcessor

    analysis = AudioProcessor().analyze_pauses(str(audio_path))
    return {"audio_path": str(audio_path), "duration_seconds": analysis["duration_seconds"]}


def test_attraction_video(
    job_config_path: str,
    output_video_dir: str = None,
    waypoint_index: int = 0,
    force: bool = False,
) -> Dict[str, Any]:
    """Generate one attraction video from one waypoint's popup image."""
    config_path, waypoints = _load_tts_waypoints(job_config_path)
    if waypoint_index < 0 or waypoint_index >= len(waypoints):
        raise IndexError(
            f"waypoint_index must be between 0 and {len(waypoints) - 1}, "
            f"got {waypoint_index}"
        )

    waypoint = waypoints[waypoint_index]
    if not isinstance(waypoint, dict):
        raise ValueError(f"Waypoint {waypoint_index} must be an object")
    if not waypoint.get("popup_image"):
        raise ValueError(f"Waypoint {waypoint_index} has no popup_image")

    from services.config.job_config import JobConfigManager
    from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient
    from services.vdoprocessing.img2vdo import AttractionVideoGenerator

    output_dir = Path(output_video_dir) if output_video_dir else project_attraction_video_dir(config_path.parent)
    output_dir.mkdir(parents=True, exist_ok=True)
    label = waypoint.get("label", f"Waypoint {waypoint_index + 1}")
    audio_info = _resolve_attraction_audio(config_path, waypoint_index, label)

    # See attraction_step.render_attraction_videos's identical call for why:
    # a killed/restarted invocation otherwise leaves its job running
    # server-side, queuing every retry further behind instead of starting fresh.
    ComfyUII2VClient().clear_queue()

    generator = AttractionVideoGenerator(JobConfigManager(config_path))
    generator.output_dir = output_dir

    result = generate_waypoint_attraction_video(
        waypoint, waypoint_index, generator,
        target_audio_duration=audio_info["duration_seconds"],
        audio_path=audio_info["audio_path"],
        force=force,
    )

    if result["status"] == "generated":
        return {
            "success": True,
            "pending": False,
            "video_path": result["video_path"],
            "audio_path": result["audio_path"],
        }
    if result["status"] == "pending":
        return {
            "success": True,
            "pending": True,
            "clip_paths": result["clip_paths"],
            "output_filename": result["output_filename"],
            "audio_path": result["audio_path"],
            "message": (
                "Multiple clips generated but not yet combined — call "
                "attraction-finalize once approved."
            ),
        }
    raise RuntimeError(f"Attraction video generation failed for waypoint {waypoint_index}")


def test_attraction_videos(
    job_config_path: str,
    output_video_dir: str = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Generate attraction videos for every waypoint with a popup image."""
    config_path, waypoints = _load_tts_waypoints(job_config_path)
    candidates = [
        (index, waypoint)
        for index, waypoint in enumerate(waypoints)
        if isinstance(waypoint, dict) and waypoint.get("popup_image")
    ]
    results = []
    for progress_index, (index, waypoint) in enumerate(candidates):
        label = waypoint.get("label", f"Waypoint {index + 1}")
        _tracker.show(f"Generating attraction video {progress_index + 1}/{len(candidates)}: {label}")
        result = test_attraction_video(
            str(config_path), output_video_dir, waypoint_index=index, force=force
        )
        results.append({"index": index, **result})
    _tracker.clear()
    return {
        "success": True,
        "video_paths": [
            item["video_path"] for item in results if not item.get("pending")
        ],
        "pending_indices": [
            item["index"] for item in results if item.get("pending")
        ],
        "results": results,
    }


def test_attraction_finalize(
    job_config_path: str,
    output_video_dir: str = None,
    waypoint_index: int = 0,
) -> Dict[str, Any]:
    """Combines a waypoint's pending (already-generated but not yet
    combined) attraction clips into the final deliverable. Call this once
    the frontend has reviewed the individual clips and approved combining
    them — the automatic pipeline / test_attraction_video no longer does
    this on its own for multi-image waypoints."""
    config_path, waypoints = _load_tts_waypoints(job_config_path)
    if waypoint_index < 0 or waypoint_index >= len(waypoints):
        raise IndexError(
            f"waypoint_index must be between 0 and {len(waypoints) - 1}, "
            f"got {waypoint_index}"
        )

    waypoint = waypoints[waypoint_index]
    label = waypoint.get("label", f"Waypoint {waypoint_index + 1}") if isinstance(waypoint, dict) else f"Waypoint {waypoint_index + 1}"

    from services.config.job_config import JobConfigManager
    from services.vdoprocessing.img2vdo import AttractionVideoGenerator

    output_dir = Path(output_video_dir) if output_video_dir else project_attraction_video_dir(config_path.parent)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_filename = attraction_output_filename(waypoint_index, label)

    generator = AttractionVideoGenerator(JobConfigManager(config_path))
    generator.output_dir = output_dir

    manifest_path = generator._pending_manifest_path(output_filename)
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"No pending clips found for waypoint {waypoint_index} "
            f"(expected manifest at {manifest_path}). Generate it first via "
            f"the 'attraction' mode."
        )

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    result_path = generator.finalize_pending_video(
        clip_paths=manifest.get("clip_paths", []),
        target_audio_duration=manifest.get("target_audio_duration", 0.0),
        output_filename=manifest.get("output_filename", output_filename),
    )
    if not result_path:
        raise RuntimeError(f"Finalizing attraction video failed for waypoint {waypoint_index}")
    return {"success": True, "video_path": result_path, "audio_path": manifest.get("audio_path")}
