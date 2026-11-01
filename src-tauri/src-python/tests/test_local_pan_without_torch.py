"""The installed app's Python has no PyTorch, diffusers or transformers: the shared model helpers must not need them."""

import sys

from services.vdoprocessing import local_pan_generator


def test_cuda_is_reported_absent_when_torch_is_missing(monkeypatch):
    for name in ("torch", "diffusers", "transformers"):
        monkeypatch.setitem(sys.modules, name, None)  # None makes `import name` raise ImportError
    assert local_pan_generator._cuda_available() is False
    local_pan_generator._free_gpu_memory()  # must not raise
