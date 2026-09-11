"""Step 2: Generate TTS narration audio.

This is the TTS domain's core module — services/cli/tts_commands.py is a
thin wrapper around generate_waypoint_audio()/stop_tts_server() below,
rather than reimplementing narration-field resolution and filename
conventions on its own (which is how the TTS audio filename scheme ended
up independently re-derived in four different places)."""

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Optional

from services.logger.progress import tracker

from .helpers import logger, output_is_valid, project_audio_dir, waypoint_audio_filename


def _resolve_narration_script(waypoint: dict) -> Optional[str]:
    """The waypoint editor writes narration as separate arriving/attraction
    legs (see WaypointEditor.tsx); "script"/"narration"/"voiceover" are only
    for older job_config.json files that predate that split."""
    arriving = (waypoint.get("arrivingNarration") or "").strip()
    attraction = (waypoint.get("attractionNarration") or waypoint.get("narration") or "").strip()
    script = " ".join(part for part in (arriving, attraction) if part) or (
        waypoint.get("script") or waypoint.get("voiceover")
    )
    return script.strip() if isinstance(script, str) and script.strip() else None


async def generate_waypoint_audio(
    waypoint: dict,
    idx: int,
    client: Any,
    processor: Any,
    output_dir: Path,
    force: bool = False,
) -> Dict[str, Any]:
    """Generates (or, if already present and not `force`, reuses) one
    waypoint's TTS audio and its pause/duration analysis. Raises ValueError
    if the waypoint has no narration text — callers decide whether that
    should abort (CLI, fail-fast) or be padded over and continued past
    (the pipeline's generate_audio(), which needs every waypoint
    represented, narrated or not)."""
    if not isinstance(waypoint, dict):
        raise ValueError(f"Waypoint {idx} must be an object")

    script = _resolve_narration_script(waypoint)
    if not script:
        raise ValueError(f"Waypoint {idx} has no script, narration, or voiceover text")

    label = waypoint.get("label", f"Waypoint {idx + 1}")
    audio_filename = waypoint_audio_filename(idx, label)
    existing_path = Path(output_dir) / audio_filename

    if not force and output_is_valid(existing_path):
        logger.info(
            "Step 2: [%d] '%s' already exists — skipping TTS.", idx + 1, label
        )
        audio_path = str(existing_path)
    else:
        logger.info("Step 2: [%d] Generating audio for: '%s'", idx + 1, label)
        audio_path = await client.generate_speech(script, output_filename=audio_filename)

    analysis = processor.analyze_pauses(audio_path)
    return {
        "index": idx,
        "label": label,
        "text": script,
        "audio_path": audio_path,
        "duration_seconds": analysis.get("duration_seconds", 0.0),
        "pauses": analysis.get("pauses", []),
    }


def stop_tts_server() -> None:
    """Force-stops the TTS server immediately after use — its idle timeout
    would otherwise keep it loaded in VRAM, contending with the attraction
    step's ComfyUI/SDXL pipeline right after."""
    from services.tts.ttsengine import IrodoriTTSClient
    IrodoriTTSClient.stop_server()


def generate_audio(
    cleaned_route: dict,
    project_config_path: str,
    output_audio_dir: Optional[str] = None,
    force: bool = False,
) -> dict:
    """
    Generates Irodori TTS audio based on the parsed route, via the same
    IrodoriTTSClient + AudioProcessor pair services/cli/tts_commands.py's
    test_tts/test_tts_all use (both now go through generate_waypoint_audio()
    above, rather than each maintaining their own copy of this logic).

    Checkpointing: if a waypoint's audio file already exists (unless
    `force`), the TTS call is skipped — but the file is still re-analyzed
    via AudioProcessor so audio_durations/audio_pauses stay populated for
    downstream steps.
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

        output_dir = Path(output_audio_dir) if output_audio_dir else project_audio_dir(config_path.parent)
        output_dir.mkdir(parents=True, exist_ok=True)
        client = IrodoriTTSClient(output_dir=output_dir)
        processor = AudioProcessor(output_dir=output_dir)

        # [NOTE] [TTS] Awaits each waypoint in order inside this loop, so despite being async the TTS calls run fully sequentially, not concurrently.
        async def _generate_all_speech():
            for idx, wp in enumerate(waypoints):
                label = wp.get("label", f"Waypoint {idx + 1}") if isinstance(wp, dict) else f"Waypoint {idx + 1}"

                # Check upfront, before ever showing "Generating..." or
                # touching the TTS server — a waypoint with no narration
                # text has nothing to generate, so skip it outright instead
                # of attempting (and silently failing) the call.
                if not isinstance(wp, dict) or not _resolve_narration_script(wp):
                    logger.info(
                        "Step 2: [%d] Skipping '%s' — no narration script configured.",
                        idx + 1, label,
                    )
                    audio_durations.append(0.0)
                    audio_pauses.append([])
                    audio_paths.append(None)
                    subtitle_paths.append(None)
                    continue

                tracker.show(f"Generating TTS {idx + 1}/{len(waypoints)}: {label}")
                try:
                    clip = await generate_waypoint_audio(
                        wp, idx, client, processor, output_dir, force=force
                    )
                except ValueError:
                    # Safety net for any other validation inside
                    # generate_waypoint_audio — the script check above
                    # should already catch the common case.
                    audio_durations.append(0.0)
                    audio_pauses.append([])
                    audio_paths.append(None)
                    subtitle_paths.append(None)
                    continue

                audio_durations.append(clip["duration_seconds"])
                audio_pauses.append(clip["pauses"])
                audio_paths.append(clip["audio_path"])
                # Subtitles are built by subtitle_step.build_subtitles() from
                # these audio_paths, not here.
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
