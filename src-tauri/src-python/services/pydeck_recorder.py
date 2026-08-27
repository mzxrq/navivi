import sys
import math
from pathlib import Path
import asyncio
import os
import json
import glob
import pandas as pd
import numpy as np
import pydeck as pdk
from scipy.interpolate import interp1d

# --- IMPORTS FOR LOCAL SERVER ---
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
            pass  # Suppresses terminal spam from the server

    server = ThreadedHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


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


def load_route_from_config(config_path: str):
    """Helper function required by video_pipeline.py."""
    with open(config_path, "r", encoding="utf-8") as f:
        project_data = json.load(f)
    return project_data


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
        zoom=17,
        pitch=45,
        bearing=0,
    )
    return output_html_path


# ---------------------------------------------------------
# HIGH-SPEED JAVASCRIPT INJECTION RENDERER
# ---------------------------------------------------------
async def render_leg_animation(
    base_html_path,
    df,
    accumulated_trail,
    fps,
    output_filename,
    port,
    model_url,
    line_color,
    line_thickness,
    marker_color,
    marker_radius,
):
    """Opens a single HTML file and uses JavaScript injection to rapidly animate the route."""
    from playwright.async_api import async_playwright

    editor = VideoEditor()
    ffmpeg_path = editor.engine.resolve_binary()

    ffmpeg_cmd = [
        ffmpeg_path,
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
        *ffmpeg_cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
    )

    # Convert Python colors to JSON arrays for JavaScript
    c_trail = json.dumps(line_color)
    c_glow = json.dumps(line_color + [90])
    c_halo = json.dumps(marker_color + [80])

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--disable-web-security",
                "--ignore-gpu-blocklist",
                "--use-gl=angle",
                "--use-angle=gl",
            ],
        )

        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()

        # FIX: surface JS errors / console logs instead of letting them
        # vanish silently inside page.evaluate(). This is what was hiding
        # the ScenegraphLayer failure before.
        page.on("pageerror", lambda exc: print(f"  [PAGE ERROR] {exc}"))
        page.on(
            "console",
            lambda msg: print(f"  [console.{msg.type}] {msg.text}")
            if msg.type in ("error", "warning")
            else None,
        )

        # Load the base HTML via the local server
        rel_path = os.path.relpath(base_html_path, project_root).replace("\\", "/")
        page_url = f"http://127.0.0.1:{port}/{rel_path}"

        await page.goto(page_url)
        print("  ... Pre-loading map and 3D models (Fast load...)")
        try:
            await page.wait_for_load_state("load", timeout=2000)
        except Exception:
            pass
        await page.wait_for_timeout(
            2000
        )  # Extra buffer to let WebGL parse the .glb model

        # DIAGNOSTIC ONLY: @deck.gl/jupyter-widget (what pydeck's to_html()
        # actually loads) already re-exports @deck.gl/mesh-layers onto
        # globalThis.deck, so ScenegraphLayer should already be present.
        # We just check and warn -- do NOT inject another copy of
        # mesh-layers here. Doing so pulls in a second, incompatible
        # luma.gl runtime ("multiple VERSIONs detected") and breaks
        # everything instead of fixing it.
        has_scenegraph = await page.evaluate(
            "() => !!(window.deck && (deck.ScenegraphLayer || deck._ScenegraphLayer))"
        )
        if not has_scenegraph:
            print(
                "  [WARNING] deck.ScenegraphLayer is still not available on "
                "window.deck. Check your installed pydeck/deck.gl version -- "
                "do not inject a second mesh-layers bundle, versions must match."
            )

        total_frames = len(df)

        for index, row in df.iterrows():
            current_leg_trail = df.iloc[: index + 1][["lon", "lat"]].values.tolist()
            full_trail = accumulated_trail + current_leg_trail

            # Convert data to JSON for JS injection
            trail_json = json.dumps([{"path": full_trail}])
            car_json = json.dumps(
                [{"lon": row["lon"], "lat": row["lat"], "yaw": row["yaw"]}]
            )
            halo_json = json.dumps([{"lon": row["lon"], "lat": row["lat"]}])

            # -----------------------------------------------------
            # 3D CAR SETTINGS
            # -----------------------------------------------------
            CAR_SIZE = 5  # Adjust scale if needed
            YAW_OFFSET = 0  # Adjust rotation if needed
            FOLLOW_ZOOM = 15.5  # Zoom level when following the vehicle
            # -----------------------------------------------------

            # JavaScript code injected directly into browser memory
            js_code = f"""
            if (window.deckgl) {{
                const currentLayers = window.deckgl.props.layers || [];
                const staticLayers = currentLayers.filter(l => 
                    l.id !== 'vehicle-layer' && l.id !== 'halo-layer' && 
                    l.id !== 'trail-layer' && l.id !== 'trail-glow'
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
                    id: 'vehicle-layer', 
                    data: {car_json},
                    scenegraph: '{model_url}',
                    getPosition: d => [d.lon, d.lat],
                    getOrientation: d => [0, d.yaw + {YAW_OFFSET}, 90],
                    sizeScale: {CAR_SIZE}
                }});
                
                // DYNAMIC CAMERA TRACKING:
                // Update viewState on every frame so the camera follows the vehicle center
                window.deckgl.setProps({{ 
                    viewState: {{
                        longitude: {row['lon']},
                        latitude: {row['lat']},
                        zoom: {FOLLOW_ZOOM},
                        pitch: 60,
                        bearing: 30,
                        transitionDuration: 0
                    }},
                    layers: [...staticLayers, newGlow, newTrail, newHalo, newVehicle] 
                }});
            }}
            """

            # Fire JavaScript injection
            await page.evaluate(js_code)
            await page.wait_for_timeout(30)
            png_bytes = await page.screenshot()

            try:
                proc.stdin.write(png_bytes)
                await proc.stdin.drain()
            except Exception as e:
                print(f"\n[ERROR] FFmpeg crashed: {e}")
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
):
    if audio_durations is None:
        audio_durations = []

    HTML_DIR = os.path.join(project_root, "frames")
    os.makedirs(HTML_DIR, exist_ok=True)

    project_data = load_route_from_config(config_path)
    settings = project_data.get("settings", {})
    FPS = settings.get("fps", 30)

    routing_cache = project_data.get("routing_cache", {})
    num_legs = len(routing_cache)
    if num_legs == 0:
        return []

    LINE_COLOR = settings.get("line_color", [0, 200, 255])
    LINE_THICKNESS = settings.get("line_thickness", 10)
    MARKER_COLOR = settings.get("marker_color", [0, 0, 255])
    MARKER_RADIUS = settings.get("marker_radius", 10)

    # Start Background Server
    server, port = start_local_server(str(project_root))

    try:
        model_filename = "car.glb"
        safe_filename = urllib.parse.quote(model_filename)
        model_url = f"http://127.0.0.1:{port}/assets/{safe_filename}"

        output_paths = []
        accumulated_trail = []

        base_dir = os.path.dirname(output_video_path)
        base_name = os.path.splitext(os.path.basename(output_video_path))[0]
        ext = os.path.splitext(output_video_path)[1]

        for leg_idx, (route_key, coords) in enumerate(routing_cache.items()):
            print(f"\n--- Processing Leg {leg_idx + 1}/{num_legs} ---")

            audio_duration = (
                audio_durations[leg_idx] if leg_idx < len(audio_durations) else 0.0
            )
            leg_duration = max(6.0, audio_duration + 1.0)

            raw_coords = [{"lat": c[0], "lon": c[1]} for c in coords]
            df_raw = pd.DataFrame(raw_coords)
            df_raw = df_raw.drop_duplicates()

            min_lon, max_lon = df_raw["lon"].min(), df_raw["lon"].max()
            min_lat, max_lat = df_raw["lat"].min(), df_raw["lat"].max()
            center_lon = (min_lon + max_lon) / 2.0
            center_lat = (min_lat + max_lat) / 2.0

            max_diff = max(max_lon - min_lon, max_lat - min_lat)
            max_diff = max(max_diff, 0.0001)
            zoom = 11.0 - np.log2(max_diff)
            zoom = min(17.5, max(13.0, zoom)) - 0.5

            view_state = pdk.ViewState(
                longitude=center_lon,
                latitude=center_lat,
                zoom=zoom,
                pitch=60,
                bearing=30,
            )

            total_frames = int(leg_duration * FPS)
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
            smooth_df = pd.DataFrame(
                {
                    "frame_id": range(total_frames),
                    "lon": interp_lon(frame_times),
                    "lat": interp_lat(frame_times),
                }
            )

            # Pre-calculate Bearing (Yaw) for all frames
            yaws = []
            last_bearing = 0.0
            for index in range(len(smooth_df)):
                if index < len(smooth_df) - 1:
                    b = calculate_bearing(
                        smooth_df.iloc[index]["lon"],
                        smooth_df.iloc[index]["lat"],
                        smooth_df.iloc[index + 1]["lon"],
                        smooth_df.iloc[index + 1]["lat"],
                    )
                    last_bearing = b
                yaws.append(-last_bearing)
            smooth_df["yaw"] = yaws

            # -----------------------------------------------------
            # CREATE ONE BASE HTML FILE PER LEG
            # -----------------------------------------------------
            base_layers = []
            if accumulated_trail:
                base_layers = [
                    pdk.Layer(
                        "PathLayer",
                        id="static-glow",
                        data=[{"path": accumulated_trail}],
                        get_path="path",
                        get_color=LINE_COLOR + [90],
                        width_scale=1,
                        width_min_pixels=LINE_THICKNESS + 8,
                    ),
                    pdk.Layer(
                        "PathLayer",
                        id="static-trail",
                        data=[{"path": accumulated_trail}],
                        get_path="path",
                        get_color=LINE_COLOR,
                        width_scale=1,
                        width_min_pixels=LINE_THICKNESS,
                    ),
                ]

            pdk.settings.custom_libraries = [
                {
                    "name": "MapboxGL",
                    "css_url": "https://api.mapbox.com/mapbox-gl-js/v2.15.0/mapbox-gl.css",
                }
            ]

            r = pdk.Deck(
                layers=base_layers,
                initial_view_state=view_state,
                map_provider="carto",
                map_style=pdk.map_styles.DARK,
                # FIX 2 (camera not tracking): with controller=True (pydeck's
                # default), deck.gl's controller owns the view state and
                # fights our per-frame setProps({ viewState: ... }) unless we
                # also wire up onViewStateChange. We drive the camera
                # programmatically for recording, so just disable it here
                # via the View, not a Deck kwarg (Deck itself has no
                # `controller` argument).
                views=[pdk.View(type="MapView", controller=False)],
            )
            base_html_path = os.path.join(HTML_DIR, f"base_leg_{leg_idx}.html")
            r.to_html(base_html_path)

            # FIX 1: Expose the deck instance globally so our injected JS can
            # find it. Depending on your installed pydeck/deck.gl version,
            # to_html() generates ONE of these patterns:
            #   - `const deckgl = new DeckGL(...)`     (older pydeck)
            #   - `const deckInstance = createDeck(...)` (pydeck ~0.9.x / deck.gl 9)
            # We patch for both so this keeps working across versions.
            with open(base_html_path, "r", encoding="utf-8") as f:
                html_content = f.read()
            html_content = html_content.replace("const deckgl =", "window.deckgl =")
            html_content = html_content.replace("let deckgl =", "window.deckgl =")
            html_content = html_content.replace(
                "const deckInstance = createDeck(",
                "const deckInstance = window.deckgl = createDeck(",
            )

            # Bonus fix: pydeck's template loads mapbox-gl.js but never links
            # its CSS, which is what triggers the "missing CSS declarations
            # for Mapbox GL JS" console warning. Harmless, but cheap to fix.
            if (
                "mapbox-gl.js" in html_content
                and "mapbox-gl.css" not in html_content
            ):
                html_content = html_content.replace(
                    "</head>",
                    '<link rel="stylesheet" '
                    'href="https://api.tiles.mapbox.com/mapbox-gl-js/v1.13.0/'
                    'mapbox-gl.css" />\n</head>',
                    1,
                )

            with open(base_html_path, "w", encoding="utf-8") as f:
                f.write(html_content)

            # -----------------------------------------------------
            # RENDER FAST ANIMATION
            # -----------------------------------------------------
            leg_output_path = os.path.join(
                base_dir, f"{base_name}_leg_{leg_idx:02d}{ext}"
            )

            asyncio.run(
                render_leg_animation(
                    base_html_path,
                    smooth_df,
                    accumulated_trail,
                    FPS,
                    leg_output_path,
                    port,
                    model_url,
                    LINE_COLOR,
                    LINE_THICKNESS,
                    MARKER_COLOR,
                    MARKER_RADIUS,
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
    record_headless_video(config_path)