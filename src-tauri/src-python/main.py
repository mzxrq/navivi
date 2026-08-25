"""
main.py
---------------------------------------------------------------------------
Entry point / orchestrator for the whole GPS-to-navigation-video pipeline,
integrated with Irodori-TTS speech synthesis and audio-video synchronization.
---------------------------------------------------------------------------
"""

import sys
import os
import json
import math
import asyncio
import traceback  # PATCH: needed for full stack traces in the CLI exception handler
from pathlib import Path
from typing import Any, Optional

from services.translator import ScriptTranslator  # PATCH: added for translation support
from services.romaji import RomajiConverter

import numpy as np
import pyproj


# Local Services
from services.gpsparser import (
    convert_gps_file,
    clean_gps_data,
    export_to_frontend_json,
    haversine_vectorized,
)
from services.filehandler import (
    initialize_new_project,
    save_project_asset_image,
    store_raw_file_with_datetime,
    generate_and_save_audio,
)
from services.mapfetcher import MapFetcher
from services.route2vdo import RouteAnimator
from services.tts import (
    get_irodori_speech,
    analyze_wav_pauses,
    concatenate_audio_files,
    assemble_final_deliverable,
    IrodoriTTSClient,
    AudioProcessor,
)
from services.job_config import JobConfigManager
from services.vdoeditor import VideoEditor
from services.llmscript import analyze_travel_image
from services.img2vdo import AttractionVideoGenerator

from services.subtitle import (
    SubtitleBuilder,
    SRTDocument,
    MasterSubtitleAssembler,
    SubtitleStyle,
)

SUBTITLE_MAX_CHARS_PER_LINE = 26

# Shared Constants
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_FRONTEND_CONFIG = (
    BASE_DIR
    / "data"
    / "inputs"
    / "gpsdata"
    / "processdata"
    / "json"
    / "example_frontend.json"
)
DEFAULT_MAP_BACKGROUND = (
    BASE_DIR / "data" / "inputs" / "fullmap_image" / "map_background.png"
)

# PATCH: these MUST mirror route2vdo.py's actual per-waypoint end-card tail
# constants (_render_waypoints: 1.0s hold + fade_sec + clip_hold_sec) so the
# master narration audio timeline (built here) matches the ACTUAL rendered
# video segment length. Previously segment_durations only counted the raw
# narration clip length, causing the master audio track to finish ~3s early
# per segment — which made `-shortest` in combine_video_and_audio truncate
# the final video by the accumulated shortfall (measured: 5.3s across 4
# segments in a real run).
#
# TODO(follow-up refactor): these are currently duplicated from route2vdo.py
# defaults rather than sourced from a single shared config object. If you
# ever change clip_summary_hold/summary_fade in route2vdo.py's job_config
# reads, update these to match, or better — have generate_navigation_video()
# return the actual per-segment tail durations it used, so this never has
# to be manually kept in sync again.
POST_NARRATION_HOLD_SECONDS: float = (
    1.0  # matches `for _ in range(fps): video.write(...)`
)
DEFAULT_CLIP_SUMMARY_FADE: float = 0.5  # matches route2vdo.py's fade_sec default
DEFAULT_CLIP_SUMMARY_HOLD: float = 2.0  # matches route2vdo.py's clip_hold_sec default

import re
from services.romaji import RomajiConverter

def is_japanese(text: str) -> bool:
    """Checks if a string contains Japanese characters (Kanji, Hiragana, Katakana)."""
    if not text:
        return False
    # Unicode ranges for Hiragana, Katakana, and CJK Unified Ideographs (Kanji)
    japanese_pattern = re.compile(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]')
    return bool(japanese_pattern.search(text))

def format_waypoint_label(raw_label: str, target_lang: str = "en") -> str:
    """
    Checks if the label is in Japanese. If target language is romaji/translation 
    and it contains Japanese, converts it. Otherwise, leaves English labels alone.
    """
    if not raw_label:
        return ""
    
    # If the user requested romaji and the label has Japanese text, convert it to Romaji
    if target_lang.lower() in ("romaji", "roman", "ja-romaji", "hepburn") and is_japanese(raw_label):
        return RomajiConverter.to_romaji(raw_label)
        
    return raw_label

