"""Isolated CLI commands for pipeline Step 2 (TTS narration generation) —
thin wrappers over services/vdoprocessing/videopipeline/audio_step.py, the
TTS domain's core module. Each one applies the pipeline's own switches
(route-only legs, default cues, pronunciation dictionary) first, so the
audio it makes is the audio run_full_pipeline would make and reuse."""

from pathlib import Path
from typing import Any, Dict
import asyncio
import json

from services.logger.logger import setup_logger
from services.logger.progress import tracker as _tracker
from services.vdoprocessing.videopipeline.audio_step import (
    _resolve_attraction_narration_script,
    apply_cued_scripts,
    existing_audio_data,
    generate_attraction_audio_for_waypoint,
    generate_audio,
    generate_overview_audio,
    generate_waypoint_audio,
    is_passed_only,
    passed_only_reason,
    is_unvisited_stopby,
    merge_pronunciation,
    stop_tts_server,
)
from services.vdoprocessing.videopipeline.helpers import project_audio_dir
from services.vdoprocessing.videopipeline.narration_step import (
    add_default_cues,
    add_overview_cues,
    record_cue_times,
)
from .helpers import _apply_pipeline_settings, _load_tts_waypoints

logger = setup_logger("TTSCommands")


def _prepare(job_config_path: str, output_audio_dir: str = None, force: bool = False):
    """Pipeline setup shared by every TTS mode: switches, default cues, the
    cued waypoints and the TTS client/processor pair. `force` also makes the
    client skip the shared phrase cache, so a redo is a new take."""
    settings = _apply_pipeline_settings(job_config_path)
    add_default_cues(job_config_path)
    config_path, waypoints = _load_tts_waypoints(job_config_path)
    apply_cued_scripts(waypoints, config_path.parent)

    output_dir = Path(output_audio_dir) if output_audio_dir else project_audio_dir(config_path.parent)
    output_dir.mkdir(parents=True, exist_ok=True)
    from services.tts.ttsengine import AudioProcessor, make_tts_client

    client = make_tts_client(settings, output_dir)
    client.bypass_cache = force

    return (
        settings, config_path, waypoints, output_dir,
        client,
        AudioProcessor(output_dir=output_dir),
        merge_pronunciation(settings.get("global_pronunciation_dictionary"), settings.get("pronunciation_dictionary")),
    )


def _record_cues(config_path: Path, settings: dict) -> None:
    if settings.get("use_narration_cues", True):
        record_cue_times(str(config_path), existing_audio_data(str(config_path)))


def _check_index(waypoints: list, waypoint_index: int) -> None:
    if waypoint_index < 0 or waypoint_index >= len(waypoints):
        raise IndexError(
            f"waypoint_index must be between 0 and {len(waypoints) - 1}, got {waypoint_index}"
        )


def _label(waypoint, index: int) -> str:
    return waypoint.get("label", f"Waypoint {index + 1}") if isinstance(waypoint, dict) else f"Waypoint {index + 1}"


def test_tts(
    job_config_path: str,
    output_audio_dir: str = None,
    waypoint_index: int = 0,
    force: bool = False,
) -> Dict[str, Any]:
    """Generate and inspect the leg narration audio for one waypoint."""
    settings, config_path, waypoints, output_dir, client, processor, p_dict = _prepare(
        job_config_path, output_audio_dir, force
    )
    _check_index(waypoints, waypoint_index)
    waypoint = waypoints[waypoint_index]
    if is_passed_only(waypoint):
        reason = passed_only_reason(waypoint)
        _tracker.note(f"Skipped TTS: {_label(waypoint, waypoint_index)} ({reason})")
        return {"success": True, "skipped": reason, "clip": None}

    label = _label(waypoint, waypoint_index)
    _tracker.show(f"Generating TTS: {label}")
    try:
        clip = asyncio.run(
            generate_waypoint_audio(
                waypoint, waypoint_index, client, processor, output_dir,
                force=force, pronunciation_dict=p_dict,
            )
        )
    finally:
        _tracker.clear()
        stop_tts_server()
    _record_cues(config_path, settings)
    return {"success": True, "audio_dir": str(output_dir), "clip": clip}


