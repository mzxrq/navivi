"""High/low pattern of one word in a voice take, to keep the take whose intonation matches the one asked for.

A pattern is one letter per mora of the word's reading: H (high) or L (low), e.g. かつらぎ "LHHH"; a Latin reading
(an English line) has one per syllable, e.g. Katsuragi (ka-tsu-ra-gi) "LHLL". The word is
found in the take by its share of the sentence's kana over the voiced stretch (sentence takes are short, so this
is close enough), the pitch is measured per mora, and the pattern read off it is compared with the one asked for.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

import numpy as np

SMALL_KANA = set("ゃゅょぁぃぅぇぉゎャュョァィゥェォヮ")
F0_MIN, F0_MAX = 70.0, 450.0
HOP_SECONDS = 0.01
# A step between two morae smaller than this (semitones) reads as level.
LEVEL_SEMITONES = 0.6
_patterns: Dict[str, str] = {}  # a dictionary word as the voice is sent it (kana) -> its pattern
_SPOKEN = re.compile(r"^(?:[ぁ-ヿ]+|[A-Za-z' -]+)$")


def remember(spoken: str, pattern: Optional[str]) -> None:
    if pattern and _SPOKEN.match(spoken or "") and valid_pattern(pattern, spoken):
        _patterns[spoken] = pattern.upper()


def wanted(text: str) -> List[Tuple[str, str]]:
    return sorted((w, p) for w, p in _patterns.items() if w in text)


def sentence_kana(text: str) -> str:
    """The line as kana only (kanji words read out, punctuation and Latin dropped), to place a word among its morae;
    an English line keeps its words."""
    from services.localization.japanese_words import spoken_kana
    from services.localization.localization import is_japanese

    if not is_japanese(text):
        return " ".join(re.findall(r"[A-Za-z']+", text))
    return re.sub(r"[^ぁ-ヿ]", "", spoken_kana(text))


def score_take(audio: bytes, kana: str, words: List[Tuple[str, str]]) -> float:
    """The worst score among every occurrence of the wanted words in one take (1 = all follow their pattern)."""
    import io

    scores = []
    for word, pattern in words:
        n = 0
        while (r := check_take(io.BytesIO(audio), kana, word, pattern, n)) is not None:
            scores.append(r["score"])
            n += 1
    return min(scores, default=1.0)


def syllables(word: str) -> List[str]:
    """katsuragi -> [ka, tsu, ra, gi]: one per vowel group (Kobe is ko-be; a reading is spelled as it is said)."""
    w = word.lower()
    parts = re.findall(r"(?:[^aeiouy]|y(?=[aeiou]))*(?:[aeiou]|y(?![aeiou]))+", w)  # y before a vowel is a consonant (koyasan, kyoto)
    if not parts:
        return [w]
    parts[-1] += w[len("".join(parts)):]
    return parts


def morae(text: str) -> List[str]:
    """かつらぎ -> [か, つ, ら, ぎ]; a small ゃ/ゅ/ょ joins the kana before it, っ ん ー are morae of their own.
    Latin words count by syllable; anything else (spaces, punctuation, kanji) is left out."""
    out: List[str] = []
    for tok in re.findall(r"[A-Za-z']+|[ぁ-ヿ]", text):
        if tok[0].isascii():
            out += syllables(tok)
        elif tok in SMALL_KANA and out:
            out[-1] += tok
        else:
            out.append(tok)
    return out


def valid_pattern(pattern: str, reading: str) -> bool:
    return bool(re.fullmatch(r"[HLhl]+", pattern or "")) and len(pattern) == len(morae(reading))


def f0_track(samples: np.ndarray, rate: int) -> np.ndarray:
    """Pitch in Hz every HOP_SECONDS (0 = unvoiced), by normalised autocorrelation on 40 ms frames."""
    samples = samples.astype(np.float64)
    frame, hop = int(0.04 * rate), int(HOP_SECONDS * rate)
    lo, hi = int(rate / F0_MAX), int(rate / F0_MIN)
    loud = np.sqrt(np.mean(samples ** 2)) or 1.0
    out = []
    for start in range(0, max(1, len(samples) - frame), hop):
        x = samples[start:start + frame]
        x = x - x.mean()
        energy = np.dot(x, x)
        if len(x) < frame or np.sqrt(energy / frame) < 0.25 * loud:
            out.append(0.0)
            continue
        ac = np.correlate(x, x, "full")[frame - 1:]
        norm = ac[lo:hi] / energy
        lag = int(np.argmax(norm))
        out.append(rate / (lo + lag) if norm[lag] > 0.5 else 0.0)
    return np.array(out)


def word_frames(f0: np.ndarray, sentence_kana: str, word_kana: str, occurrence: int = 0) -> Optional[np.ndarray]:
    """Voiced frames of the n-th `word_kana` in the take, from its place among the sentence's morae (pauses,
    which take no morae, are left out first)."""
    sent, word = morae(sentence_kana), morae(word_kana)
    starts = [i for i in range(len(sent) - len(word) + 1) if sent[i:i + len(word)] == word]
    voiced = np.nonzero(f0)[0]
    if occurrence >= len(starts) or not len(voiced):
        return None
    i = starts[occurrence]
    a, b = int(len(voiced) * i / len(sent)), int(len(voiced) * (i + len(word)) / len(sent))
    return voiced[a:max(b, a + 1)]


def measured_pattern(f0: np.ndarray, frames: np.ndarray, n: int) -> List[Optional[float]]:
    """Median pitch of each of the word's `n` morae in semitones (None for a mora with no voiced frame)."""
    out = []
    for part in np.array_split(f0[frames], n):
        out.append(float(12 * np.log2(np.median(part))) if len(part) else None)
    return out


