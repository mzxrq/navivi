"""
main.py
---------------------------------------------------------------------------
CLI entry point for the GPS-to-navigation-video pipeline.

Supports isolated tests for overview rendering, residential rendering, and
TTS narration generation and attraction video generation.
---------------------------------------------------------------------------
"""

import asyncio
import shutil
import sys
import json
import traceback
from pathlib import Path
from typing import Any, Dict, Optional


def _video_safe_label(label: Any, fallback: str) -> str:
    """Match the residential renderer's label sanitization for shared basenames."""
    safe_label = "".join(
        char for char in str(label) if char.isalnum() or char in (" ", "_", "-")
    ).strip().replace(" ", "_")
    return safe_label or fallback


def test_overview_video(job_config_path: str, output_video_dir: str = None) -> Dict[str, Any]:
    """Runs GPS parsing + route video rendering only, to sanity-check the
    overview map animation without paying for TTS/attraction/subtitle stages."""
    from services.vdoprocessing.videopipeline import process_gps, render_route_video

    config_path = Path(job_config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"job_config.json not found: {config_path}")

    output_video_dir = output_video_dir or str(config_path.parent / "video")

    cleaned_route = process_gps(str(config_path))

    video_paths = render_route_video(
        cleaned_route=cleaned_route,
        project_config_path=str(config_path),
        output_video_dir=output_video_dir,
    )

    return {
        "success": True,
        "video_paths": video_paths,
        "summary": cleaned_route.get("summary", {}),
    }


