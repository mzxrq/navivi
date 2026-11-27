"""Step 4: Render the visual map animation, synced to audio timing.

Its parts live beside it: leg_sequence.py (each leg's render entry and the
stops' pop-up data), animator_config.py (the renderer's config),
render_look.py (pin glyphs/colors, look options), render_checkpoint.py (the
render manifest) and overview_framing.py (overview padding, bands, bounding
box)."""

import json
from pathlib import Path
from typing import Any, NamedTuple, Optional

import numpy as np

from services.gpsparser.gpscalculator import GPSMath
from services.logger.progress import tracker
from services.projectfiles import ROUTE_CACHE, meta_file, write_json_atomic
from services.mapfetcher.mapfetcher import MapFetcher
from services.vdoprocessing.route2vdo import RouteAnimator
from services.vdoprocessing.spatial_renderer import SpatialRenderer
from services.config.job_config import JobConfigManager
from services import tuning
from services.mapfetcher.graphicengine.pinimage import marker_for

from .animator_config import build_animator_config
from .leg_sequence import build_leg_sequence, inject_waypoint_popups
from .narration_step import CueStore
from .helpers import (
    BASE_DIR,
    DEFAULT_FRONTEND_CONFIG,
    DEFAULT_MAP_BACKGROUND,
    _build_point_colors,
    _build_point_modes,
    _project_route_to_pixels,
    logger,
    project_route_video_dir,
)
from .overview_framing import overview_bounding_box, purge_map_images_on_language_change
from .render_checkpoint import (
    _RENDER_MANIFEST_NAME, _checkpoint_parts, _render_checkpoint_key, _short_hash, reuse_render_manifest,
)
from .render_look import _project_color


# Fallback real-world speed (km/h) used when a leg's own mode has no
# configured speed AND there's no configured "car" speed to fall back to
# either (see mode_speed_kmh.get(mode) or mode_speed_kmh.get("car", ...)
# below).
_FALLBACK_CAR_SPEED_KMH = 70.0

_SECONDS_PER_HOUR = 3600.0

# Overview animation pacing bounds/rates — see the "Pace the overview off
# the route itself" comment further down for the full rationale.
_OVERVIEW_MIN_DURATION_SECONDS = 24.0
_OVERVIEW_MAX_DURATION_SECONDS = 180.0
_OVERVIEW_SECONDS_PER_LEG = 8.0
_OVERVIEW_SECONDS_PER_KM = 1.5
_OVERVIEW_MIN_FINAL_DURATION_SECONDS = 10.0



def _checkpoint_inputs(project_config_path, cleaned_route, audio_durations, audio_pauses,
                       overview_cue_times, overview_audio_duration):
    """(the render checkpoint's key, its per-part hashes)."""
    checkpoint_key = _render_checkpoint_key(
        project_config_path, cleaned_route, audio_durations, audio_pauses
    )
    checkpoint_parts = _checkpoint_parts(
        project_config_path, cleaned_route, audio_durations, audio_pauses
    )
    if overview_cue_times:
        # Where the overview voice lands (it moves with the intro's length).
        checkpoint_parts["route.overview_voice"] = _short_hash(
            {"cues": {k: round(float(v), 2) for k, v in overview_cue_times.items()},
             "audio": round(float(overview_audio_duration or 0.0), 2)}
        )
    return checkpoint_key, checkpoint_parts


def _read_routing_cache(config_path: Path) -> dict:
    routing_cache = {}
    routecache_path = meta_file(config_path.parent, ROUTE_CACHE)
    if routecache_path.exists():
        try:
            with open(routecache_path, "r", encoding="utf-8") as f:
                routing_cache = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Step 4: Failed to read %s: %s", routecache_path, e)
    return routing_cache


