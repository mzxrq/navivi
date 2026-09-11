"""
Tile Downloader and Map Fetcher Service (map_tile.py)
---------------------------------------------------------------------------
Handles downloading map tiles and fetching map images for route visualization.
---------------------------------------------------------------------------
"""

# [I/O] Import libraries for map tile downloading and fetching
import os
import time
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
from services import tuning

# [Utility] Log setup for debugging and monitoring
logger = setup_logger("MapTile")

# Load src-python/.env AND the frontend's repo-root .env (VITE_MAPBOX_TOKEN)
# into the process environment. Explicit paths rather than dotenv's
# auto-search, since the CWD this runs from (launched by the Tauri sidecar)
# isn't guaranteed to be src-python. Walk up by directory NAME (not a fixed
# `.parent` depth) so this survives future re-nesting — see
# pydeckrecorder/common.py's identical reasoning.
_src_python_dir = Path(__file__).resolve().parent
while _src_python_dir.name != "src-python" and _src_python_dir.parent != _src_python_dir:
    _src_python_dir = _src_python_dir.parent
load_dotenv(_src_python_dir / ".env")
# src-python/../.. == the repo root, where the frontend's own .env
# (VITE_MAPBOX_TOKEN) lives — loaded second so it doesn't override an
# explicit src-python/.env value already set (load_dotenv default:
# override=False), only fills in what's still missing.
load_dotenv(_src_python_dir.parent.parent / ".env")

# Tiles are cached to disk forever with no eviction otherwise — across every
# project/run this grows unbounded. Best-effort age-based sweep, run once
# per TileDownloader init (see _evict_stale_tiles below).
_TILE_CACHE_MAX_AGE_DAYS = 30


def _evict_stale_tiles(cache_dir: Path, max_age_days: float = _TILE_CACHE_MAX_AGE_DAYS) -> None:
    """Deletes cached tile files under `cache_dir` whose mtime is older than
    `max_age_days`. Best-effort and silent — a cache-cleanup failure should
    never break a render, it just means the cache grows a bit more."""
    try:
        cutoff = time.time() - (max_age_days * 86400)
        removed = 0
        for path in cache_dir.rglob("*"):
            if not path.is_file():
                continue
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                continue
        if removed:
            logger.info(
                "Evicted %d stale tile cache file(s) older than %d day(s) from %s.",
                removed, max_age_days, cache_dir,
            )
    except OSError as exc:
        logger.warning("Tile cache eviction skipped for %s: %s", cache_dir, exc)


