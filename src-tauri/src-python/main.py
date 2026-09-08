"""
main.py
---------------------------------------------------------------------------
CLI entry point for the GPS-to-navigation-video pipeline.

Every isolated pipeline command (GPS parsing, TTS, attraction videos,
subtitles, video rendering/concat, and test_all) lives in services/cli/ —
this file is just the argv dispatch on top of them, plus the two
whole-pipeline commands (full_pipeline, render_timeline) that live in
services/vdoprocessing/videopipeline/.
---------------------------------------------------------------------------
"""

import sys
import json
import traceback

from services.logger.progress import tracker as _tracker
from services.cli import (
    _output_dir_from_config,
    test_gps,
    test_residential_video,
    test_tts,
    test_tts_all,
    test_attraction_video,
    test_attraction_videos,
    test_attraction_finalize,
    test_subtitle,
    test_subtitles,
    test_video_concat,
    test_transition_editor,
    test_all,
    test_overview_video,
)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "Usage: python main.py <path/to/job_config.json> "
            "[gps|overview|residential|tts|tts-all|attraction|attraction-all|"
            "attraction-finalize|subtitle|subtitle-all|concat|transition|all] "
            "[waypoint_index]\n"
            "       (output dir is always <job_config's directory_path>/video)\n"
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
            # [NOTE] [Core] output_dir_arg is always derived from job_config.json's directory_path here — every mode below shares the same "<project>/video" output dir, none of them take it as a separate CLI argument.
            job_config_arg = command_arg
            output_dir_arg = _output_dir_from_config(job_config_arg)
            mode_arg = sys.argv[2] if len(sys.argv) > 2 else "overview"

            # [NOTE] [Core] Each branch below is one isolated pipeline step
            # (see services/cli/'s own module docstrings / test_*
            # docstrings) — run individually so a change scoped to one
            # stage doesn't require re-running the whole pipeline just to
            # check it.
            if mode_arg == "gps":
                # [NOTE] [GPS] Step 1 only: parses raw_track.gpx into a cleaned route + summary, no media generated.
                result = test_gps(job_config_arg)
            elif mode_arg == "residential":
                # [NOTE] [Animation] Renders only the per-waypoint leg-by-leg clips (2D or 3D per settings.use_3d_res) — no overview map.
                result = test_residential_video(job_config_arg, output_dir_arg)
            elif mode_arg == "tts":
                # [NOTE] [TTS] Generates narration audio for ONE waypoint (index from argv[3], default 0).
                waypoint_index_arg = int(sys.argv[3]) if len(sys.argv) > 3 else 0
                result = test_tts(job_config_arg, output_dir_arg, waypoint_index_arg)
            elif mode_arg == "tts-all":
                # [NOTE] [TTS] Generates narration audio for every narrated waypoint.
                result = test_tts_all(job_config_arg, output_dir_arg)
            elif mode_arg == "attraction":
                # [NOTE] [Animation] Generates ONE waypoint's attraction (pan/outpaint) video from its popup image (index from argv[3], default 0).
                waypoint_index_arg = int(sys.argv[3]) if len(sys.argv) > 3 else 0
                result = test_attraction_video(
                    job_config_arg, output_dir_arg, waypoint_index_arg
                )
            elif mode_arg == "attraction-all":
                # [NOTE] [Animation] Generates attraction videos for every waypoint that has a popup image.
                result = test_attraction_videos(job_config_arg, output_dir_arg)
            elif mode_arg == "attraction-finalize":
                # [NOTE] [Editor] Combines a multi-image waypoint's already-generated pending clips into the final deliverable (index from argv[3], default 0) — see test_attraction_finalize's docstring.
                waypoint_index_arg = int(sys.argv[3]) if len(sys.argv) > 3 else 0
                result = test_attraction_finalize(
                    job_config_arg, output_dir_arg, waypoint_index_arg
                )
            elif mode_arg == "subtitle":
                # [NOTE] [Subtitle] Generates the .srt for ONE waypoint from its matching TTS audio (index from argv[3], default 0).
                waypoint_index_arg = int(sys.argv[3]) if len(sys.argv) > 3 else 0
                result = test_subtitle(
                    job_config_arg, output_dir_arg, waypoint_index_arg
                )
            elif mode_arg == "subtitle-all":
                # [NOTE] [Subtitle] Generates .srt files for every waypoint from matching TTS audio.
                result = test_subtitles(job_config_arg, output_dir_arg)
            elif mode_arg == "concat":
                # [NOTE] [Editor] Joins explicit clip paths (argv[3:]) — or, with none given, every *.mp4 already in the output dir in filename order — into 03_concat.mp4.
                clip_paths_arg = sys.argv[3:] if len(sys.argv) > 3 else None
                result = test_video_concat(
                    job_config_arg, output_dir_arg, clip_paths_arg
                )
            elif mode_arg == "transition":
                # [NOTE] [Transition] Renders the overview/storyboard map animation, including configured popup transitions — thin wrapper over test_overview_video.
                result = test_transition_editor(job_config_arg, output_dir_arg)
            elif mode_arg == "all":
                # [NOTE] [Core] Runs every isolated stage above (TTS, attractions, subtitles, overview+residential, concat) as one combined project test — NOT the same as full_pipeline (no subtitle burn-in / timeline.json, see above).
                result = test_all(job_config_arg, output_dir_arg)
            else:
                # [NOTE] [Core] Default when no mode (or an unrecognized one) is given — just the overview map animation.
                result = test_overview_video(job_config_arg, output_dir_arg)

        _tracker.clear()
        if sys.stderr.isatty():
            sys.stderr.write(f"Done in {_tracker.elapsed()}\n")
            sys.stderr.flush()
        print(json.dumps(result, ensure_ascii=False, indent=2))

    except Exception as e:
        error_result = {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc(),
        }

        _tracker.clear()
        if sys.stderr.isatty():
            sys.stderr.write(f"Failed after {_tracker.elapsed()}: {e}\n")
            sys.stderr.flush()

        # [NOTE] [Core] Errors are printed as JSON to stdout (not just stderr) so the Tauri sidecar's parent process can parse the failure the same way it parses a successful result.
        print(json.dumps(error_result, ensure_ascii=False, indent=2))

        # [NOTE] [Core] Non-zero exit code signals failure to the OS/caller independent of the JSON payload above.
        sys.exit(1)
