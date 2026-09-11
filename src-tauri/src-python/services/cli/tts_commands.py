"""Isolated CLI commands for pipeline Step 2 (TTS narration generation) —
thin wrappers over services/vdoprocessing/videopipeline/audio_step.py, the
TTS domain's core module."""

from pathlib import Path
from typing import Any, Dict
import asyncio

from services.logger.logger import setup_logger
from services.logger.progress import tracker as _tracker
from services.vdoprocessing.videopipeline.audio_step import generate_waypoint_audio
from services.vdoprocessing.videopipeline.helpers import project_audio_dir
from .helpers import _load_tts_waypoints

logger = setup_logger("TTSCommands")


def test_tts(
    job_config_path: str,
    output_audio_dir: str = None,
    waypoint_index: int = 0,
    force: bool = False,
) -> Dict[str, Any]:
    """Generate and inspect TTS audio for one narrated waypoint."""
    logger.info("test_tts: loading waypoints from %s", job_config_path)
    config_path, waypoints = _load_tts_waypoints(job_config_path)
    logger.info("test_tts: loaded %d waypoint(s)", len(waypoints))
    if waypoint_index < 0 or waypoint_index >= len(waypoints):
        logger.error(
            "test_tts: waypoint_index %d out of range (0-%d)",
            waypoint_index, len(waypoints) - 1,
        )
        raise IndexError(
            f"waypoint_index must be between 0 and {len(waypoints) - 1}, "
            f"got {waypoint_index}"
        )

    output_dir = Path(output_audio_dir) if output_audio_dir else project_audio_dir(config_path.parent)
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("test_tts: audio output dir = %s", output_dir)

    from services.tts.ttsengine import AudioProcessor, IrodoriTTSClient

    client = IrodoriTTSClient(output_dir=output_dir)
    processor = AudioProcessor(output_dir=output_dir)

    waypoint = waypoints[waypoint_index]
    label = (
        waypoint.get("label", f"Waypoint {waypoint_index + 1}")
        if isinstance(waypoint, dict)
        else f"Waypoint {waypoint_index + 1}"
    )
    logger.info("test_tts: generating clip for waypoint %d ('%s')", waypoint_index, label)
    _tracker.show(f"Generating TTS: {label}")
    try:
        clip = asyncio.run(
            generate_waypoint_audio(
                waypoint, waypoint_index, client, processor, output_dir, force=force
            )
        )
    except Exception:
        logger.exception("test_tts: generation failed for waypoint %d ('%s')", waypoint_index, label)
        raise
    finally:
        _tracker.clear()
    logger.info("test_tts: done, clip=%s", clip["audio_path"])
    return {
        "success": True,
        "audio_dir": str(output_dir),
        "clip": clip,
    }


def test_tts_all(
    job_config_path: str,
    output_audio_dir: str = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Generate and inspect TTS audio for every narrated waypoint."""
    logger.info("test_tts_all: loading waypoints from %s", job_config_path)
    config_path, waypoints = _load_tts_waypoints(job_config_path)
    logger.info("test_tts_all: loaded %d waypoint(s)", len(waypoints))

    output_dir = Path(output_audio_dir) if output_audio_dir else project_audio_dir(config_path.parent)
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("test_tts_all: audio output dir = %s", output_dir)

    from services.tts.ttsengine import AudioProcessor, IrodoriTTSClient

    client = IrodoriTTSClient(output_dir=output_dir)
    processor = AudioProcessor(output_dir=output_dir)

    async def generate_all() -> list:
        total = len(waypoints)
        clips = []
        for index, waypoint in enumerate(waypoints):
            label = (
                waypoint.get("label", f"Waypoint {index + 1}")
                if isinstance(waypoint, dict)
                else f"Waypoint {index + 1}"
            )
            logger.info("test_tts_all: [%d/%d] starting waypoint '%s'", index + 1, total, label)
            _tracker.show(f"Generating TTS {index + 1}/{total}: {label}")
            try:
                clip = await generate_waypoint_audio(
                    waypoint, index, client, processor, output_dir, force=force
                )
            except Exception:
                logger.exception(
                    "test_tts_all: [%d/%d] waypoint '%s' failed", index + 1, total, label
                )
                raise
            clips.append(clip)
            logger.info("test_tts_all: [%d/%d] finished waypoint '%s'", index + 1, total, label)
        return clips

    try:
        clips = asyncio.run(generate_all())
    finally:
        _tracker.clear()
    logger.info("test_tts_all: done, generated %d clip(s)", len(clips))
    return {
        "success": True,
        "audio_dir": str(output_dir),
        "clips": clips,
    }
