"""
MapFetcher Service (mapfetcher.py)
---------------------------------------------------------------------------
Orchestrates geographic data parsing and image downloading.
Imports core geometry and tile downloading from map_engine.py.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import concurrent.futures
import math
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import pandas as pd

from services.mapfetcher.mapengine import RouteGeometry, RoutePacing, TileDownloader
from services.config.job_config import JobConfigManager
from services.logger.logger import setup_logger
from services.logger.progress import tracker
from services import tuning
from services.mapbox_token import resolve_mapbox_token
from services.mapfetcher.maplanguage import needs_gl_labels, resolve_map_style, streets_lang
from services.vdoprocessing.stopby_visits import visits_stopby

# Logging configuration
logger = setup_logger("MapFetcher")

_EARTH_RADIUS_M = 6371000.0


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2.0) ** 2
    )
    return _EARTH_RADIUS_M * (2.0 * math.asin(math.sqrt(a)))


def _boundary_positions(waypoints: List[Dict], merge_stopbys: bool) -> List[int]:
    """Which sorted-waypoint POSITIONS act as leg boundaries.

    With merge_stopbys on, a stop-by strictly between two boundaries merges into the leg
    spanning them instead of starting its own; the trip's first/last waypoint is always a
    boundary. A waypoint skipped in video export is never one either: the walker passes it
    (a pip card, see pedestrian.py's pip_only path)."""
    last = len(waypoints) - 1

    def _is_boundary(i: int, wp: Dict) -> bool:
        if i == 0 or i == last:
            return True
        if wp.get("skipAssetGeneration"):
            return False
        return not (merge_stopbys and wp.get("isStopBy", False))

    return [i for i, wp in enumerate(waypoints) if _is_boundary(i, wp)]


def _unwrap_popup_image(wp: Dict) -> Optional[str]:
    """job_config stores popup_image as a LIST (the UI's multi-image field); the image loader
    downstream only matches a plain path string."""
    pi = wp.get("popup_image")
    if isinstance(pi, list) and pi:
        return str(pi[-1])
    return str(pi) if pi else None


def _capped_freeze(value) -> Optional[float]:
    if value is None:
        return None
    return min(float(value), tuning.POPUP_FREEZE_SECONDS_MAX)


def _stopby_marker(wp: Dict, row_idx: int) -> Dict:
    """A stop-by merged into a leg as a mid-leg marker (see waypoints.py's mid_marker_pins)."""
    return {
        "row_idx": row_idx,
        "label": wp.get("label"),
        # [NOTE] [Map] The waypoint's own coordinate, so a stop-by only observed from the trail
        # (island, viewpoint across water) is drawn where it is, not at the nearest track row.
        "lat": wp.get("lat"),
        "lng": wp.get("lng", wp.get("lon")),
        # The walk pauses here (stopby_visits: connected, or any stop-by with a photo in the
        # "course" overview type). A Closed place is never walked to, but the leg stops on its
        # fullscreen photo too.
        "connect_to_route": visits_stopby(wp) or bool(wp.get("inaccessible")),
        "inaccessible": bool(wp.get("inaccessible")),  # a closed place: a red × dot
        # The waypoint's stable job_config id: route2vdo resolves its RAW position in
        # job_config's "waypoints" (not a position in this padded copy).
        "waypoint_id": wp.get("id"),
        "popup_image": _unwrap_popup_image(wp),
        "freeze_seconds": _capped_freeze(wp.get("freeze_seconds")),
        # "cover" (full-bleed photo) is the default; "pip" only when a waypoint asks for it.
        "image_display": wp.get("image_display", "cover"),
        # Its own narration TTS length, so a connected stop-by's pause outlasts its narration.
        "narration_audio_seconds": wp.get("_narration_audio_seconds"),
    }


def _build_segments(waypoints: List[Dict], wp_indices: List[int], merge_stopbys: bool) -> List[Tuple]:
    """(start_row, end_row, arrival_wp, departure_wp, merged stop-by markers) per leg.

    Each segment carries its own waypoint dicts, since merging boundaries breaks positional
    indexing into `waypoints`."""
    boundary_positions = _boundary_positions(waypoints, merge_stopbys)
    segments = []
    for bi in range(len(boundary_positions) - 1):
        start_pos, end_pos = boundary_positions[bi], boundary_positions[bi + 1]
        stopby_markers = [
            _stopby_marker(waypoints[p], wp_indices[p]) for p in range(start_pos + 1, end_pos)
        ]
        segments.append(
            (
                wp_indices[start_pos],
                wp_indices[end_pos],
                waypoints[end_pos],
                waypoints[start_pos],
                stopby_markers,
            )
        )
    return segments


def _chunk_starts(route_df: pd.DataFrame, seg_start: int, seg_end: int, max_chunk_m: float) -> List[int]:
    chunk_starts = [seg_start]
    accumulated_distance = 0.0
    for i in range(seg_start, seg_end):
        lat1, lon1 = route_df.iloc[i][["latitude", "longitude"]]
        lat2, lon2 = route_df.iloc[i + 1][["latitude", "longitude"]]
        accumulated_distance += _haversine_m(lat1, lon1, lat2, lon2)
        if accumulated_distance >= max_chunk_m:
            chunk_starts.append(i + 1)
            accumulated_distance = 0.0
    if chunk_starts[-1] != seg_end:
        chunk_starts.append(seg_end)
    return chunk_starts


def _plan_leg_jobs(
    route_df: pd.DataFrame,
    leg_idx: int,
    segment: Tuple,
    total_legs: int,
    max_chunk_distance_meters: float,
    png_dir: Path,
) -> List[Dict]:
    """Plan every map-tile chunk of one leg (cheap, CPU-only, no network I/O)."""
    seg_start, seg_end, wp, start_wp, stopby_markers = segment
    place_label = wp.get("label") or f"leg_{leg_idx + 1}"
    logger.info(
        "[%d/%d] Planning residential leg -> arriving at: '%s'",
        leg_idx + 1,
        total_legs,
        place_label,
    )

    # [NOTE] [Map] Straight-line distance between the leg's own pins gates the wide establishing
    # shot (tuning.RESIDENTIAL_WIDE_MIN_DISTANCE_M). Deliberately NOT the path distance: a short
    # leg can wind a long way, but with close pins the wide and tight tiles land at nearly the
    # same zoom anyway.
    leg_lat1, leg_lon1 = route_df.iloc[seg_start][["latitude", "longitude"]]
    leg_lat2, leg_lon2 = route_df.iloc[seg_end][["latitude", "longitude"]]
    leg_pin_distance_m = _haversine_m(leg_lat1, leg_lon1, leg_lat2, leg_lon2)
    leg_wants_wide_shot = leg_pin_distance_m >= tuning.RESIDENTIAL_WIDE_MIN_DISTANCE_M

    chunk_starts = _chunk_starts(route_df, seg_start, seg_end, max_chunk_distance_meters)
    num_chunks_this_leg = len(chunk_starts) - 1
    if num_chunks_this_leg > 1:
        logger.info(
            "  -> '%s' split into %d sub-chunk(s) (long leg).",
            place_label,
            num_chunks_this_leg,
        )

    jobs: List[Dict] = []
    for chunk_idx in range(num_chunks_this_leg):
        chunk_start, chunk_end = chunk_starts[chunk_idx], chunk_starts[chunk_idx + 1]
        if chunk_start >= chunk_end:
            continue

        lbl_base = "".join(
            c for c in str(wp.get("label", "Segment")) if c.isalnum() or c in (" ", "_")
        ).rstrip()
        lbl = f"{lbl_base}_part{chunk_idx + 1}" if len(chunk_starts) > 2 else lbl_base

        # The wide establishing shot plays once per LEG (before its first chunk), not per chunk.
        is_first_chunk_of_leg = chunk_idx == 0 and leg_wants_wide_shot
        # Merged-in stop-bys whose route-row falls in THIS chunk: a pass-through pin (waypoints.py).
        chunk_markers = [m for m in stopby_markers if chunk_start <= m["row_idx"] <= chunk_end]

        jobs.append(
            {
                "leg_idx": leg_idx,
                "chunk_start": chunk_start,
                "chunk_end": chunk_end,
                "chunk": route_df.iloc[chunk_start : chunk_end + 1],
                "lbl": lbl,
                "res_map_path": str(png_dir / f"res_map_{lbl}.png"),
                "res_map_path_wide": (
                    str(png_dir / f"res_map_{lbl}_wide.png") if is_first_chunk_of_leg else None
                ),
                "wp": wp,
                "start_wp": start_wp,
                "seg_end": seg_end,
                "chunk_markers": chunk_markers,
            }
        )
    return jobs


def _fetch_job(downloader: TileDownloader, job: Dict, output_size: Tuple[int, int]):
    tight_extent = downloader.fetch_residential_chunk(job["chunk"], job["res_map_path"], output_size)
    wide_extent = None
    # Same pooled task as its tight tile: one extra sequential call per leg's FIRST chunk only.
    if job["res_map_path_wide"]:
        wide_extent = downloader.fetch_residential_wide(job["chunk"], job["res_map_path_wide"], output_size)
    return tight_extent, wide_extent


def _fetch_all_tiles(downloader: TileDownloader, jobs: List[Dict], output_size: Tuple[int, int]):
    """Fetch every chunk's map tile through a small thread pool.

    [NOTE] [Map] Pure network wait (the GIL is released), so fetches overlap; TileDownloader keeps
    no per-call mutable state, so sharing it is safe. The worker count (tuning.py) stays modest to
    clear the provider's rate limiting; its wait/retry backoff still applies per call."""
    total_jobs = len(jobs)
    tracker.begin_substeps(total_jobs)
    extents: List[Optional[Tuple[float, float, float, float]]] = [None] * total_jobs
    wide_extents: List[Optional[Tuple[float, float, float, float]]] = [None] * total_jobs
    max_workers = max(1, min(tuning.RESIDENTIAL_TILE_FETCH_WORKERS, total_jobs))

    def _task(job_index: int):
        return (job_index, *_fetch_job(downloader, jobs[job_index], output_size))

    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_task, i) for i in range(total_jobs)]
        for future in concurrent.futures.as_completed(futures):
            job_index, res_extent, wide_extent = future.result()
            extents[job_index] = res_extent
            wide_extents[job_index] = wide_extent
            completed += 1
            job = jobs[job_index]
            logger.info(
                "  -> [%d/%d] '%s' tile ready -> %s",
                completed, total_jobs, job["lbl"], job["res_map_path"],
            )
            tracker.show_item(
                completed,
                f"Fetching map tiles {completed}/{total_jobs}: '{job['lbl']}'",
            )
    return extents, wide_extents


