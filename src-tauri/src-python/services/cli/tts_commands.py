"""Isolated CLI commands for pipeline Step 2 (TTS narration generation)."""

from pathlib import Path
from typing import Any, Dict
import asyncio

from services.logger.logger import setup_logger
from services.logger.progress import tracker as _tracker
from .helpers import _load_tts_waypoints, _video_safe_label

logger = setup_logger("TTSCommands")


async def _generate_tts_clip(
    client: Any,
    processor: Any,
    waypoint: Dict[str, Any],
    waypoint_index: int,
) -> Dict[str, Any]:
    if not isinstance(waypoint, dict):
        raise ValueError(f"Waypoint {waypoint_index} must be an object")

    # [NOTE] [TTS] The waypoint editor writes narration as separate
    # arriving/attraction legs (see WaypointEditor.tsx); "script"/"narration"/
    # "voiceover" are only for older job_config.json files that predate that split.
    arriving = (waypoint.get("arrivingNarration") or "").strip()
    attraction = (waypoint.get("attractionNarration") or waypoint.get("narration") or "").strip()
    script = " ".join(part for part in (arriving, attraction) if part) or (
        waypoint.get("script") or waypoint.get("voiceover")
    )
    if not isinstance(script, str) or not script.strip():
        logger.warning(
            "Waypoint %d has no script, narration, or voiceover text", waypoint_index
        )
        raise ValueError(
            f"Waypoint {waypoint_index} has no script, narration, or voiceover text"
        )

    label = waypoint.get("label", f"Waypoint {waypoint_index + 1}")
    audio_filename = (
        f"02_waypoint_{waypoint_index + 1:02d}_"
        f"{_video_safe_label(label, f'leg{waypoint_index + 1}')}.wav"
    )
    logger.info(
        "Waypoint %d ('%s'): requesting TTS clip -> %s (%d chars)",
        waypoint_index, label, audio_filename, len(script.strip()),
    )
    audio_path = await client.generate_speech(
        script.strip(), output_filename=audio_filename
    )
    logger.info("Waypoint %d ('%s'): audio saved to %s", waypoint_index, label, audio_path)

    analysis = processor.analyze_pauses(audio_path)
    logger.info(
        "Waypoint %d ('%s'): duration=%.2fs, %d pause(s) detected",
        waypoint_index, label, analysis["duration_seconds"], len(analysis["pauses"]),
    )
    return {
        "index": waypoint_index,
        "label": label,
        "text": script.strip(),
        "audio_path": audio_path,
        "duration_seconds": analysis["duration_seconds"],
        "pauses": analysis["pauses"],
    }


def test_tts(
    job_config_path: str,
    output_audio_dir: str = None,
    waypoint_index: int = 0,
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

    output_dir = Path(output_audio_dir or (config_path.parent / "audio"))
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("test_tts: audio output dir = %s", output_dir)

    from services.tts.ttsengine import AudioProcessor, IrodoriTTSClient

    client = IrodoriTTSClient(output_dir=output_dir)
    processor = AudioProcessor(output_dir=output_dir)

    async def generate_speech() -> str:
        return await _generate_tts_clip(
            client, processor, waypoints[waypoint_index], waypoint_index
        )

    label = (
        waypoints[waypoint_index].get("label", f"Waypoint {waypoint_index + 1}")
        if isinstance(waypoints[waypoint_index], dict)
        else f"Waypoint {waypoint_index + 1}"
    )
    logger.info("test_tts: generating clip for waypoint %d ('%s')", waypoint_index, label)
    _tracker.show(f"Generating TTS: {label}")
    try:
        clip = asyncio.run(generate_speech())
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
) -> Dict[str, Any]:
    """Generate and inspect TTS audio for every narrated waypoint."""
    logger.info("test_tts_all: loading waypoints from %s", job_config_path)
    config_path, waypoints = _load_tts_waypoints(job_config_path)
    logger.info("test_tts_all: loaded %d waypoint(s)", len(waypoints))

    output_dir = Path(output_audio_dir or (config_path.parent / "audio"))
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
                clip = await _generate_tts_clip(client, processor, waypoint, index)
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
