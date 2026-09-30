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

from services import tuning
from services.localization.cues import clean_text, cue_times, strip_cues
from services.logger.progress import tracker

from .helpers import (
    attraction_audio_filename,
    logger,
    output_is_valid,
    project_audio_dir,
    waypoint_audio_filename,
)


def is_unvisited_stopby(waypoint: dict) -> bool:
    """A stop-by the route only passes near (not connected to it): the walker
    never goes there, so it gets no narration audio and no attraction video."""
    return isinstance(waypoint, dict) and bool(waypoint.get("isStopBy")) and not waypoint.get("connectToRoute")


# Whether a leg speaks only its route (arriving) narration. On when the
# project makes attraction videos (the pipeline sets it, see
# set_route_only_legs): each waypoint's attraction clip plays its
# attractionNarration, so the leg speaking it too played the same text twice,
# back to back. Off (the CLI modes, or attraction videos turned off): the leg
# carries both, since nothing else would speak the attraction text.
_ROUTE_ONLY_LEGS = False


def set_route_only_legs(on: bool) -> None:
    global _ROUTE_ONLY_LEGS
    _ROUTE_ONLY_LEGS = bool(on)


def has_own_attraction_clip(waypoint: dict) -> bool:
    """The waypoint gets an attraction clip that speaks its attraction text:
    it has that text and a photo (attraction_step makes clips from
    popup_image), and the walker actually goes there."""
    return (
        isinstance(waypoint, dict)
        and not is_unvisited_stopby(waypoint)
        and bool((waypoint.get("attractionNarration") or waypoint.get("narration") or "").strip())
        and bool(waypoint.get("popup_image"))
    )


def base_narration_script(waypoint: dict, route_only: Optional[bool] = None) -> Optional[str]:
    """The narration the user wrote for a waypoint, timing cue tags included
    (see localization/cues.py). The waypoint editor writes narration as
    separate arriving/attraction legs (see WaypointEditor.tsx);
    "script"/"narration"/"voiceover" are only for older job_config.json files
    that predate that split. With route-only legs (see _ROUTE_ONLY_LEGS) a
    waypoint with its own attraction clip keeps only its arriving part."""
    if route_only is None:
        route_only = _ROUTE_ONLY_LEGS
    arriving = (waypoint.get("arrivingNarration") or "").strip()
    attraction = (waypoint.get("attractionNarration") or waypoint.get("narration") or "").strip()
    if route_only and has_own_attraction_clip(waypoint):
        attraction = ""
    script = " ".join(part for part in (arriving, attraction) if part) or (
        waypoint.get("script") or waypoint.get("voiceover")
    )
    return script.strip() if isinstance(script, str) and script.strip() else None


def raw_narration_script(waypoint: dict) -> Optional[str]:
    """The narration with its cue tags: the version narration_step stored
    (attached in memory as `_cued_script`) when there is one, else the user's."""
    return waypoint.get("_cued_script") or base_narration_script(waypoint)


def waypoint_cue_key(waypoint: dict, pos: int) -> str:
    """Key of a waypoint in the cue store (its stable id, else its position)."""
    return str(waypoint.get("id") or f"wp{pos}")


def apply_cued_scripts(waypoints: list, project_dir) -> int:
    """Attaches each waypoint's stored cued script to the in-memory waypoint as
    `_cued_script`. job_config.json itself is never touched. Returns how many."""
    from .narration_step import CueStore

    store = CueStore(project_dir)
    attached = 0
    for pos, wp in enumerate(waypoints):
        if not isinstance(wp, dict):
            continue
        wp.pop("_cued_script", None)
        base = base_narration_script(wp)
        cued = store.cued_text(waypoint_cue_key(wp, pos), base) if base else None
        if cued:
            wp["_cued_script"] = cued
            attached += 1
    return attached


OVERVIEW_CUE_KEY = "overview"


def overview_tagged_script(project_config: dict, project_dir) -> str:
    """The overview narration with its cue tags: the version narration_step
    stored (auto-placed {n} / {go}) when it was made from this exact script,
    else the user's own."""
    from .narration_step import CueStore

    base = project_config.get("overview_narration") or ""
    if base and project_dir is not None:
        return CueStore(project_dir).cued_text(OVERVIEW_CUE_KEY, base) or base
    return base


