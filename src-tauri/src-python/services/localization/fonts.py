"""Installed font families, so a style never names a font libass would silently swap.

Reads the 'name' table of every font in the Windows system and per-user font
folders (fontTools, already a dependency). Both the English and localized
family names count, since libass/DirectWrite match either (Meiryo / メイリオ).
"""

from __future__ import annotations

import os
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from services.logger.logger import setup_logger

logger = setup_logger("Fonts")

_FONT_EXTS = {".ttf", ".otf", ".ttc", ".otc"}
# Typographic family (16) when present, else the legacy family (1).
_FAMILY_NAME_IDS = (16, 1)

# Language groups the font picker shows, in order. Other fonts are left out of it.
FONT_LANGUAGES = ("ja", "en")
# OS/2 ulCodePageRange1 bits.
_CP_LATIN1, _CP_LATIN2, _CP_JAPANESE, _CP_CHINESE, _CP_KOREAN, _CP_SYMBOL = 0, 1, 17, 18, 19, 31
_CP_CJK = range(17, 22)
_KANA = (0x3042, 0x30A2)  # あ ア
# A Latin font that isn't pan-European may still be made for another script (Thai, Arabic,
# Javanese, Yi...): this many letters of another script, or symbols, rule it out.
_MAX_OTHER_LETTERS = 30
_MAX_SYMBOLS = 300


def _user_font_dir() -> Optional[Path]:
    """Where fonts installed for this Windows user (and the app's downloads) live."""
    local = os.environ.get("LOCALAPPDATA")
    return Path(local) / "Microsoft" / "Windows" / "Fonts" if local else None


def _font_dirs() -> List[Path]:
    dirs = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts", _user_font_dir()]
    return [d for d in dirs if d and d.is_dir()]


def _language(font) -> Optional[str]:
    """'ja' for a Japanese font, 'en' for a Latin one made for no other script, else None."""
    os2 = font.get("OS/2") if "OS/2" in font else None
    if os2 is None or getattr(os2, "version", 0) < 1:
        return None
    pages = os2.ulCodePageRange1
    if pages & (1 << _CP_SYMBOL):
        return None
    has = lambda bit: bool(pages & (1 << bit))
    cmap = font.getBestCmap() or {}
    if has(_CP_JAPANESE):
        # Chinese fonts carry kana too but don't claim the Japanese code page; a Korean one
        # that does is left out unless it is pan-CJK (Chinese as well).
        if has(_CP_KOREAN) and not has(_CP_CHINESE):
            return None
        return "ja" if all(c in cmap for c in _KANA) else None
    if any(has(b) for b in _CP_CJK) or not has(_CP_LATIN1):
        return None
    if sum(1 for c in range(0x41, 0x7B) if c in cmap) < 52:  # icon fonts
        return None
    if has(_CP_LATIN2):  # pan-European (Arial, Tahoma): other scripts are extras
        return "en"
    other_letters = symbols = 0
    for c in cmap:
        if c < 0x370 or 0xE000 <= c <= 0xF8FF:
            continue
        category = unicodedata.category(chr(c))
        if category.startswith("L") and not unicodedata.name(chr(c), "").startswith("LATIN"):
            other_letters += 1
        elif category == "So":
            symbols += 1
    if other_letters >= _MAX_OTHER_LETTERS or symbols >= _MAX_SYMBOLS:
        return None
    return "en"


def _families_in(path: Path) -> Iterable[tuple]:
    """(display name, every name it answers to, language) per face in the file."""
    from fontTools.ttLib import TTCollection, TTFont

    if path.suffix.lower() in (".ttc", ".otc"):
        fonts = TTCollection(str(path), lazy=True).fonts
    else:
        fonts = [TTFont(str(path), lazy=True, fontNumber=0)]
    for font in fonts:
        names = set()
        display = None
        for name_id in _FAMILY_NAME_IDS:
            english = None
            for r in font["name"].names:
                if r.nameID != name_id:
                    continue
                try:
                    text = r.toUnicode().strip()
                except Exception:
                    continue
                if text:
                    names.add(text)
                    if r.platformID == 3 and r.langID == 0x409:
                        english = text
            display = display or english
        if names:
            try:
                language = _language(font)
            except Exception:
                language = None
            yield display or sorted(names)[0], names, language


@lru_cache(maxsize=1)
def _scan() -> tuple:
    """(lower-cased name in any language -> display family, display family -> language,
    families installed per user, i.e. downloaded)."""
    index: Dict[str, str] = {}
    downloaded = set()
    user_dir = _user_font_dir()
    # Every face of a family must agree (Malgun Gothic's Semilight claims Japanese, its others Korean).
    languages: Dict[str, Optional[str]] = {}
    for folder in _font_dirs():
        for path in folder.iterdir():
            if path.suffix.lower() not in _FONT_EXTS:
                continue
            try:
                for display, names, language in _families_in(path):
                    if folder == user_dir:
                        downloaded.add(display)
                    for n in names:
                        index.setdefault(n.casefold(), display)
                    if languages.setdefault(display, language) != language:
                        languages[display] = None
            except Exception as exc:  # one broken font must not hide the rest
                logger.debug("Skipping unreadable font %s: %s", path, exc)
    return index, {name: lang for name, lang in languages.items() if lang}, sorted(downloaded, key=str.casefold)


def _index() -> Dict[str, str]:
    return _scan()[0]


def downloaded_font_families() -> List[str]:
    """Families installed for this user rather than shipped with Windows or Office."""
    return _scan()[2]


def font_languages() -> Dict[str, str]:
    """Display family -> its picker group (see FONT_LANGUAGES); unlisted families have none."""
    return _scan()[1]


def installed_font_families() -> List[str]:
    """Sorted display names, one per family, for the frontend's font picker."""
    return sorted(set(_index().values()), key=str.casefold)


def find_font_family(name: str) -> Optional[str]:
    """The installed family `name` refers to (case/language-insensitive), or None."""
    return _index().get((name or "").strip().casefold())


def resolve_font_family(name: str, fallback: str) -> str:
    """`name` if installed, else `fallback` (logged). Unknown when no font folder
    can be read (non-Windows): trust the name rather than override it."""
    if not _index() or find_font_family(name):
        return name
    logger.warning("Font %r is not installed; using %r instead.", name, fallback)
    return fallback
