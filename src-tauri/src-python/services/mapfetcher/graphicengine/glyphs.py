"""Letters the bundled LINE Seed JP font cannot draw, swapped for their plain base letter.

[NOTE] [Font] PIL has no per-glyph fallback, so a missing letter is drawn as a box: LINE Seed JP lacks ō/Ō
("Jizō" came out "Jiz□"). Japanese is fully covered, so Japanese text never changes.
"""

import os
import unicodedata
from functools import lru_cache

_FONTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "assets", "fonts")


@lru_cache(maxsize=1)
def _covered() -> frozenset:
    """Code points both LINE Seed JP weights have; empty (nothing swapped) when they can't be read."""
    try:
        from fontTools.ttLib import TTFont

        maps = [set(TTFont(os.path.join(_FONTS_DIR, f"LINESeedJP-{w}.ttf")).getBestCmap()) for w in ("Regular", "Bold")]
        return frozenset(maps[0] & maps[1])
    except Exception:
        return frozenset()


def drawable(text: str) -> str:
    """`text` with each letter the font lacks replaced by its base letter (ō -> o) when the font has that."""
    covered = _covered()
    if not text or not covered:
        return text or ""

    def swap(ch: str) -> str:
        if ord(ch) in covered or ch.isspace():
            return ch
        base = unicodedata.normalize("NFKD", ch)[:1]
        return base if base and ord(base) in covered else ch

    return "".join(swap(ch) for ch in text)
