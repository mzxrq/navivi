"""Step 6: Assemble timeline.json — the final clip order (video + audio + subtitles)."""

import json
import re
from pathlib import Path
from typing import Optional, Union

from services.vdoprocessing.cliptiming import read_audio_offset

from .helpers import logger, project_subtitle_dir
from services import tuning
from services.projectfiles import write_json_atomic

# [NOTE] [Core] Waypoint index embedded in attraction clip filenames, e.g. "04_attraction_03_Kabutoyama.mp4" -> waypoint index 3 (matches attraction_step.py's `f"04_attraction_{idx:02d}_{safe_label}.mp4"`).
_ATTRACTION_RE = re.compile(r"04_attraction_(\d+)_")
# Residential-leg clip's embedded 1-based departure-waypoint RAW position
# (matches waypoints.py's chunk_filename and render_step.py's own
# RESIDENTIAL_LEG_RE) — used to look up that leg's narration by position
# instead of a blind per-clip counter, which stop-by leg-merging (a leg can
# skip over a merged-away stop-by) would otherwise throw out of sync with
# audio_paths/subtitle_paths.
from .leg_pieces import _RESIDENTIAL_LEG_RE  # noqa: E402
# Overview clip's fixed filename — hardcoded the same way in
# route2vdo.py/overview.py (no shared tuning.py constant for it).
_OVERVIEW_FILENAME = "01_overview.mp4"


def _read_waypoints(project_dir: str) -> list:
    try:
        with open(Path(project_dir) / "job_config.json", "r", encoding="utf-8") as f:
            return json.load(f).get("waypoints", [])
    except (OSError, json.JSONDecodeError):
        return []


def _unvisited_stopbys(waypoints: list) -> set:
    """0-based positions of waypoints the walker only passes (unconnected
    stop-bys, and waypoints skipped in video export) and return stops (their leg ends on a photo card): no
    attraction clip."""
    from .audio_step import no_attraction
    from .render_look import _is_return_stop

    return {pos for pos, wp in enumerate(waypoints) if no_attraction(wp) or _is_return_stop(waypoints, pos)}


def _waypoint_ids(project_dir: str, waypoints: Optional[list] = None) -> dict:
    """{waypoint id: 0-based position}, from `waypoints` or else the project's job_config.json."""
    waypoints = _read_waypoints(project_dir) if waypoints is None else waypoints
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
    """Clip length as the editor and exporter lay it out: video, held for the narration and the
    exporter's AUDIO_END_HOLD_SECONDS after it (each track's `duration`, which the export then uses as is)."""
    narration = audio_offset + _duration(audio) + tuning.AUDIO_END_HOLD_SECONDS if audio else 0.0
    return max(_MIN_SEGMENT, _duration(video), narration)


def _group_route_clips(route_pairs: list) -> tuple:
    """The route clips sorted into the intro, the overview, and the legs (by leg number, in order of appearance).

    Returns (intro pair, overview pair, {leg number: [(source, burned)]}, leg numbers in order).
    """
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
    return intro_pair, overview_pair, legs_by_number, leg_order


def _attractions_by_waypoint(attraction_pairs: list, unvisited: set) -> dict:
    """0-based waypoint index -> its attraction clips (see _ATTRACTION_RE).

    Unmatched entries fall under key -1 and are still shown, just at the
    end (right before outro) instead of next to a leg they can't be
    matched to.
    """
    attractions_by_idx: dict[int, list[tuple[str, str]]] = {}
    for source, burned in attraction_pairs:
        match = _ATTRACTION_RE.search(Path(source).name)
        wp_idx = int(match.group(1)) if match else -1
        if wp_idx in unvisited:
            continue  # a passed-only waypoint (unconnected stop-by / skipped) has no attraction video
        attractions_by_idx.setdefault(wp_idx, []).append((source, burned))
    return attractions_by_idx


