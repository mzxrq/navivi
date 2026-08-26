import re
import sys
from typing import Any
from services.romaji import RomajiConverter
from services.translator import ScriptTranslator
from services.job_config import JobConfigManager
from services.subtitle import SubtitleStyle


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


def build_display_text(original_jp: str, target_lang: Any) -> str:
    if not isinstance(target_lang, str) or not target_lang.strip():
        target_lang = "en"
    normalized_target = target_lang.strip().lower()

    if normalized_target in ("romaji", "roman", "ja-romaji", "hepburn"):
        return RomajiConverter.to_romaji(original_jp)

    translated = ScriptTranslator.translate(original_jp, target_lang=target_lang)

    if ScriptTranslator.last_call_failed:
        print(
            f"⚠️  Translation to '{target_lang}' FAILED — falling back to Romaji for: {original_jp[:30]!r}...",
            file=sys.stderr,
        )
        return RomajiConverter.to_romaji(original_jp)
    return translated


def _build_subtitle_style(job_config: "JobConfigManager") -> SubtitleStyle:
    settings = job_config.get_settings()
    return SubtitleStyle(
        font_name=settings.get("subtitle_font", "Yu Gothic UI"),
        font_size=int(settings.get("subtitle_font_size", 30)),
        primary_color=settings.get("subtitle_color", "&H00FFFFFF"),
        outline_color=settings.get("subtitle_outline_color", "&H00000000"),
        bold=bool(settings.get("subtitle_bold", False)),
        alignment=int(settings.get("subtitle_alignment", 2)),
        margin_v=int(settings.get("subtitle_margin_v", 50)),
    )
