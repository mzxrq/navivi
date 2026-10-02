"""A subtitle built from an earlier take of the narration must be rebuilt (Review > Redo voice)."""

import os

from services.vdoprocessing.videopipeline.helpers import is_newer_than


def _touch(path, text, when_ns):
    path.write_text(text, encoding="utf-8")
    os.utime(path, ns=(when_ns, when_ns))


def test_subtitle_older_than_audio_is_stale(tmp_path):
    audio, srt = tmp_path / "a.wav", tmp_path / "a.srt"
    _touch(srt, "old", 1_000_000_000)
    _touch(audio, "new take", 2_000_000_000)
    assert not is_newer_than(srt, audio)


def test_subtitle_written_after_audio_is_fresh(tmp_path):
    audio, srt = tmp_path / "a.wav", tmp_path / "a.srt"
    _touch(audio, "take", 1_000_000_000)
    _touch(srt, "cues", 2_000_000_000)
    assert is_newer_than(srt, audio)


def test_same_timestamp_counts_as_fresh(tmp_path):
    audio, srt = tmp_path / "a.wav", tmp_path / "a.srt"
    _touch(audio, "take", 1_000_000_000)
    _touch(srt, "cues", 1_000_000_000)
    assert is_newer_than(srt, audio)


def test_missing_file_is_stale(tmp_path):
    assert not is_newer_than(tmp_path / "none.srt", tmp_path / "none.wav")
