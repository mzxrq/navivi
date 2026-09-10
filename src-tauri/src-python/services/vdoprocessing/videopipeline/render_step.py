"""Step 4: Render the visual map animation, synced to audio timing."""

import json
import math
import os
import re
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from services.gpsparser.gpscalculator import GPSMath
from services.logger.progress import tracker
from services.mapfetcher.mapfetcher import MapFetcher
from services.vdoprocessing.route2vdo import RouteAnimator
from services.vdoprocessing.spatial_renderer import SpatialRenderer
from services.localization.localization import format_waypoint_label
from services.config.job_config import JobConfigManager
from services import tuning

from .helpers import (
    BASE_DIR,
    DEFAULT_FRONTEND_CONFIG,
    DEFAULT_MAP_BACKGROUND,
    PIPELINE_LABELS,
    _build_point_modes,
    _project_route_to_pixels,
    _resolve_leg_geometry_from_cache,
    logger,
)


# Residential-leg clip filename's embedded 1-based departure-waypoint
# position (see waypoints.py's chunk_filename: "02_waypoint_{N:02d}_...") —
# used below (and by timeline_step.py's own mirrored match) to look up that
# leg's narration by the waypoint's actual RAW position instead of a blind
# per-clip counter, which stop-by leg-merging can throw out of sync (a
# merged-away stop-by means consecutive leg clips no longer correspond to
# consecutive audio_paths entries).
RESIDENTIAL_LEG_RE = re.compile(r"02_waypoint_(\d+)_")


# Overview map padding, scaled to how physically big the route actually
# is (bounding-box diagonal, in km) — a flat percentage padding looks
# right at one scale and wrong at another: 10% margin around a route that
# spans 40km is a lot of genuinely useful breathing room, but the same
# 10% around a route that spans 800m is still a huge, mostly-empty gap
# with the pins clustered tiny in the middle. Smaller routes get a
# tighter (more zoomed-in) crop; bigger ones get a bit more room so nearby
# pins/labels don't crowd the frame edge.
_OVERVIEW_PADDING_BY_SPAN_KM = (
    (1.5, 0.06),
    (5.0, 0.08),
    (15.0, 0.10),
    (40.0, 0.13),
)
_OVERVIEW_PADDING_MAX_SPAN = 0.16


def _adaptive_overview_padding(route_df: pd.DataFrame) -> float:
    """Picks the overview map's padding_factor from the route's own
    bounding-box diagonal distance (km) — see _OVERVIEW_PADDING_BY_SPAN_KM
    above. Falls back to the old flat 10% if the span can't be computed
    (e.g. a single-point route)."""
    try:
        min_lat, max_lat = route_df["latitude"].min(), route_df["latitude"].max()
        min_lon, max_lon = route_df["longitude"].min(), route_df["longitude"].max()
        span_km = float(
            GPSMath.haversine_vectorized(
                np.array([min_lat]), np.array([min_lon]),
                np.array([max_lat]), np.array([max_lon]),
            )[0]
        )
    except (KeyError, ValueError, IndexError):
        return 0.10

    for max_span, padding in _OVERVIEW_PADDING_BY_SPAN_KM:
        if span_km <= max_span:
            return padding
    return _OVERVIEW_PADDING_MAX_SPAN