def test_tts_all(
    job_config_path: str,
    output_audio_dir: str = None,
    force: bool = False,
) -> Dict[str, Any]:
    """The pipeline's whole Step 2: overview narration, every leg narration
    and every attraction narration, then the cue times."""
    settings = _apply_pipeline_settings(job_config_path)
    config_path = Path(job_config_path)
    add_default_cues(str(config_path))
    add_overview_cues(str(config_path))
    try:
        audio = generate_audio({}, str(config_path), output_audio_dir, force=force)
    finally:
        stop_tts_server()
    if settings.get("use_narration_cues", True):
        record_cue_times(str(config_path), audio)
    output_dir = Path(output_audio_dir) if output_audio_dir else project_audio_dir(config_path.parent)
    return {
        "success": True,
        "audio_dir": str(output_dir),
        "narrated": sum(1 for p in audio.get("audio_paths", []) if p),
        "attraction_narrated": sum(1 for p in audio.get("attraction_audio_paths", []) if p),
        **audio,
    }


def test_overview_tts(
    job_config_path: str,
    output_audio_dir: str = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Generate only the overview narration audio (00_overview_narration.wav)."""
    add_overview_cues(job_config_path)
    settings, config_path, _waypoints, output_dir, client, processor, p_dict = _prepare(
        job_config_path, output_audio_dir, force
    )
    project_config = json.loads(config_path.read_text(encoding="utf-8"))
    _tracker.show("Generating overview narration audio")
    try:
        clip = asyncio.run(
            generate_overview_audio(
                project_config, client, processor, output_dir, force=force,
                project_dir=config_path.parent, pronunciation_dict=p_dict,
            )
        )
    finally:
        _tracker.clear()
        stop_tts_server()
    if clip is None:
        return {"success": True, "skipped": "no overview narration", "clip": None}
    return {"success": True, "audio_dir": str(output_dir), "clip": clip}


def _attraction_tts_skip_reason(waypoint) -> str:
    """Why a waypoint gets no attraction narration ("" when it does)."""
    if not isinstance(waypoint, dict):
        return "not a waypoint"
    if is_passed_only(waypoint):
        return passed_only_reason(waypoint)
    if not _resolve_attraction_narration_script(waypoint):
        return "no attraction narration"
    return ""


def test_attraction_tts(
    job_config_path: str,
    output_audio_dir: str = None,
    waypoint_index: int = 0,
    force: bool = False,
) -> Dict[str, Any]:
    """Generate the attraction-only narration audio (the clip the attraction
    video plays) for one waypoint."""
    _settings, _config_path, waypoints, output_dir, client, processor, p_dict = _prepare(
        job_config_path, output_audio_dir, force
    )
    _check_index(waypoints, waypoint_index)
    waypoint = waypoints[waypoint_index]
    reason = _attraction_tts_skip_reason(waypoint)
    if reason:
        logger.info("test_attraction_tts: waypoint %d skipped (%s).", waypoint_index, reason)
        return {"success": True, "skipped": reason, "clip": None}

    _tracker.show(f"Generating attraction TTS: {_label(waypoint, waypoint_index)}")
    try:
        clip = asyncio.run(
            generate_attraction_audio_for_waypoint(
                waypoint, waypoint_index, client, processor, output_dir,
                force=force, pronunciation_dict=p_dict,
            )
        )
    finally:
        _tracker.clear()
        stop_tts_server()
    return {"success": True, "audio_dir": str(output_dir), "clip": clip}


def test_attraction_tts_all(
    job_config_path: str,
    output_audio_dir: str = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Generate the attraction-only narration audio for every waypoint that
    has one (stop-bys not connected to the route are skipped)."""
    _settings, _config_path, waypoints, output_dir, client, processor, p_dict = _prepare(
        job_config_path, output_audio_dir, force
    )
    todo = [(i, w) for i, w in enumerate(waypoints) if not _attraction_tts_skip_reason(w)]
    for i, w in enumerate(waypoints):
        if is_passed_only(w):
            _tracker.note(f"Skipped attraction TTS {i + 1}/{len(waypoints)}: {_label(w, i)} ({passed_only_reason(w)})")

    async def generate_all() -> list:
        clips = []
        for n, (index, waypoint) in enumerate(todo, 1):
            _tracker.show(f"Generating attraction TTS {n}/{len(todo)}: {_label(waypoint, index)}")
            clips.append(
                await generate_attraction_audio_for_waypoint(
                    waypoint, index, client, processor, output_dir,
                    force=force, pronunciation_dict=p_dict,
                )
            )
        return clips

    try:
        clips = asyncio.run(generate_all())
    finally:
        _tracker.clear()
        stop_tts_server()
    logger.info("test_attraction_tts_all: %d clip(s), %d waypoint(s) skipped.", len(clips), len(waypoints) - len(todo))
    return {"success": True, "audio_dir": str(output_dir), "clips": clips, "skipped": len(waypoints) - len(todo)}
