"""Step 3: Generate AI videos for individual attractions (ComfyUI/Wan2.2
image-to-video, falling back to local outpaint+pan on failure).

This is the attraction domain's core module — services/cli/attraction_commands.py
is a thin wrapper around generate_waypoint_attraction_video() below, rather
than reimplementing prompt resolution and filename conventions on its own."""

from pathlib import Path
from typing import Any, Dict, Optional

from services.logger.progress import tracker

from .helpers import attraction_output_filename, logger


def _resolve_attraction_prompt(waypoint: dict) -> list:
    """Passes the full camera_pans list (not just one) so the generator can
    chain multiple pans per attraction, falling back to a label-based
    prompt when none are configured."""
    camera_pans = waypoint.get("camera_pans", [])
    if isinstance(camera_pans, list) and camera_pans:
        return camera_pans
    return [waypoint.get("label", "Beautiful Japanese scenery, high quality")]


def generate_waypoint_attraction_video(
    waypoint: dict,
    idx: int,
    generator: Any,
    target_audio_duration: float = 0.0,
    audio_path: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Generates (or reuses/leaves-pending per generator's own checkpointing)
    one waypoint's attraction video. Returns a dict with a `status` of
    "generated" / "pending" / "failed" / "skipped_no_image", plus whatever
    path/clip data is relevant to that status."""
    popup_image_entry = waypoint.get("popup_image")
    label = waypoint.get("label", f"waypoint_{idx}")

    if not popup_image_entry:
        return {"status": "skipped_no_image", "label": label}

    output_filename = attraction_output_filename(idx, label)

    result_path = generator.process_attraction_video(
        popup_image_entry=popup_image_entry,
        prompt_text=_resolve_attraction_prompt(waypoint),
        target_audio_duration=target_audio_duration,
        audio_path=audio_path,
        output_filename=output_filename,
        place_label=label,
        force=force,
    )

    if result_path:
        return {
            "status": "generated",
            "label": label,
            "video_path": result_path,
            "audio_path": audio_path,
            "output_filename": output_filename,
        }

    # [NOTE] [Core] A None result here isn't necessarily a failure — a pending manifest means clips were generated but await frontend approval via attraction-finalize.
    manifest_path = generator._pending_manifest_path(output_filename)
    if manifest_path.exists():
        import json

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        return {
            "status": "pending",
            "label": label,
            "clip_paths": manifest.get("clip_paths", []),
            "audio_path": audio_path,
            "output_filename": output_filename,
        }

    return {"status": "failed", "label": label, "output_filename": output_filename}


def render_attraction_videos(
    project_config_path: str,
    audio_durations: Optional[list[float]] = None,
    audio_paths: Optional[list[str]] = None,
    force: bool = False,
) -> list[str]:
    """Step 3: Generates AI videos for individual attractions via the
    bundled ComfyUI server (Wan2.2 image-to-video), falling back to the
    local outpaint+pan generator per-clip on failure."""
    logger.info("Step 3: Generating attraction videos (ComfyUI/Wan2.2 I2V).")

    config_path = Path(project_config_path)
    if not config_path.exists():
        logger.warning("Step 3: No project config found at %s — skipping.", config_path)
        return []

    from services.config.job_config import JobConfigManager
    from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient
    from services.vdoprocessing.img2vdo import AttractionVideoGenerator

    job_config = JobConfigManager(config_path)
    generator = AttractionVideoGenerator(job_config=job_config)

    # A killed/restarted pipeline run otherwise leaves its in-flight
    # ComfyUI job running server-side — the next run's submissions just
    # queue up behind it (and behind each other, across repeated restarts)
    # instead of ever starting fresh. Clear the slate before this run's
    # first submission.
    ComfyUII2VClient().clear_queue()

    waypoints = job_config.get("waypoints", [])
    generated_videos = []
    audio_durations = audio_durations or []
    audio_paths = audio_paths or []

    for idx, wp in enumerate(waypoints):
        place_label = wp.get("label", f"waypoint_{idx}")
        tracker.show(f"Generating attraction video {idx + 1}/{len(waypoints)}: {place_label}")
        logger.info(
            "Step 3: [%d/%d] Generating attraction video for: '%s'",
            idx + 1, len(waypoints), place_label,
        )

        result = generate_waypoint_attraction_video(
            wp, idx, generator,
            target_audio_duration=audio_durations[idx] if idx < len(audio_durations) else 0.0,
            audio_path=audio_paths[idx] if idx < len(audio_paths) else None,
            force=force,
        )

        if result["status"] == "skipped_no_image":
            logger.info(
                "Step 3: [%d/%d] Skipping '%s' — no popup image configured.",
                idx + 1, len(waypoints), place_label,
            )
        elif result["status"] == "generated":
            logger.info(
                "Step 3: [%d/%d] '%s' complete -> %s",
                idx + 1, len(waypoints), place_label, result["video_path"],
            )
            generated_videos.append(result["video_path"])
        elif result["status"] == "pending":
            logger.info(
                "Step 3: [%d/%d] '%s' has multiple clips pending approval — "
                "combining deferred, call attraction-finalize once ready.",
                idx + 1, len(waypoints), place_label,
            )
        else:
            logger.warning(
                "Step 3: [%d/%d] '%s' FAILED to produce a video.",
                idx + 1, len(waypoints), place_label,
            )

    tracker.clear()
    logger.info(
        "Step 3 complete: %d attraction video(s) produced.", len(generated_videos)
    )
    return generated_videos
