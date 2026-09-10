"""Step 2: Generate TTS narration audio."""

import asyncio
import json
from pathlib import Path
from typing import Optional

from services.logger.progress import tracker

from .helpers import logger


def _safe_audio_label(label, fallback: str) -> str:
    """Matches main.py's _video_safe_label so filenames stay consistent
    with the ones the CLI test commands (test_tts/test_tts_all) produce."""
    safe = "".join(
        char for char in str(label) if char.isalnum() or char in (" ", "_", "-")
    ).strip().replace(" ", "_")
    return safe or fallback


def generate_audio(
    cleaned_route: dict,
    project_config_path: str,
    output_audio_dir: Optional[str] = None,
) -> dict:
    """
    Generates Irodori TTS audio based on the parsed route, via the same
    IrodoriTTSClient + AudioProcessor pair main.py's test_tts/test_tts_all
    use directly (there is no separate "TTSPipelineManager" — an earlier
    version of this function referenced one that was never actually
    defined anywhere in services.tts, which made this step silently no-op
    on every real pipeline run).
    """
    logger.info("Step 2: Generating TTS audio for config: %s", project_config_path)

    audio_durations = []
    audio_pauses = []
    audio_paths = []
    subtitle_paths = []
    waypoints = []

    try:
        config_path = Path(project_config_path)
        if not config_path.exists():
            logger.warning("Step 2: No project config found. Skipping TTS.")
            return {
                "audio_durations": [],
                "audio_pauses": [],
                "audio_paths": [],
                "subtitle_paths": [],
            }

        with open(config_path, "r", encoding="utf-8") as f:
            project_config = json.load(f)

        waypoints = project_config.get("waypoints", [])

        from services.tts.ttsengine import AudioProcessor, IrodoriTTSClient

        output_dir = Path(output_audio_dir or (config_path.parent / "audio"))
        output_dir.mkdir(parents=True, exist_ok=True)
        client = IrodoriTTSClient(output_dir=output_dir)
        processor = AudioProcessor(output_dir=output_dir)

        # [NOTE] [TTS] Awaits each waypoint in order inside this loop, so despite being async the TTS calls run fully sequentially, not concurrently.
        async def _generate_all_speech():
            for idx, wp in enumerate(waypoints):
                # The waypoint editor writes narration as separate
                # arriving/attraction legs (see WaypointEditor.tsx); "script"/
                # "narration"/"voiceover" are only for older job_config.json
                # files that predate that split.
                arriving = (wp.get("arrivingNarration") or "").strip()
                attraction = (wp.get("attractionNarration") or wp.get("narration") or "").strip()
                script = " ".join(part for part in (arriving, attraction) if part) or (
                    wp.get("script") or wp.get("voiceover")
                )
                label = wp.get("label", f"Waypoint {idx + 1}")

                if not script:
                    audio_durations.append(0.0)
                    audio_pauses.append([])
                    audio_paths.append(None)
                    subtitle_paths.append(None)
                    continue

                tracker.show(f"Generating TTS {idx + 1}/{len(waypoints)}: {label}")

                logger.info(
                    f"Step 2: [%d/%d] Generating audio for: '%s'",
                    idx + 1,
                    len(waypoints),
                    label,
                )

                # 1. Generate speech via IrodoriTTSClient — auto-starts the
                # local TTS server (and waits for it to become healthy) if
                # it isn't already running, instead of failing outright.
                audio_filename = (
                    f"02_waypoint_{idx + 1:02d}_"
                    f"{_safe_audio_label(label, f'leg{idx + 1}')}.wav"
                )
                wav_path = await client.generate_speech(
                    script.strip(), output_filename=audio_filename
                )

                # 2. Analyze pauses via AudioProcessor
                analysis = processor.analyze_pauses(wav_path)

                audio_durations.append(analysis.get("duration_seconds", 0.0))
                audio_pauses.append(analysis.get("pauses", []))
                audio_paths.append(wav_path)

                # Subtitles can be injected here later if your TTS engine outputs them
                subtitle_paths.append(None)

        # Execute the async function synchronously within the pipeline
        asyncio.run(_generate_all_speech())
        tracker.clear()

        logger.info("Step 2 complete: TTS audio successfully generated.")
        return {
            "audio_durations": audio_durations,
            "audio_pauses": audio_pauses,
            "audio_paths": audio_paths,
            "subtitle_paths": subtitle_paths,
        }

    except ImportError as e:
        logger.error(
            "Step 2 failed: Could not import IrodoriTTSClient/AudioProcessor "
            "from services.tts.ttsengine. %s",
            e,
        )
        return {
            "audio_durations": [],
            "audio_pauses": [],
            "audio_paths": [],
            "subtitle_paths": [],
        }
    except Exception as e:
        logger.error("Step 2 failed: TTS Audio generation encountered an error: %s", e)
        # [NOTE] [TTS] Pad out to one entry per waypoint (rather than discarding) so a mid-loop failure still returns whatever audio was already generated, index-aligned with waypoints.
        pad_count = max(0, len(waypoints) - len(audio_durations))
        audio_durations.extend([0.0] * pad_count)
        audio_pauses.extend([[]] * pad_count)
        audio_paths.extend([None] * pad_count)
        subtitle_paths.extend([None] * pad_count)
        return {
            "audio_durations": audio_durations,
            "audio_pauses": audio_pauses,
            "audio_paths": audio_paths,
            "subtitle_paths": subtitle_paths,
        }
