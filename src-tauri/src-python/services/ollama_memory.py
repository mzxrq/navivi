"""Hands Ollama's memory back before the heavy pipeline stages.

The app keeps the script model loaded for 30 minutes so the next script starts fast (ollamaApi.ts KEEP_ALIVE). On a PC where that model
is most of the RAM, the narration and rendering stages would then fight it for memory, so the pipeline unloads whatever Ollama holds
before them. Every failure is silent: Ollama not running is the normal case."""

import httpx

from services.logger.logger import setup_logger

logger = setup_logger("OllamaMemory")

OLLAMA_URL = "http://127.0.0.1:11434"


def unload_ollama_models(base_url: str = OLLAMA_URL, timeout: float = 3.0) -> list:
    try:
        loaded = httpx.get(f"{base_url}/api/ps", timeout=timeout).json().get("models", [])
    except Exception:
        return []
    unloaded = []
    for model in loaded:
        name = model.get("model") or model.get("name")
        if not name:
            continue
        try:
            httpx.post(f"{base_url}/api/generate", json={"model": name, "keep_alive": 0}, timeout=timeout)
            unloaded.append(name)
        except Exception:
            pass
    if unloaded:
        logger.info("Unloaded %s from Ollama to free memory for the render.", ", ".join(unloaded))
    return unloaded
