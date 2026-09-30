"""CLI commands that combine other steps: video concatenation, the
transition/storyboard renderer, and the "run every isolated stage" test_all."""

import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.logger.progress import tracker as _tracker
from services.vdoprocessing.videopipeline.helpers import (
    project_audio_dir,
    project_subtitle_dir,
    project_video_dir,
)
from services.vdoprocessing.videopipeline.timeline_step import _piece_target, _waypoint_ids
from .gps_commands import test_overview_video, test_residential_video
from .tts_commands import test_tts_all
from .attraction_commands import test_attraction_videos
from .subtitle_commands import test_subtitles

# A leg's continuation parts share its base name with a "_contN" suffix
# (route2vdo.py's own leg-splitting convention — see gps_commands.test_residential_video's
# multi-part video_paths). Grouping on this lets _order_like_timeline treat a
# split leg as the one leg it actually is, not several.
_CONT_SUFFIX_RE = re.compile(r"_cont\d+$")


def _order_like_timeline(
    project_dir: Path,
    overview_paths: List[str],
    attraction_results: List[Dict[str, Any]],
    residential_paths: List[str],
) -> List[str]:
    """Orders test_all's raw stage outputs to match the real pipeline's
    timeline.json convention (timeline_step.build_timeline's docstring):
    overview -> for each leg in travel order, that leg's DEPARTURE
    waypoint's own attraction video (if any) immediately followed by the
    leg itself -> the final waypoint's own attraction video (nothing
    plays it otherwise, since no leg departs from it).

    This is a video-only reordering (no audio/subtitle muxing — that's
    build_timeline's job for the real render_timeline path); it exists so
    test_all's dev-preview concat isn't grouped into a "sightseeing reel"
    block followed by a "travel reel" block, which doesn't reflect what
    the finished video actually looks like.
    """
    attraction_by_index = {
        item["index"]: item["video_path"]
        for item in attraction_results
        if not item.get("pending") and item.get("video_path")
    }

    # Group residential clips by leg (strip the "_contN" suffix), preserving
    # the renderer's own output order — it already renders leg 0, 1, 2...
    # in travel order, appending each leg's own continuation parts right
    # after its main part before moving to the next leg.
    leg_groups: List[List[str]] = []
    for path in residential_paths:
        base = _CONT_SUFFIX_RE.sub("", Path(path).stem)
        if leg_groups and _CONT_SUFFIX_RE.sub("", Path(leg_groups[-1][0]).stem) == base:
            leg_groups[-1].append(path)
        else:
            leg_groups.append([path])

    waypoint_ids = _waypoint_ids(str(project_dir))
    ordered = list(overview_paths)
    departure_index = 0  # the route always starts at waypoint 0
    for group in leg_groups:
        if departure_index in attraction_by_index:
            ordered.append(attraction_by_index[departure_index])
        ordered.extend(group)
        target = _piece_target(group[0], waypoint_ids)
        if target is not None:
            departure_index = target
    # The final waypoint's own attraction never gets picked up as a
    # "departure" above (no leg departs from the route's last stop).
    if departure_index in attraction_by_index:
        ordered.append(attraction_by_index[departure_index])

    return ordered


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
    # [NOTE] [Editor] Explicit clip_paths (from the CLI/frontend) take priority; with none given, fall back to every *.mp4 already in the output dir (including its route/attraction subfolders), alphabetically — relying on the "0N_..." filename prefixes each stage writes to land clips in pipeline order.
    inputs = [Path(path) for path in clip_paths] if clip_paths else sorted(
        path for path in output_dir.rglob("*.mp4") if path.name != output_path.name
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


def test_mux_audio(
    job_config_path: str,
    video_path: str,
    audio_path: str,
    output_video_dir: str = None,
    output_filename: Optional[str] = None,
) -> Dict[str, Any]:
    """Muxes an existing audio file onto an existing video file, standalone —
    the same VideoEditor.mux_audio_to_video the real pipeline calls
    internally (render_step.py for the overview, vdoexporter.py for the
    final timeline export), exposed on its own so a re-synthesized
    narration (or any other audio/video pair) can be checked against an
    already-rendered clip without re-running the whole render.

    No -shortest (see mux_audio_to_video's own note): the video keeps its
    full length regardless of the audio's — a narration shorter than the
    clip just leaves it silent after the voice ends, not cut short."""
    config_path = Path(job_config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"job_config.json not found: {config_path}")
    video_p = Path(video_path)
    audio_p = Path(audio_path)
    if not video_p.exists():
        raise FileNotFoundError(f"Video file not found: {video_p}")
    if not audio_p.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_p}")

    from services.config.job_config import JobConfigManager
    from services.vdoprocessing.vdoeditor import VideoEditor

    output_filename = output_filename or f"{video_p.stem}_muxed{video_p.suffix}"
    editor = VideoEditor(JobConfigManager(config_path))

    _tracker.show(f"Muxing {audio_p.name} onto {video_p.name}...")
    output_path = editor.mux_audio_to_video(str(video_p), str(audio_p), output_filename)
    _tracker.clear()

    # mux_audio_to_video always resolves under <project>/assets/video/
    # (VideoEditor._resolve_output_path) — move it if the caller asked for
    # somewhere else.
    if output_video_dir:
        target_dir = Path(output_video_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / Path(output_path).name
        if Path(output_path).resolve() != target_path.resolve():
            shutil.move(output_path, str(target_path))
            output_path = str(target_path)

    return {
        "success": True,
        "video_path": output_path,
        "source_video": str(video_p),
        "source_audio": str(audio_p),
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
    # Route (overview/residential) and attraction outputs get their own
    # subfolders under video_dir instead of sharing one flat folder — see
    # helpers.project_route_video_dir/project_attraction_video_dir.
    route_dir = video_dir / "route"
    attraction_dir = video_dir / "attraction"

    # [NOTE] [Core] Read use_3d_res up front so the total stage count for _tracker.stage(total=...) is known before the first stage starts.
    with config_path.open("r", encoding="utf-8") as config_file:
        use_3d_res = bool(
            json.load(config_file).get("settings", {}).get("use_3d_res", False)
        )
    total_stages = 8

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
    attraction_result = test_attraction_videos(str(config_path), str(attraction_dir), force=force)

    _tracker.stage("Generating subtitles")
    subtitle_result = test_subtitles(str(config_path), str(subtitle_dir), force=force)

    _tracker.stage("Rendering overview & residential video...")
    transition_result = test_transition_editor(str(config_path), str(route_dir), force=force)

    # [NOTE] [Animation] test_transition_editor always renders via
    # render_mode="overview" (see test_overview_video's docstring), which
    # now skips the residential sequence entirely regardless of 2D/3D —
    # so residential always needs this separate call, not just 3D. (This
    # used to be 3D-only, back when render_mode="overview" still bundled
    # both outputs together for 2D; that's no longer true.)
    _tracker.stage(f"Rendering residential video{' (3D)' if use_3d_res else ''}...")
    residential_result = test_residential_video(str(config_path), str(route_dir), force=force)

    _tracker.stage("Concatenating final video...")
    videos_to_concat = _order_like_timeline(
        project_dir,
        transition_result["video_paths"],
        attraction_result["results"],
        residential_result["video_paths"] if residential_result else [],
    )
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
