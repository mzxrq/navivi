"""Isolated CLI commands for the intro/outro clip steps — on-demand test
hooks mirroring the pipeline's own render_intro_clip/render_outro_clip
(see services/vdoprocessing/videopipeline/intro_step.py and outro_step.py),
so either clip can be sanity-checked without running the whole pipeline."""

from pathlib import Path
from typing import Any, Dict, Optional

from services.logger.progress import tracker as _tracker


def test_intro_video(job_config_path: str, output_video_dir: Optional[str] = None) -> Dict[str, Any]:
    """Builds only the intro clip (random waypoint popup image, Ken Burns
    zoom-in, project name burned in) — no GPS/TTS/attraction/subtitle
    stages. output_video_dir is accepted for signature parity with the
    other test_* commands, but render_intro_clip derives its own video_dir
    from job_config's directory_path, so it's otherwise unused here."""
    from services.vdoprocessing.videopipeline import render_intro_clip

    config_path = Path(job_config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"job_config.json not found: {config_path}")

    _tracker.show("Rendering intro clip...")
    intro_path = render_intro_clip(str(config_path))
    _tracker.clear()

    return {
        "success": bool(intro_path),
        "video_path": intro_path,
    }


def test_outro_video(job_config_path: str, output_video_dir: Optional[str] = None) -> Dict[str, Any]:
    """Builds only the outro clip (project name + numbered thumbnail grid
    of every waypoint with a popup image) — no GPS/TTS/attraction/subtitle
    stages. output_video_dir is accepted for signature parity with the
    other test_* commands, but render_outro_clip derives its own video_dir
    from job_config's directory_path, so it's otherwise unused here."""
    from services.vdoprocessing.videopipeline import render_outro_clip

    config_path = Path(job_config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"job_config.json not found: {config_path}")

    _tracker.show("Rendering outro clip...")
    outro_path = render_outro_clip(str(config_path))
    _tracker.clear()

    return {
        "success": bool(outro_path),
        "video_path": outro_path,
    }