def _speed_tables(settings: dict) -> tuple[dict, dict]:
    """(mode_speed_kmh, animation_speed_kmh).

    mode_speed_kmh is the real-world REPORTED speed per mode (the summary card's duration estimate);
    animation_speed_kmh only weights each residential leg's ON-SCREEN duration. Every mode shares one
    pace except walking and ferry (tuning.py's WALKING/FERRY_ANIMATION_SPEED_FACTOR, applied the same
    way by SpatialRendererBase for the overview render)."""
    mode_speed_kmh = {
        **SpatialRenderer._DEFAULT_MODE_SPEED_KMH,
        **{
            str(k).lower(): float(v)
            for k, v in (settings.get("mode_speeds_kmh") or {}).items()
        },
    }
    _walking_default_kmh = (
        SpatialRenderer._DEFAULT_ANIMATION_SPEED_KMH * tuning.WALKING_ANIMATION_SPEED_FACTOR
    )
    _default_kmh_by_mode = {
        "walking": _walking_default_kmh,
        "ferry": _walking_default_kmh * tuning.FERRY_ANIMATION_SPEED_FACTOR,
    }
    animation_speed_kmh = {
        **{
            mode: _default_kmh_by_mode.get(mode, SpatialRenderer._DEFAULT_ANIMATION_SPEED_KMH)
            for mode in mode_speed_kmh
        },
        **{
            str(k).lower(): float(v)
            for k, v in (settings.get("animation_speeds_kmh") or {}).items()
        },
    }
    return mode_speed_kmh, animation_speed_kmh


def _mode_totals(route_df, point_modes: list, mode_speed_kmh: dict) -> tuple[dict, dict, float]:
    """(km per mode, seconds per mode, total km).

    Time is distance / configured mode speed, not GPS timestamps: a recorded track often has pauses
    (a lunch break while "walking") baked in that would inflate the summary card's duration."""
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

        for mode, dist_km in mode_breakdown.items():
            speed = mode_speed_kmh.get(mode) or mode_speed_kmh.get(
                "car", _FALLBACK_CAR_SPEED_KMH
            )
            if speed > 0:
                mode_duration[mode] = (dist_km / speed) * _SECONDS_PER_HOUR
    return mode_breakdown, mode_duration, total_distance_km


def _leg_stats(route_df, wp_indices: list) -> list[dict]:
    """leg_stats[i] is the leg leaving waypoints[i] (arriving at i + 1), on raw GPS timestamps since
    these show per-arrival right after the recorded leg."""
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
    return leg_stats


def _leg_modes(wp_indices: list, waypoints: list, point_modes: list) -> list[str]:
    """One travel mode per leg (the waypoint's own routeMode, else the GPS-derived mode at the leg's
    start), so on-screen time is weighted by speed: a long fast ferry must not outweigh a short walk."""
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
    return seg_modes


def _overview_duration(wp_indices: list, total_distance_km: float, settings: dict,
                       overview_audio_duration: Optional[float]) -> float:
    """The overview's length is paced off the route (a baseline per leg plus time per km, clamped,
    divided by settings.overview_speed_multiplier) and stretched to cover its narration plus a short
    tail, since the later `-shortest` mux would otherwise cut the voice's end.
    ("duration_seconds" is the per-stop hold, never the overview's length.)"""
    num_legs = max(1, len(wp_indices) - 1) if wp_indices else 1
    base_overview_duration = max(
        _OVERVIEW_MIN_DURATION_SECONDS,
        min(
            _OVERVIEW_MAX_DURATION_SECONDS,
            num_legs * _OVERVIEW_SECONDS_PER_LEG + total_distance_km * _OVERVIEW_SECONDS_PER_KM,
        ),
    )
    overview_speed_multiplier = float(settings.get("overview_speed_multiplier", 4.0))
    overview_duration = max(
        _OVERVIEW_MIN_FINAL_DURATION_SECONDS, base_overview_duration / overview_speed_multiplier
    )
    if overview_audio_duration:
        overview_duration = max(overview_duration, overview_audio_duration + 1.0)
    return overview_duration


def _overview_bbox(fetcher, route_df, sub_overview, project_config: dict):
    """The overview's box; the sub course plays after the main one, so the map is framed to hold both."""
    framed_df = route_df
    if sub_overview:
        import pandas as pd

        lat, lon = zip(*sub_overview["track"])
        framed_df = pd.concat([route_df[["latitude", "longitude"]], pd.DataFrame({"latitude": lat, "longitude": lon})])
    return overview_bounding_box(fetcher, framed_df, project_config)


def _summary_for_render(cleaned_route: dict, mode_breakdown: dict, mode_duration: dict, leg_stats: list) -> dict:
    summary = dict(cleaned_route.get("summary", {}))
    if mode_breakdown:
        summary["mode_breakdown"] = mode_breakdown
    if mode_duration:
        summary["mode_duration"] = mode_duration
        # Keep the card's "Total" consistent with the per-mode durations beside it.
        summary["total_duration_seconds"] = sum(mode_duration.values())
    if leg_stats:
        summary["leg_stats"] = leg_stats
    return summary


