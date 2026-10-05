"""Which model drafts the overview narration: the project's online provider when it picked one
(settings.ai_provider, see online_llm), else the local Ollama model (settings.overview_script_model)."""

from typing import Callable, Optional, Tuple

from services.localization.online_llm import online_generate, target_from_settings

DEFAULT_SCRIPT_MODEL = "schroneko/gemma-2-2b-jpn-it"

Generate = Callable[[str, int], Optional[str]]


def script_generator(settings: Optional[dict]) -> Tuple[Generate, str]:
    """(generate, a label for logs and the result: the model's name, with its provider when online)."""
    target = target_from_settings(settings)
    if target:
        provider, model, base = target
        return online_generate(provider, model, base), f"{provider}:{model}"

    from services.localization.overview_script import ollama_generate

    model = (settings or {}).get("overview_script_model", DEFAULT_SCRIPT_MODEL)
    return ollama_generate(model), model
