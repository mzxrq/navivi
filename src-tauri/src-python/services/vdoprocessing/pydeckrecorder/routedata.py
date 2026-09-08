"""Route/project data loading and pydeck HTML generation helpers."""

import os
from pathlib import Path

import json
import numpy as np
import pandas as pd
import pydeck as pdk
from scipy.interpolate import interp1d

from .common import MAPBOX_API_KEY, logger


def load_route_from_config(config_path: str):
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    cache_file = Path(config_path).parent / ".routecache.json"
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

    mapbox_key = project_data.get("settings", {}).get("mapbox_token", MAPBOX_API_KEY)

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


def interpolate_route_data(
    df_raw: pd.DataFrame,
    leg_duration: float,
    total_frames: int,
    total_leg_km: float,
    leg_dist_km: list,
) -> pd.DataFrame:
    # [NOTE] [Animation] Each raw route point gets a timestamp proportional
    # to its cumulative distance along the leg (not evenly spaced in time),
    # so a constant-speed vehicle really does move at constant speed once
    # resampled below -- dense stretches of raw points don't slow the
    # animation down relative to sparse ones.
    if total_leg_km > 0:
        df_raw["time_sec"] = [(d / total_leg_km) * leg_duration for d in leg_dist_km]
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

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(content)
