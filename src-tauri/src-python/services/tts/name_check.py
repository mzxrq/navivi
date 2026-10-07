"""Hears a narration take back and lists the place names the voice got wrong (サルサカ峠 spoken as さらさかとうげ).

The names are the katakana the pronunciation dictionary put into the line, with a plain kanji ending (峠, 神社, ...). The take is
transcribed with faster-whisper on the CPU. A name counts as heard as often as the transcript has its original spelling
(木ノ本 written 木の本) or its reading, read back by MeCab or pykakasi; voicing marks and long-vowel bars are ignored, so 坂 heard
as ざか is not a miss. The recogniser writes a misheard name in kana (さらさか峠), which no reading turns back into the name; a
homophone written in other kanji (西年寺 for 西念寺) is a false miss and only costs a retake. Without faster-whisper installed
nothing is checked.
"""

import io
import re
import unicodedata
from functools import lru_cache
from typing import Dict, List, Tuple

from services import tuning
from services.localization import japanese_words
from services.logger.logger import setup_logger

logger = setup_logger("NameCheck")

_originals: Dict[str, str] = {}  # spelled-out name -> how the script writes it, filled by apply_pronunciation_dictionary


_kanji_names: Dict[str, Tuple[str, str]] = {}  # name left in kanji -> (its reading, how a retake spells it out)


def remember(spoken: str, word: str) -> None:
    _originals[spoken] = word


def remember_kanji(word: str, reading: str, spoken: str) -> None:
    _kanji_names[word] = (reading, spoken)


def spell_out(text: str, names: List[str]) -> str:
    """`text` with the kanji names among `names` spelled out, for a retake after the voice misread them."""
    for name in sorted(names, key=len, reverse=True):
        if name in _kanji_names:
            spoken = _kanji_names[name][1]
            remember(spoken, name)
            text = text.replace(name, spoken)
    return text


def _kanji_form(text: str) -> str:
    return re.sub(r"[\s、。，．・「」（）()]", "", text).replace("ノ", "の").replace("ヶ", "が").replace("ケ", "が")


_SUFFIXES = "|".join(sorted(japanese_words.PLAIN_SUFFIXES, key=len, reverse=True))
_NAME = re.compile(r"([ァ-ヺー]{2,})(%s)?" % _SUFFIXES)


def expected_names(text: str) -> List[tuple]:
    """(name as written, its reading) for each place name in `text`: the spelled-out ones, then those left in kanji."""
    names = []
    for m in _NAME.finditer(text):
        if not m.group(2) and len(m.group(1).replace("ー", "")) < tuning.TTS_NAME_CHECK_MIN_CHARS:
            continue
        reading = japanese_words.to_hiragana(m.group(1)) + japanese_words.PLAIN_SUFFIXES.get(m.group(2) or "", "")
        if (m.group(0), reading) not in names:
            names.append((m.group(0), reading))
    for word, (reading, _) in sorted(_kanji_names.items(), key=lambda item: -len(item[0])):
        if word in text and not any(word in name for name, _ in names):
            names.append((word, reading))
    return names


def _plain(kana: str) -> str:
    """Hiragana without voicing marks, long-vowel bars or anything that isn't kana."""
    bare = "".join(c for c in unicodedata.normalize("NFD", japanese_words.to_hiragana(kana)) if c not in "゙゚")
    return "".join(c for c in unicodedata.normalize("NFC", bare) if "ぁ" <= c <= "ゖ")


def _reading_of_transcript(text: str) -> str:
    tagger = japanese_words._tagger()
    if tagger is None:
        return japanese_words.reading_of(text) or ""
    parts = []
    for token in tagger(text):
        kana = getattr(token.feature, "kana", None)
        parts.append(kana if kana and kana != "*" else token.surface)
    return "".join(parts)


@lru_cache(maxsize=1)
def _model():
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        logger.info("faster-whisper is not installed; narration takes are not checked for misread place names.")
        return None
    logger.info("Loading the speech recogniser %s (CPU) to check place names.", tuning.TTS_NAME_CHECK_MODEL)
    return WhisperModel(tuning.TTS_NAME_CHECK_MODEL, device="cpu", compute_type="int8")


def transcribe(audio: bytes) -> str:
    model = _model()
    if model is None:
        return ""
    segments, _ = model.transcribe(io.BytesIO(audio), language="ja", beam_size=5, chunk_length=15, condition_on_previous_text=False)
    return "".join(s.text for s in segments)


def misheard_names(audio: bytes, text: str) -> List[str]:
    """The names in `text` the take does not say, or [] when they are all heard (or nothing can be checked)."""
    names = expected_names(text)
    if not names or not tuning.TTS_NAME_CHECK:
        return []
    try:
        heard_text = transcribe(audio)
    except Exception as exc:  # a broken model must never stop the narration
        logger.warning("Place-name check skipped: %s", exc)
        return []
    if not heard_text:
        return []
    readings = [_plain(_reading_of_transcript(heard_text)), _plain(japanese_words._kakasi_reading(heard_text))]
    written = _kanji_form(heard_text)
    missing = []
    for name, reading in names:
        original = _kanji_form(_originals.get(name) or (name if name in _kanji_names else ""))
        times_heard = max([r.count(_plain(reading)) for r in readings] + [written.count(original) if original else 0])
        if times_heard < text.count(name):
            missing.append(name)
    if missing:
        logger.warning("Place names not heard in the take: %s (heard: %s)", ", ".join(missing), heard_text)
    return missing
