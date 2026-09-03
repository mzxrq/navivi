"""Core per-leg renderer: drives Playwright/deck.gl frame-by-frame into ffmpeg."""

import asyncio
import hashlib
import json
import os
from typing import Any, Dict, Optional

from .common import logger, project_root
from .popupsequence import _run_popup_freeze_sequence


async def render_leg_animation(
    base_html_path,
    df,
    accumulated_trail,
    fps,
    output_filename,
    port,
    model_url,
    active_color,
    line_thickness,
    marker_color,
    marker_radius,
    camera_config,
    popup_url=None,
    freeze_frames=0,
    marker_url=None,
    waypoint_markers=None,
    image_display="pip",
    intro_popup: Optional[Dict[str, Any]] = None,
    debug_dump_dir: Optional[str] = None,
):
    from playwright.async_api import async_playwright
    from services.vdoprocessing.vdoeditor import FFmpegEngine

    if not isinstance(active_color, list):
        active_color = [255, 0, 0]
    if not isinstance(marker_color, list):
        marker_color = [0, 0, 255]

    editor = FFmpegEngine()
    ffmpeg_cmd = [
        editor.resolve_binary(),
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

    c_trail = json.dumps(active_color)
    c_glow = json.dumps(active_color + [90])
    c_halo = json.dumps(marker_color + [80])

    waypoints_json = json.dumps(waypoint_markers or [])

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
        page.on("pageerror", lambda exc: logger.error(f"  [PAGE ERROR] {exc}"))

        # =========================================================
        # START OF MAPBOX TILE CACHING LOGIC
        # =========================================================
        TILE_CACHE_DIR = os.path.join(project_root, ".tile_cache")
        os.makedirs(TILE_CACHE_DIR, exist_ok=True)

        async def route_handler(route):
            url = route.request.url
            if "api.mapbox.com" in url or "tiles.mapbox.com" in url:
                url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()
                ext = ".pbf" if ".pbf" in url else (".png" if ".png" in url else ".bin")
                cache_file = os.path.join(TILE_CACHE_DIR, f"{url_hash}{ext}")

                if os.path.exists(cache_file):
                    await route.fulfill(path=cache_file)
                    return

                response = await route.fetch()
                body = await response.body()

                with open(cache_file, "wb") as f:
                    f.write(body)

                await route.fulfill(response=response, body=body)
            else:
                await route.continue_()

        await page.route("**/*", route_handler)
        # =========================================================
        # END OF MAPBOX TILE CACHING LOGIC
        # =========================================================

        rel_path = os.path.relpath(base_html_path, project_root).replace("\\", "/")
        await page.goto(f"http://127.0.0.1:{port}/{rel_path}")

        logger.info("  ... Pre-loading map and 3D models (Fast load...)")
        try:
            await page.wait_for_load_state("load", timeout=2000)
        except Exception:
            logger.warning("  ... Failed to wait for page load.")
        await page.wait_for_timeout(2000)

        await page.evaluate("""
            const mapCanvas = document.querySelector('.mapboxgl-canvas');
            if (mapCanvas) {
                mapCanvas.style.filter = 'brightness(0.82) contrast(1.3) saturate(3.5)';
            }
        """)

        if intro_popup and intro_popup.get("freeze_frames", 0) > 0:
            logger.info(
                "  ... Playing intro popup (display=%s) before driving frames.",
                intro_popup.get("image_display", "pip"),
            )
            await _run_popup_freeze_sequence(
                page=page,
                proc=proc,
                fps=fps,
                freeze_frames=intro_popup["freeze_frames"],
                popup_url=intro_popup.get("popup_url"),
                image_display=intro_popup.get("image_display", "pip"),
                debug_dump_dir=debug_dump_dir,
            )

        for index, row in df.iterrows():
            active_trail = df.iloc[: index + 1][["lon", "lat"]].values.tolist()

            if accumulated_trail:
                active_trail.insert(0, accumulated_trail[-1])

            trail_json = json.dumps([{"path": active_trail}])

            car_json = json.dumps(
                [{"lon": row["lon"], "lat": row["lat"], "yaw": row["yaw"]}]
            )
            halo_json = json.dumps([{"lon": row["lon"], "lat": row["lat"]}])

            js_code = f"""
            if (window.deckgl) {{
                const currentLayers = window.deckgl.props.layers || [];
                const staticLayers = currentLayers.filter(l =>
                    !['vehicle-layer', 'halo-layer', 'trail-layer', 'trail-glow', 'waypoint-3d-markers', 'waypoint-labels', 'waypoint-labels-shadow'].includes(l.id)
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

                const textShadows = new deck.TextLayer({{
                    id: 'waypoint-labels-shadow',
                    data: {waypoints_json},
                    getPosition: d => [d.lon, d.lat, 25],
                    getText: d => d.name,
                    getSize: 24,
                    getColor: [0, 0, 0, 255],
                    fontFamily: '"Noto Sans JP", sans-serif',
                    fontWeight: 'bold',
                    characterSet: 'auto',
                    getAlignmentBaseline: 'bottom',
                    getPixelOffset: [2, -28]
                }});

                const textLabels = new deck.TextLayer({{
                    id: 'waypoint-labels',
                    data: {waypoints_json},
                    getPosition: d => [d.lon, d.lat, 25],
                    getText: d => d.name,
                    getSize: 24,
                    getColor: [255, 255, 255, 255],
                    fontFamily: '"Noto Sans JP", sans-serif',
                    fontWeight: 'bold',
                    characterSet: 'auto',
                    getAlignmentBaseline: 'bottom',
                    getPixelOffset: [0, -30]
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
                    layers: [...staticLayers, newGlow, newTrail, newHalo, static3DMarkers, textShadows, textLabels, newVehicle]
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
                logger.error(f"\n[ERROR] FFmpeg crashed: {e}")
                break

        # ---------------------------------------------------------
        # END-OF-LEG ARRIVAL FREEZE / POPUP
        # ---------------------------------------------------------
        if freeze_frames > 0:
            logger.info(
                f"  ... Arrived at waypoint! Freezing final frame for {freeze_frames} frames..."
            )
            if popup_url:
                await _run_popup_freeze_sequence(
                    page=page,
                    proc=proc,
                    fps=fps,
                    freeze_frames=freeze_frames,
                    popup_url=popup_url,
                    image_display=image_display,
                    debug_dump_dir=debug_dump_dir,
                )
            else:
                frozen_png = await page.screenshot()
                for _ in range(freeze_frames):
                    proc.stdin.write(frozen_png)
                    await proc.stdin.drain()

    await asyncio.sleep(0.2)
    logger.info(f"\nSUCCESS! High-speed animation saved to: {output_filename}")
