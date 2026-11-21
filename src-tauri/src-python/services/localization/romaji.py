"""
RomajiConverter (romaji.py)
---------------------------------------------------------------------------
This module provides a utility class for transliterating Japanese text into Romaji
using the pykakasi library. It includes lazy loading of the converter and error handling
---------------------------------------------------------------------------
"""

import json
import re
from pathlib import Path
from typing import Dict, Tuple

from services.logger.logger import setup_logger

# Logging configuration
logger = setup_logger("RomajiConverter")

# [Core] pykakasi import with error handling
try:
    import pykakasi  # type: ignore

    _PYKAKASI_AVAILABLE = True
except ImportError:
    pykakasi = None
    _PYKAKASI_AVAILABLE = False
    logger.warning(
        "pykakasi is not installed — Romaji transliteration will be "
        "UNAVAILABLE and will fall through to returning original text. "
        "Run: pip install pykakasi"
    )

# [Config] Default path to the glossary.json file
_DEFAULT_GLOSSARY_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "glossary.json"
)


# [HACK] [Translation] Pattern tolerates pykakasi inserting stray spaces inside the
# "__PLACE_i__" placeholder token (e.g. "p l a c e") when it transliterates it character-by-character.
_PLACEHOLDER_PATTERN = re.compile(r"_*\s*p\s*l\s*a\s*c\s*e\s*_*\s*(\d+)\s*_*", re.IGNORECASE)


def _protect_glossary_terms(text: str, glossary: dict) -> Tuple[str, Dict[str, str]]:
    """`text` with each glossary term swapped for a placeholder token, and the romaji each token stands for.

    [NOTE] [Translation] Glossary terms are swapped for placeholder tokens before pykakasi runs,
    since pykakasi would otherwise transliterate proper nouns phonetically instead of using the curated romaji/en value.
    """
    processed_text = text
    placeholder_map: Dict[str, str] = {}
    # Longest first, so 三段壁 is swapped whole before a shorter term such as 三段 cuts into it.
    for i, (jp_name, raw_value) in sorted(enumerate(glossary.items()), key=lambda e: -len(e[1][0])):
        if jp_name in processed_text:
            placeholder = f"__PLACE_{i}__"

            # Resolve mapping (prioritizes a specific "romaji" key over "en")
            if isinstance(raw_value, dict):
                resolved_value = raw_value.get(
                    "romaji", raw_value.get("en", jp_name)
                )
            else:
                resolved_value = str(raw_value)

            placeholder_map[str(i)] = resolved_value
            processed_text = processed_text.replace(jp_name, placeholder)
    return processed_text, placeholder_map


def _restore_glossary_terms(romaji: str, placeholder_map: Dict[str, str]) -> str:
    """`romaji` with every placeholder token swapped back for its curated value."""

    def replace_placeholder(match):
        index = match.group(1)
        replacement = placeholder_map.get(index, match.group(0))
        # Force a space before and after the protected word
        return f" {replacement} "

    return _PLACEHOLDER_PATTERN.sub(replace_placeholder, romaji)


# [Core] RomajiConverter Class
class RomajiConverter:
    _kks = None
    _glossary = None

    @classmethod
    def load_glossary(cls, glossary_path: Path = _DEFAULT_GLOSSARY_PATH):
        if cls._glossary is None:
            if glossary_path.exists():
                try:
                    with open(glossary_path, "r", encoding="utf-8") as f:
                        cls._glossary = json.load(f)
                except Exception as e:
                    logger.error(f"Failed to load glossary from {glossary_path}: {e}")
                    cls._glossary = {}
            else:
                cls._glossary = {}
        return cls._glossary

    # [Translation/Config] Lazy loads the pykakasi converter instance
    @classmethod
    def get_converter(cls):
        """Lazy loads the pykakasi converter instance."""
        if not _PYKAKASI_AVAILABLE:
            raise RuntimeError("pykakasi is not installed.")
        if cls._kks is None:
            cls._kks = pykakasi.kakasi()  # type: ignore
        return cls._kks

    # [Translation] Converts Japanese text to capitalized Hepburn Romaji
    @staticmethod
    def to_romaji(text: str) -> str:
        if not text:
            return text

        try:
            glossary = RomajiConverter.load_glossary()
            processed_text, placeholder_map = _protect_glossary_terms(text, glossary)

            # Convert remaining text using pykakasi
            kks = RomajiConverter.get_converter()
            result = kks.convert(processed_text)
            romaji_tokens = [item["hepburn"] for item in result]
            formatted_romaji = " ".join(romaji_tokens).title()

            formatted_romaji = _restore_glossary_terms(formatted_romaji, placeholder_map)

            # Clean up formatting (remove double spaces, fix punctuation gaps)
            formatted_romaji = re.sub(r"\s+", " ", formatted_romaji)
            formatted_romaji = re.sub(r"\s+([.,!?])", r"\1", formatted_romaji).strip()

            return formatted_romaji

        except Exception as e:
            logger.error(f"Romaji conversion failed for '{text}': {e}")
            return text