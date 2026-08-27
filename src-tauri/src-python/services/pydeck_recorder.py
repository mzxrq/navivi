import sys
from pathlib import Path
import asyncio
import os
import json
import glob
import pandas as pd
import numpy as np
import pydeck as pdk
from scipy.interpolate import interp1d

current_dir = Path(__file__).resolve().parent
project_root = current_dir if current_dir.name == "src-python" else current_dir.parent
sys.path.append(str(project_root))

from services.vdoeditor import VideoEditor


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


async def reliable_render_and_pipe(files, fps, output_filename):
    total_files = len(files)
    if total_files == 0:
        return

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
        str(fps),  # Forces precise output framerate
        "-pix_fmt",
        "yuv420p",
        output_filename,
    ]

    proc = await asyncio.create_subprocess_exec(
        *ffmpeg_cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
    )

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

        for i, html_file in enumerate(files):
            abs_path = f"file://{os.path.abspath(html_file)}"
            await page.goto(abs_path)

            if i == 0:
                print(
                    f"  ... Pre-loading map tiles on Frame 1 (Waiting up to 10s...)",
                    end="\r",
                    flush=True,
                )
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass

                await page.wait_for_timeout(500)
            else:
                await page.wait_for_timeout(50)

            png_bytes = await page.screenshot()

            try:
                proc.stdin.write(png_bytes)
                await proc.stdin.drain()
            except Exception as e:
                print(f"\n[ERROR] FFmpeg crashed or disconnected: {e}")
                break

            try:
                os.remove(html_file)
            except OSError:
                pass

            print(
                f"  ... Rendered & Piped {i + 1}/{total_files} frames",
                end="\r",
                flush=True,
            )

        await page.close()
        await browser.close()

    proc.stdin.close()
    await proc.wait()
    print(f"\nSUCCESS! Reliable video saved directly to: {output_filename}")


