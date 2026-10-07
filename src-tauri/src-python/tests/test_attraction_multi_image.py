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

    def fake(self, image, prompt, duration_sec=6.0, save_path=None, place=None):
        if str(prompt).lower() == "none":
            return real(self, image, prompt, duration_sec, save_path, place)
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
        prompt_text=["pan-down", "none", "pan-right"],
        target_audio_duration=12.0,
        output_filename="04_attraction_05_test.mp4",
        force=True,
    )
    assert out and FFmpegManager.get_media_duration(out) == pytest.approx(12.0, abs=0.3)
    # Nothing left parked for an approval step, and no temp pieces left over;
    # each photo's raw clip is kept for reuse.
    leftovers = {p.name for p in generator.output_dir.iterdir() if p.is_file() and p.suffix != ".signlock"}
    assert "04_attraction_05_test.mp4" in leftovers
    others = leftovers - {"04_attraction_05_test.mp4"}
    assert len(others) == 3 and all(n.startswith("raw_04_attraction_05_test_") for n in others)


def test_single_moving_photo_keeps_moving_to_the_narration_end(generator, tmp_path):
    out = generator.process_attraction_video(
        popup_image_entry=_photos(tmp_path, 1),
        prompt_text=["pan-down"],
        target_audio_duration=15.0,
        output_filename="04_attraction_06_single.mp4",
        force=True,
    )
    # Not cut back to the raw-clip cap: the slow move carries it to 15 s.
    assert out and FFmpegManager.get_media_duration(out) == pytest.approx(15.0, abs=0.3)


def test_changed_camera_preset_regenerates_the_clip(generator, tmp_path, monkeypatch):
    photos = _photos(tmp_path, 1)
    kwargs = dict(popup_image_entry=photos, target_audio_duration=4.0,
                  output_filename="04_attraction_08_pan.mp4")
    generator.process_attraction_video(prompt_text=["pan-down"], **kwargs)

    calls = []
    real = AttractionVideoGenerator._generate_single_clip
    monkeypatch.setattr(
        AttractionVideoGenerator, "_generate_single_clip",
        lambda self, *a, **k: calls.append(a[1]) or real(self, *a, **k),
    )
    generator.process_attraction_video(prompt_text=["Pan Down"], **kwargs)
    assert calls == []  # same preset, other spelling: reused
    generator.process_attraction_video(prompt_text=["pan-left"], **kwargs)
    assert calls == ["pan-left"]


@pytest.fixture
def calls(monkeypatch):
    seen = []
    real = AttractionVideoGenerator._generate_single_clip
    monkeypatch.setattr(
        AttractionVideoGenerator, "_generate_single_clip",
        lambda self, *a, **k: seen.append((a[0], a[1], a[2])) or real(self, *a, **k),
    )
    return seen


def _raws(generator, stem):
    return sorted(p.name for p in generator.output_dir.glob(f"raw_{stem}_*.mp4"))


def test_added_photo_only_generates_the_new_one(generator, tmp_path, calls):
    photos = _photos(tmp_path, 2)
    kwargs = dict(target_audio_duration=10.0, output_filename="04_attraction_09_add.mp4")
    generator.process_attraction_video(popup_image_entry=photos[:1], prompt_text=["pan-down"], **kwargs)
    calls.clear()

    out = generator.process_attraction_video(
        popup_image_entry=photos, prompt_text=["pan-down", "pan-left"], **kwargs
    )
    assert [(img, pan) for img, pan, _ in calls] == [(photos[1], "pan-left")]
    assert calls[0][2] == pytest.approx(5.0)
    assert out and FFmpegManager.get_media_duration(out) == pytest.approx(10.0, abs=0.3)
    assert len(_raws(generator, "04_attraction_09_add")) == 2


def test_changed_preset_regenerates_only_that_photo(generator, tmp_path, calls):
    photos = _photos(tmp_path, 2)
    kwargs = dict(popup_image_entry=photos, target_audio_duration=8.0,
                  output_filename="04_attraction_10_change.mp4")
    generator.process_attraction_video(prompt_text=["pan-down", "pan-left"], **kwargs)
    before = _raws(generator, "04_attraction_10_change")
    calls.clear()

    generator.process_attraction_video(prompt_text=["pan-up", "pan-left"], **kwargs)
    assert [(img, pan) for img, pan, _ in calls] == [(photos[0], "pan-up")]
    after = _raws(generator, "04_attraction_10_change")
    assert len(after) == 2 and len(set(before) & set(after)) == 1  # old photo-1 clip removed


def test_removed_photo_regenerates_a_clip_made_for_a_shorter_share(generator, tmp_path, calls):
    photos = _photos(tmp_path, 2)
    kwargs = dict(target_audio_duration=8.0, output_filename="04_attraction_11_remove.mp4")
    generator.process_attraction_video(
        popup_image_entry=photos, prompt_text=["pan-down", "pan-left"], **kwargs
    )
    calls.clear()

    generator.process_attraction_video(popup_image_entry=photos[:1], prompt_text=["pan-down"], **kwargs)
    assert [(img, pan, d) for img, pan, d in calls] == [(photos[0], "pan-down", pytest.approx(8.0))]
    assert len(_raws(generator, "04_attraction_11_remove")) == 1


def test_index_named_clip_from_an_older_run_is_reused(generator, tmp_path, calls):
    photos = _photos(tmp_path, 1)
    stem = "04_attraction_12_legacy"
    _fake_clip(generator.output_dir / f"raw_{stem}_00.mp4", 4.0)
    inputs = generator._inputs_path(f"{stem}.mp4")
    inputs.parent.mkdir(parents=True, exist_ok=True)
    inputs.write_text(json.dumps({"pans": ["panright"]}), encoding="utf-8")

    out = generator.process_attraction_video(
        popup_image_entry=photos, prompt_text=["pan-right"], target_audio_duration=4.0,
        output_filename=f"{stem}.mp4",
    )
    assert out and calls == []
    assert len(_raws(generator, stem)) == 1 and not (generator.output_dir / f"raw_{stem}_00.mp4").exists()


@pytest.fixture
def slow_moves(monkeypatch):
    from services.vdoprocessing import slow_move

    seen = []
    real = slow_move.extend_with_slow_move
    monkeypatch.setattr(
        slow_move, "extend_with_slow_move",
        lambda path, target, *a, **k: seen.append(target) or real(path, target, *a, **k),
    )
    return seen


def test_capped_wan_clip_is_finished_with_the_slow_zoom_out(generator, tmp_path, slow_moves):
    out = generator.process_attraction_video(
        popup_image_entry=_photos(tmp_path, 1), prompt_text=["pan-down"],
        target_audio_duration=15.0, output_filename="04_attraction_13_cap.mp4",
    )
    assert slow_moves == [15.0]
    assert out and FFmpegManager.get_media_duration(out) == pytest.approx(15.0, abs=0.3)


def test_small_gap_is_held_not_zoomed(generator, tmp_path, slow_moves):
    out = generator.process_attraction_video(
        popup_image_entry=_photos(tmp_path, 1), prompt_text=["pan-down"],
        target_audio_duration=2.6, output_filename="04_attraction_14_gap.mp4",
    )
    assert slow_moves == []
    assert out and FFmpegManager.get_media_duration(out) == pytest.approx(2.6, abs=0.3)


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
    kwargs = dict(prompt_text=["pan-down"], target_audio_duration=0, output_filename="04_attraction_07_swap.mp4")
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
