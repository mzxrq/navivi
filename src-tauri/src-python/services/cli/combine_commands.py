"""CLI commands that combine other steps' outputs: video concatenation and audio muxing."""

import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from services.logger.progress import tracker as _tracker
from services.vdoprocessing.videopipeline.helpers import project_video_dir


def test_video_concat(
    job_config_path: str,
    output_video_dir: str | None = None,
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
        path for path in output_dir.rglob("*.mp4")
        if path.name != output_path.name and not any(p.startswith(".") for p in path.relative_to(output_dir).parts)
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


def _move_into_dir(output_path: str, output_video_dir: str) -> str:
    """Moves `output_path` into `output_video_dir` (created if needed); returns its new path.

    mux_audio_to_video always resolves under <project>/assets/video/
    (VideoEditor._resolve_output_path) — move it if the caller asked for
    somewhere else.
    """
    target_dir = Path(output_video_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / Path(output_path).name
    if Path(output_path).resolve() != target_path.resolve():
        shutil.move(output_path, str(target_path))
        return str(target_path)
    return output_path


def test_mux_audio(
    job_config_path: str,
    video_path: str,
    audio_path: str,
    output_video_dir: str | None = None,
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

    if output_video_dir:
        output_path = _move_into_dir(output_path, output_video_dir)

    return {
        "success": True,
        "video_path": output_path,
        "source_video": str(video_p),
        "source_audio": str(audio_p),
    }
