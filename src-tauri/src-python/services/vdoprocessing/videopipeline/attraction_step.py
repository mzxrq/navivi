"""Step 4: Generate AI videos for individual attractions via ComfyUI."""

from pathlib import Path
from typing import Optional

from services.config.job_config import JobConfigManager

from .helpers import logger


def render_attraction_videos(
    project_config_path: str,
    audio_durations: Optional[list[float]] = None,
    audio_paths: Optional[list[str]] = None,
) -> list[str]:
    """Step 4: Generates AI videos for individual attractions using ComfyUI."""
    logger.info("Step 4: Generating attraction videos via ComfyUI.")

    config_path = Path(project_config_path)
    if not config_path.exists():
        logger.warning("Step 4: No project config found at %s — skipping.", config_path)
        return []

    from services.vdoprocessing.img2vdo import AttractionVideoGenerator

    job_config = JobConfigManager(config_path)
    generator = AttractionVideoGenerator(job_config=job_config)

    waypoints = job_config.get("waypoints", [])
    generated_videos = []

    audio_durations = audio_durations or []
    audio_paths = audio_paths or []

    for idx, wp in enumerate(waypoints):
        popup_image_entry = wp.get("popup_image")
        place_label = wp.get("label", f"waypoint_{idx}")

        if not popup_image_entry:
            logger.info(
                "Step 4: [%d/%d] Skipping '%s' — no popup image configured.",
                idx + 1,
                len(waypoints),
                place_label,
            )
            continue

        # --- MODIFIED PROMPT EXTRACTION ---
        # Extract the full list of camera pans from the waypoint config
        camera_pans = wp.get("camera_pans", [])

        # Pass the whole list, or fallback to a default list if empty
        if camera_pans and len(camera_pans) > 0:
            prompt_text = camera_pans
        else:
            prompt_text = [wp.get("label", "Beautiful Japanese scenery, high quality")]
        # ----------------------------------

        target_audio_duration = (
            audio_durations[idx] if idx < len(audio_durations) else 0.0
        )
        audio_path = audio_paths[idx] if idx < len(audio_paths) else None

        safe_label = str(wp.get("label", f"waypoint_{idx}")).replace(" ", "_")
        output_filename = f"04_attraction_{idx:02d}_{safe_label}.mp4"

        print(
            f"\n[Step 4/5] Generating AI Video for Attraction [{idx + 1}/{len(waypoints)}]: '{wp.get('label')}'"
        )

        logger.info(
            "Step 4: [%d/%d] Generating attraction video for: '%s'",
            idx + 1,
            len(waypoints),
            place_label,
        )

        result_path = generator.process_attraction_video(
            popup_image_entry=popup_image_entry,
            prompt_text=prompt_text,
            target_audio_duration=target_audio_duration,
            audio_path=audio_path,
            output_filename=output_filename,
        )

        if result_path:
            logger.info(
                "Step 4: [%d/%d] '%s' complete -> %s",
                idx + 1,
                len(waypoints),
                place_label,
                result_path,
            )
            generated_videos.append(result_path)
        else:
            logger.warning(
                "Step 4: [%d/%d] '%s' FAILED to produce a video.",
                idx + 1,
                len(waypoints),
                place_label,
            )

    logger.info(
        "Step 4 complete: %d attraction video(s) produced.", len(generated_videos)
    )
    return generated_videos
