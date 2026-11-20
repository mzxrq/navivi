"""Narration-synthesis settings: the TTSConfig dataclass and the job_config.json -> TTSConfig mapping."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from services import tuning
from services.logger.logger import setup_logger

logger = setup_logger("TTSEngine")


@dataclass(frozen=True)
class TTSConfig:
    """Narration-synthesis parameters sent to the Irodori TTS server.

    Covers the request's named fields (model/voice/speed/response_format)
    directly; anything beyond that — the server's ~30 advanced sampling
    knobs (cfg_scale, seed, chunking, ...) — goes through `extra_options`
    and is forwarded verbatim as the request's `irodori` sub-object, so this
    class doesn't have to mirror each one by hand to stay "fully configurable".
    Built once per client/call (frozen, validated up front) rather than
    re-validated on every request.
    """

    model: str = tuning.TTS_MODEL
    voice: str = tuning.TTS_VOICE
    speed: float = tuning.TTS_SPEED
    response_format: Optional[str] = tuning.TTS_RESPONSE_FORMAT
    caption: Optional[str] = tuning.TTS_CAPTION
    hardware_override: Optional[str] = None
    extra_options: Dict[str, Any] = field(default_factory=dict)
    quality: str = tuning.TTS_QUALITY_DEFAULT
    engine: str = tuning.TTS_ENGINE_DEFAULT

    def __post_init__(self) -> None:
        if not (tuning.TTS_MIN_SPEED <= self.speed <= tuning.TTS_MAX_SPEED):
            raise ValueError(
                f"TTS speed must be between {tuning.TTS_MIN_SPEED} and "
                f"{tuning.TTS_MAX_SPEED}, got {self.speed}"
            )

    def to_payload(self, text: str) -> Dict[str, Any]:
        """Serializes this config + the narration text into the request body IrodoriTTSClient posts."""
        payload: Dict[str, Any] = {
            "model": self.model,
            "input": text,
            "voice": self.voice,
            "speed": self.speed,
        }
        if self.response_format:
            payload["response_format"] = self.response_format
        if self.caption:
            payload["caption"] = self.caption
        options = {**tuning.TTS_QUALITY_PRESETS.get(self.quality, {}), **self.extra_options}
        if options:
            payload["irodori"] = options
        return payload


def _kokoro_config(tts: Dict[str, Any], speed: float) -> TTSConfig:
    """Kokoro's config: a fixed voice from its own list, no caption, no cloning."""
    voice = str(tts.get("kokoro_voice") or tuning.KOKORO_VOICE)
    if voice not in tuning.KOKORO_VOICES:
        logger.warning("Kokoro voice '%s' is not one of %s; using '%s'.", voice, list(tuning.KOKORO_VOICES), tuning.KOKORO_VOICE)
        voice = tuning.KOKORO_VOICE
    return TTSConfig(model="kokoro", voice=voice, speed=speed, caption=None, engine="kokoro")


def tts_config_from_settings(settings: Optional[Dict[str, Any]]) -> TTSConfig:
    """Builds a TTSConfig from job_config.json's settings.

    Reads settings.tts.engine/voice/kokoro_voice/speed/quality and hardware_spec_override;
    an unknown value falls back to its tuning.py default with a warning.
    """
    from services.tts import voices

    settings = settings or {}
    tts = settings.get("tts") or {}
    engine = str(tts.get("engine") or tuning.TTS_ENGINE_DEFAULT)
    if engine not in tuning.TTS_ENGINES:
        logger.warning("TTS engine '%s' is not one of %s; using '%s'.", engine, list(tuning.TTS_ENGINES), tuning.TTS_ENGINE_DEFAULT)
        engine = tuning.TTS_ENGINE_DEFAULT
    try:
        speed = float(tts.get("speed", tuning.TTS_SPEED))
    except (TypeError, ValueError):
        speed = tuning.TTS_SPEED
    if not (tuning.TTS_MIN_SPEED <= speed <= tuning.TTS_MAX_SPEED):
        logger.warning("TTS speed %s out of range; using %s.", speed, tuning.TTS_SPEED)
        speed = tuning.TTS_SPEED

    if engine == "kokoro":
        return _kokoro_config(tts, speed)

    voice = str(tts.get("voice") or tuning.TTS_VOICE).strip()
    if engine == "qwen3" and (voice == voices.NO_REF_VOICE or not voices.voice_file(voice)):
        voice = tuning.TTS_VOICE  # it clones a recording, so "no reference" cannot work
    if not voices.voice_exists(voice):
        logger.warning("TTS voice '%s' not found in %s; using '%s'.", voice, voices.voices_dir(), tuning.TTS_VOICE)
        voice = tuning.TTS_VOICE
    caption = tts.get("caption", tuning.TTS_CAPTION)
    caption = str(caption).strip() if caption else None
    quality = str(tts.get("quality") or tuning.TTS_QUALITY_DEFAULT)
    if quality not in tuning.TTS_QUALITY_PRESETS:
        logger.warning("TTS quality '%s' is not one of %s; using '%s'.", quality, list(tuning.TTS_QUALITY_PRESETS), tuning.TTS_QUALITY_DEFAULT)
        quality = tuning.TTS_QUALITY_DEFAULT
    hardware = settings.get("hardware_spec_override")
    return TTSConfig(
        model="qwen3" if engine == "qwen3" else TTSConfig.model,
        voice=voice,
        speed=speed,
        caption=None if engine == "qwen3" else caption,
        quality=quality,
        engine=engine,
        hardware_override=hardware if hardware in ("low", "high") else None,
    )
