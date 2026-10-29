"""GeoJsonLayer-driven walking leg rendering: the RESIDENTIAL/leg clip (chase
camera, turn-by-turn HUD banner + distance/time card, stop-by photo moments).

A self-contained, plain-argument function — no RouteAnimator/job_config
coupling. Its pieces live beside it: pin_icons.py (pins and labels),
leg_camera.py (framing/projection), leg_hud.py (HUD), stopby_pause.py (a
stop-by's photo moment); the 3D overview is overview_pydeck.py. See
recorder.py/renderer.py for the sibling DRIVING-mode (vehicle scenegraph)
pipeline this deliberately does not touch.
"""

from __future__ import annotations

import asyncio
import base64
import bisect
import json
import math
import os
import shutil
import tempfile
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd
import pydeck as pdk

from services import tuning, video_text
from services.logger.progress import tracker
from services.vdoprocessing.cliptiming import write_audio_offset

from .common import MAPBOX_API_KEY, logger
from .geomath import cumulative_distance_km, haversine_km
from .httpserver import start_local_server
from .popupsequence import _wait_for_paint
from .recorder import _route_gradient_feature, _route_linestring_feature
from .frame_sink import FrameSink
from .elevation import leg_segment_colors, profile_card, quantize, usable_heights
from .routedata import interpolate_route_data, patch_pydeck_html
from .leg_camera import (
    _LEG_TOP_MARGIN_PX, _ease_in_out_cubic, _fit_view_for_path, _framed_points, _leg_bottom_margin_px,
    _project_lonlat_to_px,
)
from .leg_hud import (
    _COMPASS_SVG, _DEFAULT_MODE_HUD, _MODE_HUD, _css_rgba, _heading_label, _hud_css, _hud_text, _localized_hud,
    _remaining_minutes, _walk_headings,
)
from .pin_icons import (
    _DEST_PIN_URL, _START_PIN_URL, _TEARDROP_PIN_H, _TEARDROP_PIN_W, _label_pill_layer, _landmark_layers,
    _leg_pin_url,
)
from .stopby_pause import _FRAME_SHOT, _play_stopby_photo_pause


def _segment_plan(df_raw, leg_dist_km, landmarks, total_seconds):
    """[(last raw point index, seconds)] for a leg cut at connected stop-bys, from
    each landmark's own `walk_seconds` (the last piece gets what is left of
    `total_seconds`). None when the leg has no cut, a landmark has no time, or
    the stop-bys don't come in route order - the leg then walks at one speed."""
    if not landmarks or total_seconds is None:
        return None
    stops = [
        lm for lm in landmarks
        if lm.get("connect_to_route") and lm.get("popup_image") and lm.get("pops_after") is None
        and lm.get("lat") is not None and lm.get("lon") is not None
    ]
    if not stops or any(lm.get("walk_seconds") is None for lm in stops):
        return None
    plan, prev_idx, used = [], 0, 0.0
    for lm in stops:
        sq = (df_raw["lat"] - lm["lat"]) ** 2 + (df_raw["lon"] - lm["lon"]) ** 2
        idx = int(sq.idxmin())
        if idx <= prev_idx:
            return None
        plan.append((idx, float(lm["walk_seconds"])))
        prev_idx, used = idx, used + float(lm["walk_seconds"])
    last = max(1.0, float(total_seconds) - used)
    plan.append((len(df_raw) - 1, last))
    return plan


