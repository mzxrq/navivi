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


def test_a_clip_open_in_a_preview_is_swapped_in_on_retry_not_re_encoded(tmp_path, monkeypatch):
    """Windows refuses to replace a clip the editor is previewing ("Make again"): the finished file is swapped in
    on a retry; the slow per-stage encode must not run again just because the swap was refused once."""
    import os

    from services import projectfiles
    from services.vdoprocessing import img2vdo
    from services.vdoprocessing.img2vdo import AttractionVideoGenerator

    gen = AttractionVideoGenerator.__new__(AttractionVideoGenerator)
    gen.output_dir = tmp_path
    monkeypatch.setattr(gen, "_resolve_duration_fit", lambda *a: (None, None), raising=False)
    monkeypatch.setattr(gen, "_extend_short_clip", lambda video, trim, hold, *a: (video, trim, hold), raising=False)
    stagewise = []
    monkeypatch.setattr(gen, "_fit_and_finalize_stagewise", lambda *a: stagewise.append(a), raising=False)
    monkeypatch.setattr(img2vdo.VideoExporter, "finalize_clip",
                        staticmethod(lambda **kw: open(kw["output_video_path"], "wb").write(b"new clip")))
    monkeypatch.setattr(img2vdo, "record_place_label", lambda *a, **k: None, raising=False)
    real_replace, refused = os.replace, []

    def replace_once_refused(src, dst):
        if not refused:
            refused.append(dst)
            raise PermissionError("in use by the preview")
        real_replace(src, dst)

    monkeypatch.setattr(projectfiles.os, "replace", replace_once_refused)
    (tmp_path / "04_attraction_01_x.mp4").write_bytes(b"old clip")

    out = gen._fit_and_finalize(str(tmp_path / "raw.mp4"), 5.0, "04_attraction_01_x.mp4", 0.5)
    assert refused and not stagewise
    assert (tmp_path / "04_attraction_01_x.mp4").read_bytes() == b"new clip" and out.endswith("04_attraction_01_x.mp4")
