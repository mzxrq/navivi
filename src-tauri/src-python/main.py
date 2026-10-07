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
from pathlib import Path

from services.logger.progress import tracker as _tracker
from services.cli import (
    _output_dir_from_config,
    test_gps,
    test_residential_video,
    test_tts,
    test_tts_all,
    test_overview_tts,
    test_attraction_tts,
    test_attraction_tts_all,
    test_attraction_video,
    test_attraction_videos,
    test_attraction_finalize,
    test_subtitle,
    test_subtitles,
    test_intro_video,
    test_outro_video,
    test_video_concat,
    test_mux_audio,
    test_transition_editor,
    test_all,
    test_overview_map,
    test_overview_video,
    test_overview_script,
)


def split_mode_payload(argv: list) -> list:
    """run_python_blueprint hands over ONE payload argument, so the app sends "tts 3 --force" as a single
    string: split it back into arguments. Only a stage call (argv[1] is a job_config.json path) is split;
    every named command (get_furigana, import_gps_track, install_google_font, the voice and image actions,
    full_pipeline, ...) keeps its payload whole, so a new command needs no entry here. A JSON payload is
    never split either."""
    if (
        len(argv) == 3
        and argv[1].lower().endswith(".json")
        and " " in argv[2].strip()
        and not argv[2].lstrip().startswith(("{", "["))
    ):
        return argv[:2] + argv[2].split()
    return argv


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "Usage: python main.py <path/to/job_config.json> "
            "[gps|map|overview|residential|tts|tts-all|overview-tts|attraction-tts|attraction-tts-all|"
            "attraction|attraction-all|attraction-finalize|intro|outro|subtitle|subtitle-all|concat|mux|"
            "transition|all|overview-script|upscale-images] [index] [--force] [--no-llm]\n"
            "       (output dir is always <job_config's directory_path>/video; no mode = the overview map video)\n"
            "       (--force bypasses checkpointing and regenerates everything)\n"
            "       python main.py full_pipeline <path/to/job_config.json> [output_dir] [--force]\n"
            "       python main.py render_timeline <timeline.json> [output_video]\n"
            "       python main.py estimate <path/to/job_config.json>\n"
            "       python main.py <command> <payload>, one of: get_furigana, extract_words, read_document,\n"
            "           import_gps_track (JSON), list_fonts, google_fonts_catalog, install_google_font, system_info,\n"
            "           convert_images (JSON), tts_voices_list, tts_voice_add, tts_voice_delete, tts_voice_preview,\n"
            "           tts_engines, tts_install_kokoro, tts_install_qwen3, tts_install_irodori, comfyui_install",
            file=sys.stderr,
        )
        sys.exit(1)

    sys.argv = split_mode_payload(sys.argv)

    # [NOTE] [Core] --force can appear anywhere on the command line (it's a
    # flag, not a positional arg) — strip it out before any positional
    # parsing below so waypoint_index/output_dir parsing is unaffected.
    force_arg = "--force" in sys.argv
    if force_arg:
        sys.argv = [arg for arg in sys.argv if arg != "--force"]
    # --no-llm: overview-script builds its draft from the route facts alone.
    no_llm_arg = "--no-llm" in sys.argv
    if no_llm_arg:
        sys.argv = [arg for arg in sys.argv if arg != "--no-llm"]

    try:
        command_arg = sys.argv[1]

        # [NOTE] [Furigana] Lightweight utility action: given a JSON array of
        # kanji strings (argv[2]), returns a JSON object mapping each word to
        # its pykakasi-derived hiragana reading.  Used by the frontend
        # Pronunciation Dictionary to auto-fill readings for detected kanji.
        if command_arg == "get_furigana":
            from services.localization.japanese_words import reading_of
            words = json.loads(sys.argv[2]) if len(sys.argv) > 2 else []
            readings = {word: reading_of(word) or "" for word in words}
            print(json.dumps({"success": True, "readings": readings}, ensure_ascii=False))
            sys.exit(0)

        # Reads a GPS file for the import dialog: track points, named waypoints, and the places it stayed at.
        # argv[2] is JSON: {"path", "radius_m"?, "min_stay_sec"?}.
        if command_arg == "import_gps_track":
            from services.gpsparser.stays import DEFAULT_MIN_STAY_SEC, DEFAULT_RADIUS_M, import_track
            args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
            track = import_track(args["path"], float(args.get("radius_m", DEFAULT_RADIUS_M)),
                                 float(args.get("min_stay_sec", DEFAULT_MIN_STAY_SEC)))
            print(json.dumps({"success": True, **track}, ensure_ascii=False))
            sys.exit(0)

        # Words with kanji in a script (whole words, not single kanji), each with its reading.
        # argv[2] is the script text itself.
        if command_arg == "extract_words":
            from services.localization.japanese_words import analyze_words
            text = sys.argv[2] if len(sys.argv) > 2 else ""
            print(json.dumps({"success": True, "words": analyze_words(text)}, ensure_ascii=False))
            sys.exit(0)

        # Plain text of a PDF / Word / text file the user gave the assistant. argv[2] is the file path.
        if command_arg == "read_document":
            from services.documents import read_document
            result = read_document(sys.argv[2] if len(sys.argv) > 2 else "")
            print(json.dumps(result, ensure_ascii=False))
            sys.exit(0)  # a failure is still a normal reply the chat shows, not a crashed run
        # How long a typed overview script is when spoken, from the project's own voice speed and route.
        # argv[2] is JSON: {"config": job_config.json path, "text": the script}. Read-only, no model.
        if command_arg == "overview_length":
            from services.cli.script_commands import overview_length
            args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
            print(json.dumps(overview_length(args["config"], args.get("text", "")), ensure_ascii=False))
            sys.exit(0)
        # Google Fonts for one picker language (argv[2]: "ja"/"en"), and installing one (argv[2]: family).
        if command_arg in ("google_fonts_catalog", "install_google_font"):
            from services.localization import google_fonts
            arg = sys.argv[2] if len(sys.argv) > 2 else ""
            try:
                if command_arg == "google_fonts_catalog":
                    reply = {"success": True, "fonts": google_fonts.catalog(arg)}
                else:
                    reply = {"success": True, "files": google_fonts.install(arg)}
            except Exception as exc:
                reply = {"success": False, "error": str(exc)}
            print(json.dumps(reply, ensure_ascii=False))
            sys.exit(0)

        # Installed font families for the font editor's picker.
        if command_arg == "list_fonts":
            from services.localization.fonts import downloaded_font_families, font_languages, installed_font_families
            print(json.dumps(
                {
                    "success": True, "fonts": installed_font_families(), "languages": font_languages(),
                    "downloaded": downloaded_font_families(),
                },
                ensure_ascii=False,
            ))
            sys.exit(0)

        # Voice library (list/add/delete/preview): argv[2] is a JSON payload,
        # stdout is one JSON object. See services/cli/voice_commands.py.
        from services.cli.voice_commands import VOICE_ACTIONS, run_voice_action
        if command_arg in VOICE_ACTIONS:
            payload = json.loads(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].strip() else {}
            print(json.dumps(run_voice_action(command_arg, payload), ensure_ascii=False))
            sys.exit(0)

        # Total/free memory and core count, for the "this model is too big for this PC" hint in Settings.
        if command_arg == "system_info":
            from services.cli.system_commands import system_info
            print(json.dumps(system_info()))
            sys.exit(0)

        # Photo import (HEIC to JPEG): argv[2] is a JSON payload, stdout one JSON object.
        # See services/cli/image_commands.py.
        from services.cli.image_commands import IMAGE_ACTIONS, run_image_action
        if command_arg in IMAGE_ACTIONS:
            payload = json.loads(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].strip() else {}
            print(json.dumps(run_image_action(command_arg, payload), ensure_ascii=False))
            sys.exit(0)

        if command_arg == "estimate":
            from services.render_estimate import estimate

            config = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
            print(json.dumps(estimate(config)))
            sys.exit(0)

        if command_arg == "full_pipeline":
            if len(sys.argv) < 3:
                raise ValueError("full_pipeline requires a source path")
            from services.vdoprocessing.videopipeline import run_full_pipeline

            result = run_full_pipeline(
                sys.argv[2],
                sys.argv[3] if len(sys.argv) > 3 else None,
                force_regenerate=force_arg,
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
            # Route (overview/residential) and attraction outputs get their
            # own subfolders under output_dir_arg instead of sharing one
            # flat folder — see helpers.project_route_video_dir/
            # project_attraction_video_dir.
            route_dir_arg = str(Path(output_dir_arg) / "route")
            attraction_dir_arg = str(Path(output_dir_arg) / "attraction")
            mode_arg = sys.argv[2] if len(sys.argv) > 2 else "overview"

            # [NOTE] [Core] Each branch below is one isolated pipeline step
            # (see services/cli/'s own module docstrings / test_*
            # docstrings) — run individually so a change scoped to one
            # stage doesn't require re-running the whole pipeline just to
            # check it.
            if mode_arg == "gps":
                # [NOTE] [GPS] Step 1 only: parses raw_track.gpx into a cleaned route + summary, no media generated.
                result = test_gps(job_config_arg)
            elif mode_arg == "upscale-images":
                # Only the photo-upscale stage (ESRGAN in ComfyUI, GPU).
                from services.vdoprocessing.videopipeline.upscale_step import upscale_waypoint_images
                from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient

                try:
                    result = upscale_waypoint_images(job_config_arg, force=force_arg)
                finally:
                    ComfyUII2VClient.stop_server()
                _tracker.clear()
            elif mode_arg == "map":
                # [NOTE] [Map] Fetches only the overview's background map image (same bbox/padding/crop as the real render, no video) - a seconds-long way to check framing. Optional argv[3] is the output png path.
                result = test_overview_map(job_config_arg, sys.argv[3] if len(sys.argv) > 3 else None)
            elif mode_arg == "residential":
                # [NOTE] [Animation] Renders the per-waypoint leg-by-leg clips (2D or 3D per settings.use_3d_res) — no overview map. Optional argv[3] renders just that ONE leg (0-indexed) instead of every leg.
                leg_index_arg = int(sys.argv[3]) if len(sys.argv) > 3 else None
                result = test_residential_video(
                    job_config_arg, route_dir_arg, force=force_arg, leg_index=leg_index_arg
                )
            elif mode_arg == "tts":
                # [NOTE] [TTS] Generates narration audio for ONE waypoint (index from argv[3], default 0).
                # None (not output_dir_arg, which is assets/video) so test_tts
                # falls back to its own project_audio_dir default (assets/
                # audio) -- passing output_dir_arg here used to put TTS test
                # output in the video folder instead of the audio one.
                waypoint_index_arg = int(sys.argv[3]) if len(sys.argv) > 3 else 0
                result = test_tts(job_config_arg, None, waypoint_index_arg, force=force_arg)
            elif mode_arg == "tts-all":
                # [NOTE] [TTS] The pipeline's whole TTS step: overview, every leg and every attraction narration, plus cue times.
                result = test_tts_all(job_config_arg, None, force=force_arg)
            elif mode_arg == "overview-tts":
                # [NOTE] [TTS] Generates only the overview narration audio.
                result = test_overview_tts(job_config_arg, None, force=force_arg)
            elif mode_arg == "attraction-tts":
                # [NOTE] [TTS] Generates the attraction-only narration audio for ONE waypoint (index from argv[3], default 0).
                waypoint_index_arg = int(sys.argv[3]) if len(sys.argv) > 3 else 0
                result = test_attraction_tts(job_config_arg, None, waypoint_index_arg, force=force_arg)
            elif mode_arg == "attraction-tts-all":
                # [NOTE] [TTS] Generates the attraction-only narration audio for every waypoint that has one (unconnected stop-bys are skipped).
                result = test_attraction_tts_all(job_config_arg, None, force=force_arg)
            elif mode_arg == "attraction":
                # [NOTE] [Animation] Generates ONE waypoint's attraction (pan/outpaint) video from its popup image (index from argv[3], default 0).
                waypoint_index_arg = int(sys.argv[3]) if len(sys.argv) > 3 else 0
                result = test_attraction_video(
                    job_config_arg, attraction_dir_arg, waypoint_index_arg, force=force_arg
                )
            elif mode_arg == "attraction-all":
                # [NOTE] [Animation] Generates attraction videos for every waypoint that has a popup image.
                result = test_attraction_videos(job_config_arg, attraction_dir_arg, force=force_arg)
            elif mode_arg == "attraction-finalize":
                # [NOTE] [Editor] Combines a multi-image waypoint's already-generated pending clips into the final deliverable (index from argv[3], default 0) — see test_attraction_finalize's docstring.
                waypoint_index_arg = int(sys.argv[3]) if len(sys.argv) > 3 else 0
                result = test_attraction_finalize(
                    job_config_arg, attraction_dir_arg, waypoint_index_arg
                )
            # [NOTE] [Core] intro/outro are on-demand CLI test hooks mirroring the
            # pipeline's own render_intro_clip/render_outro_clip steps.
            elif mode_arg == "intro":
                result = test_intro_video(job_config_arg, output_dir_arg)
            elif mode_arg == "outro":
                result = test_outro_video(job_config_arg, output_dir_arg)
            elif mode_arg == "subtitle":
                # [NOTE] [Subtitle] Generates the .srt for ONE waypoint from its matching TTS audio (index from argv[3], default 0). None = the project's assets/subtitles (output_dir_arg is assets/video, which is where these used to land by mistake).
                waypoint_index_arg = int(sys.argv[3]) if len(sys.argv) > 3 else 0
                result = test_subtitle(
                    job_config_arg, None, waypoint_index_arg, force=force_arg
                )
            elif mode_arg == "subtitle-all":
                # [NOTE] [Subtitle] Generates every .srt the pipeline makes (legs, overview, attractions) from the audio on disk.
                result = test_subtitles(job_config_arg, None, force=force_arg)
            elif mode_arg == "concat":
                # [NOTE] [Editor] Joins explicit clip paths (argv[3:]) — or, with none given, every *.mp4 already in the output dir in filename order — into 03_concat.mp4.
                clip_paths_arg = sys.argv[3:] if len(sys.argv) > 3 else None
                result = test_video_concat(
                    job_config_arg, output_dir_arg, clip_paths_arg
                )
            elif mode_arg == "mux":
                # [NOTE] [Editor] Muxes an existing audio file onto an existing video file: argv[3]=video path, argv[4]=audio path, optional argv[5]=output filename (else "<video-stem>_muxed.mp4", written under assets/video/). Standalone version of the mux the real pipeline runs internally — no re-render, just combines two files already on disk.
                if len(sys.argv) < 5:
                    raise ValueError("mux requires a video path (argv[3]) and an audio path (argv[4])")
                result = test_mux_audio(
                    job_config_arg, sys.argv[3], sys.argv[4],
                    output_dir_arg, sys.argv[5] if len(sys.argv) > 5 else None,
                )
            elif mode_arg == "transition":
                # [NOTE] [Transition] Renders the overview/storyboard map animation, including configured popup transitions — thin wrapper over test_overview_video.
                result = test_transition_editor(job_config_arg, route_dir_arg, force=force_arg)
            elif mode_arg == "overview-script":
                # [NOTE] [LLM] Drafts a tour-guide overview narration from the route (the way between stops, each stop described, {n}/{go} cues) into overview_script_draft.txt — never over overview_narration.
                result = test_overview_script(job_config_arg, use_llm=not no_llm_arg)
            elif mode_arg == "all":
                # [NOTE] [Core] Runs every isolated stage above in the pipeline's order and settings (TTS, subtitles, attractions, overview+residential, intro/outro, concat) — NOT the same as full_pipeline (no timeline.json, no audio in the concat).
                result = test_all(job_config_arg, output_dir_arg, force=force_arg)
            else:
                # [NOTE] [Core] Default when no mode (or an unrecognized one) is given — just the overview map animation.
                result = test_overview_video(job_config_arg, route_dir_arg, force=force_arg)

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
