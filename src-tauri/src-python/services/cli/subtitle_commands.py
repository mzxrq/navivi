"""Isolated CLI commands for pipeline Step 5 (subtitle generation from
matching TTS audio)."""

from pathlib import Path
from typing import Any, Dict

from services.logger.progress import tracker as _tracker
from .helpers import _load_tts_waypoints, _video_safe_label


# [NOTE] [Subtitle] Mirrors attraction_commands._attraction_audio_path's filename scheme rather than sharing it, since the two are looked up as different types (Optional[str] vs. Path) — keep both in sync if the "02_waypoint_NN_<label>.wav" naming ever changes.
def _subtitle_audio_path(config_path: Path, waypoint_index: int, label: Any) -> Path:
    return (
        config_path.parent
        / "audio"
        / (
            f"02_waypoint_{waypoint_index + 1:02d}_"
            f"{_video_safe_label(label, f'leg{waypoint_index + 1}')}.wav"
        )
    )


def _build_subtitle(
    config_path: Path,
    waypoint: Dict[str, Any],
    waypoint_index: int,
    output_subtitle_dir: Path,
) -> Dict[str, Any]:
    if not isinstance(waypoint, dict):
        raise ValueError(f"Waypoint {waypoint_index} must be an object")

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
    audio_path = _subtitle_audio_path(config_path, waypoint_index, label)
    if not audio_path.exists():
        raise FileNotFoundError(
            f"TTS audio not found for waypoint {waypoint_index}: {audio_path}"
        )

    from services.localization.subtitle import SRTDocument, SubtitleBuilder
    from services.tts.ttsengine import AudioProcessor

    analysis = AudioProcessor().analyze_pauses(str(audio_path))
    cues = SubtitleBuilder.build(
        text=script.strip(),
        duration_seconds=analysis["duration_seconds"],
        pauses=analysis["pauses"],
    )
    output_subtitle_dir.mkdir(parents=True, exist_ok=True)
    subtitle_path = output_subtitle_dir / f"{audio_path.stem}.srt"
    SRTDocument.write(cues, str(subtitle_path))
    return {
        "index": waypoint_index,
        "label": label,
        "audio_path": str(audio_path),
        "subtitle_path": str(subtitle_path),
        "cue_count": len(cues),
    }


def test_subtitle(
    job_config_path: str,
    output_subtitle_dir: str = None,
    waypoint_index: int = 0,
) -> Dict[str, Any]:
    """Generate subtitles for one waypoint from its matching TTS audio."""
    config_path, waypoints = _load_tts_waypoints(job_config_path)
    if waypoint_index < 0 or waypoint_index >= len(waypoints):
        raise IndexError(
            f"waypoint_index must be between 0 and {len(waypoints) - 1}, "
            f"got {waypoint_index}"
        )
    output_dir = Path(output_subtitle_dir or (config_path.parent / "subtitles"))
    result = _build_subtitle(
        config_path, waypoints[waypoint_index], waypoint_index, output_dir
    )
    return {"success": True, **result}


def test_subtitles(
    job_config_path: str,
    output_subtitle_dir: str = None,
) -> Dict[str, Any]:
    """Generate subtitles for every waypoint from matching TTS audio."""
    config_path, waypoints = _load_tts_waypoints(job_config_path)
    output_dir = Path(output_subtitle_dir or (config_path.parent / "subtitles"))
    total = len(waypoints)
    results = []
    for index, waypoint in enumerate(waypoints):
        label = (
            waypoint.get("label", f"Waypoint {index + 1}")
            if isinstance(waypoint, dict)
            else f"Waypoint {index + 1}"
        )
        _tracker.show(f"Generating subtitle {index + 1}/{total}: {label}")
        results.append(_build_subtitle(config_path, waypoint, index, output_dir))
    _tracker.clear()
    return {
        "success": True,
        "subtitle_dir": str(output_dir),
        "subtitle_paths": [result["subtitle_path"] for result in results],
        "results": results,
    }
