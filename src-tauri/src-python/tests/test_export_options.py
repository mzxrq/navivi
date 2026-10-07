import subprocess
from pathlib import Path

import pytest

from services.vdoprocessing.vdoexporter import VideoExporter

FFMPEG = VideoExporter.resolve_ffmpeg()
needs_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg not available")

CUES = [{"start": 0.1, "end": 0.9, "text": "hello"}, {"start": 1.0, "end": 1.8, "text": "  "}]


@pytest.fixture
def clips(tmp_path):
    paths = []
    for i in range(2):
        out = tmp_path / f"c{i}.mp4"
        subprocess.run(
            [FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=s=320x240:r=25:d=1",
             "-pix_fmt", "yuv420p", str(out)],
            check=True,
        )
        paths.append(str(out))
    return paths


def _timeline(clips, **extra):
    tracks = [{"file_path": p, "duration": 1.0} for p in clips]
    return {"video_tracks": tracks, "subtitles": CUES, **extra}


def test_no_options_keep_the_clip_size_and_30_fps():
    tracks = [{"file_path": "x.mp4"}]
    assert VideoExporter._timeline_fps({}) == 30.0
    assert VideoExporter._timeline_fps({"fps": "junk"}) == 30.0
    assert VideoExporter._timeline_fps({"fps": 500}) == 30.0
    assert VideoExporter._timeline_fps({"fps": 24}) == 24.0
    assert VideoExporter._timeline_size({"resolution": {"width": 1920, "height": 1080}}, tracks) == (1920, 1080)


def test_export_height_keeps_the_aspect_and_is_always_even():
    for base in ((1920, 1080), (320, 240), (321, 241), (1080, 1920)):
        for height in (99, 101, 720, 1080, 1440, 2160):
            w, h = VideoExporter._timeline_size(
                {"resolution": {"width": base[0], "height": base[1]}, "export_height": height}, []
            )
            assert w % 2 == 0 and h % 2 == 0 and h in (height, height + 1)
            assert abs(w / h - base[0] / base[1]) < 0.02
    assert VideoExporter._timeline_size({"resolution": {"width": 1920, "height": 1080}, "export_height": 720}, []) == (1280, 720)
    assert VideoExporter._timeline_size({"export_height": 2160}, []) == (3840, 2160)  # nothing to measure: 16:9
    assert VideoExporter._timeline_size({"resolution": {"width": 1920, "height": 1080}, "export_height": "x"}, []) == (1920, 1080)


@needs_ffmpeg
def test_export_applies_height_fps_and_writes_the_srt(clips, tmp_path):
    out = tmp_path / "out.mp4"
    VideoExporter.concat_from_timeline(
        _timeline(clips, export_height=201, fps=24, burn_subtitles=False, save_srt=True), str(out)
    )
    assert VideoExporter._video_size(out) == (268, 202)
    assert abs(VideoExporter._video_fps(out) - 24) < 0.1
    srt = out.with_suffix(".srt").read_text(encoding="utf-8")
    assert "hello" in srt and srt.count("-->") == 1  # the blank cue is left out


@needs_ffmpeg
def test_default_export_is_unchanged_and_writes_no_srt(clips, tmp_path):
    out = tmp_path / "plain.mp4"
    VideoExporter.concat_from_timeline(_timeline(clips), str(out))
    assert VideoExporter._video_size(out) == (320, 240)
    assert abs(VideoExporter._video_fps(out) - 30) < 0.1
    assert not Path(out).with_suffix(".srt").exists()
