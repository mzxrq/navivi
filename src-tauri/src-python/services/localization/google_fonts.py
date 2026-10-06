"""Google Fonts for the font picker: a catalog per language, and a per-user install.

The catalog is Google Fonts' public metadata (no API key), cached a week. Installing
downloads the family's regular and bold TTFs through the css2 API (an old user agent
gets TTF instead of WOFF2) into the per-user font folder, registers them under HKCU
and announces them, so libass and the app see them without admin rights.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List

from services.localization import fonts
from services.logger.logger import setup_logger

logger = setup_logger("GoogleFonts")

CATALOG_URL = "https://fonts.google.com/metadata/fonts"
CSS_URL = "https://fonts.googleapis.com/css2?family={family}:wght@{weights}"
_CACHE = Path(tempfile.gettempdir()) / "navivi_google_fonts.json"
_CACHE_SECONDS = 7 * 24 * 3600
_TIMEOUT = 30
_WEIGHTS = ("400", "700")
_CJK_SUBSETS = {"japanese", "korean", "chinese-simplified", "chinese-traditional", "chinese-hongkong"}
_REG_KEY = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"


def _get(url: str, user_agent: str = "Mozilla/5.0") -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read()


def _families() -> List[dict]:
    if _CACHE.exists() and time.time() - _CACHE.stat().st_mtime < _CACHE_SECONDS:
        try:
            return json.loads(_CACHE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    raw = _get(CATALOG_URL).decode("utf-8")
    families = json.loads(raw[raw.index("{"):])["familyMetadataList"]
    keep = ("family", "category", "subsets", "popularity", "primaryScript", "fonts")
    slim = [{k: f.get(k) for k in keep} for f in families]
    try:
        _CACHE.write_text(json.dumps(slim, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        logger.debug("Could not cache the Google Fonts catalog: %s", exc)
    return slim


def _in_language(family: dict, lang: str) -> bool:
    subsets = set(family.get("subsets") or [])
    if lang == "ja":
        return "japanese" in subsets
    if lang == "en":
        return "latin" in subsets and not subsets & _CJK_SUBSETS and (family.get("primaryScript") or "Latn") == "Latn"
    return False


def catalog(lang: str) -> List[Dict]:
    """Families for one picker language (fonts.FONT_LANGUAGES), most popular first."""
    rows = [f for f in _families() if _in_language(f, lang)]
    rows.sort(key=lambda f: f.get("popularity") or 1e9)
    # "Installed" means downloaded for this user: only those are offered in the font picker.
    downloaded = {name.casefold() for name in fonts.downloaded_font_families()}
    return [
        {
            "family": f["family"],
            "category": f.get("category") or "",
            "bold": "700" in (f.get("fonts") or {}),
            "installed": f["family"].casefold() in downloaded,
        }
        for f in rows
    ]


def _user_font_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise RuntimeError("LOCALAPPDATA is not set; fonts can only be installed on Windows.")
    folder = Path(local) / "Microsoft" / "Windows" / "Fonts"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _register(path: Path, display: str) -> None:
    import ctypes
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, f"{display} (TrueType)", 0, winreg.REG_SZ, str(path))
    gdi = ctypes.windll.gdi32
    gdi.AddFontResourceW(str(path))
    # WM_FONTCHANGE to every top-level window, so running apps reload their font lists.
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001D, 0, 0, 0x0002, 1000, None)


def install(family: str) -> List[str]:
    """Downloads and installs `family` (regular, plus bold when it has one). Returns the files."""
    family = (family or "").strip()
    if not family or not re.fullmatch(r"[\w .'&-]+", family):
        raise ValueError(f"Not a font family name: {family!r}")
    weights = ";".join(_WEIGHTS)
    css = _get(CSS_URL.format(family=urllib.parse.quote_plus(family), weights=weights), user_agent="Mozilla/4.0").decode("utf-8")
    faces = re.findall(r"font-weight:\s*(\d+);.*?url\((https://fonts\.gstatic\.com/[^)\s]+\.ttf)\)", css, re.S)
    if not faces:
        raise RuntimeError(f"Google Fonts has no downloadable files for {family}.")
    folder = _user_font_dir()
    stem = re.sub(r"[^\w-]+", "", family.replace(" ", "-"))
    written: List[str] = []
    for weight, url in dict(faces).items():
        style = "Bold" if weight == "700" else "Regular"
        path = folder / f"{stem}-{style}.ttf"
        path.write_bytes(_get(url))
        _register(path, family if style == "Regular" else f"{family} Bold")
        written.append(str(path))
    logger.info("Installed Google font %s: %s", family, ", ".join(written))
    return written