def _order_clips(
    intro_pair, overview_pair, leg_order: list, legs_by_number: dict, attractions_by_idx: dict,
    trailing_pairs: list, waypoint_ids,
) -> list:
    """The final ordered (kind, source, burned) sequence: intro, overview, then per leg (in
    travel order) that leg's own attraction clip followed by the leg itself, then any
    attraction clips that never matched a leg, then the outro.

    Every leg piece is followed by the attraction video of the waypoint it
    walks TOWARD (its target, from the leg's _pieces.json), so the arrival
    photo the leg ends on runs straight into that place's own video. A
    waypoint no leg arrives at (the trip's first one) gets its video before
    the leg that leaves it; a stop-by merged into a leg, with no piece of
    its own, gets its video just before that leg.
    """
    ordered: list[tuple[str, str, str]] = []
    if intro_pair:
        ordered.append(("route", *intro_pair))
    if overview_pair:
        ordered.append(("overview", *overview_pair))

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
        # start_pos -1: the separate start point's leg, which has no attraction (key -1 holds unmatched clips).
        if start_pos >= 0 and (start_pos not in arrived or all(t is None for t in targets)):
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

    for _name, path in trailing_pairs:
        # The full path, so the finale's timing sidecar (voice start) is found beside it.
        ordered.append(("route", path, path))
    return ordered


class _ClipAudio:
    """Finds the narration audio and subtitle file that belong to a clip, from its file name."""

    def __init__(
        self, audio_paths: list, subtitle_paths: list, attraction_audio_paths: list,
        attraction_subtitle_paths: list, leg_narration_splits: dict, subtitles_dir,
    ):
        self.audio_paths = audio_paths
        self.subtitle_paths = subtitle_paths
        self.attraction_audio_paths = attraction_audio_paths
        self.attraction_subtitle_paths = attraction_subtitle_paths
        self.leg_narration_splits = leg_narration_splits
        self.subtitles_dir = subtitles_dir

    def for_leg(self, source_name: str) -> tuple[Optional[str], Optional[str]]:
        leg_match = _RESIDENTIAL_LEG_RE.search(source_name)
        if not leg_match:
            return None, None
        # 1-based in the filename; audio_paths/subtitle_paths are 0-based (00 = the separate start point's leg).
        idx = int(leg_match.group(1)) - 1
        # A leg cut into multiple pieces (connectToRoute stop-by mid-leg
        # pause) has each piece's own TARGET waypoint's narration resolved
        # by leg_pieces.compute_leg_narration_splits, keyed by that piece's
        # own (possibly narration-padded) stem — source_name here already
        # reflects that padding, since pipeline.py replaces video_paths
        # with the padded result before this function ever sees it.
        split = self.leg_narration_splits.get(Path(source_name).stem)
        if split is not None:
            return split
        if not (0 <= idx < len(self.audio_paths)):
            return None, None
        audio_path = self.audio_paths[idx]
        subtitle_path = (
            self.subtitle_paths[idx]
            if idx < len(self.subtitle_paths) and self.subtitle_paths[idx]
            else _find_subtitle(audio_path, self.subtitles_dir)
        )
        return audio_path, subtitle_path

    def for_attraction(self, source_name: str) -> tuple[Optional[str], Optional[str]]:
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
        if not (idx < len(self.attraction_audio_paths)) or not self.attraction_audio_paths[idx]:
            return None, None
        audio_path = self.attraction_audio_paths[idx]
        subtitle_path = (
            self.attraction_subtitle_paths[idx]
            if idx < len(self.attraction_subtitle_paths) and self.attraction_subtitle_paths[idx]
            else _find_subtitle(audio_path, self.subtitles_dir)
        )
        return audio_path, subtitle_path


def _voice_over_intro_cues(overview_subtitle_path: Optional[str], overview_voice_start: float, intro_pair) -> dict:
    """The overview voice starting on the intro (`overview_voice_start` seconds in): its captions go on
    whichever of the two clips they fall in (one across the cut is split in two)."""
    intro_len = _clip_length(intro_pair[1], None, 0.0)
    voice_cues: dict = {"intro": [], "overview": []}
    for cue in _read_srt(overview_subtitle_path):
        start, end = cue["start"] + overview_voice_start, cue["end"] + overview_voice_start
        if start < intro_len:
            voice_cues["intro"].append({**cue, "start": start, "end": min(end, intro_len)})
        if end > intro_len:
            voice_cues["overview"].append(
                {**cue, "start": max(start, intro_len) - intro_len, "end": end - intro_len}
            )
    return voice_cues


def _cues_within_clip(source_cues: list, audio_offset: float, length: float) -> list:
    """Cues relative to the clip (narration offset applied), not burned in."""
    clip_cues = []
    for cue in source_cues:
        start = min(cue["start"] + audio_offset, length)
        end = min(cue["end"] + audio_offset, length)
        if end - start >= 0.05:
            clip_cues.append({"start": round(start, 3), "end": round(end, 3), "text": cue["text"]})
    return clip_cues


