"""Installed font families, so a style never names a font libass would silently swap.

Reads the 'name' table of every font in the Windows system and per-user font
folders (fontTools, already a dependency). Both the English and localized
family names count, since libass/DirectWrite match either (Meiryo / メイリオ).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from services.logger.logger import setup_logger

logger = setup_logger("Fonts")

_FONT_EXTS = {".ttf", ".otf", ".ttc", ".otc"}
# Typographic family (16) when present, else the legacy family (1).
_FAMILY_NAME_IDS = (16, 1)


def _font_dirs() -> List[Path]:
    dirs = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    return [d for d in dirs if d.is_dir()]


def _families_in(path: Path) -> Iterable[tuple]:
    """(display name, every name it answers to) per face in the file."""
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
            yield display or sorted(names)[0], names


@lru_cache(maxsize=1)
def _index() -> Dict[str, str]:
    """lower-cased name (any language) -> display (English) family name."""
    index: Dict[str, str] = {}
    for folder in _font_dirs():
        for path in folder.iterdir():
            if path.suffix.lower() not in _FONT_EXTS:
                continue
            try:
                for display, names in _families_in(path):
                    for n in names:
                        index.setdefault(n.casefold(), display)
            except Exception as exc:  # one broken font must not hide the rest
                logger.debug("Skipping unreadable font %s: %s", path, exc)
    return index


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
