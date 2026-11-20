"""
Tile Downloader and Map Fetcher Service (map_tile.py)
---------------------------------------------------------------------------
Handles downloading map tiles and fetching map images for route visualization.
---------------------------------------------------------------------------
"""

# [I/O] Import libraries for map tile downloading and fetching
import re
import time
from pathlib import Path
import contextily as cx  # type: ignore
from dotenv import load_dotenv
from services.projectfiles import tile_cache_dir
from PIL import Image
import math
from typing import Dict, NamedTuple, Optional, Tuple
import pandas as pd
import numpy as np

# [I/O] Import service dependencies for Integration
from services.logger.logger import setup_logger
from services import tuning
from services.mapfetcher.maplanguage import resolve_map_style, streets_lang
from services.mapbox_token import resolve_mapbox_token

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


_METERS_PER_DEG_LAT = 111_320.0
# 20% breathing room on top of the half-extent: covers the pin+label graphic (which extends past its anchor) and
# the unpredictable trim the tile-grid snapping and _crop_to_aspect_ratio add on any edge.
_RESIDENTIAL_BOX_PAD = 0.20


class _Pins(NamedTuple):
    """Latitude/longitude of a leg's start and end pins."""
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float


def _residential_half_extent(
    chunk_df: pd.DataFrame, pins: _Pins, bbox_multiplier: float, apply_min_zoom: bool,
) -> Tuple[float, float, float, float]:
    """(center_lat, center_lon, half_lat, half_lon) of the leg's whole path.

    Centered on the path's point-density MEAN, not its bbox midpoint: a boomerang-shaped leg left the corner away
    from the bend empty when centered on the bbox. Half-extent is the larger one-sided distance from that mean.
    """
    lat_min, lat_max = chunk_df["latitude"].min(), chunk_df["latitude"].max()
    lon_min, lon_max = chunk_df["longitude"].min(), chunk_df["longitude"].max()
    center_lat = chunk_df["latitude"].mean()
    center_lon = chunk_df["longitude"].mean()

    # [NOTE] The wide shot's multiplier (2.5) suits a multi-km leg; on a short local leg it swallowed whole
    # neighboring hills, so those legs get the tapered LOCAL multiplier (never the tight tile: multiplier 1.0).
    pin_dist_lon_scale = math.cos(math.radians((pins.start_lat + pins.end_lat) / 2.0))
    pin_distance_for_taper_m = math.hypot(
        (pins.end_lat - pins.start_lat) * 111_320.0,
        (pins.end_lon - pins.start_lon) * 111_320.0 * pin_dist_lon_scale,
    )
    if not apply_min_zoom and pin_distance_for_taper_m <= tuning.RESIDENTIAL_MIN_ZOOM_MAX_PIN_DISTANCE_M:
        bbox_multiplier = min(bbox_multiplier, tuning.RESIDENTIAL_WIDE_BBOX_MULTIPLIER_LOCAL)

    half_lat = max(center_lat - lat_min, lat_max - center_lat, 1e-9) * bbox_multiplier
    half_lon = max(center_lon - lon_min, lon_max - center_lon, 1e-9) * bbox_multiplier

    # [NOTE] A ramp loop or switchback can inflate the path bbox far past what the pins need; scale BOTH axes
    # down together (keeps the aspect) once the path diagonal exceeds RESIDENTIAL_LOOP_ZOOM_CAP x the pin diagonal.
    # Floored in absolute degrees so near-coincident pins don't cap the box to nothing.
    lon_scale_for_cap = math.cos(math.radians(center_lat))
    pin_diag = math.hypot(
        abs(pins.end_lat - pins.start_lat), abs(pins.end_lon - pins.start_lon) * lon_scale_for_cap
    )
    path_diag = math.hypot(half_lat, half_lon * lon_scale_for_cap)
    max_diag = max(
        pin_diag * tuning.RESIDENTIAL_LOOP_ZOOM_CAP,
        tuning.RESIDENTIAL_LOOP_ZOOM_CAP_MIN_DEGREES,
    )
    if path_diag > max_diag:
        shrink = max_diag / path_diag
        half_lat *= shrink
        half_lon *= shrink
    return center_lat, center_lon, half_lat, half_lon


def _fit_box_to_ratio(
    w: float, s: float, e: float, n: float, center_lat: float, target_ratio: float,
) -> Tuple[float, float, float, float]:
    """Widens or heightens the (w, s, e, n) box to the target aspect ratio."""
    lon_scale = math.cos(math.radians(center_lat))
    current_ratio = ((e - w) * lon_scale) / (n - s)
    if current_ratio < target_ratio:
        expansion = (((n - s) * target_ratio) / lon_scale - (e - w)) / 2.0
        return w - expansion, s, e + expansion, n
    expansion = (((e - w) * lon_scale) / target_ratio - (n - s)) / 2.0
    return w, s - expansion, e, n + expansion


