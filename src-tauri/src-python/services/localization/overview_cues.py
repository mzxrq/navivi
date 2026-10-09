"""Cue tags for an overview narration the user wrote themselves.

A hand-written overview script has no {n} / {go} tags, so the walk cannot stop
at a waypoint while the voice describes it. This places them with plain rules,
never changing a word of the script:

    {n}   before the first sentence that names visible waypoint n (in route
          order: a name mentioned before the previous stop's is a passing
          mention, not the stop's description)
    {go}  before the first later sentence of that stop's passage that sets
          off for somewhere else ("次は…", "ここから…"): the stop is described
          until there, then the walker heads on
    {start} before "これが全体のルートです。" (the map appears; the opening
          before it plays over the intro, and its names are not stops), and
          {route} before the next sentence (the route is traced from there)
    {extras} before "茶色で示した地点は…" (the stop-bys appear; not stops either)

Tags the user wrote win: a script with any {n} keeps its own, and one with any
{go} keeps its own.
"""

from __future__ import annotations

import re
from typing import List, Optional, Sequence

from services.localization.cues import cue_tags
from services.localization.sentence_split import SENTENCE_END

_SENTENCE_END = SENTENCE_END

# A sentence that starts with one of these leaves the place just described.
TRANSITION_OPENERS = (
    "次は", "次に", "続いて", "つづいて", "さらに進", "ここから", "そこから",
    "さて", "では", "それでは", "さあ",
)
# ...or that ends by heading somewhere.
TRANSITION_ENDINGS = re.compile(r"(へ|に)(向かい|進み|歩き|移動し|戻り)(ます|ましょう)[。！!]?$")

_ROUTE_PIVOT = re.compile(r"全体のルート|ルート全体|ルートの全体")
_EXTRAS = re.compile(r"茶色で示した|茶色のマーカー|追加の見どころ")

# Dropped from a name to also find its short form (加太駅 -> 加太).
_NAME_SUFFIXES = ("駅", "神社", "寺", "城", "公園", "港", "橋", "展望台", "資料館", "博物館")


def _sentences(text: str) -> List[str]:
    """Pieces that join back to exactly `text`, each ending at 。！？ or a line break."""
    return [s for s in _SENTENCE_END.split(text) if s]


def name_variants(label: str) -> List[str]:
    """How a place may be written in the script, longest first."""
    label = (label or "").strip()
    if not label:
        return []
    variants = {label, re.sub(r"[（(].*?[)）]", "", label).strip()}
    for v in list(variants):
        for suffix in _NAME_SUFFIXES:
            if v.endswith(suffix) and len(v) - len(suffix) >= 2:
                variants.add(v[: -len(suffix)])
    return sorted((v for v in variants if v), key=len, reverse=True)


def is_transition(sentence: str) -> bool:
    s = sentence.strip()
    return s.startswith(TRANSITION_OPENERS) or bool(TRANSITION_ENDINGS.search(s))


