"""A waypoint with several photos: the clips are combined automatically
(no approval step) and the result lasts as long as the narration."""

import json
import subprocess

import pytest
from PIL import Image

from services.config.job_config import JobConfigManager
from services.tts.ttsengine import FFmpegManager
from services.vdoprocessing.img2vdo import AttractionVideoGenerator


def _fake_clip(path, seconds):
    subprocess.run(
        [FFmpegManager.resolve_ffmpeg_bin(), "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"testsrc2=size=1280x704:rate=24:duration={seconds}", "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )
    return str(path)


@pytest.fixture
def generator(tmp_path, monkeypatch):
    cfg = tmp_path / "job_config.json"
    cfg.write_text(json.dumps({"directory_path": str(tmp_path), "waypoints": []}), encoding="utf-8")
    gen = AttractionVideoGenerator(JobConfigManager(str(cfg)))

    # Wan stand-in: every moving photo gives a 2 s clip; "none" stays the real still clip.
    real = AttractionVideoGenerator._generate_single_clip

    def fake(self, image, prompt, duration_sec=6.0, save_path=None):
        if str(prompt).lower() == "none":
            return real(self, image, prompt, duration_sec, save_path)
        return _fake_clip(save_path, 2.0)

    monkeypatch.setattr(AttractionVideoGenerator, "_generate_single_clip", fake)
    return gen


def _photos(tmp_path, n):
    paths = []
    for i in range(n):
        p = tmp_path / f"p{i}.jpg"
        Image.new("RGB", (900, 600), (40 * i, 90, 120)).save(p)
        paths.append(str(p))
    return paths


def test_three_photos_are_combined_to_the_narration_length(generator, tmp_path):
    out = generator.process_attraction_video(
        popup_image_entry=_photos(tmp_path, 3),
        prompt_text=["zoom-in", "none", "pan-right"],
        target_audio_duration=12.0,
        output_filename="04_attraction_05_test.mp4",
        force=True,
    )
    assert out and FFmpegManager.get_media_duration(out) == pytest.approx(12.0, abs=0.3)
    # Nothing left parked for an approval step, and no temp pieces left over.
    leftovers = {p.name for p in generator.output_dir.iterdir() if p.is_file()}
    assert leftovers == {"04_attraction_05_test.mp4", "04_attraction_05_test.inputs.json"}


def test_single_moving_photo_keeps_moving_to_the_narration_end(generator, tmp_path):
    out = generator.process_attraction_video(
        popup_image_entry=_photos(tmp_path, 1),
        prompt_text=["zoom-in"],
        target_audio_duration=15.0,
        output_filename="04_attraction_06_single.mp4",
        force=True,
    )
    # Not cut back to the raw-clip cap: the slow move carries it to 15 s.
    assert out and FFmpegManager.get_media_duration(out) == pytest.approx(15.0, abs=0.3)


def test_still_photo_is_held_for_the_whole_narration(generator, tmp_path):
    out = generator.process_attraction_video(
        popup_image_entry=_photos(tmp_path, 1),
        prompt_text=["none"],
        target_audio_duration=14.0,
        output_filename="04_attraction_07_still.mp4",
        force=True,
    )
    assert out and FFmpegManager.get_media_duration(out) == pytest.approx(14.0, abs=0.3)


def test_clip_is_remade_when_its_photos_change(generator, tmp_path, monkeypatch):
    first, second = _photos(tmp_path, 2)
    kwargs = dict(prompt_text=["zoom-in"], target_audio_duration=0, output_filename="04_attraction_07_swap.mp4")
    out = generator.process_attraction_video(popup_image_entry=[first], **kwargs)

    calls = []
    real = AttractionVideoGenerator._generate_single_clip
    monkeypatch.setattr(
        AttractionVideoGenerator, "_generate_single_clip",
        lambda self, *a, **k: calls.append(a[0]) or real(self, *a, **k),
    )
    assert generator.process_attraction_video(popup_image_entry=[first], **kwargs) == out
    assert calls == []
    generator.process_attraction_video(popup_image_entry=[second], **kwargs)
    assert calls == [second]