def build_display_text(original_jp: str, target_lang: Any) -> str:
    if not isinstance(target_lang, str) or not target_lang.strip():
        target_lang = "en"
    normalized_target = target_lang.strip().lower()

    if normalized_target in ("romaji", "roman", "ja-romaji", "hepburn"):
        return RomajiConverter.to_romaji(original_jp)

    translated = ScriptTranslator.translate(original_jp, target_lang=target_lang)

    # Check the explicit failure flag to gracefully fall back to Romaji if offline models fail
    if ScriptTranslator.last_call_failed:
        print(
            f"⚠️  Translation to '{target_lang}' FAILED — falling back to Romaji for: {original_jp[:30]!r}...",
            file=sys.stderr,
        )
        return RomajiConverter.to_romaji(original_jp)

    return translated

def _build_subtitle_style(job_config: "JobConfigManager") -> SubtitleStyle:
    settings = job_config.get_settings()
    return SubtitleStyle(
        font_name=settings.get("subtitle_font", "Yu Gothic UI"),
        font_size=int(settings.get("subtitle_font_size", 30)),
        primary_color=settings.get("subtitle_color", "&H00FFFFFF"),
        outline_color=settings.get("subtitle_outline_color", "&H00000000"),
        bold=bool(settings.get("subtitle_bold", False)),
        alignment=int(settings.get("subtitle_alignment", 2)),
        margin_v=int(settings.get("subtitle_margin_v", 50)),
    )


async def generate_attraction_videos(project_config_path: str) -> list[Optional[str]]:
    job_config = JobConfigManager(project_config_path)
    project_dir = Path(
        job_config.get("directory_path", Path(project_config_path).parent)
    )

    audio_output_dir = project_dir / "audio"
    audio_output_dir.mkdir(parents=True, exist_ok=True)

    tts_client = IrodoriTTSClient(output_dir=audio_output_dir)
    audio_processor = AudioProcessor(output_dir=audio_output_dir)
    video_generator = AttractionVideoGenerator(job_config=job_config)

    waypoints = job_config.get_waypoints()
    audio_paths = []
    audio_durations = []

    print(
        "Step 1: Generating Irodori-TTS narration audio for attractions...",
        file=sys.stderr,
    )
    for i, wp in enumerate(waypoints):
        text = wp.get("video_narration") or wp.get("narration") or ""
        if text:
            audio_path = await tts_client.generate_speech(text)
            audio_paths.append(audio_path)

            analysis = audio_processor.analyze_pauses(audio_path)
            audio_durations.append(analysis["duration_seconds"])
            print(
                f"   -> Waypoint {i}: Audio generated ({analysis['duration_seconds']}s)",
                file=sys.stderr,
            )
        else:
            audio_paths.append(None)
            audio_durations.append(0.0)
            print(f"   -> Waypoint {i}: No narration text provided.", file=sys.stderr)

    print("\n🎬 Step 2: Generating AI Video Clips from Images...", file=sys.stderr)
    waypoint_video_outputs = []

    for i, wp in enumerate(waypoints):
        popup_image = wp.get("popup_image")
        prompt = (
            wp.get("video_narration") or wp.get("narration") or "Cinematic slow pan"
        )

        audio_path = audio_paths[i]
        target_dur = (
            audio_durations[i]
            if audio_durations[i] > 0
            else float(wp.get("freeze_seconds", 3.0))
        )

        if popup_image:
            out_filename = f"attraction_wp_{i:02d}.mp4"
            print(f"\n--- Processing Waypoint {i} ---", file=sys.stderr)

            video_result = video_generator.process_attraction_video(
                popup_image_entry=popup_image,
                prompt_text=prompt,
                target_audio_duration=target_dur,
                audio_path=audio_path,
                output_filename=out_filename,
            )
            waypoint_video_outputs.append(video_result)
        else:
            print(f"Skipping Waypoint {i}: No popup image found.", file=sys.stderr)
            waypoint_video_outputs.append(None)

    return waypoint_video_outputs


