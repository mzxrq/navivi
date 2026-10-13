from pathlib import Path

from services import tuning
from services.tts.ttsengine import FFmpegManager
from services.vdoprocessing import slow_move
from services.vdoprocessing.img2vdo import AttractionVideoGenerator


def _run(monkeypatch, tmp_path, clip_seconds, target):
    calls = {}
    monkeypatch.setattr(tuning, "ATTRACTION_SLOW_MOVE_STYLE", "photo")
    monkeypatch.setattr(FFmpegManager, "get_media_duration", staticmethod(lambda _p: clip_seconds))

    def extend(src, target_duration, pan, out, photo_path=None):
        calls["src"], calls["target"] = src, target_duration
        return out

    monkeypatch.setattr(slow_move, "extend_with_slow_move", extend)
    gen = AttractionVideoGenerator.__new__(AttractionVideoGenerator)
    gen.editor = type("E", (), {"trim_video_duration": lambda *a: calls.setdefault("trimmed", True)})()
    result = gen._end_on_photo("clip.mp4", target, "zoomin", "photo.jpg", Path(tmp_path) / "out.mp4")
    return result, calls


def test_the_whole_animation_plays_before_the_photo(monkeypatch, tmp_path):
    result, calls = _run(monkeypatch, tmp_path, clip_seconds=5.0, target=6.0)
    assert result and calls["src"] == "clip.mp4" and "trimmed" not in calls


def test_an_animation_longer_than_the_narration_gets_no_photo(monkeypatch, tmp_path):
    result, calls = _run(monkeypatch, tmp_path, clip_seconds=8.0, target=6.0)
    assert result is None and not calls
