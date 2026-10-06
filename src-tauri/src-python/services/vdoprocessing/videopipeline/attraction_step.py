"""Step 3: Generate AI videos for individual attractions (ComfyUI/Wan2.2
image-to-video, falling back to local outpaint+pan on failure).

This is the attraction domain's core module — services/cli/attraction_commands.py
is a thin wrapper around generate_waypoint_attraction_video() below, rather
than reimplementing prompt resolution and filename conventions on its own."""

from pathlib import Path
from typing import Any, Dict, Optional

from services.logger.progress import tracker

from .helpers import attraction_output_filename, has_attraction_media, logger


def _resolve_attraction_prompt(waypoint: dict) -> list:
    """The editor's pan per photo (imagePans, one per image, "panright" where
    unset; camera_pans in projects saved before it), else a label prompt."""
    pans = waypoint.get("imagePans")
    if not isinstance(pans, list) or not pans:
        pans = waypoint.get("camera_pans") if isinstance(waypoint.get("camera_pans"), list) else []
    photos = len(waypoint.get("images") or waypoint.get("popup_image") or [])
    if photos:
        pans = [pans[i] if i < len(pans) and pans[i] else "panright" for i in range(photos)]
    if pans:
        return pans
    return [waypoint.get("label", "Beautiful Japanese scenery, high quality")]


def needs_wan(waypoints: list) -> bool:
    """Whether any of these waypoints' attraction clips will run on ComfyUI
    (a photo with a moving preset); stills and the user's own videos don't."""
    from services import tuning
    from services.vdoprocessing.camera_pan import STILL_PRESET, normalize_camera_pan

    if tuning.ATTRACTION_GENERATOR == "parallax":
        return False
    for wp in waypoints:
        if not isinstance(wp, dict) or wp.get("videos") or not wp.get("popup_image") or is_passed_only(wp):
            continue
        if any(normalize_camera_pan(p) not in (STILL_PRESET, *tuning.ATTRACTION_JUMP_CUT_PRESETS)
               for p in _resolve_attraction_prompt(wp)):
            return True
    return False


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
    # `images` holds every photo; the editor saves only the first into `popup_image`.
    popup_image_entry = waypoint.get("images") or waypoint.get("popup_image")
    label = waypoint.get("label", f"waypoint_{idx}")

    if waypoint.get("videos"):
        from services.vdoprocessing.user_videos import process_user_videos

        output_filename = attraction_output_filename(idx, label)
        result_path = process_user_videos(
            generator, waypoint["videos"], waypoint.get("videoSound") or [], target_audio_duration,
            output_filename, place_label=label, force=force,
        )
        if result_path:
            return {
                "status": "generated", "label": label, "video_path": result_path,
                "audio_path": audio_path, "output_filename": output_filename,
            }
        return {"status": "failed", "label": label, "output_filename": output_filename}

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


from .audio_step import is_passed_only, is_unvisited_stopby, passed_only_reason  # noqa: E402,F401  (shared rule: see audio_step)


def render_attraction_videos(
    project_config_path: str,
    audio_durations: Optional[list[float]] = None,
    audio_paths: Optional[list[str]] = None,
    force: bool = False,
) -> list[str]:
    # [NOTE] [Core] `audio_durations`/`audio_paths` are each waypoint's own
    # ATTRACTION-only narration (audio_data's "attraction_audio_durations"/
    # "attraction_audio_paths" — see audio_step.py's
    # generate_attraction_audio_for_waypoint), NOT the combined arrival+
    # attraction audio used for the residential leg's own narration.
    # Reusing that combined audio here used to replay the arrival
    # narration onto the attraction clip too, and — when attractionNarration
    # was blank — give the attraction clip 100% arrival-narration audio/
    # subtitles instead of staying silent, which is what it should do.
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
    # first submission. Only when this run uses Wan: an all-stills run would
    # otherwise kill another process's job on the shared server.
    waypoints = job_config.get("waypoints", [])
    if needs_wan(waypoints):
        ComfyUII2VClient().clear_queue()

    generated_videos = []
    audio_durations = audio_durations or []
    audio_paths = audio_paths or []

    for idx, wp in enumerate(waypoints):
        place_label = wp.get("label", f"waypoint_{idx}")

        # A place the walker only passes (an unconnected stop-by, or a
        # waypoint skipped in video export) gets no attraction video (and
        # timeline_step never uses one).
        if is_passed_only(wp):
            reason = passed_only_reason(wp)
            logger.info(
                "Step 3: [%d/%d] Skipping '%s' — %s.", idx + 1, len(waypoints), place_label, reason,
            )
            tracker.note(f"Skipped attraction video {idx + 1}/{len(waypoints)}: {place_label} ({reason})")
            continue

        # Check upfront, before ever showing "Generating..." or touching
        # ComfyUI/the local fallback — a waypoint with no popup image has
        # nothing to generate a clip from, so skip it outright.
        if not has_attraction_media(wp):
            logger.info(
                "Step 3: [%d/%d] Skipping '%s' — no popup image configured.",
                idx + 1, len(waypoints), place_label,
            )
            continue

        tracker.show(f"Generating attraction video {idx + 1}/{len(waypoints)}: {place_label}")
        # ComfyUI/Wan holds a lot of RAM: with little left, restart its server
        # (it reloads on the next call) before piling another clip onto it.
        from services import tuning
        from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient

        tuning.ensure_free_ram(
            f"attraction video {idx + 1}", relief=ComfyUII2VClient.stop_server
        )
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
            # Shouldn't normally hit this now that we pre-check above —
            # kept as a safety net for any other validation inside
            # generate_waypoint_attraction_video.
            logger.info(
                "Step 3: [%d/%d] Skipping '%s' — no popup image configured.",
                idx + 1, len(waypoints), place_label,
            )
        elif result["status"] == "generated":
            logger.info(
                "Step 3: [%d/%d] '%s' complete -> %s",
                idx + 1, len(waypoints), place_label, result["video_path"],
            )
            # Narration audio is deliberately NOT muxed in here — this clip
            # stays silent, same as every other clip the pipeline produces
            # (see render_step.py's own note). Its narration audio (already
            # generated above, result["audio_path"]) is wired into
            # timeline.json as a separate track by pipeline.py's own
            # attraction_audio_paths, and only muxed at final export.
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
