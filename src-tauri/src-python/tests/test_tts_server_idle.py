"""The Kokoro/Qwen3 servers stop themselves after --idle-seconds: idle time counts from when the model is loaded,
so a slow first load (a download, a cold disk) is not taken as the server sitting unused."""

import sys
import types

from services.tts import kokoro_server


def test_kokoro_idle_clock_starts_when_the_model_is_ready(monkeypatch):
    fake = types.ModuleType("kokoro")
    fake.KPipeline = lambda **kw: object()
    monkeypatch.setitem(sys.modules, "kokoro", fake)
    monkeypatch.setattr(kokoro_server, "_last_request", 0.0)
    monkeypatch.setattr(kokoro_server, "_pipelines", {})
    monkeypatch.setattr(kokoro_server, "_ready", kokoro_server.threading.Event())

    kokoro_server.load_pipeline()
    assert kokoro_server._ready.is_set() and kokoro_server._last_request > 0.0
