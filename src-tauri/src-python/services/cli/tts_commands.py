"""Isolated CLI commands for pipeline Step 2 (TTS narration generation)."""

from pathlib import Path
from typing import Any, Dict
import asyncio

from services.logger.progress import tracker as _tracker
from .helpers import _load_tts_waypoints, _video_safe_label


async def _generate_tts_clip(
    client: Any,
    processor: Any,
    waypoint: Dict[str, Any],
    waypoint_index: int,
) -> Dict[str, Any]:
    if not isinstance(waypoint, dict):
        raise ValueError(f"Waypoint {waypoint_index} must be an object")

    # [NOTE] [TTS] "script" is the canonical field; "narration"/"voiceover" are accepted for job_config.json files written by older frontend builds.
    script = (
        waypoint.get("script")
        or waypoint.get("narration")
        or waypoint.get("voiceover")
    )
    if not isinstance(script, str) or not script.strip():
        raise ValueError(
            f"Waypoint {waypoint_index} has no script, narration, or voiceover text"
        )

    label = waypoint.get("label", f"Waypoint {waypoint_index + 1}")
    audio_filename = (
        f"02_waypoint_{waypoint_index + 1:02d}_"
        f"{_video_safe_label(label, f'leg{waypoint_index + 1}')}.wav"
    )
    audio_path = await client.generate_speech(
        script.strip(), output_filename=audio_filename
    )
    analysis = processor.analyze_pauses(audio_path)
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
    config_path, waypoints = _load_tts_waypoints(job_config_path)
    if waypoint_index < 0 or waypoint_index >= len(waypoints):
        raise IndexError(
            f"waypoint_index must be between 0 and {len(waypoints) - 1}, "
            f"got {waypoint_index}"
        )

    output_dir = Path(output_audio_dir or (config_path.parent / "audio"))
    output_dir.mkdir(parents=True, exist_ok=True)

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
    _tracker.show(f"Generating TTS: {label}")
    clip = asyncio.run(generate_speech())
    _tracker.clear()
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
    config_path, waypoints = _load_tts_waypoints(job_config_path)
    output_dir = Path(output_audio_dir or (config_path.parent / "audio"))
    output_dir.mkdir(parents=True, exist_ok=True)

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
            _tracker.show(f"Generating TTS {index + 1}/{total}: {label}")
            clips.append(await _generate_tts_clip(client, processor, waypoint, index))
        return clips

    clips = asyncio.run(generate_all())
    _tracker.clear()
    return {
        "success": True,
        "audio_dir": str(output_dir),
        "clips": clips,
    }
