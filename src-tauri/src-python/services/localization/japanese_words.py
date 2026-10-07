"""Words that contain kanji, with their readings, for the pronunciation dictionary.

A morphological analyser (fugashi + UniDic) splits the text into real words, so a verb such as
透き通る stays whole (and gets its reading from the dictionary) instead of becoming 透 and 通.
Runs of nouns are joined (三 + 段 + 壁 -> 三段壁), and て / た are kept on the verb or adjective they
follow (透き通った), because the pronunciation dictionary replaces text exactly as written.
Without the analyser installed everything falls back to pykakasi's word guesses.
"""

import re
from functools import lru_cache
from typing import Dict, Iterable, List, Optional

# Endings with one reading, kept in kanji after a spelled-out name (サルサカ峠, not サルサカトウゲ): a shorter katakana run, which the
# voice slurs less.
PLAIN_SUFFIXES = {"展望台": "てんぼうだい", "神社": "じんじゃ", "公園": "こうえん", "海岸": "かいがん", "温泉": "おんせん", "峠": "とうげ", "駅": "えき"}

_NOUNISH = {"名詞", "接頭辞", "接尾辞"}
_CONTENT = {"動詞", "形容詞", "形状詞", "副詞", "連体詞", "接続詞", "感動詞", "代名詞"}
_ATTACHED = {"て", "で", "た", "だ"}


def _is_kanji(ch: str) -> bool:
    return "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿" or ch == "々"


def has_kanji(text: str) -> bool:
    return any(_is_kanji(c) for c in text)


def to_hiragana(text: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)


def to_katakana(text: str) -> str:
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in text)


@lru_cache(maxsize=1)
def _tagger():
    try:
        import fugashi

        return fugashi.Tagger()
    except Exception:  # not installed, or its dictionary is missing
        return None


@lru_cache(maxsize=1)
def _kakasi():
    import pykakasi

    return pykakasi.kakasi()


def _kakasi_reading(text: str) -> str:
    return "".join(item["hira"] for item in _kakasi().convert(text))


def _pos(token) -> str:
    return getattr(token.feature, "pos1", "") or ""


def _nounish(token) -> bool:
    return _pos(token) in _NOUNISH


def _single_kanji_between_nouns(tokens, k: int) -> bool:
    """A lone kanji the dictionary took for a verb or adjective in the middle of a name (白良浜 -> 白, 良, 浜)."""
    token = tokens[k]
    return (
        len(token.surface) == 1
        and _is_kanji(token.surface)
        and 0 < k < len(tokens) - 1
        and _nounish(tokens[k - 1])
        and _nounish(tokens[k + 1])
    )


def _group_reading(group) -> str:
    kana = [getattr(t.feature, "kana", None) for t in group]
    if all(kana) and all(k != "*" for k in kana):
        return to_hiragana("".join(kana))
    return _kakasi_reading("".join(t.surface for t in group))


def analyze_words(text: str) -> List[Dict[str, str]]:
    """Kanji-bearing words of `text` in order of first appearance, each as {"word", "reading"}."""
    tagger = _tagger()
    if not text or tagger is None:
        return _fallback_words(text or "")

    tokens = list(tagger(text))
    groups: List[list] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        pos = _pos(token)
        if pos in _NOUNISH:
            group = [token]
            while i + 1 < len(tokens) and (_nounish(tokens[i + 1]) or _single_kanji_between_nouns(tokens, i + 1)):
                i += 1
                group.append(tokens[i])
            groups.append(group)
        elif pos in _CONTENT:
            group = [token]
            if pos in ("動詞", "形容詞"):
                while i + 1 < len(tokens) and tokens[i + 1].surface in _ATTACHED:
                    i += 1
                    group.append(tokens[i])
            groups.append(group)
        i += 1

    seen = set()
    words: List[Dict[str, str]] = []
    for group in groups:
        surface = "".join(t.surface for t in group)
        if surface in seen or not has_kanji(surface):
            continue
        seen.add(surface)
        words.append({"word": surface, "reading": ruins_reading(surface, _group_reading(group))})
    return words


_PLACE_KINDS = {"地名", "一般"}  # proper nouns that aren't people's names


def _is_place(token) -> bool:
    return getattr(token.feature, "pos2", "") == "固有名詞" and getattr(token.feature, "pos3", "") in _PLACE_KINDS


def analyze_place_words(text: str, names: Iterable[str] = ()) -> List[Dict[str, str]]:
    """Place names in `text`, each as {"word", "reading"}: the project's own place `names` that it mentions,
    then any word the analyser tags as a proper noun (not a person's name). Readings come from JMnedict first."""
    words: List[Dict[str, str]] = []
    seen = set()
    for name in sorted({n.strip() for n in names if n and n.strip()}, key=text.find):
        if name in text and has_kanji(name) and name not in seen:
            seen.add(name)
            words.append({"word": name, "reading": _name_reading(name)})
    tagger = _tagger()
    if text and tagger is not None:
        proper = {t.surface for t in tagger(text) if _is_place(t)}
        for entry in analyze_words(text):
            if entry["word"] not in seen and any(p in entry["word"] for p in proper):
                seen.add(entry["word"])
                words.append({"word": entry["word"], "reading": _place_reading(entry["word"], entry["reading"])})
    return words


