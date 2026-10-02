from services import ollama_memory


class Reply:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def test_unloads_every_loaded_model(monkeypatch):
    posts = []
    monkeypatch.setattr(ollama_memory.httpx, "get", lambda url, timeout: Reply({"models": [{"model": "gemma4:26b"}, {"name": "llama3.2:latest"}]}))
    monkeypatch.setattr(ollama_memory.httpx, "post", lambda url, json, timeout: posts.append((url, json)))
    assert ollama_memory.unload_ollama_models() == ["gemma4:26b", "llama3.2:latest"]
    assert posts == [
        ("http://127.0.0.1:11434/api/generate", {"model": "gemma4:26b", "keep_alive": 0}),
        ("http://127.0.0.1:11434/api/generate", {"model": "llama3.2:latest", "keep_alive": 0}),
    ]


def test_nothing_loaded_sends_nothing(monkeypatch):
    monkeypatch.setattr(ollama_memory.httpx, "get", lambda url, timeout: Reply({"models": []}))
    monkeypatch.setattr(ollama_memory.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no unload expected")))
    assert ollama_memory.unload_ollama_models() == []


def test_ollama_not_running_is_quietly_fine(monkeypatch):
    def down(*a, **k):
        raise ConnectionError("refused")

    monkeypatch.setattr(ollama_memory.httpx, "get", down)
    assert ollama_memory.unload_ollama_models() == []


def test_one_model_failing_to_unload_does_not_stop_the_others(monkeypatch):
    monkeypatch.setattr(ollama_memory.httpx, "get", lambda url, timeout: Reply({"models": [{"model": "a"}, {"model": "b"}]}))

    def post(url, json, timeout):
        if json["model"] == "a":
            raise TimeoutError()

    monkeypatch.setattr(ollama_memory.httpx, "post", post)
    assert ollama_memory.unload_ollama_models() == ["b"]
