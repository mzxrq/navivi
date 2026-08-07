"""
GPS pipeline: map background image generator (16:9, HD, video-ready).
"""

import os
import math

import pandas as pd
import contextily as cx
import matplotlib.pyplot as plt


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


def save_map_image(bounding_box: dict, output_filename: str = "map_background.png", target_dpi: int = 300):
    """
    Forces the map boundaries into a perfect 16:9 aspect ratio, fetches the tiles
    (capped at zoom 19 and a safe tile-count budget), and saves them as a
    high-resolution, video-ready background.
    """
    print("Calculating 16:9 aspect ratio boundaries...")

    w = bounding_box["min_lon"]
    s = bounding_box["min_lat"]
    e = bounding_box["max_lon"]
    n = bounding_box["max_lat"]

    # --- MINIMUM COVERAGE GUARD (fixes low-res output on short routes) ---
    # OSM tiles top out at zoom 19 - that's the most real detail available,
    # no matter what. If the route is short, the bbox can be so small that
    # even at zoom 19 only a handful of tiles are fetched (e.g. 512x512px
    # native), which then gets stretched to fill a 4800x2700 canvas below -
    # that's not "HD", it's a small image blown up and blurry.
    # Enforce a minimum real-world span so short routes still pull enough
    # tiles at max zoom to have genuine pixel detail to work with.
    MIN_SPAN_METERS = 300  # tune to taste - bigger = more context around a short walk
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

    # --- NEW: ENABLE TILE CACHING ---
    # This will create a folder called 'map_cache' inside your 'data' folder.
    # It will store every downloaded tile here forever.
    os.makedirs("data/map_cache", exist_ok=True)
    cx.set_cache_dir("data/map_cache")
    # --------------------------------

    # --- CALCULATE AND CAP ZOOM AT 19 ---
    print("Calculating optimal zoom level...")
    optimal_zoom = 19

    # Find the highest zoom that keeps tile downloads under a safe limit (~30 tiles)
    for z in range(19, 0, -1):
        if cx.howmany(w, s, e, n, z, ll=True) <= 30:
            optimal_zoom = z
            break

    # Hard cap to ensure it NEVER goes above 19
    if optimal_zoom > 19:
        optimal_zoom = 19

    print(f"Fetching 16:9 map tiles via Contextily (Max Zoom: {optimal_zoom})...")

    img = None
    extent = None

    # Loop that tries to download the map, and lowers zoom if the server fails.
    # NOTE: the exception variable is named `download_error`, NOT `e` -
    # `e` is already the East longitude bound used in the bounds2img call
    # below, and Python 3 auto-deletes `except ... as e` after the block,
    # which would silently wipe out that longitude value on the next retry.
    while optimal_zoom > 0:
        try:
            print(f"Trying zoom level {optimal_zoom}...")
            img, extent = cx.bounds2img(w, s, e, n, ll=True, zoom=optimal_zoom, use_cache="data/map_cache") # type: ignore
            break  # Success! Exit the loop.
        except Exception as download_error:
            print(f"Zoom {optimal_zoom} failed ({download_error}). Lowering zoom by 1...")
            optimal_zoom -= 1

    if img is None:
        raise RuntimeError("Failed to download map tiles at any zoom level.")
    # -----------------------------------------

    # Lock the Matplotlib canvas to exactly 16:9 (e.g., 16 inches by 9 inches)
    fig, ax = plt.subplots(figsize=(16, 9), dpi=target_dpi)

    # Strip away all borders, margins, and axes
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    ax.axis('off')

    # Draw and save
    # aspect='auto' stretches the image to fill the 16:9 axes exactly,
    # instead of the default aspect='equal' which preserves the tile
    # grid's native (rarely-exactly-16:9) proportions and leaves bars.
    # interpolation='lanczos' smooths any residual up/downscale instead of
    # the default blocky/aliased resampling - matters most on short routes
    # where the native tile image is small relative to the output canvas.
    ax.imshow(img, extent=extent, aspect='auto', interpolation='lanczos')

    # NOTE: bbox_inches='tight' can crop the saved PNG slightly differently
    # than `extent` describes, which will throw off pixel-perfect OpenCV
    # alignment later. Since subplots_adjust already fills the figure with
    # no margins, it's safe (and more precise) to drop 'tight' entirely:
    fig.savefig(output_filename, pad_inches=0, dpi=target_dpi, transparent=True)
    plt.close(fig)

    print(f"✅ Success! 16:9 map saved to: {os.path.abspath(output_filename)}")
    print(f"🌍 Map Extent (Web Mercator): {extent}")

    return extent

# --- How to use it ---
# # 1. Convert the raw NMEA text file to CSV
# track = convert_nmea("backend\\data\\LOG00003.TXT", "data/gps_log.csv", "iblue747")

# # 2. Clean the data and extract the route DataFrame
# gps_data = clean_gps_data(track)
# route_df = gps_data["route"]

# # 3. Calculate the padded bounding box for the map
# padded_box = calculate_bounding_box(route_df, padding_percent=0.15)

# # 4. Fetch and save the high-resolution map image
# map_extent = save_map_image(
#     bounding_box=padded_box,
#     output_filename="data/final_map.jpeg"
# )