def data_pipeline_process(input_file: str, output_format: str = "iblue747") -> str:
    print(f"📁 Processing file: {input_file}")
    route = convert_gps_file(
        input_file=input_file,
        output_filename=input_file.replace(".TXT", ".csv"),
        output_format=output_format,
    )
    cleaned_route = clean_gps_data(route)
    json_route = export_to_frontend_json(
        cleaned_route, original_input_path=input_file, project_name="Untitled Project"
    )
    print("✅ Pipeline completed successfully!")
    return json.dumps(json_route, ensure_ascii=False)


def generate_audio_tts(text: str, output_path: str = "output.mp3") -> Optional[str]:
    return generate_and_save_audio(text, output_path)


def store_raw_file(input_file: str) -> Optional[str]:
    stored_file_path = store_raw_file_with_datetime(input_file)
    if stored_file_path:
        print(f"Raw file stored at: {stored_file_path}")
    else:
        print("Failed to store raw file.")
    return stored_file_path


def handle_incoming_gps_upload(raw_source_path: str) -> str:
    stored_path = store_raw_file(raw_source_path)
    if not stored_path:
        raise ValueError(f"Failed to store raw file from: {raw_source_path}")
    return data_pipeline_process(input_file=stored_path, output_format="iblue747")


_WGS84_TO_WEBMERCATOR = pyproj.Transformer.from_crs(
    "EPSG:4326", "EPSG:3857", always_xy=True
)


def _project_route_to_pixels(
    lats,
    lons,
    extent: tuple[float, float, float, float],
    img_width_px: int,
    img_height_px: int,
) -> list[list[float]]:
    w, e, s, n = extent
    merc_x, merc_y = _WGS84_TO_WEBMERCATOR.transform(lons, lats)
    px = (np.asarray(merc_x) - w) / (e - w) * img_width_px
    py = (n - np.asarray(merc_y)) / (n - s) * img_height_px
    return [[float(x), float(y)] for x, y in zip(px, py)]


