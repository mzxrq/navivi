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

# Logging configuration
logger = setup_logger("MapFetcher")


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
        # DYNAMIC PATH FIX: Route the overview map to the central png directory
        # ---------------------------------------------------------------------
        base_path = Path(self.config.get("directory_path", "assets"))
        png_dir = (base_path / "png").resolve()
        png_dir.mkdir(parents=True, exist_ok=True)

        # Override the filename path to sit correctly in the png folder
        final_filename = str(png_dir / Path(output_filename).name)

        settings = (self.config.get("settings", {}) if self.config else {}) or {}
        # Opt-in per project (settings.overview_background: "pydeck" in
        # job_config.json) — the default stays the existing contextily/Esri
        # tile stitch, which needs no Mapbox token/headless-browser
        # dependency. See pydeck_overview.py's own module docstring for why
        # this is a separate top-down-only capture rather than reusing the
        # residential mode's tilted pydeck camera.
        if str(settings.get("overview_background", "")).lower() == "pydeck":
            from services.mapfetcher.pydeck_overview import fetch_overview_image_pydeck

            logger.info("Fetching overview map background via pydeck...")
            result = fetch_overview_image_pydeck(
                bounding_box, final_filename, output_size,
                mapbox_key=settings.get("mapbox_token"),
            )
            logger.info("Overview map background saved -> %s", result[0])
            return result

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
    ) -> List[Dict]:
        """Core orchestrator logic utilizing the dedicated Downloader and Geometry classes.

        `merge_stopbys` (default from tuning.DEFAULT_MERGE_STOPBY_WAYPOINTS):
        when True, a stop-by waypoint ("isStopBy": true) does NOT get its own
        leg/tile boundary — it merges into whichever real-to-real leg it
        falls inside, surfacing only as a "mid_markers" entry on that leg's
        first chunk's sequence_data (a pin drawn as the traveler passes, no
        popup/summary-card). When False, every stop-by is a full leg
        boundary exactly like a real waypoint (the old behavior)."""
        sequence_data = []

        # ---------------------------------------------------------------------
        # DYNAMIC PATH FIX: Route all residential chunks to the central png directory
        # ---------------------------------------------------------------------
        base_path = Path(self.config.get("directory_path", "assets"))
        png_dir = (base_path / "png").resolve()
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

        # Which sorted-waypoint POSITIONS act as leg boundaries. With
        # merge_stopbys on, a stop-by strictly between two boundaries is
        # skipped here — it merges into the leg spanning those two
        # boundaries instead of starting its own — but the trip's true
        # first/last waypoint is always kept as a boundary even if
        # (unusually) flagged stop-by, since "pass through" isn't a
        # meaningful concept for the trip's own endpoints.
        if merge_stopbys:
            boundary_positions = [
                i
                for i, wp in enumerate(waypoints)
                if i == 0 or i == len(waypoints) - 1 or not wp.get("isStopBy", False)
            ]
        else:
            boundary_positions = list(range(len(waypoints)))

        # Each segment carries its own departure/arrival waypoint dicts
        # directly (rather than relying on positional indexing into the
        # full `waypoints` list, which merging boundaries would otherwise
        # break), plus any stop-bys that merged into it as mid-leg markers.
        segments = []
        for bi in range(len(boundary_positions) - 1):
            start_pos, end_pos = boundary_positions[bi], boundary_positions[bi + 1]
            stopby_markers = [
                {
                    "row_idx": wp_indices[p],
                    "label": waypoints[p].get("label"),
                    # Carried through so a merged-in stop-by (drawn as a
                    # plain pass-through pin — see waypoints.py's
                    # mid_marker_pins) can still show its own popup photo
                    # briefly when the traveler passes it, instead of
                    # being purely a silent marker. job_config stores this
                    # as a LIST (the UI's own multi-image field) — unwrapped
                    # to a plain path string here, same convention
                    # render_step.py's own popup_image handling uses;
                    # left as a list, the image loader downstream never
                    # matched it as a valid path and the card silently
                    # never rendered.
                    "popup_image": (
                        str(_pi[0])
                        if isinstance(_pi := waypoints[p].get("popup_image"), list) and _pi
                        else (str(_pi) if _pi else None)
                    ),
                    "freeze_seconds": waypoints[p].get("freeze_seconds"),
                    # "cover" (full-bleed photo, label overlaid) is now
                    # the default look — "pip" (photo + caption strip
                    # below) only applies when a waypoint explicitly asks
                    # for it.
                    "image_display": waypoints[p].get("image_display", "cover"),
                }
                for p in range(start_pos + 1, end_pos)
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

        # [NEW] Total leg count known up front — lets every per-leg log line
        # show "[i/total]" progress instead of an unbounded counter.
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

        # Pass 1: plan every chunk across every leg first (cheap, CPU-only —
        # no network I/O), so pass 2 below can fetch them all through a
        # thread pool instead of one leg at a time. Kept as a separate pass
        # (rather than fetching inline per-leg as this used to) specifically
        # so tile downloads — the actual slow, network-bound step — can run
        # several at once; nothing about the planning logic itself changed.
        jobs: List[Dict] = []
        for leg_idx, (seg_start, seg_end, wp, start_wp, stopby_markers) in enumerate(segments):
            place_label = wp.get("label") or f"leg_{leg_idx + 1}"
            logger.info(
                "[%d/%d] Planning residential leg -> arriving at: '%s'",
                leg_idx + 1,
                total_legs,
                place_label,
            )

            # Straight-line distance between the leg's own start/end pins —
            # gates whether the wide establishing shot is worth showing at
            # all (see tuning.RESIDENTIAL_WIDE_MIN_DISTANCE_M). Deliberately
            # NOT the accumulated path distance below: a short/local leg can
            # still have a long, winding path, but if its two pins are close
            # together the wide and tight tiles land at nearly the same zoom
            # anyway, so the "establishing shot" would add nothing.
            leg_lat1, leg_lon1 = route_df.iloc[seg_start][["latitude", "longitude"]]
            leg_lat2, leg_lon2 = route_df.iloc[seg_end][["latitude", "longitude"]]
            leg_dlat, leg_dlon = math.radians(leg_lat2 - leg_lat1), math.radians(leg_lon2 - leg_lon1)
            leg_a = (
                math.sin(leg_dlat / 2.0) ** 2
                + math.cos(math.radians(leg_lat1))
                * math.cos(math.radians(leg_lat2))
                * math.sin(leg_dlon / 2.0) ** 2
            )
            leg_pin_distance_m = 6371000.0 * (2.0 * math.asin(math.sqrt(leg_a)))
            leg_wants_wide_shot = leg_pin_distance_m >= tuning.RESIDENTIAL_WIDE_MIN_DISTANCE_M

            chunk_starts = [seg_start]
            accumulated_distance = 0.0

            for i in range(seg_start, seg_end):
                lat1, lon1 = route_df.iloc[i][["latitude", "longitude"]]
                lat2, lon2 = route_df.iloc[i + 1][["latitude", "longitude"]]
                dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
                a = (
                    math.sin(dlat / 2.0) ** 2
                    + math.cos(math.radians(lat1))
                    * math.cos(math.radians(lat2))
                    * math.sin(dlon / 2.0) ** 2
                )
                accumulated_distance += 6371000.0 * (2.0 * math.asin(math.sqrt(a)))

                if accumulated_distance >= max_chunk_distance_meters:
                    chunk_starts.append(i + 1)
                    accumulated_distance = 0.0

            if chunk_starts[-1] != seg_end:
                chunk_starts.append(seg_end)

            num_chunks_this_leg = len(chunk_starts) - 1
            if num_chunks_this_leg > 1:
                # Only worth logging when a leg actually gets split into
                # multiple map tiles — the common case (max_chunk=inf) has
                # exactly 1 chunk per leg and this would just be noise.
                logger.info(
                    "  -> '%s' split into %d sub-chunk(s) (long leg).",
                    place_label,
                    num_chunks_this_leg,
                )

            for chunk_idx in range(num_chunks_this_leg):
                chunk_start, chunk_end = (
                    chunk_starts[chunk_idx],
                    chunk_starts[chunk_idx + 1],
                )
                if chunk_start >= chunk_end:
                    continue

                chunk = route_df.iloc[chunk_start : chunk_end + 1]
                lbl_base = "".join(
                    c
                    for c in str(wp.get("label", "Segment"))
                    if c.isalnum() or c in (" ", "_")
                ).rstrip()
                lbl = (
                    f"{lbl_base}_part{chunk_idx + 1}"
                    if len(chunk_starts) > 2
                    else lbl_base
                )

                # The wide establishing shot only plays once per LEG (before
                # its first chunk), not once per chunk — a leg split into
                # several tiles should still open with one wide shot, then
                # hard-cut chunk to chunk as today.
                is_first_chunk_of_leg = chunk_idx == 0 and leg_wants_wide_shot
                # Any merged-in stop-by whose own route-row falls inside
                # THIS chunk's span — drawn as a pass-through pin on this
                # chunk's clip (see waypoints.py), never its own tile/leg.
                chunk_markers = [
                    m for m in stopby_markers
                    if chunk_start <= m["row_idx"] <= chunk_end
                ]

                jobs.append(
                    {
                        "leg_idx": leg_idx,
                        "chunk_start": chunk_start,
                        "chunk_end": chunk_end,
                        "chunk": chunk,
                        "lbl": lbl,
                        # Update file path to use the absolute, centralized png directory
                        "res_map_path": str(png_dir / f"res_map_{lbl}.png"),
                        "res_map_path_wide": (
                            str(png_dir / f"res_map_{lbl}_wide.png")
                            if is_first_chunk_of_leg
                            else None
                        ),
                        "wp": wp,
                        "start_wp": start_wp,
                        "seg_end": seg_end,
                        "chunk_markers": chunk_markers,
                    }
                )

        # Pass 2: fetch every chunk's map tile — the actual slow step, a
        # live network call to the tile provider via contextily — through a
        # small thread pool rather than one at a time. This is pure I/O
        # wait (contextily/requests release the GIL while blocking on the
        # network), so concurrent fetches genuinely overlap instead of
        # competing for CPU; TileDownloader itself does no per-call mutable
        # state (provider/cache_dir/zoom cap are all set once at __init__
        # and only read from here), so it's safe to share across threads.
        # Kept modest (see tuning.py) to stay well clear of the tile
        # provider's own rate limiting — TileDownloader's existing
        # wait/retry backoff (_bounds2img_safe) still applies per-call on
        # top of this.
        total_jobs = len(jobs)
        tracker.begin_substeps(total_jobs)
        extents: List[Optional[Tuple[float, float, float, float]]] = [None] * total_jobs
        wide_extents: List[Optional[Tuple[float, float, float, float]]] = [None] * total_jobs
        max_workers = max(1, min(tuning.RESIDENTIAL_TILE_FETCH_WORKERS, total_jobs))

        def _fetch(job_index: int):
            job = jobs[job_index]
            tight_extent = self.downloader.fetch_residential_chunk(
                job["chunk"], job["res_map_path"], output_size
            )
            wide_extent = None
            # Fetched in the same pooled task (same thread) as its tight
            # tile — one extra sequential network call per leg's FIRST
            # chunk only, still overlapping with every other leg's fetches
            # via the surrounding thread pool.
            if job["res_map_path_wide"]:
                wide_extent = self.downloader.fetch_residential_wide(
                    job["chunk"], job["res_map_path_wide"], output_size
                )
            return job_index, tight_extent, wide_extent

        completed = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_fetch, i) for i in range(total_jobs)]
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

        # Pass 3: assemble sequence_data in the ORIGINAL leg/chunk order —
        # fetches above complete in whatever order the pool finishes them
        # in, but downstream (video assembly) needs legs in route order,
        # same as before this was parallelized.
        for job_index, job in enumerate(jobs):
            res_extent = extents[job_index]
            chunk, wp, seg_end = job["chunk"], job["wp"], job["seg_end"]
            leg_idx, chunk_start, chunk_end = (
                job["leg_idx"], job["chunk_start"], job["chunk_end"],
            )

            chunk_points, chunk_labels, chunk_popups = [], [], []
            for row_idx, row in chunk.iterrows():
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
                            "freeze_seconds": float(wp.get("freeze_seconds", 3.0)),
                            "popup_image": wp.get("popup_image"),
                            "triggered": False,
                        }
                    )
                else:
                    chunk_labels.append(None)
                    chunk_popups.append(None)

            # Merged-in stop-bys whose route-row falls in THIS chunk — a
            # pin drawn as the traveler passes it (see waypoints.py's
            # mid_marker_pins), separate from the real leg-arrival popup
            # mechanism that chunk_labels/chunk_popups above feeds. Still
            # carries its own popup_image/freeze_seconds/image_display
            # (added upstream in _pos+1's stopby_markers) through to that
            # pin, though — dropped here before, which silently kept a
            # passed stop-by's own photo from ever showing.
            mid_markers = [
                {
                    "row_idx": m["row_idx"],
                    "label": m["label"],
                    "px": chunk_points[m["row_idx"] - chunk_start],
                    "popup_image": m.get("popup_image"),
                    "freeze_seconds": m.get("freeze_seconds"),
                    "image_display": m.get("image_display", "cover"),
                }
                for m in job["chunk_markers"]
            ]

            sequence_data.append(
                {
                    "start_idx": chunk_start,
                    "end_idx": chunk_end,
                    "img_path": job["res_map_path"],
                    "extent": res_extent,
                    # Wide establishing-shot tile + its own geo extent —
                    # only set on a leg's FIRST chunk (see is_first_chunk_of_leg
                    # in Pass 1); None on every other chunk.
                    "wide_img_path": job["res_map_path_wide"],
                    "wide_extent": wide_extents[job_index],
                    "mid_markers": mid_markers,
                    "lats": chunk["latitude"].to_numpy(),
                    "lons": chunk["longitude"].to_numpy(),
                    "points": chunk_points,
                    "labels": chunk_labels,
                    "popups": chunk_popups,
                    # This leg's real departure/arrival waypoint ids
                    # (job_config's own "id" field) — several
                    # waypoints in the same project can share a label
                    # (e.g. a route that passes through "大阪市"
                    # multiple times), so matching a leg's endpoint
                    # back to its true position in the whole route
                    # by id is unambiguous where label text alone
                    # isn't. Read directly off this job's own departure/
                    # arrival waypoint dicts (not positional indexing into
                    # `waypoints`, which merged-away stop-bys would throw
                    # off) — see `start_wp`/`wp` set in Pass 1.
                    "start_waypoint_id": job["start_wp"].get("id"),
                    "end_waypoint_id": wp.get("id"),
                    "leg_idx": leg_idx,
                }
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
    def douglas_peucker(*args, **kwargs):
        return RouteGeometry.douglas_peucker(*args, **kwargs)

    @staticmethod
    def get_smooth_path(*args, **kwargs):
        return RouteGeometry.get_smooth_path(*args, **kwargs)

    @staticmethod
    def compute_segment_durations(*args, **kwargs):
        return RoutePacing.compute_segment_durations(*args, **kwargs)

    @staticmethod
    def compute_chunk_durations(*args, **kwargs):
        return RoutePacing.compute_chunk_durations(*args, **kwargs)

    @staticmethod
    def generate_residential_sequence(*args, **kwargs):
        return MapFetcher().process_residential_sequence(*args, **kwargs)