"""Core per-leg renderer: drives Playwright/deck.gl frame-by-frame into ffmpeg."""

import asyncio
import hashlib
import json
import math
import os
from typing import Any, Dict, Optional

from .common import logger
from .coinprop import coin_layer_expr, play_coin_collect, play_intro_coin_hold, setup_coin_mesh
from .popupsequence import _run_popup_freeze_sequence, _wait_for_paint


async def render_leg_animation(
    base_html_path,
    df,
    accumulated_trail,
    fps,
    output_filename,
    port,
    config_dir,
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
    coin_image_url: Optional[str] = None,
    coin_target: Optional[Dict[str, float]] = None,
    mapbox_key: Optional[str] = None,
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
        # Cached under the PROJECT's own folder (config_dir), same reasoning
        # as html_dir in recorder.py -- keeps render debris out of the app's
        # source tree and next to the project it belongs to.
        TILE_CACHE_DIR = os.path.join(config_dir, "cache")
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
                # Only cache successful responses -- a failed request (a
                # tile that legitimately doesn't exist yet, a transient
                # network error, a bad URL from an earlier bug) would
                # otherwise get written to disk and then replayed forever
                # on every future render, even after whatever caused the
                # failure is fixed in code.
                if not response.ok:
                    await route.fulfill(response=response)
                    return

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

        # base_html_path lives under config_dir (the project's own folder),
        # which is what the local server serves at '/' -- see
        # recorder.start_local_server / httpserver.start_local_server.
        rel_path = os.path.relpath(base_html_path, config_dir).replace("\\", "/")
        await page.goto(f"http://127.0.0.1:{port}/{rel_path}")

        logger.info("  ... Pre-loading map and 3D models (Fast load...)")
        try:
            await page.wait_for_load_state("load", timeout=2000)
        except Exception:
            logger.warning("  ... Failed to wait for page load.")
        # 3D vehicle/marker models (.glb) load asynchronously over the
        # network after this point; give them real time to land before the
        # first frame is captured, or they show up missing on early frames.
        await page.wait_for_timeout(2500)

        await page.evaluate("""
            const mapCanvas = document.querySelector('.mapboxgl-canvas');
            if (mapCanvas) {
                mapCanvas.style.filter = 'brightness(0.82) contrast(1.3) saturate(1)';
            }
        """)

        if mapbox_key:
            # Extruded 3D buildings from Mapbox's own building footprint
            # vector tiles (mapbox-streets-v8's 'building' source-layer,
            # which carries a real `height` in meters per building) --
            # verified live over a dense city area before wiring this in.
            # Uses raw deck.gl MVTLayer construction (not pydeck's
            # declarative pdk.Layer) because `dataTransform` is a JS
            # function, which pydeck's JSON-based layer serialization can't
            # carry through faithfully.
            await page.evaluate(
                """([token]) => {
                    if (!window.deckgl) return;
                    const buildingsLayer = new deck.MVTLayer({
                        id: 'buildings-3d',
                        data: `https://api.mapbox.com/v4/mapbox.mapbox-streets-v8/{z}/{x}/{y}.vector.pbf?access_token=${token}`,
                        minZoom: 13,
                        maxZoom: 20,
                        binary: false,
                        dataTransform: (data) => data.filter(f => f.properties && f.properties.layerName === 'building'),
                        extruded: true,
                        filled: true,
                        stroked: false,
                        getElevation: f => (f.properties && f.properties.height) || 0,
                        getFillColor: [220, 205, 190, 255],
                        material: true,
                    });
                    const current = window.deckgl.props.layers || [];
                    window.deckgl.setProps({ layers: [...current, buildingsLayer] });
                }""",
                [mapbox_key],
            )

        coin_mesh_ready = False
        if coin_image_url and coin_target:
            await setup_coin_mesh(page)
            coin_mesh_ready = True

        intro_frames = intro_popup.get("freeze_frames", 0) if intro_popup else 0
        if intro_frames > 0:
            intro_url = intro_popup.get("popup_url")
            intro_coin_target = intro_popup.get("coin_target")

            if intro_coin_target:
                # Freeze/reveal happens AT the waypoint (same chase-cam
                # framing driving uses), not on the wide per-leg overview
                # the base HTML loads with -- the camera hasn't moved to
                # the driving position yet at this point in the timeline.
                intro_bearing = float(df.iloc[0]["bearing"]) if len(df) else 0.0
                await page.evaluate(
                    """([lon, lat, zoom, pitch, bearing]) => {
                        if (window.deckgl) {
                            window.deckgl.setProps({
                                viewState: { longitude: lon, latitude: lat, zoom, pitch, bearing, transitionDuration: 0 }
                            });
                        }
                    }""",
                    [
                        intro_coin_target["lon"],
                        intro_coin_target["lat"],
                        camera_config["follow_zoom"],
                        camera_config["follow_pitch"],
                        intro_bearing,
                    ],
                )
                await _wait_for_paint(page)

            if intro_url and intro_coin_target:
                # No screen-space popup box here -- the intro is the same
                # in-world spinning coin used at every other waypoint's
                # arrival: the route "opens" at its first waypoint (marker
                # + spinning photo), then starts driving.
                logger.info("  ... Showing start waypoint + spinning photo coin before driving.")
                if not coin_mesh_ready:
                    await setup_coin_mesh(page)
                    coin_mesh_ready = True
                await play_intro_coin_hold(
                    page,
                    proc,
                    fps,
                    intro_coin_target["lon"],
                    intro_coin_target["lat"],
                    intro_url,
                    intro_frames,
                    marker_url,
                    waypoints_json,
                    _wait_for_paint,
                )
            else:
                frozen_png = await page.screenshot()
                for _ in range(intro_frames):
                    proc.stdin.write(frozen_png)
                    await proc.stdin.drain()

        # The coin spins in place at the destination for the whole drive-in
        # (~1 rotation every 1.4s), so it reads as "a coin waiting there"
        # rather than something that only appears on arrival.
        coin_deg_per_frame = 360.0 / max(1, fps * 1.4)
        last_coin_spin = 0.0

        for index, row in df.iterrows():
            active_trail = df.iloc[: index + 1][["lon", "lat"]].values.tolist()

            if accumulated_trail:
                active_trail.insert(0, accumulated_trail[-1])

            trail_json = json.dumps([{"path": active_trail}])

            car_json = json.dumps(
                [{"lon": row["lon"], "lat": row["lat"], "yaw": row["yaw"]}]
            )
            halo_json = json.dumps([{"lon": row["lon"], "lat": row["lat"]}])

            if coin_image_url and coin_target:
                last_coin_spin = (index * coin_deg_per_frame) % 360.0
                coin_bob = 3.0 + 1.2 * math.sin(index * 0.12)
                coin_expr = coin_layer_expr(
                    coin_target["lon"],
                    coin_target["lat"],
                    coin_image_url,
                    last_coin_spin,
                    coin_bob,
                )
            else:
                coin_expr = "null"

            js_code = f"""
            if (window.deckgl) {{
                const currentLayers = window.deckgl.props.layers || [];
                const staticLayers = currentLayers.filter(l =>
                    !['vehicle-layer', 'halo-layer', 'trail-layer', 'trail-glow', 'waypoint-3d-markers', 'waypoint-labels', 'waypoint-labels-shadow', 'popup-coin'].includes(l.id)
                );

                const coinLayer = {coin_expr};

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
                    getPosition: d => [d.lon, d.lat, 12],
                    getOrientation: [0, 0, 90],
                    getColor: [46, 160, 67, 255],
                    sizeScale: 8,
                    // Always draws above the coin regardless of its actual
                    // 3D depth (the coin grows well past the marker's own
                    // height during its collect burst) -- combined with
                    // being added to the layers array AFTER coinLayer
                    // below, this guarantees the pin is never hidden behind
                    // the photo. Verified in isolation: no self-occlusion
                    // artifacts on this model with depth testing off.
                    parameters: {{ depthTest: false }}
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
                    layers: [...staticLayers, newGlow, newTrail, newHalo, newVehicle, ...(coinLayer ? [coinLayer] : []), static3DMarkers, textShadows, textLabels]
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
        # END-OF-LEG ARRIVAL: COLLECT THE COIN, THEN FREEZE / POPUP
        # ---------------------------------------------------------
        if coin_image_url and coin_target:
            logger.info("  ... Arrived! Collecting waypoint photo coin...")
            await play_coin_collect(
                page,
                proc,
                fps,
                coin_target["lon"],
                coin_target["lat"],
                coin_image_url,
                last_coin_spin,
                _wait_for_paint,
            )

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
