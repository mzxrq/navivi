"""
mapfetcher.py
---------------------------------------------------------------------------
Bounding box + 16:9 HD static map image generator (OSM tiles via contextily).
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import contextily as cx
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from datetime import datetime

# Dynamically resolve the path to src-python/data/caches
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "caches"


def calculate_bounding_box(route_df: pd.DataFrame, padding_percent: float = 0.15) -> dict:
    """
    Finds the exact geographical corners of the GPS route and adds padding
    so the route doesn't clip the edges of the final frame.
    """
    min_lat = route_df["latitude"].min()
    max_lat = route_df["latitude"].max()
    min_lon = route_df["longitude"].min()
    max_lon = route_df["longitude"].max()

    lat_span = max_lat - min_lat
    lon_span = max_lon - min_lon

    if lat_span == 0:
        lat_span = 0.001
    if lon_span == 0:
        lon_span = 0.001

    pad_lat = lat_span * padding_percent
    pad_lon = lon_span * padding_percent

    padded_box = {
        "min_lat": min_lat - pad_lat,
        "max_lat": max_lat + pad_lat,
        "min_lon": min_lon - pad_lon,
        "max_lon": max_lon + pad_lon,
    }

    print("Bounding Box Calculated:")
    print(f"  Latitude:  {padded_box['min_lat']:.5f} to {padded_box['max_lat']:.5f}")
    print(f"  Longitude: {padded_box['min_lon']:.5f} to {padded_box['max_lon']:.5f}")

    return padded_box


def save_map_image(
    bounding_box: dict,
    output_filename: str = "map_background.png",
    output_size: tuple[int, int] = (1920, 1080),
    max_zoom: int = 19,
) -> tuple[tuple[float, float, float, float], int, int]:
    """
    Forces the map boundaries into a perfect 16:9 aspect ratio, fetches the tiles
    (capped at `max_zoom` — default 19, OSM's usual max) and a safe tile-count
    budget), and saves them as a high-resolution, video-ready background at
    exactly `output_size` pixels (must be 16:9, e.g. (1920, 1080), (1280, 720),
    (960, 540)).

    Note: `max_zoom` controls tile *detail*, not the pixel size of the saved
    image (`output_size` controls that). Capping `max_zoom` too low actually
    makes the map cover MORE ground area for small/short routes, since each
    tile then spans more real-world distance — shrinking your route to a
    speck instead of tightening the frame around it. Leave this at 19 unless
    you have a specific reason (e.g. very slow/limited connection) to fetch
    coarser tiles.

    Returns (extent, img_width_px, img_height_px). extent is (w, e, s, n) in
    Web Mercator (EPSG:3857) meters — pass this straight into
    gpsparser.convert_gps_to_pixels(extent=...).
    """
    out_w, out_h = output_size
    if abs((out_w / out_h) - (16.0 / 9.0)) > 0.01:
        raise ValueError(
            f"output_size {output_size} is not a 16:9 ratio "
            f"(try (1920, 1080), (1280, 720), or (960, 540))."
        )
    # figsize is fixed at 16x9 inches below, so dpi = width_px / 16 lands
    # exactly on the requested resolution (960x540 needs dpi=60; 1080p needs
    # dpi=120; 4K needs dpi=240, etc.)
    target_dpi = out_w / 16.0

    print(f"Calculating 16:9 aspect ratio boundaries (target {out_w}x{out_h})...")

    w = bounding_box["min_lon"]
    s = bounding_box["min_lat"]
    e = bounding_box["max_lon"]
    n = bounding_box["max_lat"]

    # --- MINIMUM COVERAGE GUARD (fixes low-res output on short routes) ---
    MIN_SPAN_METERS = 300
    center_lat = (s + n) / 2.0
    meters_per_deg_lat = 111_320
    meters_per_deg_lon = 111_320 * math.cos(math.radians(center_lat))

    min_lat_span = MIN_SPAN_METERS / meters_per_deg_lat
    min_lon_span = MIN_SPAN_METERS / meters_per_deg_lon

    if (n - s) < min_lat_span:
        pad = (min_lat_span - (n - s)) / 2.0
        s -= pad
        n += pad
    if (e - w) < min_lon_span:
        pad = (min_lon_span - (e - w)) / 2.0
        w -= pad
        e += pad
    # -----------------------------------------------------------------

    # --- 16:9 ASPECT RATIO MATH ---
    target_ratio = 16.0 / 9.0

    center_lat = (s + n) / 2.0
    lat_span = n - s
    lon_span = e - w

    lon_scale = math.cos(math.radians(center_lat))
    current_ratio = (lon_span * lon_scale) / lat_span

    if current_ratio < target_ratio:
        new_lon_span = (lat_span * target_ratio) / lon_scale
        expansion = (new_lon_span - lon_span) / 2.0
        w -= expansion
        e += expansion
    else:
        new_lat_span = (lon_span * lon_scale) / target_ratio
        expansion = (new_lat_span - lat_span) / 2.0
        s -= expansion
        n += expansion
    # -----------------------------------
    
    os.makedirs(CACHE_DIR, exist_ok=True)
    cx.set_cache_dir(str(CACHE_DIR))

    print(f"Calculating optimal zoom level (capped at {max_zoom})...")
    
    optimal_zoom = max_zoom
    for z in range(max_zoom, 0, -1):
        if cx.howmany(w, s, e, n, z, ll=True) <= 30:
            optimal_zoom = z
            break
    if optimal_zoom > max_zoom:
        optimal_zoom = max_zoom

    print(f"Fetching 16:9 map tiles via Contextily (Max Zoom: {optimal_zoom})...")

    img = None
    extent = None

    while optimal_zoom > 0:
        try:
            print(f"Trying zoom level {optimal_zoom}...")
            img, extent = cx.bounds2img(w, s, e, n, ll=True, zoom=optimal_zoom, use_cache=str(CACHE_DIR))  # type: ignore
            break  
        except Exception as download_error:
            print(f"Zoom {optimal_zoom} failed ({download_error}). Lowering zoom by 1...")
            optimal_zoom -= 1

    if img is None:
        raise RuntimeError("Failed to download map tiles at any zoom level.")

    fig, ax = plt.subplots(figsize=(16, 9), dpi=target_dpi)
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    ax.axis('off')
    ax.imshow(img, extent=extent, aspect='auto', interpolation='lanczos')

    fig.savefig(output_filename, pad_inches=0, dpi=target_dpi, transparent=True)
    plt.close(fig)

    img_width_px = int(round(16 * target_dpi))
    img_height_px = int(round(9 * target_dpi))

    print(f" Success! 16:9 map saved to: {os.path.abspath(output_filename)}")
    print(f"🌍 Map Extent (Web Mercator): {extent}")
    print(f"🖼  Saved image size: {img_width_px}x{img_height_px}px")

    return extent, img_width_px, img_height_px  # type: ignore


def get_residential_map(
    lat: float, 
    lon: float, 
    radius_meters: int = 400, 
    output_filename: str = "residential_map.png",
    output_size: tuple[int, int] = (1920, 1080)
):
    """
    Takes a single Lat/Lon coordinate, calculates a physical bounding box 
    around it based on a radius, and fetches a high-detail residential map.
    """
    print(f"📍 Calculating map boundaries for Center: {lat}, {lon} (Radius: {radius_meters}m)")

    # 1. LAT/LON TO METERS MATH
    # 1 degree of latitude is roughly 111,320 meters
    meters_per_deg_lat = 111_320.0
    meters_per_deg_lon = 111_320.0 * math.cos(math.radians(lat))

    # Calculate the offsets
    lat_offset = radius_meters / meters_per_deg_lat
    lon_offset = radius_meters / meters_per_deg_lon

    # Create the initial bounding box
    s = lat - lat_offset
    n = lat + lat_offset
    w = lon - lon_offset
    e = lon + lon_offset

    # 2. FORCE 16:9 ASPECT RATIO
    out_w, out_h = output_size
    target_ratio = out_w / out_h
    
    lat_span = n - s
    lon_span = e - w
    lon_scale = math.cos(math.radians(lat))
    current_ratio = (lon_span * lon_scale) / lat_span

    if current_ratio < target_ratio:
        new_lon_span = (lat_span * target_ratio) / lon_scale
        expansion = (new_lon_span - lon_span) / 2.0
        w -= expansion
        e += expansion
    else:
        new_lat_span = (lon_span * lon_scale) / target_ratio
        expansion = (new_lat_span - lat_span) / 2.0
        s -= expansion
        n += expansion

    # 3. CONFIGURE TILE PROVIDER
    provider = cx.providers.CartoDB.Voyager  
    
    os.makedirs(CACHE_DIR, exist_ok=True)
    cx.set_cache_dir(str(CACHE_DIR))

    # --- NEW DYNAMIC ZOOM CALCULATION ---
    # Find the maximum zoom that keeps the total tile download under 40 tiles
    max_zoom = 19
    optimal_zoom = max_zoom
    for z in range(max_zoom, 0, -1):
        if cx.howmany(w, s, e, n, z, ll=True) <= 40:
            optimal_zoom = z
            break
    # ------------------------------------

    print(f"Fetching high-detail map tiles (Optimal Zoom: {optimal_zoom})...")
    
    while optimal_zoom > 0:
        try:
            print(f"Trying zoom level {optimal_zoom}...")
            img, extent = cx.bounds2img(
                w, s, e, n, 
                ll=True, 
                zoom=optimal_zoom,  # type: ignore
                source=provider,
                use_cache=str(CACHE_DIR)  # type: ignore
            )
            break
        except Exception as download_error:
            print(f"Zoom {optimal_zoom} failed ({download_error}). Lowering zoom by 1...")
            optimal_zoom -= 1

    if img is None:
        raise RuntimeError("Failed to download map tiles at any zoom level.")

    # 4. RENDER AND SAVE
    target_dpi = out_w / 16.0
    fig, ax = plt.subplots(figsize=(16, 9), dpi=target_dpi)
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    ax.axis('off')
    ax.imshow(img, extent=extent, aspect='auto', interpolation='lanczos')

    fig.savefig(output_filename, pad_inches=0, dpi=target_dpi, transparent=True)
    plt.close(fig)

    print(f" Success! Residential map saved to: {os.path.abspath(output_filename)}")
    return extent


def generate_residential_map_series(
    route_df: pd.DataFrame, 
    points_per_slice: int = 500,  
    output_dir: str = "data/outputs",
    output_prefix: str = "res_map",
    output_size: tuple[int, int] = (1920, 1080)
) -> list[dict]:
    """
    Slices the full GPS route dynamically based on a set number of points 
    per slice, generating a highly detailed residential map for each segment.
    """
    total_points = len(route_df)
    num_slices = max(1, math.ceil(total_points / points_per_slice))
    
    print(f"🔪 Total data points: {total_points}.")
    print(f"🔪 Slicing route into {num_slices} segments (target: {points_per_slice} points/slice)...")
    
    os.makedirs(output_dir, exist_ok=True)
    datetime_str = datetime.now().strftime("%Y%m%d_%H%M%S")

    # --- THE FIX: Use pure Pandas to chunk the data safely ---
    chunks = [route_df.iloc[i : i + points_per_slice] for i in range(0, total_points, points_per_slice)]
    
    results = []
    
    for i, chunk in enumerate(chunks):
        # 1. Find the geographical center of this specific chunk
        min_lat = chunk["latitude"].min()
        max_lat = chunk["latitude"].max()
        min_lon = chunk["longitude"].min()
        max_lon = chunk["longitude"].max()
        
        center_lat = (min_lat + max_lat) / 2.0
        center_lon = (min_lon + max_lon) / 2.0
        
        # 2. Calculate the physical size of this chunk in meters
        lat_span_meters = (max_lat - min_lat) * 111_320.0
        lon_span_meters = (max_lon - min_lon) * (111_320.0 * math.cos(math.radians(center_lat)))
        
        # 3. Determine the radius needed to fit this chunk (plus 20% padding)
        chunk_radius = max(lat_span_meters, lon_span_meters) / 2.0
        chunk_radius = int(chunk_radius * 1.2)
        
        # Enforce a minimum radius so it still looks like a "residential" zoom level
        if chunk_radius < 100: # Changed from 300 to allow tighter zooms
            chunk_radius = 100
            
        out_path = None
        for seq in range(1, 100):
            candidate = Path(output_dir) / f"{output_prefix}_{datetime_str}_{seq:02d}.png"
            if not candidate.exists():
                out_path = candidate
                break
        if out_path is None:
            raise FileExistsError(
                f"Could not generate a unique filename for residential slice {i+1} "
                f"(99 files already exist for {datetime_str})."
            )
        out_name = str(out_path)

        print(f"\n--- Generating Map {i+1}/{num_slices} (contains {len(chunk)} points) ---")
        
        # 4. Call your existing function for this chunk
        extent = get_residential_map(
            lat=center_lat,
            lon=center_lon,
            radius_meters=chunk_radius,
            output_filename=out_name,
            output_size=output_size
        )
        
        # Save the data so the video renderer can use it later
        results.append({
            "chunk_df": chunk,       
            "map_file": out_name,    
            "extent": extent         
        })
        
    print(f"\n Finished generating {num_slices} residential maps!")
    return results

def generate_residential_map_series_by_landmark(
    route_chunks: list[pd.DataFrame],
    source_filename: str,
    output_dir: str = "data/outputs",
    output_size: tuple[int, int] = (1920, 1080),
) -> list[dict]:
    """
    One residential map per landmark chunk (from split_route_by_landmarks),
    centered on that landmark's own coordinates. File naming follows the
    project-wide convention: {source_stem}_{date}_{time}_{seq}_res{N}.png,
    so waypoints[N-1] in the exported JSON always maps to res{N}.png.
    """
    os.makedirs(output_dir, exist_ok=True)
    datetime_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_stem = Path(source_filename).stem  # traceability back to source log

    results = []
    for res_num, chunk in enumerate(route_chunks, start=1):
        landmarked_rows = chunk[chunk["is_landmarked"]]
        if landmarked_rows.empty:
            # Should never happen given split_route_by_landmarks' contract,
            # but fail loudly rather than silently mis-centering the image.
            raise ValueError(f"Chunk {res_num} has no landmark row to center on.")
        landmark_row = landmarked_rows.iloc[-1]
        center_lat = float(landmark_row["latitude"])
        center_lon = float(landmark_row["longitude"])

        # Radius sized to fully contain the chunk's approach path
        min_lat, max_lat = chunk["latitude"].min(), chunk["latitude"].max()
        min_lon, max_lon = chunk["longitude"].min(), chunk["longitude"].max()
        meters_per_deg_lat = 111_320.0
        meters_per_deg_lon = 111_320.0 * math.cos(math.radians(center_lat))
        lat_span_m = (max_lat - min_lat) * meters_per_deg_lat
        lon_span_m = (max_lon - min_lon) * meters_per_deg_lon
        
        # Changed minimum from 300 to 100
        radius = max(int(max(lat_span_m, lon_span_m) / 2.0 * 1.2), 100)

        # Collision-safe filename: probe sequence numbers 01-99 the same
        # way filehandler.store_raw_file_with_datetime does.
        out_path = None
        for seq in range(1, 100):
            candidate = f"{base_stem}_{datetime_str}_{seq:02d}_res{res_num:02d}.png"
            candidate_path = Path(output_dir) / candidate
            if not candidate_path.exists():
                out_path = candidate_path
                break
        if out_path is None:
            raise FileExistsError(
                f"Could not generate a unique filename for residential map #{res_num}."
            )

        print(f"🏘️  Residential map {res_num}/{len(route_chunks)} → {out_path.name}")
        extent = get_residential_map(
            lat=center_lat,
            lon=center_lon,
            radius_meters=radius,
            output_filename=str(out_path),
            output_size=output_size,
        )

        results.append({
            "chunk_df": chunk,
            "map_file": str(out_path),
            "extent": extent,
            "center": (center_lat, center_lon),
            "residential_number": res_num,
        })

    return results