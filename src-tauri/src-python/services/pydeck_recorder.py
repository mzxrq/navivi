import sys
import math
import shutil
from pathlib import Path
import asyncio
import os
import json
import glob
import pandas as pd
import numpy as np
import pydeck as pdk
from scipy.interpolate import interp1d

import urllib.parse
import threading
import http.server
import socketserver

current_dir = Path(__file__).resolve().parent
project_root = current_dir if current_dir.name == "src-python" else current_dir.parent
sys.path.append(str(project_root))

from services.vdoeditor import VideoEditor


# ---------------------------------------------------------
# LOCAL HTTP SERVER
# ---------------------------------------------------------
class ThreadedHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


def start_local_server(directory):
    """Starts a background web server to serve local 3D assets safely to Playwright."""

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)

        def log_message(self, format, *args):
            pass

    server = ThreadedHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


# ---------------------------------------------------------
# MATH & GEO HELPERS
# ---------------------------------------------------------
def calculate_bearing(lon1, lat1, lon2, lat2):
    """Calculates the compass bearing angle between two GPS coordinates."""
    lon1, lat1, lon2, lat2 = map(math.radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - (
        math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    )
    initial_bearing = math.atan2(x, y)
    return (math.degrees(initial_bearing) + 360) % 360


def smooth_bearings(bearings, alpha=0.15):
    """Circular exponential smoothing for a list of compass bearings (0-360)."""
    if not bearings:
        return []
    smoothed = [bearings[0]]
    current = bearings[0]
    for b in bearings[1:]:
        diff = ((b - current + 180) % 360) - 180
        current = (current + alpha * diff) % 360
        smoothed.append(current)
    return smoothed


def offset_point(lon, lat, bearing_deg, distance_m):
    """Returns a new (lon, lat) point `distance_m` meters away."""
    R = 6371000.0
    bearing_rad = math.radians(bearing_deg)
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    ang_dist = distance_m / R

    lat2 = math.asin(
        math.sin(lat_rad) * math.cos(ang_dist)
        + math.cos(lat_rad) * math.sin(ang_dist) * math.cos(bearing_rad)
    )
    lon2 = lon_rad + math.atan2(
        math.sin(bearing_rad) * math.sin(ang_dist) * math.cos(lat_rad),
        math.cos(ang_dist) - math.sin(lat_rad) * math.sin(lat2),
    )
    return math.degrees(lon2), math.degrees(lat2)


def haversine_km(lon1, lat1, lon2, lat2):
    """Great-circle distance in km between two points."""
    R = 6371.0
    lon1, lat1, lon2, lat2 = map(math.radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))


def cumulative_distance_km(lons, lats):
    """Cumulative traveled distance (km) at each point along a route."""
    cum = [0.0]
    for i in range(1, len(lons)):
        cum.append(cum[-1] + haversine_km(lons[i - 1], lats[i - 1], lons[i], lats[i]))
    return cum


# ---------------------------------------------------------
# DATA PROCESSING HELPERS
# ---------------------------------------------------------
def load_route_from_config(config_path: str):
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_pydeck_map(
    project_data: dict, output_html_path: str = "frames/temp_map.html"
):
    """Helper function required by video_pipeline.py to generate map configurations."""
    os.makedirs(os.path.dirname(output_html_path), exist_ok=True)

    raw_coords = []
    for route_key, coords in project_data.get("routing_cache", {}).items():
        for coord in coords:
            raw_coords.append({"lat": coord[0], "lon": coord[1]})

    if not raw_coords:
        raw_coords = [{"lat": 35.6762, "lon": 139.6503}]

    df_raw = pd.DataFrame(raw_coords)
    view_state = pdk.ViewState(
        longitude=df_raw["lon"].iloc[0],
        latitude=df_raw["lat"].iloc[0],
        zoom=15,
        pitch=45,
        bearing=0,
    )

    r = pdk.Deck(
        layers=[],
        initial_view_state=view_state,
        map_provider="carto",
        map_style=pdk.map_styles.DARK,
    )
    r.to_html(output_html_path)
    return output_html_path


