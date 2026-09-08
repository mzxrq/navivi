"""Isolated CLI commands for pipeline Step 3 (attraction/pan-zoom video
generation from waypoint popup images)."""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from services.logger.progress import tracker as _tracker
from .helpers import _load_tts_waypoints, _video_safe_label


def _attraction_prompt(waypoint: Dict[str, Any]) -> list:
    camera_pans = waypoint.get("camera_pans", [])
    if isinstance(camera_pans, list) and camera_pans:
        return camera_pans
    return [waypoint.get("label", "Beautiful Japanese scenery, high quality")]


def _attraction_audio_path(
    config_path: Path, waypoint_index: int, label: Any
) -> Optional[str]:
    audio_path = (
        config_path.parent
        / "audio"
        / (
            f"02_waypoint_{waypoint_index + 1:02d}_"
            f"{_video_safe_label(label, f'leg{waypoint_index + 1}')}.wav"
        )
    )
    return str(audio_path) if audio_path.exists() else None


def test_attraction_video(
    job_config_path: str,
    output_video_dir: str = None,
    waypoint_index: int = 0,
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
    from services.vdoprocessing.img2vdo import AttractionVideoGenerator
    from services.tts.ttsengine import AudioProcessor

    output_dir = Path(output_video_dir or (config_path.parent / "video"))
    output_dir.mkdir(parents=True, exist_ok=True)
    label = waypoint.get("label", f"Waypoint {waypoint_index + 1}")
    audio_path = _attraction_audio_path(config_path, waypoint_index, label)
    audio_duration = (
        AudioProcessor().analyze_pauses(audio_path)["duration_seconds"]
        if audio_path
        else 0.0
    )
    generator = AttractionVideoGenerator(JobConfigManager(config_path))
    generator.output_dir = output_dir
    output_filename = (
        f"04_attraction_{waypoint_index:02d}_"
        f"{_video_safe_label(label, f'waypoint_{waypoint_index}')}.mp4"
    )
    result_path = generator.process_attraction_video(
        popup_image_entry=waypoint["popup_image"],
        prompt_text=_attraction_prompt(waypoint),
        target_audio_duration=audio_duration,
        audio_path=audio_path,
        output_filename=output_filename,
    )
    if not result_path:
        # [NOTE] [Animation] A multi-image waypoint parks raw clips in a pending manifest instead of auto-combining, so a None result isn't necessarily a failure.
        manifest_path = generator._pending_manifest_path(output_filename)
        if manifest_path.exists():
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            return {
                "success": True,
                "pending": True,
                "clip_paths": manifest.get("clip_paths", []),
                "output_filename": output_filename,
                "audio_path": audio_path,
                "message": (
                    "Multiple clips generated but not yet combined — call "
                    "attraction-finalize once approved."
                ),
            }
        raise RuntimeError(f"Attraction video generation failed for waypoint {waypoint_index}")
    return {"success": True, "pending": False, "video_path": result_path, "audio_path": audio_path}


def test_attraction_videos(
    job_config_path: str,
    output_video_dir: str = None,
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
            str(config_path), output_video_dir, waypoint_index=index
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

    output_dir = Path(output_video_dir or (config_path.parent / "video"))
    output_dir.mkdir(parents=True, exist_ok=True)
    output_filename = (
        f"04_attraction_{waypoint_index:02d}_"
        f"{_video_safe_label(label, f'waypoint_{waypoint_index}')}.mp4"
    )

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