def render_route_video(
    cleaned_route: dict,
    project_config_path: str = str(DEFAULT_FRONTEND_CONFIG),
    output_video_dir: Optional[str] = None,
    map_output_path: str = str(DEFAULT_MAP_BACKGROUND),
    audio_paths: Optional[list[str]] = None,
    audio_durations: Optional[list[float]] = None,
    audio_pauses: Optional[list[Any]] = None,
    render_mode: str = "both",
) -> list[str]:
    """Generates the visual map animation using synced audio timing.

    render_mode gates which OUTPUT video(s) actually get produced/written:
    "overview" skips building the residential leg-by-leg sequence entirely
    (no per-leg residential map tile fetches, no residential clips
    rendered/returned); "residential" still fetches the overview background
    tile (needed for route_points/img_w/img_h, shared by both outputs) but
    skips rendering the overview animation itself; "both" (the default,
    used by run_full_pipeline) renders everything, unchanged from before.
    Lets services/cli/gps_commands.py's test_overview_video and
    test_residential_video each produce ONLY the video their name promises,
    instead of both always being bundled into one call regardless of which
    was asked for."""
    logger.info("Step 4: Rendering Video Engine — starting.")

    route_df = cleaned_route.get("route")
    if route_df is None or route_df.empty:
        raise ValueError("Cannot render a navigation video from an empty route.")

    # 1. Load Config & Settings Early
    project_config = {}
    config_path = Path(project_config_path)
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            project_config = json.load(f)

    project_name = project_config.get("project_name", "Navigation Project")

    # Defaults to the project's OWN folder (job_config.json's directory_path
    # — the same "video" subfolder every other stage already writes to:
    # audio_step.py, subtitle_step.py, intro_step.py/outro_step.py) rather
    # than a fixed install-relative path — a caller can still override this
    # explicitly (every real caller currently does).
    if output_video_dir is None:
        output_video_dir = str(
            Path(project_config.get("directory_path", BASE_DIR)) / "video"
        )

    tracker.show(f"Rendering overview & residential video: {project_name}")

    settings = project_config.get("settings", {})
    waypoints = project_config.get("waypoints", [])
    # 3D residential rendering is opt-in. The 2D spatial renderer is the
    # reliable fallback and remains the default for existing projects.
    use_3d_res = bool(settings.get("use_3d_res", False))
    subtitle_lang = settings.get("subtitle_language", "en")

    audio_durations = audio_durations or []
    audio_pauses = audio_pauses or []

    # 2. Fetch Base Map & Project Pixels
    logger.info("Step 4: Computing bounding box and fetching overview map tile...")
    tracker.show("Fetching overview map tile...")

    # Pass the job_config explicitly (rather than relying on whatever state
    # the JobConfigManager singleton happens to already be in) so the tile
    # cache always lands under THIS project's directory_path/cache, even
    # when render_route_video runs as its own process/command without
    # process_gps having initialized the singleton first.
    fetcher = MapFetcher(job_config=JobConfigManager(str(config_path)))

    bbox = fetcher.get_bounding_box(
        route_df, padding_factor=_adaptive_overview_padding(route_df)
    )

    map_output_path, extent, (img_w, img_h) = fetcher.fetch_image(
        bounding_box=bbox, output_filename=map_output_path
    )

    if not map_output_path:
        raise RuntimeError(
            "Map fetch failed - cannot render video without background map."
        )

    route_points = _project_route_to_pixels(
        route_df["latitude"].to_numpy(),
        route_df["longitude"].to_numpy(),
        extent,
        img_w,
        img_h,
    )

    route_labels = [
        row["store_name"] if row.get("is_landmarked") else None
        for _, row in route_df.iterrows()
    ]
    route_popups = [None] * len(route_points)
    wp_indices = MapFetcher.build_waypoint_index(route_df, waypoints)

    routing_cache = {}
    routecache_path = config_path.parent / ".routecache.json"
    if routecache_path.exists():
        try:
            with open(routecache_path, "r", encoding="utf-8") as f:
                routing_cache = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Step 4: Failed to read %s: %s", routecache_path, e)

    point_modes = _build_point_modes(len(route_points), wp_indices, waypoints, routing_cache)

    # Real-world REPORTED speed per travel mode — what the summary card's
    # per-mode duration breakdown is estimated from. Kept separate from
    # animation_speed_kmh below (used to weight on-screen time) — that one
    # is a single uniform pace for every mode instead (see SpatialRenderer's
    # _DEFAULT_ANIMATION_SPEED_KMH).
    mode_speed_kmh = {
        **SpatialRenderer._DEFAULT_MODE_SPEED_KMH,
        **{
            str(k).lower(): float(v)
            for k, v in (settings.get("mode_speeds_kmh") or {}).items()
        },
    }
    # Speed used only to weight each residential leg's ON-SCREEN duration
    # (see seg_durations further down) — not shown anywhere as a stat.
    # Every mode defaults to the SAME pace (SpatialRenderer's own uniform
    # _DEFAULT_ANIMATION_SPEED_KMH, not a per-mode dict) so a real-world-fast
    # car/ferry leg doesn't get allocated dramatically more/less on-screen
    # time than a walking one purely from its real-world speed.
    animation_speed_kmh = {
        **{mode: SpatialRenderer._DEFAULT_ANIMATION_SPEED_KMH for mode in mode_speed_kmh},
        **{
            str(k).lower(): float(v)
            for k, v in (settings.get("animation_speeds_kmh") or {}).items()
        },
    }

    mode_breakdown: dict[str, float] = {}
    mode_duration: dict[str, float] = {}
    total_distance_km = 0.0
    if len(route_df) > 1:
        lat_arr = route_df["latitude"].to_numpy()
        lon_arr = route_df["longitude"].to_numpy()
        seg_dist_km = GPSMath.haversine_vectorized(
            lat_arr[:-1], lon_arr[:-1], lat_arr[1:], lon_arr[1:]
        )
        total_distance_km = float(np.nansum(seg_dist_km))
        for dist, mode in zip(seg_dist_km, point_modes[1:]):
            mode_breakdown[mode] = mode_breakdown.get(mode, 0.0) + float(dist)

        # Per-mode time is derived from configured mode_speeds_kmh
        # (distance / speed), not raw GPS timestamps — the recorded track
        # often has stops/pauses baked into its timestamps (e.g. a long
        # lunch break during "walking") that would otherwise inflate the
        # summary card's duration well past a realistic estimate. Uses
        # mode_speed_kmh (the REPORTED speed), not animation_speed_kmh —
        # the on-screen pace (SpatialRenderer._mode_speed_factor) is
        # allowed to run faster than this for modes like walking, so the
        # two intentionally diverge rather than staying "consistent".
        for mode, dist_km in mode_breakdown.items():
            speed = mode_speed_kmh.get(mode) or mode_speed_kmh.get("car", 70.0)
            if speed > 0:
                mode_duration[mode] = (dist_km / speed) * 3600.0

    # Per-leg (waypoint-to-waypoint) distance/duration, so the overview can
    # show "this segment: X km, Y min" at each arrival instead of only a
    # single end-of-video total. leg_stats[i] is the leg arriving AT
    # waypoints[i + 1] (i.e. leaving waypoints[i]). Kept on raw GPS
    # timestamps (unlike mode_duration above) since these are shown
    # per-arrival right after the actual recorded leg, not folded into
    # the mode-speed-driven end summary.
    has_timestamp = "timestamp" in route_df.columns
    leg_stats: list[dict] = []
    for leg_idx in range(len(wp_indices) - 1):
        start_i, end_i = wp_indices[leg_idx], wp_indices[leg_idx + 1]
        if end_i <= start_i:
            leg_stats.append({"distance_km": 0.0, "duration_seconds": 0.0})
            continue
        seg_lat = route_df["latitude"].to_numpy()[start_i : end_i + 1]
        seg_lon = route_df["longitude"].to_numpy()[start_i : end_i + 1]
        seg_dist_km = float(
            np.nansum(
                GPSMath.haversine_vectorized(
                    seg_lat[:-1], seg_lon[:-1], seg_lat[1:], seg_lon[1:]
                )
            )
        )
        duration_seconds = (
            float(
                (
                    route_df["timestamp"].iloc[end_i]
                    - route_df["timestamp"].iloc[start_i]
                ).total_seconds()
            )
            if has_timestamp
            else 0.0
        )
        leg_stats.append(
            {"distance_km": seg_dist_km, "duration_seconds": duration_seconds}
        )

    # 3. Inject Waypoints
    if waypoints:
        logger.info("Step 4: Injecting %d custom waypoints.", len(waypoints))
        start_label = project_config.get("start_point", {}).get("label")
        end_label = project_config.get("end_point", {}).get("label")

        for idx, wp in enumerate(waypoints):
            c_idx = wp_indices[idx]
            raw_label = wp.get("label", PIPELINE_LABELS["waypoint_fallback"])

            if idx == 0 and start_label:
                raw_label = start_label
            elif idx == len(waypoints) - 1 and end_label:
                raw_label = end_label

            formatted = format_waypoint_label(raw_label, subtitle_lang)
            prefix = (
                PIPELINE_LABELS["start_prefix"] if idx == 0
                else PIPELINE_LABELS["stop_prefix"] if idx == len(waypoints) - 1
                else ""
            )
            route_labels[c_idx] = (
                f"{prefix}{formatted}" if formatted else prefix.strip(": ")
            )

            popup_img = wp.get("popup_image")
            route_popups[c_idx] = {
                "freeze_seconds": float(wp.get("freeze_seconds", 3.0)),
                "popup_image": (
                    str(popup_img[0])
                    if isinstance(popup_img, list) and popup_img
                    else (str(popup_img) if popup_img else None)
                ),
                "image_display": str(
                    wp.get("image_display", "pip")
                ).lower(),
                "triggered": False,
                # Matches the map editor's own MapArea.tsx: a stop-by
                # waypoint always renders as pinType="stopby" (dark brown, a
                # "・" dot instead of a number) and is skipped entirely by
                # the OTHER waypoints' sequential numbering — see
                # spatial_renderer/pins.py's _draw_pin/_pin_color.
                "is_stopby": bool(wp.get("isStopBy", False)),
            }

    # 4. Process Residential Sequence (3D Bypass vs 2D Generation)
    res_sequence = []
    # One travel mode per leg (same resolution order render_route_video
    # itself uses further down for each res_sequence entry: the waypoint's
    # own routeMode, else the GPS-derived point_modes at that leg's start)
    # so compute_segment_durations can weight each leg's on-screen time by
    # real-world speed instead of raw distance alone — otherwise a long,
    # fast ferry crossing gets allocated MORE screen time than a short
    # walking leg, the opposite of how it should feel.
    seg_modes = []
    for seg_i in range(max(0, len(wp_indices) - 1)):
        leg_mode = (
            str(waypoints[seg_i].get("routeMode", "")).lower()
            if seg_i < len(waypoints)
            else ""
        )
        if not leg_mode and wp_indices[seg_i] + 1 < len(point_modes):
            leg_mode = point_modes[wp_indices[seg_i] + 1]
        leg_mode = leg_mode or "walking"
        seg_modes.append(tuning.MODE_ALIASES.get(leg_mode, leg_mode))

    seg_durations = (
        MapFetcher.compute_segment_durations(
            wp_indices,
            route_df,
            target_avg_seconds=settings.get("res_target_avg_seconds", 14.0),
            # Caps any single leg's on-screen time regardless of how long
            # it is relative to its neighbors — without this, one
            # unusually long-distance leg (e.g. several km of walking)
            # could still drag on for a long time even after mode-speed
            # weighting, since that weighting is only relative to the
            # OTHER legs in the route.
            max_segment_seconds=settings.get("res_max_segment_seconds", 16.0),
            seg_modes=seg_modes,
            mode_speeds_kmh=animation_speed_kmh,
        )
        if len(wp_indices) > 1
        else []
    )

    if render_mode == "overview":
        # Overview-only: skip building the residential sequence entirely —
        # no per-leg residential map tile fetches, no residential clips
        # produced. res_sequence stays [] (set above), which
        # RouteAnimator.render already treats as "nothing to render" for
        # the residential side.
        logger.info("Step 4: render_mode=overview — skipping residential sequence.")
    elif use_3d_res:
        logger.info(
            "Step 4: 3D residential rendering is enabled. Bypassing 2D map fetch."
        )
        for seq_idx in range(max(0, len(wp_indices) - 1)):
            has_audio = seq_idx < len(audio_durations) and audio_durations[seq_idx] > 0
            total_time = (
                audio_durations[seq_idx]
                if has_audio
                else (seg_durations[seq_idx] if seq_idx < len(seg_durations) else 10.0)
            )
            res_sequence.append({"segment_duration": total_time})
    else:
        logger.info("Step 4: Generating 2D residential map sequence...")
        # Stop-by leg-merging is toggleable per project (default: merge —
        # see tuning.DEFAULT_MERGE_STOPBY_WAYPOINTS); multi-tile chunk
        # splitting is deliberately kept off here (math.inf) even though
        # process_residential_sequence now supports it — enabling it would
        # also require reworking the audio-mux/timeline position lookups
        # below to handle several clips sharing one leg's narration, which
        # is real follow-up work, not something to fold in silently here.
        sequence_data = fetcher.process_residential_sequence(
            route_df,
            waypoints,
            output_size=(img_w, img_h),
            max_chunk_distance_meters=math.inf,
            precomputed_indices=wp_indices,
            merge_stopbys=bool(
                settings.get("merge_stopby_waypoints", tuning.DEFAULT_MERGE_STOPBY_WAYPOINTS)
            ),
        )

        # Maps a waypoint's job_config "id" back to its RAW position in the
        # (unfiltered, includes stop-bys) `waypoints` list — audio_durations/
        # audio_pauses/seg_durations are all indexed by that raw position
        # (see audio_step.py's `for idx, wp in enumerate(waypoints)`), but
        # once stop-by merging can skip a waypoint as a leg boundary, a
        # leg's position in `sequence_data` no longer equals its departure
        # waypoint's raw position — every lookup below must resolve through
        # this map instead of indexing by `seq_idx` directly.
        id_to_position = {
            wp.get("id"): pos for pos, wp in enumerate(waypoints) if wp.get("id")
        }

        for seq_idx, item in enumerate(sequence_data):
            start_idx, end_idx = item["start_idx"], item["end_idx"]
            chunk = route_df.iloc[start_idx : end_idx + 1]

            # This leg's departure/arrival RAW positions in `waypoints` —
            # resolved by id (see id_to_position above), not by `seq_idx`,
            # since a merged-away stop-by can make them diverge. Falls back
            # to the old positional guess only if a waypoint is missing its
            # "id" field (older data saved before ids were assigned).
            start_pos = id_to_position.get(item.get("start_waypoint_id"))
            if start_pos is None:
                start_pos = seq_idx
            end_pos = id_to_position.get(item.get("end_waypoint_id"))
            if end_pos is None:
                end_pos = seq_idx + 1

            leg_mode = (
                str(waypoints[start_pos].get("routeMode", "")).lower()
                if start_pos < len(waypoints)
                else ""
            )
            if not leg_mode and start_idx + 1 < len(point_modes):
                leg_mode = point_modes[start_idx + 1]
            leg_mode = leg_mode or "walking"
            leg_mode = tuning.MODE_ALIASES.get(leg_mode, leg_mode)
            if str(leg_mode).lower() == "ferry" and end_pos < len(waypoints):
                start_wp, end_wp = waypoints[start_pos], waypoints[end_pos]
                cached_geometry = _resolve_leg_geometry_from_cache(
                    start_wp, end_wp, routing_cache
                )
                if cached_geometry:
                    # Use the actual routed ferry line from .routecache.json
                    # (the same polyline the map UI itself draws) instead of
                    # route_df's own GPS track for this leg, which for a
                    # ferry crossing may be sparse/inaccurate.
                    ferry_lats = np.asarray(
                        [float(pt[0]) for pt in cached_geometry]
                    )
                    ferry_lons = np.asarray(
                        [float(pt[1]) for pt in cached_geometry]
                    )
                else:
                    # No cached route for this leg — fall back to the direct
                    # water crossing between stops rather than whatever
                    # (possibly road-snapped) path route_df happens to have.
                    ferry_count = max(2, min(120, end_idx - start_idx + 1))
                    ferry_lats = np.linspace(
                        float(start_wp["lat"]), float(end_wp["lat"]), ferry_count
                    )
                    ferry_lons = np.linspace(
                        float(start_wp["lng"]), float(end_wp["lng"]), ferry_count
                    )
                chunk = pd.DataFrame(
                    {"latitude": ferry_lats, "longitude": ferry_lons}
                )
                ferry_map_path = str(
                    Path(item["img_path"]).with_name(f"res_map_ferry_{seq_idx + 1}.png")
                )
                item["img_path"] = ferry_map_path
                item["extent"] = fetcher.downloader.fetch_residential_chunk(
                    chunk, ferry_map_path, (img_w, img_h)
                )

            # Extract safe variables — indexed by start_pos (this leg's
            # departure waypoint's RAW position), not seq_idx: with stop-by
            # merging, a leg can span MULTIPLE raw waypoint-to-waypoint
            # gaps (e.g. real -> merged stop-by -> real), so its distance-
            # fallback duration sums every raw gap's own seg_durations
            # entry across [start_pos, end_pos) rather than reading a
            # single seg_durations[seq_idx]. audio_durations/audio_pauses
            # only ever come from the true departure waypoint itself
            # (start_pos) — a merged-in stop-by's own narration, if any,
            # is intentionally not played (no dedicated arrival moment for
            # it anymore, matching "just show its pin as we pass").
            has_audio = start_pos < len(audio_durations) and audio_durations[start_pos] > 0
            distance_fallback = sum(
                seg_durations[p] for p in range(start_pos, end_pos) if p < len(seg_durations)
            ) or 10.0
            total_time = audio_durations[start_pos] if has_audio else distance_fallback

            lats_arr, lons_arr = item["lats"], item["lons"]
            seg_dist = (
                float(
                    np.nansum(
                        GPSMath.haversine_vectorized(
                            lats_arr[:-1], lons_arr[:-1], lats_arr[1:], lons_arr[1:]
                        )
                    )
                )
                if len(lats_arr) > 1
                else 0.0
            )

            raw_img = item.get("img_path")
            leg_popups = [None] * len(chunk)
            if len(leg_popups) > 0:
                leg_popups[-1] = route_popups[end_idx]

            res_sequence.append(
                {
                    "img_path": (
                        str(raw_img[0])
                        if isinstance(raw_img, list) and raw_img
                        else (str(raw_img) if raw_img else None)
                    ),
                    "extent": item["extent"],
                    "lats": lats_arr,
                    "lons": lons_arr,
                    "points": _project_route_to_pixels(
                        chunk["latitude"].to_numpy(),
                        chunk["longitude"].to_numpy(),
                        item["extent"],
                        img_w,
                        img_h,
                    ),
                    "labels": route_labels[start_idx : end_idx + 1],
                    # A residential clip starts at the previous waypoint,
                    # so only the destination popup may end its route
                    # animation. Including the start popup makes the renderer
                    # terminate on the first frame of every leg.
                    "popups": leg_popups,
                    "mode": leg_mode,
                    "travel_duration": total_time,
                    "segment_duration": total_time,
                    "real_duration_seconds": (
                        (
                            chunk["timestamp"].iloc[-1] - chunk["timestamp"].iloc[0]
                        ).total_seconds()
                        if "timestamp" in chunk.columns and len(chunk) > 1
                        else 0.0
                    ),
                    "distance_km": seg_dist,
                    "pauses": (
                        audio_pauses[start_pos] if start_pos < len(audio_pauses) else []
                    ),
                    # This leg's departure waypoint's RAW position — embedded
                    # into the output clip's filename (see waypoints.py) so
                    # the audio-mux loop below and timeline_step.py's own
                    # mirrored lookup can resolve the correct narration by
                    # position instead of a blind per-clip counter, which
                    # stop-by merging would otherwise throw out of sync.
                    "start_pos": start_pos,
                    "wide_img_path": item.get("wide_img_path"),
                    "wide_extent": item.get("wide_extent"),
                    # "pos_in_chunk" (0-based index into this leg's own
                    # `points`/res_points list, not the route_df row index)
                    # is what waypoints.py actually needs to know when the
                    # traveler has passed a merged-in stop-by along the way.
                    "mid_markers": [
                        {**m, "pos_in_chunk": m["row_idx"] - start_idx}
                        for m in item.get("mid_markers", [])
                    ],
                }
            )

    # 5. Final Rendering Orchestration

    # "duration_seconds" is the per-waypoint HOLD/freeze duration default
    # (see WaypointEditor's "Hold Duration" field, a 1-8s range) — it used
    # to also be read here as the length of the ENTIRE overview animation,
    # which made any real route fly by its stops in a few seconds flat.
    # Pace the overview off the route itself instead: a baseline per leg
    # (so a burst of nearby popups has a chance to clear before the next
    # one triggers) plus time proportional to the distance actually
    # covered, clamped to a sane range either way.
    num_legs = max(1, len(wp_indices) - 1) if wp_indices else 1
    base_overview_duration = max(
        24.0, min(180.0, num_legs * 8.0 + total_distance_km * 1.5)
    )
    # Overall playback speed for the overview — 2x by default (i.e. half
    # the paced-out duration above), tunable via job_config.json's
    # settings.overview_speed_multiplier. This scales everything uniformly
    # (mode-to-mode ratios from mode_speeds_kmh are unaffected), unlike
    # that setting which only controls relative pacing between modes.
    overview_speed_multiplier = float(settings.get("overview_speed_multiplier", 2.0))
    overview_duration = max(10.0, base_overview_duration / overview_speed_multiplier)

    animator_config = {
        "output_dir": output_video_dir,
        "use_3d_res": use_3d_res,
        "res_route_path": project_config_path,
        "leg_durations": seg_durations or None,
        "duration": settings.get("duration", overview_duration),
        **{
            k: settings.get(k, default)
            for k, default in [
                ("fps", 30),
                ("line_thickness", 10),
                ("marker_radius", 24),
                ("map_font_size", 24),
                ("card_border_thickness", tuning.DEFAULT_CARD_BORDER_THICKNESS),
                ("route_line_border_thickness", tuning.DEFAULT_LINE_BORDER_THICKNESS),
                ("pause", 2.0),
                ("summary_hold", 4.0),
                ("summary_fade", 0.5),
                ("clip_summary_hold", 2.0),
                ("show_segment_summary", True),
                ("res_duration", 12.0),
                ("post_arrival_hold_seconds", 1.0),
                ("use_leg_storyboard", False),
                ("default_transition_hold_seconds", 1.5),
                ("hide_route_on_popup", False),
                ("enable_fullscreen_popups", True),
                ("hide_upcoming_pins_on_popup", False),
            ]
        },
        "line_color": tuple(settings.get("line_color", (243, 150, 33))),  # BGR blue
        "marker_color": tuple(settings.get("marker_color", (235, 150, 60))),  # blue (BGR)
        "arrived_marker_color": tuple(settings.get("arrived_marker_color", (200, 110, 30))),
        "card_border_color": tuple(
            settings.get("card_border_color", tuning.DEFAULT_CARD_BORDER_COLOR)
        ),
        "route_line_border_color": tuple(
            settings.get("route_line_border_color", tuning.DEFAULT_LINE_BORDER_COLOR)
        ),
        "trigger_radius_padding": settings.get("trigger_radius_padding", {}),
        "fullscreen_transition": settings.get("fullscreen_transition", {}),
        # Real-world average speed (km/h) per travel mode — how much
        # faster a car/ferry/etc. leg animates on screen relative to a
        # walking one is derived from these ratios (see SpatialRenderer's
        # _DEFAULT_MODE_SPEED_KMH for the fallback values). Set e.g.
        # {"walking": 3, "car": 70, "ferry": 36} in job_config.json's
        # settings to override per project.
        "mode_speeds_kmh": settings.get("mode_speeds_kmh", {}),
        "animation_speeds_kmh": settings.get("animation_speeds_kmh", {}),
        # Which summary-card template the overview/per-leg cards render as
        # ("glass" default, or "taskbar" for the notification-flyout-style
        # template — see cards.py's render_summary_card). Was missing from
        # this dict entirely, so job_config.json's settings.summary_card_style
        # never reached RouteAnimator/GraphicsEngine no matter what a
        # project set it to — self.config here IS this whole dict, not the
        # raw settings (see RouteAnimator.__init__'s own note on that).
        "summary_card_style": settings.get(
            "summary_card_style", tuning.DEFAULT_SUMMARY_CARD_STYLE
        ),
        # Per-project override of any subset of assets/config/labels_ja.json's
        # summary-card keys (mode_name, mode_duration_label, total_label,
        # distance_label, taskbar_card_title) — see cards.py's
        # merge_summary_card_labels. Same "must be forwarded through THIS
        # dict, not just read off raw settings" requirement as
        # summary_card_style above.
        "summary_card_labels": settings.get("summary_card_labels"),
    }

    animator = RouteAnimator(animator_config)

    summary = dict(cleaned_route.get("summary", {}))
    if mode_breakdown:
        summary["mode_breakdown"] = mode_breakdown
    if mode_duration:
        summary["mode_duration"] = mode_duration
        # Keep the card's "Total" consistent with the per-mode durations
        # sitting right next to it, instead of mixing a mode-speed-derived
        # breakdown with a raw-GPS-timestamp total.
        summary["total_duration_seconds"] = sum(mode_duration.values())
    if leg_stats:
        summary["leg_stats"] = leg_stats

    output_paths = animator.render(
        img_path=map_output_path,
        points=route_points,
        labels=route_labels,
        popups=route_popups,
        res_sequence=res_sequence,
        summary=summary,
        wp_indices=wp_indices,
        point_modes=point_modes,
        render_mode=render_mode,
    )

    # --- 2. ADD THIS AUDIO MUXING BLOCK ---
    if audio_paths:
        from services.vdoprocessing.vdoeditor import VideoEditor

        editor = VideoEditor()
        muxed_paths = []

        logger.info("Muxing TTS narration audio into video segments...")

        for v_path in output_paths:
            filename = Path(v_path).name
            match = RESIDENTIAL_LEG_RE.search(filename)

            if match:
                # 1-based in the filename (matches the "Waypoint N" numbering
                # everywhere else); audio_durations/audio_paths are 0-based.
                audio_idx = int(match.group(1)) - 1
                if (
                    0 <= audio_idx < len(audio_paths)
                    and audio_paths[audio_idx]
                    and os.path.exists(audio_paths[audio_idx])
                ):
                    try:
                        muxed = editor.mux_audio_to_video(
                            video_path=v_path,
                            audio_path=audio_paths[audio_idx],
                            output_filename=filename,
                        )
                        muxed_paths.append(muxed)
                    # [NOTE] [Editor] Falls back to the unmuxed video on any mux failure rather than aborting the whole pipeline over one leg's audio.
                    except Exception as e:
                        logger.error(f"Failed to mux audio for {v_path}: {e}")
                        muxed_paths.append(v_path)
                else:
                    muxed_paths.append(v_path)
            else:
                # This is the 01_overview map, pass it through silently!
                muxed_paths.append(v_path)

        output_paths = muxed_paths
    tracker.clear()
    logger.info("Step 4 complete: %d video file(s) produced.", len(output_paths))

    return output_paths
