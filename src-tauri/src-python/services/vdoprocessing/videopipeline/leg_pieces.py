"""Resolves each residential leg piece's own narration/subtitle.

Every leg's narration is DESTINATION-based: each piece (a whole simple
leg's only piece, or one piece of a leg a connectToRoute stop-by's
fullscreen photo-pause cut into several -- see pydeckrecorder/pedestrian.
py's `landmarks` docstring and route2vdo.py's own note on the "_contN"
filename convention) is the walk TOWARD its own next stop -- a landmark, or
the leg's actual destination for its last (or only) piece -- and plays
THAT stop's own narration, never the departure waypoint's. This is what
stops a waypoint's own narration from playing twice: once approaching it
(as some earlier leg/piece's target) and again leaving it (which is what a
departure-based model would otherwise do for the very next leg).

If a piece's target narration runs longer than the piece's own natural
video length, the piece's video is padded with a held last frame
(mirroring img2vdo.py's own narration-hold trick for attraction clips) so
its fullscreen photo-pause (or, for a leg's last piece, the walk itself)
visibly holds until the narration finishes, instead of cutting away
mid-sentence.

Before this existed, a leg was departure-based: every piece of a cut leg
got the SAME departure waypoint's narration/subtitle muxed on unmodified,
so it audibly restarted from the beginning (and the same subtitle cues
re-appeared from the start) on every piece — and a connected stop-by's own
written narration never played anywhere at all.

Computed ONCE, right after Step 4 (render_route_video) produces the silent
per-leg video files, and reused by both Step 5 (subtitle_step.burn_subtitles,
which needs the right subtitle to burn onto each piece's pixels) and Step 6
(timeline_step.build_timeline, which needs the right audio to mux at final
export) — burning happens before the timeline is built, so a split computed
only at Step 6 would be too late to affect what's actually burned onto the
video. Also returns an updated `video_paths` list (pieces needing a pad are
swapped for their padded copy) for pipeline.py to use from Step 5 onward.
"""

import json
import re
import subprocess
from pathlib import Path
from typing import Optional

from services import tuning
from services.vdoprocessing.cliptiming import read_audio_offset

from .helpers import logger

# Matches waypoints.py's chunk_filename / route2vdo.py's "_contN" convention —
# every piece of a cut leg shares this same prefix.
_RESIDENTIAL_LEG_RE = re.compile(r"02_waypoint_(\d+)_")

# Below this, a video/audio length mismatch isn't worth padding a whole
# extra encode for.
_MIN_PAD_SECONDS = 0.05

# A clip runs this long past the end of its narration, so the voice finishes
# on screen instead of the clip cutting away on its last word.
END_BUFFER_SECONDS = 0.0


def _pad_video_tail(ffmpeg_cmd: str, video_path: str, pad_seconds: float) -> Optional[str]:
    """Extends `video_path` by `pad_seconds`, holding its last frame (same
    tpad clone technique as vdoexporter.VideoExporter.finalize_clip's own
    hold_to path). Returns the new padded file's path, or None on failure
    (caller keeps the original, unpadded file in that case)."""
    src = Path(video_path)
    padded = src.with_name(f"{src.stem}_padded{src.suffix}")
    cmd = [
        ffmpeg_cmd, "-y", *tuning.ffmpeg_log_args(), "-i", str(src),
        "-vf", f"tpad=stop_mode=clone:stop_duration={pad_seconds:.3f}",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(padded),
    ]
    proc = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0 or not padded.exists():
        logger.warning("Narration split: failed to pad '%s' — %s", src.name, proc.stderr)
        return None
    return str(padded)