def generate_navigation_video(
    cleaned_route: dict,
    project_config_path: str = str(DEFAULT_FRONTEND_CONFIG),
    output_video_dir: str = str(BASE_DIR / "data" / "outputs" / "video"),
    map_output_path: str = str(DEFAULT_MAP_BACKGROUND),
    audio_durations: Optional[list[float]] = None,
    audio_pauses: Optional[list[Any]] = None,
) -> list[str]:

    audio_durations = audio_durations or []
    audio_pauses = audio_pauses or []

    route_df = cleaned_route["route"]
    summary = cleaned_route.get("summary", {})

    if route_df.empty:
        raise ValueError("Cannot render a navigation video from an empty route.")

    fetcher = MapFetcher()
    bbox = fetcher.get_bounding_box(route_df, padding_factor=0.15)
    map_output_path, extent, (img_w, img_h) = fetcher.fetch_image(
        bbox, output_filename=map_output_path
    )

    if map_output_path is None:
        raise RuntimeError(
            "Map fetch failed - cannot render video without background map."
        )

    route_points = _project_route_to_pixels(
        route_df["latitude"].to_numpy(),
        route_df["longitude"].to_numpy(),
        extent,
        img_w,
        img_h,
    )
    route_labels = [
        (row["store_name"] if row.get("is_landmarked") else None)
        for _, row in route_df.iterrows()
    ]
    route_popups: list[Optional[dict[str, Any]]] = [None] * len(route_points)

    project_config = {}
    config_path = Path(project_config_path)
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            project_config = json.load(f)

    waypoints = project_config.get("waypoints", []) if project_config else []
    wp_indices = MapFetcher.build_waypoint_index(route_df, waypoints)

    settings = project_config.get("settings", {})
    subtitle_lang = settings.get("subtitle_language", "en")

    if waypoints:
        print(f"🗺️ Injecting {len(waypoints)} custom waypoints from JSON config...")
        for idx, wp in enumerate(waypoints):
            closest_idx = wp_indices[idx]
            raw_label = wp.get("label", "Waypoint")

            formatted_label = format_waypoint_label(raw_label, subtitle_lang)

            if idx == 0:
                wp_label = f"Start: {formatted_label}" if formatted_label else "Start"
            elif idx == len(waypoints) - 1:
                wp_label = f"Stop: {formatted_label}" if formatted_label else "Stop"
            else:
                wp_label = formatted_label

            route_labels[closest_idx] = wp_label

            # SAFEGUARD: Ensure popup_image is a strict string to prevent _path_exists errors
            raw_popup = wp.get("popup_image")
            if isinstance(raw_popup, list):
                popup_img = str(raw_popup[0]) if raw_popup else None
            else:
                popup_img = str(raw_popup) if raw_popup else None

            route_popups[closest_idx] = {
                "freeze_seconds": float(wp.get("freeze_seconds", 3.0)),
                "popup_image": popup_img,
                "triggered": False,
            }

    image_output_dir = BASE_DIR / "data" / "inputs" / "res_images"
    sequence_data = MapFetcher.generate_residential_sequence(
        route_df,
        waypoints,
        image_output_dir,
        (img_w, img_h),
        max_chunk_distance_meters=math.inf,
        precomputed_indices=wp_indices,
    )

    seg_durations = (
        MapFetcher.compute_segment_durations(
            waypoints, wp_indices, route_df, target_avg_seconds=20.0
        )
        if waypoints and len(wp_indices) > 1
        else []
    )

    res_sequence = []
    for seq_idx, item in enumerate(sequence_data):
        start_idx = item["start_idx"]
        end_idx = item["end_idx"]
        chunk = route_df.iloc[start_idx : end_idx + 1]
        chunk_points = _project_route_to_pixels(
            chunk["latitude"].to_numpy(),
            chunk["longitude"].to_numpy(),
            item["extent"],
            img_w,
            img_h,
        )

        real_time_sec = 0.0
        if "timestamp" in chunk.columns and len(chunk) > 1:
            real_time_sec = (
                chunk["timestamp"].iloc[-1] - chunk["timestamp"].iloc[0]
            ).total_seconds()

        lats_arr, lons_arr = item["lats"], item["lons"]
        if len(lats_arr) > 1:
            seg_distance_km = float(
                np.nansum(
                    haversine_vectorized(
                        lats_arr[:-1], lons_arr[:-1], lats_arr[1:], lons_arr[1:]
                    )
                )
            )
        else:
            seg_distance_km = 0.0

        distance_fallback = (
            seg_durations[seq_idx] if seq_idx < len(seg_durations) else 10.0
        )
        has_audio = (
            bool(audio_durations)
            and seq_idx < len(audio_durations)
            and audio_durations[seq_idx] > 0
        )
        active_pauses = (
            audio_pauses[seq_idx]
            if audio_pauses and seq_idx < len(audio_pauses)
            else []
        )

        if has_audio:
            travel_duration = total_time = audio_durations[seq_idx]
        else:
            travel_duration = total_time = distance_fallback

        # SAFEGUARD: Ensure generated sequence images are strictly strings
        raw_img_path = item.get("img_path")
        res_img = (
            str(raw_img_path[0])
            if isinstance(raw_img_path, list) and raw_img_path
            else str(raw_img_path) if raw_img_path else None
        )

        res_sequence.append(
            {
                "img_path": res_img,
                "extent": item["extent"],
                "lats": item["lats"],
                "lons": item["lons"],
                "points": chunk_points,
                "labels": route_labels[start_idx : end_idx + 1],
                "popups": route_popups[start_idx : end_idx + 1],
                "travel_duration": travel_duration,
                "segment_duration": total_time,
                "real_duration_seconds": real_time_sec,
                "distance_km": seg_distance_km,
                "pauses": active_pauses,
            }
        )

    animator_config = {
        "output_dir": output_video_dir,
        "fps": project_config.get("fps", 30),
        "duration": project_config.get("duration_seconds", 8.0),
        "line_color": project_config.get("line_color", (0, 200, 255)),
        "line_thickness": project_config.get("line_thickness", 10),
        "marker_color": project_config.get("marker_color", (0, 0, 255)),
        "marker_radius": project_config.get("marker_radius", 18),
        "pause": project_config.get("pause_seconds", 2.0),
        "summary_hold": project_config.get("summary_hold", 4.0),
        "summary_fade": project_config.get("summary_fade", 0.5),
        "res_duration": 12.0,
    }

    animator = RouteAnimator(animator_config)
    return animator.render(
        img_path=map_output_path,
        points=route_points,
        labels=route_labels,
        popups=route_popups,
        res_sequence=res_sequence,
        summary=summary,
    )


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

    audio_paths = []
    audio_durations = []
    audio_pauses = []
    segment_cues_list = []
    display_text = "" 
    duration = 0.0
    pauses = []

    # Optional: Read target language from your job_config settings, default to English
    target_lang = job_config.get("settings", {}).get("subtitle_language", "en")

    # 1. Handle Overview Narration First
    overview_text_jp = job_config.get("overview_narration", "").strip()
    print("🎙️ Generating Irodori-TTS audio for Overview...", file=sys.stderr)

    if overview_text_jp:
        # Generate Japanese Audio
        path = await tts_client.generate_speech(overview_text_jp)
        audio_paths.append(path)   # PATCH: this line was missing — without it,
                                    # every audio_paths[i] downstream referred to
                                    # the WRONG waypoint's narration (off-by-one),
                                    # and the final video segment lost its audio
                                    # entirely once the list ran short.

        analysis = audio_processor.analyze_pauses(path)
        duration = analysis["duration_seconds"]
        pauses = analysis["pauses"]

        audio_durations.append(duration)
        audio_pauses.append(pauses)

        # TRANSLATE HERE
        display_text = build_display_text(overview_text_jp, target_lang)

        # Build subtitles using the translated text (bump max chars to 40 for English words)
        cues = SubtitleBuilder.build(display_text, duration, pauses, max_chars_per_line=40)
        segment_cues_list.append(cues)

        srt_path = Path(path).with_suffix(".srt")
        SRTDocument.write(cues, str(srt_path))
    else:
        audio_paths.append(None)
        audio_durations.append(0.0)
        audio_pauses.append([])
        segment_cues_list.append([])
        path = Path("")

        # Build subtitles using the translated text (bump max chars to 40 for English words)
        cues = SubtitleBuilder.build(display_text, duration, pauses, max_chars_per_line=40)
        segment_cues_list.append(cues)

        srt_path = Path(path).with_suffix(".srt")
        SRTDocument.write(cues, str(srt_path))

    # 2. Handle Waypoint Narrations
    waypoints = job_config.get_waypoints()
    print("🎙️ Generating Irodori-TTS narration audio and subtitles for waypoints...", file=sys.stderr)
    for wp in waypoints:
        text_jp = wp.get("narration", "").strip()
        if text_jp:
            # Generate Japanese Audio
            path = await tts_client.generate_speech(text_jp)
            audio_paths.append(path)

            analysis = audio_processor.analyze_pauses(path)
            duration = analysis["duration_seconds"]
            pauses = analysis["pauses"]

            audio_durations.append(duration)
            audio_pauses.append(pauses)

            # 🌐 TRANSLATE HERE
            display_text = ScriptTranslator.translate(text_jp, target_lang=target_lang)

            # Build subtitles using the translated text
            cues = SubtitleBuilder.build(display_text, duration, pauses, max_chars_per_line=40)
            segment_cues_list.append(cues)

            srt_path = Path(path).with_suffix(".srt")
            SRTDocument.write(cues, str(srt_path))

            print(f"   -> Generated {path} & translated subtitles ({duration}s)", file=sys.stderr)
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

    # 3. Assemble Master Subtitles BEFORE rendering/muxing so the file exists
    offsets = []
    current_offset = 0.0
    for dur in audio_durations:
        offsets.append(current_offset)
        current_offset += dur if dur > 0 else 12.0

    master_cues = MasterSubtitleAssembler.assemble(segment_cues_list, offsets)
    master_srt_path = audio_output_dir / "master_navigation_subtitles.srt"
    SRTDocument.write(master_cues, str(master_srt_path))

    # SAFEGUARD: Unpack gps_route if it was accidentally saved as a list in the JSON
    raw_gps_path = job_config.get("source_files", {}).get("gps_route")
    if isinstance(raw_gps_path, list):
        raw_gps_path = raw_gps_path[0] if raw_gps_path else None

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
    final_video_paths = []
    segment_has_narration = []
    segment_narration_audio = []
    segment_durations = []

    DEFAULT_OVERVIEW_DURATION, DEFAULT_PAUSE_SECONDS, DEFAULT_SUMMARY_HOLD = (
        8.0,
        2.0,
        4.0,
    )

    for i, vid_path in enumerate(video_paths):
        audio_idx = i
        if audio_idx < len(audio_paths) and audio_paths[audio_idx]:
            print(f"🎵 Muxing audio into segment {i}...", file=sys.stderr)
            base_name = Path(vid_path).stem
            muxed_filename = f"{base_name}_with_audio.mp4"

            try:
                muxed_path = editor.mux_audio_to_video(
                    video_path=vid_path,
                    audio_path=audio_paths[audio_idx],
                    output_filename=muxed_filename,
                )
            except Exception as e:
                raise RuntimeError(
                    f"Failed to mux audio into segment {i} ({vid_path}): {e}"
                )

            final_video_paths.append(muxed_path)
            segment_has_narration.append(True)
            segment_narration_audio.append(audio_paths[audio_idx])

            # PATCH: previously `segment_durations.append(audio_durations[audio_idx])`
            # — the raw narration length only. The ACTUAL rendered video segment
            # is narration_length + a fixed post-narration tail (hold + fade +
            # summary-card hold), which the master audio track never accounted
            # for. That shortfall accumulated across every narrated segment and
            # made -shortest truncate the final combined video (measured: 5.3s
            # lost across 4 segments in a real run — see chat history).
            #
            # The overview segment (i == 0) uses route2vdo's OVERVIEW-specific
            # tail (pause + summary_fade + summary_hold from animator_config),
            # not the per-waypoint clip_summary_hold — these are two distinct
            # code paths in route2vdo.py's _render_overview vs _render_waypoints.
            if i == 0:
                post_tail = (
                    DEFAULT_PAUSE_SECONDS
                    + DEFAULT_CLIP_SUMMARY_FADE
                    + DEFAULT_SUMMARY_HOLD
                )
            else:
                post_tail = (
                    POST_NARRATION_HOLD_SECONDS
                    + DEFAULT_CLIP_SUMMARY_FADE
                    + DEFAULT_CLIP_SUMMARY_HOLD
                )
            segment_durations.append(audio_durations[audio_idx] + post_tail)

            if os.path.exists(vid_path):
                os.remove(vid_path)
        else:
            final_video_paths.append(vid_path)
            segment_has_narration.append(False)
            segment_narration_audio.append(None)

            if i == 0:
                segment_durations.append(
                    DEFAULT_OVERVIEW_DURATION
                    + DEFAULT_PAUSE_SECONDS
                    + DEFAULT_SUMMARY_HOLD
                )
            else:
                segment_durations.append(12.0)

    # PATCH: cheap early-warning invariant check. Converts a confusing
    # downstream "-shortest truncated my video" or a length-mismatch crash
    # 40+ seconds into rendering into an immediate, actionable log line.
    if len(video_paths) != len(segment_durations):
        print(
            f"⚠️  WARNING: video_paths ({len(video_paths)}) and segment_durations "
            f"({len(segment_durations)}) length mismatch — check waypoint matching.",
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
        style=_build_subtitle_style(job_config),   # PATCH
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


def run_full_pipeline(
    raw_source_path: str, output_video_dir: Optional[str] = None
) -> dict:
    source_path = Path(raw_source_path)
    project_dir = source_path.parent
    config_file_path = project_dir / "job_config.json"

    job_config = JobConfigManager(config_file_path)

    if not output_video_dir:
        base_path = Path(job_config.get("directory_path", project_dir))
        output_video_dir = str((base_path / "video").resolve())

    csv_path = convert_gps_file(
        input_file=raw_source_path,
        output_filename=source_path.with_suffix(".csv").name,
        output_format="iblue747",
    )
    cleaned_route = clean_gps_data(csv_path)

    video_paths = generate_navigation_video(
        cleaned_route=cleaned_route,
        project_config_path=str(config_file_path),
        output_video_dir=output_video_dir,
    )

    return {"video_paths": video_paths, "summary": cleaned_route.get("summary", {})}


if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1]
        payload = sys.argv[2] if len(sys.argv) > 2 else ""
        try:
            if command == "process_gps":
                print(handle_incoming_gps_upload(payload))

            elif command == "full_pipeline":
                output_arg = sys.argv[3] if len(sys.argv) > 3 else None
                result = run_full_pipeline(payload, output_video_dir=output_arg)
                print(
                    json.dumps(
                        {
                            "success": True,
                            "video_paths": result["video_paths"],
                            "summary": result["summary"],
                        },
                        ensure_ascii=False,
                    )
                )

            elif command == "init_project":
                project_name = sys.argv[3] if len(sys.argv) > 3 else "Untitled Project"
                config_path = initialize_new_project(
                    user_id=payload, project_name=project_name
                )
                print(
                    json.dumps(
                        {"success": True, "config_path": config_path},
                        ensure_ascii=False,
                    )
                )

            elif command == "save_asset":
                source_image_path = sys.argv[3] if len(sys.argv) > 3 else ""
                asset_path = save_project_asset_image(
                    project_dir=payload, source_image_path=source_image_path
                )
                print(
                    json.dumps(
                        {"success": True, "asset_path": asset_path}, ensure_ascii=False
                    )
                )

            elif command == "generate_speech":
                output_path = sys.argv[3] if len(sys.argv) > 3 else "output.mp3"
                saved_path = generate_and_save_audio(
                    text=payload, output_path=output_path
                )
                print(
                    json.dumps(
                        {"success": True, "audio_path": saved_path}, ensure_ascii=False
                    )
                )

            elif command == "synced_tts_pipeline":
                output_arg = sys.argv[3] if len(sys.argv) > 3 else None
                result = asyncio.run(
                    run_synced_tts_pipeline(
                        project_config_path=payload, output_video_dir=output_arg
                    )
                )
                print(json.dumps({"success": True, **result}, ensure_ascii=False))

            elif command == "save_config":
                config = JobConfigManager(payload)
                config.save()
                print(json.dumps({"success": True}, ensure_ascii=False))

            elif command == "analyze_image":
                analysis_result = analyze_travel_image(payload)
                print(
                    json.dumps(
                        {"success": True, "data": analysis_result}, ensure_ascii=False
                    )
                )

            elif command == "generate_attraction_videos":
                video_outputs = asyncio.run(generate_attraction_videos(payload))
                print(
                    json.dumps(
                        {"success": True, "video_outputs": video_outputs},
                        ensure_ascii=False,
                    )
                )

            else:
                print(
                    json.dumps(
                        {"success": False, "error": f"Unknown command '{command}'"},
                        ensure_ascii=False,
                    )
                )
                sys.exit(1)

        except Exception as e:
            # PATCH: previously `{"success": False, "error": str(e)}` alone —
            # discarded the full call stack, making bugs like the earlier
            # "segment_cues and segment_offsets" error a black box. Now every
            # failure carries its exact origin (file:line) for fast triage.
            error_res = {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__,
                "traceback": traceback.format_exc(),
            }
            print(json.dumps(error_res, ensure_ascii=False))
            sys.exit(1)
