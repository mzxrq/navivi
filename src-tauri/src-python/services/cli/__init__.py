"""Isolated CLI commands for the GPS-to-navigation-video pipeline — split
out of main.py (which stays a thin argv-dispatch wrapper around these) so
each pipeline step's test_* command lives next to its own concerns:

- helpers: output-dir resolution, filename sanitization, waypoint loading
- gps_commands: GPS parsing, overview video, residential video
- tts_commands: TTS narration generation
- attraction_commands: attraction/pan-zoom video generation
- subtitle_commands: subtitle generation from TTS audio
- combine_commands: video concat, the transition editor, and test_all
  (which runs every isolated stage above as one combined project test)
"""

from .helpers import _output_dir_from_config, _video_safe_label, _load_tts_waypoints
from .gps_commands import test_gps, test_overview_video, test_residential_video
from .tts_commands import test_tts, test_tts_all
from .attraction_commands import (
    test_attraction_video,
    test_attraction_videos,
    test_attraction_finalize,
)
from .subtitle_commands import test_subtitle, test_subtitles
from .combine_commands import test_video_concat, test_transition_editor, test_all

__all__ = [
    "_output_dir_from_config",
    "_video_safe_label",
    "_load_tts_waypoints",
    "test_gps",
    "test_overview_video",
    "test_residential_video",
    "test_tts",
    "test_tts_all",
    "test_attraction_video",
    "test_attraction_videos",
    "test_attraction_finalize",
    "test_subtitle",
    "test_subtitles",
    "test_video_concat",
    "test_transition_editor",
    "test_all",
]
