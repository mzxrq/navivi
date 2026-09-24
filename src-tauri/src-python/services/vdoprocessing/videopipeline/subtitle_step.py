"""Subtitle domain core: builds .srt cue files from waypoint narration +
TTS audio, and burns them permanently onto the finished video files
(Step 5). services/cli/subtitle_commands.py is a thin wrapper over
build_waypoint_subtitle()/build_subtitles() below."""

import re
from pathlib import Path
from typing import Any, Dict, Optional

from services.logger.progress import tracker
from services.vdoprocessing.vdoexporter import VideoExporter

from .audio_step import _resolve_attraction_narration_script, _resolve_narration_script
from .helpers import logger, output_is_valid

# Same convention render_step.py's own RESIDENTIAL_LEG_RE and
# timeline_step.py's own mirrored regex use: a residential leg clip's
# filename embeds its 1-based departure-waypoint position
# ("02_waypoint_{N:02d}_..."), which is how those two steps look up a
# clip's narration/subtitle instead of trusting a blind per-clip position
# (stop-by leg-merging, or one leg producing more than one output file —
# see pedestrian.py's connected-stop-by cut — can both throw a raw index
# out of sync with subtitle_paths, which stays one entry per WAYPOINT
# regardless of how many video files a leg ends up producing).
_RESIDENTIAL_LEG_RE = re.compile(r"02_waypoint_(\d+)_")
# Attraction clip's embedded 0-based waypoint index (matches
# attraction_step.py's own filename convention and timeline_step.py's
# identical _ATTRACTION_RE) — same reasoning as the leg regex above:
# attraction clips aren't necessarily produced in waypoint order, so their
# position in `video_paths` is not a safe stand-in for their subtitle's
# index in `subtitle_paths`.
_ATTRACTION_RE = re.compile(r"04_attraction_(\d+)_")
_OVERVIEW_FILENAME = "01_overview.mp4"


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


def build_overview_subtitle(
    project_config: dict,
    audio_path: Optional[str],
    output_dir,
    force: bool = False,
) -> Optional[str]:
    """Builds (or, if already present and not `force`, reuses) the .srt
    subtitle for job_config.json's top-level "overview_narration" script —
    the one clip that isn't a waypoint, so it needs its own entry point
    rather than going through build_waypoint_subtitle. Returns None when
    there's no narration text configured or no matching audio to time
    cues against (mirrors build_waypoint_subtitle's own ValueError/
    FileNotFoundError cases, just swallowed here since the pipeline has
    nothing waypoint-shaped to skip-and-continue past for this one)."""
    script = (project_config.get("overview_narration") or "").strip()
    if not script or not audio_path or not Path(audio_path).exists():
        return None

    output_dir = Path(output_dir)
    subtitle_path = output_dir / f"{Path(audio_path).stem}.srt"

    if not force and output_is_valid(subtitle_path, min_bytes=10):
        return str(subtitle_path)

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
    return str(subtitle_path)


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


def build_attraction_subtitles(
    waypoints: list, attraction_audio_paths: list, output_subtitle_dir: str, force: bool = False
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

        if not force and output_is_valid(subtitle_path, min_bytes=10):
            subtitle_paths.append(str(subtitle_path))
            continue

        if not Path(audio_path).exists():
            subtitle_paths.append(None)
            continue

        try:
            from services.localization.subtitle import SRTDocument, SubtitleBuilder
            from services.tts.ttsengine import AudioProcessor

            analysis = AudioProcessor().analyze_pauses(str(audio_path))
            cues = SubtitleBuilder.build(
                text=script,
                duration_seconds=analysis["duration_seconds"],
                pauses=analysis["pauses"],
            )
            SRTDocument.write(cues, str(subtitle_path))
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


def burn_subtitles(
    video_paths: list[str],
    subtitle_paths: list[str],
    force: bool = False,
    overview_subtitle_path: Optional[str] = None,
    attraction_subtitle_paths: Optional[list[str]] = None,
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

    attraction_subtitle_paths = attraction_subtitle_paths or []
    final_videos = []

    # [NOTE] [Subtitle] Every clip is matched to its subtitle by the index
    # embedded in ITS OWN filename (leg/attraction — same regex convention
    # render_step.py's audio mux and timeline_step.py already use), or by
    # exact filename for the one-off overview clip — never by raw position
    # in `video_paths`. This used to fall back to `idx` (list position) for
    # anything that wasn't a residential leg, which happened to work only
    # by coincidence when an attraction/overview clip's position matched
    # some unrelated waypoint's subtitle_paths entry; a project with
    # attraction videos NOT produced in waypoint order (or any project at
    # all, for the overview clip, which was never even in subtitle_paths'
    # index space to begin with) got the wrong subtitle burned on, or a
    # random one, instead of its own.
    for idx, video_path in enumerate(video_paths):
        original_file = Path(video_path)
        name = original_file.name
        leg_match = _RESIDENTIAL_LEG_RE.search(name)
        attraction_match = _ATTRACTION_RE.search(name)

        if leg_match:
            sub_idx = int(leg_match.group(1)) - 1
            sub_path = subtitle_paths[sub_idx] if 0 <= sub_idx < len(subtitle_paths) else None
        elif attraction_match:
            sub_idx = int(attraction_match.group(1))
            sub_path = (
                attraction_subtitle_paths[sub_idx]
                if 0 <= sub_idx < len(attraction_subtitle_paths)
                else None
            )
        elif name == _OVERVIEW_FILENAME:
            sub_path = overview_subtitle_path
        else:
            # intro/outro/anything else never had a subtitle to begin with.
            sub_path = None

        if sub_path:
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
