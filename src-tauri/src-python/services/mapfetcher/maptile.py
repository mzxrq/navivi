"""
Tile Downloader and Map Fetcher Service (map_tile.py)
---------------------------------------------------------------------------
Handles downloading map tiles and fetching map images for route visualization.
---------------------------------------------------------------------------
"""

# [I/O] Import libraries for map tile downloading and fetching
import os
from pathlib import Path
import contextily as cx  # type: ignore
from dotenv import load_dotenv
from PIL import Image
import math
from typing import Dict, Tuple
import pandas as pd
import numpy as np

# [I/O] Import service dependencies for Integration
from services.logger.logger import setup_logger

# [Utility] Log setup for debugging and monitoring
logger = setup_logger("MapTile")

# Load src-python/.env (MAPBOX_API_KEY, etc.) into the process environment.
# Explicit path rather than dotenv's auto-search, since the CWD this runs
# from (launched by the Tauri sidecar) isn't guaranteed to be src-python.
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

class TileDownloader:
    """Handles downloading map tiles and fetching map images for route visualization."""

    # [Final] Constants for map tile downloading and geometry processing
    PROVIDER = cx.providers.Esri.WorldStreetMap  # type: ignore
    MAX_ZOOM_LEVEL = 19
    MAPBOX_DEFAULT_STYLE = "mapbox/streets-v12"

    # [Initialization] Initialize the TileDownloader with job configuration
    def __init__(self, job_config, provider=None):
        self.job_config = job_config
        settings = (job_config.get("settings", {}) if job_config else {}) or {}

        if provider is not None:
            self.provider = provider
        else:
            self.provider = self._build_provider(settings)

        base_path = Path(self.job_config.get("directory_path", "data/caches/contextily"))
        # settings.tile_cache_dir lets a project point the cache somewhere
        # else (e.g. a cache shared across projects); relative paths are
        # resolved against directory_path so they still land inside the
        # project folder by default. Otherwise: <directory_path>/cache.
        cache_override = settings.get("tile_cache_dir")
        if cache_override:
            override_path = Path(cache_override)
            self.cache_dir = (
                override_path if override_path.is_absolute() else base_path / override_path
            ).resolve()
        else:
            self.cache_dir = (base_path / "cache").resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # Tiles are cached to disk here keyed by (provider, z, x, y) — every
        # subsequent fetch of an already-seen tile (any provider, Mapbox
        # included) is served from disk instead of hitting the network again.
        cx.set_cache_dir(str(self.cache_dir))

    # [Map/Util] Picks Mapbox (higher-resolution, retina-capable tiles) when
    # an access token is configured, falling back to the free Esri tiles
    # otherwise. Mapbox token can come from job_config settings, or from
    # src-python/.env (MAPBOX_API_KEY / MAPBOX_ACCESS_TOKEN).
    def _build_provider(self, settings: Dict):
        token = (
            settings.get("mapbox_access_token")
            or os.environ.get("MAPBOX_API_KEY")
            or os.environ.get("MAPBOX_ACCESS_TOKEN")
        )
        if not token:
            return self.PROVIDER

        provider = cx.providers.MapBox.copy()  # type: ignore
        provider["accessToken"] = token
        provider["id"] = settings.get("mapbox_style_id", self.MAPBOX_DEFAULT_STYLE)
        # @2x pulls double-density (retina) tiles — same geographic coverage
        # per tile, roughly 4x the pixels — for a visibly sharper map at the
        # same zoom level. Off by default only if explicitly disabled.
        provider["r"] = "@2x" if settings.get("mapbox_retina", True) else ""
        self.MAX_ZOOM_LEVEL = min(self.MAX_ZOOM_LEVEL, provider.get("max_zoom", 18))
        logger.info(
            "Using Mapbox tiles (style=%s, retina=%s) for higher-resolution maps.",
            provider["id"],
            bool(provider["r"]),
        )
        return provider

    # [Map/Util] Ensure an output path has a .png extension (cx.bounds2img output is saved as PNG)
    @staticmethod
    def _force_png_path(output_filename: str) -> str:
        path = Path(output_filename)
        return str(path) if path.suffix.lower() == ".png" else str(path.with_suffix(".png"))

    # [Map/Util] Pick a tile zoom level proportional to the physical area being
    # covered. Always requesting max zoom for a large bounding box means
    # downloading a huge tile mosaic just to downsample it away, and — for
    # sparsely-mapped (e.g. rural/mountain) areas — tends to land on a
    # visibly different fallback style than the well-mapped tiles nearby.
    @staticmethod
    def _optimal_zoom_for_span(span_meters: float) -> int:
        return (
            19 if span_meters <= 300 else
            18 if span_meters <= 600 else
            17 if span_meters <= 1200 else
            16 if span_meters <= 2500 else
            15 if span_meters <= 5000 else
            14 if span_meters <= 10000 else
            13 if span_meters <= 20000 else
            12 if span_meters <= 40000 else
            11
        )

    # [Map] Fetch a single overview map image covering a whole bounding box
    def fetch_overview_image(
        self,
        bounding_box: Dict[str, float],
        output_filename: str,
        output_size: Tuple[int, int] = (1920, 1080),
        max_zoom: int = 20,
    ) -> Tuple[str, Tuple[float, float, float, float], Tuple[int, int]]:
        """Fetches a single map image covering `bounding_box`, cropped/resized to `output_size`."""
        w, s, e, n = (
            bounding_box["min_lon"],
            bounding_box["min_lat"],
            bounding_box["max_lon"],
            bounding_box["max_lat"],
        )

        out_w, out_h = output_size
        target_ratio = out_w / out_h
        center_lat = (s + n) / 2.0
        lon_scale = math.cos(math.radians(center_lat))
        current_ratio = ((e - w) * lon_scale) / (n - s)

        if current_ratio < target_ratio:
            expansion = (((n - s) * target_ratio) / lon_scale - (e - w)) / 2.0
            w, e = w - expansion, e + expansion
        else:
            expansion = (((e - w) * lon_scale) / target_ratio - (n - s)) / 2.0
            s, n = s - expansion, n + expansion

        meters_per_deg_lat = 111_320.0
        meters_per_deg_lon = 111_320.0 * lon_scale
        span_meters = max((n - s) * meters_per_deg_lat, (e - w) * meters_per_deg_lon)
        zoom = min(max_zoom, self.MAX_ZOOM_LEVEL, self._optimal_zoom_for_span(span_meters))
        img, extent = None, None
        while zoom > 0:
            try:
                img, extent = cx.bounds2img(
                    w, s, e, n, ll=True, source=self.provider,
                    zoom=zoom, use_cache=str(self.cache_dir)
                )
                break
            except Exception:
                zoom -= 1

        if img is None or extent is None:
            raise RuntimeError("Failed to download overview map tiles.")

        final_path = self._force_png_path(output_filename)
        cropped_img, new_extent = self._crop_to_aspect_ratio(img, extent, target_ratio)

        Image.fromarray(cropped_img).resize(
            output_size, Image.Resampling.LANCZOS
        ).convert("RGB").save(final_path)

        return final_path, new_extent, output_size

    # [Map] Fetch a residential chunk image based on a DataFrame of lat/lon points
    def fetch_residential_chunk(
        self,
        chunk_df: pd.DataFrame,
        output_filename: str,
        output_size: Tuple[int, int] = (1920, 1080),
    ) -> Tuple[float, float, float, float]:
        """Fetches and crops map tiles for a specific route segment, ensuring proper aspect ratio."""
        
        if chunk_df.empty:
            raise ValueError("Chunk DataFrame is empty.")

        # 1. Calculate Bounding Box with Padding
        min_lat = min(chunk_df["latitude"].min(), chunk_df["latitude"].iloc[0], chunk_df["latitude"].iloc[-1])
        max_lat = max(chunk_df["latitude"].max(), chunk_df["latitude"].iloc[0], chunk_df["latitude"].iloc[-1])
        min_lon = min(chunk_df["longitude"].min(), chunk_df["longitude"].iloc[0], chunk_df["longitude"].iloc[-1])
        max_lon = max(chunk_df["longitude"].max(), chunk_df["longitude"].iloc[0], chunk_df["longitude"].iloc[-1])

        lat_span, lon_span = max_lat - min_lat, max_lon - min_lon
        center_lat = (min_lat + max_lat) / 2.0

        # Apply 3% padding around the route segment
        s, n = min_lat - lat_span * 0.03, max_lat + lat_span * 0.03
        w, e = min_lon - lon_span * 0.03, max_lon + lon_span * 0.03

        # 2. Determine Optimal Zoom based on physical span
        meters_per_deg_lat = 111_320.0
        meters_per_deg_lon = 111_320.0 * math.cos(math.radians(center_lat))
        span_meters = max(lat_span * meters_per_deg_lat, lon_span * meters_per_deg_lon)

        optimal_zoom = (
            19 if span_meters <= 300 else
            18 if span_meters <= 600 else
            17 if span_meters <= 1200 else
            16 if span_meters <= 2500 else 15
        )

        # 3. Adjust Bounding Box to Target Aspect Ratio
        out_w, out_h = output_size
        target_ratio = out_w / out_h
        lon_scale = math.cos(math.radians(center_lat))
        current_ratio = ((e - w) * lon_scale) / (n - s)

        if current_ratio < target_ratio:
            expansion = (((n - s) * target_ratio) / lon_scale - (e - w)) / 2.0
            w, e = w - expansion, e + expansion
        else:
            expansion = (((e - w) * lon_scale) / target_ratio - (n - s)) / 2.0
            s, n = s - expansion, n + expansion

        # 4. Fetch Map Tiles with Fallback
        img, extent = None, None
        while optimal_zoom > 0:
            try:
                img, extent = cx.bounds2img(
                    w, s, e, n, ll=True, source=self.provider, 
                    zoom=optimal_zoom, use_cache=str(self.cache_dir)
                )
                break
            except Exception:
                optimal_zoom -= 1

        if img is None or extent is None:
            raise RuntimeError("Failed to download map tiles for chunk.")

        # 5. Crop, Resize, and Save Image
        final_path = self._force_png_path(output_filename)
        cropped_img, new_extent = self._crop_to_aspect_ratio(img, extent, target_ratio)
        
        Image.fromarray(cropped_img).resize(
            output_size, Image.Resampling.LANCZOS
        ).convert("RGB").save(final_path)

        return new_extent

    # [Map/Util] Crop an image to a specific aspect ratio and adjust the extent accordingly
    def _crop_to_aspect_ratio(
        self, img: np.ndarray, ext: Tuple, target_ratio: float, **kwargs
    ) -> Tuple[np.ndarray, Tuple]:
        h, w = img.shape[:2]
        min_x, max_x, min_y, max_y = ext
        current_ratio = w / h
        if abs(current_ratio - target_ratio) < 1e-6:
            return img, ext

        if current_ratio > target_ratio:
            target_w = int(round(h * target_ratio))
            x0 = (w - target_w) // 2
            meters_per_px_x = (max_x - min_x) / w
            return img[:, x0 : x0 + target_w], (
                min_x + x0 * meters_per_px_x,
                max_x - (w - target_w - x0) * meters_per_px_x,
                min_y,
                max_y,
            )
        else:
            target_h = int(round(w / target_ratio))
            y0 = (h - target_h) // 2
            meters_per_px_y = (max_y - min_y) / h
            # Image row 0 is the NORTH edge (max_y) and row (h-1) is the
            # SOUTH edge (min_y) — row index increases as Y decreases. So
            # the new top row (y0) is the new max_y, and the new bottom row
            # (y0 + target_h) is the new min_y. Returning them swapped (as
            # this did before) inverts the y-extent for every mode/tolerance
            # of vertical crop, corrupting every lat/lon -> pixel projection
            # against this image.
            return img[y0 : y0 + target_h, :], (
                min_x,
                max_x,
                min_y + (h - target_h - y0) * meters_per_px_y,
                max_y - y0 * meters_per_px_y,
            )