def _chunk_points_labels_popups(job: Dict, res_extent, output_size: Tuple[int, int]):
    """Pixel points per route row, plus the leg-arrival label/popup on the arrival row."""
    wp, seg_end = job["wp"], job["seg_end"]
    chunk_points, chunk_labels, chunk_popups = [], [], []
    for row_idx, row in job["chunk"].iterrows():
        px, py = RouteGeometry.project_latlon_to_pixel(
            row["latitude"],
            row["longitude"],
            res_extent,
            output_size[0],
            output_size[1],
        )
        chunk_points.append([px, py])

        if row_idx == seg_end:
            chunk_labels.append(wp.get("label"))
            chunk_popups.append(
                {
                    "freeze_seconds": min(
                        float(wp.get("freeze_seconds", 3.0)),
                        tuning.POPUP_FREEZE_SECONDS_MAX,
                    ),
                    "popup_image": wp.get("popup_image"),
                    "triggered": False,
                }
            )
        else:
            chunk_labels.append(None)
            chunk_popups.append(None)
    return chunk_points, chunk_labels, chunk_popups


def _mid_markers(job: Dict, chunk_points: List) -> List[Dict]:
    """Merged-in stop-bys in this chunk, drawn as a pin as the traveler passes (waypoints.py's
    mid_marker_pins), separate from the leg-arrival popup. connect_to_route and popup_image must
    both be carried through, or a connected stop-by's fullscreen photo pause never triggers."""
    return [
        {
            "row_idx": m["row_idx"],
            "label": m["label"],
            "px": chunk_points[m["row_idx"] - job["chunk_start"]],
            # waypoints.py reprojects the marker onto its true position via the chunk's extent.
            "lat": m.get("lat"),
            "lng": m.get("lng"),
            "connect_to_route": bool(m.get("connect_to_route", False)),
            "inaccessible": bool(m.get("inaccessible")),
            "waypoint_id": m.get("waypoint_id"),
            "popup_image": m.get("popup_image"),
            "freeze_seconds": _capped_freeze(m.get("freeze_seconds")),
            "image_display": m.get("image_display", "cover"),
        }
        for m in job["chunk_markers"]
    ]


