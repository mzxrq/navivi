"""Where a sentence ends, for Japanese (。！？) and English (a period before a space).

One pattern for the narration chunker, the cue code and the subtitle splitter, so an English script is cut at its sentences
and not at "Mt." or "Sta." or the point of "1.5 km". The pattern matches an empty position, so splitting with it loses nothing:
the pieces joined give back the text."""

import re

# Abbreviations that end in a period without ending a sentence (as the translated place names write them).
ABBREVIATIONS = ("Mt", "St", "Sta", "Dr", "Mr", "Mrs", "Ms", "Jr", "Sr", "No", "Pref", "Ave", "Rd", "Ft", "vs", "approx", "etc")

_NOT_ABBREVIATION = "".join(r"(?<!\b%s\.)" % a for a in ABBREVIATIONS)

SENTENCE_END = re.compile(r"(?<=[。！？!?\n])|" + _NOT_ABBREVIATION + r"(?<=[A-Za-z0-9)\"'”’]\.)(?=\s)")


def split_sentences(text: str) -> list:
    return [s for s in SENTENCE_END.split(text or "") if s]