def _write_render_manifest(manifest_path: Path, output_video_dir: str, output_paths: list,
                           checkpoint_key, checkpoint_parts: dict) -> None:
    try:
        Path(output_video_dir).mkdir(parents=True, exist_ok=True)
        write_json_atomic(
            manifest_path,
            {"output_paths": output_paths, "input_hash": checkpoint_key, "input_parts": checkpoint_parts},
        )
    except OSError as e:
        logger.warning("Step 4: Failed to write render manifest: %s", e)


def _load_project_config(project_config_path: str):
    """(project_config, config_path, job_config_mgr).

    Loaded through JobConfigManager (not json.load) so every path in the file is normalized to
    absolute: a hand-edited/copied project's RELATIVE image path would otherwise be resolved against
    the process CWD and its popup card silently never render."""
    project_config = {}
    config_path = Path(project_config_path)
    job_config_mgr: Optional[JobConfigManager] = None
    if config_path.exists():
        job_config_mgr = JobConfigManager(str(config_path))
        project_config = job_config_mgr.data
    return project_config, config_path, job_config_mgr


class _Overview(NamedTuple):
    """The overview's background map and what was framed for it."""
    fetcher: Any
    sub_overview: Optional[dict]
    bbox: Any
    map_output_path: str
    extent: Any
    img_w: int
    img_h: int


def _fetch_overview(job_config_mgr, config_path: Path, route_df, project_config: dict,
                    render_mode: str, map_output_path: str) -> _Overview:
    logger.info("Step 4: Computing bounding box and fetching overview map tile...")
    tracker.show("Fetching overview map tile...")

    # The job_config is passed explicitly so the tile cache lands under THIS project's directory_path
    # even when this runs as its own process without process_gps having initialized the singleton.
    fetcher = MapFetcher(job_config=job_config_mgr or JobConfigManager(str(config_path)))

    purge_map_images_on_language_change(config_path.parent, project_config.get("map_language"))
    from services.config.sub_course import sub_course_overview

    sub_overview = sub_course_overview(project_config, config_path.parent) if render_mode != "residential" else None
    bbox = _overview_bbox(fetcher, route_df, sub_overview, project_config)

    map_output_path, extent, (img_w, img_h) = fetcher.fetch_image(
        bounding_box=bbox, output_filename=map_output_path,
        raster=render_mode == "recap_frame",  # a layout preview, not the video: stays off the GPU
    )
    if not map_output_path:
        raise RuntimeError(
            "Map fetch failed - cannot render video without background map."
        )
    return _Overview(fetcher, sub_overview, bbox, map_output_path, extent, img_w, img_h)


class _RouteGeometry(NamedTuple):
    route_points: Any
    route_labels: list
    route_popups: list
    wp_indices: list
    routing_cache: dict
    point_modes: list
    point_colors: Any


def _route_geometry(route_df, ov: _Overview, waypoints: list, config_path: Path) -> _RouteGeometry:
    route_points = _project_route_to_pixels(
        route_df["latitude"].to_numpy(),
        route_df["longitude"].to_numpy(),
        ov.extent,
        ov.img_w,
        ov.img_h,
    )
    route_labels = [
        row["store_name"] if row.get("is_landmarked") else None
        for _, row in route_df.iterrows()
    ]
    route_popups = [None] * len(route_points)
    wp_indices = MapFetcher.build_waypoint_index(route_df, waypoints)
    routing_cache = _read_routing_cache(config_path)
    point_modes = _build_point_modes(len(route_points), wp_indices, waypoints, routing_cache)
    point_colors = _build_point_colors(len(route_points), wp_indices, waypoints)
    return _RouteGeometry(route_points, route_labels, route_popups, wp_indices, routing_cache, point_modes, point_colors)


class _RouteStats(NamedTuple):
    mode_speed_kmh: dict
    animation_speed_kmh: dict
    mode_breakdown: dict
    mode_duration: dict
    total_distance_km: float
    leg_stats: list


def _route_stats(route_df, geo: _RouteGeometry, settings: dict) -> _RouteStats:
    mode_speed_kmh, animation_speed_kmh = _speed_tables(settings)
    mode_breakdown, mode_duration, total_distance_km = _mode_totals(route_df, geo.point_modes, mode_speed_kmh)
    leg_stats = _leg_stats(route_df, geo.wp_indices)
    return _RouteStats(mode_speed_kmh, animation_speed_kmh, mode_breakdown, mode_duration, total_distance_km, leg_stats)


