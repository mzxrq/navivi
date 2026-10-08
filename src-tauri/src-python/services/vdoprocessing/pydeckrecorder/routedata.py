"""Route/project data loading and pydeck HTML generation helpers."""

import os
from pathlib import Path

import json
import math
import numpy as np
import pandas as pd
import pydeck as pdk
from scipy.interpolate import interp1d

from services.config.upscaled_images import apply_upscaled_images
from services.mapfetcher.maplanguage import current_map_language, style_localizer_script

from .common import MAPBOX_API_KEY, logger, resolve_mapbox_token


def load_route_from_config(config_path: str):
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    apply_upscaled_images(data, Path(config_path).parent)

    from services.projectfiles import ROUTE_CACHE, meta_file

    cache_file = meta_file(Path(config_path).parent, ROUTE_CACHE)
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as cf:
                cache_data = json.load(cf)
                if isinstance(cache_data, dict) and "routing_cache" in cache_data:
                    data["routing_cache"] = cache_data["routing_cache"]
                else:
                    data["routing_cache"] = cache_data
        except Exception as e:
            logger.warning(f"Failed to read .routecache.json: {e}")

    return data


def build_pydeck_map(
    project_data: dict, output_html_path: str = "frames/temp_map.html"
):
    os.makedirs(os.path.dirname(output_html_path), exist_ok=True)

    mapbox_key = resolve_mapbox_token(project_data.get("settings", {})) or MAPBOX_API_KEY

    raw_coords = []
    for route_key, coords in project_data.get("routing_cache", {}).items():
        for coord in coords:
            raw_coords.append({"lat": coord[0], "lon": coord[1]})

    if not raw_coords:
        # [NOTE] [Map] Falls back to Tokyo so pydeck always has a valid
        # centroid to build a ViewState from, even when routing_cache is
        # empty (e.g. an early preview call before any leg has been routed).
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
        map_provider="mapbox",
        map_style="mapbox://styles/mapbox/streets-v12",
        api_keys={"mapbox": mapbox_key},
        views=[pdk.View(type="MapView", controller=True)],
    )
    r.to_html(output_html_path)
    return output_html_path


def arrival_time_fraction(frac: float, seconds: float, slow_seconds: float, end_speed: float = 0.4) -> float:
    """When (as a fraction of a walk lasting `seconds`) the walker reaches
    `frac` of its distance, if it walks at full speed and then slows down
    evenly to `end_speed` of it over the last `slow_seconds` (at most half the
    walk). It still arrives at 1.0: only the pace inside the walk changes."""
    if slow_seconds <= 0 or seconds <= 0 or frac <= 0 or frac >= 1:
        return min(1.0, max(0.0, frac))
    a = max(0.5, 1.0 - slow_seconds / seconds)  # time fraction where slowing starts
    k = (1.0 - end_speed) / (2.0 * (1.0 - a))
    whole = 1.0 - (1.0 - end_speed) * (1.0 - a) / 2.0  # distance at u=1, in full-speed units
    target = min(1.0, max(0.0, frac)) * whole
    if target <= a:
        return target
    x = (1.0 - math.sqrt(max(0.0, 1.0 - 4.0 * k * (target - a)))) / (2.0 * k)
    return min(1.0, a + x)


def interpolate_route_data(
    df_raw: pd.DataFrame,
    leg_duration: float,
    total_frames: int,
    total_leg_km: float,
    leg_dist_km: list,
    segment_plan: "list[tuple[int, float]] | None" = None,
    arrival_slow_seconds: float = 0.0,
) -> pd.DataFrame:
    """`segment_plan`: [(last raw point index of a segment, seconds it takes)]
    in route order, covering the whole leg. Each segment then takes exactly its
    own time (constant speed inside it), so a leg cut at stop-bys can give every
    piece its own length. None: one constant speed over the whole leg.
    `arrival_slow_seconds`: the walker slows down over this long before each
    stop (see arrival_time_fraction); 0 keeps a constant speed."""
    # [NOTE] [Animation] Each raw route point gets a timestamp proportional
    # to its cumulative distance along the leg (not evenly spaced in time),
    # so a constant-speed vehicle really does move at constant speed once
    # resampled below -- dense stretches of raw points don't slow the
    # animation down relative to sparse ones.
    if segment_plan and total_leg_km > 0:
        times = []
        seg = 0
        seg_start_idx, seg_start_time = 0, 0.0
        for i, d in enumerate(leg_dist_km):
            while seg < len(segment_plan) - 1 and i > segment_plan[seg][0]:
                seg_start_idx, seg_start_time = segment_plan[seg][0], seg_start_time + segment_plan[seg][1]
                seg += 1
            end_idx, seconds = segment_plan[seg]
            d0, d1 = leg_dist_km[seg_start_idx], leg_dist_km[min(end_idx, len(leg_dist_km) - 1)]
            frac = 1.0 if d1 <= d0 else min(1.0, max(0.0, (d - d0) / (d1 - d0)))
            times.append(seg_start_time + arrival_time_fraction(frac, seconds, arrival_slow_seconds) * seconds)
        df_raw["time_sec"] = times
    elif total_leg_km > 0:
        df_raw["time_sec"] = [
            arrival_time_fraction(d / total_leg_km, leg_duration, arrival_slow_seconds) * leg_duration
            for d in leg_dist_km
        ]
    else:
        df_raw["time_sec"] = np.linspace(0, leg_duration, num=len(df_raw))

    # [NOTE] [Animation] interp1d requires strictly distinct x-values;
    # duplicate lon/lat points (stationary GPS samples, or two points close
    # enough to round to the same time_sec) would otherwise raise.
    df_raw = df_raw.drop_duplicates(subset=["time_sec"], keep="first").reset_index(
        drop=True
    )

    # Resample onto a fixed number of evenly-spaced-in-TIME frames --
    # this is what actually turns the raw route polyline into per-frame
    # positions for the animation loop.
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
    """Exposes deckgl to window. No more Mapbox/OSM hacks here."""
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()

    # [HACK] [Map] pydeck's generated HTML keeps its Deck instance in a
    # local const/let, unreachable from outside the inline script -- string
    # patching the generated variable declaration is the only hook available
    # to expose it as window.deckgl, which renderer.py's page.evaluate calls
    # depend on for every frame. Three alternate patterns are covered since
    # pydeck's own template has changed which one it emits across versions.
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

    localizer = style_localizer_script(current_map_language())
    if localizer:
        content = content.replace("<head>", "<head>\n" + localizer, 1)

    # pydeck's bundled createDeck() JS doesn't expose an attributionControl
    # option to turn off from here, so the "© Mapbox © OpenStreetMap Improve
    # this map" strip it always adds is hidden via CSS instead -- it has no
    # place in a rendered video frame.
    content = content.replace(
        "</head>",
        '<style>.mapboxgl-ctrl-attrib, .mapboxgl-ctrl-logo, '
        '.maplibregl-ctrl-attrib, .maplibregl-ctrl-logo { display: none !important; }</style>\n</head>',
        1,
    )

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(content)
