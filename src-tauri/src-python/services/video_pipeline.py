import math
import json
import os
from pathlib import Path
import sys
from typing import Optional, Any, Dict

import numpy as np
import pyproj
import asyncio
from tqdm import tqdm

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


def clear_console():
    os.system("cls" if os.name == "nt" else "clear")


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
    logger.info("Processing GPS data from config: %s", raw_source_path)

    config_path = Path(raw_source_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Project configuration file missing: {config_path}")

    # Open and parse the JSON file
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = json.load(f)

    gps_route_file = config_data.get("source_files", {}).get("gps_route", "N/A")

    print(f"\n[Step 1/5] Processing GPS Data from: {Path(gps_route_file).name}")

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
def generate_audio(
    cleaned_route: dict,
    project_config_path: str,
    output_audio_dir: Optional[str] = None,
) -> dict:
    """
    Generates Irodori TTS audio based on the parsed route.
    Uses the local TTSPipelineManager from tts.py to generate and analyze clips.
    """
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
        print(
            f"\n[Step 2/5] Generating Narration Audio for {len(waypoints)} Waypoints..."
        )

        # Import the unified manager from your new tts.py file
        from services.tts import TTSPipelineManager

        # Properly initialize the manager with the target directory
        if output_audio_dir:
            Path(output_audio_dir).mkdir(parents=True, exist_ok=True)
            tts_manager = TTSPipelineManager(output_audio_dir=Path(output_audio_dir))
        else:
            tts_manager = TTSPipelineManager()

        # Create an async worker to process all TTS tasks
        async def _generate_all_speech():
            for idx, wp in enumerate(waypoints):
                # Look for narration text in standard keys
                script = wp.get("script") or wp.get("narration") or wp.get("voiceover")
                label = wp.get("label", f"Waypoint {idx + 1}")

                if not script:
                    audio_durations.append(0.0)
                    audio_pauses.append([])
                    audio_paths.append(None)
                    subtitle_paths.append(None)
                    continue

                print(f"   Synthesizing audio [{idx + 1}/{len(waypoints)}]: '{label}'")

                logger.info(
                    f"Step 2: [%d/%d] Generating audio for: '%s'",
                    idx + 1,
                    len(waypoints),
                    label,
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
    audio_paths: Optional[list[str]] = None,
    audio_durations: Optional[list[float]] = None,
    audio_pauses: Optional[list[Any]] = None,
) -> list[str]:
    """Generates the visual map animation using synced audio timing."""
    logger.info("Step 3: Rendering Video Engine — starting.")

    route_df = cleaned_route.get("route")
    if route_df is None or route_df.empty:
        raise ValueError("Cannot render a navigation video from an empty route.")

    # 1. Load Config & Settings Early
    project_config = {}
    config_path = Path(project_config_path)
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            project_config = json.load(f)

    project_name = project_config.get("project_name", "Navigation Project")

    print(f"\n[Step 3/5] Rendering Video Engine for Project: '{project_name}'")

    settings = project_config.get("settings", {})
    waypoints = project_config.get("waypoints", [])
    use_3d_res = settings.get("use_3d_res", True)
    subtitle_lang = settings.get("subtitle_language", "en")

    audio_durations = audio_durations or []
    audio_pauses = audio_pauses or []

    # 2. Fetch Base Map & Project Pixels
    logger.info("Step 3: Computing bounding box and fetching overview map tile...")

    fetcher = MapFetcher()

    bbox = fetcher.get_bounding_box(route_df, padding_factor=0.15)

    map_output_path, extent, (img_w, img_h) = fetcher.fetch_image(
        bounding_box=bbox, output_filename=map_output_path
    )

    if not map_output_path:
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
        row["store_name"] if row.get("is_landmarked") else None
        for _, row in route_df.iterrows()
    ]
    route_popups = [None] * len(route_points)
    wp_indices = MapFetcher.build_waypoint_index(route_df, waypoints)

    # 3. Inject Waypoints
    if waypoints:
        logger.info("Step 3: Injecting %d custom waypoints.", len(waypoints))
        start_label = project_config.get("start_point", {}).get("label")
        end_label = project_config.get("end_point", {}).get("label")

        for idx, wp in enumerate(waypoints):
            c_idx = wp_indices[idx]
            raw_label = wp.get("label", "Waypoint")

            if idx == 0 and start_label:
                raw_label = start_label
            elif idx == len(waypoints) - 1 and end_label:
                raw_label = end_label

            formatted = format_waypoint_label(raw_label, subtitle_lang)
            prefix = (
                "Start: " if idx == 0 else "Stop: " if idx == len(waypoints) - 1 else ""
            )
            route_labels[c_idx] = (
                f"{prefix}{formatted}" if formatted else prefix.strip(": ")
            )

            popup_img = wp.get("popup_image")
            route_popups[c_idx] = {
                "freeze_seconds": float(wp.get("freeze_seconds", 3.0)),
                "popup_image": (
                    str(popup_img[0])
                    if isinstance(popup_img, list) and popup_img
                    else (str(popup_img) if popup_img else None)
                ),
                "image display": wp.get("image display", "none").lower(),
                "triggered": False,
            }

    # 4. Process Residential Sequence (3D Bypass vs 2D Generation)
    res_sequence = []
    seg_durations = (
        MapFetcher.compute_segment_durations(
            wp_indices, route_df, target_avg_seconds=20.0
        )
        if len(wp_indices) > 1
        else []
    )

    if use_3d_res:
        logger.info(
            "Step 3: 3D residential rendering is enabled. Bypassing 2D map fetch."
        )
        for seq_idx in range(max(0, len(wp_indices) - 1)):
            has_audio = seq_idx < len(audio_durations) and audio_durations[seq_idx] > 0
            total_time = (
                audio_durations[seq_idx]
                if has_audio
                else (seg_durations[seq_idx] if seq_idx < len(seg_durations) else 10.0)
            )
            res_sequence.append({"segment_duration": total_time})
    else:
        logger.info("Step 3: Generating 2D residential map sequence...")
        img_out_dir = BASE_DIR / "data" / "inputs" / "res_images"
        sequence_data = MapFetcher.generate_residential_sequence(
            route_df,
            waypoints,
            img_out_dir,
            (img_w, img_h),
            max_chunk_distance_meters=math.inf,
            precomputed_indices=wp_indices,
        )

        for seq_idx, item in enumerate(sequence_data):
            start_idx, end_idx = item["start_idx"], item["end_idx"]
            chunk = route_df.iloc[start_idx : end_idx + 1]

            # Extract safe variables
            has_audio = seq_idx < len(audio_durations) and audio_durations[seq_idx] > 0
            distance_fallback = (
                seg_durations[seq_idx] if seq_idx < len(seg_durations) else 10.0
            )
            total_time = audio_durations[seq_idx] if has_audio else distance_fallback

            lats_arr, lons_arr = item["lats"], item["lons"]
            seg_dist = (
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

            raw_img = item.get("img_path")

            res_sequence.append(
                {
                    "img_path": (
                        str(raw_img[0])
                        if isinstance(raw_img, list) and raw_img
                        else (str(raw_img) if raw_img else None)
                    ),
                    "extent": item["extent"],
                    "lats": lats_arr,
                    "lons": lons_arr,
                    "points": _project_route_to_pixels(
                        chunk["latitude"].to_numpy(),
                        chunk["longitude"].to_numpy(),
                        item["extent"],
                        img_w,
                        img_h,
                    ),
                    "labels": route_labels[start_idx : end_idx + 1],
                    "popups": route_popups[start_idx : end_idx + 1],
                    "travel_duration": total_time,
                    "segment_duration": total_time,
                    "real_duration_seconds": (
                        (
                            chunk["timestamp"].iloc[-1] - chunk["timestamp"].iloc[0]
                        ).total_seconds()
                        if "timestamp" in chunk.columns and len(chunk) > 1
                        else 0.0
                    ),
                    "distance_km": seg_dist,
                    "pauses": (
                        audio_pauses[seq_idx] if seq_idx < len(audio_pauses) else []
                    ),
                }
            )

    # 5. Final Rendering Orchestration
    animator_config = {
        "output_dir": output_video_dir,
        "use_3d_res": use_3d_res,
        "res_route_path": project_config_path,
        "leg_durations": seg_durations or None,
        **{
            k: settings.get(k, default)
            for k, default in [
                ("fps", 30),
                ("duration", 8.0),
                ("line_thickness", 10),
                ("marker_radius", 18),
                ("pause", 2.0),
                ("summary_hold", 4.0),
                ("summary_fade", 0.5),
                ("clip_summary_hold", 2.0),
                ("show_segment_summary", True),
                ("res_duration", 12.0),
                ("post_arrival_hold_seconds", 1.0),
                ("use_leg_storyboard", False),
                ("default_transition_hold_seconds", 1.5),
            ]
        },
        "line_color": tuple(settings.get("line_color", (0, 200, 255))),
        "marker_color": tuple(settings.get("marker_color", (0, 0, 255))),
        "trigger_radius_padding": settings.get("trigger_radius_padding", {}),
        "fullscreen_transition": settings.get("fullscreen_transition", {}),
    }

    animator = RouteAnimator(animator_config)

    # 6. PyDeck 3D Background Generation
    # video_background_path = map_output_path
    # if use_3d_res:
    #     from services.pydeck_recorder import (
    #         load_route_from_config,
    #         build_pydeck_map,
    #         record_headless_video,
    #     )

    #     logger.info("Step 3.5: Generating 3D Drone Background Video...")
    #     logger.info("    Compiling 3D Map Animation Video...")
    #     try:
    #         pydeck_route = load_route_from_config(project_config_path)
    #         html_file = build_pydeck_map(pydeck_route)

    #         bg_output_target = str(
    #             Path(output_video_dir) / "01_3d_drone_background.mp4"
    #         )
    #         rendered_videos = record_headless_video(
    #             project_config_path, bg_output_target
    #         )

    #         if rendered_videos and len(rendered_videos) > 0:
    #             video_background_path = rendered_videos[0]
    #         else:
    #             logger.warning("PyDeck returned no videos. Falling back to 2D Map.")

    #     except Exception as e:
    #         logger.error(
    #             "Failed to generate 3D Pydeck video: %s. Falling back to 2D Map.", e
    #         )
    #         video_background_path = map_output_path

    output_paths = animator.render(
        img_path=map_output_path,
        points=route_points,
        labels=route_labels,
        popups=route_popups,
        res_sequence=res_sequence,
        summary=cleaned_route.get("summary", {}),
        wp_indices=wp_indices,
    )

    # --- 2. ADD THIS AUDIO MUXING BLOCK ---
    if audio_paths:
        from services.vdoeditor import VideoEditor

        editor = VideoEditor()
        muxed_paths = []

        logger.info("Muxing TTS narration audio into video segments...")

        # We need a separate counter just for the residential audio
        audio_idx = 0

        for v_path in output_paths:
            filename = Path(v_path).name

            # Only mux audio if the file is a residential leg (skip the overview map)
            if (
                "02_" in filename
                or "leg" in filename.lower()
                or "waypoint" in filename.lower()
            ):
                if (
                    audio_idx < len(audio_paths)
                    and audio_paths[audio_idx]
                    and os.path.exists(audio_paths[audio_idx])
                ):
                    try:
                        muxed = editor.mux_audio_to_video(
                            video_path=v_path,
                            audio_path=audio_paths[audio_idx],
                            output_filename=filename,
                        )
                        muxed_paths.append(muxed)
                    except Exception as e:
                        logger.error(f"Failed to mux audio for {v_path}: {e}")
                        muxed_paths.append(v_path)
                else:
                    muxed_paths.append(v_path)

                # Move to the next audio file for the next residential leg
                audio_idx += 1
            else:
                # This is the 01_overview map, pass it through silently!
                muxed_paths.append(v_path)

        output_paths = muxed_paths
    logger.info("Step 3 complete: %d video file(s) produced.", len(output_paths))
    print(f"    Successfully generated {len(output_paths)} video segment(s).")

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
    logger.info("Step 4: Generating attraction videos via ComfyUI.")

    config_path = Path(project_config_path)
    if not config_path.exists():
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

        # --- MODIFIED PROMPT EXTRACTION ---
        # Extract the full list of camera pans from the waypoint config
        camera_pans = wp.get("camera_pans", [])

        # Pass the whole list, or fallback to a default list if empty
        if camera_pans and len(camera_pans) > 0:
            prompt_text = camera_pans
        else:
            prompt_text = [wp.get("label", "Beautiful Japanese scenery, high quality")]
        # ----------------------------------

        target_audio_duration = (
            audio_durations[idx] if idx < len(audio_durations) else 0.0
        )
        audio_path = audio_paths[idx] if idx < len(audio_paths) else None

        safe_label = str(wp.get("label", f"waypoint_{idx}")).replace(" ", "_")
        output_filename = f"04_attraction_{idx:02d}_{safe_label}.mp4"

        print(
            f"\n[Step 4/5] Generating AI Video for Attraction [{idx + 1}/{len(waypoints)}]: '{wp.get('label')}'"
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
    logger.info("Step 5: Burning subtitles into %d video(s).", len(video_paths))
    print(f"\n[Step 5/5] Burning Subtitles and Finalizing Videos...")

    final_videos = []

    for idx, video_path in enumerate(video_paths):
        original_file = Path(video_path)

        if idx < len(subtitle_paths) and subtitle_paths[idx]:
            sub_path = subtitle_paths[idx]
            subtitled_output = str(
                Path(output_dir)
                / f"{original_file.stem}_subtitled{original_file.suffix}"
            )

            print(
                f"    Processing file [{idx + 1}/{len(video_paths)}]: {original_file.name}"
            )

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
            print(
                f"    Passing through video file [{idx + 1}/{len(video_paths)}]: {original_file.name}"
            )

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
    """Executes all steps sequentially with a single progress bar at the bottom."""
    # Clear the console screen for a fresh, clean view
    print("\033[H\033[J", end="")

    print("Starting Automated Video Rendering Pipeline\n")

    source_path = Path(raw_source_path)
    project_dir = source_path.parent
    config_file_path = project_dir / "job_config.json"
    job_config = JobConfigManager(config_file_path)

    if not output_video_dir:
        base_path = Path(job_config.get("directory_path", project_dir))
        output_video_dir = str((base_path / "video").resolve())

    # Initialize a single progress bar for the 4 main steps
    with tqdm(
        total=100,
        desc="Progress",
        bar_format="{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [Time: {elapsed}<{remaining}]",
    ) as pbar:

        # --- STEP 1 ---
        cleaned_route = process_gps(raw_source_path)
        pbar.update(2)

        # --- STEP 2 ---
        audio_data = generate_audio(cleaned_route, str(config_file_path))
        pbar.update(8)

        # --- STEP 3 ---
        attraction_videos = render_attraction_videos(
            str(config_file_path),
            audio_durations=audio_data.get("audio_durations"),
            audio_paths=audio_data.get("audio_paths"),
        )
        pbar.update(60)

        # --- STEP 4 ---
        video_paths = render_route_video(
            cleaned_route=cleaned_route,
            project_config_path=str(config_file_path),
            output_video_dir=output_video_dir,
            audio_durations=audio_data.get("audio_durations"),
            audio_pauses=audio_data.get("audio_pauses"),
            audio_paths=audio_data.get("audio_paths"),
        )
        pbar.update(85)

        all_videos = video_paths + attraction_videos

        # --- STEP 5 ---
        final_videos = burn_subtitles(
            video_paths=all_videos,
            subtitle_paths=audio_data.get("subtitle_paths", []),
            output_dir=output_video_dir,
        )
        pbar.update(5)

    print("\nProject Rendering Successfully Completed!")
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

    print(f"Fast re-render complete  {final_path}")
    logger.info("NLE Engine: Fast re-render complete  %s", final_path)
    return final_path


def estimate_step_durations(project_config: dict, cleaned_route: dict) -> dict:
    """Estimates the duration (in seconds) for each pipeline step."""
    waypoints = project_config.get("waypoints", [])
    num_waypoints = len(waypoints)

    total_points = cleaned_route.get("summary", {}).get("total_route_points", 100)

    # Heuristics based on standard local rendering speeds
    est_gps = 1.0  # GPS parsing is very fast
    est_tts = max(2.0, num_waypoints * 1.5)  # ~1.5s per TTS narration

    # 3D video rendering depends on total frames (assume 30fps, 8s per leg/waypoint)
    est_video = max(5.0, num_waypoints * 8.0 * 0.4)

    est_ai = (
        num_waypoints * 10.0 if any(wp.get("popup_image") for wp in waypoints) else 2.0
    )
    est_subtitles = 1.0

    return {
        "gps": est_gps,
        "tts": est_tts,
        "video": est_video,
        "ai": est_ai,
        "subtitles": est_subtitles,
        "total": est_gps + est_tts + est_video + est_ai + est_subtitles,
    }
