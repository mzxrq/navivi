"""Top-level orchestrator: renders every leg of a route into headless video clips."""

import asyncio
import json
import os
import shutil
import urllib.parse

import numpy as np
import pandas as pd
import pydeck as pdk

from .common import MAPBOX_API_KEY, logger, project_root
from .geomath import calculate_bearing, cumulative_distance_km, offset_point, smooth_bearings
from .httpserver import start_local_server
from .legresolve import _MODE_ALIASES, _resolve_leg
from .renderer import render_leg_animation
from .routedata import interpolate_route_data, load_route_from_config, patch_pydeck_html


def record_headless_video(
    config_path: str,
    output_video_path: str = "final_reliable_map_animation.mp4",
    audio_durations: list = None,
    fps: int = None,
    speed_kmh: float = None,
):
    audio_durations = audio_durations or []

    project_data = load_route_from_config(config_path)
    settings = project_data.get("settings", {})
    waypoints = project_data.get("waypoints", [])

    config_dir = os.path.dirname(config_path)
    # Scratch HTML/screenshot frames live under the PROJECT's own directory
    # (config_path's folder), not `project_root` — that name refers to the
    # src-python codebase root, so writing there scattered per-render debris
    # into the app's own source tree instead of the project.
    html_dir = os.path.join(config_dir, "frames")
    os.makedirs(html_dir, exist_ok=True)

    cache_path = os.path.join(config_dir, ".routecache.json")

    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            routing_cache = json.load(f)
    else:
        # Fallback just in case it's an old project
        routing_cache = project_data.get("routing_cache", {})

    num_legs = len(routing_cache)
    if num_legs == 0:
        logger.warning("No routing cache found! Exiting silently.")
        print("Error: Could not find any routes in .routecache.json!")
        return []

    render_fps = max(
        10, min(60, int(fps if fps is not None else settings.get("fps", 30)))
    )
    target_speed = speed_kmh if speed_kmh is not None else settings.get("speed_kmh")

    logger.info(f"Rendering at {render_fps} FPS")
    if target_speed:
        logger.info(f"Using constant speed: {target_speed} km/h")

    line_color = settings.get("line_color", [255, 0, 0])
    history_color = settings.get("history_color", [80, 80, 80])
    line_thickness = settings.get("line_thickness", 10)
    marker_color = settings.get("marker_color", [0, 0, 255])
    marker_radius = settings.get("marker_radius", 10)

    server, port = start_local_server(str(project_root))

    # Static Marker Setup (Added "name" property for labels)
    marker_filename = settings.get("marker_filename", "Sticker_08.glb")
    marker_url = f"http://127.0.0.1:{port}/assets/{urllib.parse.quote(marker_filename)}"
    waypoint_markers = [
        {
            "lon": float(wp.get("lng", wp.get("lon"))),
            "lat": float(wp["lat"]),
            "name": wp.get("label", ""),
        }
        for wp in waypoints
        if wp.get("lat")
    ]

    output_paths = []
    accumulated_trail = []
    base_dir, base_name = (
        os.path.dirname(output_video_path),
        os.path.splitext(os.path.basename(output_video_path))[0],
    )
    ext = os.path.splitext(output_video_path)[1]

    camera_config = {
        "car_size": 3,
        "yaw_offset": 180,
        "follow_zoom": 19,
        "follow_pitch": 60,
    }

    try:
        for leg_idx, (route_key, coords) in enumerate(routing_cache.items()):
            logger.info(f"\n--- Processing Leg {leg_idx + 1}/{num_legs} ---")

            resolved_mode, resolved_place, from_wp = _resolve_leg(route_key, waypoints)

            wp_idx = min(leg_idx + 1, len(waypoints) - 1) if waypoints else leg_idx + 1
            place_name = resolved_place or (
                waypoints[wp_idx].get("label", f"Place {wp_idx}")
                if wp_idx < len(waypoints)
                else "Destination"
            )

            print(f"    Rendering route to: '{place_name}' ({leg_idx + 1}/{num_legs})")

            fallback_mode = (
                route_key.split("|")[-1].strip().lower() if "|" in route_key else "walking"
            )
            leg_mode = resolved_mode or _MODE_ALIASES.get(fallback_mode, fallback_mode)

            if leg_mode == "walking":
                model_filename = "human.glb"
                camera_config["car_size"] = 2.0
            elif leg_mode == "ferry":
                model_filename = "ferry.glb"
                camera_config["car_size"] = 5.0
            elif leg_mode == "airplane":
                model_filename = "airplane.glb"
                camera_config["car_size"] = 10.0
            else:
                # driving, or any other/unrecognized mode.
                model_filename = "car.glb"
                camera_config["car_size"] = 3.0

            if from_wp is not None and "leg_size" in from_wp:
                camera_config["car_size"] = float(from_wp["leg_size"])

            model_url = (
                f"http://127.0.0.1:{port}/assets/{urllib.parse.quote(model_filename)}"
            )

            marker_filename = "Sticker_08.glb"
            safe_marker = urllib.parse.quote(marker_filename)
            marker_url = f"http://127.0.0.1:{port}/assets/{safe_marker}"

            df_raw = (
                pd.DataFrame([{"lat": c[0], "lon": c[1]} for c in coords])
                .drop_duplicates()
                .reset_index(drop=True)
            )
            leg_dist_km = cumulative_distance_km(
                df_raw["lon"].tolist(), df_raw["lat"].tolist()
            )
            total_leg_km = leg_dist_km[-1]

            if target_speed:
                leg_duration = max(1.0, (total_leg_km / target_speed) * 3600.0)
            else:
                audio_duration = (
                    audio_durations[leg_idx] if leg_idx < len(audio_durations) else 0.0
                )
                leg_duration = max(6.0, audio_duration + 1.0)

            total_frames = int(leg_duration * render_fps)
            smooth_df = interpolate_route_data(
                df_raw, leg_duration, total_frames, total_leg_km, leg_dist_km
            )

            raw_bearings = [
                calculate_bearing(
                    smooth_df.iloc[i]["lon"],
                    smooth_df.iloc[i]["lat"],
                    smooth_df.iloc[i + 1]["lon"],
                    smooth_df.iloc[i + 1]["lat"],
                )
                for i in range(len(smooth_df) - 1)
            ]
            raw_bearings.append(raw_bearings[-1] if raw_bearings else 0.0)

            smooth_bearing_list = smooth_bearings(
                raw_bearings, alpha=settings.get("bearing_smoothing", 0.15)
            )

            cam_follow_dist = settings.get("camera_follow_distance_m", 14)
            cam_coords = [
                offset_point(lon, lat, (b + 180) % 360, cam_follow_dist)
                for lon, lat, b in zip(
                    smooth_df["lon"], smooth_df["lat"], smooth_bearing_list
                )
            ]

            smooth_df["bearing"] = smooth_bearing_list
            smooth_df["yaw"] = [-b for b in smooth_bearing_list]
            smooth_df["cam_lon"] = [c[0] for c in cam_coords]
            smooth_df["cam_lat"] = [c[1] for c in cam_coords]

            popup_url, freeze_frames, image_display = None, 0, "pip"
            if wp_idx < len(waypoints):
                wp = waypoints[wp_idx]
                freeze_frames = int(float(wp.get("freeze_seconds", 0.0)) * render_fps)
                image_display = wp.get(
                    "image_display", wp.get("image display", "pip")
                ).lower()

                raw_popup = wp.get("popup_image")
                popup_img = (
                    str(raw_popup[0])
                    if isinstance(raw_popup, list) and raw_popup
                    else (str(raw_popup) if raw_popup else None)
                )

                if popup_img and os.path.exists(popup_img):
                    img_ext = os.path.splitext(popup_img)[1] or ".png"
                    temp_img_path = os.path.join(html_dir, f"popup_{leg_idx}{img_ext}")
                    shutil.copy2(popup_img, temp_img_path)
                    popup_url = (
                        f"http://127.0.0.1:{port}/frames/popup_{leg_idx}{img_ext}"
                    )

            center_lon = (df_raw["lon"].min() + df_raw["lon"].max()) / 2.0
            center_lat = (df_raw["lat"].min() + df_raw["lat"].max()) / 2.0
            max_diff = max(
                df_raw["lon"].max() - df_raw["lon"].min(),
                df_raw["lat"].max() - df_raw["lat"].min(),
                0.0001,
            )

            view_state = pdk.ViewState(
                longitude=center_lon,
                latitude=center_lat,
                zoom=min(17.5, max(13.0, 11.0 - np.log2(max_diff))) - 0.5,
                pitch=60,
                bearing=30,
            )

            base_layers = []

            # --- OPTIONAL: 3D BUILDING LAYER ---
            # If you want extruded 3D buildings on your map:
            building_layer = pdk.Layer(
                "GeoJsonLayer",
                id="building-layer",
                data="path_to_your_buildings.geojson",  # Path to your building data file
                extruded=True,
                get_elevation="properties.height",  # Height attribute from your data
                get_fill_color=[220, 200, 180, 200],  # Building color
                get_line_color=[100, 100, 100],
            )
            base_layers.append(building_layer)
            # -----------------------------------

            if accumulated_trail:
                base_layers.extend(
                    [
                        pdk.Layer(
                            "PathLayer",
                            id="static-glow",
                            data=[{"path": accumulated_trail}],
                            get_path="path",
                            get_color=history_color + [90],
                            width_scale=1,
                            width_min_pixels=line_thickness + 8,
                        ),
                        pdk.Layer(
                            "PathLayer",
                            id="static-trail",
                            data=[{"path": accumulated_trail}],
                            get_path="path",
                            get_color=history_color,
                            width_scale=1,
                            width_min_pixels=line_thickness,
                        ),
                    ]
                )

            mapbox_key = settings.get("mapbox_token", MAPBOX_API_KEY)

            base_html_path = os.path.join(html_dir, f"base_leg_{leg_idx}.html")
            pdk.Deck(
                layers=base_layers,
                initial_view_state=view_state,
                map_provider="mapbox",
                map_style="mapbox://styles/mapbox/outdoors-v12",
                api_keys={"mapbox": mapbox_key},
                views=[pdk.View(type="MapView", controller=False)],
            ).to_html(base_html_path)
            patch_pydeck_html(base_html_path)

            intro_popup_spec = None
            if leg_idx == 0 and waypoints:
                intro_wp = waypoints[0]
                intro_freeze_frames = int(
                    float(intro_wp.get("freeze_seconds", 0.0)) * render_fps
                )
                if intro_freeze_frames > 0:
                    intro_display = intro_wp.get(
                        "image_display", wp.get("image display", "pip")
                    ).lower()
                    raw_intro_popup = intro_wp.get("popup_image")
                    intro_popup_img = (
                        str(raw_intro_popup[0])
                        if isinstance(raw_intro_popup, list) and raw_intro_popup
                        else (str(raw_intro_popup) if raw_intro_popup else None)
                    )
                    intro_popup_url = None
                    if intro_popup_img and os.path.exists(intro_popup_img):
                        img_ext = os.path.splitext(intro_popup_img)[1] or ".png"
                        temp_img_path = os.path.join(html_dir, f"popup_intro{img_ext}")
                        shutil.copy2(intro_popup_img, temp_img_path)
                        intro_popup_url = (
                            f"http://127.0.0.1:{port}/frames/popup_intro{img_ext}"
                        )

                    intro_popup_spec = {
                        "freeze_frames": intro_freeze_frames,
                        "popup_url": intro_popup_url,
                        "image_display": intro_display,
                    }

            leg_output_path = os.path.join(
                base_dir, f"{base_name}_leg_{leg_idx:02d}{ext}"
            )

            asyncio.run(
                render_leg_animation(
                    base_html_path,
                    smooth_df,
                    accumulated_trail,
                    render_fps,
                    leg_output_path,
                    port,
                    model_url,
                    line_color,
                    line_thickness,
                    marker_color,
                    marker_radius,
                    camera_config,
                    popup_url=popup_url,
                    freeze_frames=freeze_frames,
                    marker_url=marker_url,
                    waypoint_markers=waypoint_markers,
                    image_display=image_display,
                    intro_popup=intro_popup_spec,
                    debug_dump_dir=(
                        os.path.join(html_dir, "debug_intro_frames")
                        if leg_idx == 0
                        else None
                    ),
                )
            )

            output_paths.append(leg_output_path)
            accumulated_trail.extend(df_raw[["lon", "lat"]].values.tolist())

            try:
                os.remove(base_html_path)
            except OSError:
                pass

        return output_paths

    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    config_path = r"C:\Users\user1\Documents\Navivi\Projects\proj_2026_very_cool_tomogashima_islands\job_config.json"
    record_headless_video(config_path, speed_kmh=120, fps=30)
