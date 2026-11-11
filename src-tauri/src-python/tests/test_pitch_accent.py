import numpy as np

from services.tts import pitch_accent as pa


def _voice(hz_per_mora, rate=16000, mora_s=0.15, gap_s=0.3):
    """A buzzy tone per mora, with silence before and after (as a take has)."""
    parts = [np.zeros(int(gap_s * rate))]
    for hz in hz_per_mora:
        t = np.arange(int(mora_s * rate)) / rate
        parts.append(sum(np.sin(2 * np.pi * hz * k * t) / k for k in range(1, 6)))
    parts.append(np.zeros(int(gap_s * rate)))
    return np.concatenate(parts), rate


def test_morae_join_small_kana():
    assert pa.morae("きょうと") == ["きょ", "う", "と"]
    assert pa.valid_pattern("LHHH", "かつらぎ") and not pa.valid_pattern("LHH", "かつらぎ")


def test_the_pattern_is_read_off_the_pitch():
    samples, rate = _voice([180, 240, 240, 235])
    f0 = pa.f0_track(samples, rate)
    frames = pa.word_frames(f0, "かつらき", "かつらき")
    pitches = pa.measured_pattern(f0, frames, 4)
    assert pa.heard_pattern(pitches) == "LHHH"
    assert pa.score(pitches, "LHHH") == 1.0
    assert pa.score(pitches, "HLLL") == 0.0  # a wrong rise fails the word


def test_the_word_is_found_past_a_pause():
    a, rate = _voice([200, 200, 200, 200])
    b, _ = _voice([250, 180, 180, 180])  # the 2nd word after a pause: HLLL
    f0 = pa.f0_track(np.concatenate([a, b]), rate)
    pitches = pa.measured_pattern(f0, pa.word_frames(f0, "かつらきかつらき", "かつらき", 1), 4)
    assert pa.heard_pattern(pitches) == "HLLL"
