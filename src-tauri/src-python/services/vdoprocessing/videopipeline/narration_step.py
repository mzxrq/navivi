"""Narration timing cues, and the walk length they decide.

Audio is the priority: how long a leg's narration is, and where its cues fall,
decide how long the walk is, so the walker speeds up or slows down to match
the voice (render_step -> pydeckrecorder.pedestrian).

A script with no cue tags gets the project's usual placement (`cued_script`).
The tagged text is stored next to job_config.json, which is never edited, and
after TTS the second each cue is spoken is recorded from the real audio
(`record_cue_times`). `leg_walk_plan` turns those into the walk's length.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Optional

from services.localization.cues import cue_tags, cue_times, strip_cues

from .audio_step import OVERVIEW_CUE_KEY, base_narration_script, raw_narration_script, waypoint_cue_key

_STORE_NAME = ".narration_cues.json"
_SENTENCE_END = re.compile(r"(?<=[。！？!?\n])")

# How much of the narration is left to speak after the walker arrives. 0: the
# voice ends as the walker reaches the destination, and all that follows is the
# quick arrival photo transition. Used when the script has no {end} cue.
TAIL_SECONDS = 0.0

# The walker may reach the destination up to this many seconds before the voice
# ends (it waits there), no more: a walk that would arrive earlier is slowed
# down so the wait never exceeds it. settings.max_early_arrival_seconds.
MAX_EARLY_ARRIVAL_SECONDS = 3.0
MIN_WALK_SECONDS = 4.0


def _sentences(text: str) -> list[str]:
    return [s for s in (p.strip() for p in _SENTENCE_END.split(text or "")) if s]


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class CueStore:
    """<project>/.narration_cues.json: per waypoint, the cued script (made from
    a given base script) and the cue times measured from its audio."""

    def __init__(self, project_dir):
        self.path = Path(project_dir) / _STORE_NAME
        try:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._data = {}

    def cued_text(self, key: str, base: str) -> Optional[str]:
        """The stored cued script for `key` if it was made from this exact base."""
        entry = self._data.get(key)
        return entry.get("text") if entry and entry.get("base") == _hash(base) else None

    def put_text(self, key: str, base: str, text: str) -> None:
        self._data[key] = {"base": _hash(base), "text": text}

    def cue_times_for(self, key: str) -> dict:
        return dict(self._data.get(key, {}).get("cue_times", {}))

    def set_cue_times(self, key: str, times: dict) -> None:
        self._data.setdefault(key, {})["cue_times"] = {t: round(v, 2) for t, v in times.items()}

    def save(self) -> None:
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")


def cued_script(waypoint: dict) -> Optional[str]:
    """The waypoint's narration with timing cues. The user's own tags win; a
    script with none gets: {start} once the arriving line has set the scene
    (the walk begins), {arrive} where the attraction text begins ("we are
    nearly there") and {end} after its first sentence (the stop is reached)."""
    base = base_narration_script(waypoint)
    if not base or cue_tags(base):
        return base
    arriving = (waypoint.get("arrivingNarration") or "").strip()
    attraction = (waypoint.get("attractionNarration") or waypoint.get("narration") or "").strip()
    if not arriving and not attraction:
        return base
    arriving_sentences = _sentences(arriving)
    out = arriving_sentences[0] if arriving_sentences else ""
    if len(arriving_sentences) >= 2:
        out += "{start}" + "".join(arriving_sentences[1:])
    attraction_sentences = _sentences(attraction)
    if attraction_sentences:
        out += "{arrive}" + attraction_sentences[0] + "{end}" + "".join(attraction_sentences[1:])
    return out if cue_tags(out) else base


def add_default_cues(project_config_path: str) -> int:
    """Stores a cued version of every waypoint narration that has none yet.
    Tags never change what is spoken, so audio already made stays valid.
    Returns how many were added. Opt-in: settings.auto_narration_cues=true."""
    config_path = Path(project_config_path)
    project = json.loads(config_path.read_text(encoding="utf-8"))
    if not project.get("settings", {}).get("auto_narration_cues", False):
        return 0
    store = CueStore(config_path.parent)
    added = 0
    for pos, wp in enumerate(project.get("waypoints", [])):
        base = base_narration_script(wp) if isinstance(wp, dict) else None
        if not base:
            continue
        key = waypoint_cue_key(wp, pos)
        if store.cued_text(key, base):
            continue
        cued = cued_script(wp)
        if cued and cued != base:
            store.put_text(key, base, cued)
            added += 1
    if added:
        store.save()
    return added


def add_overview_cues(project_config_path: str) -> bool:
    """Stores the overview narration with {n} / {go} tags placed (see
    localization/overview_cues.py), so the walker stops at each waypoint while
    the voice describes it. Words are never changed, so audio already made
    stays valid; the user's own tags win. On by default (tuning.DEFAULT_AUTO_OVERVIEW_CUES);
    settings.auto_overview_cues=false turns it off.
    Returns whether a new tagged version was stored."""
    from services.localization.overview_cues import auto_tag_overview
    from services.localization.overview_script import visible_waypoints

    config_path = Path(project_config_path)
    project = json.loads(config_path.read_text(encoding="utf-8"))
    from services import tuning

    if not project.get("settings", {}).get("auto_overview_cues", tuning.DEFAULT_AUTO_OVERVIEW_CUES):
        return False
    base = project.get("overview_narration") or ""
    store = CueStore(config_path.parent)
    if not base.strip() or store.cued_text(OVERVIEW_CUE_KEY, base):
        return False
    labels = [w.get("label") or w.get("name") or "" for w in visible_waypoints(project)]
    tagged = auto_tag_overview(base, labels)
    if not tagged or tagged == base:
        return False
    store.put_text(OVERVIEW_CUE_KEY, base, tagged)
    store.save()
    return True


def record_cue_times(project_config_path: str, audio_data: dict) -> None:
    """Stores, per waypoint, the second of its narration audio at which each
    cue tag is spoken."""
    from .audio_step import apply_cued_scripts

    config_path = Path(project_config_path)
    waypoints = json.loads(config_path.read_text(encoding="utf-8")).get("waypoints", [])
    apply_cued_scripts(waypoints, config_path.parent)
    store = CueStore(config_path.parent)
    durations = audio_data.get("audio_durations") or []
    pauses = audio_data.get("audio_pauses") or []
    for pos, wp in enumerate(waypoints):
        if not isinstance(wp, dict) or pos >= len(durations) or not durations[pos]:
            continue
        clean, cues = strip_cues(raw_narration_script(wp))
        if cues:
            store.set_cue_times(
                waypoint_cue_key(wp, pos),
                cue_times(cues, clean, durations[pos], pauses[pos] if pos < len(pauses) else []),
            )
    store.save()


def leg_walk_plan(
    store: CueStore,
    waypoint: dict,
    pos: int,
    audio_seconds: float,
    natural_seconds: Optional[float] = None,
    use_cues: bool = True,
    max_wait_seconds: float = MAX_EARLY_ARRIVAL_SECONDS,
    ignore_start: bool = False,
) -> Optional[tuple[float, Optional[float], float]]:
    """(walk seconds, {start} cue seconds or None, wait seconds) for the leg
    that ends at waypoint `pos`, from its narration's real length and cues;
    None when there is no narration to follow.

    The script says WHEN the walker has to be there: its {end} cue (or, if it
    has none, {arrive}) marks the moment the destination is reached - "at this
    moment it should already have arrived". With no such cue the deadline is
    the end of the voice. The walker never arrives after the deadline; it may
    arrive early, by at most `max_wait_seconds` (a faster natural pace is
    slowed down to that, a slower one sped up to the deadline). After arriving
    it waits (`wait`) until the voice is done, and only then does the
    fullscreen photo transition start.

    {start}: the voice starts with the walk, so times are counted from it
    (`ignore_start` for a piece that does not begin with the leg's opening).
    The voice is delayed by the clip's opening (see pydeckrecorder.pedestrian).
    `use_cues` False: cues are ignored, only the audio's length counts."""
    if not audio_seconds or audio_seconds <= 0:
        return None
    cues = store.cue_times_for(waypoint_cue_key(waypoint, pos)) if use_cues else {}
    start = None if ignore_start else cues.get("start")
    origin = start or 0.0
    voice = max(MIN_WALK_SECONDS, audio_seconds - origin - TAIL_SECONDS)  # voice length from the walk's start
    mark = cues.get("end") if cues.get("end") is not None else cues.get("arrive")
    deadline = voice if mark is None or mark <= origin else max(MIN_WALK_SECONDS, min(voice, mark - origin))
    if natural_seconds is None:
        walk = deadline
    else:
        walk = max(MIN_WALK_SECONDS, min(deadline, max(natural_seconds, deadline - max_wait_seconds)))
    return walk, start, max(0.0, voice - walk)
