"""Step 6: Assemble timeline.json — the final clip order (video + audio + subtitles)."""

import json
import re
from pathlib import Path
from typing import Optional

from services.vdoprocessing.cliptiming import read_audio_offset

from .helpers import logger, project_subtitle_dir
from services import tuning

# [NOTE] [Core] Waypoint index embedded in attraction clip filenames, e.g. "04_attraction_03_Kabutoyama.mp4" -> waypoint index 3 (matches attraction_step.py's `f"04_attraction_{idx:02d}_{safe_label}.mp4"`).
_ATTRACTION_RE = re.compile(r"04_attraction_(\d+)_")
# Residential-leg clip's embedded 1-based departure-waypoint RAW position
# (matches waypoints.py's chunk_filename and render_step.py's own
# RESIDENTIAL_LEG_RE) — used to look up that leg's narration by position
# instead of a blind per-clip counter, which stop-by leg-merging (a leg can
# skip over a merged-away stop-by) would otherwise throw out of sync with
# audio_paths/subtitle_paths.
_RESIDENTIAL_LEG_RE = re.compile(r"02_waypoint_(\d+)_")
# Overview clip's fixed filename — hardcoded the same way in
# route2vdo.py/overview.py (no shared tuning.py constant for it).
_OVERVIEW_FILENAME = "01_overview.mp4"


def _unvisited_stopbys(project_dir: str) -> set:
    """0-based positions of waypoints the walker only passes (unconnected
    stop-bys, and waypoints skipped in video export): no attraction clip."""
    from .audio_step import is_passed_only

    try:
        with open(Path(project_dir) / "job_config.json", "r", encoding="utf-8") as f:
            waypoints = json.load(f).get("waypoints", [])
    except (OSError, json.JSONDecodeError):
        return set()
    return {pos for pos, wp in enumerate(waypoints) if is_passed_only(wp)}


def _waypoint_ids(project_dir: str) -> dict:
    """{waypoint id: 0-based position} from the project's job_config.json."""
    try:
        with open(Path(project_dir) / "job_config.json", "r", encoding="utf-8") as f:
            waypoints = json.load(f).get("waypoints", [])
    except (OSError, json.JSONDecodeError):
        return {}
    return {wp.get("id"): pos for pos, wp in enumerate(waypoints) if wp.get("id")}


def _piece_target(source: str, waypoint_ids: dict) -> Optional[int]:
    """0-based position of the waypoint a leg piece walks toward, from the
    leg's _pieces.json (written by route2vdo.py), or None if unknown."""
    src = Path(source)
    match = _RESIDENTIAL_LEG_RE.search(src.name)
    if not match:
        return None
    plan_path = src.parent / f"02_waypoint_{int(match.group(1)):02d}_pieces.json"
    try:
        with open(plan_path, "r", encoding="utf-8") as f:
            pieces = json.load(f).get("pieces", [])
    except (OSError, json.JSONDecodeError):
        return None
    # `source` may be a "_padded" copy (leg_pieces.py); the plan names the original.
    stem = src.stem.replace("_padded", "")
    for entry in pieces:
        if Path(entry.get("file", "")).stem == stem:
            return waypoint_ids.get(entry.get("target_waypoint_id"))
    return None


def _find_subtitle(audio_path: Optional[str], subtitles_dir: Path) -> Optional[str]:
    if not audio_path:
        return None
    candidate = subtitles_dir / f"{Path(audio_path).stem}.srt"
    return str(candidate) if candidate.exists() else None


def _resolve(path: Optional[str]) -> Optional[str]:
    return str(Path(path).resolve()) if path else None


_SRT_TIME_RE = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")
# Matches the editor's MIN_SEGMENT (src/features/editor/model.ts).
_MIN_SEGMENT = 0.5


def _read_srt(path: Optional[str]) -> list[dict]:
    """[{start, end, text}] from an .srt file; [] if missing or unreadable."""
    if not path:
        return []
    try:
        raw = Path(path).read_text(encoding="utf-8-sig")
    except OSError:
        return []
    cues = []
    for block in re.split(r"\n\s*\n", raw.replace("\r", "").strip()):
        lines = block.split("\n")
        for i, line in enumerate(lines):
            m = _SRT_TIME_RE.search(line)
            if not m:
                continue
            g = [int(x) for x in m.groups()]
            start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
            end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
            text = "\n".join(lines[i + 1:]).strip()
            if text:
                cues.append({"start": round(start, 3), "end": round(end, 3), "text": text})
            break
    return cues


