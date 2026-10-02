"""Voice library actions for the frontend (main.py tts_voice_* / tts_voices_list).

Each takes the JSON payload dict and returns a JSON-able dict; failures come
back as {"success": False, "error": ...} so the UI gets a readable message."""

import asyncio
import re
from typing import Any, Callable, Dict

from services.tts import voices

PREVIEW_TEXT = "こんにちは。この声で、旅の案内をお届けします。"

VOICE_ACTIONS = ("tts_voices_list", "tts_voice_add", "tts_voice_delete", "tts_voice_preview", "tts_engines", "tts_install_kokoro", "tts_install_qwen3")


def voices_list(_payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"success": True, "voices_dir": str(voices.voices_dir()), "voices": voices.list_voices()}


def voice_add(payload: Dict[str, Any]) -> Dict[str, Any]:
    voice = voices.add_voice(
        payload["path"], payload.get("id") or None, replace=bool(payload.get("replace"))
    )
    return {"success": True, "voice": voice}


def voice_delete(payload: Dict[str, Any]) -> Dict[str, Any]:
    voice_id = payload["id"]
    if not voices.delete_voice(voice_id):
        raise FileNotFoundError(f"Voice '{voice_id}' was not found.")
    return {"success": True, "id": voice_id}


def engines(_payload: Dict[str, Any]) -> Dict[str, Any]:
    """What the Voice tab needs to offer the fast engine: whether it is set up and the voices it has."""
    from services import tuning
    from services.tts.ttsengine import KokoroTTSClient, Qwen3TTSClient

    return {
        "success": True,
        "qwen3": {"ready": Qwen3TTSClient.is_ready()},
        "kokoro": {
            "ready": KokoroTTSClient.is_ready(),
            "default_voice": tuning.KOKORO_VOICE,
            "voices": [{"id": vid, "label": label} for vid, label in tuning.KOKORO_VOICES.items()],
        },
    }


def install_kokoro(_payload: Dict[str, Any]) -> Dict[str, Any]:
    from services.tts.kokoro_setup import install_kokoro as run

    return run()


def install_qwen3(_payload: Dict[str, Any]) -> Dict[str, Any]:
    from services.tts.qwen3_setup import install_qwen3 as run

    return run()


def voice_preview(payload: Dict[str, Any]) -> Dict[str, Any]:
    from services.tts.ttsengine import make_tts_client

    engine = str(payload.get("engine") or "irodori")
    voice = str(payload.get("voice") or "").strip()
    if engine != "kokoro" and not voices.voice_exists(voice):
        raise FileNotFoundError(f"Voice '{voice}' was not found.")
    tts = {"engine": engine, "voice": voice, "kokoro_voice": voice}
    if payload.get("speed") is not None:
        tts["speed"] = payload["speed"]
    if payload.get("quality"):
        tts["quality"] = payload["quality"]
    out_dir = voices.voices_dir() / ".preview"
    client = make_tts_client({"tts": tts, "hardware_spec_override": payload.get("hardware")}, out_dir)
    config = client.config
    text = str(payload.get("text") or PREVIEW_TEXT).strip()
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", f"{engine}_{voice}")
    # Server left running on purpose: the next preview is fast, the idle watchdog stops it.
    path = asyncio.run(client.generate_speech(text, f"{safe}.wav"))
    return {"success": True, "voice": voice, "speed": config.speed, "text": text, "path": path}


_HANDLERS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "tts_voices_list": voices_list,
    "tts_voice_add": voice_add,
    "tts_voice_delete": voice_delete,
    "tts_voice_preview": voice_preview,
    "tts_engines": engines,
    "tts_install_kokoro": install_kokoro,
    "tts_install_qwen3": install_qwen3,
}


def run_voice_action(action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return _HANDLERS[action](payload or {})
    except KeyError as exc:
        return {"success": False, "error": f"Missing field: {exc.args[0]}"}
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:  # e.g. the TTS server failed to start
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
