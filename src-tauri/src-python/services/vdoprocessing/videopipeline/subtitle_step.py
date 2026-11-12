"""Subtitle domain core: builds .srt cue files from waypoint narration + TTS audio. They are burned once, onto
the whole video, at export (render_timeline). services/cli/subtitle_commands.py is a thin wrapper over
build_waypoint_subtitle()/build_subtitles() below."""

from pathlib import Path
from typing import Any, Dict, Optional

from services.localization.cues import clean_text
from services.logger.progress import tracker

from .audio_step import _resolve_attraction_narration_script, _resolve_narration_script
from .helpers import logger


def _write_srt(script: str, audio_path, subtitle_path: Path) -> int:
    """Times `script` against its audio and writes the .srt only when it changed. Always
    rebuilt (milliseconds)."""
    from services.localization.subtitle import SRTDocument, SubtitleBuilder
    from services.tts.ttsengine import AudioProcessor

    analysis = AudioProcessor().analyze_pauses(str(audio_path))
    cues = SubtitleBuilder.build(script, analysis["duration_seconds"], analysis["pauses"])
    if not (subtitle_path.exists() and subtitle_path.read_text(encoding="utf-8") == SRTDocument.to_string(cues)):
        SRTDocument.write(cues, str(subtitle_path))
    return len(cues)


def build_waypoint_subtitle(
    waypoint: dict,
    idx: int,
    audio_path: Optional[str],
    output_dir,
    force: bool = False,
) -> Dict[str, Any]:
    """Builds (or, if already present and not `force`, reuses) one
    waypoint's .srt subtitle file from its narration text and matching TTS
    audio's pause/duration analysis. Raises ValueError/FileNotFoundError if
    this waypoint can't produce a subtitle — callers decide whether that
    should abort (CLI, fail-fast) or be skipped-and-continued (the
    pipeline's build_subtitles(), which needs to keep going past
    un-narrated waypoints)."""
    if not isinstance(waypoint, dict):
        raise ValueError(f"Waypoint {idx} must be an object")

    script = _resolve_narration_script(waypoint)
    if not script:
        raise ValueError(f"Waypoint {idx} has no script, narration, or voiceover text")

    if not audio_path or not Path(audio_path).exists():
        raise FileNotFoundError(f"TTS audio not found for waypoint {idx}: {audio_path}")

    label = waypoint.get("label", f"Waypoint {idx + 1}")
    output_dir = Path(output_dir)
    subtitle_path = output_dir / f"{Path(audio_path).stem}.srt"
    cue_count = _write_srt(script, audio_path, subtitle_path)
    return {
        "index": idx,
        "label": label,
        "audio_path": str(audio_path),
        "subtitle_path": str(subtitle_path),
        "cue_count": cue_count,
    }


def build_overview_subtitle(
    project_config: dict,
    audio_path: Optional[str],
    output_dir,
    force: bool = False,
    script: Optional[str] = None,
) -> Optional[str]:
    """Builds (or, if already present and not `force`, reuses) the .srt
    subtitle for job_config.json's top-level "overview_narration" script
    (`script`: the part this audio file speaks, when the opening has its own) —
    the one clip that isn't a waypoint, so it needs its own entry point
    rather than going through build_waypoint_subtitle. Returns None when
    there's no narration text configured or no matching audio to time
    cues against (mirrors build_waypoint_subtitle's own ValueError/
    FileNotFoundError cases, just swallowed here since the pipeline has
    nothing waypoint-shaped to skip-and-continue past for this one)."""
    script = clean_text(script or project_config.get("overview_narration") or "").strip()
    if not script or not audio_path or not Path(audio_path).exists():
        return None

    subtitle_path = Path(output_dir) / f"{Path(audio_path).stem}.srt"
    _write_srt(script, audio_path, subtitle_path)
    return str(subtitle_path)


def build_finale_subtitle(project_config: dict, project_dir, output_dir) -> Optional[str]:
    """The finale narration's .srt (settings.finale_narration, timed against 98_finale_narration.wav); None without one."""
    from .audio_step import FINALE_NARRATION_FILENAME, finale_script
    from .helpers import project_audio_dir

    script = finale_script(project_config)
    if not script:
        return None
    audio = Path(project_audio_dir(project_dir)) / FINALE_NARRATION_FILENAME
    return build_overview_subtitle(project_config, str(audio), output_dir, script=script)


def build_subtitles(
    waypoints: list, audio_paths: list, output_subtitle_dir: str, force: bool = False,
) -> list:
    """Step: builds .srt subtitle files for every narrated waypoint that
    has matching TTS audio, keeping the returned list index-aligned with
    `waypoints` (None for any waypoint that can't produce a subtitle)."""
    output_dir = Path(output_subtitle_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    total = len(waypoints)
    subtitle_paths = []

    for idx, wp in enumerate(waypoints):
        audio_path = audio_paths[idx] if idx < len(audio_paths) else None
        tracker.show(f"Generating subtitle {idx + 1}/{total}")
        try:
            result = build_waypoint_subtitle(wp, idx, audio_path, output_dir, force=force)
            subtitle_paths.append(result["subtitle_path"])
        except (ValueError, FileNotFoundError):
            subtitle_paths.append(None)

    tracker.clear()
    logger.info(
        "Subtitle build complete: %d of %d waypoint(s) have subtitles.",
        sum(1 for p in subtitle_paths if p),
        total,
    )
    return subtitle_paths


def build_attraction_subtitles(
    waypoints: list, attraction_audio_paths: list, output_subtitle_dir: str, force: bool = False,
) -> list:
    """Step: builds .srt subtitle files for each waypoint's ATTRACTION-only
    narration (attractionNarration alone — see
    audio_step._resolve_attraction_narration_script), matched against
    `attraction_audio_paths` (audio_data's "attraction_audio_paths", NOT
    the combined arrival+attraction `audio_paths` build_subtitles() above
    uses). Kept as its own pass rather than folded into build_subtitles:
    burning the COMBINED subtitle onto an attraction clip used to show the
    arrival narration's text on a clip about looking around the place, and
    showed text at all even when attractionNarration itself was blank."""
    output_dir = Path(output_subtitle_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    total = len(waypoints)
    subtitle_paths = []

    for idx, wp in enumerate(waypoints):
        audio_path = attraction_audio_paths[idx] if idx < len(attraction_audio_paths) else None
        if not isinstance(wp, dict) or not _resolve_attraction_narration_script(wp) or not audio_path:
            subtitle_paths.append(None)
            continue

        tracker.show(f"Generating attraction subtitle {idx + 1}/{total}")
        script = _resolve_attraction_narration_script(wp)
        subtitle_path = output_dir / f"{Path(audio_path).stem}.srt"

        if not Path(audio_path).exists():
            subtitle_paths.append(None)
            continue

        try:
            _write_srt(script, audio_path, subtitle_path)
            subtitle_paths.append(str(subtitle_path))
        except Exception as e:
            logger.error("Failed to build attraction subtitle for waypoint %d: %s", idx, e)
            subtitle_paths.append(None)

    tracker.clear()
    logger.info(
        "Attraction subtitle build complete: %d of %d waypoint(s) have subtitles.",
        sum(1 for p in subtitle_paths if p),
        total,
    )
    return subtitle_paths