_NAME_PARTS = re.compile(r"([\s（）()「」『』【】・]+)")


def _name_reading(name: str) -> str:
    """Each part of a name looked up on its own, so 西念寺（二ノ宿観音堂） and 孝子駅 (GOAL) still find 西念寺 and 孝子駅 in JMnedict.
    A part's guess is the analyser's reading of it inside the whole name (alone, 葛城 reads かつらぎの)."""
    in_context = _context_readings(name)
    out, pos = [], 0
    for part in _NAME_PARTS.split(name):
        if has_kanji(part):
            out.append(_place_reading(part, in_context.get((pos, pos + len(part))) or reading_of(part)))
        else:
            out.append(part)
        pos += len(part)
    return "".join(out)


def _context_readings(text: str) -> Dict[tuple, str]:
    """(start, end) -> reading for each run of whole tokens between separators, as the analyser read them in `text`."""
    tagger = _tagger()
    if tagger is None:
        return {}
    spans: Dict[tuple, str] = {}
    start, kana, pos = None, [], 0
    for token in tagger(text):
        at = text.find(token.surface, pos)
        reading = getattr(token.feature, "kana", None)
        if at < 0 or _NAME_PARTS.fullmatch(token.surface) or not reading or reading == "*":
            start, kana = None, []
            pos = max(pos, at + len(token.surface)) if at >= 0 else pos
            continue
        if start is None or at != pos:
            start, kana = at, []
        kana.append(reading)
        pos = at + len(token.surface)
        spans[(start, pos)] = to_hiragana("".join(kana))
    return spans


def _place_reading(name: str, guess: Optional[str]) -> str:
    """JMnedict's reading of a place (札立山 -> ふだたてやま where MeCab says さつたてやま), else the analyser's."""
    from services.localization import jmnedict

    return ruins_reading(name, jmnedict.place_reading(name, guess, reading_of) or guess or "")


# A building whose ruins are named "<name><building>跡": the 跡 reads あと (神福寺跡 = しんぷくじあと), unlike 遺跡 or 史跡.
_RUINED_BUILDINGS = set("寺院城邸宮社庵坊堂館陣関駅宅塔門")


def ruins_reading(word: str, reading: str) -> str:
    """The analyser takes 寺跡 for one word and reads it じせき; after a building, 跡 is あと."""
    if len(word) > 2 and word.endswith("跡") and word[-2] in _RUINED_BUILDINGS and reading.endswith("せき"):
        return reading[: -len("せき")] + "あと"
    return reading


def _fallback_words(text: str) -> List[Dict[str, str]]:
    """Without the analyser: pykakasi's own word boundaries, merged where a kanji word is followed by its okurigana."""
    out: List[Dict[str, str]] = []
    seen = set()
    for item in _kakasi().convert(text):
        word = item["orig"]
        if has_kanji(word) and word not in seen:
            seen.add(word)
            out.append({"word": word, "reading": item["hira"]})
    return out


# Words the dictionary reads wrong in prose: 歩 alone is the shogi piece ふ to it, but 歩を進める is ほ.
_PRON_FIXES = {"歩": "ホ"}


def spoken_kana(text: str) -> str:
    """`text` with every kanji word replaced by how it is said, in katakana (漂う -> タダヨウ, 空間 -> クーカン), so an engine that
    guesses kanji readings speaks each syllable as written. A counter after a number keeps its kanji (1分 is いっぷん, not 1フン)."""
    tagger = _tagger()
    if not text or tagger is None:
        return text
    out, pos = [], 0
    for token in tagger(text):
        at = text.find(token.surface, pos)
        if at < 0:
            continue
        out.append(text[pos:at])
        pron = _PRON_FIXES.get(token.surface) or getattr(token.feature, "pron", None)
        after_number = at > 0 and text[at - 1].isdigit()
        if has_kanji(token.surface) and pron and pron != "*" and not after_number:
            out.append(pron)
        else:
            out.append(token.surface)
        pos = at + len(token.surface)
    out.append(text[pos:])
    return "".join(out)


def reading_of(word: str) -> Optional[str]:
    """The reading of one word or phrase, as written."""
    if not word:
        return None
    tagger = _tagger()
    if tagger is not None:
        tokens = [t for t in tagger(word) if t.surface.strip()]
        kana = [getattr(t.feature, "kana", None) for t in tokens]
        if tokens and all(kana) and all(k != "*" for k in kana):
            return to_hiragana("".join(kana))
    return _kakasi_reading(word)
