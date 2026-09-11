"""Step 6: Assemble timeline.json — the final clip order (video + audio + subtitles)."""

import json
import re
from pathlib import Path
from typing import Optional

from .helpers import logger, project_subtitle_dir

# [NOTE] [Core] Waypoint index embedded in attraction clip filenames, e.g. "04_attraction_03_Kabutoyama.mp4" -> waypoint index 3 (matches attraction_step.py's `f"04_attraction_{idx:02d}_{safe_label}.mp4"`).
_ATTRACTION_RE = re.compile(r"04_attraction_(\d+)_")
# Residential-leg clip's embedded 1-based departure-waypoint RAW position
# (matches waypoints.py's chunk_filename and render_step.py's own
# RESIDENTIAL_LEG_RE) — used to look up that leg's narration by position
# instead of a blind per-clip counter, which stop-by leg-merging (a leg can
# skip over a merged-away stop-by) would otherwise throw out of sync with
# audio_paths/subtitle_paths.
_RESIDENTIAL_LEG_RE = re.compile(r"02_waypoint_(\d+)_")


def _find_subtitle(audio_path: Optional[str], subtitles_dir: Path) -> Optional[str]:
    if not audio_path:
        return None
    candidate = subtitles_dir / f"{Path(audio_path).stem}.srt"
    return str(candidate) if candidate.exists() else None


def _resolve(path: Optional[str]) -> Optional[str]:
    return str(Path(path).resolve()) if path else None


def build_timeline(
    video_paths: list[str],
    attraction_videos: list[str],
    final_videos: list[str],
    audio_paths: Optional[list[str]] = None,
    subtitle_paths: Optional[list[str]] = None,
    project_dir: str = ".",
    timeline_path: Optional[str] = None,
) -> str:
    """Builds timeline.json, one entry per final clip in the exact order the
    pipeline produced them (video_paths, i.e. overview + residential legs,
    followed by attraction_videos), each carrying its matching narration
    audio and subtitle file when one exists.
    """
    audio_paths = audio_paths or []
    subtitle_paths = subtitle_paths or []
    subtitles_dir = project_subtitle_dir(project_dir)

    num_route_videos = len(video_paths)

    tracks = []
    for order, final_path in enumerate(final_videos):
        if order < num_route_videos:
            source_name = Path(video_paths[order]).name
        else:
            attraction_idx = order - num_route_videos
            source_name = (
                Path(attraction_videos[attraction_idx]).name
                if attraction_idx < len(attraction_videos)
                else Path(final_path).name
            )

        audio_path = None
        subtitle_path = None

        if order < num_route_videos:
            leg_match = _RESIDENTIAL_LEG_RE.search(source_name)
            if leg_match:
                # 1-based in the filename; audio_paths/subtitle_paths are 0-based.
                leg_audio_idx = int(leg_match.group(1)) - 1
                if 0 <= leg_audio_idx < len(audio_paths):
                    audio_path = audio_paths[leg_audio_idx]
                    subtitle_path = (
                        subtitle_paths[leg_audio_idx]
                        if leg_audio_idx < len(subtitle_paths) and subtitle_paths[leg_audio_idx]
                        else _find_subtitle(audio_path, subtitles_dir)
                    )
        else:
            # [NOTE] [Core] Attraction clips index audio/subtitles directly by the waypoint index parsed from the filename (not a running counter like the residential-leg branch), since attraction videos aren't necessarily produced in waypoint order.
            match = _ATTRACTION_RE.search(source_name)
            if match:
                wp_idx = int(match.group(1))
                if wp_idx < len(audio_paths):
                    audio_path = audio_paths[wp_idx]
                    subtitle_path = (
                        subtitle_paths[wp_idx]
                        if wp_idx < len(subtitle_paths) and subtitle_paths[wp_idx]
                        else _find_subtitle(audio_path, subtitles_dir)
                    )

        tracks.append(
            {
                "order": order,
                "clip_name": Path(final_path).stem,
                "file_path": _resolve(final_path),
                "audio_path": _resolve(audio_path),
                "subtitle_path": _resolve(subtitle_path),
            }
        )

    timeline_data = {"video_tracks": tracks}

    output_path = Path(timeline_path) if timeline_path else Path(project_dir) / "timeline.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(timeline_data, f, indent=2, ensure_ascii=False)

    logger.info("Step 6 complete: timeline written to %s (%d clip(s)).", output_path, len(tracks))
    return str(output_path)