def compute_leg_narration_splits(
    video_paths: list[str],
    audio_paths: Optional[list[str]],
    subtitle_paths: Optional[list[str]],
    waypoints: Optional[list[dict]],
    project_dir: str,
) -> tuple[list[str], dict[str, tuple[Optional[str], Optional[str]]]]:
    """Groups `video_paths` (Step 4's silent per-leg output, pre-subtitle-
    burn) by their embedded leg number. For every leg with more than one
    piece, resolves each piece's own "target" waypoint (see route2vdo.py's
    "_pieces.json" sidecar) and, if needed, pads that piece's video to
    cover its target's full narration length.

    `waypoints`: job_config's raw "waypoints" array (with each entry's own
    stable "id") — resolves a piece plan's "target_waypoint_id" back to
    that waypoint's RAW 0-based position, i.e. its index into
    `audio_paths`/`subtitle_paths`.

    Returns (updated_video_paths, splits): `updated_video_paths` is
    `video_paths` with any padded piece swapped in for its original, and
    `splits` maps {final_video_stem: (audio_path, subtitle_path)} for every
    piece that got its own target narration resolved — a leg with no
    resolvable plan (or only one piece) is left entirely alone, so its
    caller falls back to the old shared-departure-audio behavior."""
    audio_paths = audio_paths or []
    subtitle_paths = subtitle_paths or []
    waypoints = waypoints or []
    id_to_position = {wp.get("id"): pos for pos, wp in enumerate(waypoints) if wp.get("id")}

    updated_video_paths = list(video_paths)
    splits: dict[str, tuple[Optional[str], Optional[str]]] = {}

    legs_by_number: dict[int, list[int]] = {}
    for i, video_path in enumerate(video_paths):
        match = _RESIDENTIAL_LEG_RE.search(Path(video_path).name)
        if not match:
            continue
        legs_by_number.setdefault(int(match.group(1)), []).append(i)

    if not legs_by_number:
        return updated_video_paths, splits

    try:
        from services.tts.ttsengine import FFmpegManager
        ffmpeg_cmd = FFmpegManager.resolve_ffmpeg_bin()
    except (RuntimeError, OSError) as exc:
        logger.warning("Narration split: ffmpeg unavailable — %s", exc)
        return updated_video_paths, splits

    # Every leg (not just ones a connectToRoute stop-by cut into several
    # pieces) is resolved the same way: narration is DESTINATION-based, so
    # even a plain single-piece leg plays its own destination waypoint's
    # narration during the walk toward it, never the departure's -- this
    # is what stops a leg's own destination narration from playing AGAIN
    # (duplicated) when the NEXT leg departs from that same waypoint.
    for leg_num, piece_indexes in legs_by_number.items():
        piece_paths = [video_paths[i] for i in piece_indexes]
        plan_path = Path(piece_paths[0]).parent / f"02_waypoint_{leg_num:02d}_pieces.json"
        target_id_by_file: dict[str, Optional[str]] = {}
        if plan_path.exists():
            try:
                with open(plan_path, "r", encoding="utf-8") as f:
                    plan = json.load(f)
                for entry in plan.get("pieces", []):
                    target_id_by_file[entry.get("file")] = entry.get("target_waypoint_id")
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Narration split: could not read piece plan '%s' — %s", plan_path, exc)
                continue
        else:
            continue

        for video_idx, video_path in zip(piece_indexes, piece_paths):
            wp_id = target_id_by_file.get(Path(video_path).name)
            if not wp_id or wp_id not in id_to_position:
                continue
            t_idx = id_to_position[wp_id]
            if not (t_idx < len(audio_paths)) or not audio_paths[t_idx]:
                continue
            target_audio = audio_paths[t_idx]
            target_subtitle = subtitle_paths[t_idx] if t_idx < len(subtitle_paths) else None

            try:
                target_dur = FFmpegManager.get_media_duration(target_audio)
                piece_dur = FFmpegManager.get_media_duration(video_path)
            except (RuntimeError, OSError) as exc:
                logger.warning("Narration split: could not probe durations for '%s' — %s", video_path, exc)
                splits[Path(video_path).stem] = (target_audio, target_subtitle)
                continue

            final_video_path = video_path
            # The narration starts `offset` seconds into the clip (after the
            # silent lead-in, see cliptiming.py), so it ends at
            # offset + target_dur, and the clip should outlast it a little
            # (END_BUFFER_SECONDS) - that's what the clip must cover.
            needed = read_audio_offset(video_path) + target_dur + END_BUFFER_SECONDS - piece_dur
            if needed > _MIN_PAD_SECONDS:
                padded = _pad_video_tail(ffmpeg_cmd, video_path, needed)
                if padded:
                    final_video_path = padded
                    updated_video_paths[video_idx] = padded

            splits[Path(final_video_path).stem] = (target_audio, target_subtitle)

    return updated_video_paths, splits
