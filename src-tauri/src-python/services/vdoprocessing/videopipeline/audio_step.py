"""Step 2: Generate TTS narration audio."""

import asyncio
import json
from pathlib import Path
from typing import Optional

from .helpers import logger


def generate_audio(
    cleaned_route: dict,
    project_config_path: str,
    output_audio_dir: Optional[str] = None,
) -> dict:
    """
    Generates Irodori TTS audio based on the parsed route.
    Uses the local TTSPipelineManager from tts.py to generate and analyze clips.
    """
    logger.info("Step 2: Generating TTS audio for config: %s", project_config_path)

    audio_durations = []
    audio_pauses = []
    audio_paths = []
    subtitle_paths = []

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
        print(
            f"\n[Step 2/5] Generating Narration Audio for {len(waypoints)} Waypoints..."
        )

        # Import the unified manager from your new tts.py file
        from services.tts import TTSPipelineManager

        # Properly initialize the manager with the target directory
        if output_audio_dir:
            Path(output_audio_dir).mkdir(parents=True, exist_ok=True)
            tts_manager = TTSPipelineManager(output_audio_dir=Path(output_audio_dir))
        else:
            tts_manager = TTSPipelineManager()

        # Create an async worker to process all TTS tasks
        async def _generate_all_speech():
            for idx, wp in enumerate(waypoints):
                # Look for narration text in standard keys
                script = wp.get("script") or wp.get("narration") or wp.get("voiceover")
                label = wp.get("label", f"Waypoint {idx + 1}")

                if not script:
                    audio_durations.append(0.0)
                    audio_pauses.append([])
                    audio_paths.append(None)
                    subtitle_paths.append(None)
                    continue

                print(f"   Synthesizing audio [{idx + 1}/{len(waypoints)}]: '{label}'")

                logger.info(
                    f"Step 2: [%d/%d] Generating audio for: '%s'",
                    idx + 1,
                    len(waypoints),
                    label,
                )

                # 1. Generate Speech via IrodoriTTSClient
                wav_path = await tts_manager.get_speech(script)

                # 2. Analyze pauses via AudioProcessor
                analysis = tts_manager.analyze_pauses(wav_path)

                audio_durations.append(analysis.get("total_duration", 0.0))
                audio_pauses.append(analysis.get("pauses", []))
                audio_paths.append(wav_path)

                # Subtitles can be injected here later if your TTS engine outputs them
                subtitle_paths.append(None)

        # Execute the async function synchronously within the pipeline
        asyncio.run(_generate_all_speech())

        logger.info("Step 2 complete: TTS audio successfully generated.")
        return {
            "audio_durations": audio_durations,
            "audio_pauses": audio_pauses,
            "audio_paths": audio_paths,
            "subtitle_paths": subtitle_paths,
        }

    except ImportError as e:
        logger.error(
            "Step 2 failed: Could not import TTSPipelineManager from services.tts. %s",
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
        return {
            "audio_durations": [],
            "audio_pauses": [],
            "audio_paths": [],
            "subtitle_paths": [],
        }