def interpolate_route_data(
    df_raw: pd.DataFrame,
    leg_duration: float,
    total_frames: int,
    total_leg_km: float,
    leg_dist_km: list,
) -> pd.DataFrame:
    """Interpolates coordinates across frames to ensure smooth animation."""
    if total_leg_km > 0:
        df_raw["time_sec"] = [(d / total_leg_km) * leg_duration for d in leg_dist_km]
    else:
        df_raw["time_sec"] = np.linspace(0, leg_duration, num=len(df_raw))

    interp_lon = interp1d(
        df_raw["time_sec"],
        df_raw["lon"],
        kind="linear",
        fill_value="extrapolate",
        bounds_error=False,
    )
    interp_lat = interp1d(
        df_raw["time_sec"],
        df_raw["lat"],
        kind="linear",
        fill_value="extrapolate",
        bounds_error=False,
    )

    frame_times = np.linspace(0, leg_duration, num=total_frames)
    return pd.DataFrame(
        {
            "frame_id": range(total_frames),
            "lon": interp_lon(frame_times),
            "lat": interp_lat(frame_times),
        }
    )


def patch_pydeck_html(html_path: str):
    """Exposes deckgl to the window object and injects missing CSS."""
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()

    content = content.replace("const deckgl =", "window.deckgl =")
    content = content.replace("let deckgl =", "window.deckgl =")
    content = content.replace(
        "const deckInstance = createDeck(",
        "const deckInstance = window.deckgl = createDeck(",
    )

    if "mapbox-gl.js" in content and "mapbox-gl.css" not in content:
        content = content.replace(
            "</head>",
            '<link rel="stylesheet" href="https://api.tiles.mapbox.com/mapbox-gl-js/v1.13.0/mapbox-gl.css" />\n</head>',
            1,
        )

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(content)


