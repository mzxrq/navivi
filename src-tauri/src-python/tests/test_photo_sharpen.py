from PIL import Image

from services.vdoprocessing.photo_sharpen import sharpened_dir, sharpened_photo


def _photo(folder, name="日本語の写真.jpg", size=(3000, 2000)):
    path = folder / name
    Image.effect_noise(size, 30).convert("RGB").save(path)
    return str(path)


def test_a_big_photo_gets_a_cached_sharpened_copy_within_the_size_limit(tmp_path):
    photo = _photo(tmp_path)
    out = sharpened_photo(photo, tmp_path)
    assert out != photo and out.startswith(str(sharpened_dir(tmp_path)))
    assert max(Image.open(out).size) == 1920
    assert sharpened_photo(photo, tmp_path) == out  # the same file the second time


def test_an_upscaled_copy_is_left_alone(tmp_path):
    folder = tmp_path / "assets" / "image" / "upscaled"
    folder.mkdir(parents=True)
    photo = _photo(folder, "a.png", (800, 600))
    assert sharpened_photo(photo, tmp_path) == photo


def test_an_unreadable_photo_is_used_as_it_is(tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    assert sharpened_photo(str(bad), tmp_path) == str(bad)


def test_sharpen_photos_on_swaps_the_photo_ComfyUI_gets_and_off_keeps_it(tmp_path, monkeypatch):
    import json

    from services.config.job_config import JobConfigManager
    from services.vdoprocessing.img2vdo import AttractionVideoGenerator

    seen = []

    def fake(self, image, prompt, duration_sec=6.0, save_path=None, place=None):
        seen.append(image)
        return None

    monkeypatch.setattr(AttractionVideoGenerator, "_generate_single_clip", fake)
    photo = _photo(tmp_path, "p.jpg")
    for on in (True, False):
        cfg = tmp_path / "job_config.json"
        cfg.write_text(json.dumps({"directory_path": str(tmp_path), "waypoints": [],
                                   "settings": {"upscale_popup_images": on}}), encoding="utf-8")
        JobConfigManager._instance = None
        gen = AttractionVideoGenerator(JobConfigManager(str(cfg)))
        seen.clear()
        gen.process_attraction_video(photo, "pan-left", 2.0, output_filename="out.mp4")
        assert bool(seen) and (seen[0] != photo) == on