def _resolve_narration_script(waypoint: dict) -> Optional[str]:
    """The spoken text of a waypoint's narration: its script without cue tags.
    TTS and subtitles both go through this, so a tag is never read aloud or
    burned onto the video."""
    return clean_text(raw_narration_script(waypoint)).strip() or None


def _resolve_attraction_narration_script(waypoint: dict) -> Optional[str]:
    """The attraction clip's OWN narration — attractionNarration alone (or
    the legacy "narration" fallback), deliberately never arrivingNarration.
    Distinct from _resolve_narration_script, which combines both for the
    waypoint's arrival/leg audio: reusing that combined audio on the
    attraction clip would replay the arrival narration there too, which is
    wrong even when attractionNarration IS set, and especially wrong when
    it's blank — the combined script is then 100% arrival narration, with
    nothing about the attraction at all."""
    text = clean_text(waypoint.get("attractionNarration") or waypoint.get("narration") or "").strip()
    return text or None


def _voice_note_path(audio_path) -> Path:
    """Beside each narration clip: the voice + speed it was spoken with."""
    return Path(str(audio_path) + ".voice.json")


def _client_fingerprint(client: Any) -> Optional[dict]:
    config = getattr(client, "config", None)
    if config is None or not hasattr(config, "voice"):
        return None
    fp = getattr(client, "_voice_fingerprint", None)
    if fp is None:
        from services.tts.voices import voice_fingerprint
        fp = voice_fingerprint(config.voice, config.speed)
        try:
            client._voice_fingerprint = fp
        except AttributeError:
            pass
    return fp


