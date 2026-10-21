"""Cue times measured from what the voice said (segments given here, no recogniser)."""

from services.localization import cue_alignment
from services.localization.cue_alignment import align_cue_times, measured_cue_times
from services.localization.cues import strip_cues

SCRIPT = "こんにちは、旅の始まりです。{start}これが全体のルートです。{1}最初は中村家住宅です。{2}次は郵便名柄館です。"
# the voice: a long opening, then three sentences a few seconds apart
HEARD = [
    (0.0, 6.0, "こんにちは、旅の始まりです。"),
    (6.5, 10.0, "これが全体のルートです。"),
    (12.0, 16.0, "最初は中村家住宅です。"),
    (19.0, 23.0, "次は郵便名柄館です。"),
]


def test_each_cue_gets_the_second_its_sentence_is_said():
    clean, cues = strip_cues(SCRIPT)
    times = align_cue_times(clean, cues, HEARD)
    assert abs(times["start"] - 6.5) < 1.5
    assert abs(times["1"] - 12.0) < 2.0
    assert abs(times["2"] - 19.0) < 2.0


def test_a_text_that_does_not_match_is_not_trusted():
    clean, cues = strip_cues(SCRIPT)
    assert align_cue_times(clean, cues, [(0.0, 5.0, "まったく別の話をしています")]) is None


def test_measured_times_fall_back_to_the_estimate(tmp_path, monkeypatch):
    clean, cues = strip_cues(SCRIPT)
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    monkeypatch.setattr(cue_alignment.tuning, "ALIGN_CUES_TO_VOICE", True)
    monkeypatch.setattr(cue_alignment, "_segments", lambda path: None)  # no recogniser
    estimate = measured_cue_times(audio, cues, clean, 23.0, [], enabled=False)
    assert measured_cue_times(audio, cues, clean, 23.0, []) == estimate


def test_measured_times_are_used_when_the_voice_was_heard(tmp_path, monkeypatch):
    clean, cues = strip_cues(SCRIPT)
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    monkeypatch.setattr(cue_alignment.tuning, "ALIGN_CUES_TO_VOICE", True)
    monkeypatch.setattr(cue_alignment, "_segments", lambda path: HEARD)
    times = measured_cue_times(audio, cues, clean, 23.0, [])
    # sentence-start cues land exactly on the heard sentence starts
    assert (times["start"], times["1"], times["2"]) == (6.5, 12.0, 19.0)
