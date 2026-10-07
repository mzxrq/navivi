"""The installed app's Python has no PyTorch, diffusers or transformers: the attraction clip fallback must still pan over the photo."""

import sys

import cv2
import numpy as np

from services.vdoprocessing import local_pan_generator


def _no_ml(monkeypatch):
    for name in ("torch", "diffusers", "transformers"):
        monkeypatch.setitem(sys.modules, name, None)  # None makes `import name` raise ImportError


def test_cuda_is_reported_absent_when_torch_is_missing(monkeypatch):
    _no_ml(monkeypatch)
    assert local_pan_generator._cuda_available() is False
    local_pan_generator._free_gpu_memory()  # must not raise


def test_a_plain_pan_is_made_without_torch(tmp_path, monkeypatch):
    _no_ml(monkeypatch)
    image = tmp_path / "photo.jpg"
    cv2.imwrite(str(image), (np.random.default_rng(1).random((240, 320, 3)) * 255).astype("uint8"))
    out = tmp_path / "clip.mp4"
    assert local_pan_generator.generate_local_clip(str(image), str(out), 1.0, "panright") == str(out)
    assert out.stat().st_size > 0
