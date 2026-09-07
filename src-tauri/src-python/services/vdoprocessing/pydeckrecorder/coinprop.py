"""In-world "Mario coin" popup prop.

Instead of a screen-space HTML overlay, the waypoint's arrival photo is
rendered as a spinning textured plane standing at the destination's actual
lon/lat in the deck.gl scene -- a prop the route drives up to and collects
(burst + fade), the same way a coin sits in the level and gets grabbed on
contact. The screen-space PIP/fullscreen reveal in popupsequence.py is kept
for the true final destination only; every other waypoint uses this instead.
"""

import json
import math

# Vertical quad (2 triangles, 6 non-indexed vertices) authored in meters,
# directly in deck.gl's Z-up local space. Because we author the geometry
# ourselves, getOrientation's yaw alone spins it around its vertical axis
# like a coin -- unlike the GLB vehicle/marker models, which need an extra
# 90deg roll to stand upright since their own "up" axis doesn't match.
_COIN_MESH_SETUP_JS = """
() => {
    const W = 22, H = 22;
    const positions = new Float32Array([
        0, -W / 2, 0,   0, W / 2, 0,   0, W / 2, H,
        0, -W / 2, 0,   0, W / 2, H,   0, -W / 2, H
    ]);
    const texcoords = new Float32Array([
        0, 1,   1, 1,   1, 0,
        0, 1,   1, 0,   0, 0
    ]);
    const normals = new Float32Array([
        1, 0, 0,  1, 0, 0,  1, 0, 0,
        1, 0, 0,  1, 0, 0,  1, 0, 0
    ]);
    window.__coinMesh = {
        attributes: {
            POSITION: { value: positions, size: 3 },
            NORMAL: { value: normals, size: 3 },
            TEXCOORD_0: { value: texcoords, size: 2 }
        }
    };
}
"""


async def setup_coin_mesh(page) -> None:
    """Defines the coin's plane geometry once per leg (the page reloads a
    fresh base_leg_N.html every leg, so window.__coinMesh doesn't survive)."""
    await page.evaluate(_COIN_MESH_SETUP_JS)


def coin_layer_expr(
    lon: float,
    lat: float,
    image_url: str,
    spin_deg: float,
    bob: float,
    scale: float = 1.0,
    opacity: float = 1.0,
) -> str:
    """A JS expression (not a statement) building the 'popup-coin'
    SimpleMeshLayer for one frame, or null if the mesh isn't set up yet."""
    return f"""(window.__coinMesh ? new deck.SimpleMeshLayer({{
        id: 'popup-coin',
        data: [{{ position: [{lon}, {lat}, {bob}] }}],
        mesh: window.__coinMesh,
        texture: {json.dumps(image_url)},
        getPosition: d => d.position,
        getOrientation: [0, {spin_deg}, 0],
        sizeScale: {scale},
        opacity: {opacity}
    }}) : null)"""


async def play_coin_collect(
    page,
    proc,
    fps: int,
    lon: float,
    lat: float,
    image_url: str,
    spin_deg_start: float,
    wait_for_paint,
) -> None:
    """Bursts the in-world coin: an accelerating spin + scale-up + fade-out,
    like Mario collecting a coin. Only the 'popup-coin' layer is touched --
    every other layer (trail/vehicle/markers) is left exactly as the last
    driving frame set it, by filtering+replacing on deck.gl's own current
    layers instead of rebuilding the whole scene from scratch.
    """
    burst_frames = max(1, int(fps * 0.5))
    for i in range(burst_frames):
        progress = i / float(burst_frames - 1) if burst_frames > 1 else 1.0
        ease = 1 - (1 - progress) ** 3
        scale = 1.0 + ease * 1.6
        alpha = max(0.0, 1.0 - progress**1.5)
        spin = (spin_deg_start + progress * 720.0) % 360.0
        bob = 3.0 + ease * 7.0

        coin_expr = coin_layer_expr(lon, lat, image_url, spin, bob, scale, alpha)
        js_code = f"""
        () => {{
            if (!window.deckgl) return;
            const current = window.deckgl.props.layers || [];
            // The marker (waypoint-3d-markers/labels) must stay drawn AFTER
            // the coin, or it loses its "always on top" guarantee during
            // the burst -- simply appending the coin last (as the id-filter
            // alone would) would put it back over the marker.
            const isMarkerLayer = l => ['waypoint-3d-markers', 'waypoint-labels', 'waypoint-labels-shadow'].includes(l.id);
            const others = current.filter(l => l.id !== 'popup-coin' && !isMarkerLayer(l));
            const markerLayers = current.filter(isMarkerLayer);
            const coin = {coin_expr};
            window.deckgl.setProps({{ layers: [...others, ...(coin ? [coin] : []), ...markerLayers] }});
        }}
        """
        await page.evaluate(js_code)
        await wait_for_paint(page)
        png_bytes = await page.screenshot()
        proc.stdin.write(png_bytes)
        await proc.stdin.drain()

    # Fully remove the coin so it doesn't linger into the freeze/pause that follows.
    await page.evaluate(
        """() => {
            if (!window.deckgl) return;
            const current = window.deckgl.props.layers || [];
            window.deckgl.setProps({ layers: current.filter(l => l.id !== 'popup-coin') });
        }"""
    )