def _voice_matches(audio_path, client: Any) -> bool:
    """False when the clip was made with another voice/speed than the project's now."""
    from services.tts.voices import LEGACY_FINGERPRINT, fingerprints_match

    current = _client_fingerprint(client)
    if current is None:
        return True
    try:
        stored = json.loads(_voice_note_path(audio_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stored = LEGACY_FINGERPRINT
    return fingerprints_match(stored, current)


def _write_voice_note(audio_path, client: Any) -> None:
    fp = _client_fingerprint(client)
    if fp is None:
        return
    try:
        _voice_note_path(audio_path).write_text(json.dumps(fp), encoding="utf-8")
    except OSError:
        pass


def apply_pronunciation_dictionary(text: str, dictionary: list) -> str:
    if not text or not dictionary:
        return text
    for entry in dictionary:
        word = entry.get("word")
        reading = entry.get("reading")
        if word and reading:
            text = text.replace(word, reading)
    return text

async def generate_attraction_audio_for_waypoint(
    waypoint: dict,
    idx: int,
    client: Any,
    processor: Any,
    output_dir: Path,
    force: bool = False,
    project_dir=None,
    pronunciation_dict: list = [],
) -> Optional[Dict[str, Any]]:
    """Generates (or reuses) one waypoint's attraction-only TTS audio, in
    its own "04_attraction_" filename namespace (see
    helpers.attraction_audio_filename) so it's never confused with — or
    accidentally overwritten by — that same waypoint's combined arrival+
    attraction audio (helpers.waypoint_audio_filename). Returns None (no
    audio, no subtitle, nothing muxed) when attractionNarration is blank —
    the attraction clip should stay silent rather than inherit whatever
    text the arrival narration happens to carry."""
    script = _resolve_attraction_narration_script(waypoint)
    if not script:
        return None
    tts_script = apply_pronunciation_dictionary(script, pronunciation_dict)

    label = waypoint.get("label", f"Waypoint {idx + 1}")
    audio_filename = attraction_audio_filename(idx, label)
    existing_path = Path(output_dir) / audio_filename

    if not force and output_is_valid(existing_path) and _voice_matches(existing_path, client):
        logger.info(
            "Step 2: [%d] '%s' attraction narration already exists — skipping TTS.",
            idx + 1, label,
        )
        audio_path = str(existing_path)
    else:
        logger.info("Step 2: [%d] Generating attraction narration for: '%s'", idx + 1, label)
        audio_path = await client.generate_speech(tts_script, output_filename=audio_filename)
        _write_voice_note(audio_path, client)

    analysis = processor.analyze_pauses(audio_path)
    return {
        "text": script,
        "audio_path": audio_path,
        "duration_seconds": analysis.get("duration_seconds", 0.0),
        "pauses": analysis.get("pauses", []),
    }


async def generate_overview_audio(
    project_config: dict,
    client: Any,
    processor: Any,
    output_dir: Path,
    force: bool = False,
    project_dir=None,
    pronunciation_dict: list = [],
) -> Optional[Dict[str, Any]]:
    """Generates (or reuses) the TTS audio for job_config.json's top-level
    "overview_narration" script -- the map-editor's OverviewPanel.tsx lets
    a project set a narration for the whole-route overview clip, separate
    from any per-waypoint narration, but nothing downstream ever read that
    field: no audio was ever generated for it, so the overview clip always
    played silent regardless of what was typed there. Returns None (same
    as a waypoint with no script) when the field is empty/missing."""
    tagged = overview_tagged_script(project_config, project_dir)
    script = clean_text(tagged).strip()
    if not script:
        return None
    tts_script = apply_pronunciation_dictionary(script, pronunciation_dict)

    audio_filename = "00_overview_narration.wav"
    existing_path = Path(output_dir) / audio_filename

    if not force and output_is_valid(existing_path) and _voice_matches(existing_path, client):
        logger.info("Step 2: Overview narration audio already exists — skipping TTS.")
        audio_path = str(existing_path)
    else:
        logger.info("Step 2: Generating overview narration audio.")
        audio_path = await client.generate_speech(tts_script, output_filename=audio_filename)
        _write_voice_note(audio_path, client)

    analysis = processor.analyze_pauses(audio_path)
    # Where each cue ({start}, {1}, {2}, {end}) falls in the real audio: the
    # overview animation lands its stops on them (overview.py).
    clean, cues = strip_cues(tagged)
    cue_seconds = cue_times(
        cues, clean, analysis.get("duration_seconds", 0.0), analysis.get("pauses", [])
    ) if cues else {}
    # The overview is sized first (60-120s) and its script to it: say when
    # the real voice misses that by more than the 3s the video can absorb.
    from services.localization.overview_script import (
        in_overview_range, overview_target_seconds, visible_waypoints,
    )

    target = overview_target_seconds(project_config, len(visible_waypoints(project_config)))
    spoken = analysis.get("duration_seconds", 0.0)
    (logger.info if in_overview_range(spoken) else logger.warning)(
        "Overview narration is %.1fs (aimed at %.0fs; the overview must be 60-120s).",
        spoken, target,
    )
    return {
        "text": script,
        "audio_path": audio_path,
        "duration_seconds": analysis.get("duration_seconds", 0.0),
        "pauses": analysis.get("pauses", []),
        "cue_times": cue_seconds,
    }


def _spoken_text_path(audio_path) -> Path:
    """Beside each waypoint's audio: the exact text it speaks."""
    return Path(str(audio_path) + ".txt")


def _spoken_text_matches(audio_path, script: str, waypoint: dict) -> bool:
    """Whether the audio already on disk speaks `script`. Audio made before
    this note existed spoke the full arriving + attraction text, so without a
    note that is what it is taken to say."""
    note = _spoken_text_path(audio_path)
    try:
        return note.read_text(encoding="utf-8") == script
    except OSError:
        legacy = clean_text(base_narration_script(waypoint, route_only=False) or "")
        # Spacing aside: a cued script joins its parts without the space.
        return "".join(legacy.split()) == "".join(script.split())


async def generate_waypoint_audio(
    waypoint: dict,
    idx: int,
    client: Any,
    processor: Any,
    output_dir: Path,
    force: bool = False,
    pronunciation_dict: list = [],
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
    tts_script = apply_pronunciation_dictionary(script, pronunciation_dict)

    label = waypoint.get("label", f"Waypoint {idx + 1}")
    audio_filename = waypoint_audio_filename(idx, label)
    existing_path = Path(output_dir) / audio_filename

    if (
        not force
        and output_is_valid(existing_path)
        and _spoken_text_matches(existing_path, script, waypoint)
        and _voice_matches(existing_path, client)
    ):
        logger.info(
            "Step 2: [%d] '%s' already exists — skipping TTS.", idx + 1, label
        )
        audio_path = str(existing_path)
    else:
        logger.info("Step 2: [%d] Generating audio for: '%s'", idx + 1, label)
        audio_path = await client.generate_speech(script, output_filename=audio_filename)
        try:
            _spoken_text_path(audio_path).write_text(script, encoding="utf-8")
        except OSError:
            pass
        _write_voice_note(audio_path, client)

    analysis = processor.analyze_pauses(audio_path)
    return {
        "index": idx,
        "label": label,
        "text": script,
        "audio_path": audio_path,
        "duration_seconds": analysis.get("duration_seconds", 0.0),
        "pauses": analysis.get("pauses", []),
    }


def existing_audio_data(project_config_path: str) -> dict:
    """The result generate_audio() would give, built only from the narration
    audio already on disk: no TTS server is started and nothing is generated (a
    missing clip counts as silent). For the stand-alone overview / residential
    commands, which must still follow the narration (its length and cues)."""
    from services.tts.ttsengine import AudioProcessor

    config_path = Path(project_config_path)
    with open(config_path, "r", encoding="utf-8") as f:
        project_config = json.load(f)
    waypoints = project_config.get("waypoints", [])
    apply_cued_scripts(waypoints, config_path.parent)
    audio_dir = project_audio_dir(config_path.parent)
    processor = AudioProcessor(output_dir=audio_dir)

    data: Dict[str, Any] = {
        "audio_durations": [], "audio_pauses": [], "audio_paths": [], "subtitle_paths": [],
        "attraction_audio_paths": [], "attraction_audio_durations": [],
        "overview_audio_path": None, "overview_audio_duration": 0.0, "overview_cue_times": {},
    }

    def analyse(path: Path):
        return processor.analyze_pauses(str(path)) if output_is_valid(path) else None

    for idx, wp in enumerate(waypoints):
        label = wp.get("label", f"Waypoint {idx + 1}") if isinstance(wp, dict) else ""
        skip = not isinstance(wp, dict) or is_unvisited_stopby(wp)
        main_path = audio_dir / waypoint_audio_filename(idx, label)
        main = None if skip or not _resolve_narration_script(wp) else analyse(main_path)
        data["audio_durations"].append(main["duration_seconds"] if main else 0.0)
        data["audio_pauses"].append(main["pauses"] if main else [])
        data["audio_paths"].append(str(main_path) if main else None)
        data["subtitle_paths"].append(None)
        attraction_path = audio_dir / attraction_audio_filename(idx, label)
        attraction = None if skip or not _resolve_attraction_narration_script(wp) else analyse(attraction_path)
        data["attraction_audio_durations"].append(attraction["duration_seconds"] if attraction else 0.0)
        data["attraction_audio_paths"].append(str(attraction_path) if attraction else None)

    tagged = overview_tagged_script(project_config, config_path.parent)
    overview_path = audio_dir / "00_overview_narration.wav"
    overview = analyse(overview_path) if clean_text(tagged).strip() else None
    if overview:
        clean, cues = strip_cues(tagged)
        data["overview_audio_path"] = str(overview_path)
        data["overview_audio_duration"] = overview["duration_seconds"]
        data["overview_cue_times"] = (
            cue_times(cues, clean, overview["duration_seconds"], overview["pauses"]) if cues else {}
        )
    return data


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
    attraction_audio_paths = []
    attraction_audio_durations = []
    waypoints = []
    overview_audio_path = None
    overview_audio_duration = 0.0
    overview_cue_times: Dict[str, float] = {}

    try:
        config_path = Path(project_config_path)
        if not config_path.exists():
            logger.warning("Step 2: No project config found. Skipping TTS.")
            return {
                "audio_durations": [],
                "audio_pauses": [],
                "audio_paths": [],
                "subtitle_paths": [],
                "attraction_audio_paths": [],
                "attraction_audio_durations": [],
                "overview_audio_path": None,
                "overview_audio_duration": 0.0,
            }

        with open(config_path, "r", encoding="utf-8") as f:
            project_config = json.load(f)
            
        p_dict = project_config.get("settings", {}).get("pronunciation_dictionary", [])

        waypoints = project_config.get("waypoints", [])
        apply_cued_scripts(waypoints, config_path.parent)

        from services.tts.ttsengine import AudioProcessor, IrodoriTTSClient, tts_config_from_settings

        output_dir = Path(output_audio_dir) if output_audio_dir else project_audio_dir(config_path.parent)
        output_dir.mkdir(parents=True, exist_ok=True)
        client = IrodoriTTSClient(
            output_dir=output_dir,
            config=tts_config_from_settings(project_config.get("settings", {})),
        )
        processor = AudioProcessor(output_dir=output_dir)

        # [NOTE] [TTS] Awaits each waypoint in order inside this loop, so despite being async the TTS calls run fully sequentially, not concurrently.
        # Shared across the overview call AND both waypoint loops below
        # (arrival+attraction combined, then attraction-only) — restarting
        # only within one loop's own `idx % 4` used to reset the count back
        # to zero the moment the second loop started, so a project with
        # ~19-20 narrated waypoints ran roughly double the TTS calls
        # (combined-script pass + attraction-only pass) with real restarts
        # only happening in the first half, then went 15-20+ calls straight
        # through the second half with no restart at all -- long enough for
        # the TTS server to exhaust RAM/VRAM on a CPU run and hang/crash
        # partway through, instead of a clean per-waypoint failure.
        tts_call_count = 0

        async def _maybe_restart_tts_server():
            nonlocal tts_call_count
            tts_call_count += 1
            # Low RAM: restart the server right now instead of waiting for
            # the every-4-calls schedule below.
            if (tuning.free_ram_gb() or float("inf")) < tuning.MIN_FREE_RAM_GB:
                logger.info("Low RAM - restarting TTS server to clear it...")
                client.stop_server()
                await asyncio.sleep(2.0)
            if tts_call_count > 1 and (tts_call_count - 1) % 4 == 0:
                logger.info("Proactively restarting TTS server to clear RAM/VRAM...")
                client.stop_server()
                await asyncio.sleep(2.0)

        async def _generate_all_speech():
            nonlocal overview_audio_path, overview_audio_duration, overview_cue_times

            tracker.show("Generating overview narration audio")
            try:
                overview_clip = await generate_overview_audio(
                    project_config, client, processor, output_dir, force=force,
                    project_dir=config_path.parent,
                )
            except Exception as exc:
                logger.warning("Overview narration TTS failed (%s). Leaving overview clip silent.", exc)
                overview_clip = None
            if overview_clip:
                overview_audio_path = overview_clip["audio_path"]
                overview_audio_duration = overview_clip["duration_seconds"]
                overview_cue_times = overview_clip.get("cue_times") or {}

            for idx, wp in enumerate(waypoints):
                label = wp.get("label", f"Waypoint {idx + 1}") if isinstance(wp, dict) else f"Waypoint {idx + 1}"

                # Check upfront, before ever showing "Generating..." or
                # touching the TTS server — a waypoint with no narration
                # text has nothing to generate, so skip it outright instead
                # of attempting (and silently failing) the call.
                if not isinstance(wp, dict) or is_unvisited_stopby(wp) or not _resolve_narration_script(wp):
                    logger.info(
                        "Step 2: [%d] Skipping '%s' — %s.",
                        idx + 1, label,
                        "stop-by not connected to the route" if is_unvisited_stopby(wp)
                        else "no narration script configured",
                    )
                    if is_unvisited_stopby(wp):
                        tracker.note(f"Skipped TTS {idx + 1}/{len(waypoints)}: {label} (stop-by not connected to the route)")
                    audio_durations.append(0.0)
                    audio_pauses.append([])
                    audio_paths.append(None)
                    subtitle_paths.append(None)
                    continue

                # Proactively restart the TTS server every 4 calls (shared
                # counter with the attraction-only loop below and the
                # overview call above) to prevent RAM/VRAM exhaustion on
                # long CPU runs. It will auto-restart on the next call.
                await _maybe_restart_tts_server()

                tracker.show(f"Generating TTS {idx + 1}/{len(waypoints)}: {label}")
                
                try:
                    clip = await generate_waypoint_audio(
                        wp, idx, client, processor, output_dir, force=force, pronunciation_dict=p_dict
                    )
                except ValueError:
                    # Safety net for missing script
                    audio_durations.append(0.0)
                    audio_pauses.append([])
                    audio_paths.append(None)
                    subtitle_paths.append(None)
                    continue
                except Exception as exc:
                    logger.warning("TTS crashed for %s (%s). Restarting server and retrying once...", label, exc)
                    client.stop_server()
                    await asyncio.sleep(2.0)
                    try:
                        clip = await generate_waypoint_audio(
                            wp, idx, client, processor, output_dir, force=force
                        )
                    except Exception as retry_exc:
                        logger.error("TTS retry failed for %s (%s). Skipping audio.", label, retry_exc)
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

            # Second, independent pass: each waypoint's own ATTRACTION-only
            # narration (see _resolve_attraction_narration_script) — kept
            # as its own loop rather than interleaved with the combined-
            # script loop above, since it needs to run (and correctly
            # append None) regardless of whether that loop's `continue`
            # branches fired for this same waypoint.
            for idx, wp in enumerate(waypoints):
                if not isinstance(wp, dict) or is_unvisited_stopby(wp) or not _resolve_attraction_narration_script(wp):
                    attraction_audio_paths.append(None)
                    attraction_audio_durations.append(0.0)
                    continue

                await _maybe_restart_tts_server()

                label = wp.get("label", f"Waypoint {idx + 1}")
                tracker.show(f"Generating attraction TTS {idx + 1}/{len(waypoints)}: {label}")
                try:
                    clip = await generate_attraction_audio_for_waypoint(
                        wp, idx, client, processor, output_dir, force=force, pronunciation_dict=p_dict
                    )
                except Exception as exc:
                    logger.warning(
                        "Attraction narration TTS failed for '%s' (%s). Leaving that clip silent.",
                        label, exc,
                    )
                    clip = None

                if clip:
                    attraction_audio_paths.append(clip["audio_path"])
                    attraction_audio_durations.append(clip["duration_seconds"])
                else:
                    attraction_audio_paths.append(None)
                    attraction_audio_durations.append(0.0)

        # Execute the async function synchronously within the pipeline
        asyncio.run(_generate_all_speech())
        tracker.clear()

        logger.info("Step 2 complete: TTS audio successfully generated.")
        return {
            "audio_durations": audio_durations,
            "audio_pauses": audio_pauses,
            "audio_paths": audio_paths,
            "subtitle_paths": subtitle_paths,
            "attraction_audio_paths": attraction_audio_paths,
            "attraction_audio_durations": attraction_audio_durations,
            "overview_audio_path": overview_audio_path,
            "overview_audio_duration": overview_audio_duration,
            "overview_cue_times": overview_cue_times,
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
            "attraction_audio_paths": [],
            "attraction_audio_durations": [],
            "overview_audio_path": None,
            "overview_audio_duration": 0.0,
        }
    except Exception as e:
        # exc_info=True (not just "%s", e) because some exceptions on this
        # path (httpx.ConnectTimeout, bare RuntimeError()) stringify to ""
        # -- without the traceback those produce a log line reading "...
        # encountered an error: " with nothing after the colon, no way to
        # tell what actually happened.
        logger.error(
            "Step 2 failed: TTS Audio generation encountered an error: %s: %s",
            type(e).__name__, e, exc_info=True,
        )
        # [NOTE] [TTS] Pad out to one entry per waypoint (rather than discarding) so a mid-loop failure still returns whatever audio was already generated, index-aligned with waypoints.
        pad_count = max(0, len(waypoints) - len(audio_durations))
        audio_durations.extend([0.0] * pad_count)
        audio_pauses.extend([[]] * pad_count)
        audio_paths.extend([None] * pad_count)
        subtitle_paths.extend([None] * pad_count)
        attraction_pad_count = max(0, len(waypoints) - len(attraction_audio_paths))
        attraction_audio_paths.extend([None] * attraction_pad_count)
        attraction_audio_durations.extend([0.0] * attraction_pad_count)
        return {
            "audio_durations": audio_durations,
            "audio_pauses": audio_pauses,
            "audio_paths": audio_paths,
            "subtitle_paths": subtitle_paths,
            "attraction_audio_paths": attraction_audio_paths,
            "attraction_audio_durations": attraction_audio_durations,
            "overview_audio_path": overview_audio_path,
            "overview_audio_duration": overview_audio_duration,
            "overview_cue_times": overview_cue_times,
        }
