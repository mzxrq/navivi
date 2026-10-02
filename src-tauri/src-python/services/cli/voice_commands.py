"""Voice library actions for the frontend (main.py tts_voice_* / tts_voices_list).

Each takes the JSON payload dict and returns a JSON-able dict; failures come
back as {"success": False, "error": ...} so the UI gets a readable message."""

import asyncio
import re
from typing import Any, Callable, Dict

from services.tts import voices

PREVIEW_TEXT = "こんにちは。この声で、旅の案内をお届けします。"

VOICE_ACTIONS = ("tts_voices_list", "tts_voice_add", "tts_voice_delete", "tts_voice_preview")


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


def voice_preview(payload: Dict[str, Any]) -> Dict[str, Any]:
    from services.tts.ttsengine import IrodoriTTSClient, tts_config_from_settings

    voice = str(payload.get("voice") or "").strip()
    if not voices.voice_exists(voice):
        raise FileNotFoundError(f"Voice '{voice}' was not found.")
    tts = {"voice": voice}
    if payload.get("speed") is not None:
        tts["speed"] = payload["speed"]
    if payload.get("quality"):
        tts["quality"] = payload["quality"]
    config = tts_config_from_settings({"tts": tts, "hardware_spec_override": payload.get("hardware")})
    text = str(payload.get("text") or PREVIEW_TEXT).strip()
    out_dir = voices.voices_dir() / ".preview"
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", voice)
    client = IrodoriTTSClient(output_dir=out_dir, config=config)
    # Server left running on purpose: the next preview is fast, the idle watchdog stops it.
    path = asyncio.run(client.generate_speech(text, f"{safe}.wav"))
    return {"success": True, "voice": voice, "speed": config.speed, "text": text, "path": path}


_HANDLERS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "tts_voices_list": voices_list,
    "tts_voice_add": voice_add,
    "tts_voice_delete": voice_delete,
    "tts_voice_preview": voice_preview,
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