def render_residential_leg_pydeck(
    leg_latlon: List[Tuple[float, float]],
    dest_label: str,
    output_path: str,
    mode: str = "walking",
    fps: int = 24,
    travel_speed_kmh: Optional[float] = None,
    target_duration_seconds: Optional[float] = None,
    output_size: Tuple[int, int] = (1920, 1080),
    mapbox_key: Optional[str] = None,
    map_style: str = "mapbox://styles/mapbox/outdoors-v12",
    follow_zoom: float = 19.0,
    follow_pitch: float = 0.0,
    arrive_threshold_m: float = 60.0,
    line_thickness: int = 8,
    walker_color: List[int] = None,
    upcoming_color: List[int] = None,
    landmarks: Optional[List[Dict]] = None,
    arrival_hold_seconds: float = 2.0,
    route_chain: Optional[List[str]] = None,
    topdown_transition_seconds: float = 1.6,
    topdown_zoom_delta: float = 1.0,
    dest_popup_image: Optional[str] = None,
    dest_popup_freeze_seconds: Optional[float] = None,
    start_popup_image: Optional[str] = None,
    start_popup_freeze_seconds: Optional[float] = None,
    dest_popup_narration_seconds: Optional[float] = None,
    start_popup_narration_seconds: Optional[float] = None,
    start_cue_seconds: Optional[float] = None,
    arrival_photo_hold_seconds: Optional[float] = None,
    arrival_wait_seconds: Optional[float] = None,
    dest_image_display: str = "cover",
    start_pin: Optional[Dict] = None,
    dest_pin: Optional[Dict] = None,
    hud_card_png: Optional[Callable[[float, float, bool, float], bytes]] = None,
    theme: Optional[str] = None,
    bottom_reserve_px: float = 0.0,
    arrival_slow_seconds: float = 0.0,
    leg_elevations: Optional[List[float]] = None,
) -> List[str]:
    """Renders one leg as a straight-down, locked-camera video with a live
    turn-by-turn HUD (destination banner + time/distance card) -- the
    GeoJsonLayer-route analogue of pydeckrecorder.recorder's driving-mode
    leg rendering, but with no vehicle scenegraph, and with actual
    on-screen HUD chrome recorder.py/renderer.py's driving path doesn't
    have. Unlike a chase camera, the view never re-centers on the walker:
    after the intro's zoom-in (see `topdown_transition_seconds` below) it
    stays fixed on a framing that fits the leg's whole path, and only the
    walker dot/trail/destination pin move within that fixed frame.

    `leg_latlon`: [(lat, lon), ...] this leg's raw route points -- drawn
    two-tone: `walker_color` (default blue) behind the walker, growing as
    the leg progresses, and `upcoming_color` (default grey, a neutral
    "guide line" for the not-yet-walked path ahead) for the remainder.

    `landmarks`: optional [{"lat", "lon", ("label"), ("connect_to_route"),
    ("popup_image"), ("freeze_seconds")}, ...] -- unnumbered brown markers
    for points the route passes near without stopping (e.g. a leg's
    merged-in stop-by waypoints), drawn statically. One with
    `connect_to_route` True AND a `popup_image` gets MORE than just the
    static dot, though -- mirroring the overview's own rule that a
    connectToRoute stop-by acts like a real waypoint rather than a silent
    pass-through pin: the moment the walker reaches it, the walk pauses,
    its own photo fades in fullscreen, holds for its (floored/capped)
    `freeze_seconds`, then shrinks back down and fades out right onto that
    marker's own on-screen position before the walk continues. One with a
    `popup_image` but `connect_to_route` False/absent (the route only
    passes NEAR it) gets a lighter touch instead: a small pip card pops in
    beside its marker as the walker nears it, holds, and fades back out --
    no fullscreen growth, no leg cut, since the walk never actually visits
    it (see `_play_stopby_photo_pause`'s `pip_only` path).

    `arrival_hold_seconds`: after the chase camera finishes traveling the
    leg, holds the final (arrived) frame on screen for this many extra
    seconds before the clip ends -- a plain freeze-frame so a viewer
    actually has time to register the destination and its marker rather
    than the clip cutting away the instant the walker arrives.

    `route_chain`: optional ["友ヶ島", "深山ノ鼻", "加太", ...] -- this leg's
    own place names in travel order (start through destination, including
    any stop-bys in between). Shown as a static breadcrumb pill in the
    top-left corner (e.g. "友ヶ島 → 深山ノ鼻 → 加太"), separate from the
    top-right destination banner, so a viewer can place this leg within
    the wider trip at a glance. Omit to leave the corner empty.

    `topdown_transition_seconds`/`topdown_zoom_delta`: each leg opens on a
    big establishing shot -- north-up bearing, zoomed out `topdown_zoom_delta`
    levels below the leg's own locked/fit-to-path zoom, centered exactly on
    the walker's starting marker -- then eases zoom/position in a bit, over
    `topdown_transition_seconds`, into that locked framing as the walker
    starts moving; the camera then stays there, unmoving, for the rest of
    the leg. It closes (after `arrival_hold_seconds`) with the reverse:
    the locked view eases back out to the same big establishing framing,
    centered on the destination marker. Since each leg is its own clip,
    cutting one leg's outro straight into the next leg's intro reads as the
    camera changing focus to a new stretch of road -- matching the
    reference video's tile-to-tile refocus beat between legs. Set
    `topdown_transition_seconds` to 0 to disable and render the leg at a
    constant locked view from the first frame, as before.

    `dest_popup_image`: this leg's destination waypoint's own popup photo
    (route2vdo.py passes it from render_step.py's `res_data["popups"][-1]`).
    When set, the clip OPENS on this photo full-bleed (covering the whole
    frame), then shrinks down to the normal small popup-card size and
    freezes there for `dest_popup_freeze_seconds` (floored/capped the same
    way every other popup's freeze_seconds is -- see tuning.
    POPUP_MIN_DISPLAY_SECONDS/POPUP_FREEZE_SECONDS_MAX) with the map's own
    marker + grey route guideline already visible behind/around the card --
    a "here's where you're headed" preview before the card fades and the
    top-down establishing shot (see `topdown_transition_seconds` above)
    zooms in toward the start marker and the walk begins. Skipped entirely
    (clip opens straight on the establishing shot) when there's no photo.

    `start_popup_image`: only ever set on the trip's very first leg (its
    departure is the trip's own true first waypoint, which is never
    anyone's destination and so never otherwise gets a residential popup
    moment — every other leg's departure IS the previous leg's destination,
    already previewed there via `dest_popup_image`). Gets the exact same
    fullscreen -> shrink-to-leader-card treatment as `dest_popup_image`
    (see `_play_leg_photo_card`, the shared implementation) and plays
    FIRST, right after the warm-up frame, before the destination preview.
    Skipped entirely when there's no photo.

    `dest_label`: the destination waypoint's display label for the banner.
    `mode`: one of _MODE_HUD's keys ("walking", "ferry", "driving",
    "airplane") -- drives the HUD's icon/label/banner-suffix AND (when
    `travel_speed_kmh` is left as None) the default pacing speed used to
    time the leg. An unrecognized mode falls back to walking's HUD chrome
    but keeps whatever `travel_speed_kmh` was actually passed.

    `target_duration_seconds`: overrides the VIDEO's own length (how long
    the camera actually takes to travel the leg), decoupling it from
    `travel_speed_kmh`/`total_leg_km` -- real routes range from a few
    meters to several kilometers per leg, and playing every one of them
    out at literal real-world walking/ferry pace would make some clips
    seconds long and others HOURS long. `travel_speed_kmh` still drives
    the HUD's own displayed remaining-time estimate (the real-world
    "X 分" a viewer would actually take), which is deliberately left
    independent of the animation's compressed playback length. Leave this
    None to fall back to real-world pacing (fine for a short/standalone
    leg, e.g. in an isolated test) -- route2vdo.py's real pipeline always
    passes this from the leg's own already-computed target duration.

    `dest_popup_narration_seconds`/`start_popup_narration_seconds`: the
    narration length of the destination/departure waypoint, passed by
    route2vdo.py. Accepted for its callers but not used yet: the photo holds
    do not wait for narration (leg_pieces.py pads the clip's tail instead).

    `start_cue_seconds`: when the leg's narration carries a {start} cue, the
    second of the narration at which the walker should START moving. The
    narration then plays from the clip's first frame: if the opening (warm-up,
    photos, intro zoom) ends before that, its last frame is held until the
    cue; if it ends after, the narration is delayed by the difference. Left
    None, the narration is delayed by the whole opening so the voice starts
    with the walk. Either way the delay is written next to the clip as a
    `.timing.json` (see services/vdoprocessing/cliptiming.py) for the
    subtitle burn and final export to apply. Only legs that are not cut by a
    connected stop-by get one.

    `arrival_photo_hold_seconds`: how long the at-arrival photo stays fullscreen
    AFTER it has finished growing. The clip's last frames are these, so the
    caller can dissolve them into the attraction video that follows: the photo
    grows to fullscreen first, then fades - the fade never overlaps the grow.
    Defaults to tuning.RESIDENTIAL_ARRIVAL_POPUP_HOLD_SECONDS (0).

    `arrival_wait_seconds`: the walker got to the destination before its
    narration ended. It stays put on the arrived map for this long (the voice
    finishing), and only then does the at-arrival photo start to grow. Left
    None, the old fixed pauses apply (tuning.RESIDENTIAL_ARRIVAL_FREEZE_SECONDS,
    `arrival_hold_seconds`).

    `dest_image_display`: the destination waypoint's `image_display` from
    job_config.json decides how its at-arrival photo ends: "pip" keeps a small
    card (no fullscreen), anything else ("cover"/"fullscreen") grows to
    fullscreen. Either way the clip then dissolves into the attraction video.

    Returns a LIST of output paths, not a single one -- normally just
    `[output_path]`, but a connected stop-by's fullscreen photo pause (see
    `landmarks` above) cuts the leg into an extra file right at its
    fullscreen beat, so a leg with one or more of those produces that many
    additional paths, all still using `output_path`'s own filename with a
    "_cont{n}" suffix so downstream (audio mux, subtitles, timeline) still
    resolves every one of them back to this SAME leg by filename.
    """
    if len(leg_latlon) < 2:
        raise ValueError("leg_latlon needs at least 2 points")

    walker_color = walker_color or [30, 136, 255]
    upcoming_color = upcoming_color or [170, 170, 170, 200]
    hud_labels = video_text.current_labels()
    mode_hud = _localized_hud(_MODE_HUD.get(mode, _DEFAULT_MODE_HUD), hud_labels)
    if travel_speed_kmh is None:
        travel_speed_kmh = mode_hud["default_speed_kmh"]

    heights = usable_heights(leg_elevations, len(leg_latlon))  # [NOTE] [Heatmap] same points as leg_latlon, before de-duplication
    df_raw = pd.DataFrame([{"lat": lat, "lon": lon} for lat, lon in leg_latlon])
    if heights is not None:
        df_raw["ele"] = heights
    df_raw = df_raw.drop_duplicates(subset=["lat", "lon"]).reset_index(drop=True)
    if len(df_raw) < 2:
        raise ValueError("leg_latlon collapsed to <2 distinct points after de-duplication")

    leg_dist_km = cumulative_distance_km(df_raw["lon"].tolist(), df_raw["lat"].tolist())
    total_leg_km = leg_dist_km[-1]

    segment_plan = _segment_plan(df_raw, leg_dist_km, landmarks, target_duration_seconds)
    leg_duration = (
        max(1.0, float(target_duration_seconds)) if target_duration_seconds is not None
        else max(3.0, (total_leg_km / travel_speed_kmh) * 3600.0)
    )
    total_frames = max(10, int(leg_duration * fps))

    smooth_df = interpolate_route_data(
        df_raw, leg_duration, total_frames, total_leg_km, leg_dist_km, segment_plan=segment_plan,
        arrival_slow_seconds=arrival_slow_seconds,
    )

    step_km = [0.0] + [
        haversine_km(
            smooth_df.iloc[i]["lon"], smooth_df.iloc[i]["lat"],
            smooth_df.iloc[i + 1]["lon"], smooth_df.iloc[i + 1]["lat"],
        )
        for i in range(len(smooth_df) - 1)
    ]
    cum_km = pd.Series(step_km).cumsum()
    remaining_km = cum_km.iloc[-1] - cum_km

    route_preview_path = df_raw[["lon", "lat"]].values.tolist()
    segment_colors = (
        quantize(leg_segment_colors(df_raw[["lat", "lon"]].values.tolist(), df_raw["ele"].tolist()) or [])
        if "ele" in df_raw.columns else []
    ) or None
    # This leg's own grey guide line -- from this leg's start waypoint to
    # its destination only. Neighboring legs' routes are deliberately never
    # drawn here (they used to be, as static blue/green "context" lines,
    # but on an out-and-back route they frequently retrace the same street
    # as this leg and just painted over/confused this leg's own guide line
    # with an irrelevant one) -- each leg's clip shows only its own path.
    base_layers = [
        pdk.Layer(
            "GeoJsonLayer", id="route-preview",
            data=(
                _route_gradient_feature(route_preview_path, [c[:3] + [upcoming_color[3] if len(upcoming_color) > 3 else 200] for c in segment_colors])
                if segment_colors else _route_linestring_feature(route_preview_path, line_color=upcoming_color)
            ),
            stroked=True, filled=False, get_line_color="properties.line_color",
            # Exactly the walked trail's own thickness (see _record_leg's
            # 'walker-trail' layer) -- the guide line is the SAME road, just
            # not yet travelled, so a thinner stroke made the trail look like
            # it was widening as it advanced rather than filling the line in.
            line_width_scale=1, line_width_min_pixels=line_thickness,
        ),
    ]
    base_layers.extend(_landmark_layers(landmarks or [], id_prefix="leg-landmark", white_dot=True))
    # The start pin is static (this leg's starting point never moves) so it
    # goes straight into base_layers and is visible for the whole clip, same
    # as the destination pin below.
    start_lat, start_lon = df_raw.iloc[0]["lat"], df_raw.iloc[0]["lon"]
    base_layers.append(
        pdk.Layer(
            "IconLayer", id="leg-start-pin",
            data=[{
                "lon": start_lon, "lat": start_lat,
                "icon": {
                    "url": _leg_pin_url(start_pin, _START_PIN_URL), "width": _TEARDROP_PIN_W,
                    "height": _TEARDROP_PIN_H, "anchorY": _TEARDROP_PIN_H,
                },
            }],
            get_icon="icon", get_position="[lon, lat]",
            get_size=60, size_units="'pixels'", size_scale=1, pickable=False,
        )
    )
    # The departure's own place name, in the same pill every other label
    # uses. route_chain is this leg's places in travel order, so its FIRST
    # entry is the waypoint this pin marks (the chain is omitted on a leg
    # that has no names at all, in which case the pin just goes unlabelled).
    start_label = (route_chain[0] if route_chain else "") or ""
    base_layers.extend(
        _label_pill_layer(
            [{"lon": start_lon, "lat": start_lat, "text": start_label}],
            "leg-start-label",
            size_px=34,
            pixel_offset_y=8,
        )
    )
    # Destination pin + name pill, shown for the whole leg (stop-by-cut
    # pieces included) so the viewer sees where the route is headed.
    dest_lat, dest_lon = df_raw.iloc[-1]["lat"], df_raw.iloc[-1]["lon"]
    if dest_pin is not False:  # False = a return stop: name pill only
        base_layers.append(
            pdk.Layer(
                "IconLayer", id="leg-dest-pin",
                data=[{
                    "lon": dest_lon, "lat": dest_lat,
                    "icon": {
                        "url": _leg_pin_url(dest_pin, _DEST_PIN_URL), "width": _TEARDROP_PIN_W,
                        "height": _TEARDROP_PIN_H, "anchorY": _TEARDROP_PIN_H,
                    },
                }],
                get_icon="icon", get_position="[lon, lat]",
                get_size=60, size_units="'pixels'", size_scale=1, pickable=False,
            )
        )
    base_layers.extend(
        _label_pill_layer(
            [{"lon": dest_lon, "lat": dest_lat, "text": dest_label or ""}],
            "leg-dest-label",
            size_px=34,
            pixel_offset_y=8,
        )
    )

    # The whole-leg "locked" camera: fits the leg's entire path in frame
    # (not a close street-level follow) and, once the intro's zoom-in
    # finishes, stays fixed there for the rest of the leg's walking
    # animation -- see _record_leg's main loop, which no longer re-centers
    # on the walker every frame the way the old chase-cam did. Capped at
    # follow_zoom so a very short/tight leg's fit-zoom can't exceed the
    # level the rest of this module treats as "close" street level.
    # The whole-leg "locked" camera: fits the leg's entire path in frame.
    # SPECIAL CASE: if the leg is interrupted by a connected stop-by photo pause,
    # compute the bounding box only up to that first stop-by so the camera
    # tightly frames the segment actually being walked in this clip, instead
    # of zooming out to fit the entire multi-segment route at once.
    fit_end = len(df_raw)
    for lm in (landmarks or []):
        if lm.get("connect_to_route") and lm.get("popup_image") and lm.get("lat") is not None and lm.get("lon") is not None:
            sq_dist = (df_raw["lat"] - lm["lat"]) ** 2 + (df_raw["lon"] - lm["lon"]) ** 2
            closest_idx = int(sq_dist.idxmin())
            # Use only a minimal +2 buffer. The previous +10 included points
            # much further down the route, which skewed the bounding box center
            # and pushed the visible portion off-center.
            fit_end = closest_idx + 2
            break

    fit_lons, fit_lats = _framed_points(df_raw, 0, fit_end, landmarks)
    locked_lon, locked_lat, locked_zoom = _fit_view_for_path(
        fit_lons, fit_lats, output_size,
        padding_frac=0.15, pitch=follow_pitch,
        bottom_margin_px=_leg_bottom_margin_px(bottom_reserve_px),
        top_margin_px=_LEG_TOP_MARGIN_PX,
    )
    # Lock max zoom to 17.5 to prevent extreme zoom-in for very short segments
    locked_zoom = min(locked_zoom, 17.5)

    view_state = pdk.ViewState(
        longitude=locked_lon, latitude=locked_lat,
        zoom=locked_zoom, pitch=follow_pitch, bearing=0,
    )
    deck = pdk.Deck(
        layers=base_layers, initial_view_state=view_state,
        map_provider="mapbox", map_style=map_style,
        api_keys={"mapbox": mapbox_key or MAPBOX_API_KEY},
        views=[pdk.View(type="MapView", controller=False)],
    )

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="navivi_pydeck_residential_") as html_dir:
        html_path = os.path.join(html_dir, "leg.html")
        deck.to_html(html_path)
        patch_pydeck_html(html_path)

        produced_paths = asyncio.run(_record_leg(
            html_path, html_dir, output_size, output_path, fps,
            df_raw, smooth_df, remaining_km, total_frames, dest_label,
            travel_speed_kmh, arrive_threshold_m, line_thickness, walker_color,
            follow_zoom, follow_pitch, mode_hud, arrival_hold_seconds, route_chain,
            topdown_transition_seconds, topdown_zoom_delta, dest_lat, dest_lon,
            total_leg_km, leg_dist_km, locked_lon, locked_lat, locked_zoom,
            dest_popup_image, dest_popup_freeze_seconds, landmarks,
            start_popup_image, start_popup_freeze_seconds, start_cue_seconds,
            arrival_photo_hold_seconds, arrival_wait_seconds, dest_image_display,
            dest_pin_url=_leg_pin_url(dest_pin, _DEST_PIN_URL),
            hud_card_png=hud_card_png, theme=theme, bottom_reserve_px=bottom_reserve_px,
            segment_colors=segment_colors,
        ))

    logger.info(f"Residential leg rendered ({mode}): {produced_paths}")
    return produced_paths