# ---------------------------------------------------------
# CORE RENDERER
# ---------------------------------------------------------
async def render_leg_animation(
    base_html_path,
    df,
    accumulated_trail,
    fps,
    output_filename,
    port,
    model_url,
    trail_color,
    line_thickness,
    marker_color,
    marker_radius,
    camera_config,
    popup_url=None,
    freeze_frames=0,
    marker_url=None,
    waypoint_markers=None,
    image_display="pip",
):
    """Opens a single HTML file and uses JavaScript injection to rapidly animate the route."""
    from playwright.async_api import async_playwright

    editor = VideoEditor()
    ffmpeg_cmd = [
        editor.engine.resolve_binary(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "-framerate",
        str(fps),
        "-i",
        "-",
        "-c:v",
        "libx264",
        "-r",
        str(fps),
        "-pix_fmt",
        "yuv420p",
        output_filename,
    ]

    proc = await asyncio.create_subprocess_exec(
        *ffmpeg_cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL
    )

    c_trail = json.dumps(trail_color)
    c_glow = json.dumps(trail_color + [90])
    c_halo = json.dumps(marker_color + [80])
    waypoints_json = json.dumps(waypoint_markers or [])

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-web-security",
                "--ignore-gpu-blocklist",
                "--use-gl=angle",
                "--use-angle=gl",
            ],
        )
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()
        page.on("pageerror", lambda exc: print(f"  [PAGE ERROR] {exc}"))

        rel_path = os.path.relpath(base_html_path, project_root).replace("\\", "/")
        await page.goto(f"http://127.0.0.1:{port}/{rel_path}")

        print("  ... Pre-loading map and 3D models (Fast load...)")
        try:
            await page.wait_for_load_state("load", timeout=2000)
        except Exception:
            pass
        await page.wait_for_timeout(2000)

        for index, row in df.iterrows():
            full_trail = (
                accumulated_trail + df.iloc[: index + 1][["lon", "lat"]].values.tolist()
            )

            trail_json = json.dumps([{"path": full_trail}])
            car_json = json.dumps(
                [{"lon": row["lon"], "lat": row["lat"], "yaw": row["yaw"]}]
            )
            halo_json = json.dumps([{"lon": row["lon"], "lat": row["lat"]}])

            js_code = f"""
            if (window.deckgl) {{
                const currentLayers = window.deckgl.props.layers || [];
                const staticLayers = currentLayers.filter(l => 
                    !['vehicle-layer', 'halo-layer', 'trail-layer', 'trail-glow', 'waypoint-3d-markers'].includes(l.id)
                );
                
                const newGlow = new deck.PathLayer({{
                    id: 'trail-glow', data: {trail_json},
                    getPath: d => d.path, getColor: {c_glow},
                    widthScale: 1, widthMinPixels: {line_thickness + 8}
                }});
                
                const newTrail = new deck.PathLayer({{
                    id: 'trail-layer', data: {trail_json},
                    getPath: d => d.path, getColor: {c_trail},
                    widthScale: 1, widthMinPixels: {line_thickness}
                }});
                
                const newHalo = new deck.ScatterplotLayer({{
                    id: 'halo-layer', data: {halo_json},
                    getPosition: d => [d.lon, d.lat],
                    getFillColor: {c_halo},
                    getRadius: {marker_radius * 2.5}, radiusMinPixels: 10
                }});
                
                const ScenegraphClass = deck.ScenegraphLayer || deck._ScenegraphLayer;
                
                const newVehicle = new ScenegraphClass({{
                    id: 'vehicle-layer', data: {car_json},
                    scenegraph: '{model_url}',
                    getPosition: d => [d.lon, d.lat],
                    getOrientation: d => [0, d.yaw + {camera_config['yaw_offset']}, 90],
                    sizeScale: {camera_config['car_size']}
                }});

                const static3DMarkers = new ScenegraphClass({{
                    id: 'waypoint-3d-markers', data: {waypoints_json},
                    scenegraph: '{marker_url}',
                    getPosition: d => [d.lon, d.lat],
                    getOrientation: [0, 0, 90],
                    sizeScale: 5
                }});
                
                window.deckgl.setProps({{ 
                    viewState: {{
                        longitude: {row["cam_lon"]},
                        latitude: {row["cam_lat"]},
                        zoom: {camera_config['follow_zoom']},
                        pitch: {camera_config['follow_pitch']},
                        bearing: {row["bearing"]},
                        transitionDuration: 0
                    }},
                    layers: [...staticLayers, newGlow, newTrail, newHalo, static3DMarkers, newVehicle] 
                }});
            }}
            """

            await page.evaluate(js_code)
            await page.wait_for_timeout(30)
            png_bytes = await page.screenshot()

            try:
                proc.stdin.write(png_bytes)
                await proc.stdin.drain()
            except Exception as e:
                print(f"\n[ERROR] FFmpeg crashed: {e}")
                break

        # ---------------------------------------------------------
        # FREEZE FRAME / POPUP LOGIC
        # ---------------------------------------------------------
        if freeze_frames > 0:
            print(
                f"  ... Arrived at waypoint! Freezing final frame for {freeze_frames} frames..."
            )
            if popup_url:
                js_popup = f"""
                const popupDiv = document.createElement('div');
                popupDiv.style.position = 'absolute';
                popupDiv.style.zIndex = '9999';
                
                if ('{image_display}' === 'fullscreen') {{
                    Object.assign(popupDiv.style, {{ top: '0', left: '0', width: '100vw', height: '100vh', backgroundColor: 'rgba(0, 0, 0, 0.85)', display: 'flex', justifyContent: 'center', alignItems: 'center' }});
                    const img = document.createElement('img');
                    img.src = '{popup_url}';
                    Object.assign(img.style, {{ maxWidth: '90%', maxHeight: '90%', objectFit: 'contain', borderRadius: '20px', boxShadow: '0 20px 50px rgba(0,0,0,0.5)' }});
                    popupDiv.appendChild(img);
                }} else {{
                    Object.assign(popupDiv.style, {{ top: '50px', right: '50px', width: '500px', backgroundColor: 'white', padding: '15px', borderRadius: '15px', boxShadow: '0 15px 35px rgba(0,0,0,0.4)' }});
                    const img = document.createElement('img');
                    img.src = '{popup_url}';
                    Object.assign(img.style, {{ width: '100%', borderRadius: '10px', display: 'block' }});
                    popupDiv.appendChild(img);
                }}
                document.body.appendChild(popupDiv);
                """
                await page.evaluate(js_popup)
                await page.wait_for_timeout(800)

            frozen_png = await page.screenshot()
            for _ in range(freeze_frames):
                try:
                    proc.stdin.write(frozen_png)
                    await proc.stdin.drain()
                except Exception:
                    break

        await page.close()
        await browser.close()

    proc.stdin.close()
    await proc.wait()
    print(f"\nSUCCESS! High-speed animation saved to: {output_filename}")


