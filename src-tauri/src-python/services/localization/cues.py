"""Timing cue tags inside narration scripts.

A script may carry inline tags that mark moments the video has to land on:

    {start}   the walk begins moving here
    {arrive}  "we are nearly there" - the walker nears the stop
    {end}     the stop is reached here
    {n}       overview only: visible waypoint number n is reached here
    {go}      overview only: the description of the stop before it ends here -
              the walker waits at that stop until now, then heads on. Recorded
              as "go<n>" (n: the last {n} before it); ignored before any {n}
    {goPreN}  overview only: a stop-by batch mentioned in passing, on the way
              to numbered stop N, ends here - the walker (or, before stop 1,
              the route's start) waits until now, then sets off. A literal
              tag naming the stop it precedes explicitly, unlike {go}, since
              a stop-by batch has no {n} of its own for {go} to attach to.
    {distance} overview only: the closing line's distance summary ("…24km
              の旅でした") ends here - the ending highlight holds at least
              until now, so it isn't cut short with that line still playing.

Tags are never spoken. They are stripped before TTS and subtitles, and the
position each one had in the spoken text is kept so its time can be worked out
from the real audio afterwards (see `cue_times`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

CUE_RE = re.compile(r"\{(start|arrive|end|distance|goPre\d+|go|\d+)\}")


@dataclass(frozen=True)
class Cue:
    tag: str  # "start" | "arrive" | "end" | "1", "2", ... | "go1", "go2", ...
    char_index: int  # offset into the CLEAN text: the cue sits right before this char


def strip_cues(text: Optional[str]) -> Tuple[str, List[Cue]]:
    """Returns (spoken text without tags, cues in order)."""
    if not text:
        return "", []
    parts: List[str] = []
    cues: List[Cue] = []
    length = 0
    pos = 0
    stop = None  # the last {n}: a {go} ends that stop's description
    for match in CUE_RE.finditer(text):
        piece = text[pos:match.start()]
        parts.append(piece)
        length += len(piece)
        tag = match.group(1)
        if tag.isdigit():
            stop = tag
        if tag != "go":
            cues.append(Cue(tag, length))
        elif stop is not None:
            cues.append(Cue("go" + stop, length))
        pos = match.end()
    parts.append(text[pos:])
    return "".join(parts), cues


def clean_text(text: Optional[str]) -> str:
    return strip_cues(text)[0]


def cue_tags(text: Optional[str]) -> List[str]:
    return [c.tag for c in strip_cues(text)[1]]


_SENTENCE_END_CHARS = "。！？!?\n"


def tags_at_sentence_start(text: Optional[str]) -> List[str]:
    """Tags of the cues that open a passage (the very start of the script, or
    right after a line break): the voice starts speaking about that place at
    the cue, so the video waits a moment there to stay in step with it. A cue
    written right after a sentence's 。！？ closes that sentence ("...です。{1}")
    and gets no extra wait - the walker simply arrives as the sentence ends
    (and still waits if it gets there before the voice)."""
    clean, cues = strip_cues(text)
    return [c.tag for c in cues if c.char_index == 0 or clean[c.char_index - 1] == "\n"]


def cue_times(
    cues: List[Cue],
    clean: str,
    duration_seconds: float,
    pauses: Optional[List[Dict[str, float]]] = None,
) -> Dict[str, float]:
    """Seconds into the audio at which each cue's following text starts to be
    spoken, mapped the same way subtitles are (characters -> speaking time,
    skipping pauses). Keyed by tag; a repeated tag keeps its first time."""
    if not cues:
        return {}
    from services.localization.subtitle import SpeakingTimelineMapper

    total_chars = max(1, len(clean))
    mapper = SpeakingTimelineMapper(duration_seconds, pauses or [])
    times: Dict[str, float] = {}
    for cue in cues:
        char_index = cue.char_index
        if mapper.total_speaking_time <= 0:
            times.setdefault(cue.tag, duration_seconds * char_index / total_chars)
            continue
        speaking = mapper.total_speaking_time * (char_index / total_chars)
        # allocate() walks `speaking` seconds of pure speech across the clip,
        # skipping pauses; the span it returns ENDS where the cue falls.
        _, reached = mapper.allocate([speaking])[0]
        # The char-proportional estimate assumes one constant reading speed
        # for the WHOLE clip, but real speech doesn't read at a constant
        # rate sentence to sentence (pauses between sentences vary too) -
        # so a cue far into a long script can land up to ~1s off. A cue
        # right after a sentence's 。！？ (a {go}, or any other tag placed
        # at a sentence boundary - the common case, see tags_at_sentence_
        # start) sits right where a real pause almost always falls, so it
        # can be snapped to that pause's actual edge instead of trusting
        # the estimate - recovering the exact position, not just a closer
        # guess.
        at_boundary = char_index == 0 or clean[char_index - 1] in _SENTENCE_END_CHARS
        if cue.tag.startswith("go") or at_boundary:
            reached = _snap_to_pause_end(reached, pauses or [])
        times.setdefault(cue.tag, reached)
    return times


# A {go} is at most this far from the pause it is snapped to.
GO_SNAP_SECONDS = 1.0


def _snap_to_pause_end(seconds: float, pauses: List[Dict[str, float]]) -> float:
    """The end of the pause nearest `seconds` (the moment the voice starts the
    next sentence), when one is close: a {go} sits between two sentences, and
    the walker should set off as the next one starts, not mid-silence."""
    near = [
        p for p in pauses
        if p.get("start", 0.0) - GO_SNAP_SECONDS <= seconds <= p.get("end", 0.0) + GO_SNAP_SECONDS
    ]
    if not near:
        return seconds
    best = min(near, key=lambda p: min(abs(seconds - p["start"]), abs(seconds - p["end"])))
    return float(best["end"])
