"""
main.py
---------------------------------------------------------------------------
CLI entry point for the GPS-to-navigation-video pipeline.

Currently wired for one purpose: testing the overview route video render
(Step 1 GPS parse -> Step 3 render_route_video) in isolation, without
running TTS/attraction/subtitle stages.

NOTE: services/config/job_config.py (JobConfigManager) does not exist yet
in this branch -- every service module here imports it. This file will
raise ImportError until that module is added.
---------------------------------------------------------------------------
"""

import sys
import json
import traceback
from pathlib import Path
from typing import Any, Dict

from services.vdoprocessing.videopipeline import process_gps, render_route_video


def test_overview_video(job_config_path: str, output_video_dir: str = None) -> Dict[str, Any]:
    """Runs GPS parsing + route video rendering only, to sanity-check the
    overview map animation without paying for TTS/attraction/subtitle stages."""
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


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "Usage: python main.py <path/to/job_config.json> [output_video_dir]",
            file=sys.stderr,
        )
        sys.exit(1)

    job_config_arg = sys.argv[1]
    output_dir_arg = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        result = test_overview_video(job_config_arg, output_dir_arg)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        error_result = {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc(),
        }
        print(json.dumps(error_result, ensure_ascii=False, indent=2))
        sys.exit(1)