def _duration(path: Optional[str]) -> float:
    if not path:
        return 0.0
    from services.tts.ttsengine import FFmpegManager

    try:
        return float(FFmpegManager.get_media_duration(path))
    except Exception as exc:
        logger.warning("Could not probe %s for subtitle timing: %s", path, exc)
        return 0.0


def _clip_length(video: Optional[str], audio: Optional[str], audio_offset: float) -> float:
    """Clip length as the editor and exporter lay it out: video, held for the narration."""
    narration = audio_offset + _duration(audio) if audio else 0.0
    return max(_MIN_SEGMENT, _duration(video), narration)


def build_timeline(
    video_paths: list[str],
    attraction_videos: list[str],
    final_videos: list[str],
    audio_paths: Optional[list[str]] = None,
    subtitle_paths: Optional[list[str]] = None,
    project_dir: str = ".",
    timeline_path: Optional[str] = None,
    overview_audio_path: Optional[str] = None,
    overview_subtitle_path: Optional[str] = None,
    attraction_audio_paths: Optional[list[str]] = None,
    attraction_subtitle_paths: Optional[list[str]] = None,
    leg_narration_splits: Optional[dict[str, tuple[Optional[str], Optional[str]]]] = None,
    attraction_fade_seconds: float = 0.0,
) -> str:
    """Builds timeline.json with clips ordered intro -> overview -> for each
    leg in travel order, that leg's departure waypoint's own attraction
    video (if it has one) immediately followed by the leg itself -> outro.

    `video_paths`/`attraction_videos` are the pre-subtitle-burn source
    paths pipeline.py rendered (in the same order/positions it built
    `final_videos` from: video_paths's clips first, then
    attraction_videos's, with intro/outro then attached before/after) —
    used here only to recover each `final_videos` entry's ORIGINAL
    filename (source_name), since that filename is what carries the
    waypoint/leg index this function reorders and audio/subtitle-matches
    by. `final_videos` itself supplies the actual (burned/muxed) paths
    that end up in the output timeline.

    Previously every residential leg played before any attraction video
    (route clips, then all attraction clips, in two separate blocks).
    Interleaved instead: a viewer sees "look around here" (the attraction
    video) before "now we travel to the next stop" (the leg), matching
    the actual visit order, rather than a "sightseeing reel" back-to-back
    with a separate "travel reel".
    """
    audio_paths = audio_paths or []
    subtitle_paths = subtitle_paths or []
    attraction_audio_paths = attraction_audio_paths or []
    attraction_subtitle_paths = attraction_subtitle_paths or []
    leg_narration_splits = leg_narration_splits or {}
    subtitles_dir = project_subtitle_dir(project_dir)

    num_route_videos = len(video_paths)
    num_attraction_videos = len(attraction_videos)
    route_pairs = list(zip(video_paths, final_videos[:num_route_videos]))
    attraction_pairs = list(
        zip(
            attraction_videos,
            final_videos[num_route_videos:num_route_videos + num_attraction_videos],
        )
    )
    # Whatever's left after the route/attraction blocks — just the outro,
    # when pipeline.py appended one (see build_timeline's caller).
    trailing_pairs = [
        (Path(p).name, p) for p in final_videos[num_route_videos + num_attraction_videos:]
    ]

    intro_pair, overview_pair = None, None
    legs_by_number: dict[int, list[tuple[str, str]]] = {}
    leg_order: list[int] = []
    for source, burned in route_pairs:
        name = Path(source).name
        if name == tuning.INTRO_OUTPUT_FILENAME:
            intro_pair = (source, burned)
        elif name == _OVERVIEW_FILENAME:
            overview_pair = (source, burned)
        else:
            leg_match = _RESIDENTIAL_LEG_RE.search(name)
            leg_num = int(leg_match.group(1)) if leg_match else -1
            if leg_num not in legs_by_number:
                legs_by_number[leg_num] = []
                leg_order.append(leg_num)
            legs_by_number[leg_num].append((source, burned))

    # 0-based waypoint index -> its attraction clip (see _ATTRACTION_RE);
    # unmatched entries fall under key -1 and are still shown, just at the
    # end (right before outro) instead of next to a leg they can't be
    # matched to.
    attractions_by_idx: dict[int, list[tuple[str, str]]] = {}
    unvisited = _unvisited_stopbys(project_dir)
    for source, burned in attraction_pairs:
        match = _ATTRACTION_RE.search(Path(source).name)
        wp_idx = int(match.group(1)) if match else -1
        if wp_idx in unvisited:
            continue  # a passed-only waypoint (unconnected stop-by / skipped) has no attraction video
        attractions_by_idx.setdefault(wp_idx, []).append((source, burned))

    def _leg_audio(source_name: str) -> tuple[Optional[str], Optional[str]]:
        leg_match = _RESIDENTIAL_LEG_RE.search(source_name)
        if not leg_match:
            return None, None
        # 1-based in the filename; audio_paths/subtitle_paths are 0-based.
        idx = int(leg_match.group(1)) - 1
        if not (0 <= idx < len(audio_paths)):
            return None, None
        # A leg cut into multiple pieces (connectToRoute stop-by mid-leg
        # pause) has each piece's own TARGET waypoint's narration resolved
        # by leg_pieces.compute_leg_narration_splits, keyed by that piece's
        # own (possibly narration-padded) stem — source_name here already
        # reflects that padding, since pipeline.py replaces video_paths
        # with the padded result before this function ever sees it.
        split = leg_narration_splits.get(Path(source_name).stem)
        if split and split[0]:
            return split
        audio_path = audio_paths[idx]
        subtitle_path = (
            subtitle_paths[idx]
            if idx < len(subtitle_paths) and subtitle_paths[idx]
            else _find_subtitle(audio_path, subtitles_dir)
        )
        return audio_path, subtitle_path

    def _attraction_audio(source_name: str) -> tuple[Optional[str], Optional[str]]:
        # [NOTE] [Core] Attraction clips index audio/subtitles directly by
        # the waypoint index parsed from the filename (not a running
        # counter), since attraction videos aren't necessarily produced in
        # waypoint order. Reads attraction_audio_paths/
        # attraction_subtitle_paths (the clip's OWN attractionNarration-
        # only audio — see audio_step.generate_attraction_audio_for_waypoint),
        # NOT the combined arrival+attraction audio_paths/subtitle_paths
        # above, which belong to the residential leg's own narration.
        match = _ATTRACTION_RE.search(source_name)
        if not match:
            return None, None
        idx = int(match.group(1))
        if not (idx < len(attraction_audio_paths)) or not attraction_audio_paths[idx]:
            return None, None
        audio_path = attraction_audio_paths[idx]
        subtitle_path = (
            attraction_subtitle_paths[idx]
            if idx < len(attraction_subtitle_paths) and attraction_subtitle_paths[idx]
            else _find_subtitle(audio_path, subtitles_dir)
        )
        return audio_path, subtitle_path

    # Assemble the final ordered (kind, source, burned) sequence: intro,
    # overview, then per leg (in travel order) that leg's own attraction
    # clip followed by the leg itself, then any attraction clips that
    # never matched a leg, then the outro.
    ordered: list[tuple[str, str, str]] = []
    if intro_pair:
        ordered.append(("route", *intro_pair))
    if overview_pair:
        ordered.append(("overview", *overview_pair))

    # Every leg piece is followed by the attraction video of the waypoint it
    # walks TOWARD (its target, from the leg's _pieces.json), so the arrival
    # photo the leg ends on runs straight into that place's own video. A
    # waypoint no leg arrives at (the trip's first one) gets its video before
    # the leg that leaves it; a stop-by merged into a leg, with no piece of
    # its own, gets its video just before that leg.
    waypoint_ids = _waypoint_ids(project_dir)
    placed: set[int] = set()
    arrived: set[int] = set()

    def add_attraction(wp_idx: int) -> None:
        if wp_idx in placed:
            return
        placed.add(wp_idx)
        for pair in attractions_by_idx.get(wp_idx, []):
            ordered.append(("attraction", *pair))

    for leg_num in leg_order:
        start_pos = leg_num - 1
        pieces = legs_by_number[leg_num]
        targets = [_piece_target(source, waypoint_ids) for source, _ in pieces]
        if start_pos not in arrived or all(t is None for t in targets):
            add_attraction(start_pos)
        if targets[-1] is not None:
            # Stop-bys the leg passes without a piece of their own come before
            # it, so the leg is still followed directly by its destination's video.
            for skipped in range(start_pos + 1, targets[-1]):
                if skipped not in targets:  # a piece's own target follows that piece
                    add_attraction(skipped)
        for pair, target in zip(pieces, targets):
            ordered.append(("route", *pair))
            if target is not None:
                arrived.add(target)
                add_attraction(target)

    for wp_idx in attractions_by_idx:
        add_attraction(wp_idx)

    for name, path in trailing_pairs:
        ordered.append(("route", name, path))

    tracks = []
    all_cues = []
    clip_start = 0.0
    for order, (kind, source_or_name, burned) in enumerate(ordered):
        source_name = Path(source_or_name).name
        if kind == "route":
            audio_path, subtitle_path = _leg_audio(source_name)
        elif kind == "overview":
            # No per-clip index to look up (there's exactly one overview
            # clip) — its narration audio is already muxed directly into
            # the video by render_step.py, this is just recorded here for
            # the editor UI, same as every other track's audio_path.
            audio_path, subtitle_path = overview_audio_path, overview_subtitle_path
        else:
            audio_path, subtitle_path = _attraction_audio(source_name)

        # The user's own footage keeps its sound beside the clip when they asked for it.
        extra_audio = None
        if kind == "attraction":
            from services.vdoprocessing.user_videos import original_sound_path

            sidecar = original_sound_path(str(source_or_name))
            extra_audio = _resolve(str(sidecar)) if sidecar.exists() else None

        # Seconds the narration starts into the clip (a leg's opening
        # before the walker moves) - applied at export; 0 otherwise.
        audio_offset = read_audio_offset(source_or_name) if audio_path and kind == "route" else 0.0
        length = _clip_length(burned, audio_path, audio_offset)
        # Cues relative to the clip (narration offset applied), not burned in.
        clip_cues = []
        for cue in _read_srt(subtitle_path):
            start = min(cue["start"] + audio_offset, length)
            end = min(cue["end"] + audio_offset, length)
            if end - start >= 0.05:
                clip_cues.append({"start": round(start, 3), "end": round(end, 3), "text": cue["text"]})
        all_cues.extend(
            {"start": round(clip_start + c["start"], 3), "end": round(clip_start + c["end"], 3), "text": c["text"]}
            for c in clip_cues
        )
        clip_start += length

        tracks.append(
            {
                "order": order,
                "extra_audio_path": extra_audio,
                "extra_audio_volume": 0.5 if extra_audio else None,
                "clip_name": Path(burned).stem,
                "file_path": _resolve(burned),
                "audio_path": _resolve(audio_path),
                "audio_offset": audio_offset,
                "subtitle_path": _resolve(subtitle_path),
                "subtitles": clip_cues,
            }
        )

    # A leg ends on its destination's fullscreen arrival photo and the
    # destination's own attraction video comes right after it: dissolve
    # between them (VideoExporter.concat_from_timeline) instead of cutting from
    # a frozen photo. Only leg -> attraction joins; never the intro or overview.
    if attraction_fade_seconds > 0:
        for k in range(len(tracks) - 1):
            kind, source, _ = ordered[k]
            if (
                kind == "route"
                and ordered[k + 1][0] == "attraction"
                and Path(source).name != tuning.INTRO_OUTPUT_FILENAME
            ):
                tracks[k]["fade_into_next_seconds"] = attraction_fade_seconds

    # Whole-video cues for the editor/exporter. Never burned from here: clips are
    # already burned when settings.burn_subtitles is on, so this stays off.
    timeline_data = {
        "total_duration_seconds": round(clip_start, 3),
        "video_tracks": tracks,
        "subtitles": all_cues,
        "burn_subtitles": False,
    }

    output_path = Path(timeline_path) if timeline_path else Path(project_dir) / "timeline.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(timeline_data, f, indent=2, ensure_ascii=False)

    logger.info("Step 6 complete: timeline written to %s (%d clip(s)).", output_path, len(tracks))
    return str(output_path)