def record_headless_video(
    config_path: str,
    output_video_path: str = "final_reliable_map_animation.mp4",
    audio_durations: list = None,
    fps: int = None,
    speed_kmh: float = None,
):
    audio_durations = audio_durations or []
    html_dir = os.path.join(project_root, "frames")
    os.makedirs(html_dir, exist_ok=True)

    project_data = load_route_from_config(config_path)
    settings = project_data.get("settings", {})
    waypoints = project_data.get("waypoints", [])
    routing_cache = project_data.get("routing_cache", {})

    num_legs = len(routing_cache)
    if num_legs == 0:
        return []

    # Settings
    render_fps = max(
        10, min(60, int(fps if fps is not None else settings.get("fps", 30)))
    )
    target_speed = speed_kmh if speed_kmh is not None else settings.get("speed_kmh")

    print(f"Rendering at {render_fps} FPS")
    if target_speed:
        print(f"Using constant speed: {target_speed} km/h")

    # Display Styles
    line_color = settings.get("line_color", [0, 200, 255])
    history_color = settings.get("history_color", [255, 100, 100])
    line_thickness = settings.get("line_thickness", 10)
    marker_color = settings.get("marker_color", [0, 0, 255])
    marker_radius = settings.get("marker_radius", 10)

    # Server initialization
    server, port = start_local_server(str(project_root))

    # Static Marker Setup
    marker_filename = settings.get("marker_filename", "marker.glb")
    marker_url = f"http://127.0.0.1:{port}/assets/{urllib.parse.quote(marker_filename)}"
    waypoint_markers = [
        {"lon": float(wp.get("lng", wp.get("lon"))), "lat": float(wp["lat"])}
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
            print(f"\n--- Processing Leg {leg_idx + 1}/{num_legs} ---")

            # Model Selection
            leg_mode = (
                route_key.split("|")[-1].strip().lower()
                if "|" in route_key
                else "walking"
            )
            if leg_idx < len(waypoints):
                leg_mode = waypoints[leg_idx].get("routeMode", leg_mode).lower()

            if leg_mode == "walking":
                model_filename = "human.glb"
            elif leg_mode == "ferry":
                model_filename = "ferry.glb"
            elif leg_mode == "airplane":
                model_filename = "airplane.glb"
            else:
                model_filename = "car.glb"

            model_url = (
                f"http://127.0.0.1:{port}/assets/{urllib.parse.quote(model_filename)}"
            )

            marker_filename = "Sticker_08.glb"
            safe_marker = urllib.parse.quote(marker_filename)
            marker_url = f"http://127.0.0.1:{port}/assets/{safe_marker}"

            # Data Processing
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

            # Bearings & Camera Follow Points
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

            # Popups & Freeze Frames
            wp_idx, popup_url, freeze_frames, image_display = (
                leg_idx + 1,
                None,
                0,
                "pip",
            )
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

            # Initial Map State
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

            pdk.settings.custom_libraries = [
                {
                    "name": "MapboxGL",
                    "css_url": "https://api.mapbox.com/mapbox-gl-js/v2.15.0/mapbox-gl.css",
                }
            ]

            base_html_path = os.path.join(html_dir, f"base_leg_{leg_idx}.html")
            pdk.Deck(
                layers=base_layers,
                initial_view_state=view_state,
                map_provider="carto",
                map_style=pdk.map_styles.ROAD,
                views=[pdk.View(type="MapView", controller=False)],
            ).to_html(base_html_path)
            patch_pydeck_html(base_html_path)

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
                    history_color,
                    line_thickness,
                    marker_color,
                    marker_radius,
                    camera_config,
                    popup_url=popup_url,
                    freeze_frames=freeze_frames,
                    marker_url=marker_url,
                    waypoint_markers=waypoint_markers,
                    image_display=image_display,
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