async def play_intro_coin_hold(
    page,
    proc,
    fps: int,
    lon: float,
    lat: float,
    image_url: str,
    hold_frames: int,
    marker_url: str,
    waypoints_json: str,
    wait_for_paint,
    deg_per_sec: float = 220.0,
) -> None:
    """Opens the very first leg: shows the waypoint markers/labels (not yet
    on screen at this point -- the driving loop that normally adds them
    hasn't started) plus a spinning photo coin at the start waypoint, held
    for hold_frames, before driving begins. No screen-space popup box --
    this is the same in-world coin used at every other waypoint's arrival,
    just played as an intro instead of a collect.

    Unlike play_coin_collect, the marker/label layers have to be built here
    (rather than filtered from deck.gl's current layers) since nothing has
    populated the scene yet on this first frame.
    """
    if hold_frames <= 0:
        return

    deg = 0.0
    for i in range(hold_frames):
        deg = (i * deg_per_sec / fps) % 360.0
        bob = 3.0 + 1.2 * math.sin(i * 0.12)
        coin_expr = coin_layer_expr(lon, lat, image_url, deg, bob)
        js_code = f"""
        () => {{
            if (!window.deckgl) return;
            const currentLayers = window.deckgl.props.layers || [];
            const staticLayers = currentLayers.filter(l =>
                !['waypoint-3d-markers', 'waypoint-labels', 'waypoint-labels-shadow', 'popup-coin'].includes(l.id)
            );
            const ScenegraphClass = deck.ScenegraphLayer || deck._ScenegraphLayer;
            const static3DMarkers = new ScenegraphClass({{
                id: 'waypoint-3d-markers', data: {waypoints_json},
                scenegraph: {json.dumps(marker_url)},
                getPosition: d => [d.lon, d.lat, 12],
                getOrientation: [0, 0, 90],
                getColor: [46, 160, 67, 255],
                sizeScale: 8,
                // Always draws above the coin regardless of actual 3D
                // depth -- combined with being added to the layers array
                // AFTER the coin below, this guarantees the pin is never
                // hidden behind the photo.
                parameters: {{ depthTest: false }}
            }});
            const textShadows = new deck.TextLayer({{
                id: 'waypoint-labels-shadow', data: {waypoints_json},
                getPosition: d => [d.lon, d.lat, 25], getText: d => d.name, getSize: 24,
                getColor: [0, 0, 0, 255], fontFamily: '"Noto Sans JP", sans-serif',
                fontWeight: 'bold', characterSet: 'auto',
                getAlignmentBaseline: 'bottom', getPixelOffset: [2, -28]
            }});
            const textLabels = new deck.TextLayer({{
                id: 'waypoint-labels', data: {waypoints_json},
                getPosition: d => [d.lon, d.lat, 25], getText: d => d.name, getSize: 24,
                getColor: [255, 255, 255, 255], fontFamily: '"Noto Sans JP", sans-serif',
                fontWeight: 'bold', characterSet: 'auto',
                getAlignmentBaseline: 'bottom', getPixelOffset: [0, -30]
            }});
            const coin = {coin_expr};
            window.deckgl.setProps({{
                layers: [...staticLayers, ...(coin ? [coin] : []), static3DMarkers, textShadows, textLabels]
            }});
        }}
        """
        await page.evaluate(js_code)
        await wait_for_paint(page)
        png_bytes = await page.screenshot()
        proc.stdin.write(png_bytes)
        await proc.stdin.drain()

    # Drop the coin before the drive starts; the markers stay (the driving
    # loop redraws them itself every frame under the same layer ids).
    await page.evaluate(
        """() => {
            if (!window.deckgl) return;
            const current = window.deckgl.props.layers || [];
            window.deckgl.setProps({ layers: current.filter(l => l.id !== 'popup-coin') });
        }"""
    )