class TileDownloader:
    """Handles downloading map tiles and fetching map images for route visualization."""

    # [Final] Constants for map tile downloading and geometry processing
    PROVIDER = cx.providers.Esri.WorldStreetMap  # type: ignore
    MAX_ZOOM_LEVEL = 19
    MAPBOX_DEFAULT_STYLE = "mapbox/streets-v12"

    # contextily's own defaults (wait=0, max_retries=2) retry a rate-limited
    # tile request twice with NO delay between attempts, then raise — which
    # our zoom-decrement fallback below would just answer by firing off yet
    # more requests at a different zoom, immediately, into the same
    # rate-limited API. Passing an actual wait here makes contextily's
    # built-in retry (see `_retryer` in contextily.tile) pause before each
    # retry instead, so a transient 429 has a real chance to clear before
    # we hit the API again.
    TILE_FETCH_WAIT_SECONDS = 1.5
    TILE_FETCH_MAX_RETRIES = 3

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
        _evict_stale_tiles(self.cache_dir)

    # [Map/Util] Picks Mapbox (higher-resolution, retina-capable tiles) when
    # an access token is configured, falling back to the free Esri tiles
    # otherwise. Mapbox token can come from job_config settings, from
    # src-python/.env (MAPBOX_API_KEY / MAPBOX_ACCESS_TOKEN), or from the
    # frontend's own repo-root .env (VITE_MAPBOX_TOKEN) — checked last so an
    # explicit backend-only override still wins, but a project with no
    # separate src-python/.env setup still picks up the same token the
    # frontend map already uses.
    def _build_provider(self, settings: Dict):
        token = (
            settings.get("mapbox_access_token")
            or os.environ.get("MAPBOX_API_KEY")
            or os.environ.get("MAPBOX_ACCESS_TOKEN")
            or os.environ.get("VITE_MAPBOX_TOKEN")
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
        self.MAX_ZOOM_LEVEL = min(self.MAX_ZOOM_LEVEL, provider.get("max_zoom", 20))
        logger.info(
            "Using Mapbox tiles (style=%s, retina=%s) for higher-resolution maps.",
            provider["id"],
            bool(provider["r"]),
        )
        return provider

    # [Map/Util] cx.bounds2img wrapper: passes an actual wait/retry budget
    # (see TILE_FETCH_WAIT_SECONDS above) so a rate-limited response gets a
    # real backoff instead of contextily's default instant double-retry.
    # On top of that, this file's own zoom-decrement loop (in
    # fetch_overview_image / fetch_residential_chunk) also backs off for a
    # beat before trying the next zoom specifically when the failure looks
    # rate-limit-shaped (HTTP 429 / "too many requests") — an unavailable
    # zoom level (a normal, non-rate-limit failure) still falls straight
    # through to the next zoom with no added delay.
    def _bounds2img_safe(self, w, s, e, n, zoom):
        try:
            return cx.bounds2img(
                w, s, e, n, ll=True, source=self.provider,
                zoom=zoom, use_cache=str(self.cache_dir),
                wait=self.TILE_FETCH_WAIT_SECONDS,
                max_retries=self.TILE_FETCH_MAX_RETRIES,
            )
        except Exception as e:
            if "429" in str(e) or "too many requests" in str(e).lower():
                logger.warning(
                    "Tile provider rate-limited us at zoom=%d; backing off %.1fs before falling back.",
                    zoom, self.TILE_FETCH_WAIT_SECONDS,
                )
                time.sleep(self.TILE_FETCH_WAIT_SECONDS)
            raise

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
            20 if span_meters <= 300 else
            19 if span_meters <= 600 else
            18 if span_meters <= 1200 else
            17 if span_meters <= 2500 else
            16 if span_meters <= 5000 else
            15 if span_meters <= 10000 else
            14 if span_meters <= 20000 else
            13 if span_meters <= 40000 else
            12 if span_meters <= 80000 else
            11
        )

    # [Map] Fetch a single overview map image covering a whole bounding box
    def fetch_overview_image(
        self,
        bounding_box: Dict[str, float],
        output_filename: str,
        output_size: Tuple[int, int] = (1920, 1080),
        max_zoom: int = 18,
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
        # lon_scale corrects for the Mercator projection's east-west
        # compression away from the equator, so degrees of longitude are
        # compared to degrees of latitude on the same physical (meters)
        # footing rather than raw degree counts.
        lon_scale = math.cos(math.radians(center_lat))
        current_ratio = ((e - w) * lon_scale) / (n - s)

        # [NOTE] [Map] Grows whichever axis (lon or lat span) is too narrow for the target aspect ratio, centered on the existing bbox, rather than cropping the wider axis down.
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
        # [HACK] [Map] Swallows any fetch failure (rate-limit, unavailable zoom, network error alike) and just steps down a zoom level until one succeeds — masks the real cause of a failure that isn't zoom-related.
        while zoom > 0:
            try:
                img, extent = self._bounds2img_safe(w, s, e, n, zoom)
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

    # [Map] Shared bbox/zoom computation for a residential chunk — split out
    # of fetch_residential_chunk so fetch_residential_wide (the leg's wide
    # establishing shot) can reuse the exact same logic with a looser
    # bbox and no zoom floor, instead of duplicating it.
    def _compute_residential_bbox(
        self,
        chunk_df: pd.DataFrame,
        output_size: Tuple[int, int],
        bbox_multiplier: float = 1.0,
        apply_min_zoom: bool = True,
    ) -> Tuple[float, float, float, float, int, float]:
        if chunk_df.empty:
            raise ValueError("Chunk DataFrame is empty.")

        # 1. Calculate a Bounding Box Centered on the Leg's FULL PATH
        #
        # Centered on the path's own min/max extent (every point of the
        # actual route, not just its two endpoints) — the whole route
        # line stays centered and fully in-frame. The tradeoff (and it IS
        # one — see git history if this needs revisiting): a leg whose
        # path loops or bulges well to one side of the straight line
        # between its start/end pins can leave one of those pins sitting
        # closer to an edge than the other, since the box is sized and
        # centered around the path's own shape rather than symmetric
        # around the two pins.
        start_lat, end_lat = chunk_df["latitude"].iloc[0], chunk_df["latitude"].iloc[-1]
        start_lon, end_lon = chunk_df["longitude"].iloc[0], chunk_df["longitude"].iloc[-1]
        lat_min, lat_max = chunk_df["latitude"].min(), chunk_df["latitude"].max()
        lon_min, lon_max = chunk_df["longitude"].min(), chunk_df["longitude"].max()
        center_lat = (lat_min + lat_max) / 2.0
        center_lon = (lon_min + lon_max) / 2.0

        # Half-extent from the path's own full bounding box — not the
        # straight-line distance between just the two pins — so a loop or
        # detour is guaranteed to stay in frame instead of running off an
        # edge. `bbox_multiplier` widens this for the wide establishing
        # shot (fetch_residential_wide) without duplicating any of this
        # logic.
        half_lat = max((lat_max - lat_min) / 2.0, 1e-9) * bbox_multiplier
        half_lon = max((lon_max - lon_min) / 2.0, 1e-9) * bbox_multiplier

        # Capped against the straight-line pin distance — an on/off-ramp
        # loop or a wide switchback can inflate the path's own bounding
        # box far beyond what the two pins actually need, zooming the
        # whole leg out to fit a loop that only briefly swings wide
        # (leaving most of the frame empty the rest of the time). Scaling
        # BOTH axes down together (not clamping each independently, which
        # would distort the box's own aspect ratio) once the path's
        # diagonal extent exceeds RESIDENTIAL_LOOP_ZOOM_CAP times the
        # pins' own diagonal distance keeps the center on the path's
        # shape (per the framing above) while still stopping a loop from
        # dominating the frame the way it did before this cap existed.
        lon_scale_for_cap = math.cos(math.radians(center_lat))
        pin_diag = math.hypot(
            abs(end_lat - start_lat), abs(end_lon - start_lon) * lon_scale_for_cap
        )
        path_diag = math.hypot(half_lat, half_lon * lon_scale_for_cap)
        # Floored in absolute degrees (not just scaled off pin_diag) so a
        # leg whose two pins sit almost on top of each other (a loop that
        # returns nearly to its own start) doesn't get capped down to a
        # near-zero box — RESIDENTIAL_LOOP_ZOOM_CAP_MIN_DEGREES is roughly
        # 55m, a sane lower bound on how tight the cap itself can squeeze.
        max_diag = max(
            pin_diag * tuning.RESIDENTIAL_LOOP_ZOOM_CAP,
            tuning.RESIDENTIAL_LOOP_ZOOM_CAP_MIN_DEGREES,
        )
        if path_diag > max_diag:
            shrink = max_diag / path_diag
            half_lat *= shrink
            half_lon *= shrink

        # 20% breathing room on top of that half-extent — covers both the
        # pin+label graphic (which extends past its anchor point) and the
        # further, not-precisely-predictable trim the fetch-then-crop
        # steps below (tile-grid snapping, then _crop_to_aspect_ratio) can
        # each add on any edge.
        _PAD = 0.20
        s, n = center_lat - half_lat * (1 + _PAD), center_lat + half_lat * (1 + _PAD)
        w, e = center_lon - half_lon * (1 + _PAD), center_lon + half_lon * (1 + _PAD)
        lat_span, lon_span = n - s, e - w

        # 2. Determine Optimal Zoom based on physical span — thresholds
        # shifted down (vs. the overview's table) so the same physical span
        # picks a higher zoom level here, capped by the provider's own
        # MAX_ZOOM_LEVEL just like fetch_overview_image does.
        meters_per_deg_lat = 111_320.0
        meters_per_deg_lon = 111_320.0 * math.cos(math.radians(center_lat))
        span_meters = max(lat_span * meters_per_deg_lat, lon_span * meters_per_deg_lon)

        optimal_zoom = (
            20 if span_meters <= 150 else
            19 if span_meters <= 350 else
            18 if span_meters <= 700 else
            17 if span_meters <= 1400 else
            16 if span_meters <= 3000 else
            15 if span_meters <= 6000 else
            14 if span_meters <= 12000 else
            13 if span_meters <= 25000 else
            12 if span_meters <= 50000 else
            11
        )
        # Ceiling independent of the provider's own MAX_ZOOM_LEVEL (a
        # capability limit, not a "looks good" limit) — a very short/tight
        # leg's span could otherwise reach right up to that provider
        # ceiling, framing so close the map reads as an abstract
        # block-level crop instead of a recognizable street view.
        optimal_zoom = min(optimal_zoom, self.MAX_ZOOM_LEVEL, tuning.RESIDENTIAL_MAX_ZOOM)

        # Zoom floor only for genuinely short/local legs — gated on the
        # straight-line distance between the two pins (immune to a
        # detour/loop inflating the padded span above) so a long car/ferry
        # leg never gets dragged up to a street-level zoom, which would
        # multiply its tile count ~4x per zoom level jumped. Skipped
        # entirely for the wide establishing shot (apply_min_zoom=False) —
        # that tile is meant to look zoomed OUT, so a min-zoom floor would
        # defeat its whole purpose.
        if apply_min_zoom:
            pin_distance_meters = math.hypot(
                (end_lat - start_lat) * meters_per_deg_lat,
                (end_lon - start_lon) * meters_per_deg_lon,
            )
            if pin_distance_meters <= tuning.RESIDENTIAL_MIN_ZOOM_MAX_PIN_DISTANCE_M:
                optimal_zoom = max(
                    optimal_zoom, min(tuning.RESIDENTIAL_MIN_ZOOM, self.MAX_ZOOM_LEVEL)
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

        # Bias the box upward (toward higher latitude) so the route's own
        # center lands in the upper portion of the frame instead of dead
        # center — leaves genuine breathing room at the bottom for the
        # summary bar to sit over without visually cutting into what
        # would otherwise read as a centered route. Only for the actual
        # per-frame chunk tile (apply_min_zoom=True) — the wide
        # establishing shot never has the bar composited on top of it.
        if apply_min_zoom:
            lat_span = n - s
            target_fraction_from_top = 0.5 - tuning.RESIDENTIAL_MAP_BOTTOM_BAR_FRACTION / 2.0
            new_n = center_lat + target_fraction_from_top * lat_span
            s, n = new_n - lat_span, new_n

        # Safety clamp: neither pin is allowed to end up within
        # RESIDENTIAL_PIN_EDGE_MARGIN of any edge, however the box above
        # got centered/capped — a zigzagging path (several switchbacks
        # all leaning the same direction, none of them a single dominant
        # loop the cap above would catch) can still drag the path-bbox
        # center far enough that a pin ends up almost cut off. Translates
        # the box (same span, so zoom is untouched) just enough to bring
        # an offending pin back to that margin — path-centered framing is
        # still the default the rest of this function computes, this
        # only intervenes in the specific case a pin would otherwise be
        # nearly or fully out of frame.
        lat_span, lon_span = n - s, e - w
        margin = tuning.RESIDENTIAL_PIN_EDGE_MARGIN
        for pin_lat, pin_lon in ((start_lat, start_lon), (end_lat, end_lon)):
            lo, hi = s + lat_span * margin, n - lat_span * margin
            if pin_lat < lo:
                s, n = s - (lo - pin_lat), n - (lo - pin_lat)
            elif pin_lat > hi:
                s, n = s + (pin_lat - hi), n + (pin_lat - hi)
            lo, hi = w + lon_span * margin, e - lon_span * margin
            if pin_lon < lo:
                w, e = w - (lo - pin_lon), e - (lo - pin_lon)
            elif pin_lon > hi:
                w, e = w + (pin_lon - hi), e + (pin_lon - hi)

        return w, s, e, n, optimal_zoom, target_ratio

    # [Map/Util] Fetch (with zoom-decrement fallback), crop, resize, and
    # save — the actual network + image-IO half of a residential fetch,
    # shared by fetch_residential_chunk and fetch_residential_wide.
    def _fetch_and_save(
        self,
        w: float, s: float, e: float, n: float,
        zoom: int,
        target_ratio: float,
        output_filename: str,
        output_size: Tuple[int, int],
    ) -> Tuple[float, float, float, float]:
        img, extent = None, None
        while zoom > 0:
            try:
                img, extent = self._bounds2img_safe(w, s, e, n, zoom)
                break
            except Exception:
                zoom -= 1

        if img is None or extent is None:
            raise RuntimeError("Failed to download map tiles for chunk.")

        final_path = self._force_png_path(output_filename)
        cropped_img, new_extent = self._crop_to_aspect_ratio(img, extent, target_ratio)

        Image.fromarray(cropped_img).resize(
            output_size, Image.Resampling.LANCZOS
        ).convert("RGB").save(final_path)

        return new_extent

    # [Map] Fetch a residential chunk image based on a DataFrame of lat/lon points
    def fetch_residential_chunk(
        self,
        chunk_df: pd.DataFrame,
        output_filename: str,
        output_size: Tuple[int, int] = (1920, 1080),
    ) -> Tuple[float, float, float, float]:
        """Fetches and crops map tiles for a specific route segment, ensuring proper aspect ratio."""
        w, s, e, n, zoom, target_ratio = self._compute_residential_bbox(chunk_df, output_size)
        return self._fetch_and_save(w, s, e, n, zoom, target_ratio, output_filename, output_size)

    # [Map] Wide establishing-shot variant of fetch_residential_chunk — same
    # chunk, a looser bbox (tuning.RESIDENTIAL_WIDE_BBOX_MULTIPLIER) and no
    # min-zoom floor, so it reads as "zoomed out" next to the tight tile
    # it's cross-faded into (see waypoints.py's leg intro sequence).
    def fetch_residential_wide(
        self,
        chunk_df: pd.DataFrame,
        output_filename: str,
        output_size: Tuple[int, int] = (1920, 1080),
    ) -> Tuple[float, float, float, float]:
        w, s, e, n, zoom, target_ratio = self._compute_residential_bbox(
            chunk_df,
            output_size,
            bbox_multiplier=tuning.RESIDENTIAL_WIDE_BBOX_MULTIPLIER,
            apply_min_zoom=False,
        )
        return self._fetch_and_save(w, s, e, n, zoom, target_ratio, output_filename, output_size)

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