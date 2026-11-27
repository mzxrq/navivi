"""Card styles as files: `<card>/<style>.html|.svg`, built in under designs/ and the user's own in
Documents/Navivi/Styles (see docs/themed-card-styles.md). A user file wins over a built-in one of the same name.

Filled with Jinja2, sandboxed: a style file someone else wrote must not be able to run Python.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from jinja2 import FileSystemLoader, StrictUndefined
from jinja2.sandbox import SandboxedEnvironment
from markupsafe import Markup, escape

from services.localization.japanese_words import phrases
from services.logger.logger import setup_logger

logger = setup_logger(__name__)

BUILTIN_DIR = Path(__file__).parent / "designs"
DEFAULT = "default"
_EXTENSIONS = (".html", ".svg")
_NAME = re.compile(r"[A-Za-z0-9_-]+")
_ROOT = re.compile(r"""class\s*=\s*["'][^"']*(?<![\w-])card(?![\w-])""")
# What the video code reads from a card, so a style without it is not usable.
_REQUIRED = {
    "strip": ('data-line="',),
    "compass": ('id="hud-compass-pointer"', 'id="hud-compass-letter"', 'id="hud-compass-label"'),
}


def user_dir() -> Path:
    override = os.environ.get("NAVIVI_STYLES_DIR")
    return Path(override) if override else Path.home() / "Documents" / "Navivi" / "Styles"


def find(card: str, style: str) -> Optional[Path]:
    """The file drawing `card` in `style`, or None."""
    if not (_NAME.fullmatch(card) and _NAME.fullmatch(style)):
        return None
    for folder in (user_dir(), BUILTIN_DIR):
        for extension in _EXTENSIONS:
            path = folder / card / f"{style}{extension}"
            if path.is_file():
                return path
    return None


def available(card: str) -> List[str]:
    """Every style name `card` can be drawn in."""
    return sorted({
        path.stem
        for folder in (user_dir(), BUILTIN_DIR)
        for path in (folder / card).glob("*")
        if path.suffix in _EXTENSIONS and _NAME.fullmatch(path.stem)
    })


def _words(text) -> Markup:
    """Text that may break only between words."""
    return Markup("<wbr>").join(phrases(str(text or "")))


def _units(text: str) -> Markup:
    """"3時間23分" with everything that is not a number set small."""
    parts = re.findall(r"[\d.,]+|[^\d.,]+", str(text))
    return Markup("").join(
        escape(p) if p[0] in "0123456789.,"
        else (Markup('<span class="u">{}</span>').format(p.strip()) if p.strip() else "")
        for p in parts)


def _environment(folders) -> SandboxedEnvironment:
    env = SandboxedEnvironment(loader=FileSystemLoader([str(f) for f in folders]), autoescape=True,
                               undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)
    env.filters.update(words=_words, units=_units, g=lambda v: format(v, "g"), f1=lambda v: format(v, ".1f"))
    return env


def _fill(env: SandboxedEnvironment, card: str, path: Path, data: Dict) -> str:
    html = env.get_template(f"{card}/{path.name}").render(data)
    missing = [part for part in _REQUIRED.get(card, ()) if part not in html]
    if not _ROOT.search(html):
        missing.insert(0, 'an element with class="card"')
    if missing:
        raise ValueError(f"the file lacks {', '.join(missing)}")
    return html


def render(card: str, style: str, data: Dict) -> str:
    """`card`'s HTML in `style`. A style that is missing or broken gives the built-in default, with a warning."""
    path = find(card, style)
    if path is None:
        logger.warning("No style '%s' for the %s card; using '%s'.", style, card, DEFAULT)
        path = find(card, DEFAULT)
    builtin = BUILTIN_DIR / card / f"{DEFAULT}.html"
    if path != builtin:
        try:
            return _fill(_environment((user_dir(), BUILTIN_DIR)), card, path, data)
        except Exception as error:  # any fault in a user's file
            logger.warning("Style file %s failed (%s); using the built-in one.", path, error)
    return _fill(_environment((BUILTIN_DIR,)), card, builtin, data)
