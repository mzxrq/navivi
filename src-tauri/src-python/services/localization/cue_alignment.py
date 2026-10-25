"""Cue times measured from the voice, not guessed from the script.

cues.cue_times spreads the speaking time over the characters, which is up to
~5 s off by the end of an 80 s overview (numbers, names and pauses are not read
at an even rate), so the walker stopped at stops before the voice named them.
Here a speech recogniser (the one that checks place names, on the CPU) listens
to the take, the script and what it heard are both turned into kana, and the
two are lined up; each cue gets the time of the sentence the voice says there.
Anything that does not work - no recogniser, a poor match - leaves the estimate.
"""

from __future__ import annotations

import difflib
import io
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from services import tuning
from services.localization import japanese_words
from services.localization.cues import Cue, cue_times
from services.logger.logger import setup_logger

logger = setup_logger("CueAlign")

# The alignment is dropped (estimate kept) when fewer script characters than this share match.
MIN_MATCH_SHARE = 0.45
# A measured cue this far from its estimate is not trusted (the recogniser lost its place).
MAX_DRIFT_SECONDS = 9.0
# A cue at a sentence start moves to the start of a heard segment this near.
SNAP_SEGMENT_SECONDS = 2.0


def _reading_with_origin(text: str) -> Tuple[str, List[int]]:
    """`text` as plain kana, and for each kana the index of the character it was read from."""
    from services.tts.name_check import _plain

    reading, origin = "", []
    tagger = japanese_words._tagger()
    if tagger is None:
        for i, ch in enumerate(text):
            for c in _plain(japanese_words._kakasi_reading(ch) if ch.strip() else ""):
                reading += c
                origin.append(i)
        return reading, origin
    at = 0
    for token in tagger(text):
        found = text.find(token.surface, at)
        start = found if found >= 0 else at
        at = start + len(token.surface)
        kana = getattr(token.feature, "kana", None)
        for c in _plain(kana if kana and kana != "*" else token.surface):
            reading += c
            origin.append(start)
    return reading, origin


def _segments(audio_path: Path) -> Optional[List[Tuple[float, float, str]]]:
    """What the recogniser heard, [(start, end, text)], kept beside the audio (the take is unchanged)."""
    stamp = f"{audio_path.stat().st_size}:{audio_path.stat().st_mtime_ns}"
    cache = Path(str(audio_path) + ".heard.json")
    try:
        saved = json.loads(cache.read_text(encoding="utf-8"))
        if saved.get("stamp") == stamp:
            return [tuple(s) for s in saved["segments"]]
    except (OSError, ValueError, KeyError):
        pass
    from services.tts import name_check

    model = name_check._model()
    if model is None:
        return None
    # Word timestamps crash ctranslate2 here; sentence-sized segments are enough.
    heard, _ = model.transcribe(
        io.BytesIO(audio_path.read_bytes()), language="ja", beam_size=1, chunk_length=15,
        condition_on_previous_text=False,
    )
    segments = [(float(s.start), float(s.end), s.text) for s in heard]
    try:
        cache.write_text(json.dumps({"stamp": stamp, "segments": segments}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return segments


def align_cue_times(clean: str, cues: List[Cue], segments: List[Tuple[float, float, str]]) -> Optional[Dict[str, float]]:
    """Seconds into the take at which each cue's text is said, or None when the
    heard text does not match the script well enough."""
    heard, stamp = "", []
    for start, end, text in segments:
        part, _ = _reading_with_origin(text)
        for i, c in enumerate(part):
            heard += c
            stamp.append(start + (end - start) * i / max(1, len(part)))
    script, origin = _reading_with_origin(clean)
    if not script or not heard:
        return None
    blocks = [b for b in difflib.SequenceMatcher(None, script, heard, autojunk=False).get_matching_blocks() if b.size]
    if sum(b.size for b in blocks) / len(script) < MIN_MATCH_SHARE:
        return None
    # (script character index, seconds) at the start and end of every matched run.
    anchors: List[Tuple[int, float]] = []
    for b in blocks:
        anchors.append((origin[b.a], stamp[b.b]))
        anchors.append((origin[b.a + b.size - 1], stamp[b.b + b.size - 1]))

    def seconds_at(char_index: int) -> float:
        before = [a for a in anchors if a[0] <= char_index]
        after = [a for a in anchors if a[0] >= char_index]
        lo = before[-1] if before else None
        hi = after[0] if after else None
        if lo and hi and hi[0] != lo[0]:
            return lo[1] + (hi[1] - lo[1]) * (char_index - lo[0]) / (hi[0] - lo[0])
        return (lo or hi)[1]

    times: Dict[str, float] = {}
    last = 0.0
    for cue in cues:
        last = max(last, seconds_at(cue.char_index))
        times.setdefault(cue.tag, last)
    return times


_SENTENCE_END = re.compile("[。！？!?\n]")
_COMMA = re.compile("[、，,]")


def measured_cue_times(
    audio_path, cues: List[Cue], clean: str, duration: float, pauses: Optional[List[Dict[str, float]]] = None,
    enabled: bool = True,
) -> Dict[str, float]:
    """cues.cue_times, corrected by listening to the take (see the module docstring)."""
    estimate = cue_times(cues, clean, duration, pauses)
    if not cues or not enabled or not tuning.ALIGN_CUES_TO_VOICE or not audio_path:
        return estimate
    try:
        segments = _segments(Path(audio_path))
        measured = align_cue_times(clean, cues, segments) if segments else None
    except Exception as exc:  # a broken recogniser must never stop the narration
        logger.warning("Cue times kept as estimates (could not listen to the take): %s", exc)
        return estimate
    if not measured:
        return estimate
    from services.localization.cues import _snap_to_pause_end

    out: Dict[str, float] = {}
    last = 0.0
    for cue in cues:
        if cue.tag in out:
            continue
        seconds = measured[cue.tag]
        if abs(seconds - estimate.get(cue.tag, seconds)) > MAX_DRIFT_SECONDS:
            seconds = estimate[cue.tag]
        # A line break inside a sentence (「近鉄御所駅と⏎吉祥草寺へ」) is not a sentence start: {9} snapped 3 s late to the next one.
        elif cue.char_index == 0 or _SENTENCE_END.match(clean[: cue.char_index].rstrip()[-1:] or "。"):
            # A sentence starts where a heard segment starts, when one is near.
            starts = [st for st, _e, _t in segments if abs(st - seconds) <= SNAP_SEGMENT_SECONDS]
            if starts:
                seconds = min(starts, key=lambda st: abs(st - seconds))
            seconds = _snap_to_pause_end(seconds, pauses or [])
        elif _COMMA.match(clean[cue.char_index - 1]):
            seconds = _snap_to_pause_end(seconds, pauses or [])  # the voice breathes at a comma
        last = max(last, min(seconds, duration))  # tags stay in script order
        out[cue.tag] = last
    shifts = [f"{t}{out[t] - estimate[t]:+.1f}" for t in out if t in estimate]
    logger.info("Cue times measured from the voice (vs the estimate, s): %s", " ".join(shifts))
    return out