class _TrackBuilder:
    """Builds one timeline track (clip, its narration, captions and text items) from an ordered clip."""

    def __init__(
        self, project_dir: str, subtitles_dir, audio: _ClipAudio, run_waypoints: list, intro_pair, overview_pair,
        overview_audio_path: Optional[str], overview_subtitle_path: Optional[str], intro_audio_path: Optional[str],
        intro_subtitle_path: Optional[str], overview_audio_offset: float, overview_voice_start: Optional[float],
        intro_text, outro_text, place_label_look, photo_credit_look,
    ):
        self.project_dir = project_dir
        self.subtitles_dir = subtitles_dir
        self.audio = audio
        self.run_waypoints = run_waypoints
        self.intro_pair = intro_pair
        self.overview_audio_path = overview_audio_path
        self.overview_subtitle_path = overview_subtitle_path
        self.intro_audio_path = intro_audio_path
        self.intro_subtitle_path = intro_subtitle_path
        self.overview_audio_offset = overview_audio_offset
        self.overview_voice_start = overview_voice_start
        self.intro_text = intro_text
        self.outro_text = outro_text
        self.place_label_look = place_label_look
        self.photo_credit_look = photo_credit_look
        # The overview voice starting on the intro (overview_voice_start seconds in): it is placed at that
        # timeline time, and its captions go on whichever of the two clips they fall in.
        self.voice_over_intro = bool(
            overview_voice_start is not None and intro_pair and overview_pair and overview_audio_path
        )
        self.voice_cues = (
            _voice_over_intro_cues(overview_subtitle_path, overview_voice_start, intro_pair)
            if self.voice_over_intro else {}
        )

    def _finale_audio(self, source_or_name: str) -> tuple[Optional[str], Optional[str]]:
        """The finale's narration (settings.finale_narration), when the clip was made with it (a timing sidecar)."""
        from services.vdoprocessing.cliptiming import timing_sidecar_path

        from .audio_step import FINALE_NARRATION_FILENAME
        from .helpers import project_audio_dir

        voice = Path(project_audio_dir(self.project_dir)) / FINALE_NARRATION_FILENAME
        voiced = voice.exists() and Path(timing_sidecar_path(str(source_or_name))).exists()
        srt = Path(self.subtitles_dir) / f"{voice.stem}.srt"
        return (str(voice) if voiced else None, str(srt) if voiced and srt.exists() else None)

    def _audio_for(self, kind: str, source_name: str, source_or_name: str) -> tuple[Optional[str], Optional[str]]:
        if source_name == tuning.FINALE_OUTPUT_FILENAME:
            return self._finale_audio(source_or_name)
        if kind == "route":
            return self.audio.for_leg(source_name)
        if kind == "overview":
            # No per-clip index to look up (there's exactly one overview
            # clip) — its narration audio is already muxed directly into
            # the video by render_step.py, this is just recorded here for
            # the editor UI, same as every other track's audio_path.
            return self.overview_audio_path, self.overview_subtitle_path
        return self.audio.for_attraction(source_name)

    @staticmethod
    def _footage_sound(kind: str, source_or_name: str) -> Optional[str]:
        """The user's own footage keeps its sound beside the clip when they asked for it."""
        if kind != "attraction":
            return None
        from services.vdoprocessing.user_videos import original_sound_path

        sidecar = original_sound_path(str(source_or_name))
        return _resolve(str(sidecar)) if sidecar.exists() else None

    def _outro_title_item(self, length: float, has_previous: bool) -> dict:
        """The outro's title rides on the text track, until its logo end card starts."""
        outro_text = self.outro_text
        shown = {k: v for k, v in outro_text.items() if k != "trim_end"}
        end = max(0.5, length - float(outro_text.get("trim_end") or 0.0))
        # Starts with the outro, its box fading in with the dissolve (below) instead of popping up over the
        # previous clip's held last frame; as the last cards go under it, it wipes away top -> bottom.
        if has_previous and isinstance(shown.get("box"), dict):
            shown["box"] = {**shown["box"], "fade_in": tuning.ENDING_FADE_SECONDS}
        if not shown.get("burned_in"):  # a burned-in title (scrapbook) goes under the logo doors with the video
            shown["wipe_out"] = min(tuning.OUTRO_TITLE_WIPE_SECONDS, end / 2)
        return {"start": 0.0, "end": round(end, 3), **shown}

    def _attraction_text_items(self, source_or_name: str, source_name: str, length: float, audio_path: Optional[str]) -> list:
        """An attraction's place name (when its clip was finalized without it) and its photo credits."""
        from services.vdoprocessing.place_label import place_text_item, unburned_place_label

        items = []
        place = unburned_place_label(source_or_name)
        if place:
            items.append({"start": 0.0, "end": round(length, 3), **place_text_item(place, self.place_label_look)})
        from services.vdoprocessing.photo_credit import credit_items

        match = _ATTRACTION_RE.search(source_name)
        if match and int(match.group(1)) < len(self.run_waypoints):
            from .audio_step import read_photo_cuts

            cuts = read_photo_cuts(audio_path) if audio_path else None
            items.extend(credit_items(self.run_waypoints[int(match.group(1))], length, self.photo_credit_look, cuts))
        return items

    def _text_items(
        self, kind: str, source_or_name: str, source_name: str, length: float, audio_path: Optional[str],
        is_intro: bool, has_previous: bool,
    ) -> list:
        clip_texts = []
        # The intro's text items ride on the text track: over the whole intro unless an item has its own times.
        if self.intro_text and is_intro:
            for item in self.intro_text if isinstance(self.intro_text, list) else [self.intro_text]:
                clip_texts.append({"start": 0.0, **item, "end": round(min(float(item.get("end", length)), length), 3)})
        if self.outro_text and source_name == tuning.OUTRO_OUTPUT_FILENAME:
            clip_texts.append(self._outro_title_item(length, has_previous))
        if kind == "attraction":
            clip_texts.extend(self._attraction_text_items(source_or_name, source_name, length, audio_path))
        return clip_texts

    def track(
        self, order: int, kind: str, source_or_name: str, burned: str, has_previous: bool
    ) -> tuple[dict, list, list, float]:
        """(the track, its cues and text items relative to the clip, the clip's length in seconds)."""
        source_name = Path(source_or_name).name
        is_intro = source_name == tuning.INTRO_OUTPUT_FILENAME
        audio_path, subtitle_path = self._audio_for(kind, source_name, source_or_name)

        # The user's own footage keeps its sound beside the clip when they asked for it.
        extra_audio, extra_volume = self._footage_sound(kind, source_or_name), 0.5

        # Seconds the narration starts into the clip (a leg's opening
        # before the walker moves) - applied at export; 0 otherwise.
        audio_offset = read_audio_offset(source_or_name) if audio_path and kind == "route" else 0.0
        # The opening narration's own file plays on the intro; the overview's own voice starts a little in.
        if is_intro and self.intro_audio_path:
            audio_path, subtitle_path = self.intro_audio_path, self.intro_subtitle_path
            audio_offset = tuning.INTRO_VOICE_LEAD_SECONDS
        elif kind == "overview" and audio_path and self.overview_audio_offset:
            audio_offset = self.overview_audio_offset
            if self.intro_audio_path and not self.intro_pair:  # no intro clip: the opening plays at the overview's start
                extra_audio, extra_volume = _resolve(self.intro_audio_path), 1.0
        free_voice = self.voice_over_intro and kind == "overview"
        length = _clip_length(burned, None if free_voice else audio_path, audio_offset)
        if self.voice_over_intro and (is_intro or free_voice):
            source_cues = self.voice_cues["intro" if is_intro else "overview"]
        else:
            source_cues = _read_srt(subtitle_path)
        clip_cues = _cues_within_clip(source_cues, audio_offset, length)
        clip_texts = self._text_items(kind, source_or_name, source_name, length, audio_path, is_intro, has_previous)

        track = {
            "order": order,
            "extra_audio_path": extra_audio,
            "extra_audio_volume": extra_volume if extra_audio else None,
            "clip_name": Path(burned).stem,
            "file_path": _resolve(burned),
            "duration": round(length, 3),
            "audio_path": _resolve(audio_path),
            "audio_offset": audio_offset,
            "subtitle_path": _resolve(subtitle_path),
            "subtitles": clip_cues,
            **({"texts": clip_texts} if clip_texts else {}),
            # Timeline seconds the narration starts at, wherever the clip is
            # (render_from_timeline mixes it in as unlinked_audio).
            **({"audio_start": round(self.overview_voice_start, 3)} if free_voice else {}),
        }
        return track, clip_cues, clip_texts, length