def auto_tag_overview(script: Optional[str], labels: Sequence[str]) -> Optional[str]:
    """`script` with {n} / {go} tags placed; `labels[i]` is visible waypoint
    i + 1's name. Returns the script unchanged when nothing could be placed."""
    if not script:
        return script
    tags = cue_tags(script)
    has_numbers = any(t.isdigit() for t in tags)
    has_go = "{go}" in script
    sentences = _sentences(script)
    # "これが全体のルートです。": the map appears there, so the opening before it plays
    # over the intro ({start}); the route is traced from the next sentence ({route}).
    # "茶色で示した地点は…": the stop-bys appear ({extras}); their names are not stops.
    pivot = None if "start" in tags else next((i for i, s in enumerate(sentences) if _ROUTE_PIVOT.search(s)), None)
    extras = None if "extras" in tags else next((i for i, s in enumerate(sentences) if _EXTRAS.search(s)), None)
    marks: dict = {}
    if pivot is not None:
        marks.setdefault(pivot, []).append("{start}")
        if pivot + 1 < len(sentences) and "route" not in tags:
            marks.setdefault(pivot + 1, []).append("{route}")
    if extras is not None:
        marks.setdefault(extras, []).append("{extras}")
    limit = extras if extras is not None else len(sentences)
    if has_numbers and has_go:
        return _with_marks(sentences, marks)
    if pivot is not None and not has_numbers:
        return _with_marks(_tag_route_names(sentences, pivot + 1, limit, labels, not has_go), marks)

    # sentence index -> the stop number whose description starts there
    starts = {}
    if has_numbers:
        # the user's own {n}: find the sentence each one sits in
        for i, s in enumerate(sentences):
            for t in cue_tags(s):
                if t.isdigit():
                    starts.setdefault(i, int(t))
    else:
        after = -1 if pivot is None else pivot  # names in the opening introduce, they are not stops
        for n, label in enumerate(labels, start=1):
            # The full name first: a short form (加太 for 加太駅) is often also
            # the town's name, so it only counts when the full one never appears.
            mentions = []
            for variants in (name_variants(label)[:1], name_variants(label)):
                mentions = [
                    i for i in range(after + 1, limit)
                    if i not in starts and any(v in sentences[i] for v in variants)
                ]
                if mentions:
                    break
            # "次は常行寺へ向かいます" only announces the place: its description
            # is the next sentence naming it (the announcement if none does).
            hit = next((i for i in mentions if not is_transition(sentences[i])), None)
            if hit is None and mentions:
                hit = mentions[0]
            if hit is not None:
                starts[hit] = n
                after = hit
    if not starts:
        return _with_marks(sentences, marks)

    # {go}: in each stop's passage, the first transition after its opening sentence
    go_before = set()
    if not has_go:
        order = sorted(starts)
        for k, first in enumerate(order):
            end = order[k + 1] if k + 1 < len(order) else len(sentences)
            hit = next((i for i in range(first + 1, end) if is_transition(sentences[i])), None)
            if hit is not None:
                go_before.add(hit)

    out = []
    for i, s in enumerate(sentences):
        if i in go_before:
            out.append("{go}")
        if i in starts and not has_numbers:
            lead = len(s) - len(s.lstrip())  # keep a line's indent before the tag
            s = s[:lead] + "{%d}" % starts[i] + s[lead:]
        out.append(s)
    return _with_marks(_sentences("".join(out)), marks)


def _tag_route_names(sentences: List[str], first: int, limit: int, labels: Sequence[str], add_go: bool) -> List[str]:
    """The course layout's route sentences (sentences[first:limit]) with {n}
    right before each stop's name, found in route order (the trace reaches a
    place as its name is said), and {go} after each sentence that names one."""
    out = list(sentences)
    i, cursor = first, 0
    for n, label in enumerate(labels, start=1):
        hit = None
        for variants in (name_variants(label)[:1], name_variants(label)):
            found = [
                (j, k, -len(v)) for j in range(i, limit) for v in variants
                for k in [out[j].find(v, cursor if j == i else 0)] if k >= 0
            ]
            if found:
                hit = min(found)
                break
        if hit is None:
            continue
        j, k, minus_len = hit
        tag = "{%d}" % n
        out[j] = out[j][:k] + tag + out[j][k:]
        i, cursor = j, k + len(tag) - minus_len
    if add_go:
        for j in range(first, limit):
            if any(t.isdigit() for t in cue_tags(out[j])):
                body = out[j].rstrip()
                out[j] = body + "{go}" + out[j][len(body):]
    return out


def _with_marks(sentences: List[str], marks: dict) -> str:
    """The sentences joined, each tag in marks[i] before sentence i (after its indent)."""
    out = list(sentences)
    for i, tags in marks.items():
        s = out[i]
        lead = len(s) - len(s.lstrip())
        out[i] = s[:lead] + "".join(tags) + s[lead:]
    return "".join(out)