async def _record_leg(
    html_path, html_dir, output_size, output_path, fps,
    df_raw, smooth_df, remaining_km, total_frames, dest_label,
    travel_speed_kmh, arrive_threshold_m, line_thickness, walker_color,
    follow_zoom, follow_pitch, mode_hud, arrival_hold_seconds=2.0, route_chain=None,
    topdown_transition_seconds=1.6, topdown_zoom_delta=6.0, dest_lat=None, dest_lon=None,
    total_leg_km=None, leg_dist_km=None,
    locked_lon=None, locked_lat=None, locked_zoom=None,
    dest_popup_image=None, dest_popup_freeze_seconds=None, landmarks=None,
    start_popup_image=None, start_popup_freeze_seconds=None, start_cue_seconds=None,
    arrival_photo_hold_seconds=None, arrival_wait_seconds=None, dest_image_display="cover",
    dest_pin_url=_DEST_PIN_URL,
    hud_card_png: Optional[Callable[[float, float, bool, float], bytes]] = None,
    theme: Optional[str] = None,
    bottom_reserve_px: float = 0.0,
    segment_colors: Optional[List[List[int]]] = None,
):
    from playwright.async_api import async_playwright

    hud_labels = video_text.current_labels()
    hud_minutes = hud_labels["hud_minutes"]

    # A leg normally writes into ONE output file; a stop-by's photo pause can cut it into more (frame_sink.py).
    sink = await FrameSink.open(output_path, fps)
    proc_ref, produced_paths, frame_state = sink.proc_ref, sink.produced_paths, sink.frame_state
    _write_frame, _finalize_clip, _cut_to_new_clip = sink.write, sink.finalize, sink.cut

    async def _play_leg_photo_card(
        image_path, freeze_seconds_raw, card_key: str, marker_px=None, grow: bool = False,
        cut_after: bool = False, hold_seconds: Optional[float] = None,
        quick: bool = False, small_hold_seconds: Optional[float] = None,
        pip_end: bool = False,
    ) -> bool:
        """Shared by every one of this leg's photo beats -- the opening
        departure preview (`start_popup_image`, only ever set on the trip's
        very first leg), the opening destination preview
        (`dest_popup_image`), and the at-arrival destination preview (see
        this function's own arrival caller) -- called one after another
        (never concurrently) on this leg's single page/DOM, so all three
        safely reuse the same element ids; `card_key` only needs to keep
        their COPIED IMAGE FILEs distinct (see pedestrian.py's own stop-by
        trigger_index comment on why a shared filename risks serving the
        wrong cached photo).

        `marker_px`: where the card's leader line points -- defaults to the
        viewport's own center (correct for the two OPENING previews, whose
        camera is centered exactly on the start marker for that whole warm
        phase -- see the warm_js call). The at-arrival call passes the
        destination pin's own actual on-screen position instead (projected
        via `_project_lonlat_to_px`), since the locked camera does NOT
        recenter on it.

        `grow` (default False): fullscreen photo -> shrink to a small
        leader-line card -> freeze -> fade out -- used for the two OPENING
        previews. True reverses the direction -- pops in AT the small card
        size (leader line already drawn) -> holds -> GROWS to fullscreen ->
        freeze -> fade out -- mirroring `_play_stopby_photo_pause`'s own
        card-then-fullscreen treatment, so the at-arrival preview reads
        consistently with every other in-route popup instead of standing
        out as the only fullscreen-first one.

        `cut_after` (grow only): skips the fade-out -- holds at fullscreen
        for `freeze_sec` then returns immediately, leaving the fullscreen
        photo as the last frame written. The caller is expected to end the
        clip right there (no outro afterward) rather than write anything
        more after this returns.

        `hold_seconds`: overrides how long the photo is held at its final
        size, replacing both the waypoint's own `freeze_seconds_raw` AND the
        POPUP_MIN_DISPLAY_SECONDS floor it would otherwise be clamped to --
        the at-arrival caller uses it for a hold deliberately shorter than
        that floor.

        Returns True if it actually played something (a caller that also
        wants to skip its own post-photo steps, like the outro, checks
        this instead of re-deriving "did this leg have a photo" itself)."""
        if not image_path or not os.path.exists(image_path):
            return False
        img_ext = os.path.splitext(image_path)[1] or ".jpg"
        img_name = f"leg_photo_card_{card_key}{img_ext}"
        shutil.copy2(image_path, os.path.join(html_dir, img_name))
        img_url = f"http://127.0.0.1:{port}/{img_name}"

        # quick (the at-arrival photo): a brief pop-in and an immediate grow
        # to fullscreen - a transition, not a beat to sit on.
        fade_in_s, small_hold_s, grow_s = (0.2, 0.0, 0.6) if quick else (0.3, 0.4, 0.7)
        if small_hold_seconds is not None:
            small_hold_s = float(small_hold_seconds)  # arrived early: the small card waits for the voice
        if hold_seconds is not None:
            # Explicit override -- NOT run through the POPUP_MIN_DISPLAY_
            # SECONDS floor below, since the only caller that passes it
            # deliberately wants a hold shorter than that floor (see
            # tuning.RESIDENTIAL_ARRIVAL_POPUP_HOLD_SECONDS).
            freeze_sec = float(hold_seconds)
        else:
            freeze_sec = (
                float(freeze_seconds_raw)
                if freeze_seconds_raw is not None
                else tuning.POPUP_MIN_DISPLAY_SECONDS
            )
            freeze_sec = min(
                max(freeze_sec, tuning.POPUP_MIN_DISPLAY_SECONDS),
                tuning.POPUP_FREEZE_SECONDS_MAX,
            )

        out_w, out_h = output_size

        card_w = 360.0
        # Same aspect ratio as the fullscreen frame itself (not the photo's
        # own natural aspect ratio) -- with object-fit:cover, changing the
        # BOX's aspect ratio mid-shrink/grow changes which slice of the
        # photo is visible, so the image read as swapping to a different
        # crop/zoom partway through. Keeping the box's aspect ratio
        # constant throughout means the same crop is shown at every size,
        # just scaled.
        card_h = card_w * (float(out_h) / float(out_w))
        full_box = (0.0, 0.0, float(out_w), float(out_h))
        if marker_px is None:
            # The camera is centered exactly on the start marker for this
            # whole phase (see warm_js in the caller), so its on-screen
            # position is simply the viewport's own center -- no need to
            # reproject lon/lat to pixels.
            marker_px = (out_w / 2.0, out_h / 2.0)

        # Place the popup image floating directly above the marker, instead
        # of shoving it into a random corner. Target the top of the
        # teardrop pin (which is 44px tall).
        leader_target_y = marker_px[1] - 44.0
        card_gap = 30.0
        card_left = marker_px[0] - card_w / 2.0
        card_top = leader_target_y - card_gap - card_h
        # Clamped to stay fully on screen -- the shrink path's marker_px is
        # always the viewport center so this never kicks in there, but the
        # at-arrival grow path's marker_px is the destination pin's REAL
        # position, which can sit close enough to an edge that the
        # marker-relative placement above would push the card partway off
        # frame. The leader line still points at marker_px itself
        # (unclamped) -- only the card's own box is kept in bounds.
        edge_margin = 20.0
        card_left = min(max(card_left, edge_margin), out_w - card_w - edge_margin)
        card_top = min(max(card_top, edge_margin), out_h - card_h - edge_margin)
        card_box = (card_left, card_top, card_w, card_h)
        anchor_x = card_box[0] + card_w / 2.0
        anchor_y = card_box[1] + card_h

        if grow:
            # Pop in AT the small card size with the leader line already
            # drawn (mirrors _play_stopby_photo_pause's own card-then-
            # fullscreen treatment) -- then grows to fullscreen below,
            # instead of opening fullscreen and shrinking down.
            await page.evaluate(
                """([url, left, top, w, h, x1, y1, x2, y2]) => new Promise((resolve) => {
                    const img = document.createElement('img');
                    img.id = 'leg-dest-preview';
                    img.src = url;
                    Object.assign(img.style, {
                        position: 'fixed', zIndex: '9998',
                        left: left + 'px', top: top + 'px', width: w + 'px', height: h + 'px',
                        objectFit: 'cover', opacity: '0', borderRadius: '15px',
                        boxShadow: '0 15px 35px rgba(0,0,0,0.4)',
                    });
                    document.body.appendChild(img);

                    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                    svg.id = 'leg-dest-leader';
                    Object.assign(svg.style, {
                        position: 'fixed', inset: '0', width: '100vw', height: '100vh',
                        zIndex: '9997', pointerEvents: 'none',
                    });
                    const line = document.createElementNS(svg.namespaceURI, 'line');
                    line.id = 'leg-dest-leader-line';
                    line.setAttribute('x1', x1); line.setAttribute('y1', y1);
                    line.setAttribute('x2', x2); line.setAttribute('y2', y2);
                    line.setAttribute('stroke', 'white');
                    line.setAttribute('stroke-width', '3');
                    line.setAttribute('opacity', '0');
                    svg.appendChild(line);
                    document.body.appendChild(svg);

                    if (img.decode) { img.decode().then(resolve).catch(resolve); }
                    else { img.onload = resolve; img.onerror = resolve; }
                    setTimeout(resolve, 2000);
                })""",
                [
                    img_url, card_box[0], card_box[1], card_box[2], card_box[3],
                    anchor_x, anchor_y, marker_px[0], leader_target_y,
                ],
            )
            await _wait_for_paint(page)

            fade_in_frames = max(1, int(fade_in_s * fps))
            for i in range(fade_in_frames):
                alpha = (i + 1) / fade_in_frames
                await page.evaluate(
                    """(alpha) => {
                        const img = document.getElementById('leg-dest-preview');
                        if (img) img.style.opacity = alpha;
                        const line = document.getElementById('leg-dest-leader-line');
                        if (line) line.setAttribute('opacity', alpha);
                    }""",
                    alpha,
                )
                await _write_frame(await page.screenshot(**_FRAME_SHOT))

            hold_small_png = await page.screenshot(**_FRAME_SHOT)
            if pip_end:
                # image_display "pip": the photo stays a small card - it never
                # grows. It holds (at least a beat, longer if the walker is
                # waiting for the voice) and the clip ends on it.
                for _ in range(max(1, int(max(0.5, small_hold_s) * fps))):
                    await _write_frame(hold_small_png)
                return True
            for _ in range(int(small_hold_s * fps) if quick else max(1, int(small_hold_s * fps))):
                await _write_frame(hold_small_png)

            grow_frames = max(1, int(grow_s * fps))
            for i in range(grow_frames):
                t = _ease_in_out_cubic((i + 1) / grow_frames)
                left = card_box[0] + (full_box[0] - card_box[0]) * t
                top = card_box[1] + (full_box[1] - card_box[1]) * t
                w = card_box[2] + (full_box[2] - card_box[2]) * t
                h = card_box[3] + (full_box[3] - card_box[3]) * t
                radius = 15.0 * (1.0 - t)
                # Leader line fades out over the first ~2/3 of the grow so
                # it's gone well before the card fills the frame (a line
                # still pointing at a full-bleed image reads as a stray
                # mark, not a callout).
                line_alpha = max(0.0, 1.0 - t * 1.5)
                await page.evaluate(
                    """([left, top, w, h, radius, alpha]) => {
                        const img = document.getElementById('leg-dest-preview');
                        if (img) {
                            img.style.left = left + 'px';
                            img.style.top = top + 'px';
                            img.style.width = w + 'px';
                            img.style.height = h + 'px';
                            img.style.borderRadius = radius + 'px';
                        }
                        const line = document.getElementById('leg-dest-leader-line');
                        if (line) line.setAttribute('opacity', alpha);
                    }""",
                    [left, top, w, h, radius, line_alpha],
                )
                await _write_frame(await page.screenshot(**_FRAME_SHOT))

            full_hold_png = await page.screenshot(**_FRAME_SHOT)
            for _ in range(max(1, int(freeze_sec * fps))):
                await _write_frame(full_hold_png)

            if cut_after:
                # No fade-out, no cleanup evaluate -- the fullscreen photo
                # is meant to be the LAST frame this clip ever writes; the
                # caller ends the clip right after this returns instead of
                # continuing on to an outro.
                return True

            fade_frames = max(1, int(0.4 * fps))
            for i in range(fade_frames):
                alpha = 1.0 - ((i + 1) / fade_frames)
                await page.evaluate(
                    """(alpha) => {
                        const img = document.getElementById('leg-dest-preview');
                        if (img) img.style.opacity = alpha;
                    }""",
                    alpha,
                )
                await _write_frame(await page.screenshot(**_FRAME_SHOT))

            await page.evaluate(
                """() => {
                    const img = document.getElementById('leg-dest-preview');
                    if (img) img.remove();
                    const svg = document.getElementById('leg-dest-leader');
                    if (svg) svg.remove();
                }"""
            )
            return True

        await page.evaluate(
            """([url, w, h]) => new Promise((resolve) => {
                const img = document.createElement('img');
                img.id = 'leg-dest-preview';
                img.src = url;
                Object.assign(img.style, {
                    position: 'fixed', zIndex: '9998',
                    left: '0px', top: '0px', width: w + 'px', height: h + 'px',
                    objectFit: 'cover', opacity: '1',
                    boxShadow: '0 15px 35px rgba(0,0,0,0.4)',
                });
                document.body.appendChild(img);
                if (img.decode) { img.decode().then(resolve).catch(resolve); }
                else { img.onload = resolve; img.onerror = resolve; }
                setTimeout(resolve, 2000);
            })""",
            [img_url, out_w, out_h],
        )
        await _wait_for_paint(page)

        hold_full_png = await page.screenshot(**_FRAME_SHOT)
        for _ in range(max(1, int(0.4 * fps))):
            await _write_frame(hold_full_png)

        # Leader line: a thin callout from the card's near (bottom-left)
        # corner down to the start marker, with a small dot at the marker
        # end -- an SVG overlay rather than a deck.gl layer since it needs
        # to track the CARD's own screen-space animation, not a map
        # coordinate. Added once here, then just updated in place through
        # the shrink/freeze/fade phases below.
        await page.evaluate(
            """([x2, y2]) => {
                const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                svg.id = 'leg-dest-leader';
                Object.assign(svg.style, {
                    position: 'fixed', inset: '0', width: '100vw', height: '100vh',
                    zIndex: '9997', pointerEvents: 'none',
                });
                const line = document.createElementNS(svg.namespaceURI, 'line');
                line.id = 'leg-dest-leader-line';
                line.setAttribute('stroke', 'white');
                line.setAttribute('stroke-width', '3');
                line.setAttribute('opacity', '0');
                svg.appendChild(line);
                document.body.appendChild(svg);
            }""",
            [marker_px[0], leader_target_y],
        )

        shrink_frames = max(1, int(0.7 * fps))
        for i in range(shrink_frames):
            t = _ease_in_out_cubic((i + 1) / shrink_frames)
            left = full_box[0] + (card_box[0] - full_box[0]) * t
            top = full_box[1] + (card_box[1] - full_box[1]) * t
            w = full_box[2] + (card_box[2] - full_box[2]) * t
            h = full_box[3] + (card_box[3] - full_box[3]) * t
            radius = 15.0 * t
            leader_x1 = left + w / 2.0
            leader_y1 = top + h
            await page.evaluate(
                """([left, top, w, h, radius, x1, y1]) => {
                    const img = document.getElementById('leg-dest-preview');
                    if (img) {
                        img.style.left = left + 'px';
                        img.style.top = top + 'px';
                        img.style.width = w + 'px';
                        img.style.height = h + 'px';
                        img.style.borderRadius = radius + 'px';
                    }
                    const line = document.getElementById('leg-dest-leader-line');
                    if (line) {
                        line.setAttribute('x1', x1);
                        line.setAttribute('y1', y1);
                        line.setAttribute('x2', x1);
                        line.setAttribute('y2', y1);
                        line.setAttribute('opacity', '0');
                    }
                }""",
                [left, top, w, h, radius, leader_x1, leader_y1],
            )
            png_bytes = await page.screenshot(**_FRAME_SHOT)
            await _write_frame(png_bytes)

        # The line only draws in once the card has settled at its final
        # small size -- growing it DURING the shrink (card corner still
        # moving fast) read as a flickery diagonal streak, not a deliberate
        # callout.
        leader_grow_frames = max(1, int(0.3 * fps))
        anchor_x = card_box[0] + card_w / 2.0
        anchor_y = card_box[1] + card_h
        for i in range(leader_grow_frames):
            t = _ease_in_out_cubic((i + 1) / leader_grow_frames)
            await page.evaluate(
                """([x2, y2, alpha]) => {
                    const line = document.getElementById('leg-dest-leader-line');
                    if (line) {
                        line.setAttribute('x2', x2);
                        line.setAttribute('y2', y2);
                        line.setAttribute('opacity', alpha);
                    }
                }""",
                [
                    anchor_x + (marker_px[0] - anchor_x) * t,
                    anchor_y + (leader_target_y - anchor_y) * t,
                    t,
                ],
            )
            png_bytes = await page.screenshot(**_FRAME_SHOT)
            await _write_frame(png_bytes)

        freeze_png = await page.screenshot(**_FRAME_SHOT)
        for _ in range(max(1, int(freeze_sec * fps))):
            await _write_frame(freeze_png)

        fade_frames = max(1, int(0.4 * fps))
        for i in range(fade_frames):
            alpha = 1.0 - ((i + 1) / fade_frames)
            await page.evaluate(
                """([alphaVal]) => {
                    const img = document.getElementById('leg-dest-preview');
                    if (img) img.style.opacity = alphaVal;
                    const svg = document.getElementById('leg-dest-leader');
                    if (svg) svg.style.opacity = alphaVal;
                }""",
                [alpha],
            )
            png_bytes = await page.screenshot(**_FRAME_SHOT)
            await _write_frame(png_bytes)

        await page.evaluate(
            """() => {
                const img = document.getElementById('leg-dest-preview');
                if (img) img.remove();
                const svg = document.getElementById('leg-dest-leader');
                if (svg) svg.remove();
            }"""
        )
        return True

    server, port = start_local_server(html_dir)
    try:
        rel_path = os.path.relpath(html_path, html_dir).replace("\\", "/")
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(viewport={"width": output_size[0], "height": output_size[1]})
                page = await context.new_page()
                page.on("pageerror", lambda exc: logger.error(f"  [PAGE ERROR] {exc}"))
                await page.goto(f"http://127.0.0.1:{port}/{rel_path}")
                try:
                    await page.wait_for_load_state("load", timeout=5000)
                except Exception:
                    pass
                await page.wait_for_timeout(2500)

                await page.evaluate(
                    """([css, bannerIcon, timeLabel, cardIcon, chainPlaces, useImgCard, compassSvg, distLabel]) => {
                        const style = document.createElement('style');
                        style.textContent = css;
                        document.head.appendChild(style);
                        const topRight = document.createElement('div');
                        topRight.id = 'hud-top-right';
                        document.body.appendChild(topRight);
                        const banner = document.createElement('div');
                        banner.id = 'hud-banner';
                        banner.innerHTML = `<span class="icon">${bannerIcon}</span> <span id="hud-banner-text"></span>`;
                        topRight.appendChild(banner);
                        if (compassSvg) {
                            topRight.insertAdjacentHTML('beforeend', compassSvg);
                            const lbl = document.createElement('div');
                            lbl.id = 'hud-compass-label';
                            topRight.appendChild(lbl);
                        }
                        const card = document.createElement('div');
                        card.id = 'hud-card';
                        card.innerHTML = `
                            <div class="metric"><div class="label"><span class="icon">${cardIcon}</span> ${timeLabel}</div><div class="value" id="hud-time">--</div></div>
                            <div class="divider"></div>
                            <div class="metric"><div class="label">${distLabel}</div><div class="value" id="hud-dist">--</div></div>
                        `;
                        document.body.appendChild(card);
                        if (useImgCard) {
                            card.classList.add('hidden');
                            const img = document.createElement('img');
                            img.id = 'hud-card-img';
                            document.body.appendChild(img);
                        }
                        if (chainPlaces && chainPlaces.length) {
                            const chain = document.createElement('div');
                            chain.id = 'hud-chain';
                            chainPlaces.forEach((p, i) => {
                                if (i > 0) {
                                    const arrow = document.createElement('span');
                                    arrow.className = 'arrow';
                                    arrow.textContent = '→';
                                    chain.appendChild(arrow);
                                }
                                const place = document.createElement('span');
                                place.className = 'place';
                                place.textContent = p;
                                chain.appendChild(place);
                            });
                            document.body.appendChild(chain);
                            // A long chain shrinks (then ends in "...") to clear the destination pill, which
                            // changes size with its text; refitted before the next paint whenever it does.
                            const fit = () => {
                                const pill = document.getElementById('hud-banner');
                                if (!pill) return;
                                const room = pill.getBoundingClientRect().left - 16 - chain.getBoundingClientRect().left;
                                chain.style.fontSize = '';
                                chain.style.maxWidth = '';
                                let size = 30;
                                while (chain.getBoundingClientRect().width > room && size > 18) {
                                    size -= 1;
                                    chain.style.fontSize = size + 'px';
                                }
                                if (chain.getBoundingClientRect().width > room) {
                                    Object.assign(chain.style, { boxSizing: 'border-box', maxWidth: room + 'px', overflow: 'hidden', textOverflow: 'ellipsis' });
                                }
                            };
                            new ResizeObserver(fit).observe(document.getElementById('hud-banner'));
                        }
                    }""",
                    [_hud_css(theme), mode_hud["banner_icon"], mode_hud["time_label"], mode_hud["icon"], route_chain,
                     hud_card_png is not None,
                     _COMPASS_SVG.format(size=int(tuning.RESIDENTIAL_COMPASS_SIZE_PX))
                     if tuning.RESIDENTIAL_SHOW_COMPASS else "",
                     hud_labels["distance_label"]],
                )

                hud_card_cache: Dict[Tuple[int, int, bool], str] = {}
                hud_card_shown: List[Optional[str]] = [None]

                # [NOTE] [Heatmap] With the heatmap's heights, an elevation profile sits bottom-left, level with the
                # summary card, and its marker follows the walker.
                elev = None
                if "ele" in df_raw.columns:
                    scale = output_size[1] / 1080.0
                    palette = tuning.ui_theme(theme)
                    label = palette["card_label"]
                    elev = profile_card(
                        df_raw[["lat", "lon"]].values.tolist(), df_raw["ele"].tolist(),
                        (int(tuning.LEG_ELEVATION_CARD_SIZE[0]), int(tuning.LEG_ELEVATION_CARD_SIZE[1])),
                        hud_labels["elevation_profile"],
                        {"text": _css_rgba(palette["card_text"]), "label": _css_rgba(label),
                         "fill": _css_rgba((*label[:3], 40))},
                    )
                    if elev is not None:
                        await page.evaluate(
                            """([svg, bg, left, scale]) => {
                                const card = document.createElement('div');
                                card.id = 'hud-elev-card';
                                card.innerHTML = svg;
                                Object.assign(card.style, {
                                    position: 'fixed', left: left + 'px', bottom: '32px', zIndex: 1000,
                                    background: bg, borderRadius: '24px', boxShadow: '0 6px 20px rgba(0,0,0,0.35)',
                                    fontFamily: '"Noto Sans JP", sans-serif', transformOrigin: 'bottom left',
                                    transform: `scale(${scale})`, lineHeight: 0,
                                });
                                document.body.appendChild(card);
                            }""",
                            [elev[0], _css_rgba(palette["card_bg"]), tuning.LEG_CARD_MARGIN_PX + 20, scale],
                        )

                async def _set_elev(share: float) -> None:
                    """The profile's marker at this share of the leg, the card's bottom level with the summary card's."""
                    if elev is None:
                        return
                    x, y = elev[1](share)
                    await page.evaluate(
                        """([x, y]) => {
                            const marker = document.getElementById('elev-marker');
                            if (marker) marker.setAttribute('transform', `translate(${x},${y})`);
                            const card = document.getElementById('hud-elev-card');
                            const beside = document.getElementById('hud-card-img') || document.getElementById('hud-card');
                            if (card && beside && beside.offsetHeight) {
                                card.style.bottom = (window.innerHeight - beside.getBoundingClientRect().bottom) + 'px';
                            }
                        }""",
                        [x, y],
                    )

                async def _set_hud_card(rem_m: float, rem_min: int, arrived: bool = False) -> None:
                    """Swaps in the summary-card image for these numbers (rendered
                    once per distinct value) and waits for it to decode; moves the
                    elevation marker along with it."""
                    path_km = total_leg_km if arrived else float(remaining_km.iloc[0])
                    await _set_elev(1.0 if arrived else 1.0 - rem_m / (path_km * 1000.0) if path_km > 0 else 0.0)
                    if hud_card_png is None:
                        return
                    key = (int(round(rem_m)), int(rem_min), arrived)
                    src = hud_card_cache.get(key)
                    if src is None:
                        # Walking frames count down the smoothed path, the arrival frame is the raw leg.
                        path_m = (total_leg_km if arrived else float(remaining_km.iloc[0])) * 1000.0
                        share = min(1.0, key[0] / path_m) if path_m > 0 else 1.0
                        png = hud_card_png(key[0] / 1000.0, key[1] * 60.0, arrived, share)
                        src = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
                        hud_card_cache[key] = src
                    if hud_card_shown[0] == src:
                        return
                    hud_card_shown[0] = src
                    await page.evaluate(
                        """async (src) => {
                            const img = document.getElementById('hud-card-img');
                            if (!img) return;
                            img.src = src;
                            try { await img.decode(); } catch (e) {}
                        }""",
                        src,
                    )

                all_trail_points = df_raw[["lon", "lat"]].values.tolist()
                headings = _walk_headings(
                    smooth_df["lon"].tolist(), smooth_df["lat"].tolist(),
                    float(tuning.RESIDENTIAL_COMPASS_HEADING_WINDOW_M),
                )

                def _needle_js(index: int) -> str:
                    deg = headings[min(index, len(headings) - 1)] if headings else 0.0
                    return (
                        "const nd = document.getElementById('hud-compass-needle');"
                        f" if (nd) nd.setAttribute('transform', 'rotate({deg:.1f} 50 50)');"
                        " const nl = document.getElementById('hud-compass-label');"
                        f" if (nl) nl.textContent = {json.dumps(_heading_label(deg))};"
                    )

                await page.evaluate(f"() => {{ {_needle_js(0)} }}")

                c_trail = json.dumps(walker_color)
                c_glow = json.dumps(walker_color + [90])

                # Intro: opens on a true top-down shot (pitch 0, north-up,
                # zoomed out `topdown_zoom_delta` levels below the locked
                # whole-leg framing, centered exactly on the walker's start
                # marker -- a big establishing map) and eases zoom/position
                # in a bit into that locked framing (see `locked_lon`/
                # `locked_lat`/`locked_zoom`, computed once in
                # render_residential_leg_pydeck to fit the whole leg) before
                # the walker starts moving. Unlike the old chase-cam, the
                # camera then STAYS at this locked view for the entire main
                # loop below -- it never re-centers on the walker.
                intro_frames = max(0, int(topdown_transition_seconds * fps))
                # Floored well above a country/region-scale zoom -- locked_zoom
                # is now a per-leg fit-to-path zoom (often much lower than the
                # old fixed follow_zoom=19 baseline this delta was originally
                # tuned against), so subtracting the full delta unclamped could
                # push a short leg's establishing shot out to a whole-Japan
                # view instead of a "zoomed out a bit" local one.
                topdown_zoom = max(
                    (locked_zoom if locked_zoom is not None else follow_zoom) - topdown_zoom_delta,
                    (locked_zoom if locked_zoom is not None else follow_zoom) - 1.5,
                    13.5,
                )
                if intro_frames > 0:
                    first_row = smooth_df.iloc[0]
                    rem_km0 = float(remaining_km.iloc[0])
                    rem_m0 = rem_km0 * 1000.0
                    rem_min0 = _remaining_minutes(rem_m0, rem_km0, travel_speed_kmh)
                    banner_text0, dist_text0 = _hud_text(
                        dest_label, rem_m0, rem_min0, arrive_threshold_m, mode=mode_hud["mode"], labels=hud_labels
                    )
                    walker_json0 = json.dumps([{"lon": first_row["lon"], "lat": first_row["lat"]}])

                    # Warm-up: jump straight to the pure top-down frame (t=0)
                    # and give Mapbox real time to fetch tiles at that much
                    # lower zoom (`topdown_zoom` vs. the `follow_zoom` used
                    # for the whole rest of the leg) before the eased
                    # descent starts sweeping through the zoom range one
                    # frame at a time -- without this, the per-frame 15ms
                    # wait below isn't enough for new tiles to load mid-
                    # sweep, and Mapbox paints whatever coarse placeholder
                    # tile it already has (a flat, wrongly-scaled block)
                    # for part of the transition. Held for a few frames so
                    # it also reads as a brief top-down establishing shot.
                    warm_js = f"""
                    if (window.deckgl) {{
                        window.deckgl.setProps({{
                            viewState: {{
                                longitude: {first_row["lon"]}, latitude: {first_row["lat"]},
                                zoom: {topdown_zoom}, pitch: 0, bearing: 0,
                                transitionDuration: 0
                            }}
                        }});
                    }}
                    """
                    await page.evaluate(warm_js)
                    # 500ms wasn't reliably enough here -- the deck.gl
                    # canvas has ALSO just been sitting at its own INITIAL
                    # viewState (locked_zoom, a much tighter street-level
                    # framing -- see render_residential_leg_pydeck's own
                    # `view_state` construction) since page load, so this
                    # jump isn't just "one zoom step" like the per-frame
                    # sweep below worries about -- it can be several levels
                    # in one go. Too short a wait here left the destination-
                    # photo sequence right after this (which reuses this
                    # same still-settling frame as its own backdrop) reading
                    # as noticeably more zoomed-in than the establishing
                    # shot it's supposed to match once tiles finish loading.
                    await page.wait_for_timeout(1500)
                    warm_png = await page.screenshot(**_FRAME_SHOT)
                    # The brief establishing hold only when the leg opens on
                    # the map. A leg that opens on its departure photo goes
                    # straight to that fullscreen photo: the hold showed as a
                    # blink of bare map between the previous clip (the
                    # attraction photo) and the photo shrinking into place.
                    # The voice delay below is counted from the frames
                    # actually written, so it stays in sync either way.
                    # The leg opens on its DEPARTURE photo (fullscreen, shrinking
                    # onto the start pin); the destination photo only when the
                    # departure has none.
                    if not dest_popup_image and not start_popup_image:
                        for _ in range(max(1, int(0.3 * fps))):
                            await _write_frame(warm_png)

                    if start_popup_image:
                        await _play_leg_photo_card(
                            start_popup_image, start_popup_freeze_seconds, "start"
                        )
                    elif dest_popup_image:
                        await _play_leg_photo_card(
                            dest_popup_image, dest_popup_freeze_seconds, "dest_opening"
                        )

                    for i in range(intro_frames):
                        t = _ease_in_out_cubic((i + 1) / intro_frames)
                        zoom = topdown_zoom + (locked_zoom - topdown_zoom) * t
                        pitch = follow_pitch * t
                        bearing = 0.0
                        lon = first_row["lon"] + (locked_lon - first_row["lon"]) * t
                        lat = first_row["lat"] + (locked_lat - first_row["lat"]) * t
                        js = f"""
                        if (window.deckgl) {{
                            const currentLayers = window.deckgl.props.layers || [];
                            // Pins/dots redrawn above the route line, and name
                            // pills above THOSE -- otherwise whichever line/dot
                            // layer happens to be re-appended after them each
                            // frame would paint straight over them.
                            const labelLayers = currentLayers.filter(l => l.id.includes('label'));
                            const pinLayers = currentLayers.filter(l => !l.id.includes('label') && (l.id.includes('pin') || l.id.includes('dots')));
                            const staticLayers = currentLayers.filter(l => !['walker-trail', 'walker-dot', 'walker-halo'].includes(l.id) && !l.id.includes('label') && !l.id.includes('pin') && !l.id.includes('dots'));
                            const newHalo = new deck.ScatterplotLayer({{
                                id: 'walker-halo', data: {walker_json0},
                                getPosition: d => [d.lon, d.lat], getFillColor: {c_glow},
                                getRadius: 6, radiusMinPixels: 26
                            }});
                            const newDot = new deck.ScatterplotLayer({{
                                id: 'walker-dot', data: {walker_json0},
                                getPosition: d => [d.lon, d.lat], getFillColor: [255, 255, 255, 255],
                                getLineColor: {c_trail}, stroked: true, lineWidthMinPixels: 4,
                                getRadius: 2, radiusMinPixels: 12
                            }});
                            window.deckgl.setProps({{
                                viewState: {{
                                    longitude: {lon}, latitude: {lat},
                                    zoom: {zoom}, pitch: {pitch}, bearing: {bearing},
                                    transitionDuration: 0
                                }},
                                layers: [...staticLayers, newHalo, newDot, ...pinLayers, ...labelLayers]
                            }});
                            document.getElementById('hud-banner-text').textContent = {json.dumps(banner_text0)};
                            document.getElementById('hud-time').textContent = {json.dumps(hud_minutes.format(n=rem_min0))};
                            document.getElementById('hud-dist').textContent = {json.dumps(dist_text0)};
                            {_needle_js(0)}
                        }}
                        """
                        await page.evaluate(js)
                        await _set_hud_card(rem_m0, rem_min0)
                        await page.wait_for_timeout(50)
                        png_bytes = await page.screenshot(**_FRAME_SHOT)
                        await _write_frame(png_bytes)

                # Connected stop-by photo pauses (see render_residential_leg_
                # pydeck's `landmarks` docstring): a merged-in stop-by with
                # "connectToRoute" true AND its own photo gets a full
                # fullscreen-pause moment the instant the walker reaches it,
                # not just the plain static dot every other landmark gets.
                # Triggered on whichever walking-loop frame's own position
                # lands closest to that stop-by's coordinates.
                stopby_triggers: Dict[int, Dict] = {}
                _stopby_candidates = []
                # Off-route stop-bys shown without walking, in order, right after the stop they pop up at
                # ("pops_after": "" = the departure stop, else that connected stop-by's waypoint id).
                followers = [
                    lm for lm in (landmarks or [])
                    if lm.get("connect_to_route") and lm.get("popup_image") and lm.get("pops_after") is not None
                ]

                async def _play_followers(after: str, tag) -> None:
                    for k, lm in enumerate(lm for lm in followers if lm.get("pops_after") == after):
                        wait_s = float(lm.get("wait_seconds") or 0.0)
                        cuts_before = frame_state["cuts"]
                        await _play_stopby_photo_pause(
                            page, _write_frame, _cut_to_new_clip, fps, html_dir, port,
                            lm, locked_lon, locked_lat, locked_zoom, output_size, f"{tag}_{k}",
                            pitch=follow_pitch,
                            small_hold_seconds=wait_s if wait_s > 0 else None,
                        )
                        if frame_state["cuts"] > cuts_before:
                            piece_lead = (frame_state["count"] - frame_state["clip_start"]) / fps
                            write_audio_offset(proc_ref["real_path"], piece_lead)

                for lm in (landmarks or []):
                    if not (lm.get("connect_to_route") and lm.get("popup_image")) or lm.get("pops_after") is not None:
                        continue
                    lm_lat, lm_lon = lm.get("lat"), lm.get("lon")
                    if lm_lat is None or lm_lon is None:
                        continue
                    sq_dist = (smooth_df["lat"] - lm_lat) ** 2 + (smooth_df["lon"] - lm_lon) ** 2
                    _stopby_candidates.append((lm, sq_dist))
                # Assigned nearest-landmark-first, each claiming the closest
                # frame index not already taken -- two connected stop-bys
                # close enough together to share the same idxmin() used to
                # both just get `stopby_triggers[idx] = lm`, so the second
                # one's write silently clobbered the first: that waypoint's
                # photo pause never fired at all, only the other one's did
                # (at ITS OWN, different marker position) -- looking exactly
                # like "the popup shown isn't for this waypoint".
                for lm, sq_dist in sorted(_stopby_candidates, key=lambda pair: pair[1].min()):
                    for idx in sq_dist.to_numpy().argsort():
                        idx = int(idx)
                        if idx not in stopby_triggers:
                            stopby_triggers[idx] = lm
                            break

                # Unconnected landmarks with their own photo (the route only
                # passes NEAR these -- see `landmarks` docstring): a small
                # pip card pops in beside the marker as the walker nears it
                # and fades back out, via `_play_stopby_photo_pause`'s own
                # `pip_only` path -- brief, no fullscreen growth, no leg
                # cut, unlike a connected stop-by's arrival. Shares the same
                # nearest-index assignment as stopby_triggers above (and the
                # same taken-index set, so a landmark sitting right beside a
                # connected stop-by's own trigger point never clobbers it).
                pip_triggers: Dict[int, Dict] = {}
                _pip_candidates = []
                for lm in (landmarks or []):
                    if lm.get("connect_to_route") or not lm.get("popup_image"):
                        continue
                    lm_lat, lm_lon = lm.get("lat"), lm.get("lon")
                    if lm_lat is None or lm_lon is None:
                        continue
                    sq_dist = (smooth_df["lat"] - lm_lat) ** 2 + (smooth_df["lon"] - lm_lon) ** 2
                    _pip_candidates.append((lm, sq_dist))
                _taken_indices = set(stopby_triggers.keys())
                for lm, sq_dist in sorted(_pip_candidates, key=lambda pair: pair[1].min()):
                    for idx in sq_dist.to_numpy().argsort():
                        idx = int(idx)
                        if idx not in _taken_indices:
                            pip_triggers[idx] = lm
                            _taken_indices.add(idx)
                            break

                # Every trigger index on this leg, connected or not, in
                # order. A pip popup now keeps the walker moving through
                # real path frames while its card is up (see
                # `_play_stopby_photo_pause`'s pip_only branch) -- with two
                # trigger points close together (an unconnected landmark
                # sitting right before a connected stop-by, say), that walk-
                # through could otherwise land PAST the next trigger's own
                # index before the outer loop ever checks it, silently
                # skipping that stop-by's pause/cut entirely. Passed to the
                # pip call below as a hard ceiling so it never advances past
                # whatever comes next.
                all_trigger_indices = sorted(set(stopby_triggers.keys()) | set(pip_triggers.keys()))
                route_lonlat = list(zip(smooth_df["lon"], smooth_df["lat"]))

                # remaining_km's own total (its value at frame 0, before any
                # distance has been walked) -- the SMOOTH path's cumulative
                # length, which is not necessarily equal to total_leg_km (the
                # RAW polyline's length): linearly resampling lon/lat between
                # sparse raw points cuts corners on any sharp turn or loop,
                # shortening (or occasionally lengthening) the smooth path
                # relative to the raw one. On a leg with a tight loop (like a
                # small-island stop-by circuit) that gap can be large enough
                # that subtracting a SMOOTH remaining-distance from the RAW
                # total below would land on the wrong raw point entirely --
                # exactly where bisect crosses the loop's densely-packed raw
                # points, a small km error jumps `n_pts` by a visible chunk,
                # reading as the blue trail blinking ahead of (or behind) the
                # walker dot right at the loop.
                smooth_total_km = float(remaining_km.iloc[0]) if len(remaining_km) else 0.0

                frame_total = len(smooth_df)
                last_png_bytes = None
                crashed = False

                async def _draw_walker_frame(index: int):
                    """Draws/writes exactly one walking frame at `index` and
                    returns its PNG bytes, or None if ffmpeg crashed (sets
                    the enclosing `crashed` flag too). Pulled out of the
                    main loop below so a pip popup's own advance-while-
                    showing-the-card beat (see `_play_stopby_photo_pause`)
                    can call this too, instead of freezing the walker."""
                    nonlocal crashed
                    row = smooth_df.iloc[index]
                    rem_km = float(remaining_km.iloc[index])
                    # Trail must end exactly where the walker dot actually is
                    # -- picking raw points by ANIMATION-FRAME fraction (the
                    # old `index / total_frames` approach) assumes frames and
                    # raw route points advance in lockstep, which they don't
                    # (smooth_df is a separately time-based resampling), so
                    # the blue trail could visibly run ahead of or behind the
                    # dot. Selecting raw points by actual DISTANCE traveled
                    # so far, then appending the dot's own real position as
                    # the trail's final vertex, keeps the two in exact sync --
                    # but only once that traveled distance is expressed as a
                    # FRACTION of the smooth path's own total and rescaled
                    # onto the raw path's total (see smooth_total_km above),
                    # rather than mixed directly across the two different
                    # length scales.
                    traveled_frac = max(0.0, min(1.0, 1.0 - rem_km / smooth_total_km)) if smooth_total_km > 0 else 0.0
                    traveled_km = traveled_frac * (total_leg_km or 0.0)
                    n_pts = bisect.bisect_right(leg_dist_km, traveled_km) if leg_dist_km else 0
                    active_trail = all_trail_points[:n_pts] + [[row["lon"], row["lat"]]]
                    trail_geojson = json.dumps(
                        _route_gradient_feature(active_trail, [c[:3] + [255] for c in segment_colors])
                        if segment_colors else _route_linestring_feature(active_trail, line_color=walker_color)
                    ) if len(active_trail) >= 2 else json.dumps({"type": "FeatureCollection", "features": []})
                    walker_json = json.dumps([{"lon": row["lon"], "lat": row["lat"]}])

                    rem_m = rem_km * 1000.0
                    rem_min = _remaining_minutes(rem_m, rem_km, travel_speed_kmh)
                    banner_text, dist_text = _hud_text(
                        dest_label, rem_m, rem_min, arrive_threshold_m, mode=mode_hud["mode"], labels=hud_labels
                    )
                    js = f"""
                    if (window.deckgl) {{
                        const currentLayers = window.deckgl.props.layers || [];
                        const afterRemoval = currentLayers.filter(l => !['walker-trail', 'walker-dot', 'walker-halo'].includes(l.id));
                        // Pins/dots redrawn above the route line, and name
                        // pills above THOSE -- otherwise whichever line/dot
                        // layer happens to be re-appended after them each
                        // frame would paint straight over them.
                        const labelLayers = afterRemoval.filter(l => l.id.includes('label'));
                        const pinLayers = afterRemoval.filter(l => !l.id.includes('label') && (l.id.includes('pin') || l.id.includes('dots')));
                        const staticLayers = afterRemoval.filter(l => !l.id.includes('label') && !l.id.includes('pin') && !l.id.includes('dots'));
                        const newTrail = new deck.GeoJsonLayer({{
                            id: 'walker-trail', data: {trail_geojson},
                            stroked: true, filled: false, getLineColor: d => d.properties.line_color,
                            lineWidthScale: 1, lineWidthMinPixels: {line_thickness}
                        }});
                        const newHalo = new deck.ScatterplotLayer({{
                            id: 'walker-halo', data: {walker_json},
                            getPosition: d => [d.lon, d.lat], getFillColor: {c_glow},
                            getRadius: 6, radiusMinPixels: 26
                        }});
                        const newDot = new deck.ScatterplotLayer({{
                            id: 'walker-dot', data: {walker_json},
                            getPosition: d => [d.lon, d.lat], getFillColor: [255, 255, 255, 255],
                            getLineColor: {c_trail}, stroked: true, lineWidthMinPixels: 4,
                            getRadius: 2, radiusMinPixels: 12
                        }});
                        // Camera is locked for the whole leg (see the intro's
                        // zoom-in above) -- no viewState here, so deck.gl just
                        // keeps whatever view the intro left it at instead of
                        // re-centering on the walker every frame.
                        window.deckgl.setProps({{
                            layers: [...staticLayers, newTrail, newHalo, newDot, ...pinLayers, ...labelLayers]
                        }});
                        document.getElementById('hud-banner-text').textContent = {json.dumps(banner_text)};
                        document.getElementById('hud-time').textContent = {json.dumps(hud_minutes.format(n=rem_min))};
                        document.getElementById('hud-dist').textContent = {json.dumps(dist_text)};
                        {_needle_js(index)}
                    }}
                    """
                    await page.evaluate(js)
                    await _set_hud_card(rem_m, rem_min)
                    await _wait_for_paint(page)
                    png_bytes = await page.screenshot(**_FRAME_SHOT)
                    try:
                        await _write_frame(png_bytes)
                    except Exception as e:
                        logger.error(f"[ERROR] FFmpeg crashed: {e}")
                        crashed = True
                        return None
                    return png_bytes

                # The opening is over: the walker starts moving on the next
                # frame. Line the narration up with that moment (see
                # start_cue_seconds) and record the delay beside the clip.
                lead_in = frame_state["count"] / fps
                cue = float(start_cue_seconds) if start_cue_seconds is not None else 0.0
                if lead_in < cue and frame_state["last"] is not None:
                    for _ in range(int(round((cue - lead_in) * fps))):
                        await _write_frame(frame_state["last"])
                write_audio_offset(output_path, max(0.0, lead_in - cue))
                logger.info(
                    "Leg opening %.2fs, {start} cue %s -> narration delayed %.2fs.",
                    lead_in, f"{cue:.2f}s" if start_cue_seconds is not None else "none",
                    max(0.0, lead_in - cue),
                )

                index = 0
                while index < frame_total and not crashed:
                    png_bytes = await _draw_walker_frame(index)
                    if png_bytes is None:
                        break
                    last_png_bytes = png_bytes
                    # Throttled (every 5 frames, not every single one) so
                    # the CLI's live status line actually moves DURING a
                    # leg's render instead of sitting frozen on whatever
                    # static "rendering leg N" text route2vdo.py's own
                    # per-leg tracker call left it on for the whole
                    # multi-minute walk.
                    if index % 5 == 0 or index == frame_total - 1:
                        pct = int(100 * (index + 1) / frame_total) if frame_total else 100
                        tracker.show(f"{dest_label}: walking frame {index + 1}/{frame_total} ({pct}%)")
                    row = smooth_df.iloc[index]

                    if index == 0:
                        await _play_followers("", "start")

                    stopby_lm = stopby_triggers.get(index)
                    if stopby_lm is not None:
                        # Arrived early: the walker stands here, with the small
                        # photo card up, until this piece's narration is done;
                        # then the card grows to fullscreen.
                        # (the small photo card is up while it waits)
                        wait_s = float(stopby_lm.get("wait_seconds") or 0.0)
                        cuts_before = frame_state["cuts"]
                        await _play_stopby_photo_pause(
                            page, _write_frame, _cut_to_new_clip, fps, html_dir, port,
                            stopby_lm, locked_lon, locked_lat, locked_zoom, output_size, index,
                            pitch=follow_pitch,
                            small_hold_seconds=wait_s if wait_s > 0 else None,
                        )
                        if any(lm.get("pops_after") == stopby_lm.get("waypoint_id") for lm in followers):
                            if frame_state["cuts"] > cuts_before:
                                write_audio_offset(
                                    proc_ref["real_path"], (frame_state["count"] - frame_state["clip_start"]) / fps
                                )
                            await _play_followers(stopby_lm.get("waypoint_id"), index)

                        # Dynamic hop to the NEXT segment's framing for the new clip!
                        # (the piece's opening - photo beat and hop - is measured
                        # below, once the hop is done, as this piece's voice delay)
                        future_indices = [k for k in stopby_triggers.keys() if k > index]
                        if future_indices:
                            next_index = min(future_indices)
                            next_lm = stopby_triggers[next_index]
                            n_lat, n_lon = next_lm.get("lat"), next_lm.get("lon")
                        else:
                            n_lat, n_lon = dest_lat, dest_lon
                            
                        if n_lat is not None and n_lon is not None:
                            sq_dist_curr = (df_raw["lat"] - row["lat"]) ** 2 + (df_raw["lon"] - row["lon"]) ** 2
                            curr_df_idx = int(sq_dist_curr.idxmin())
                            sq_dist_next = (df_raw["lat"] - n_lat) ** 2 + (df_raw["lon"] - n_lon) ** 2
                            next_df_idx = int(sq_dist_next.idxmin())
                            
                            next_fit_lons, next_fit_lats = _framed_points(df_raw, curr_df_idx, next_df_idx + 2, landmarks)
                            if next_fit_lons:
                                new_lon, new_lat, new_zoom = _fit_view_for_path(
                                    next_fit_lons, next_fit_lats, output_size,
                                    padding_frac=0.15, pitch=follow_pitch,
                                    bottom_margin_px=_leg_bottom_margin_px(bottom_reserve_px),
                                    top_margin_px=_LEG_TOP_MARGIN_PX,
                                )
                                # Lock max zoom to prevent zooming in too much on short segments
                                new_zoom = min(new_zoom, 17.5)
                                
                                hop_frames = max(1, int(1.5 * fps))
                                for i in range(hop_frames):
                                    t = _ease_in_out_cubic((i + 1) / hop_frames)
                                    pan_lon = locked_lon + (new_lon - locked_lon) * t
                                    pan_lat = locked_lat + (new_lat - locked_lat) * t
                                    dip = math.sin(t * math.pi) * 1.5
                                    base_zoom = locked_zoom + (new_zoom - locked_zoom) * t
                                    pan_zoom = base_zoom - dip
                                    
                                    js_hop = f"""
                                    if (window.deckgl) {{
                                        window.deckgl.setProps({{
                                            viewState: {{
                                                longitude: {pan_lon}, latitude: {pan_lat},
                                                zoom: {pan_zoom}, pitch: {follow_pitch}, bearing: 0.0,
                                                transitionDuration: 0
                                            }}
                                        }});
                                    }}"""
                                    await page.evaluate(js_hop)
                                    await _wait_for_paint(page)
                                    png_bytes = await page.screenshot(**_FRAME_SHOT)
                                    await _write_frame(png_bytes)
                                
                                locked_lon, locked_lat, locked_zoom = new_lon, new_lat, new_zoom

                        if frame_state["cuts"] > cuts_before:
                            piece_lead = (frame_state["count"] - frame_state["clip_start"]) / fps
                            write_audio_offset(proc_ref["real_path"], piece_lead)
                            logger.info("Piece opening %.2fs -> its narration delayed %.2fs.", piece_lead, piece_lead)

                    pip_lm = pip_triggers.get(index)
                    if pip_lm is not None:
                        # Unconnected landmark: no camera hop, no leg cut --
                        # the walker keeps moving under the pip card itself
                        # (see `_play_stopby_photo_pause`'s pip_only branch),
                        # so it hands back whichever frame index it actually
                        # got to instead of the one it started on. Capped at
                        # the NEXT trigger's own index (see
                        # `all_trigger_indices`) so a nearby stop-by right
                        # after this pip never gets walked straight past.
                        next_trigger = next(
                            (k for k in all_trigger_indices if k > index), frame_total
                        )
                        index = await _play_stopby_photo_pause(
                            page, _write_frame, _cut_to_new_clip, fps, html_dir, port,
                            pip_lm, locked_lon, locked_lat, locked_zoom, output_size, index,
                            pitch=follow_pitch, pip_only=True,
                            advance_frame=_draw_walker_frame, frame_index=index + 1, frame_total=next_trigger,
                            avoid_lonlat=route_lonlat,
                        )
                        continue

                    index += 1

                # Freeze-frame on arrival: holds the final (arrived) frame
                # -- destination banner + marker already on screen -- for a
                # few extra seconds instead of cutting away the instant the
                # walker reaches the destination, so a viewer actually has
                # time to register where this is.
                #
                # The walker's own halo+dot (drawn on TOP of every static
                # layer each frame) lands exactly on the destination pin at
                # this final frame and is bigger than it, so it completely
                # hides the teardrop underneath -- clearing those two
                # layers first lets the actual pin read clearly in the held
                # frame instead of looking like an oversized blurry circle.
                if not crashed and last_png_bytes is not None:
                    # The HUD card's own remaining-distance/time reads "0 m
                    # / 0 分" the instant the walker arrives (see
                    # _remaining_minutes) -- correct while still walking,
                    # but meaningless as a held arrival frame. Swapped here
                    # for the LEG'S OWN total distance/time instead, so the
                    # freeze below reads as "here's the walk you just did"
                    # rather than a nonsense zero.
                    total_m = (total_leg_km or 0.0) * 1000.0
                    total_min = _remaining_minutes(total_m, total_leg_km or 0.0, travel_speed_kmh)
                    total_dist_text = f"{total_m:.0f} m" if total_m < 1000 else f"{total_m / 1000.0:.1f} km"
                    await page.evaluate(
                        """([distText, minText]) => {
                            if (window.deckgl) {
                                const staticLayers = (window.deckgl.props.layers || [])
                                    .filter(l => !['walker-halo', 'walker-dot'].includes(l.id));
                                window.deckgl.setProps({ layers: staticLayers });
                            }
                            const timeEl = document.getElementById('hud-time');
                            if (timeEl) timeEl.textContent = minText;
                            const distEl = document.getElementById('hud-dist');
                            if (distEl) distEl.textContent = distText;
                        }""",
                        [total_dist_text, hud_minutes.format(n=total_min)],
                    )
                    await _set_hud_card(total_m, total_min, arrived=True)
                    await _wait_for_paint(page)
                    last_png_bytes = await page.screenshot(**_FRAME_SHOT)

                    # Brief hold on this plain arrived frame before the
                    # photo takes over -- without it, the clip cuts straight
                    # from "still walking" to "photo popping in" the instant
                    # the walker stops, with no beat to register arrival.
                    if dest_popup_image:
                        # The arrived map holds for the freeze, then the small
                        # photo card pops up and waits for the rest of the voice
                        # (small_hold_seconds below, shortened by the freeze so
                        # the clip's length doesn't change).
                        pre_popup_hold_frames = int(tuning.RESIDENTIAL_ARRIVAL_FREEZE_SECONDS * fps)
                        for _ in range(pre_popup_hold_frames):
                            await _write_frame(last_png_bytes)

                    # EVERY leg's own destination photo plays here, RIGHT as
                    # the walker arrives (before the plain hold below),
                    # anchoring its leader line to the destination pin's real
                    # on-screen position under the now-locked camera (unlike
                    # at the opening, where the topdown-to-locked transition
                    # is still animating) -- not just leg 0's. cut_after=True:
                    # no fade-out, no outro
                    # afterward -- the clip ends right on the fullscreen
                    # arrival photo, a hard cut instead of fading back to
                    # the map first. Skipped (falls back to a plain hold +
                    # the normal outro) only when this leg's destination has
                    # no popup photo at all.
                    cut_on_arrival = False
                    if dest_popup_image:
                        arrival_marker_px = _project_lonlat_to_px(
                            dest_lon, dest_lat, locked_lon, locked_lat, locked_zoom,
                            output_size, pitch=follow_pitch,
                        )
                        cut_on_arrival = await _play_leg_photo_card(
                            dest_popup_image, dest_popup_freeze_seconds,
                            "dest_arrival", marker_px=arrival_marker_px, grow=True,
                            cut_after=True, quick=True,
                            small_hold_seconds=(
                                None if arrival_wait_seconds is None
                                else max(0.0, arrival_wait_seconds - tuning.RESIDENTIAL_ARRIVAL_FREEZE_SECONDS)
                            ),
                            pip_end=False,  # image_display is ignored: arrivals always go fullscreen
                            hold_seconds=(
                                arrival_photo_hold_seconds
                                if arrival_photo_hold_seconds is not None
                                else tuning.RESIDENTIAL_ARRIVAL_POPUP_HOLD_SECONDS
                            ),
                        )
                    else:
                        hold_frames = max(0, int(
                            (arrival_wait_seconds if arrival_wait_seconds is not None
                             else arrival_hold_seconds) * fps
                        ))
                        for _ in range(hold_frames):
                            await _write_frame(last_png_bytes)

                    # Outro: the reverse of the intro above -- eases the
                    # locked whole-leg framing back OUT to the same top-down
                    # establishing shot (pitch 0, north-up, zoomed out,
                    # centered exactly on the destination marker) so this
                    # clip ENDS on an overview shot, and the next leg's clip
                    # (see intro block) starts on its own overview shot and
                    # descends back in -- cutting the two together reads as
                    # the camera changing focus to a new stretch of road.
                    # Skipped entirely when the arrival photo just cut the
                    # clip -- there's nothing left to ease back out FROM,
                    # the fullscreen photo was already the last frame.
                    outro_frames = 0 if cut_on_arrival else max(0, int(topdown_transition_seconds * fps))
                    if outro_frames > 0:
                        last_row = smooth_df.iloc[-1]
                        for i in range(outro_frames):
                            t = _ease_in_out_cubic((i + 1) / outro_frames)
                            zoom = locked_zoom + (topdown_zoom - locked_zoom) * t
                            pitch = follow_pitch * (1.0 - t)
                            bearing = 0.0
                            lon = locked_lon + (last_row["lon"] - locked_lon) * t
                            lat = locked_lat + (last_row["lat"] - locked_lat) * t
                            js = f"""
                            if (window.deckgl) {{
                                window.deckgl.setProps({{
                                    viewState: {{
                                        longitude: {lon}, latitude: {lat},
                                        zoom: {zoom}, pitch: {pitch}, bearing: {bearing},
                                        transitionDuration: 0
                                    }}
                                }});
                            }}
                            """
                            await page.evaluate(js)
                            await page.wait_for_timeout(50)
                            png_bytes = await page.screenshot(**_FRAME_SHOT)
                            await _write_frame(png_bytes)

                        # Same tile warm-up problem as the intro's, mirrored:
                        # the outro just swept zoom all the way down to
                        # `topdown_zoom` in <2s, so give Mapbox a real beat
                        # to finish loading those low-zoom tiles before the
                        # clip ends on this frame (it's also what the NEXT
                        # leg's own intro warm-up starts from, visually).
                        await page.wait_for_timeout(400)
                        final_topdown_png = await page.screenshot(**_FRAME_SHOT)
                        for _ in range(max(1, int(0.3 * fps))):
                            await _write_frame(final_topdown_png)
            finally:
                await browser.close()
    finally:
        server.shutdown()
        server.server_close()

    await _finalize_clip()
    return produced_paths
