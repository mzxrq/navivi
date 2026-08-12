"""
mapfetcher.py
---------------------------------------------------------------------------
Fetches a static background map image (via contextily/OSM-style tiles)
for a given route's bounding box, and hands back exactly what
route2vdo.py's pixel-projection step needs: the saved image's pixel
size, and the Web Mercator (EPSG:3857) `extent` that image covers.

WHY THIS FILE WAS REWRITTEN (not just import-renamed):
The previous version saved the map via
    plt.savefig(..., bbox_inches='tight', pad_inches=0)
`bbox_inches='tight'` crops the saved PNG to a tight box around the
*rendered content*, which does NOT necessarily match the pixel
dimensions matplotlib's `figsize`/`dpi` would imply. That's fine for a
one-off "pretty picture," but it silently breaks any pipeline stage
that needs to convert lat/lon -> pixel coordinates using the returned
`extent`, because the extent-to-pixel ratio you'd compute from
figsize/dpi no longer matches the actual saved image after cropping.

The fix: skip matplotlib entirely for the file write. `cx.bounds2img()`
already returns a raw RGBA numpy tile array - we save THAT array
directly (via PIL), so the saved PNG's pixel dimensions are exactly
`img.shape`, with zero ambiguity between "what we think we saved" and
"what's actually on disk." matplotlib is no longer part of the output
path at all - one less place for a silent pixel-mapping bug to hide.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import os
from pathlib import Path
from tkinter import Image
from typing import Final

import contextily as cx
import numpy as np
import pandas as pd
from PIL import Image
import matplotlib.pyplot as plt
import json

# Standard 16:9 video frame - route2vdo.py renders onto this canvas, so
# the background map should already be this shape rather than relying
# on downstream letterboxing/stretching to fix a mismatched aspect ratio.
TARGET_ASPECT_RATIO: Final[float] = 16 / 9

# Floor on the saved map's pixel width. WHY THIS EXISTS: contextily
# picks a tile zoom level (and therefore a returned image resolution)
# based on how much geographic area the bbox covers - a short walking
# route with a tight bbox can legitimately come back as a 200-300px-
# wide image. route2vdo.py's summary card is a fixed 420px wide and
# anchors itself with a margin near a frame corner; if the frame is
# narrower than (card_width + margin), the card's crop region goes
# negative/zero-width and the alpha-composite step crashes with a
# numpy broadcast error. Upscaling small tiles to this floor guarantees
# every video frame this pipeline produces is large enough to hold the
# card, independent of how small/tight the input route happens to be.
MIN_MAP_WIDTH_PX: Final[int] = 1280
CACHE_DIR: Final[Path] = Path("data\\caches\\contextily")


class MapFetcher:
    def __init__(self, provider=None):
        """
        Initialize the MapFetcher.
        Defaults to CartoDB Voyager, but can accept any contextily provider.
        """
        # cx.providers is powered by xyzservices
        self.provider = provider if provider else cx.providers.CartoDB.Voyager  # type: ignore

    def get_bounding_box(self, df: pd.DataFrame, padding_factor: float = 0.05) -> dict:
        """
        Calculates the West, South, East, and North bounds (in WGS84
        lat/lon degrees) for a set of GPS coordinates, expanded by
        `padding_factor` so the route doesn't touch the image edge.

        NOTE: this does NOT yet force a 16:9 aspect ratio - that
        correction happens in fetch_image(), once we know the actual
        pixel geometry contextily is about to fetch. Doing the aspect
        correction here (in lat/lon degrees) vs. there (in Web Mercator
        meters) would give a visibly different result near the poles,
        since degree-based padding isn't uniform in real-world distance.
        Web Mercator meters are uniform in x/y, so that's the right
        space to do the 16:9 correction in.
        """
        if df.empty or "latitude" not in df.columns or "longitude" not in df.columns:
            raise ValueError("DataFrame must contain 'latitude' and 'longitude' columns.")

        min_lat = df["latitude"].min()
        max_lat = df["latitude"].max()
        min_lon = df["longitude"].min()
        max_lon = df["longitude"].max()

        # Add padding so the route doesn't touch the exact edge of the image
        lat_padding = (max_lat - min_lat) * padding_factor
        lon_padding = (max_lon - min_lon) * padding_factor

        south = min_lat - lat_padding
        north = max_lat + lat_padding
        west = min_lon - lon_padding
        east = max_lon + lon_padding

        return {
            "w": west,
            "s": south,
            "e": east,
            "n": north,
        }

    def fetch_image(
        self,
        bounding_box: dict,
        output_filename: str = "data\\inputs\\imagemap_background.png",
        output_size: tuple[int, int] = (1920, 1080),
        max_zoom: int = 19,
    ) -> tuple[str, tuple[float, float, float, float], tuple[int, int]]:
        """
        Forces the map boundaries into a perfect 16:9 aspect ratio, fetches the tiles, 
        and saves them directly via PIL (bypassing matplotlib entirely to avoid 
        rendering bugs).
        """
        import math # Ensured locally in case it's missing at the top of the file

        out_w, out_h = output_size
        if abs((out_w / out_h) - (16.0 / 9.0)) > 0.01:
            raise ValueError(
                f"output_size {output_size} is not a 16:9 ratio "
                f"(try (1920, 1080), (1280, 720), or (960, 540))."
            )

        print(f"Calculating 16:9 aspect ratio boundaries (target {out_w}x{out_h})...")

        # FIX: Adjusted to use the actual keys returned by get_bounding_box()
        w = bounding_box.get("w", bounding_box.get("min_lon"))
        s = bounding_box.get("s", bounding_box.get("min_lat"))
        e = bounding_box.get("e", bounding_box.get("max_lon"))
        n = bounding_box.get("n", bounding_box.get("max_lat"))

        # --- MINIMUM COVERAGE GUARD ---
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
        
        # Setup cache dir safely
        cache_dir = Path("data\\caches\\contextily")
        cache_dir.mkdir(exist_ok=True) 
        cx.set_cache_dir(str(cache_dir))

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
                img, extent = cx.bounds2img(w, s, e, n, ll=True, source=self.provider, zoom=optimal_zoom, use_cache=str(cache_dir)) 
                break  
            except Exception as download_error:
                print(f"Zoom {optimal_zoom} failed ({download_error}). Lowering zoom by 1...")
                optimal_zoom -= 1

        if img is None or extent is None:
            raise RuntimeError("Failed to download map tiles at any zoom level.")

        # --- THE FIX: USE PIL DIRECTLY ---
        # Bypasses matplotlib entirely, resizing the raw tile array exactly to the requested output_size.
        img_pil = Image.fromarray(img)
        img_pil = img_pil.resize(output_size, Image.LANCZOS)
        
        # Save as a standard RGB PNG (dropping the alpha channel to prevent transparency rendering issues)
        img_pil.convert("RGB").save(output_filename)

        print(f" Success! 16:9 map saved to: {os.path.abspath(output_filename)}")
        print(f" Map Extent (Web Mercator): {extent}")
        print(f" Saved image size: {output_size[0]}x{output_size[1]}px")

        return output_filename, extent, (output_size[0], output_size[1])

    @staticmethod
    def _crop_to_aspect_ratio(img: np.ndarray, ext: tuple, target_ratio: float) -> tuple[np.ndarray, tuple]:
        """
        Center-crops the fetched tile image to `target_ratio` (width/height).
        Returns the cropped image AND a geometrically updated Web Mercator extent.
        """
        h, w = img.shape[:2]
        min_x, max_x, min_y, max_y = ext
        current_ratio = w / h

        if abs(current_ratio - target_ratio) < 1e-6:
            return img, ext  # already correct, avoid a needless copy

        if current_ratio > target_ratio:
            # Too wide - crop left/right, keep full height.
            target_w = int(round(h * target_ratio))
            x0 = (w - target_w) // 2
            
            # Calculate how many meters each pixel represents to adjust the bounds
            meters_per_px_x = (max_x - min_x) / w
            new_min_x = min_x + (x0 * meters_per_px_x)
            new_max_x = max_x - ((w - target_w - x0) * meters_per_px_x)
            
            return img[:, x0:x0 + target_w], (new_min_x, new_max_x, min_y, max_y)
        else:
            # Too tall - crop top/bottom, keep full width.
            target_h = int(round(w / target_ratio))
            y0 = (h - target_h) // 2
            
            meters_per_px_y = (max_y - min_y) / h
            # Remember: min_y is South (bottom), max_y is North (top)
            new_max_y = max_y - (y0 * meters_per_px_y)
            new_min_y = min_y + ((h - target_h - y0) * meters_per_px_y)
            
            return img[y0:y0 + target_h, :], (min_x, max_x, new_min_y, new_max_y)

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
    import math # Ensuring it's here just in case!
    
    print(f"Calculating map boundaries for Center: {lat}, {lon} (Radius: {radius_meters}m)")

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
    provider = cx.providers.Esri.WorldImagery
    
    os.makedirs(CACHE_DIR, exist_ok=True)
    cx.set_cache_dir(str(CACHE_DIR))

    optimal_zoom = 18

    print("Fetching high-detail map tiles...")
    img = None
    extent = None
    
    while optimal_zoom > 0:
        try:
            print(f"Trying zoom level {optimal_zoom}...")
            img, extent = cx.bounds2img(
                w, s, e, n, 
                ll=True, 
                zoom=optimal_zoom,  
                source=provider,
                use_cache=str(CACHE_DIR)  
            )
            break
        except Exception as download_error:
            print(f"Zoom {optimal_zoom} failed ({download_error}). Lowering zoom by 1...")
            optimal_zoom -= 1

    if img is None or extent is None:
        raise RuntimeError("Failed to download map tiles at any zoom level.")

    # 4. RENDER AND SAVE VIA PIL (Fixing the blank screen bug)
    img_pil = Image.fromarray(img)
    img_pil = img_pil.resize(output_size, Image.LANCZOS)
    
    # Save as a standard RGB PNG
    img_pil.convert("RGB").save(output_filename)

    print(f" Success! Residential map saved to: {os.path.abspath(output_filename)}")
    return extent

def generate_maps_from_waypoints(
    json_config_path: str, 
    output_dir: str = "data/outputs",
    radius_meters: int = 400,
    output_size: tuple[int, int] = (1920, 1080)
) -> list[dict]:
    """
    Reads the project JSON config and generates a highly detailed residential map 
    centered exactly on each waypoint.
    """
    # 1. Load the JSON config
    with open(json_config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    waypoints = config.get("waypoints", [])
    
    if not waypoints:
        print("No waypoints found in the JSON config. Skipping residential maps.")
        return []

    print(f"📍 Found {len(waypoints)} waypoints in config. Generating maps...")
    os.makedirs(output_dir, exist_ok=True)
    results = []
    
    # 2. Iterate through each waypoint in the JSON
    for i, wp in enumerate(waypoints):
        # Extract the exact coordinates and label from the JSON
        lat = wp["lat"]
        lon = wp["lng"]
        # Fallback to a numbered name if the label is empty
        label = wp.get("label", f"waypoint_{i+1}") 
        
        # Clean the label so it is safe for filenames
        safe_label = "".join(c for c in label if c.isalnum() or c in (' ', '_')).rstrip()
        out_name = os.path.join(output_dir, f"res_map_{safe_label}.png")
        
        print(f"\n--- Generating Map for Waypoint '{label}' ---")
        
        # 3. Call your working get_residential_map function
        extent = get_residential_map(
            lat=lat,
            lon=lon,
            radius_meters=radius_meters,
            output_filename=out_name,
            output_size=output_size
        )
        
        # 4. Save the results for the video renderer
        results.append({
            "waypoint_label": label,
            "lat": lat,
            "lon": lon,
            "map_file": out_name,
            "extent": extent,
            "freeze_seconds": wp.get("freeze_seconds", 0)
        })
        
    print(f"\n✅ Finished generating {len(results)} waypoint maps!")
    return results