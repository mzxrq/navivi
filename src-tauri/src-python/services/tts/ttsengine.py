"""TTS engine service: the import path the rest of the app uses, re-exporting the modules it was split into.

- tts_config.py: TTSConfig and the job_config.json -> TTSConfig mapping
- text_split.py: chunking a narration text for single TTS requests
- ffmpeg_tools.py: FFmpegManager (binary resolution, probing) and the narration speed filter
- audio_processor.py: AudioProcessor (pause analysis, silence, concatenation)
- server_client.py: starting, sharing and stopping a local TTS server subprocess
- clients.py: the Irodori, Qwen3 and Kokoro clients and make_tts_client

Code that moved looks its own names up in its new module, so a test that replaces one (cut_off_ratio,
ensure_reference_latent, apply_speed, ...) patches it there, not here.
"""

from services.tts.audio_processor import AudioProcessor
from services.tts.clients import (
    IrodoriTTSClient,
    KokoroTTSClient,
    Qwen3TTSClient,
    ensure_reference_latent,
    make_tts_client,
    qwen3_device,
    qwen3_language,
    stop_all_tts_servers,
)
from services.tts.ffmpeg_tools import FFmpegManager, _atempo_filter, apply_speed
from services.tts.text_split import chunk_limits, split_text_for_tts
from services.tts.tts_config import TTSConfig, tts_config_from_settings

__all__ = [
    "AudioProcessor",
    "FFmpegManager",
    "IrodoriTTSClient",
    "KokoroTTSClient",
    "Qwen3TTSClient",
    "TTSConfig",
    "_atempo_filter",
    "apply_speed",
    "chunk_limits",
    "ensure_reference_latent",
    "make_tts_client",
    "qwen3_device",
    "qwen3_language",
    "split_text_for_tts",
    "stop_all_tts_servers",
    "tts_config_from_settings",
]
