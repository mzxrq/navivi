"""Overview narration written by an online model instead of the local Ollama one.

Mirrors the frontend's src/services/ai/providers.ts, but without streaming or photos: the pipeline only needs the
finished text of a short prompt. The key comes from the environment (NAVIVI_AI_KEY_<PROVIDER>, set by the Rust shell
from the OS credential store); it is never in job_config.json.
"""

import os
import time
from typing import Any, Callable, Dict, Optional, Tuple

import httpx

from services.logger.logger import setup_logger

logger = setup_logger("OnlineLLM")

# Mirrors PROVIDERS in src/services/ai/providers.ts (default model and address per provider).
PROVIDERS: Dict[str, Dict[str, str]] = {
    "anthropic": {"base": "https://api.anthropic.com/v1", "model": "claude-haiku-4-5-20251001"},
    "openai": {"base": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    "gemini": {"base": "https://generativelanguage.googleapis.com/v1beta", "model": "gemini-2.5-flash"},
    "openrouter": {"base": "https://openrouter.ai/api/v1", "model": "openai/gpt-4o-mini"},
    "custom": {"base": "", "model": ""},
}

MAX_TOKENS = 2000  # reasoning models spend part of it thinking, so it is far above a passage's real length
TIMEOUT_SECONDS = 90.0
RETRIES = 2  # after the first try, for a busy server or a dropped connection
RETRY_STATUSES = {408, 429, 500, 502, 503, 504, 529}
GIVE_UP_STATUSES = {400, 401, 403, 404}  # the same request will fail again, so the rest of the run skips the model


class OnlineLLMError(Exception):
    pass


def key_env_name(provider: str) -> str:
    return f"NAVIVI_AI_KEY_{provider.upper()}"


def target_from_settings(settings: Optional[dict]) -> Optional[Tuple[str, str, str]]:
    """(provider, model, base_url) when the project's settings pick an online provider, else None (local Ollama)."""
    settings = settings or {}
    provider = settings.get("ai_provider")
    if provider not in PROVIDERS:
        return None
    models = settings.get("ai_online_models") or {}
    model = (models.get(provider) or PROVIDERS[provider]["model"]).strip()
    base = (settings.get("ai_online_base_url") if provider == "custom" else "") or PROVIDERS[provider]["base"]
    return provider, model, base.rstrip("/")


def build_request(provider: str, model: str, base: str, api_key: str, prompt: str) -> Tuple[str, Dict[str, str], dict, Dict[str, str]]:
    """(url, headers, json body, query params) for one non-streaming request."""
    if provider == "anthropic":
        return (
            f"{base}/messages",
            {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            {"model": model, "max_tokens": MAX_TOKENS, "messages": [{"role": "user", "content": prompt}]},
            {},
        )
    if provider == "gemini":
        return (
            f"{base}/models/{model}:generateContent",
            {"x-goog-api-key": api_key},
            {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": MAX_TOKENS}},
            {},
        )
    # OpenAI and the servers that copy its API. OpenAI's newer models only accept max_completion_tokens.
    token_field = "max_completion_tokens" if provider == "openai" else "max_tokens"
    return (
        f"{base}/chat/completions",
        {"authorization": f"Bearer {api_key}"},
        {"model": model, token_field: MAX_TOKENS, "messages": [{"role": "user", "content": prompt}]},
        {},
    )


def parse_response(provider: str, data: Any) -> str:
    """The text of the answer, '' when there is none."""
    if provider == "anthropic":
        return "".join(b.get("text", "") for b in (data or {}).get("content", []) if b.get("type") == "text")
    if provider == "gemini":
        parts = (((data or {}).get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts if not p.get("thought"))
    return (((data or {}).get("choices") or [{}])[0].get("message") or {}).get("content") or ""


def error_text(response: httpx.Response) -> str:
    try:
        body = response.json()
        err = body.get("error")
        if isinstance(err, dict):
            return str(err.get("message", ""))
        if isinstance(err, str):
            return err
    except Exception:
        pass
    return response.text[:200]


def online_generate(
    provider: str,
    model: str,
    base_url: str,
    api_key: Optional[str] = None,
    client: Optional[httpx.Client] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Callable[[str, int], Optional[str]]:
    """A `generate(prompt, max_chars)` like overview_script.ollama_generate, backed by an online model.

    A request that is bound to fail again (bad key, unknown model) is reported once and every later call returns None,
    so the script falls back to its templates at once instead of waiting for each passage to fail."""
    key = api_key if api_key is not None else os.environ.get(key_env_name(provider), "")
    state = {"dead": ""}

    def _generate(prompt: str, max_chars: int) -> Optional[str]:
        if state["dead"]:
            return None
        if not key:
            state["dead"] = f"no API key for {provider} (add it in Settings > AI models)"
            logger.warning("Online model skipped: %s.", state["dead"])
            return None
        if not model or not base_url:
            state["dead"] = "no model or address is set"
            logger.warning("Online model skipped: %s.", state["dead"])
            return None

        url, headers, body, params = build_request(provider, model, base_url, key, prompt)
        http = client or httpx.Client(timeout=TIMEOUT_SECONDS)
        try:
            for attempt in range(RETRIES + 1):
                try:
                    response = http.post(url, headers={**headers, "content-type": "application/json"}, json=body, params=params)
                except httpx.HTTPError as exc:
                    if attempt == RETRIES:
                        raise OnlineLLMError(f"{provider} could not be reached: {exc}") from exc
                    sleep(2.0 * (attempt + 1))
                    continue
                if response.status_code == 200:
                    return parse_response(provider, response.json()) or None
                if response.status_code in GIVE_UP_STATUSES:
                    state["dead"] = f"{provider} answered {response.status_code}: {error_text(response)}"
                    logger.warning("Online model stopped for this run: %s", state["dead"])
                    return None
                if response.status_code in RETRY_STATUSES and attempt < RETRIES:
                    sleep(2.0 * (attempt + 1))
                    continue
                raise OnlineLLMError(f"{provider} answered {response.status_code}: {error_text(response)}")
        finally:
            if client is None:
                http.close()
        return None

    return _generate
