"""Japanese names in English lines for the fast voice (Kokoro). A dictionary word whose reading is kana is sent as
`[Kuhonji](ja:くほんじ)` (kokoro_server.py turns the kana into sounds); one whose reading is sounds between slashes,
`/kuhoːnʤi/`, is sent as `[Kuhonji](/kuhoːnʤi/)`, which Kokoro speaks as written.
The other engines never see the marks (they skip such entries, see audio_step.apply_pronunciation_dictionary)."""

import re
from typing import Dict

RULE_VERSION = 2  # kokoro_server.japanese_sounds; bump when it changes so cached lines are voiced again
_readings: Dict[str, str] = {}  # word as an English script writes it -> its kana reading or /sounds/
_MARK = r"\]\((?:ja:[^)]*|/[^)]*/)\)"


def is_sounds(reading: str) -> bool:
    return len(reading) > 2 and reading.startswith("/") and reading.endswith("/")


def remember(word: str, reading: str) -> None:
    if word and reading:
        _readings[word] = reading


def _tag(word: str, reading: str) -> str:
    return f"[{word}]({reading})" if is_sounds(reading) else f"[{word}](ja:{reading})"


def mark(text: str) -> str:
    if not _readings:
        return text
    words = sorted(_readings, key=len, reverse=True)
    lookup = {w.lower(): r for w, r in _readings.items()}
    pattern = re.compile(r"(?<!\w)(" + "|".join(map(re.escape, words)) + r")(?!\w)", re.IGNORECASE)
    marked = pattern.sub(lambda m: _tag(m[1], lookup[m[1].lower()]), text)
    # A hyphen glued to a name runs it into the next word ("Meiji-era" was heard as Magieira), so it becomes a space.
    marked = re.sub(r"(" + _MARK + r")-(?=\w)", r"\1 ", marked)
    return re.sub(r"(?<=\w)-(\[[^\]]+" + _MARK + r")", r" \1", marked)
