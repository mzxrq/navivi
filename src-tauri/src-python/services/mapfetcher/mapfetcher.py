"""
MapFetcher Service (mapfetcher.py)
---------------------------------------------------------------------------
Orchestrates geographic data parsing and image downloading.
Imports core geometry and tile downloading from map_engine.py.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import pandas as pd

from services.mapfetcher.mapengine import RouteGeometry, RoutePacing, TileDownloader
from services.config.job_config import JobConfigManager
from services.logger.logger import setup_logger

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
        max_chunk_distance_meters: float = 1000.0,
        precomputed_indices: Optional[List[int]] = None,
    ) -> List[Dict]:
        """Core orchestrator logic utilizing the dedicated Downloader and Geometry classes."""
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

        for leg_idx, (seg_start, seg_end, wp) in enumerate(segments):
            place_label = wp.get("label") or f"leg_{leg_idx + 1}"

            # [NEW] Tracking log — names the exact place this leg's
            # residential map/video segment is being generated FOR, before
            # any (potentially slow) tile-download or chunking work starts.
            logger.info(
                "[%d/%d] Building residential leg -> arriving at: '%s'",
                leg_idx + 1,
                total_legs,
                place_label,
            )

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

                # Update file path to use the absolute, centralized png directory
                res_map_path = str(png_dir / f"res_map_{lbl}.png")

                # [NEW] This is the actual slow step — a live network call
                # to the map tile provider via contextily. Logging
                # immediately before it fires means a stall here is
                # visibly attributable to "waiting on map tiles for X",
                # not a silent hang somewhere unidentifiable.
                logger.info(
                    "  -> [%d/%d] Downloading map tile for '%s' -> %s",
                    leg_idx + 1,
                    total_legs,
                    lbl,
                    res_map_path,
                )
                res_extent = self.downloader.fetch_residential_chunk(
                    chunk, res_map_path, output_size
                )
                logger.info(
                    "  -> [%d/%d] '%s' tile ready.", leg_idx + 1, total_legs, lbl
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