import json
import os
import subprocess

import pytest

from services.config.job_config import JobConfigManager
from services.tts.ttsengine import FFmpegManager
from services.vdoprocessing.img2vdo import AttractionVideoGenerator
from services.vdoprocessing.user_videos import original_sound_path, process_user_videos
from services.vdoprocessing.vdoexporter import VideoExporter

FFMPEG = VideoExporter.resolve_ffmpeg()
pytestmark = pytest.mark.skipif(not FFMPEG, reason="ffmpeg not available")


def _run(*args):
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", *args], check=True)


@pytest.fixture
def project(tmp_path):
    (tmp_path / "job_config.json").write_text(json.dumps({"directory_path": str(tmp_path), "waypoints": [], "settings": {}}), encoding="utf-8")
    clip = tmp_path / "mine.mp4"
    _run("-f", "lavfi", "-i", "testsrc=s=320x180:r=25:d=3", "-f", "lavfi", "-i", "sine=frequency=330:duration=3",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip))
    generator = AttractionVideoGenerator(job_config=JobConfigManager(tmp_path / "job_config.json"))
    return generator, clip


def _has_audio(path):
    return "Audio:" in subprocess.run([FFMPEG, "-i", str(path)], capture_output=True, text=True).stderr


def test_footage_is_fitted_and_silent_by_default(project):
    generator, clip = project
    out = process_user_videos(generator, [str(clip)], [False], 5.0, "04_attraction_00_x.mp4", place_label="x")
    assert out and os.path.exists(out)
    assert 4.8 < FFmpegManager.get_media_duration(out) < 5.3
    assert not original_sound_path(out).exists()
    assert not _has_audio(out)


def test_keep_sound_writes_a_sidecar_the_exporter_mixes(project, tmp_path):
    generator, clip = project
    out = process_user_videos(generator, [str(clip)], [True], 4.0, "04_attraction_01_x.mp4")
    sidecar = original_sound_path(out)
    assert sidecar.exists()
    assert abs(FFmpegManager.get_media_duration(str(sidecar)) - FFmpegManager.get_media_duration(out)) < 0.3

    exported = tmp_path / "out.mp4"
    VideoExporter.concat_from_timeline(
        {"video_tracks": [{"file_path": out, "extra_audio_path": str(sidecar), "extra_audio_volume": 0.5}]}, str(exported)
    )
    assert _has_audio(exported)


def test_unchanged_footage_is_not_rebuilt_and_toggle_invalidates(project):
    generator, clip = project
    out = process_user_videos(generator, [str(clip)], [False], 4.0, "04_attraction_02_x.mp4")
    first = os.stat(out).st_mtime_ns
    assert process_user_videos(generator, [str(clip)], [False], 4.0, "04_attraction_02_x.mp4") == out
    assert os.stat(out).st_mtime_ns == first
    process_user_videos(generator, [str(clip)], [True], 4.0, "04_attraction_02_x.mp4")
    assert original_sound_path(out).exists()


def test_two_clips_are_combined(project):
    generator, clip = project
    out = process_user_videos(generator, [str(clip), str(clip)], [False, True], 6.0, "04_attraction_03_x.mp4")
    assert out and 5.5 < FFmpegManager.get_media_duration(out) < 6.5
    assert original_sound_path(out).exists()


def _mean_db(path, start, length):
    err = subprocess.run(
        [FFMPEG, "-ss", str(start), "-t", str(length), "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    return float(err.split("mean_volume:")[1].split("dB")[0])


def test_footage_sound_follows_the_trim(tmp_path):
    video, sound = tmp_path / "v.mp4", tmp_path / "v.original.m4a"
    _run("-f", "lavfi", "-i", "testsrc=s=320x180:r=25:d=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video))
    # Silent for 2s, then a tone: trimming the first 2s off must start on the tone.
    _run("-f", "lavfi", "-i", r"aevalsrc=if(lt(t\,2)\,0\,0.5*sin(2*PI*440*t)):d=4", "-c:a", "aac", str(sound))
    exported = tmp_path / "out.mp4"
    VideoExporter.concat_from_timeline(
        {"video_tracks": [{
            "file_path": str(video), "extra_audio_path": str(sound), "extra_audio_volume": 1.0,
            "trim_in": 2.0, "trim_out": 4.0, "duration": 3.0,
        }]},
        str(exported),
    )
    assert _mean_db(exported, 0.2, 1.5) > -30
    # The held last frame is silent, like the preview.
    assert _mean_db(exported, 2.3, 0.6) < -60

