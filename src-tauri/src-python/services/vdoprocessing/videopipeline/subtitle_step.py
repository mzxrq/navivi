"""Subtitle domain core: builds .srt cue files from waypoint narration +
TTS audio, and burns them permanently onto the finished video files
(Step 5). services/cli/subtitle_commands.py is a thin wrapper over
build_waypoint_subtitle()/build_subtitles() below."""

from pathlib import Path
from typing import Any, Dict, Optional

from services.logger.progress import tracker
from services.vdoprocessing.vdoexporter import VideoExporter

from .audio_step import _resolve_narration_script
from .helpers import logger, output_is_valid


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

    if not force and output_is_valid(subtitle_path, min_bytes=10):
        return {
            "index": idx,
            "label": label,
            "audio_path": str(audio_path),
            "subtitle_path": str(subtitle_path),
            "cue_count": None,
            "skipped": True,
        }

    from services.localization.subtitle import SRTDocument, SubtitleBuilder
    from services.tts.ttsengine import AudioProcessor

    analysis = AudioProcessor().analyze_pauses(str(audio_path))
    cues = SubtitleBuilder.build(
        text=script,
        duration_seconds=analysis["duration_seconds"],
        pauses=analysis["pauses"],
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    SRTDocument.write(cues, str(subtitle_path))
    return {
        "index": idx,
        "label": label,
        "audio_path": str(audio_path),
        "subtitle_path": str(subtitle_path),
        "cue_count": len(cues),
    }


def build_subtitles(
    waypoints: list, audio_paths: list, output_subtitle_dir: str, force: bool = False
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


def burn_subtitles(
    video_paths: list[str],
    subtitle_paths: list[str],
    force: bool = False,
) -> list[str]:
    """Step 5: Permanently burns SRT subtitles onto the finished video files.

    Each subtitled output is written next to its own source video (same
    directory) rather than into one shared folder — route and attraction
    clips now live in their own subfolders (see
    helpers.project_route_video_dir/project_attraction_video_dir), so this
    keeps a leg's/attraction's subtitled output grouped with its source
    instead of flattening everything back into one place.
    """
    logger.info("Step 5: Burning subtitles into %d video(s).", len(video_paths))

    final_videos = []

    # [NOTE] [Subtitle] Matches subtitle_paths[idx] to video_paths[idx] purely by list position — the two lists must stay in the same order upstream or subtitles land on the wrong clip.
    for idx, video_path in enumerate(video_paths):
        original_file = Path(video_path)

        if idx < len(subtitle_paths) and subtitle_paths[idx]:
            sub_path = subtitle_paths[idx]
            subtitled_output = str(
                original_file.parent
                / f"{original_file.stem}_subtitled{original_file.suffix}"
            )

            if not force and output_is_valid(subtitled_output):
                logger.info(
                    "Step 5: [%d/%d] '%s' already subtitled — skipping burn.",
                    idx + 1,
                    len(video_paths),
                    original_file.name,
                )
                final_videos.append(subtitled_output)
                continue

            tracker.show(
                f"Burning subtitle {idx + 1}/{len(video_paths)}: {original_file.name}"
            )

            logger.info(
                "Step 5: [%d/%d] Burning subtitles onto '%s'.",
                idx + 1,
                len(video_paths),
                original_file.name,
            )
            try:
                result = VideoExporter.burn_subtitles(
                    input_video_path=video_path,
                    subtitle_file_path=sub_path,
                    output_video_path=subtitled_output,
                )
                final_videos.append(result)
            except Exception as e:
                logger.error(
                    "Step 5: [%d/%d] Failed to burn subtitle for '%s': %s",
                    idx + 1,
                    len(video_paths),
                    original_file.name,
                    e,
                )
                final_videos.append(video_path)
        else:
            tracker.show(
                f"Passing through video {idx + 1}/{len(video_paths)}: {original_file.name}"
            )

            logger.info(
                "Step 5: [%d/%d] No subtitle file for '%s' — passing through unchanged.",
                idx + 1,
                len(video_paths),
                original_file.name,
            )
            final_videos.append(video_path)

    tracker.clear()
    logger.info("Step 5 complete: %d video(s) processed.", len(final_videos))
    return final_videos
