import math
import json
from pathlib import Path
from typing import Optional, Any, Dict

import numpy as np
import pyproj
import asyncio

from services.gps_parser import convert_gps_file, clean_gps_data, haversine_vectorized
from services.mapfetcher import MapFetcher
from services.route2vdo import RouteAnimator
from services.localization import format_waypoint_label
from services.job_config import JobConfigManager
from services.vdo_exporter import VideoExporter
from services.img2vdo import AttractionVideoGenerator
from services.logger import setup_logger

# Standardized logger — writes to logs/app.log AND stderr, matching
# every other service module in this codebase.
logger = setup_logger("VideoPipeline")

BASE_DIR = Path(__file__).resolve().parent.parent
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
    """Helper to convert GPS coordinates to pixel space on the map."""
    w, e, s, n = extent
    merc_x, merc_y = _WGS84_TO_WEBMERCATOR.transform(lons, lats)
    px = (np.asarray(merc_x) - w) / (e - w) * img_width_px
    py = (n - np.asarray(merc_y)) / (n - s) * img_height_px
    return [[float(x), float(y)] for x, y in zip(px, py)]


# =========================================================================
#  [Core] PARSE & CLEAN GPS
# =========================================================================
def process_gps(raw_source_path: str) -> dict:
    """Extracts the GPS path from job_config.json, then converts and cleans the data."""
    print("Step 1: Processing GPS Data from config...")
    logger.info("Step 1: Processing GPS data from config: %s", raw_source_path)

    config_path = Path(raw_source_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Project configuration file missing: {config_path}")

    # Open and parse the JSON file
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = json.load(f)

    # Extract the GPS route path from the nested dictionary
    source_files = config_data.get("source_files", {})
    raw_source_path = source_files.get("gps_route")

    if not raw_source_path or not Path(raw_source_path).exists():
        raise FileNotFoundError(
            f"GPS route file not found in config or on disk: {raw_source_path}"
        )

    source_path = Path(raw_source_path)

    csv_path = convert_gps_file(
        input_file=str(source_path),
        output_filename=source_path.with_suffix(".csv").name,
        output_format="iblue747",
    )
    cleaned = clean_gps_data(csv_path)
    summary = cleaned.get("summary", {})
    logger.info(
        "Step 1 complete: %d route points, %.2f km, %s",
        summary.get("total_route_points", 0),
        summary.get("total_distance_km", 0.0),
        summary.get("total_duration_formatted", "N/A"),
    )
    return cleaned


# =========================================================================
#  [Core] GENERATE AUDIO (TTS)
# =========================================================================
def generate_audio(cleaned_route: dict, project_config_path: str) -> dict:
    """
    Generates Irodori TTS audio based on the parsed route.
    Uses the local TTSPipelineManager from tts.py to generate and analyze clips.
    """
    print("Step 2: Generating TTS Audio via tts.py...")
    logger.info("Step 2: Generating TTS audio for config: %s", project_config_path)

    audio_durations = []
    audio_pauses = []
    audio_paths = []
    subtitle_paths = []

    try:
        config_path = Path(project_config_path)
        if not config_path.exists():
            logger.warning("Step 2: No project config found. Skipping TTS.")
            return {
                "audio_durations": [],
                "audio_pauses": [],
                "audio_paths": [],
                "subtitle_paths": [],
            }

        with open(config_path, "r", encoding="utf-8") as f:
            project_config = json.load(f)

        waypoints = project_config.get("waypoints", [])

        # Import the unified manager from your new tts.py file
        from services.tts import TTSPipelineManager

        tts_manager = TTSPipelineManager()

        # Create an async worker to process all TTS tasks
        async def _generate_all_speech():
            for idx, wp in enumerate(waypoints):
                # Look for narration text in standard keys
                script = wp.get("script") or wp.get("narration") or wp.get("voiceover")

                if not script:
                    # If there's no script for this waypoint, append empty defaults
                    audio_durations.append(0.0)
                    audio_pauses.append([])
                    audio_paths.append(None)
                    subtitle_paths.append(None)
                    continue

                logger.info(
                    f"Step 2: [%d/%d] Generating audio for: '%s'",
                    idx + 1,
                    len(waypoints),
                    wp.get("label", f"Waypoint {idx}"),
                )

                # 1. Generate Speech via IrodoriTTSClient
                wav_path = await tts_manager.get_speech(script)

                # 2. Analyze pauses via AudioProcessor
                analysis = tts_manager.analyze_pauses(wav_path)

                audio_durations.append(analysis.get("total_duration", 0.0))
                audio_pauses.append(analysis.get("pauses", []))
                audio_paths.append(wav_path)

                # Subtitles can be injected here later if your TTS engine outputs them
                subtitle_paths.append(None)

        # Execute the async function synchronously within the pipeline
        asyncio.run(_generate_all_speech())

        logger.info("Step 2 complete: TTS audio successfully generated.")
        return {
            "audio_durations": audio_durations,
            "audio_pauses": audio_pauses,
            "audio_paths": audio_paths,
            "subtitle_paths": subtitle_paths,
        }

    except ImportError as e:
        logger.error(
            "Step 2 failed: Could not import TTSPipelineManager from services.tts. %s",
            e,
        )
        return {
            "audio_durations": [],
            "audio_pauses": [],
            "audio_paths": [],
            "subtitle_paths": [],
        }
    except Exception as e:
        logger.error("Step 2 failed: TTS Audio generation encountered an error: %s", e)
        return {
            "audio_durations": [],
            "audio_pauses": [],
            "audio_paths": [],
            "subtitle_paths": [],
        }


# =========================================================================
#  [Core] RENDER ROUTE VIDEO
# =========================================================================
def render_route_video(
    cleaned_route: dict,
    project_config_path: str = str(DEFAULT_FRONTEND_CONFIG),
    output_video_dir: str = str(BASE_DIR / "data" / "outputs" / "video"),
    map_output_path: str = str(DEFAULT_MAP_BACKGROUND),
    audio_durations: Optional[list[float]] = None,
    audio_pauses: Optional[list[Any]] = None,
) -> list[str]:
    """Generates the visual map animation using synced audio timing."""
    print("Step 3: Rendering Video Engine...")
    logger.info("Step 3: Rendering Video Engine — starting.")

    audio_durations = audio_durations or []
    audio_pauses = audio_pauses or []
    route_df = cleaned_route["route"]
    summary = cleaned_route.get("summary", {})

    if route_df.empty:
        raise ValueError("Cannot render a navigation video from an empty route.")

    logger.info("Step 3: Computing bounding box and fetching overview map tile...")
    fetcher = MapFetcher()
    bbox = fetcher.get_bounding_box(route_df, padding_factor=0.15)
    map_output_path, extent, (img_w, img_h) = fetcher.fetch_image(
        bbox, output_filename=map_output_path
    )

    if map_output_path is None:
        raise RuntimeError(
            "Map fetch failed - cannot render video without background map."
        )
    logger.info("Step 3: Overview map tile ready -> %s", map_output_path)

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
    route_popups = [None] * len(route_points)

    project_config = {}
    config_path = Path(project_config_path)
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            project_config = json.load(f)

    waypoints = project_config.get("waypoints", []) if project_config else []
    wp_indices = MapFetcher.build_waypoint_index(route_df, waypoints)

    settings: Dict[str, Any] = (
        project_config.get("settings", {}) if project_config else {}
    )
    subtitle_lang = settings.get("subtitle_language", "en")

    if waypoints:
        print(f"Injecting {len(waypoints)} custom waypoints from JSON config...")
        logger.info(
            "Step 3: Injecting %d custom waypoints from job_config.json.",
            len(waypoints),
        )

        start_point_label = project_config.get("start_point", {}).get("label")
        end_point_label = project_config.get("end_point", {}).get("label")

        for idx, wp in enumerate(waypoints):
            closest_idx = wp_indices[idx]
            raw_label = wp.get("label", "Waypoint")

            if idx == 0 and start_point_label:
                raw_label = start_point_label
            elif idx == len(waypoints) - 1 and end_point_label:
                raw_label = end_point_label

            formatted_label = format_waypoint_label(raw_label, subtitle_lang)

            if idx == 0:
                wp_label = f"Start: {formatted_label}" if formatted_label else "Start"
            elif idx == len(waypoints) - 1:
                wp_label = f"Stop: {formatted_label}" if formatted_label else "Stop"
            else:
                wp_label = formatted_label

            route_labels[closest_idx] = wp_label

            logger.info(
                "Step 3: [%d/%d] Waypoint resolved -> '%s' (route index %d)",
                idx + 1,
                len(waypoints),
                wp_label,
                closest_idx,
            )

            raw_popup = wp.get("popup_image")
            popup_img = (
                str(raw_popup[0])
                if isinstance(raw_popup, list) and raw_popup
                else str(raw_popup) if raw_popup else None
            )

            route_popups[closest_idx] = {  # type: ignore
                "freeze_seconds": float(wp.get("freeze_seconds", 3.0)),
                "popup_image": popup_img,
                "image display": wp.get("image display", "none").lower(),
                "triggered": False,
            }

    image_output_dir = BASE_DIR / "data" / "inputs" / "res_images"

    logger.info(
        "Step 3: Generating residential map sequence for %d waypoint(s)...",
        len(waypoints),
    )
    sequence_data = MapFetcher.generate_residential_sequence(
        route_df,
        waypoints,
        image_output_dir,
        (img_w, img_h),
        max_chunk_distance_meters=math.inf,
        precomputed_indices=wp_indices,
    )
    logger.info(
        "Step 3: Residential map sequence complete — %d chunk(s) generated.",
        len(sequence_data),
    )

    seg_durations = (
        MapFetcher.compute_segment_durations(
            wp_indices, route_df, target_avg_seconds=20.0
        )
        if waypoints and len(wp_indices) > 1
        else []
    )

    res_sequence = []
    total_segments = len(sequence_data)
    for seq_idx, item in enumerate(sequence_data):
        start_idx, end_idx = item["start_idx"], item["end_idx"]
        chunk = route_df.iloc[start_idx : end_idx + 1]

        place_name = route_labels[end_idx] if end_idx < len(route_labels) else None
        display_name = place_name or f"segment_{seq_idx + 1}"

        logger.info(
            "Step 3: [%d/%d] Generating residential leg video -> arriving at: '%s'",
            seq_idx + 1,
            total_segments,
            display_name,
        )

        chunk_points = _project_route_to_pixels(
            chunk["latitude"].to_numpy(),
            chunk["longitude"].to_numpy(),
            item["extent"],
            img_w,
            img_h,
        )

        real_time_sec = (
            (chunk["timestamp"].iloc[-1] - chunk["timestamp"].iloc[0]).total_seconds()
            if "timestamp" in chunk.columns and len(chunk) > 1
            else 0.0
        )
        lats_arr, lons_arr = item["lats"], item["lons"]
        seg_distance_km = (
            float(
                np.nansum(
                    haversine_vectorized(
                        lats_arr[:-1], lons_arr[:-1], lats_arr[1:], lons_arr[1:]
                    )
                )
            )
            if len(lats_arr) > 1
            else 0.0
        )

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

        travel_duration = total_time = (
            audio_durations[seq_idx] if has_audio else distance_fallback
        )
        raw_img_path = item.get("img_path")
        res_img = (
            str(raw_img_path[0])
            if isinstance(raw_img_path, list) and raw_img_path
            else str(raw_img_path) if raw_img_path else None
        )

        logger.info(
            "Step 3: [%d/%d] '%s' -> distance %.2f km, planned duration %.1fs%s",
            seq_idx + 1,
            total_segments,
            display_name,
            seg_distance_km,
            total_time,
            (
                " (synced to narration audio)"
                if has_audio
                else " (distance-based fallback)"
            ),
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
        "fps": settings.get("fps", 30),
        "duration": settings.get("duration_seconds", 8.0),
        "line_color": tuple(settings.get("line_color", (0, 200, 255))),
        "line_thickness": settings.get("line_thickness", 10),
        "marker_color": tuple(settings.get("marker_color", (0, 0, 255))),
        "marker_radius": settings.get("marker_radius", 18),
        "pause": settings.get("pause_seconds", 2.0),
        "summary_hold": settings.get("summary_hold", 4.0),
        "summary_fade": settings.get("summary_fade", 0.5),
        "clip_summary_hold": settings.get("clip_summary_hold", 2.0),
        "show_segment_summary": settings.get("show_segment_summary", True),
        "res_duration": settings.get("res_duration", 12.0),
        "post_arrival_hold_seconds": settings.get("post_arrival_hold_seconds", 1.0),
        "trigger_radius_padding": settings.get("trigger_radius_padding", {}),
        "fullscreen_transition": settings.get("fullscreen_transition", {}),
        "use_leg_storyboard": settings.get("use_leg_storyboard", False),
        "leg_durations": seg_durations if seg_durations else None,
        "default_transition_hold_seconds": settings.get(
            "default_transition_hold_seconds", 1.5
        ),
        # --- NEW FLAGS FOR 3D RESIDENTIAL ---
        "use_3d_res": True,  # Forces route2vdo.py to use the PyDeck renderer
        "res_route_path": project_config_path,
    }

    logger.info(
        "Step 3: Starting final render pass (overview%s)...",
        " + storyboard legs" if animator_config["use_leg_storyboard"] else "",
    )
    animator = RouteAnimator(animator_config)

    # 💡 NEW: Generate the 3D Video right here using the already-loaded project_config!
    from services.pydeck_recorder import (
        load_route_from_config,
        build_pydeck_map,
        record_headless_video,
    )

    logger.info("Step 3.5: Generating 3D Drone Background Video...")
    try:
        pydeck_route = load_route_from_config(project_config)
        html_file = build_pydeck_map(pydeck_route)
        video_background_path = record_headless_video(html_file, pydeck_route)
    except Exception as e:
        logger.error(
            "Failed to generate 3D Pydeck video: %s. Falling back to 2D Map.", e
        )
        video_background_path = map_output_path

    output_paths = animator.render(
        img_path=video_background_path,
        points=route_points,
        labels=route_labels,
        popups=route_popups,
        res_sequence=res_sequence,
        summary=summary,
        wp_indices=wp_indices,
    )
    logger.info("Step 3 complete: %d video file(s) produced.", len(output_paths))
    return output_paths


# =========================================================================
#  [Core] RENDER ATTRACTION VIDEO
# =========================================================================
def render_attraction_videos(
    project_config_path: str,
    audio_durations: Optional[list[float]] = None,
    audio_paths: Optional[list[str]] = None,
) -> list[str]:
    """Step 4: Generates AI videos for individual attractions using ComfyUI."""
    print("Step 4: Generating Attraction Videos via ComfyUI...")
    logger.info("Step 4: Generating attraction videos via ComfyUI.")

    config_path = Path(project_config_path)
    if not config_path.exists():
        print("No project config found. Skipping attraction videos.")
        logger.warning("Step 4: No project config found at %s — skipping.", config_path)
        return []

    job_config = JobConfigManager(config_path)
    generator = AttractionVideoGenerator(job_config=job_config)

    waypoints = job_config.get("waypoints", [])
    generated_videos = []

    audio_durations = audio_durations or []
    audio_paths = audio_paths or []

    for idx, wp in enumerate(waypoints):
        popup_image_entry = wp.get("popup_image")
        place_label = wp.get("label", f"waypoint_{idx}")

        if not popup_image_entry:
            logger.info(
                "Step 4: [%d/%d] Skipping '%s' — no popup image configured.",
                idx + 1,
                len(waypoints),
                place_label,
            )
            continue

        prompt_text = wp.get(
            "video_prompt", wp.get("label", "Beautiful Japanese scenery, high quality")
        )

        target_audio_duration = (
            audio_durations[idx] if idx < len(audio_durations) else 0.0
        )
        audio_path = audio_paths[idx] if idx < len(audio_paths) else None

        safe_label = str(wp.get("label", f"waypoint_{idx}")).replace(" ", "_")
        output_filename = f"04_attraction_{idx:02d}_{safe_label}.mp4"

        print(
            f"   -> Processing attraction {idx + 1}/{len(waypoints)}: {wp.get('label')}"
        )
        logger.info(
            "Step 4: [%d/%d] Generating attraction video for: '%s'",
            idx + 1,
            len(waypoints),
            place_label,
        )

        result_path = generator.process_attraction_video(
            popup_image_entry=popup_image_entry,
            prompt_text=prompt_text,
            target_audio_duration=target_audio_duration,
            audio_path=audio_path,
            output_filename=output_filename,
        )

        if result_path:
            logger.info(
                "Step 4: [%d/%d] '%s' complete -> %s",
                idx + 1,
                len(waypoints),
                place_label,
                result_path,
            )
            generated_videos.append(result_path)
        else:
            logger.warning(
                "Step 4: [%d/%d] '%s' FAILED to produce a video.",
                idx + 1,
                len(waypoints),
                place_label,
            )

    logger.info(
        "Step 4 complete: %d attraction video(s) produced.", len(generated_videos)
    )
    return generated_videos


# =========================================================================
# [Util] BURN SUBTITLES
# =========================================================================
def burn_subtitles(
    video_paths: list[str], subtitle_paths: list[str], output_dir: str
) -> list[str]:
    """Step 5: Permanently burns SRT subtitles onto the finished video files."""
    print("Step 5: Burning Subtitles into Videos...")
    logger.info("Step 5: Burning subtitles into %d video(s).", len(video_paths))

    final_videos = []

    for idx, video_path in enumerate(video_paths):
        original_file = Path(video_path)

        if idx < len(subtitle_paths) and subtitle_paths[idx]:
            sub_path = subtitle_paths[idx]
            subtitled_output = str(
                Path(output_dir)
                / f"{original_file.stem}_subtitled{original_file.suffix}"
            )

            print(f"   -> Burning subtitles onto: {original_file.name}")
            logger.info(
                "Step 5: [%d/%d] Burning subtitles onto '%s'.",
                idx + 1,
                len(video_paths),
                original_file.name,
            )
            try:
                result = VideoExporter.burn_subtitles(
                    input_video_path=video_path,
                    subtitle_file_path=sub_path,
                    output_video_path=subtitled_output,
                )
                final_videos.append(result)
            except Exception as e:
                print(f"     Failed to burn subtitle for {original_file.name}: {e}")
                logger.error(
                    "Step 5: [%d/%d] Failed to burn subtitle for '%s': %s",
                    idx + 1,
                    len(video_paths),
                    original_file.name,
                    e,
                )
                final_videos.append(video_path)
        else:
            logger.info(
                "Step 5: [%d/%d] No subtitle file for '%s' — passing through unchanged.",
                idx + 1,
                len(video_paths),
                original_file.name,
            )
            final_videos.append(video_path)

    logger.info("Step 5 complete: %d video(s) processed.", len(final_videos))
    return final_videos


# =========================================================================
# [Core] MASTER ORCHESTRATOR
# =========================================================================
def run_full_pipeline(
    raw_source_path: str, output_video_dir: Optional[str] = None
) -> dict:
    """Executes all steps sequentially for a one-click full generation."""
    print("Starting Full Automated Pipeline...")
    logger.info("=" * 60)
    logger.info("Starting Full Automated Pipeline for: %s", raw_source_path)
    logger.info("=" * 60)

    source_path = Path(raw_source_path)
    project_dir = source_path.parent
    config_file_path = project_dir / "job_config.json"
    job_config = JobConfigManager(config_file_path)

    if not output_video_dir:
        base_path = Path(job_config.get("directory_path", project_dir))
        output_video_dir = str((base_path / "video").resolve())

    # --- STEP 1 ---
    cleaned_route = process_gps(raw_source_path)

    # --- STEP 2 ---
    audio_data = generate_audio(cleaned_route, str(config_file_path))

    # --- STEP 3 ---
    video_paths = render_route_video(
        cleaned_route=cleaned_route,
        project_config_path=str(config_file_path),
        output_video_dir=output_video_dir,
        audio_durations=audio_data.get("audio_durations"),
        audio_pauses=audio_data.get("audio_pauses"),
    )

    all_videos = video_paths

    # --- STEP 5 ---
    final_videos = burn_subtitles(
        video_paths=all_videos,
        subtitle_paths=audio_data.get("subtitle_paths", []),
        output_dir=output_video_dir,
    )

    print("Full Pipeline Complete!")
    logger.info("=" * 60)
    logger.info("Full Pipeline Complete! %d final video(s).", len(final_videos))
    logger.info("=" * 60)
    return {"video_paths": final_videos, "summary": cleaned_route.get("summary", {})}


# =========================================================================
# NLE FAST RE-RENDERER
# =========================================================================
def render_from_timeline(
    timeline_json_path: str, output_video_path: Optional[str] = None
) -> str:
    """Reads an existing timeline.json file and instantly re-renders the master video."""
    timeline_path = Path(timeline_json_path)
    if not timeline_path.exists():
        raise FileNotFoundError(f"Timeline JSON not found: {timeline_path}")

    with open(timeline_path, "r", encoding="utf-8") as f:
        timeline_data = json.load(f)

    if not output_video_path:
        project_dir = timeline_path.parent
        output_video_path = str(project_dir / "video" / "01_overview_rerendered.mp4")

    print(f"NLE Engine: Re-rendering video from {timeline_path.name}...")
    logger.info("NLE Engine: Re-rendering video from %s...", timeline_path.name)

    final_path = VideoExporter.concat_from_timeline(
        timeline_data=timeline_data, output_path=output_video_path, save_json_path=None
    )

    print(f"Fast re-render complete: {final_path}")
    logger.info("NLE Engine: Fast re-render complete -> %s", final_path)
    return final_path
