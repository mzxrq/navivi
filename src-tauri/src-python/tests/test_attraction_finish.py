"""The finishing pass of attraction clips: denoise instead of the post-upscale sharpen."""

import subprocess

from services import tuning
from services.tts.ttsengine import FFmpegManager
from services.vdoprocessing.img2vdo import AttractionVideoGenerator
from services.vdoprocessing.vdoexporter import VideoExporter


def test_denoise_runs_before_the_upscale(tmp_path):
    src, out = tmp_path / "in.mp4", tmp_path / "out.mp4"
    subprocess.run([FFmpegManager.resolve_ffmpeg_bin(), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=960x544:rate=24:duration=1", "-pix_fmt", "yuv420p", str(src)], check=True)
    VideoExporter.finalize_clip(str(src), str(out), scale_to=(1920, 1080), denoise=tuning.ATTRACTION_DENOISE)
    assert out.exists() and FFmpegManager.get_media_duration(str(out)) > 0.9


def test_a_changed_finish_refits_kept_clips(monkeypatch):
    before = AttractionVideoGenerator._tail_signature()
    monkeypatch.setattr(tuning, "ATTRACTION_DENOISE", "hqdn3d=3:3:9:9")
    assert AttractionVideoGenerator._tail_signature() != before


def test_a_clip_whose_sound_cannot_be_added_fails_the_export(tmp_path):
    import pytest

    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not a video")
    with pytest.raises(RuntimeError, match="could not add the sound"):
        VideoExporter._mux_track_for_concat(FFmpegManager.resolve_ffmpeg_bin(), broken, None, tmp_path, 0)
