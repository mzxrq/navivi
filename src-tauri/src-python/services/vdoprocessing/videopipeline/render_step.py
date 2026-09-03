"""Step 3: Render the visual map animation, synced to audio timing."""

import json
import math
import os
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from services.gpsparser.gpscalculator import GPSMath
from services.mapfetcher.mapfetcher import MapFetcher
from services.vdoprocessing.route2vdo import RouteAnimator
from services.vdoprocessing.spatial_renderer import SpatialRenderer
from services.localization.localization import format_waypoint_label
from services.config.job_config import JobConfigManager

from .helpers import (
    BASE_DIR,
    DEFAULT_FRONTEND_CONFIG,
    DEFAULT_MAP_BACKGROUND,
    _build_point_modes,
    _project_route_to_pixels,
    logger,
)


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
    # 3D residential rendering is opt-in. The 2D spatial renderer is the
    # reliable fallback and remains the default for existing projects.
    use_3d_res = bool(settings.get("use_3d_res", False))
    subtitle_lang = settings.get("subtitle_language", "en")

    audio_durations = audio_durations or []
    audio_pauses = audio_pauses or []

    # 2. Fetch Base Map & Project Pixels
    logger.info("Step 3: Computing bounding box and fetching overview map tile...")

    # Pass the job_config explicitly (rather than relying on whatever state
    # the JobConfigManager singleton happens to already be in) so the tile
    # cache always lands under THIS project's directory_path/cache, even
    # when render_route_video runs as its own process/command without
    # process_gps having initialized the singleton first.
    fetcher = MapFetcher(job_config=JobConfigManager(str(config_path)))

    bbox = fetcher.get_bounding_box(route_df, padding_factor=0.10)

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

    routing_cache = {}
    routecache_path = config_path.parent / ".routecache.json"
    if routecache_path.exists():
        try:
            with open(routecache_path, "r", encoding="utf-8") as f:
                routing_cache = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Step 3: Failed to read %s: %s", routecache_path, e)

    point_modes = _build_point_modes(len(route_points), wp_indices, waypoints, routing_cache)

    mode_breakdown: dict[str, float] = {}
    mode_duration: dict[str, float] = {}
    total_distance_km = 0.0
    if len(route_df) > 1:
        lat_arr = route_df["latitude"].to_numpy()
        lon_arr = route_df["longitude"].to_numpy()
        seg_dist_km = GPSMath.haversine_vectorized(
            lat_arr[:-1], lon_arr[:-1], lat_arr[1:], lon_arr[1:]
        )
        total_distance_km = float(np.nansum(seg_dist_km))
        for dist, mode in zip(seg_dist_km, point_modes[1:]):
            mode_breakdown[mode] = mode_breakdown.get(mode, 0.0) + float(dist)

        # Per-mode time is derived from configured mode_speeds_kmh
        # (distance / speed), not raw GPS timestamps — the recorded track
        # often has stops/pauses baked into its timestamps (e.g. a long
        # lunch break during "walking") that would otherwise inflate the
        # summary card's duration well past what the video's own
        # mode-based animation speed implies. This keeps the on-screen
        # numbers consistent with the same speeds driving playback pacing
        # (see SpatialRenderer._mode_speed_factor).
        mode_speed_kmh = {
            **SpatialRenderer._DEFAULT_MODE_SPEED_KMH,
            **{
                str(k).lower(): float(v)
                for k, v in (settings.get("mode_speeds_kmh") or {}).items()
            },
        }
        for mode, dist_km in mode_breakdown.items():
            speed = mode_speed_kmh.get(mode) or mode_speed_kmh.get("car", 70.0)
            if speed > 0:
                mode_duration[mode] = (dist_km / speed) * 3600.0

    # Per-leg (waypoint-to-waypoint) distance/duration, so the overview can
    # show "this segment: X km, Y min" at each arrival instead of only a
    # single end-of-video total. leg_stats[i] is the leg arriving AT
    # waypoints[i + 1] (i.e. leaving waypoints[i]). Kept on raw GPS
    # timestamps (unlike mode_duration above) since these are shown
    # per-arrival right after the actual recorded leg, not folded into
    # the mode-speed-driven end summary.
    has_timestamp = "timestamp" in route_df.columns
    leg_stats: list[dict] = []
    for leg_idx in range(len(wp_indices) - 1):
        start_i, end_i = wp_indices[leg_idx], wp_indices[leg_idx + 1]
        if end_i <= start_i:
            leg_stats.append({"distance_km": 0.0, "duration_seconds": 0.0})
            continue
        seg_lat = route_df["latitude"].to_numpy()[start_i : end_i + 1]
        seg_lon = route_df["longitude"].to_numpy()[start_i : end_i + 1]
        seg_dist_km = float(
            np.nansum(
                GPSMath.haversine_vectorized(
                    seg_lat[:-1], seg_lon[:-1], seg_lat[1:], seg_lon[1:]
                )
            )
        )
        duration_seconds = (
            float(
                (
                    route_df["timestamp"].iloc[end_i]
                    - route_df["timestamp"].iloc[start_i]
                ).total_seconds()
            )
            if has_timestamp
            else 0.0
        )
        leg_stats.append(
            {"distance_km": seg_dist_km, "duration_seconds": duration_seconds}
        )

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
                "image_display": str(wp.get("image_display", "none")).lower(),
                "image_display": str(
                    wp.get("image_display", "pip")
                ).lower(),
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
        sequence_data = fetcher.process_residential_sequence(
            route_df,
            waypoints,
            output_size=(img_w, img_h),
            max_chunk_distance_meters=math.inf,
            precomputed_indices=wp_indices,
        )

        for seq_idx, item in enumerate(sequence_data):
            start_idx, end_idx = item["start_idx"], item["end_idx"]
            chunk = route_df.iloc[start_idx : end_idx + 1]
            leg_mode = (
                str(waypoints[seq_idx].get("routeMode", "")).lower()
                if seq_idx < len(waypoints)
                else ""
            )
            if not leg_mode and start_idx + 1 < len(point_modes):
                leg_mode = point_modes[start_idx + 1]
            leg_mode = leg_mode or "walking"
            if str(leg_mode).lower() == "ferry" and seq_idx + 1 < len(waypoints):
                # Ferry routes returned by routing providers can snap to
                # nearby roads. For the 2D residential view, represent a
                # ferry crossing as the direct water crossing between stops.
                start_wp, end_wp = waypoints[seq_idx], waypoints[seq_idx + 1]
                ferry_count = max(2, min(120, end_idx - start_idx + 1))
                ferry_lats = np.linspace(
                    float(start_wp["lat"]), float(end_wp["lat"]), ferry_count
                )
                ferry_lons = np.linspace(
                    float(start_wp["lng"]), float(end_wp["lng"]), ferry_count
                )
                chunk = pd.DataFrame(
                    {"latitude": ferry_lats, "longitude": ferry_lons}
                )
                ferry_map_path = str(
                    Path(item["img_path"]).with_name(f"res_map_ferry_{seq_idx + 1}.png")
                )
                item["img_path"] = ferry_map_path
                item["extent"] = fetcher.downloader.fetch_residential_chunk(
                    chunk, ferry_map_path, (img_w, img_h)
                )

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
                        GPSMath.haversine_vectorized(
                            lats_arr[:-1], lons_arr[:-1], lats_arr[1:], lons_arr[1:]
                        )
                    )
                )
                if len(lats_arr) > 1
                else 0.0
            )

            raw_img = item.get("img_path")
            leg_popups = [None] * len(chunk)
            if len(leg_popups) > 0:
                leg_popups[-1] = route_popups[end_idx]

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
                    # A residential clip starts at the previous waypoint,
                    # so only the destination popup may end its route
                    # animation. Including the start popup makes the renderer
                    # terminate on the first frame of every leg.
                    "popups": leg_popups,
                    "mode": leg_mode,
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

    # "duration_seconds" is the per-waypoint HOLD/freeze duration default
    # (see WaypointEditor's "Hold Duration" field, a 1-8s range) — it used
    # to also be read here as the length of the ENTIRE overview animation,
    # which made any real route fly by its stops in a few seconds flat.
    # Pace the overview off the route itself instead: a baseline per leg
    # (so a burst of nearby popups has a chance to clear before the next
    # one triggers) plus time proportional to the distance actually
    # covered, clamped to a sane range either way.
    num_legs = max(1, len(wp_indices) - 1) if wp_indices else 1
    base_overview_duration = max(
        24.0, min(180.0, num_legs * 8.0 + total_distance_km * 1.5)
    )
    # Overall playback speed for the overview — 2x by default (i.e. half
    # the paced-out duration above), tunable via job_config.json's
    # settings.overview_speed_multiplier. This scales everything uniformly
    # (mode-to-mode ratios from mode_speeds_kmh are unaffected), unlike
    # that setting which only controls relative pacing between modes.
    overview_speed_multiplier = float(settings.get("overview_speed_multiplier", 2.0))
    overview_duration = max(10.0, base_overview_duration / overview_speed_multiplier)

    animator_config = {
        "output_dir": output_video_dir,
        "use_3d_res": use_3d_res,
        "res_route_path": project_config_path,
        "leg_durations": seg_durations or None,
        "duration": settings.get("duration", overview_duration),
        **{
            k: settings.get(k, default)
            for k, default in [
                ("fps", 30),
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
                ("hide_route_on_popup", False),
                ("enable_fullscreen_popups", True),
                ("hide_upcoming_pins_on_popup", False),
            ]
        },
        "line_color": tuple(settings.get("line_color", (243, 150, 33))),  # BGR blue
        "marker_color": tuple(settings.get("marker_color", (0, 0, 255))),
        "arrived_marker_color": tuple(settings.get("arrived_marker_color", (0, 0, 220))),
        "trigger_radius_padding": settings.get("trigger_radius_padding", {}),
        "fullscreen_transition": settings.get("fullscreen_transition", {}),
        # Real-world average speed (km/h) per travel mode — how much
        # faster a car/ferry/etc. leg animates on screen relative to a
        # walking one is derived from these ratios (see SpatialRenderer's
        # _DEFAULT_MODE_SPEED_KMH for the fallback values). Set e.g.
        # {"walking": 3, "car": 70, "ferry": 36} in job_config.json's
        # settings to override per project.
        "mode_speeds_kmh": settings.get("mode_speeds_kmh", {}),
    }

    animator = RouteAnimator(animator_config)

    summary = dict(cleaned_route.get("summary", {}))
    if mode_breakdown:
        summary["mode_breakdown"] = mode_breakdown
    if mode_duration:
        summary["mode_duration"] = mode_duration
        # Keep the card's "Total" consistent with the per-mode durations
        # sitting right next to it, instead of mixing a mode-speed-derived
        # breakdown with a raw-GPS-timestamp total.
        summary["total_duration_seconds"] = sum(mode_duration.values())
    if leg_stats:
        summary["leg_stats"] = leg_stats

    output_paths = animator.render(
        img_path=map_output_path,
        points=route_points,
        labels=route_labels,
        popups=route_popups,
        res_sequence=res_sequence,
        summary=summary,
        wp_indices=wp_indices,
        point_modes=point_modes,
    )

    # --- 2. ADD THIS AUDIO MUXING BLOCK ---
    if audio_paths:
        from services.vdoprocessing.vdoeditor import VideoEditor

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
