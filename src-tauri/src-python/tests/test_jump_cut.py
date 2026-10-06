import cv2
import numpy as np
from PIL import Image

from services import tuning
from services.vdoprocessing import jump_cut


def _photo(path, size=(2400, 1350)):
    """Black frame with a white centre square, so the punch-in shows more white."""
    w, h = size
    im = np.zeros((h, w, 3), np.uint8)
    im[h // 2 - 100:h // 2 + 100, w // 2 - 100:w // 2 + 100] = 255
    Image.fromarray(im).save(path)
    return str(path)


def _frames(path):
    cap = cv2.VideoCapture(str(path))
    out = []
    while True:
        ok, frame = cap.read()
        if not ok:
            return out
        out.append(frame)


def _white(frame):
    return float((frame > 128).mean())


def test_zoom_in_cuts_from_wide_to_tight_once(tmp_path):
    out = jump_cut.generate_jump_cut(_photo(tmp_path / "p.png"), str(tmp_path / "z.mp4"), 2.0, "zoomin")
    frames = _frames(out)
    assert abs(len(frames) - 2 * tuning.COMFYUI_FPS) <= 1
    assert frames[0].shape[:2] == (tuning.COMFYUI_HEIGHT, tuning.COMFYUI_WIDTH)
    first, last = _white(frames[0]), _white(frames[-1])
    assert last > first * 1.8
    jumps = sum(abs(_white(a) - _white(b)) > first * 0.5 for a, b in zip(frames, frames[1:]))
    assert jumps == 1


def test_zoom_out_is_the_reverse(tmp_path):
    out = jump_cut.generate_jump_cut(_photo(tmp_path / "p.png"), str(tmp_path / "z.mp4"), 2.0, "zoomout")
    frames = _frames(out)
    assert _white(frames[0]) > _white(frames[-1]) * 1.8


class _FakePipe:
    def __init__(self):
        self.calls = []

    def __call__(self, **kw):
        self.calls.append(kw)
        return type("R", (), {"images": [Image.new("RGB", (kw["width"], kw["height"]), (255, 0, 0))]})()


def _fake_sdxl(monkeypatch):
    from services.vdoprocessing import local_pan_generator as lpg

    pipe = _FakePipe()
    monkeypatch.setattr(tuning, "ATTRACTION_JUMP_CUT_AI", True)
    monkeypatch.setattr(lpg, "_cuda_available", lambda: True)
    monkeypatch.setattr(lpg, "_describe_scene", lambda img: "a station")
    monkeypatch.setattr(lpg, "_get_pipe", lambda: pipe)
    return pipe


def test_ai_wide_keeps_the_real_photo_in_the_middle(tmp_path, monkeypatch):
    pipe = _fake_sdxl(monkeypatch)
    photo = Image.new("RGB", (1600, 900), (0, 0, 255))
    wide = np.array(jump_cut.outpaint_wide(photo, 1280, 704))
    assert tuple(wide[352, 640]) == (0, 0, 255)  # real photo
    assert tuple(wide[5, 5]) == (255, 0, 0)  # AI ring
    kw = pipe.calls[0]
    assert (kw["width"], kw["height"]) == tuning.ATTRACTION_JUMP_CUT_AI_SIZE
    assert kw["prompt"].startswith("a station")
    mask = np.array(kw["mask_image"])
    assert mask[0, 0] == 255 and mask[kw["height"] // 2, kw["width"] // 2] == 0


def test_ai_zoom_in_cuts_from_the_outpainted_wide_to_the_photo(tmp_path, monkeypatch):
    _fake_sdxl(monkeypatch)
    out = jump_cut.generate_jump_cut(_photo(tmp_path / "p.png"), str(tmp_path / "z.mp4"), 2.0, "zoomin")
    frames = _frames(out)
    red = lambda f: float(((f[..., 2] > 200) & (f[..., 1] < 60)).mean())
    assert red(frames[0]) > 0.3 and red(frames[-1]) < 0.01
    assert (tmp_path / "z.wide.png").exists()


def test_failed_outpaint_falls_back_to_the_crop(tmp_path, monkeypatch):
    from services.vdoprocessing import local_pan_generator as lpg

    _fake_sdxl(monkeypatch)
    monkeypatch.setattr(lpg, "_get_pipe", lambda: (_ for _ in ()).throw(RuntimeError("oom")))
    out = jump_cut.generate_jump_cut(_photo(tmp_path / "p.png"), str(tmp_path / "z.mp4"), 2.0, "zoomin")
    frames = _frames(out)
    assert _white(frames[-1]) > _white(frames[0]) * 1.8


def test_a_big_photo_is_used_as_is(tmp_path):
    big = _photo(tmp_path / "p.png")
    assert jump_cut.upscaled_photo(big, tmp_path / "job_config.json") == big


def test_a_small_photo_uses_its_upscaled_copy(tmp_path, monkeypatch):
    from services.vdoprocessing.videopipeline import upscale_step

    small = _photo(tmp_path / "s.png", (400, 225))
    copy = upscale_step.cached_path(tmp_path, small)
    calls = []

    def fake_upscale(config_path, force=False):
        calls.append(config_path)
        copy.parent.mkdir(parents=True, exist_ok=True)
        _photo(copy)

    monkeypatch.setattr(upscale_step, "upscale_waypoint_images", fake_upscale)
    assert jump_cut.upscaled_photo(small, tmp_path / "job_config.json") == str(copy)
    assert len(calls) == 1
    assert jump_cut.upscaled_photo(small, tmp_path / "job_config.json") == str(copy)
    assert len(calls) == 1