def _apply_fades(tracks: list, ordered: list, attraction_fade_seconds: float) -> None:
    """Sets `fade_into_next_seconds` where a clip dissolves into the next one."""
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
            # Two legs joined at a return stop share their camera there (pedestrian.py `end_view_path`):
            # the dissolve only swaps the route lines and cards over the same map.
            leg = _RESIDENTIAL_LEG_RE.search(Path(source).name)
            if (
                kind == "route" and ordered[k + 1][0] == "route" and leg
                and (Path(source).parent / f"{leg.group(0)}endview.json").exists()
                and not (Path(source).parent / f"{leg.group(0)}nofade").exists()
            ):
                tracks[k]["fade_into_next_seconds"] = attraction_fade_seconds
    # The goodbye dissolves into the outro card instead of cutting to it.
    # (The finale, already a pull-back to the whole route, cuts to it.)
    if (len(ordered) > 1 and Path(ordered[-1][2]).name == tuning.OUTRO_OUTPUT_FILENAME
            and Path(ordered[-2][2]).name != tuning.FINALE_OUTPUT_FILENAME):
        tracks[-2]["fade_into_next_seconds"] = tuning.ENDING_FADE_SECONDS


def _lay_out_tracks(builder: "_TrackBuilder", ordered: list) -> tuple:
    """(tracks, whole-video cues, whole-video texts, total seconds): each clip's cues and texts shifted to its start."""
    tracks, all_cues, all_texts = [], [], []
    clip_start = 0.0
    for order, (kind, source_or_name, burned) in enumerate(ordered):
        track, clip_cues, clip_texts, length = builder.track(order, kind, source_or_name, burned, bool(tracks))
        all_cues.extend(
            {"start": round(clip_start + c["start"], 3), "end": round(clip_start + c["end"], 3), "text": c["text"]}
            for c in clip_cues
        )
        all_texts.extend(
            {**x, "start": round(clip_start + x["start"], 3), "end": round(clip_start + x["end"], 3)}
            for x in clip_texts
        )
        clip_start += length
        tracks.append(track)
    return tracks, all_cues, all_texts, clip_start


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
    intro_text: Optional[Union[dict, list]] = None,
    outro_text: Optional[dict] = None,
    place_label_look: Optional[dict] = None,
    photo_credit_look: Optional[dict] = None,
    overview_voice_start: Optional[float] = None,
    intro_audio_path: Optional[str] = None,
    intro_subtitle_path: Optional[str] = None,
    overview_audio_offset: float = 0.0,
    waypoints: Optional[list] = None,
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
    subtitles_dir = project_subtitle_dir(project_dir)
    audio = _ClipAudio(
        audio_paths or [], subtitle_paths or [], attraction_audio_paths or [],
        attraction_subtitle_paths or [], leg_narration_splits or {}, subtitles_dir,
    )

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

    intro_pair, overview_pair, legs_by_number, leg_order = _group_route_clips(route_pairs)

    # The waypoints the run started with (fix.md #4): job_config.json may have been edited during the render.
    run_waypoints = _read_waypoints(project_dir) if waypoints is None else waypoints
    attractions_by_idx = _attractions_by_waypoint(attraction_pairs, _unvisited_stopbys(run_waypoints))
    ordered = _order_clips(
        intro_pair, overview_pair, leg_order, legs_by_number, attractions_by_idx, trailing_pairs,
        _waypoint_ids(project_dir, run_waypoints),
    )

    builder = _TrackBuilder(
        project_dir, subtitles_dir, audio, run_waypoints, intro_pair, overview_pair, overview_audio_path,
        overview_subtitle_path, intro_audio_path, intro_subtitle_path, overview_audio_offset,
        overview_voice_start, intro_text, outro_text, place_label_look, photo_credit_look,
    )
    tracks, all_cues, all_texts, clip_start = _lay_out_tracks(builder, ordered)
    _apply_fades(tracks, ordered, attraction_fade_seconds)

    # Whole-video cues for the editor/exporter, burned at export (render_timeline).
    timeline_data = {
        "total_duration_seconds": round(clip_start, 3),
        "video_tracks": tracks,
        "subtitles": all_cues,
        "texts": all_texts,
        "burn_subtitles": True,
    }

    output_path = Path(timeline_path) if timeline_path else Path(project_dir) / "timeline.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(output_path, timeline_data)

    logger.info("Step 6 complete: timeline written to %s (%d clip(s)).", output_path, len(tracks))
    return str(output_path)


