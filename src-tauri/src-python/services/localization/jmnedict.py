"""Readings of Japanese place names from JMnedict, the names dictionary jisho.org's name search uses.

Downloaded once (about 12 MB) into the shared cache, then reduced to place, station, organisation and
unclassified names (the types temples and mountains come under) and kept as a small index. Lookups are
offline. JMnedict is the property of the Electronic Dictionary Research and Development Group and is used
under its licence (CC BY-SA 4.0); the credit is in Settings > About.
"""

import gzip
import json
import time
import urllib.request
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, List, Optional

from services.logger.logger import setup_logger
from services.projectfiles import dictionary_cache_dir

logger = setup_logger("JMnedict")

SOURCE_URL = "http://ftp.edrdg.org/pub/Nihongo/JMnedict.xml.gz"
KEPT_TYPES = {"place name", "railway station", "unclassified name", "organization name"}
RETRY_AFTER_SECONDS = 24 * 3600  # a failed download is not tried again on every scan
MIN_PREFIX_CHARS = 2


def _index_path() -> Path:
    return dictionary_cache_dir() / "jmnedict_places.json.gz"


def build_index(source: Path, target: Path) -> int:
    """Kanji spelling -> its readings (place-like names only). Returns how many spellings were kept."""
    index: Dict[str, List[str]] = {}
    with gzip.open(source, "rb") as f:
        for _, entry in ET.iterparse(f, events=("end",)):
            if entry.tag != "entry":
                continue
            types = {t.text for t in entry.iter("name_type")}
            if types & KEPT_TYPES:
                kanji = [k.text for k in entry.iter("keb") if k.text]
                for r in entry.findall("r_ele"):
                    reading = r.findtext("reb")
                    only = {x.text for x in r.findall("re_restr")}
                    for k in kanji:
                        if reading and (not only or k in only) and reading not in index.setdefault(k, []):
                            index[k].append(reading)
            entry.clear()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as out:
        json.dump(index, out, ensure_ascii=False, separators=(",", ":"))
    tmp.replace(target)
    return len(index)


def ensure_index(download: Callable[[str, Path], None] = None) -> Optional[Path]:
    """The index, downloading and building it the first time. None when that isn't possible (offline)."""
    target = _index_path()
    if target.exists():
        return target
    failed = dictionary_cache_dir() / ".download_failed"
    if failed.exists() and time.time() - failed.stat().st_mtime < RETRY_AFTER_SECONDS:
        return None
    source = dictionary_cache_dir() / "JMnedict.xml.gz"
    try:
        if not source.exists():
            source.parent.mkdir(parents=True, exist_ok=True)
            (download or _download)(SOURCE_URL, source)
        count = build_index(source, target)
        logger.info("JMnedict place-name index built: %d spellings.", count)
        failed.unlink(missing_ok=True)
        return target
    except Exception as exc:
        logger.warning("JMnedict is not available, place names use MeCab readings only: %s", exc)
        failed.parent.mkdir(parents=True, exist_ok=True)
        failed.write_text(str(exc), encoding="utf-8")
        return None


def _download(url: str, target: Path) -> None:
    tmp = target.with_suffix(".part")
    request = urllib.request.Request(url, headers={"User-Agent": "Navivi"})
    with urllib.request.urlopen(request, timeout=120) as response, open(tmp, "wb") as out:
        while chunk := response.read(1 << 16):
            out.write(chunk)
    tmp.replace(target)


@lru_cache(maxsize=1)
def _index() -> Dict[str, List[str]]:
    path = ensure_index()
    if path is None:
        return {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def readings(name: str) -> List[str]:
    return list(_index().get(name, []))


def place_reading(name: str, guess: Optional[str], read_rest: Callable[[str], Optional[str]]) -> Optional[str]:
    """The reading of `name`: JMnedict's own (the one matching `guess` when it lists several), else the longest
    name it knows at the start (南海本線 + 孝子駅, 鳴滝不動 + 尊), the rest read the same way. `guess` is the analyser's
    reading of the whole name; a one-kanji rest takes its part of it (尊 alone would read みこと). A start the guess disagrees with is
    skipped: it is often another name sharing the kanji (神福 = かみふく would make 神福寺跡 かみふくてらあと, not しんぷくじあと).
    None when it knows nothing."""
    found = readings(name)
    if found:
        return guess if guess in found else found[0]
    for end in range(len(name) - 1, MIN_PREFIX_CHARS - 1, -1):
        head = readings(name[:end])
        if not head:
            continue
        agreed = min((h for h in head if guess and guess.startswith(h)), key=len, default=None)
        if guess and agreed is None:
            continue
        rest_guess = guess[len(agreed):] if agreed else None
        rest_name = name[end:]
        if len(rest_name) >= MIN_PREFIX_CHARS:
            # The analyser can glue a kana onto the start (葛城 = かつらぎの): the rest's own reading drops it.
            own = read_rest(rest_name)
            if rest_guess and own and rest_guess != own and rest_guess.endswith(own):
                rest_guess = own
            rest = place_reading(rest_name, rest_guess, read_rest) or rest_guess or read_rest(rest_name)
        else:
            rest = rest_guess or read_rest(rest_name)
        return (agreed or head[0]) + rest if rest is not None else None
    return None