def _build_res_sequence(route_df, ov: _Overview, geo: _RouteGeometry, stats: _RouteStats, project_config: dict,
                        config_path: Path, marker_base_dir: str, audio_and_mode: tuple) -> tuple[list, list]:
    """(the residential leg sequence, each leg's on-screen seconds). `audio_and_mode` is
    (audio_durations, audio_pauses, render_mode, leg_index)."""
    audio_durations, audio_pauses, render_mode, leg_index = audio_and_mode
    settings = project_config.get("settings", {})
    waypoints = project_config.get("waypoints", [])
    res_sequence = []
    cue_store = CueStore(config_path.parent)
    seg_modes = _leg_modes(geo.wp_indices, waypoints, geo.point_modes)

    seg_durations = (
        MapFetcher.compute_segment_durations(
            geo.wp_indices,
            route_df,
            target_avg_seconds=settings.get("res_target_avg_seconds", 14.0),
            # Caps one unusually long leg even after mode-speed weighting (which is only relative to the other legs).
            max_segment_seconds=settings.get("res_max_segment_seconds", 16.0),
            seg_modes=seg_modes,
            mode_speeds_kmh=stats.animation_speed_kmh,
        )
        if len(geo.wp_indices) > 1
        else []
    )

    build_leg_sequence(
        audio_durations=audio_durations,
        audio_pauses=audio_pauses,
        cue_store=cue_store,
        fetcher=ov.fetcher,
        img_h=ov.img_h,
        img_w=ov.img_w,
        leg_index=leg_index,
        marker_base_dir=marker_base_dir,
        point_modes=geo.point_modes,
        project_config=project_config,
        render_mode=render_mode,
        res_sequence=res_sequence,
        route_df=route_df,
        route_labels=geo.route_labels,
        route_popups=geo.route_popups,
        routing_cache=geo.routing_cache,
        seg_durations=seg_durations,
        settings=settings,
        waypoints=waypoints,
        wp_indices=geo.wp_indices,
    )
    return res_sequence, seg_durations


def render_route_video(
    cleaned_route: dict,
    project_config_path: str = str(DEFAULT_FRONTEND_CONFIG),
    output_video_dir: Optional[str] = None,
    map_output_path: str = str(DEFAULT_MAP_BACKGROUND),
    audio_durations: Optional[list[float]] = None,
    audio_pauses: Optional[list[Any]] = None,
    overview_audio_duration: Optional[float] = None,
    overview_cue_times: Optional[dict] = None,
    force: bool = False,
    render_mode: str = "both",
    leg_index: Optional[int] = None,
    leg_file: Optional[int] = None,
) -> list[str]:
    """Generates the visual map animation using synced audio timing.

    Checkpointing: a manifest of the output paths of the last successful render plus a content hash
    of its inputs (_render_checkpoint_key) is written to `.render_manifest.json` in output_video_dir.
    If every listed path is still a valid file and the inputs hash the same, the render is skipped
    and those paths returned; any of those failing re-renders, same as `force`.

    The manifest is only READ and WRITTEN when render_mode == "both" (run_full_pipeline's call). A
    standalone "overview"/"residential" call (the editor's "recreate this video" actions) always
    regenerates, and must not write a manifest listing only half the outputs that a later
    full_pipeline run would wrongly trust.

    render_mode: "overview" skips the residential leg sequence entirely; "residential" still fetches
    the overview tile (route_points/img_w/img_h are shared) but skips the overview animation; "both"
    renders everything.

    `overview_audio_duration`: the overview narration's synthesized length, used only to size the
    overview render so it is never shorter than its voice. Every clip produced here stays silent;
    narration is muxed only at final export (VideoExporter.concat_from_timeline) so the NLE editor
    can edit video and audio independently.

    `leg_index`: renders only that ONE leg of the residential sequence (0-indexed in travel order);
    no effect on the overview. None renders every leg. `leg_file`: every leg is worked out
    (neighbours: street views, the walk going on) but only that file's leg is rendered.
    """
    logger.info("Step 4: Rendering Video Engine — starting.")

    manifest_path = Path(output_video_dir) / _RENDER_MANIFEST_NAME
    is_full_pipeline_render = render_mode == "both"
    checkpoint_key, checkpoint_parts = _checkpoint_inputs(
        project_config_path, cleaned_route, audio_durations, audio_pauses,
        overview_cue_times, overview_audio_duration,
    )
    overview_stale = False
    if is_full_pipeline_render and not force and manifest_path.exists():
        cached, overview_stale = reuse_render_manifest(
            manifest_path, checkpoint_key, checkpoint_parts, project_config_path
        )
        if cached is not None:
            return cached

    route_df = cleaned_route.get("route")
    if route_df is None or route_df.empty:
        raise ValueError("Cannot render a navigation video from an empty route.")

    project_config, config_path, job_config_mgr = _load_project_config(project_config_path)
    project_name = project_config.get("project_name", "Navigation Project")

    if output_video_dir is None:
        output_video_dir = str(
            project_route_video_dir(project_config.get("directory_path", BASE_DIR))
        )

    tracker.show(f"Rendering overview & residential video: {project_name}")

    settings = project_config.get("settings", {})
    # The user's own pin pictures (customMarker / routeMarker); empty -> every pin stays the built-in teardrop.
    route_marker = marker_for({}, settings, str(Path(project_config_path).parent))
    ctx = _RenderCtx(
        project_config, config_path, job_config_mgr, project_config_path, output_video_dir, map_output_path,
        render_mode, force, overview_stale, overview_audio_duration, overview_cue_times, leg_index, leg_file,
        route_marker, audio_durations or [], audio_pauses or [],
    )
    output_paths = _render_project(ctx, cleaned_route, route_df)

    # [NOTE] [Editor] Narration is deliberately never muxed into these clips: timeline.json carries
    # video and audio as independent tracks, muxed once at final export (concat_from_timeline).
    tracker.clear()
    logger.info("Step 4 complete: %d video file(s) produced.", len(output_paths))

    # Only a "both" render is a complete, resumable checkpoint (see the docstring).
    if is_full_pipeline_render:
        _write_render_manifest(manifest_path, output_video_dir, output_paths, checkpoint_key, checkpoint_parts)

    return output_paths


