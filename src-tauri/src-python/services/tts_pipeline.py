import os
import sys
from pathlib import Path
from typing import Optional

from services.job_config import JobConfigManager
from services.tts import IrodoriTTSClient, AudioProcessor, assemble_final_deliverable
from services.translator import ScriptTranslator
from services.vdoeditor import VideoEditor
from services.subtitle import SubtitleBuilder, SRTDocument, MasterSubtitleAssembler
from services.gps_parser import convert_gps_file, clean_gps_data
from services.video_pipeline import generate_navigation_video
from services.localization import build_display_text, _build_subtitle_style

POST_NARRATION_HOLD_SECONDS: float = 1.0
DEFAULT_CLIP_SUMMARY_FADE: float = 0.5
DEFAULT_CLIP_SUMMARY_HOLD: float = 2.0


async def run_synced_tts_pipeline(
    project_config_path: str, output_video_dir: Optional[str] = None
) -> dict:
    config_path = Path(project_config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Project config not found: {project_config_path}")

    job_config = JobConfigManager(config_path)
    project_dir = Path(job_config.get("directory_path", config_path.parent))
    audio_output_dir = project_dir / "audio"
    audio_output_dir.mkdir(parents=True, exist_ok=True)

    if not output_video_dir:
        output_video_dir = str((project_dir / "video").resolve())

    tts_client = IrodoriTTSClient(output_dir=audio_output_dir)
    audio_processor = AudioProcessor(output_dir=audio_output_dir)

    audio_paths, audio_durations, audio_pauses, segment_cues_list = [], [], [], []
    display_text, duration, pauses = "", 0.0, []
    target_lang = job_config.get("settings", {}).get("subtitle_language", "en")

    # 1. Handle Overview Narration First
    overview_text_jp = job_config.get("overview_narration", "").strip()
    print(" Generating Irodori-TTS audio for Overview...", file=sys.stderr)

    if overview_text_jp:
        path = await tts_client.generate_speech(overview_text_jp)
        audio_paths.append(path)
        analysis = audio_processor.analyze_pauses(path)
        duration, pauses = analysis["duration_seconds"], analysis["pauses"]
        audio_durations.append(duration)
        audio_pauses.append(pauses)

        display_text = build_display_text(overview_text_jp, target_lang)
        cues = SubtitleBuilder.build(
            display_text, duration, pauses, max_chars_per_line=40
        )
        segment_cues_list.append(cues)
        SRTDocument.write(cues, str(Path(path).with_suffix(".srt")))
    else:
        audio_paths.append(None)
        audio_durations.append(0.0)
        audio_pauses.append([])
        cues = SubtitleBuilder.build(
            display_text, duration, pauses, max_chars_per_line=40
        )
        segment_cues_list.append(cues)

    # 2. Handle Waypoint Narrations
    waypoints = job_config.get_waypoints()
    print(
        " Generating Irodori-TTS narration audio and subtitles for waypoints...",
        file=sys.stderr,
    )
    for wp in waypoints:
        text_jp = wp.get("narration", "").strip()
        if text_jp:
            path = await tts_client.generate_speech(text_jp)
            audio_paths.append(path)
            analysis = audio_processor.analyze_pauses(path)
            duration, pauses = analysis["duration_seconds"], analysis["pauses"]
            audio_durations.append(duration)
            audio_pauses.append(pauses)

            display_text = ScriptTranslator.translate(text_jp, target_lang=target_lang)
            cues = SubtitleBuilder.build(
                display_text, duration, pauses, max_chars_per_line=40
            )
            segment_cues_list.append(cues)
            SRTDocument.write(cues, str(Path(path).with_suffix(".srt")))
            print(
                f"   -> Generated {path} & translated subtitles ({duration}s)",
                file=sys.stderr,
            )
        else:
            audio_paths.append(None)
            audio_durations.append(0.0)
            audio_pauses.append([])
            segment_cues_list.append([])

    valid_audio_paths = [p for p in audio_paths if p]
    master_audio = None
    if valid_audio_paths:
        master_audio_path = audio_output_dir / "master_navigation_audio.wav"
        master_audio = audio_processor.concatenate_files(
            valid_audio_paths, str(master_audio_path)
        )

    # 3. Assemble Master Subtitles
    offsets, current_offset = [], 0.0
    for dur in audio_durations:
        offsets.append(current_offset)
        current_offset += dur if dur > 0 else 12.0

    master_cues = MasterSubtitleAssembler.assemble(segment_cues_list, offsets)
    master_srt_path = audio_output_dir / "master_navigation_subtitles.srt"
    SRTDocument.write(master_cues, str(master_srt_path))

    # 4. Process Route
    raw_gps_path = job_config.get("source_files", {}).get("gps_route")
    raw_gps_path = (
        raw_gps_path[0]
        if isinstance(raw_gps_path, list) and raw_gps_path
        else raw_gps_path
    )
    if not raw_gps_path:
        raise ValueError("GPS route source file not specified in configuration.")

    csv_output_filename = f"{Path(raw_gps_path).stem}_converted.csv"
    csv_path = convert_gps_file(
        input_file=raw_gps_path,
        output_filename=csv_output_filename,
        output_format="iblue747",
    )
    cleaned_route = clean_gps_data(csv_path)

    video_paths = generate_navigation_video(
        cleaned_route=cleaned_route,
        project_config_path=project_config_path,
        output_video_dir=output_video_dir,
        audio_durations=audio_durations,
        audio_pauses=audio_pauses,
    )

    editor = VideoEditor(job_config=job_config)
    (
        final_video_paths,
        segment_has_narration,
        segment_narration_audio,
        segment_durations,
    ) = ([], [], [], [])
    DEFAULT_OVERVIEW_DURATION, DEFAULT_PAUSE_SECONDS, DEFAULT_SUMMARY_HOLD = (
        8.0,
        2.0,
        4.0,
    )

    for i, vid_path in enumerate(video_paths):
        audio_idx = i
        if audio_idx < len(audio_paths) and audio_paths[audio_idx]:
            print(f" Muxing audio into segment {i}...", file=sys.stderr)
            base_name = Path(vid_path).stem
            muxed_filename = f"{base_name}_with_audio.mp4"
            muxed_path = editor.mux_audio_to_video(
                video_path=vid_path,
                audio_path=audio_paths[audio_idx],
                output_filename=muxed_filename,
            )
            final_video_paths.append(muxed_path)
            segment_has_narration.append(True)
            segment_narration_audio.append(audio_paths[audio_idx])

            post_tail = (
                (
                    DEFAULT_PAUSE_SECONDS
                    + DEFAULT_CLIP_SUMMARY_FADE
                    + DEFAULT_SUMMARY_HOLD
                )
                if i == 0
                else (
                    POST_NARRATION_HOLD_SECONDS
                    + DEFAULT_CLIP_SUMMARY_FADE
                    + DEFAULT_CLIP_SUMMARY_HOLD
                )
            )
            segment_durations.append(audio_durations[audio_idx] + post_tail)
            if os.path.exists(vid_path):
                os.remove(vid_path)
        else:
            final_video_paths.append(vid_path)
            segment_has_narration.append(False)
            segment_narration_audio.append(None)
            segment_durations.append(
                DEFAULT_OVERVIEW_DURATION + DEFAULT_PAUSE_SECONDS + DEFAULT_SUMMARY_HOLD
                if i == 0
                else 12.0
            )

    if len(video_paths) != len(segment_durations):
        print(
            f"⚠️  WARNING: video_paths ({len(video_paths)}) and segment_durations ({len(segment_durations)}) length mismatch.",
            file=sys.stderr,
        )

    print(
        "🎬 Assembling final combined video + audio with burned subtitles...",
        file=sys.stderr,
    )
    assembly = assemble_final_deliverable(
        video_segment_paths=final_video_paths,
        segment_has_narration=segment_has_narration,
        segment_durations=segment_durations,
        segment_narration_audio=segment_narration_audio,
        output_dir=output_video_dir,
        subtitle_path=str(master_srt_path),
        style=_build_subtitle_style(job_config),
    )

    return {
        "video_paths": final_video_paths,
        "master_audio_path": master_audio,
        "final_video_path": assembly["full_video_path"],
        "full_master_audio_path": assembly["full_audio_path"],
        "final_combined_path": assembly["final_combined_path"],
        "summary": cleaned_route.get("summary", {}),
        "master_subtitle_path": str(master_srt_path),
    }