def _bias_box_upward(s: float, n: float, center_lat: float) -> Tuple[float, float]:
    """Moves the box so the route's center sits in the upper part of the frame, leaving room for the summary bar."""
    lat_span = n - s
    target_fraction_from_top = 0.5 - tuning.RESIDENTIAL_MAP_BOTTOM_BAR_FRACTION / 2.0
    new_n = center_lat + target_fraction_from_top * lat_span
    return new_n - lat_span, new_n


def _clamp_box_to_pins(
    w: float, s: float, e: float, n: float, pins: _Pins,
) -> Tuple[float, float, float, float]:
    """Translates the box (span, so zoom, untouched) until neither pin is within RESIDENTIAL_PIN_EDGE_MARGIN of an edge.

    A zigzag leaning one way can drag the path-centered box far enough to nearly cut a pin off.
    """
    lat_span, lon_span = n - s, e - w
    margin = tuning.RESIDENTIAL_PIN_EDGE_MARGIN
    for pin_lat, pin_lon in ((pins.start_lat, pins.start_lon), (pins.end_lat, pins.end_lon)):
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
    return w, s, e, n


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
        # project folder. Otherwise the cache every project shares (Documents/Navivi/Cache).
        cache_override = settings.get("tile_cache_dir")
        if cache_override:
            override_path = Path(cache_override)
            # Always its own subfolder: the 30-day sweep below deletes every old file under cache_dir, and a
            # setting like "." would otherwise point it at the project's photos, audio and exports.
            self.cache_dir = (
                (override_path if override_path.is_absolute() else base_path / override_path) / "navivi_tiles"
            ).resolve()
        else:
            self.cache_dir = tile_cache_dir().resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # Tiles are cached to disk here keyed by (provider, z, x, y) — every
        # subsequent fetch of an already-seen tile (any provider, Mapbox
        # included) is served from disk instead of hitting the network again.
        cx.set_cache_dir(str(self.cache_dir))
        _evict_stale_tiles(self.cache_dir)

    # [Map/Util] Picks Mapbox (higher-resolution, retina-capable tiles) when
    # an access token is configured, falling back to the free Esri tiles
    # otherwise. The token is the app's own (NAVIVI_MAPBOX_TOKEN, set by the
    # desktop app), then a legacy project setting, then the old env/.env names;
    # see services/mapbox_token.py.
    def _build_provider(self, settings: Dict):
        token = resolve_mapbox_token(settings)
        if not token:
            return self.PROVIDER

        provider = cx.providers.MapBox.copy()  # type: ignore
        provider["accessToken"] = token
        lang = streets_lang(self.job_config.get("map_language") if self.job_config else None)
        provider["id"] = resolve_map_style(settings, self.MAPBOX_DEFAULT_STYLE, lang, raster=True)
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

    def _fetch_stepping_down(self, w, s, e, n, zoom: int, what: str):
        """(img, extent) at `zoom`, or the next zoom down that the provider has. A refused key (401/403) fails at
        once, since every zoom would; otherwise the last error is named (key blanked) instead of a bare failure."""
        last = None
        while zoom > 0:
            try:
                return self._bounds2img_safe(w, s, e, n, zoom)
            except Exception as exc:
                last = re.sub(r"access_token=[^&\s']+", "access_token=...", f"{type(exc).__name__}: {exc}")[:300]
                if re.search(r"\b40[13] Client Error|Unauthorized|Forbidden", last):  # not a tile x/y that is 401
                    raise RuntimeError(f"The map provider refused the key ({last}). Check the Mapbox key in Settings.") from None
                zoom -= 1
        raise RuntimeError(f"Failed to download {what} ({last or 'no zoom level left'}).")

    # [Map/Util] Ensure an output path has a .png extension (cx.bounds2img output is saved as PNG)
    @staticmethod
    def _force_png_path(output_filename: str) -> str:
        path = Path(output_filename)
        return str(path) if path.suffix.lower() == ".png" else str(path.with_suffix(".png"))

    # "How many real pixels does this provider deliver for one logical
    # zoom step" — NOT the same number as the provider dict's own
    # `tileSize`/`zoomOffset` entries, and NOT simply derivable from them
    # either: textbook zoomOffset math says a 512px tile fetched at
    # zoomOffset=-1 covers exactly the same ground per logical zoom as a
    # standard 256px tile (they cancel out), but empirically contextily's
    # actual fetched mosaic for this Mapbox provider (tileSize=512,
    # zoomOffset=-1) comes back ~2x denser than that theoretical 256
    # baseline predicts, even with NO retina suffix — measured directly by
    # comparing a fetched mosaic's real meters-per-pixel against the
    # textbook C/(256*2^zoom) formula at several zoom levels. On TOP of
    # that base ~2x, a "@2x" retina suffix doubles the pixel count AGAIN
    # for the same z/x/y address (that part IS the documented, expected
    # behavior). Net: ~512 effective "tile size" with no retina, ~1024
    # with it. Getting this wrong under-corrects _optimal_zoom_for_span,
    # which returns a mosaic far bigger than `output_size` — the
    # subsequent LANCZOS downsize then crushes small label text into
    # illegibility (or nothing at all): reproduced directly, raw tiles
    # fetched at the zoom this method picked had clearly readable
    # place-name labels, yet the final stitched-and-resized overview PNG
    # showed none, because the real mosaic was ~4x wider than intended.
    _TILE_SIZE_PX = 256
    _EARTH_CIRCUMFERENCE_M = 2 * math.pi * 6378137.0
    # Empirically measured (not theoretically derived — see the multi-
    # paragraph note above): contextily's actual fetched mosaic for THIS
    # provider shape (tileSize=512, zoomOffset=-1 — cx.providers.MapBox)
    # comes back 2.537x denser, in real meters-per-pixel, than the
    # standard 256px-tile formula predicts — confirmed stable across
    # zoom 12/14/16 (ratio held at 2.537 every time, not a fluke of one
    # zoom level). Retina "@2x" multiplies pixel count by another 2x on
    # top of that, independently confirmed the same way (5.073 ≈
    # 2.537 * 2). Esri's provider (the token-less fallback) has neither
    # `tileSize` nor `zoomOffset` set — contextily's own plain-256
    # defaults apply there, so this calibration must NOT be applied to it.
    _MAPBOX_TILESIZE512_RESOLUTION_RATIO = 2.537

    # [Map/Util] Pick a tile zoom level proportional to the physical area
    # being covered, continuously rather than in coarse steps: solves for
    # the zoom at which `output_px` pixels would span `span_meters` and
    # rounds UP to the nearest whole zoom. A fixed step table (the old
    # behavior — kept as a documented illustration of the problem, not
    # live code) sized correctly at the TOP of each bucket but left a span
    # near the BOTTOM of one stuck at the same zoom as a span nearly twice
    # as large: e.g. span=10001m and span=19999m both landed on zoom 14
    # despite a 2x difference in physical coverage, so the smaller one's
    # fetched tile mosaic came back well under `output_size` and had to be
    # upscaled (blurry, and visibly LESS zoomed-in/detailed than the
    # bucket's zoom number would suggest) to fill the frame. Rounding up
    # (never down) guarantees the fetched mosaic is always at least
    # `output_size` — see the `retina` note above for the other half of
    # getting this right (not OVER-fetching either).
    @classmethod
    def _optimal_zoom_for_span(
        cls,
        span_meters: float,
        output_px: int = 1920,
        retina: bool = False,
        tilesize_512_quirk: bool = False,
    ) -> int:
        if span_meters <= 0:
            return cls.MAX_ZOOM_LEVEL
        tile_px = cls._TILE_SIZE_PX
        if tilesize_512_quirk:
            tile_px *= cls._MAPBOX_TILESIZE512_RESOLUTION_RATIO
        if retina:
            tile_px *= 2
        exact = math.log2(
            cls._EARTH_CIRCUMFERENCE_M * output_px / (tile_px * span_meters)
        )
        return max(1, math.ceil(exact))

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
        is_retina = bool(self.provider.get("r")) if hasattr(self.provider, "get") else False
        tilesize_512_quirk = (
            hasattr(self.provider, "get") and self.provider.get("tileSize") == 512
        )
        zoom = min(
            max_zoom,
            self.MAX_ZOOM_LEVEL,
            self._optimal_zoom_for_span(
                span_meters, out_w, retina=is_retina,
                tilesize_512_quirk=tilesize_512_quirk,
            ),
        )
        img, extent = self._fetch_stepping_down(w, s, e, n, zoom, "overview map tiles")

        final_path = self._force_png_path(output_filename)
        # Tiles come in whole-tile chunks, so the mosaic is routinely much
        # wider/taller than the padded bbox that was asked for - and by a
        # different amount per side, depending on where tile edges fall. A
        # padded edge landing a few metres past a tile edge pulled in a whole
        # extra tile (~5km) on that side, and _crop_to_aspect_ratio below
        # only ever trims ONE axis to the target ratio, so that extra tile
        # stayed in the frame (padding looked like it "extended the left only,
        # way too much"). Cropping to the requested window first makes the
        # padding mean what it says, on every side, at any value.
        cropped_img, new_extent = self._crop_to_box(img, extent, (w, s, e, n), target_ratio)

        Image.fromarray(cropped_img).resize(
            output_size, Image.Resampling.LANCZOS
        ).convert("RGB").save(final_path)

        return final_path, new_extent, output_size

    def _crop_to_box(self, img: np.ndarray, extent: Tuple, box: Tuple, target_ratio: float) -> Tuple[np.ndarray, Tuple]:
        """The mosaic cut to the lon/lat `box` (w, s, e, n) it was fetched for, then to `target_ratio` around the box's
        centre: the mosaic overhangs the box by up to a tile, and by a different amount on each side."""
        w, s, e, n = box
        # Web Mercator (EPSG:3857) metres, `extent`'s own units (RouteGeometryProcessor.project_latlon_to_pixel's formula).
        r = 6378137.0
        to_x = lambda lon: lon * (r * math.pi / 180.0)
        to_y = lambda lat: math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * r
        img, extent = self._crop_to_window(img, extent, (to_x(w), to_x(e), to_y(s), to_y(n)))
        return self._crop_to_aspect_ratio(img, extent, target_ratio, target_center=(to_x((w + e) / 2.0), to_y((s + n) / 2.0)))

    @staticmethod
    def _crop_to_window(
        img: np.ndarray, ext: Tuple, window: Tuple
    ) -> Tuple[np.ndarray, Tuple]:
        """Crops the tile mosaic `img` (extent `ext` = min_x, max_x, min_y,
        max_y in mercator metres) down to `window` (same convention),
        clamped to what the mosaic actually covers. Returns the cropped image
        and its own extent, so pixel <-> map projections stay correct."""
        h, w = img.shape[:2]
        min_x, max_x, min_y, max_y = ext
        wx0, wx1, wy0, wy1 = window
        mpp_x = (max_x - min_x) / w
        mpp_y = (max_y - min_y) / h
        # Row 0 is the NORTH edge (max_y); columns grow eastward.
        x0 = max(0, int(math.floor((wx0 - min_x) / mpp_x)))
        x1 = min(w, int(math.ceil((wx1 - min_x) / mpp_x)))
        y0 = max(0, int(math.floor((max_y - wy1) / mpp_y)))
        y1 = min(h, int(math.ceil((max_y - wy0) / mpp_y)))
        if x1 - x0 < 2 or y1 - y0 < 2:  # a degenerate window - leave the mosaic alone
            return img, ext
        return img[y0:y1, x0:x1], (
            min_x + x0 * mpp_x,
            min_x + x1 * mpp_x,
            max_y - y1 * mpp_y,
            max_y - y0 * mpp_y,
        )

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

        pins = _Pins(
            chunk_df["latitude"].iloc[0], chunk_df["longitude"].iloc[0],
            chunk_df["latitude"].iloc[-1], chunk_df["longitude"].iloc[-1],
        )
        center_lat, center_lon, half_lat, half_lon = _residential_half_extent(
            chunk_df, pins, bbox_multiplier, apply_min_zoom
        )
        s, n = center_lat - half_lat * (1 + _RESIDENTIAL_BOX_PAD), center_lat + half_lat * (1 + _RESIDENTIAL_BOX_PAD)
        w, e = center_lon - half_lon * (1 + _RESIDENTIAL_BOX_PAD), center_lon + half_lon * (1 + _RESIDENTIAL_BOX_PAD)
        optimal_zoom = self._residential_zoom(
            (w, s, e, n), center_lat, pins, output_size[0], apply_min_zoom
        )

        out_w, out_h = output_size
        target_ratio = out_w / out_h
        w, s, e, n = _fit_box_to_ratio(w, s, e, n, center_lat, target_ratio)
        # The summary bar is only composited over the per-frame chunk tile, never the wide shot.
        if apply_min_zoom:
            s, n = _bias_box_upward(s, n, center_lat)
        w, s, e, n = _clamp_box_to_pins(w, s, e, n, pins)
        return w, s, e, n, optimal_zoom, target_ratio

    def _residential_zoom(
        self, box: Tuple[float, float, float, float], center_lat: float, pins: _Pins,
        out_w: int, apply_min_zoom: bool,
    ) -> int:
        """Zoom for the padded (w, s, e, n) box's physical span.

        Same density-calibrated formula as fetch_overview_image (see _optimal_zoom_for_span), capped by the
        provider's MAX_ZOOM_LEVEL and RESIDENTIAL_MAX_ZOOM (a "looks good" ceiling: too close reads as a block crop).
        """
        w, s, e, n = box
        lat_span, lon_span = n - s, e - w
        meters_per_deg_lon = _METERS_PER_DEG_LAT * math.cos(math.radians(center_lat))
        span_meters = max(lat_span * _METERS_PER_DEG_LAT, lon_span * meters_per_deg_lon)

        is_retina = bool(self.provider.get("r")) if hasattr(self.provider, "get") else False
        tilesize_512_quirk = (
            hasattr(self.provider, "get") and self.provider.get("tileSize") == 512
        )
        optimal_zoom = self._optimal_zoom_for_span(
            span_meters, out_w, retina=is_retina, tilesize_512_quirk=tilesize_512_quirk
        )
        optimal_zoom = min(optimal_zoom, self.MAX_ZOOM_LEVEL, tuning.RESIDENTIAL_MAX_ZOOM)

        # [NOTE] Zoom floor only for short/local legs, judged on the pin distance (immune to a detour inflating
        # the span) so a long leg isn't dragged to street level; skipped for the wide shot, which should look zoomed out.
        if apply_min_zoom:
            pin_distance_meters = math.hypot(
                (pins.end_lat - pins.start_lat) * _METERS_PER_DEG_LAT,
                (pins.end_lon - pins.start_lon) * meters_per_deg_lon,
            )
            if pin_distance_meters <= tuning.RESIDENTIAL_MIN_ZOOM_MAX_PIN_DISTANCE_M:
                optimal_zoom = max(
                    optimal_zoom, min(tuning.RESIDENTIAL_MIN_ZOOM, self.MAX_ZOOM_LEVEL)
                )
        return optimal_zoom

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
        img, extent = self._fetch_stepping_down(w, s, e, n, zoom, "map tiles for chunk")

        final_path = self._force_png_path(output_filename)
        # Centred on the box asked for, as the overview is: centred on the mosaic, a pin near an edge was cut off.
        cropped_img, new_extent = self._crop_to_box(img, extent, (w, s, e, n), target_ratio)

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
        self,
        img: np.ndarray,
        ext: Tuple,
        target_ratio: float,
        target_center: Optional[Tuple[float, float]] = None,
        **kwargs,
    ) -> Tuple[np.ndarray, Tuple]:
        """Crops the fetched tile mosaic down to `target_ratio`.

        `target_center` (mercator meters (x, y), same convention as `ext`)
        is the center of the bbox the CALLER actually asked for — pass it
        whenever known. Tile fetching snaps to whole-tile boundaries, so
        the mosaic `img`/`ext` routinely covers noticeably more than the
        requested bbox, and NOT symmetrically: which side gets the extra
        margin depends on where tile edges happen to fall, unrelated to
        where the caller's bbox actually sat. Center-cropping on the
        mosaic's OWN midpoint (the old behavior, still used as a fallback
        when `target_center` is omitted) inherits that asymmetry — it can
        trim INTO the caller's intended bbox on one side while leaving
        pointless extra margin on the other, which is exactly how a route
        with enough requested padding on paper still ended up clipped off
        the top of frame: the real crop window had silently drifted south
        of where the padding calculation assumed it would be centered.
        Centering on the caller's own target instead keeps the crop
        anchored to what was actually asked for, clamped so it never
        reads outside the fetched mosaic's own bounds.
        """
        h, w = img.shape[:2]
        min_x, max_x, min_y, max_y = ext
        current_ratio = w / h
        if abs(current_ratio - target_ratio) < 1e-6:
            return img, ext

        if current_ratio > target_ratio:
            target_w = int(round(h * target_ratio))
            meters_per_px_x = (max_x - min_x) / w
            if target_center is not None:
                cx_px = (target_center[0] - min_x) / meters_per_px_x
                x0 = int(round(cx_px - target_w / 2.0))
                x0 = max(0, min(w - target_w, x0))
            else:
                x0 = (w - target_w) // 2
            return img[:, x0 : x0 + target_w], (
                min_x + x0 * meters_per_px_x,
                max_x - (w - target_w - x0) * meters_per_px_x,
                min_y,
                max_y,
            )
        else:
            target_h = int(round(w / target_ratio))
            meters_per_px_y = (max_y - min_y) / h
            if target_center is not None:
                # Row 0 is the NORTH edge (max_y); row increases southward.
                cy_px = (max_y - target_center[1]) / meters_per_px_y
                y0 = int(round(cy_px - target_h / 2.0))
                y0 = max(0, min(h - target_h, y0))
            else:
                y0 = (h - target_h) // 2
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