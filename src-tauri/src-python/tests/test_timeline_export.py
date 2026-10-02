import subprocess

import pytest

from services.tts.ttsengine import FFmpegManager
from services.vdoprocessing.vdoexporter import VideoExporter

FFMPEG = VideoExporter.resolve_ffmpeg()
pytestmark = pytest.mark.skipif(not FFMPEG, reason="ffmpeg not available")


def _run(*args):
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", *args], check=True)


@pytest.fixture
def media(tmp_path):
    for name, color in (("a.mp4", "red"), ("b.mp4", "blue")):
        _run("-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=30:d=4", "-pix_fmt", "yuv420p", str(tmp_path / name))
    _run("-f", "lavfi", "-i", "sine=frequency=440:duration=2", str(tmp_path / "voice.wav"))
    _run("-f", "lavfi", "-i", "sine=frequency=220:duration=1", str(tmp_path / "music.wav"))
    return tmp_path


def _has_audio(path):
    out = subprocess.run([FFMPEG, "-i", str(path)], capture_output=True, text=True).stderr
    return "Audio:" in out


def test_trim_and_music_and_subtitles(media):
    timeline = {
        "video_tracks": [
            {"file_path": str(media / "a.mp4"), "audio_path": str(media / "voice.wav"), "trim_in": 1.0, "trim_out": 3.0},
            {"file_path": str(media / "b.mp4"), "muted": True, "audio_path": str(media / "voice.wav")},
        ],
        "music": {"path": str(media / "music.wav"), "volume": 0.3},
        "subtitles": [{"start": 0.0, "end": 1.0, "text": "hello"}],
        "burn_subtitles": False,
    }
    out = media / "out.mp4"
    VideoExporter.concat_from_timeline(timeline, str(out))
    duration = FFmpegManager.get_media_duration(str(out))
    # 2s trimmed clip (voice 2s + hold) + 4s clip
    assert 5.8 < duration < 6.8
    assert _has_audio(out)


def test_cues_to_srt_sorted():
    srt = VideoExporter.cues_to_srt([{"start": 5, "end": 6, "text": "b"}, {"start": 1, "end": 2, "text": "a"}])
    assert srt.startswith("1\n00:00:01,000 --> 00:00:02,000\na")


def test_editor_durations_make_the_export_as_long_as_the_preview(media):
    # Preview lengths: max(trimmed video, offset + voice) -> 2.5 and 4.0, no tail hold.
    timeline = {
        "video_tracks": [
            {"file_path": str(media / "a.mp4"), "audio_path": str(media / "voice.wav"),
             "audio_offset": 0.5, "trim_in": 2.0, "duration": 2.5},
            {"file_path": str(media / "b.mp4"), "duration": 4.0},
        ],
        "subtitles": [{"start": 0.5, "end": 2.0, "text": "ようこそ。"}],
        "burn_subtitles": True,
    }
    out = media / "out.mp4"
    VideoExporter.concat_from_timeline(timeline, str(out))
    assert abs(FFmpegManager.get_media_duration(str(out)) - 6.5) < 0.15
    assert _has_audio(out)
