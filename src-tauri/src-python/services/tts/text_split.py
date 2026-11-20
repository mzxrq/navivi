"""Splits a narration text into chunks short enough for one TTS request."""

from __future__ import annotations

import re
from typing import List, Tuple

from services import tuning
from services.localization.sentence_split import SENTENCE_END

_CLAUSE_END = re.compile(r"(?<=[、，,])")


def _cut_to_chars(piece: str, max_chars: int) -> List[str]:
    """A single sentence (or any piece), forced under `max_chars`: cut at its
    commas, and only as a last resort in the middle of a clause.
    split_text_for_tts then re-packs the pieces up to max_chars."""
    if len(piece) <= max_chars:
        return [piece]
    out, cur = [], ""
    for clause in (c for c in _CLAUSE_END.split(piece) if c):
        while len(clause) > max_chars:  # no comma to cut at
            if cur:
                out.append(cur)
                cur = ""
            out.append(clause[:max_chars])
            clause = clause[max_chars:]
        if cur and len(cur) + len(clause) > max_chars:
            out.append(cur)
            cur = ""
        cur += clause
    if cur:
        out.append(cur)
    return out


def chunk_limits(text: str) -> Tuple[int, int]:
    """(max, min) characters per TTS request: about 15 s of speech in the text's own script."""
    from services.localization.localization import is_japanese

    if is_japanese(text):
        return tuning.TTS_MAX_CHUNK_CHARS, tuning.TTS_MIN_CHUNK_CHARS
    return tuning.TTS_MAX_CHUNK_CHARS_LATIN, tuning.TTS_MIN_CHUNK_CHARS_LATIN


def split_text_for_tts(text: str, max_chars: int, min_chars: int = 0) -> List[str]:
    """Splits `text` into pieces of at most `max_chars` characters for separate
    TTS requests: whole sentences, grouped until a chunk has `min_chars`; a
    sentence that is too long is cut at its commas, and only as a last resort
    in the middle of a clause. The pieces joined give back exactly `text`.

    `min_chars` (tuning.TTS_MIN_CHUNK_CHARS): a trailing chunk left shorter
    than this - typically just the closing line, once nothing else remains
    to pack it with - is merged into the chunk before it, even past
    `max_chars`. See TTS_MIN_CHUNK_CHARS's own comment for why: sent alone,
    a too-short chunk risks the TTS server hallucinating a "ghost sentence"
    past the end of the real text."""
    text = text or ""
    if len(text) <= max_chars:
        return [text] if text else []

    # A chunk closes at the first sentence end once it has min_chars, not packed up to max_chars: editing one
    # sentence then changes only its own chunk, and the others are served from the phrase cache.
    chunks, cur = [], ""
    for sentence in (s for s in SENTENCE_END.split(text) if s):
        for piece in _cut_to_chars(sentence, max_chars):
            if cur and len(cur) + len(piece) > max_chars:
                chunks.append(cur)
                cur = ""
            cur += piece
        if len(cur) >= min_chars:
            chunks.append(cur)
            cur = ""
    if cur:
        chunks.append(cur)
    if min_chars and len(chunks) >= 2 and len(chunks[-1]) < min_chars:
        tail = chunks.pop()  # NOTE: chunks[-2] after pop() is chunks[-1] before it - grab the tail first
        chunks[-1] += tail
    return chunks