def record_headless_video(
    config_path: str,
    output_video_path: str = "final_reliable_map_animation.mp4",
    audio_durations: list = None,
):
    """Generates a split 2D top-down video for each waypoint leg synced with audio."""
    if audio_durations is None:
        audio_durations = []

    HTML_DIR = "frames"
    os.makedirs(HTML_DIR, exist_ok=True)

    project_data = load_route_from_config(config_path)
    settings = project_data.get("settings", {})
    FPS = settings.get("fps", 30)

    # Get routing cache to split by leg
    routing_cache = project_data.get("routing_cache", {})
    num_legs = len(routing_cache)
    if num_legs == 0:
        print("No route cache found to render.")
        return []

    LINE_COLOR = settings.get("line_color", [0, 200, 255])
    LINE_THICKNESS = settings.get("line_thickness", 10)
    MARKER_COLOR = settings.get("marker_color", [0, 0, 255])
    MARKER_RADIUS = settings.get("marker_radius", 10)

    output_paths = []
    accumulated_trail = []

    base_dir = os.path.dirname(output_video_path)
    base_name = os.path.splitext(os.path.basename(output_video_path))[0]
    ext = os.path.splitext(output_video_path)[1]

    # Process each waypoint-to-waypoint leg as its own video
    for leg_idx, (route_key, coords) in enumerate(routing_cache.items()):
        print(f"--- Processing Leg {leg_idx + 1}/{num_legs} ---")

        # Sync duration with Voiceover
        audio_duration = (
            audio_durations[leg_idx] if leg_idx < len(audio_durations) else 0.0
        )
        leg_duration = max(6.0, audio_duration + 1.0)

        # Extract coordinates
        raw_coords = [{"lat": c[0], "lon": c[1]} for c in coords]
        df_raw = pd.DataFrame(raw_coords)

        # Remove duplicates to prevent interpolation errors
        df_raw = df_raw.drop_duplicates()

        # ---------------------------------------------------------
        # NEW: CALCULATE STATIC CAMERA FOR THE ENTIRE LEG
        # ---------------------------------------------------------
        min_lon, max_lon = df_raw["lon"].min(), df_raw["lon"].max()
        min_lat, max_lat = df_raw["lat"].min(), df_raw["lat"].max()
        center_lon = (min_lon + max_lon) / 2.0
        center_lat = (min_lat + max_lat) / 2.0

        # Calculate optimal zoom to fit the route on screen
        max_diff = max(max_lon - min_lon, max_lat - min_lat)
        max_diff = max(max_diff, 0.0001)  # Prevent math errors
        zoom = 11.0 - np.log2(max_diff)
        zoom = min(17.5, max(13.0, zoom))  # Keep zoom within reasonable limits

        # Define the view state ONCE outside the loop so the camera stays static
        view_state = pdk.ViewState(
            longitude=center_lon,
            latitude=center_lat,
            zoom=zoom,
            pitch=0,
            bearing=0,
        )
        # ---------------------------------------------------------

        total_frames = int(leg_duration * FPS)
        df_raw["time_sec"] = np.linspace(0, leg_duration, num=len(df_raw))

        # fill_value="extrapolate" and bounds_error=False prevents scipy crashes on short leg arrays
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

        print(f"Generating {total_frames} PyDeck frames for leg {leg_idx + 1}...")
        for index, row in smooth_df.iterrows():
            current_lon = row["lon"]
            current_lat = row["lat"]
            frame_number = int(row["frame_id"])

            # 1. Smaller, crisp center dot
            marker_center = pdk.Layer(
                "ScatterplotLayer",
                data=[{"lon": current_lon, "lat": current_lat}],
                get_position="[lon, lat]",
                get_color=MARKER_COLOR,
                get_radius=MARKER_RADIUS * 0.8,
                radius_min_pixels=4,
                pickable=False,
            )

            # 2. Outer translucent "Halo" to make it look like a glowing GPS beacon
            marker_halo = pdk.Layer(
                "ScatterplotLayer",
                data=[{"lon": current_lon, "lat": current_lat}],
                get_position="[lon, lat]",
                get_color=MARKER_COLOR + [80],
                get_radius=MARKER_RADIUS * 2.5,
                radius_min_pixels=10,
                pickable=False,
            )

            # Combine previous legs' trails with the current leg's trail
            current_leg_trail = smooth_df.iloc[: index + 1][
                ["lon", "lat"]
            ].values.tolist()
            full_trail = accumulated_trail + current_leg_trail

            trail_layer = pdk.Layer(
                "PathLayer",
                data=[{"path": full_trail}],
                get_path="path",
                get_color=LINE_COLOR,
                width_scale=1,
                width_min_pixels=LINE_THICKNESS,
                pickable=False,
            )

            # Translucent glow beneath the main line
            trail_glow = pdk.Layer(
                "PathLayer",
                data=[{"path": full_trail}],
                get_path="path",
                get_color=LINE_COLOR + [90],
                width_scale=1,
                width_min_pixels=LINE_THICKNESS + 8,
                pickable=False,
            )

            r = pdk.Deck(
                layers=[trail_glow, trail_layer, marker_halo, marker_center],
                initial_view_state=view_state,
                map_provider="carto",
                map_style=pdk.map_styles.DARK,
            )

            filename = f"{HTML_DIR}/frame_{frame_number:04d}.html"
            r.to_html(filename)

        # Store this leg's full coordinates to persist the line on the map for the next video
        accumulated_trail.extend(df_raw[["lon", "lat"]].values.tolist())

        # Render this specific leg to MP4
        leg_output_path = os.path.join(base_dir, f"{base_name}_leg_{leg_idx:02d}{ext}")
        html_files = sorted(glob.glob(f"{HTML_DIR}/*.html"))
        asyncio.run(reliable_render_and_pipe(html_files, FPS, leg_output_path))

        output_paths.append(leg_output_path)

        # Clean up frames for the next iteration
        for f in html_files:
            try:
                os.remove(f)
            except OSError:
                pass

    return output_paths


if __name__ == "__main__":
    config_path = r"C:\Users\user1\Documents\Navivi\Projects\proj_2026_very_cool_tomogashima_islands\job_config.json"
    record_headless_video(config_path)
