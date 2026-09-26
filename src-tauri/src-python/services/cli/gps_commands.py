"""Isolated CLI commands for pipeline Step 1 (GPS parsing) and the
overview/residential video rendering steps."""

from pathlib import Path
from typing import Any, Dict, Optional

from services.logger.progress import tracker as _tracker
from services.vdoprocessing.videopipeline.helpers import project_route_video_dir


def test_gps(job_config_path: str) -> Dict[str, Any]:
    """Runs GPS parsing only (pipeline Step 1) — isolated so editing just
    raw_track.gpx/job_config.json's GPS-related settings can be checked
    without paying for TTS/attraction/video/subtitle stages. Every other
    test_* function across services/cli/ is this same one-step-only shape
    for its own pipeline step — together they cover all 5 of
    run_full_pipeline's steps individually, so a change scoped to one
    step/file doesn't require re-running the whole pipeline to check it."""
    from services.vdoprocessing.videopipeline import process_gps

    config_path = Path(job_config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"job_config.json not found: {config_path}")

    _tracker.show("Parsing GPS track...")
    cleaned_route = process_gps(str(config_path))
    _tracker.clear()
    return {
        "success": True,
        "summary": cleaned_route.get("summary", {}),
    }


def _existing_narration(config_path: str) -> dict:
    """Narration lengths / pauses / overview cues from the audio on disk, with
    the per-waypoint cue times stored (no TTS). Cues are left out when the
    project turns them off (settings.use_narration_cues=false)."""
    import json

    from services.vdoprocessing.videopipeline.audio_step import existing_audio_data
    from services.vdoprocessing.videopipeline.narration_step import record_cue_times

    audio = existing_audio_data(config_path)
    with open(config_path, "r", encoding="utf-8") as f:
        use_cues = bool(json.load(f).get("settings", {}).get("use_narration_cues", True))
    if use_cues:
        record_cue_times(config_path, audio)
    else:
        audio["overview_cue_times"] = {}
    return audio


def test_overview_video(
    job_config_path: str, output_video_dir: str = None, force: bool = False
) -> Dict[str, Any]:
    """Runs GPS parsing + route video rendering only, to sanity-check the
    overview map animation without paying for TTS/attraction/subtitle
    stages. render_mode="overview" also skips residential entirely (no
    per-leg residential map tile fetches, no residential clips rendered) —
    this really is overview-only now, not both bundled together."""
    from services.vdoprocessing.videopipeline import process_gps, render_route_video

    config_path = Path(job_config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"job_config.json not found: {config_path}")

    output_video_dir = output_video_dir or str(project_route_video_dir(config_path.parent))

    _tracker.show("Parsing GPS track...")
    cleaned_route = process_gps(str(config_path))
    _tracker.clear()

    _tracker.show("Rendering overview video...")
    # The overview follows its narration's cues: read the audio already made
    # (never generated here) so this stand-alone render matches the full pipeline.
    audio = _existing_narration(str(config_path))
    video_paths = render_route_video(
        cleaned_route=cleaned_route,
        project_config_path=str(config_path),
        output_video_dir=output_video_dir,
        overview_audio_duration=audio.get("overview_audio_duration"),
        overview_cue_times=audio.get("overview_cue_times"),
        force=force,
        render_mode="overview",
    )
    _tracker.clear()

    return {
        "success": True,
        "video_paths": video_paths,
        "summary": cleaned_route.get("summary", {}),
    }


def test_residential_video(
    job_config_path: str,
    output_video_dir: str = None,
    fps: Optional[int] = None,
    speed_kmh: Optional[float] = None,
    force: bool = False,
    leg_index: Optional[int] = None,
) -> Dict[str, Any]:
    """Runs the per-waypoint leg-by-leg render only, to sanity-check the
    residential animation without paying for the overview, TTS, or subtitle
    stages. Always goes through render_route_video (render_mode=
    "residential", so the overview animation itself is never rendered) and
    lets RouteAnimator.render() pick the engine from job_config.json's
    settings itself (use_pydeck_pedestrian, defaulting to the GeoJsonLayer
    chase camera; use_3d_res for the older vehicle-scenegraph renderer;
    else the flat 2D SpatialRenderer) — this used to special-case
    use_3d_res here and call record_headless_video directly, which bypassed
    that selection (and use_pydeck_pedestrian) entirely, so a project with
    use_3d_res set always got the vehicle pipeline no matter what.
    `fps`/`speed_kmh` are accepted for backwards compatibility with
    existing callers but no longer used — render_route_video derives both
    from job_config.json itself (settings.fps, per-leg mode speeds).
    `leg_index`: render only that ONE leg (0-indexed, in travel order) —
    see render_route_video's own docstring. Leave None to render every leg.
    """
    config_path = Path(job_config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"job_config.json not found: {config_path}")

    output_video_dir = Path(output_video_dir) if output_video_dir else project_route_video_dir(config_path.parent)
    output_video_dir.mkdir(parents=True, exist_ok=True)

    from services.vdoprocessing.videopipeline import process_gps, render_route_video

    _tracker.show("Parsing GPS track...")
    cleaned_route = process_gps(str(config_path))
    _tracker.clear()

    _tracker.show("Rendering residential video...")
    audio = _existing_narration(str(config_path))
    video_paths = render_route_video(
        cleaned_route=cleaned_route,
        project_config_path=str(config_path),
        output_video_dir=str(output_video_dir),
        audio_durations=audio.get("audio_durations"),
        audio_pauses=audio.get("audio_pauses"),
        force=force,
        render_mode="residential",
        leg_index=leg_index,
    )
    _tracker.clear()

    return {
        "success": bool(video_paths),
        "video_paths": video_paths,
    }