class _RenderCtx(NamedTuple):
    """What one render of a project carries from stage to stage."""
    project_config: dict
    config_path: Path
    job_config_mgr: Any
    project_config_path: str
    output_video_dir: str
    map_output_path: str
    render_mode: str
    force: bool
    overview_stale: bool
    overview_audio_duration: Optional[float]
    overview_cue_times: Optional[dict]
    leg_index: Optional[int]
    leg_file: Optional[int]
    route_marker: Any
    audio_durations: list
    audio_pauses: list

    @property
    def settings(self) -> dict:
        return self.project_config.get("settings", {})

    @property
    def waypoints(self) -> list:
        return self.project_config.get("waypoints", [])

    @property
    def marker_base_dir(self) -> str:
        return str(Path(self.project_config_path).parent)


def _render_project(ctx: _RenderCtx, cleaned_route: dict, route_df) -> list[str]:
    """Overview map, route geometry, leg sequence, then the animator's render; returns its output paths."""
    ov = _fetch_overview(ctx.job_config_mgr, ctx.config_path, route_df, ctx.project_config, ctx.render_mode,
                         ctx.map_output_path)
    geo = _route_geometry(route_df, ov, ctx.waypoints, ctx.config_path)
    stats = _route_stats(route_df, geo, ctx.settings)
    _inject_popups(ctx, geo)
    res_sequence, seg_durations = _build_res_sequence(
        route_df, ov, geo, stats, ctx.project_config, ctx.config_path, ctx.marker_base_dir,
        (ctx.audio_durations, ctx.audio_pauses, ctx.render_mode, ctx.leg_index),
    )
    overview_duration = _overview_duration(
        geo.wp_indices, stats.total_distance_km, ctx.settings, ctx.overview_audio_duration
    )
    animator = _make_animator(ctx, overview_duration, seg_durations)

    summary = _summary_for_render(cleaned_route, stats.mode_breakdown, stats.mode_duration, stats.leg_stats)
    if ov.sub_overview:
        animator.spatial_renderer.config["sub_course_overview"] = _sub_overview_frame(
            ov.sub_overview, route_df, geo.wp_indices, summary, stats.mode_speed_kmh, ov.extent, ov.img_w, ov.img_h
        )

    return animator.render(
        img_path=ov.map_output_path,
        points=geo.route_points,
        labels=geo.route_labels,
        popups=geo.route_popups,
        res_sequence=res_sequence,
        summary=summary,
        wp_indices=geo.wp_indices,
        point_modes=geo.point_modes,
        point_colors=geo.point_colors,
        render_mode=ctx.render_mode,
        # The bbox/extent the overview background was fetched with, for the pydeck zoom-in intro and
        # for re-projecting a stop-by pin from its own lat/lng onto this exact image.
        overview_bounding_box=ov.bbox,
        overview_extent=ov.extent,
    )