def _assemble_chunk(job: Dict, res_extent, wide_extent, output_size: Tuple[int, int]) -> Dict:
    chunk = job["chunk"]
    chunk_points, chunk_labels, chunk_popups = _chunk_points_labels_popups(job, res_extent, output_size)
    return {
        "start_idx": job["chunk_start"],
        "end_idx": job["chunk_end"],
        "img_path": job["res_map_path"],
        "extent": res_extent,
        # Wide establishing-shot tile + extent: only a leg's FIRST chunk, None elsewhere.
        "wide_img_path": job["res_map_path_wide"],
        "wide_extent": wide_extent,
        "mid_markers": _mid_markers(job, chunk_points),
        "lats": chunk["latitude"].to_numpy(),
        "lons": chunk["longitude"].to_numpy(),
        "points": chunk_points,
        "labels": chunk_labels,
        "popups": chunk_popups,
        # [NOTE] [Map] Endpoint ids from the leg's own waypoint dicts: labels can repeat in one
        # project (a route through the same city twice), ids are unambiguous.
        "start_waypoint_id": job["start_wp"].get("id"),
        "end_waypoint_id": job["wp"].get("id"),
        "leg_idx": job["leg_idx"],
    }


# [Core] MapFetcher Class
class MapFetcher:
    """Orchestrates geographic data parsing and image downloading."""

    # [Config] Initialize with optional provider and JobConfigManager
    def __init__(self, provider=None, job_config=None):
        # Bring in JobConfigManager just like the other modules
        self.config = job_config or JobConfigManager()
        self.downloader = TileDownloader(job_config=self.config, provider=provider)

    # [Map] Fetch  image based on a bounding box and save it to a specified filename
    def fetch_image(
        self,
        bounding_box: Dict[str, float],
        output_filename: str,
        output_size: Tuple[int, int] = (1920, 1080),
        max_zoom: int = 20,
    ):
        """Instance method mapping for overview maps."""
        # ---------------------------------------------------------------------
        # DYNAMIC PATH FIX: Route the overview map to the central map-image directory
        # ---------------------------------------------------------------------
        base_path = Path(self.config.get("directory_path", "assets"))
        png_dir = (base_path / "assets" / "image" / "map").resolve()
        png_dir.mkdir(parents=True, exist_ok=True)

        # Override the filename path to sit correctly in the map-image folder
        final_filename = str(png_dir / Path(output_filename).name)

        settings = (self.config.get("settings", {}) if self.config else {}) or {}
        # Opt-in per project (settings.overview_background: "pydeck" in
        # job_config.json) — the default stays the existing contextily/Esri
        # tile stitch, which needs no Mapbox token/headless-browser
        # dependency. See pydeck_overview.py's own module docstring for why
        # this is a separate top-down-only capture rather than reusing the
        # residential mode's tilted pydeck camera.
        background = str(settings.get("overview_background", "")).lower()
        # Static raster tiles can't be relabeled, so a map in another language than the style's own
        # (English) is drawn through the GL page, which rewrites its labels (maplanguage's localizer),
        # unless the project gave a Studio style for that language or chose the background itself.
        lang = streets_lang(self.config.get("map_language")) if self.config else None
        if needs_gl_labels(settings, lang, bool(resolve_mapbox_token(settings))):
            background = "pydeck"
            logger.info("Map language %s: drawing the overview map through the GL page so its labels follow it.", lang)
        # The course overview zooms in on the GL map (course._course_gl_frames): its whole-map frame must be that
        # same map, or each zoom would switch map style.
        if settings.get("overview_style") == "course" and resolve_mapbox_token(settings):
            background = "pydeck"
        if background == "pydeck":
            from services.mapfetcher.pydeck_overview import fetch_overview_image_pydeck

            logger.info("Fetching overview map background via pydeck...")
            map_style = resolve_map_style(settings, "mapbox/streets-v12")
            try:
                result = fetch_overview_image_pydeck(
                    bounding_box, final_filename, output_size,
                    mapbox_key=resolve_mapbox_token(settings),
                    map_style=map_style,
                )
                logger.info("Overview map background saved -> %s", result[0])
                return result
            except Exception as exc:
                if str(settings.get("overview_background", "")).lower() == "pydeck":
                    raise
                logger.warning("GL overview map failed (%s); using the raster map (its labels stay in the style's language).", exc)

        logger.info("Fetching overview map tile (zoom<=%d)...", max_zoom)
        result = self.downloader.fetch_overview_image(
            bounding_box, final_filename, output_size, max_zoom
        )
        logger.info("Overview map tile saved -> %s", result[0])
        return result

    # [Map] Process a residential sequence based on route DataFrame and waypoints
    def process_residential_sequence(
        self,
        route_df: pd.DataFrame,
        waypoints: List[Dict],
        output_size: Tuple[int, int] = (1920, 1080),
        max_chunk_distance_meters: float = tuning.RESIDENTIAL_DEFAULT_MAX_CHUNK_DISTANCE_M,
        precomputed_indices: Optional[List[int]] = None,
        merge_stopbys: bool = tuning.DEFAULT_MERGE_STOPBY_WAYPOINTS,
        leg_index: Optional[int] = None,
    ) -> List[Dict]:
        """Core orchestrator logic utilizing the dedicated Downloader and Geometry classes.

        `leg_index`: when given, only that ONE leg (0-indexed, in travel
        order, AFTER stop-by merging is applied) is planned/fetched at all
        -- every other leg's map tile fetch is skipped entirely, not just
        excluded from the returned sequence. Applied right after `segments`
        is built below (the point stop-by merging has already resolved),
        so the leg numbering here always matches the final, merged leg
        count a caller would see in the full (unfiltered) result.

        `merge_stopbys` (default from tuning.DEFAULT_MERGE_STOPBY_WAYPOINTS):
        when True, a stop-by waypoint ("isStopBy": true) does NOT get its own
        leg/tile boundary — it merges into whichever real-to-real leg it
        falls inside, surfacing only as a "mid_markers" entry on that leg's
        first chunk's sequence_data (a pin drawn as the traveler passes, no
        popup/summary-card). When False, every stop-by is a full leg
        boundary exactly like a real waypoint (the old behavior)."""
        sequence_data = []

        # DYNAMIC PATH FIX: Route all residential chunks to the central map-image directory
        base_path = Path(self.config.get("directory_path", "assets"))
        png_dir = (base_path / "assets" / "image" / "map").resolve()
        png_dir.mkdir(parents=True, exist_ok=True)

        if route_df.empty or not waypoints:
            return sequence_data

        wp_indices = (
            precomputed_indices
            if precomputed_indices is not None
            else RouteGeometry.build_waypoint_index(route_df, waypoints)
        )
        sorted_wps = sorted(zip(wp_indices, waypoints), key=lambda x: x[0])
        wp_indices = [x[0] for x in sorted_wps]
        waypoints = [x[1] for x in sorted_wps]

        segments = _build_segments(waypoints, wp_indices, merge_stopbys)
        if leg_index is not None:
            if not (0 <= leg_index < len(segments)):
                raise ValueError(
                    f"leg_index {leg_index} out of range — this route has {len(segments)} leg(s) (0-{len(segments) - 1})."
                )
            segments = [segments[leg_index]]

        # Total leg count known up front, so every per-leg log line shows "[i/total]".
        total_legs = len(segments)
        logger.info(
            "process_residential_sequence: %d leg(s) to process (max_chunk=%s m).",
            total_legs,
            (
                "inf"
                if math.isinf(max_chunk_distance_meters)
                else f"{max_chunk_distance_meters:.0f}"
            ),
        )

        # Pass 1: plan every chunk across every leg (CPU-only) so pass 2 can fetch them all
        # through a thread pool instead of one leg at a time.
        jobs: List[Dict] = []
        for leg_idx, segment in enumerate(segments):
            jobs.extend(
                _plan_leg_jobs(route_df, leg_idx, segment, total_legs, max_chunk_distance_meters, png_dir)
            )

        # Pass 2: the slow, network-bound tile fetches.
        extents, wide_extents = _fetch_all_tiles(self.downloader, jobs, output_size)

        # Pass 3: assemble in the ORIGINAL leg/chunk order (the pool finishes in any order, but
        # video assembly needs route order).
        for job_index, job in enumerate(jobs):
            sequence_data.append(
                _assemble_chunk(job, extents[job_index], wide_extents[job_index], output_size)
            )

        logger.info(
            "process_residential_sequence complete: %d chunk(s) generated across %d leg(s).",
            len(sequence_data),
            total_legs,
        )
        return sequence_data

    # [Util/Map] Static method wrappers for RouteGeometry and RoutePacing functionalities
    @staticmethod
    def get_bounding_box(*args, **kwargs):
        return RouteGeometry.get_bounding_box(*args, **kwargs)

    @staticmethod
    def build_waypoint_index(*args, **kwargs):
        return RouteGeometry.build_waypoint_index(*args, **kwargs)

    @staticmethod
    def get_smooth_path(*args, **kwargs):
        return RouteGeometry.get_smooth_path(*args, **kwargs)

    @staticmethod
    def compute_segment_durations(*args, **kwargs):
        return RoutePacing.compute_segment_durations(*args, **kwargs)
