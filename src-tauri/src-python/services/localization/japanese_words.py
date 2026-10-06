"""Words that contain kanji, with their readings, for the pronunciation dictionary.

A morphological analyser (fugashi + UniDic) splits the text into real words, so a verb such as
透き通る stays whole (and gets its reading from the dictionary) instead of becoming 透 and 通.
Runs of nouns are joined (三 + 段 + 壁 -> 三段壁), and て / た are kept on the verb or adjective they
follow (透き通った), because the pronunciation dictionary replaces text exactly as written.
Without the analyser installed everything falls back to pykakasi's word guesses.
"""

from functools import lru_cache
from typing import Dict, Iterable, List, Optional

_NOUNISH = {"名詞", "接頭辞", "接尾辞"}
_CONTENT = {"動詞", "形容詞", "形状詞", "副詞", "連体詞", "接続詞", "感動詞", "代名詞"}
_ATTACHED = {"て", "で", "た", "だ"}


def _is_kanji(ch: str) -> bool:
    return "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿" or ch == "々"


def has_kanji(text: str) -> bool:
    return any(_is_kanji(c) for c in text)


def to_hiragana(text: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)


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
        words.append({"word": surface, "reading": _group_reading(group)})
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
            words.append({"word": name, "reading": _place_reading(name, reading_of(name))})
    tagger = _tagger()
    if text and tagger is not None:
        proper = {t.surface for t in tagger(text) if _is_place(t)}
        for entry in analyze_words(text):
            if entry["word"] not in seen and any(p in entry["word"] for p in proper):
                seen.add(entry["word"])
                words.append({"word": entry["word"], "reading": _place_reading(entry["word"], entry["reading"])})
    return words


def _place_reading(name: str, guess: Optional[str]) -> str:
    """JMnedict's reading of a place (札立山 -> ふだたてやま where MeCab says さつたてやま), else the analyser's."""
    from services.localization import jmnedict

    return jmnedict.place_reading(name, guess, reading_of) or guess or ""


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
