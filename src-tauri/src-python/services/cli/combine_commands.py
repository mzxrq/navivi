"""CLI commands that combine other steps: video concatenation, the
transition/storyboard renderer, and the "run every isolated stage" test_all."""

import json
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from services.logger.progress import tracker as _tracker
from services.vdoprocessing.videopipeline.helpers import (
    project_audio_dir,
    project_subtitle_dir,
    project_video_dir,
)
from .gps_commands import test_overview_video, test_residential_video
from .tts_commands import test_tts_all
from .attraction_commands import test_attraction_videos
from .subtitle_commands import test_subtitles


def test_video_concat(
    job_config_path: str,
    output_video_dir: str = None,
    clip_paths: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """Concatenate selected project videos, allowing a single clip as a no-op copy."""
    config_path = Path(job_config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"job_config.json not found: {config_path}")

    output_dir = Path(output_video_dir) if output_video_dir else project_video_dir(config_path.parent)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "03_concat.mp4"
    # [NOTE] [Editor] Explicit clip_paths (from the CLI/frontend) take priority; with none given, fall back to every *.mp4 already in the output dir, alphabetically — relying on the "0N_..." filename prefixes each stage writes to land clips in pipeline order.
    inputs = [Path(path) for path in clip_paths] if clip_paths else sorted(
        path for path in output_dir.glob("*.mp4") if path.name != output_path.name
    )
    if not inputs:
        raise ValueError(f"No video clips found in {output_dir}")
    missing = [str(path) for path in inputs if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Video clip(s) not found: {', '.join(missing)}")

    _tracker.show("Concatenating final video...")
    # [NOTE] [Editor] A single clip is just copied to the expected output filename — ffmpeg's concat demuxer is skipped since there's nothing to actually join.
    if len(inputs) == 1:
        shutil.copyfile(inputs[0], output_path)
    else:
        from services.config.job_config import JobConfigManager
        from services.vdoprocessing.vdoeditor import VideoEditor

        generated_path = Path(
            VideoEditor(JobConfigManager(config_path)).concatenate_videos(
            [str(path) for path in inputs], output_path.name
        )
        )
        if generated_path.resolve() != output_path.resolve():
            shutil.copyfile(generated_path, output_path)
    _tracker.clear()

    return {
        "success": True,
        "video_path": str(output_path),
        "input_paths": [str(path) for path in inputs],
    }


def test_transition_editor(
    job_config_path: str,
    output_video_dir: str = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Run the overview/storyboard renderer, including configured transitions."""
    result = test_overview_video(job_config_path, output_video_dir, force=force)
    return {
        "success": result["success"],
        "video_paths": result["video_paths"],
        "summary": result.get("summary", {}),
    }


def test_all(
    job_config_path: str,
    output_dir: str = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Run all isolated media stages as one project test.

    Checkpointing: by default (`force=False`) nothing is wiped up front —
    each stage below skips any of its own outputs that already exist on
    disk. Pass `force=True` to reproduce the old behavior of wiping
    audio/video/subtitles and regenerating everything from scratch.
    """
    config_path = Path(job_config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"job_config.json not found: {config_path}")

    project_dir = config_path.parent
    audio_dir = project_audio_dir(project_dir)
    video_dir = Path(output_dir) if output_dir else project_video_dir(project_dir)
    subtitle_dir = project_subtitle_dir(project_dir)

    # [NOTE] [Core] Read use_3d_res up front so the total stage count for _tracker.stage(total=...) is known before the first stage starts.
    with config_path.open("r", encoding="utf-8") as config_file:
        use_3d_res = bool(
            json.load(config_file).get("settings", {}).get("use_3d_res", False)
        )
    total_stages = 7 + (1 if use_3d_res else 0)

    if force:
        # [HACK] [IO] Per-waypoint cleanup only deletes files matching current labels/order, so a renamed or removed waypoint would leave stale files behind — brute-force wipe the whole dir instead.
        _tracker.stage("Clearing stale outputs...", total=total_stages)
        for stale_dir in (audio_dir, video_dir, subtitle_dir):
            if stale_dir.exists():
                shutil.rmtree(stale_dir)
            stale_dir.mkdir(parents=True, exist_ok=True)
        _tracker.clear()
    else:
        _tracker.stage("Checking existing outputs...", total=total_stages)
        for stale_dir in (audio_dir, video_dir, subtitle_dir):
            stale_dir.mkdir(parents=True, exist_ok=True)
        _tracker.clear()

    _tracker.stage("Generating TTS narration")
    tts_result = test_tts_all(str(config_path), str(audio_dir), force=force)

    # [NOTE] [TTS] Force-stop the TTS server now — its idle timeout would otherwise keep it loaded and contending with the attraction step's SDXL pipeline for VRAM (~20s -> ~8min observed).
    _tracker.stage("Stopping TTS server...")
    from services.tts.ttsengine import IrodoriTTSClient
    IrodoriTTSClient.stop_server()
    _tracker.clear()

    _tracker.stage("Generating attraction videos")
    attraction_result = test_attraction_videos(str(config_path), str(video_dir), force=force)

    _tracker.stage("Generating subtitles")
    subtitle_result = test_subtitles(str(config_path), str(subtitle_dir), force=force)

    _tracker.stage("Rendering overview & residential video...")
    transition_result = test_transition_editor(str(config_path), str(video_dir), force=force)

    # [NOTE] [Animation] 2D mode already renders residential clips inside render_route_video; only 3D mode needs this separate pydeck/Playwright call, to avoid rendering residential twice.
    if use_3d_res:
        _tracker.stage("Rendering residential video (3D)...")
    residential_result = (
        test_residential_video(str(config_path), str(video_dir), force=force)
        if use_3d_res
        else None
    )

    _tracker.stage("Concatenating final video...")
    videos_to_concat = [
        *attraction_result["video_paths"],
        *transition_result["video_paths"],
        *(residential_result["video_paths"] if residential_result else []),
    ]
    concat_result = test_video_concat(
        str(config_path), str(video_dir), videos_to_concat
    )

    return {
        "success": True,
        "tts": tts_result,
        "attractions": attraction_result,
        "subtitles": subtitle_result,
        "transition": transition_result,
        "residential": residential_result,
        "concat": concat_result,
    }
