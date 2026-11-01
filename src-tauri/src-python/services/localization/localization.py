import re
from services.localization.romaji import RomajiConverter


def is_japanese(text: str) -> bool:
    """Checks if a string contains Japanese characters (Kanji, Hiragana, Katakana)."""
    if not text:
        return False
    japanese_pattern = re.compile(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]")
    return bool(japanese_pattern.search(text))


def format_waypoint_label(raw_label: str, target_lang: str = "en") -> str:
    """Converts to Romaji only if it contains Japanese."""
    if not raw_label:
        return ""
    if target_lang.lower() in (
        "romaji",
        "roman",
        "ja-romaji",
        "hepburn",
    ) and is_japanese(raw_label):
        return RomajiConverter.to_romaji(raw_label)
    return raw_label