def _inject_popups(ctx: _RenderCtx, geo: _RouteGeometry) -> None:
    inject_waypoint_popups(
        audio_durations=ctx.audio_durations,
        marker_base_dir=ctx.marker_base_dir,
        project_config=ctx.project_config,
        route_labels=geo.route_labels,
        route_popups=geo.route_popups,
        settings=ctx.settings,
        subtitle_lang=ctx.settings.get("subtitle_language", "en"),
        waypoints=ctx.waypoints,
        wp_indices=geo.wp_indices,
    )


def _make_animator(ctx: _RenderCtx, overview_duration: float, seg_durations: list):
    animator_config = build_animator_config(
        config_path=ctx.config_path,
        force=ctx.force,
        is_full_pipeline_render=ctx.render_mode == "both",
        marker_base_dir=ctx.marker_base_dir,
        # Resolved once up front: the arrived-pin color derives from it when the project names none.
        marker_color_bgr=_project_color(ctx.settings, "marker_color", (235, 150, 60)),
        output_video_dir=ctx.output_video_dir,
        overview_audio_duration=ctx.overview_audio_duration,
        overview_cue_times=ctx.overview_cue_times,
        overview_duration=overview_duration,
        overview_stale=ctx.overview_stale,
        project_config=ctx.project_config,
        project_config_path=ctx.project_config_path,
        route_marker=ctx.route_marker,
        seg_durations=seg_durations,
        settings=ctx.settings,
        # The pydeck chase camera is the default residential engine; false falls back to the flat 2D renderer.
        use_pydeck_pedestrian=bool(ctx.settings.get("use_pydeck_pedestrian", True)),
    )
    if ctx.leg_file is not None:
        animator_config["only_leg_file"] = int(ctx.leg_file)
    return RouteAnimator(animator_config)



def _sub_overview_frame(sub: dict, route_df, wp_indices: list, summary: dict, mode_speed_kmh: dict,
                        extent, img_w: int, img_h: int) -> dict:
    """The sub course on the overview's own image: its track and stops in pixels, plus its summary card's numbers:
    the main course from its start to the branch stop, then the sub course (what someone taking it walks)."""
    lat = np.array([p[0] for p in sub["track"]])
    lon = np.array([p[1] for p in sub["track"]])
    sub_km = float(np.nansum(GPSMath.haversine_vectorized(lat[:-1], lon[:-1], lat[1:], lon[1:])))
    main_km, main_s = float(summary.get("total_distance_km") or 0.0), float(summary.get("total_duration_seconds") or 0.0)
    branch = wp_indices[sub["from_index"]] if 0 <= sub["from_index"] < len(wp_indices) else 0
    if branch > 0 and len(route_df) > 1:
        m_lat, m_lon = route_df["latitude"].to_numpy()[: branch + 1], route_df["longitude"].to_numpy()[: branch + 1]
        before_km = float(np.nansum(GPSMath.haversine_vectorized(m_lat[:-1], m_lon[:-1], m_lat[1:], m_lon[1:])))
    else:
        before_km = 0.0
    before_s = main_s * before_km / main_km if main_km > 0 else 0.0
    speed = mode_speed_kmh.get(sub["mode"]) or mode_speed_kmh.get("walking") or 4.0
    sub_s = sub_km / speed * _SECONDS_PER_HOUR
    stop_px = _project_route_to_pixels(
        np.array([s["lat"] for s in sub["stops"]], dtype=float), np.array([s["lng"] for s in sub["stops"]], dtype=float),
        extent, img_w, img_h,
    )
    return {
        "points": [tuple(map(int, p)) for p in _project_route_to_pixels(lat, lon, extent, img_w, img_h)],
        "stops": [{**s, "x": int(p[0]), "y": int(p[1])} for s, p in zip(sub["stops"], stop_px)],
        "mode": sub["mode"],
        "name": sub["name"],
        "summary": {
            "total_distance_km": before_km + sub_km,
            "total_duration_seconds": before_s + sub_s,
            "mode_breakdown": {sub["mode"]: before_km + sub_km},
            "mode_duration": {sub["mode"]: before_s + sub_s},
        },
    }
