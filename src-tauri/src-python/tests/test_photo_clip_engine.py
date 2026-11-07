from services.vdoprocessing.img2vdo import AttractionVideoGenerator


class _Config:
    def __init__(self, engine=None):
        self.settings = {"photo_clip_engine": engine} if engine else {}

    def get_settings(self):
        return self.settings


def _generator(engine, tmp_path):
    gen = AttractionVideoGenerator.__new__(AttractionVideoGenerator)
    gen.config = _Config(engine)
    gen.output_dir = tmp_path
    return gen


def test_ai_photo_clips_off_makes_every_move_a_3d_photo_without_comfyui(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(AttractionVideoGenerator, "_parallax_clip", staticmethod(lambda *a: calls.append(a[3]) or "clip.mp4"))
    gen = _generator("cpu", tmp_path)
    assert gen._cpu_only()
    for preset in ("panright", "walkin", "zoomin"):
        assert gen._generate_single_clip_here("photo.jpg", preset, 4.0, str(tmp_path / f"{preset}.mp4")) == "clip.mp4"
    assert calls == ["panright", "walkin", "zoomin"]  # never reached LTXV / Wan (ComfyUI)


def test_ai_photo_clips_stay_on_by_default(tmp_path):
    assert not _generator(None, tmp_path)._cpu_only()
    assert not _generator("ai", tmp_path)._cpu_only()
