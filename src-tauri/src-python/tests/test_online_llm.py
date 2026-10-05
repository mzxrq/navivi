"""The online model behind the overview narration (localization/online_llm.py, script_engine.py)."""

import json

import httpx
import pytest

from services.localization import online_llm, script_engine
from services.localization.online_llm import (
    build_request, key_env_name, online_generate, parse_response, target_from_settings,
)


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _openai_ok(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


class TestTargetFromSettings:
    def test_no_provider_or_ollama_means_local(self):
        assert target_from_settings(None) is None
        assert target_from_settings({}) is None
        assert target_from_settings({"ai_provider": "ollama"}) is None
        assert target_from_settings({"ai_provider": "nonsense"}) is None

    def test_a_provider_gets_its_default_model_and_address(self):
        assert target_from_settings({"ai_provider": "anthropic"}) == (
            "anthropic", "claude-haiku-4-5-20251001", "https://api.anthropic.com/v1",
        )

    def test_the_chosen_model_wins(self):
        settings = {"ai_provider": "openai", "ai_online_models": {"openai": " gpt-4o ", "anthropic": "x"}}
        assert target_from_settings(settings) == ("openai", "gpt-4o", "https://api.openai.com/v1")

    def test_only_the_custom_provider_uses_the_typed_address(self):
        custom = {"ai_provider": "custom", "ai_online_models": {"custom": "m"}, "ai_online_base_url": "http://h:1234/v1/"}
        assert target_from_settings(custom) == ("custom", "m", "http://h:1234/v1")
        other = {"ai_provider": "openai", "ai_online_base_url": "http://ignored"}
        assert target_from_settings(other)[2] == "https://api.openai.com/v1"


class TestBuildRequest:
    def test_openai_uses_a_bearer_key_and_max_completion_tokens(self):
        url, headers, body, _ = build_request("openai", "m", "https://api.openai.com/v1", "sk", "hi")
        assert url == "https://api.openai.com/v1/chat/completions"
        assert headers["authorization"] == "Bearer sk"
        assert body["max_completion_tokens"] == online_llm.MAX_TOKENS
        assert "max_tokens" not in body

    def test_other_openai_compatible_servers_use_max_tokens(self):
        _, _, body, _ = build_request("openrouter", "m", "https://openrouter.ai/api/v1", "k", "hi")
        assert body["max_tokens"] == online_llm.MAX_TOKENS

    def test_anthropic(self):
        url, headers, body, _ = build_request("anthropic", "claude-x", "https://api.anthropic.com/v1", "ak", "hi")
        assert url.endswith("/messages")
        assert headers["x-api-key"] == "ak" and headers["anthropic-version"] == "2023-06-01"
        assert body["messages"] == [{"role": "user", "content": "hi"}]

    def test_gemini_puts_the_model_in_the_url_and_the_key_in_a_header(self):
        url, headers, body, _ = build_request("gemini", "gemini-2.5-flash", "https://g/v1beta", "gk", "hi")
        assert url == "https://g/v1beta/models/gemini-2.5-flash:generateContent"
        assert headers["x-goog-api-key"] == "gk"
        assert body["contents"][0]["parts"] == [{"text": "hi"}]


class TestParseResponse:
    def test_each_shape(self):
        assert parse_response("openai", {"choices": [{"message": {"content": "こんにちは"}}]}) == "こんにちは"
        assert parse_response("anthropic", {"content": [{"type": "thinking", "text": "x"}, {"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}) == "ab"
        assert parse_response("gemini", {"candidates": [{"content": {"parts": [{"text": "hm", "thought": True}, {"text": "ok"}]}}]}) == "ok"

    def test_an_empty_or_odd_answer_is_empty_text(self):
        assert parse_response("openai", {}) == ""
        assert parse_response("anthropic", None) == ""
        assert parse_response("gemini", {"candidates": []}) == ""


class TestOnlineGenerate:
    def test_returns_the_answer_and_sends_the_key(self):
        seen = {}

        def handler(request):
            seen["auth"] = request.headers["authorization"]
            seen["body"] = json.loads(request.content)
            return _openai_ok("本文です。")

        gen = online_generate("openai", "m", "https://api.openai.com/v1", "sk-1", client=_client(handler))
        assert gen("プロンプト", 50) == "本文です。"
        assert seen["auth"] == "Bearer sk-1"
        assert seen["body"]["messages"][0]["content"] == "プロンプト"

    def test_the_key_comes_from_the_environment_when_not_given(self, monkeypatch):
        monkeypatch.setenv(key_env_name("openai"), "from-env")
        seen = {}

        def handler(request):
            seen["auth"] = request.headers["authorization"]
            return _openai_ok("x")

        online_generate("openai", "m", "https://api.openai.com/v1", client=_client(handler))("p", 10)
        assert seen["auth"] == "Bearer from-env"

    def test_no_key_returns_none_without_calling_out(self, monkeypatch):
        monkeypatch.delenv(key_env_name("openai"), raising=False)
        calls = []
        gen = online_generate("openai", "m", "https://api.openai.com/v1", client=_client(lambda r: calls.append(r) or _openai_ok("x")))
        assert gen("p", 10) is None
        assert calls == []

    def test_a_rejected_key_is_reported_once_and_later_calls_skip_the_request(self):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(401, json={"error": {"message": "Incorrect API key"}})

        gen = online_generate("openai", "m", "https://api.openai.com/v1", "bad", client=_client(handler))
        assert gen("a", 10) is None
        assert gen("b", 10) is None
        assert len(calls) == 1

    def test_a_busy_server_is_retried_then_succeeds(self):
        answers = iter([httpx.Response(429, json={"error": {"message": "slow down"}}), httpx.Response(503), _openai_ok("やっと")])
        waits = []
        gen = online_generate(
            "openai", "m", "https://api.openai.com/v1", "k", client=_client(lambda r: next(answers)), sleep=waits.append,
        )
        assert gen("p", 10) == "やっと"
        assert waits == [2.0, 4.0]

    def test_a_server_that_keeps_failing_raises_so_the_passage_uses_its_template(self):
        gen = online_generate(
            "openai", "m", "https://api.openai.com/v1", "k",
            client=_client(lambda r: httpx.Response(500, text="boom")), sleep=lambda s: None,
        )
        with pytest.raises(online_llm.OnlineLLMError, match="500"):
            gen("p", 10)

    def test_a_dropped_connection_is_retried_then_raises(self):
        def handler(request):
            raise httpx.ConnectError("down")

        gen = online_generate("openai", "m", "https://api.openai.com/v1", "k", client=_client(handler), sleep=lambda s: None)
        with pytest.raises(online_llm.OnlineLLMError, match="could not be reached"):
            gen("p", 10)

    def test_a_missing_model_or_address_is_skipped(self):
        gen = online_generate("custom", "", "", "k", client=_client(lambda r: _openai_ok("x")))
        assert gen("p", 10) is None


class TestScriptGenerator:
    def test_an_online_provider_is_used_when_the_project_picks_one(self, monkeypatch):
        monkeypatch.setenv(key_env_name("anthropic"), "k")
        generate, label = script_engine.script_generator({"ai_provider": "anthropic"})
        assert label == "anthropic:claude-haiku-4-5-20251001"
        assert callable(generate)

    def test_otherwise_the_local_model_named_in_the_settings(self, monkeypatch):
        import services.localization.overview_script as overview_script

        monkeypatch.setattr(overview_script, "ollama_generate", lambda model: f"local<{model}>")
        assert script_engine.script_generator({"overview_script_model": "gemma3"}) == ("local<gemma3>", "gemma3")
        assert script_engine.script_generator(None) == (f"local<{script_engine.DEFAULT_SCRIPT_MODEL}>", script_engine.DEFAULT_SCRIPT_MODEL)


class TestPipelineWiring:
    def _config(self, tmp_path, settings):
        cfg = tmp_path / "job_config.json"
        cfg.write_text(json.dumps({"overview_narration": "", "waypoints": [{"id": "a"}, {"id": "b"}], "settings": settings}), encoding="utf-8")
        return cfg

    def test_the_overview_is_drafted_by_the_online_model_when_one_is_chosen(self, tmp_path, monkeypatch):
        import services.localization.overview_script as overview_script
        from services.vdoprocessing.videopipeline.narration_step import ensure_overview_narration

        monkeypatch.setenv(key_env_name("openai"), "sk")
        seen = {}

        def fake_build(project, cache, generate):
            seen["text"] = generate("プロンプト", 40)
            return "{start}drafted", []

        monkeypatch.setattr(overview_script, "build_tour_script", fake_build)
        monkeypatch.setattr(overview_script, "ollama_generate", lambda model: pytest.fail("the local model must not be used"))
        real_client = httpx.Client
        monkeypatch.setattr(
            online_llm.httpx, "Client",
            lambda **kw: real_client(transport=httpx.MockTransport(lambda request: _openai_ok("オンラインの本文"))),
        )
        cfg = self._config(tmp_path, {"ai_provider": "openai"})
        assert ensure_overview_narration(str(cfg)) is True
        assert seen["text"] == "オンラインの本文"
        assert json.loads(cfg.read_text(encoding="utf-8"))["overview_narration"] == "{start}drafted"