def test_residential_video(
    job_config_path: str,
    output_video_dir: str = None,
    fps: Optional[int] = None,
    speed_kmh: Optional[float] = None,
) -> Dict[str, Any]:
    """Runs the per-waypoint leg-by-leg render only, to sanity-check the
    residential animation without paying for the overview, TTS, or subtitle
    stages. Honors job_config.json's settings.use_3d_res (default False):
    2D (SpatialRenderer.render_waypoints, via the same render_route_video
    path test_overview_video uses) unless the project has explicitly opted
    into the 3D pydeck/Playwright renderer.
    """
    config_path = Path(job_config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"job_config.json not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as config_file:
        project_config = json.load(config_file)
    use_3d_res = bool(project_config.get("settings", {}).get("use_3d_res", False))

    output_video_dir = Path(output_video_dir or (config_path.parent / "video"))
    output_video_dir.mkdir(parents=True, exist_ok=True)

    if use_3d_res:
        output_video_path = str(output_video_dir / "02_residential_map.mp4")

        from services.vdoprocessing.pydeckrecorder import record_headless_video

        video_paths = record_headless_video(
            str(config_path),
            output_video_path,
            fps=fps,
            speed_kmh=speed_kmh,
        )
    else:
        from services.vdoprocessing.videopipeline import process_gps, render_route_video

        cleaned_route = process_gps(str(config_path))
        all_paths = render_route_video(
            cleaned_route=cleaned_route,
            project_config_path=str(config_path),
            output_video_dir=str(output_video_dir),
        )
        # render_route_video also produces "01_overview.mp4" — this entry
        # point is scoped to the residential/per-leg clips only, matching
        # what the 3D branch above returns.
        video_paths = [
            p for p in all_paths if Path(p).name != "01_overview.mp4"
        ]

    return {
        "success": bool(video_paths),
        "video_paths": video_paths,
    }


def _load_tts_waypoints(job_config_path: str) -> tuple[Path, list]:
    config_path = Path(job_config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"job_config.json not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as config_file:
        project_config = json.load(config_file)

    waypoints = project_config.get("waypoints", [])
    if not isinstance(waypoints, list):
        raise ValueError("job_config.json 'waypoints' must be a list")

    return config_path, waypoints


async def _generate_tts_clip(
    client: Any,
    processor: Any,
    waypoint: Dict[str, Any],
    waypoint_index: int,
) -> Dict[str, Any]:
    if not isinstance(waypoint, dict):
        raise ValueError(f"Waypoint {waypoint_index} must be an object")

    script = (
        waypoint.get("script")
        or waypoint.get("narration")
        or waypoint.get("voiceover")
    )
    if not isinstance(script, str) or not script.strip():
        raise ValueError(
            f"Waypoint {waypoint_index} has no script, narration, or voiceover text"
        )

    label = waypoint.get("label", f"Waypoint {waypoint_index + 1}")
    audio_filename = (
        f"02_waypoint_{waypoint_index + 1:02d}_"
        f"{_video_safe_label(label, f'leg{waypoint_index + 1}')}.wav"
    )
    audio_path = await client.generate_speech(
        script.strip(), output_filename=audio_filename
    )
    analysis = processor.analyze_pauses(audio_path)
    return {
        "index": waypoint_index,
        "label": label,
        "text": script.strip(),
        "audio_path": audio_path,
        "duration_seconds": analysis["duration_seconds"],
        "pauses": analysis["pauses"],
    }


def test_tts(
    job_config_path: str,
    output_audio_dir: str = None,
    waypoint_index: int = 0,
) -> Dict[str, Any]:
    """Generate and inspect TTS audio for one narrated waypoint."""
    config_path, waypoints = _load_tts_waypoints(job_config_path)
    if waypoint_index < 0 or waypoint_index >= len(waypoints):
        raise IndexError(
            f"waypoint_index must be between 0 and {len(waypoints) - 1}, "
            f"got {waypoint_index}"
        )

    output_dir = Path(output_audio_dir or (config_path.parent / "audio"))
    output_dir.mkdir(parents=True, exist_ok=True)

    from services.tts.ttsengine import AudioProcessor, IrodoriTTSClient

    client = IrodoriTTSClient(output_dir=output_dir)
    processor = AudioProcessor(output_dir=output_dir)

    async def generate_speech() -> str:
        return await _generate_tts_clip(
            client, processor, waypoints[waypoint_index], waypoint_index
        )

    clip = asyncio.run(generate_speech())
    return {
        "success": True,
        "audio_dir": str(output_dir),
        "clip": clip,
    }


def test_tts_all(
    job_config_path: str,
    output_audio_dir: str = None,
) -> Dict[str, Any]:
    """Generate and inspect TTS audio for every narrated waypoint."""
    config_path, waypoints = _load_tts_waypoints(job_config_path)
    output_dir = Path(output_audio_dir or (config_path.parent / "audio"))
    output_dir.mkdir(parents=True, exist_ok=True)

    from services.tts.ttsengine import AudioProcessor, IrodoriTTSClient

    client = IrodoriTTSClient(output_dir=output_dir)
    processor = AudioProcessor(output_dir=output_dir)

    async def generate_all() -> list:
        return [
            await _generate_tts_clip(client, processor, waypoint, index)
            for index, waypoint in enumerate(waypoints)
        ]

    clips = asyncio.run(generate_all())
    return {
        "success": True,
        "audio_dir": str(output_dir),
        "clips": clips,
    }


def _attraction_prompt(waypoint: Dict[str, Any]) -> list:
    camera_pans = waypoint.get("camera_pans", [])
    if isinstance(camera_pans, list) and camera_pans:
        return camera_pans
    return [waypoint.get("label", "Beautiful Japanese scenery, high quality")]


def _attraction_audio_path(
    config_path: Path, waypoint_index: int, label: Any
) -> Optional[str]:
    audio_path = (
        config_path.parent
        / "audio"
        / (
            f"02_waypoint_{waypoint_index + 1:02d}_"
            f"{_video_safe_label(label, f'leg{waypoint_index + 1}')}.wav"
        )
    )
    return str(audio_path) if audio_path.exists() else None


def test_attraction_video(
    job_config_path: str,
    output_video_dir: str = None,
    waypoint_index: int = 0,
) -> Dict[str, Any]:
    """Generate one attraction video from one waypoint's popup image."""
    config_path, waypoints = _load_tts_waypoints(job_config_path)
    if waypoint_index < 0 or waypoint_index >= len(waypoints):
        raise IndexError(
            f"waypoint_index must be between 0 and {len(waypoints) - 1}, "
            f"got {waypoint_index}"
        )

    waypoint = waypoints[waypoint_index]
    if not isinstance(waypoint, dict):
        raise ValueError(f"Waypoint {waypoint_index} must be an object")
    if not waypoint.get("popup_image"):
        raise ValueError(f"Waypoint {waypoint_index} has no popup_image")

    from services.config.job_config import JobConfigManager
    from services.vdoprocessing.img2vdo import AttractionVideoGenerator
    from services.tts.ttsengine import AudioProcessor

    output_dir = Path(output_video_dir or (config_path.parent / "video"))
    output_dir.mkdir(parents=True, exist_ok=True)
    label = waypoint.get("label", f"Waypoint {waypoint_index + 1}")
    audio_path = _attraction_audio_path(config_path, waypoint_index, label)
    audio_duration = (
        AudioProcessor().analyze_pauses(audio_path)["duration_seconds"]
        if audio_path
        else 0.0
    )
    generator = AttractionVideoGenerator(JobConfigManager(config_path))
    generator.output_dir = output_dir
    output_filename = (
        f"04_attraction_{waypoint_index:02d}_"
        f"{_video_safe_label(label, f'waypoint_{waypoint_index}')}.mp4"
    )
    result_path = generator.process_attraction_video(
        popup_image_entry=waypoint["popup_image"],
        prompt_text=_attraction_prompt(waypoint),
        target_audio_duration=audio_duration,
        audio_path=audio_path,
        output_filename=output_filename,
    )
    if not result_path:
        raise RuntimeError(f"Attraction video generation failed for waypoint {waypoint_index}")
    return {"success": True, "video_path": result_path, "audio_path": audio_path}


def test_attraction_videos(
    job_config_path: str,
    output_video_dir: str = None,
) -> Dict[str, Any]:
    """Generate attraction videos for every waypoint with a popup image."""
    config_path, waypoints = _load_tts_waypoints(job_config_path)
    results = []
    for index, waypoint in enumerate(waypoints):
        if not isinstance(waypoint, dict) or not waypoint.get("popup_image"):
            continue
        result = test_attraction_video(
            str(config_path), output_video_dir, waypoint_index=index
        )
        results.append({"index": index, **result})
    return {"success": True, "video_paths": [item["video_path"] for item in results], "results": results}


def _subtitle_audio_path(config_path: Path, waypoint_index: int, label: Any) -> Path:
    return (
        config_path.parent
        / "audio"
        / (
            f"02_waypoint_{waypoint_index + 1:02d}_"
            f"{_video_safe_label(label, f'leg{waypoint_index + 1}')}.wav"
        )
    )


def _build_subtitle(
    config_path: Path,
    waypoint: Dict[str, Any],
    waypoint_index: int,
    output_subtitle_dir: Path,
) -> Dict[str, Any]:
    if not isinstance(waypoint, dict):
        raise ValueError(f"Waypoint {waypoint_index} must be an object")

    script = (
        waypoint.get("script")
        or waypoint.get("narration")
        or waypoint.get("voiceover")
    )
    if not isinstance(script, str) or not script.strip():
        raise ValueError(
            f"Waypoint {waypoint_index} has no script, narration, or voiceover text"
        )

    label = waypoint.get("label", f"Waypoint {waypoint_index + 1}")
    audio_path = _subtitle_audio_path(config_path, waypoint_index, label)
    if not audio_path.exists():
        raise FileNotFoundError(
            f"TTS audio not found for waypoint {waypoint_index}: {audio_path}"
        )

    from services.localization.subtitle import SRTDocument, SubtitleBuilder
    from services.tts.ttsengine import AudioProcessor

    analysis = AudioProcessor().analyze_pauses(str(audio_path))
    cues = SubtitleBuilder.build(
        text=script.strip(),
        duration_seconds=analysis["duration_seconds"],
        pauses=analysis["pauses"],
    )
    output_subtitle_dir.mkdir(parents=True, exist_ok=True)
    subtitle_path = output_subtitle_dir / f"{audio_path.stem}.srt"
    SRTDocument.write(cues, str(subtitle_path))
    return {
        "index": waypoint_index,
        "label": label,
        "audio_path": str(audio_path),
        "subtitle_path": str(subtitle_path),
        "cue_count": len(cues),
    }


def test_subtitle(
    job_config_path: str,
    output_subtitle_dir: str = None,
    waypoint_index: int = 0,
) -> Dict[str, Any]:
    """Generate subtitles for one waypoint from its matching TTS audio."""
    config_path, waypoints = _load_tts_waypoints(job_config_path)
    if waypoint_index < 0 or waypoint_index >= len(waypoints):
        raise IndexError(
            f"waypoint_index must be between 0 and {len(waypoints) - 1}, "
            f"got {waypoint_index}"
        )
    output_dir = Path(output_subtitle_dir or (config_path.parent / "subtitles"))
    result = _build_subtitle(
        config_path, waypoints[waypoint_index], waypoint_index, output_dir
    )
    return {"success": True, **result}


def test_subtitles(
    job_config_path: str,
    output_subtitle_dir: str = None,
) -> Dict[str, Any]:
    """Generate subtitles for every waypoint from matching TTS audio."""
    config_path, waypoints = _load_tts_waypoints(job_config_path)
    output_dir = Path(output_subtitle_dir or (config_path.parent / "subtitles"))
    results = [
        _build_subtitle(config_path, waypoint, index, output_dir)
        for index, waypoint in enumerate(waypoints)
    ]
    return {
        "success": True,
        "subtitle_dir": str(output_dir),
        "subtitle_paths": [result["subtitle_path"] for result in results],
        "results": results,
    }


def test_video_concat(
    job_config_path: str,
    output_video_dir: str = None,
    clip_paths: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """Concatenate selected project videos, allowing a single clip as a no-op copy."""
    config_path = Path(job_config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"job_config.json not found: {config_path}")

    output_dir = Path(output_video_dir or (config_path.parent / "video"))
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "03_concat.mp4"
    inputs = [Path(path) for path in clip_paths] if clip_paths else sorted(
        path for path in output_dir.glob("*.mp4") if path.name != output_path.name
    )
    if not inputs:
        raise ValueError(f"No video clips found in {output_dir}")
    missing = [str(path) for path in inputs if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Video clip(s) not found: {', '.join(missing)}")

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

    return {
        "success": True,
        "video_path": str(output_path),
        "input_paths": [str(path) for path in inputs],
    }


def test_transition_editor(
    job_config_path: str,
    output_video_dir: str = None,
) -> Dict[str, Any]:
    """Run the overview/storyboard renderer, including configured transitions."""
    result = test_overview_video(job_config_path, output_video_dir)
    return {
        "success": result["success"],
        "video_paths": result["video_paths"],
        "summary": result.get("summary", {}),
    }


def test_all(
    job_config_path: str,
    output_dir: str = None,
) -> Dict[str, Any]:
    """Run all isolated media stages as one project test."""
    config_path = Path(job_config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"job_config.json not found: {config_path}")

    project_dir = config_path.parent
    audio_dir = project_dir / "audio"
    video_dir = Path(output_dir or (project_dir / "video"))
    subtitle_dir = project_dir / "subtitles"

    tts_result = test_tts_all(str(config_path), str(audio_dir))
    attraction_result = test_attraction_videos(str(config_path), str(video_dir))
    subtitle_result = test_subtitles(str(config_path), str(subtitle_dir))
    transition_result = test_transition_editor(str(config_path), str(video_dir))

    videos_to_concat = [
        *attraction_result["video_paths"],
        *transition_result["video_paths"],
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
        "concat": concat_result,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "Usage: python main.py <path/to/job_config.json> [output_dir] "
            "[overview|residential|tts|tts-all|attraction|attraction-all|"
            "subtitle|subtitle-all|concat|transition|all] [waypoint_index]\n"
            "       python main.py full_pipeline <source_path> [output_dir]\n"
            "       python main.py render_timeline <timeline.json> [output_video]",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        command_arg = sys.argv[1]
        if command_arg == "full_pipeline":
            if len(sys.argv) < 3:
                raise ValueError("full_pipeline requires a source path")
            from services.vdoprocessing.videopipeline import run_full_pipeline

            result = run_full_pipeline(
                sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None
            )
        elif command_arg == "render_timeline":
            if len(sys.argv) < 3:
                raise ValueError("render_timeline requires a timeline path")
            from services.vdoprocessing.videopipeline import render_from_timeline

            result = render_from_timeline(
                sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None
            )
        else:
            job_config_arg = command_arg
            output_dir_arg = sys.argv[2] if len(sys.argv) > 2 else None
            mode_arg = sys.argv[3] if len(sys.argv) > 3 else "overview"

            if mode_arg == "residential":
                result = test_residential_video(job_config_arg, output_dir_arg)
            elif mode_arg == "tts":
                waypoint_index_arg = int(sys.argv[4]) if len(sys.argv) > 4 else 0
                result = test_tts(job_config_arg, output_dir_arg, waypoint_index_arg)
            elif mode_arg == "tts-all":
                result = test_tts_all(job_config_arg, output_dir_arg)
            elif mode_arg == "attraction":
                waypoint_index_arg = int(sys.argv[4]) if len(sys.argv) > 4 else 0
                result = test_attraction_video(
                    job_config_arg, output_dir_arg, waypoint_index_arg
                )
            elif mode_arg == "attraction-all":
                result = test_attraction_videos(job_config_arg, output_dir_arg)
            elif mode_arg == "subtitle":
                waypoint_index_arg = int(sys.argv[4]) if len(sys.argv) > 4 else 0
                result = test_subtitle(
                    job_config_arg, output_dir_arg, waypoint_index_arg
                )
            elif mode_arg == "subtitle-all":
                result = test_subtitles(job_config_arg, output_dir_arg)
            elif mode_arg == "concat":
                clip_paths_arg = sys.argv[4:] if len(sys.argv) > 4 else None
                result = test_video_concat(
                    job_config_arg, output_dir_arg, clip_paths_arg
                )
            elif mode_arg == "transition":
                result = test_transition_editor(job_config_arg, output_dir_arg)
            elif mode_arg == "all":
                result = test_all(job_config_arg, output_dir_arg)
            else:
                result = test_overview_video(job_config_arg, output_dir_arg)

        print(json.dumps(result, ensure_ascii=False, indent=2))
        
    except Exception as e:
        error_result = {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc(),
        }
        
        # Printing the error as JSON to stdout allows parent processes to parse it easily
        print(json.dumps(error_result, ensure_ascii=False, indent=2))
        
        # Exit with a non-zero status code to indicate failure to the OS
        sys.exit(1)
        