def score(pitches: List[Optional[float]], pattern: str) -> float:
    """How well the steps between neighbouring morae match the pattern's: the share of its rises and falls that
    are there, held down by the share of its level steps that stay level (a wrong rise or fall fails the word)."""
    pattern = pattern.upper()
    pairs = [(p, q, pattern[i], pattern[i + 1]) for i, (p, q) in enumerate(zip(pitches, pitches[1:])) if p is not None and q is not None]
    if not pairs:
        return 0.0
    moves, levels = [], []
    for p, q, x, y in pairs:
        step = q - p
        want = (y == "H") - (x == "H")  # +1 rise, -1 fall, 0 level
        if want > 0:
            moves.append(step > LEVEL_SEMITONES)
        elif want < 0:
            moves.append(step < -LEVEL_SEMITONES)
        else:
            levels.append(abs(step) <= 2 * LEVEL_SEMITONES)
    share = lambda xs: sum(xs) / len(xs) if xs else 1.0
    return min(share(moves), share(levels))


def heard_pattern(pitches: List[Optional[float]]) -> str:
    """The H/L pattern the take actually has (for the log): high = above the word's middle pitch."""
    known = [p for p in pitches if p is not None]
    if not known:
        return "?" * len(pitches)
    mid = (max(known) + min(known)) / 2
    return "".join("?" if p is None else "H" if p > mid else "L" for p in pitches)


def check_take(wav_path, sentence_kana: str, word_kana: str, pattern: str, occurrence: int = 0) -> Optional[dict]:
    """{"score", "heard", "pitches"} for the word in one take; None when the word is not in the sentence."""
    import soundfile as sf

    samples, rate = sf.read(wav_path if hasattr(wav_path, "read") else str(wav_path), always_2d=True)
    f0 = f0_track(samples.mean(axis=1), rate)
    frames = word_frames(f0, sentence_kana, word_kana, occurrence)
    if frames is None:
        return None
    pitches = measured_pattern(f0, frames, len(morae(word_kana)))
    return {"score": round(score(pitches, pattern), 2), "heard": heard_pattern(pitches),
            "pitches": [None if p is None else round(p, 1) for p in pitches]}

