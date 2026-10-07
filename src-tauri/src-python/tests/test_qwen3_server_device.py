"""Where qwen3_server puts its model, with fake torch / qwen_tts modules (no GPU is touched)."""

import sys
import types

import pytest

from services.tts import qwen3_server


@pytest.fixture
def fake(monkeypatch):
    state = types.SimpleNamespace(cuda=True, fail_on_cuda=False, loads=[], caps=[])

    class Model:
        @staticmethod
        def from_pretrained(model_id, device_map, dtype):
            if device_map.startswith("cuda") and state.fail_on_cuda:
                raise RuntimeError("CUDA error: no kernel image")
            state.loads.append((device_map, dtype))
            return object()

    torch = types.SimpleNamespace(
        float32="float32", bfloat16="bfloat16", set_num_threads=lambda n: None,
        cuda=types.SimpleNamespace(
            is_available=lambda: state.cuda,
            set_per_process_memory_fraction=lambda f: state.caps.append(f),
            empty_cache=lambda: None,
        ),
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "qwen_tts", types.SimpleNamespace(Qwen3TTSModel=Model))
    monkeypatch.setattr(qwen3_server, "_ready", qwen3_server.threading.Event())
    return state


def test_cuda_loads_in_bfloat16_under_the_vram_cap(fake, monkeypatch):
    monkeypatch.setenv("QWEN3_DEVICE", "cuda")
    monkeypatch.setenv("QWEN3_VRAM_FRACTION", "0.4")
    qwen3_server.load_model()
    assert fake.loads == [("cuda:0", "bfloat16")] and fake.caps == [0.4]
    assert qwen3_server._device == "cuda" and qwen3_server._ready.is_set()


def test_a_cpu_only_torch_falls_back_to_the_cpu(fake, monkeypatch):
    monkeypatch.setenv("QWEN3_DEVICE", "cuda")
    fake.cuda = False
    qwen3_server.load_model()
    assert fake.loads == [("cpu", "float32")] and qwen3_server._device == "cpu"


def test_a_gpu_that_fails_to_load_falls_back_to_the_cpu(fake, monkeypatch):
    monkeypatch.setenv("QWEN3_DEVICE", "cuda")
    fake.fail_on_cuda = True
    qwen3_server.load_model()
    assert fake.loads == [("cpu", "float32")] and qwen3_server._device == "cpu"


def test_cpu_is_the_default(fake, monkeypatch):
    monkeypatch.delenv("QWEN3_DEVICE", raising=False)
    qwen3_server.load_model()
    assert fake.loads == [("cpu", "float32")] and fake.caps == []
