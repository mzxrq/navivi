"""Step 4: Render the visual map animation, synced to audio timing.

Its parts live beside it: leg_sequence.py (each leg's render entry and the
stops' pop-up data), animator_config.py (the renderer's config),
render_look.py (pin glyphs/colors, look options), render_checkpoint.py (the
render manifest) and overview_framing.py (overview padding, bands, bounding
box)."""

import json
from pathlib import Path
from typing import Any, Optional

import numpy as np

from services.gpsparser.gpscalculator import GPSMath
from services.logger.progress import tracker
from services.projectfiles import ROUTE_CACHE, meta_file
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
) -> list[str]:
    """Generates the visual map animation using synced audio timing.

    Checkpointing: this step's internals branch too heavily (2D/3D
    residential, ferry legs, overview map) to check each sub-output
    individually, so instead a manifest of the exact output paths from the
    last successful render — plus a content hash of the inputs that
    produced them (see _render_checkpoint_key) — is written to
    `.render_manifest.json` in output_video_dir. If that manifest exists,
    every path it lists is still a valid file, AND the current inputs hash
    to the same value stored in the manifest, the whole (expensive) render
    is skipped and those paths are returned directly. Any of those three
    failing (a missing/deleted output, or job_config.json/the route/the
    narration having changed since) re-renders, same as `force` set.

    The manifest is only READ (to skip) and WRITTEN when render_mode ==
    "both" — i.e. only run_full_pipeline's own call, gated by its
    --force flag, ever resumes from or updates this checkpoint. A
    standalone render_mode="overview"/"residential" call (from
    services/cli/gps_commands.py's test_overview_video /
    test_residential_video — the map editor's own "recreate this video"
    actions) always regenerates from scratch: those calls exist
    specifically so a user can force one piece to redo, and honoring a
    stale checkpoint there would silently no-op the very action they
    asked for. It also fixes a latent correctness bug this used to have:
    a standalone overview-only run's manifest listed ONLY the overview
    path, so a later full_pipeline run could read that incomplete
    manifest and wrongly skip rendering the residential clips it never
    actually produced.

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
    was asked for.

    `overview_audio_duration`: the project's top-level "overview_narration"
    script's already-synthesized audio length (audio_step.generate_audio's
    "overview_audio_duration" return key) — used only to size the overview
    render's own duration (see below) so it's never shorter than its
    narration; the audio itself is never muxed in here (or anywhere else
    in this function). Every clip this function produces — overview,
    residential legs — stays silent; narration stays a separate file/track
    all the way through the pipeline, only muxed onto its video at final
    export (VideoExporter.concat_from_timeline), so a frontend NLE editor
    can still edit video and audio independently up to that point.

    `leg_index`: when given, renders only that ONE leg of the residential
    sequence (0-indexed into res_sequence, i.e. the Nth clip in travel
    order) instead of the whole route — a fast way to sanity-check one
    leg's rendering without paying for every other leg's map tile
    fetch/render too. No effect on the overview (render_mode="overview"
    still renders the whole-route overview regardless). Ignored (renders
    every leg, as before) when None.
    """
    logger.info("Step 4: Rendering Video Engine — starting.")

    manifest_path = Path(output_video_dir) / _RENDER_MANIFEST_NAME
    is_full_pipeline_render = render_mode == "both"
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

    # 1. Load Config & Settings Early
    #
    # Loaded through JobConfigManager (not a plain json.load, as this used
    # to be) so every path in the file — directory_path, each waypoint's
    # images/popup_image/popup_video, thumbnail_path, source_files — is
    # normalized to absolute first (see JobConfigManager._resolve_relative_
    # paths). job_config.json is written with absolute paths by the app,
    # but it's also a file people hand-edit or copy between projects/
    # machines, where a RELATIVE image path ("assets/image/x.jpg") is the
    # only spelling that still works. Reading it raw here meant every
    # downstream os.path.exists(popup_image) check (e.g.
    # graphicengine/popup_box.py's render_popup_box) was resolved against
    # the process's CWD instead of the project folder — for any project
    # using relative paths, popup_image silently failed that check and its
    # card just never rendered, with no error anywhere in the pipeline.
    project_config = {}
    config_path = Path(project_config_path)
    job_config_mgr: Optional[JobConfigManager] = None
    if config_path.exists():
        job_config_mgr = JobConfigManager(str(config_path))
        project_config = job_config_mgr.data

    project_name = project_config.get("project_name", "Navigation Project")

    # Defaults to the project's OWN folder (job_config.json's directory_path
    # — the same "video" subfolder every other stage already writes to:
    # audio_step.py, subtitle_step.py, intro_step.py/outro_step.py) rather
    # than a fixed install-relative path — a caller can still override this
    # explicitly (every real caller currently does).
    if output_video_dir is None:
        output_video_dir = str(
            project_route_video_dir(project_config.get("directory_path", BASE_DIR))
        )

    tracker.show(f"Rendering overview & residential video: {project_name}")

    settings = project_config.get("settings", {})
    waypoints = project_config.get("waypoints", [])
    # The user's own pin pictures (customMarker / routeMarker); empty -> every pin stays the built-in teardrop.
    marker_base_dir = str(Path(project_config_path).parent)
    route_marker = marker_for({}, settings, marker_base_dir)
    # use_pydeck_pedestrian (the GeoJsonLayer chase camera, top-down ->
    # follow) is now the DEFAULT residential engine — see route2vdo.py's
    # RouteAnimator.render, which picks it unless a project explicitly sets
    # it false. use_3d_res (the older vehicle-scenegraph renderer) is opt-in
    # and only actually used when pydeck-pedestrian is explicitly disabled
    # (both flags gate the res_sequence build below the same way they gate
    # RouteAnimator.render's own engine choice, so the two stay in sync).
    use_pydeck_pedestrian = bool(settings.get("use_pydeck_pedestrian", True))
    use_3d_res = bool(settings.get("use_3d_res", False)) and not use_pydeck_pedestrian
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
    # process_gps having initialized the singleton first. Reuses the same
    # instance project_config was already loaded from above instead of
    # constructing (and re-loading/re-normalizing) a second one.
    fetcher = MapFetcher(job_config=job_config_mgr or JobConfigManager(str(config_path)))

    purge_map_images_on_language_change(config_path.parent, project_config.get("map_language"))
    bbox = overview_bounding_box(fetcher, route_df, project_config)

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
    routecache_path = meta_file(config_path.parent, ROUTE_CACHE)
    if routecache_path.exists():
        try:
            with open(routecache_path, "r", encoding="utf-8") as f:
                routing_cache = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Step 4: Failed to read %s: %s", routecache_path, e)

    point_modes = _build_point_modes(len(route_points), wp_indices, waypoints, routing_cache)
    point_colors = _build_point_colors(len(route_points), wp_indices, waypoints)

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
    # time than a walking one purely from its real-world speed — except
    # walking and ferry, which get their own defaults (see tuning.py's
    # WALKING/FERRY_ANIMATION_SPEED_FACTOR and SpatialRendererBase.__init__,
    # which applies the identical adjustment for the overview render).
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
            speed = mode_speed_kmh.get(mode) or mode_speed_kmh.get(
                "car", _FALLBACK_CAR_SPEED_KMH
            )
            if speed > 0:
                mode_duration[mode] = (dist_km / speed) * _SECONDS_PER_HOUR

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
    inject_waypoint_popups(
        audio_durations=audio_durations,
        marker_base_dir=marker_base_dir,
        project_config=project_config,
        route_labels=route_labels,
        route_popups=route_popups,
        settings=settings,
        subtitle_lang=subtitle_lang,
        waypoints=waypoints,
        wp_indices=wp_indices,
    )

    # 4. Process Residential Sequence (3D Bypass vs 2D Generation)
    res_sequence = []
    # One travel mode per leg (same resolution order render_route_video
    # itself uses further down for each res_sequence entry: the waypoint's
    # own routeMode, else the GPS-derived point_modes at that leg's start)
    # so compute_segment_durations can weight each leg's on-screen time by
    # real-world speed instead of raw distance alone — otherwise a long,
    # fast ferry crossing gets allocated MORE screen time than a short
    # walking leg, the opposite of how it should feel.
    cue_store = CueStore(config_path.parent)
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

    build_leg_sequence(
        audio_durations=audio_durations,
        audio_pauses=audio_pauses,
        cue_store=cue_store,
        fetcher=fetcher,
        img_h=img_h,
        img_w=img_w,
        leg_index=leg_index,
        marker_base_dir=marker_base_dir,
        point_modes=point_modes,
        project_config=project_config,
        render_mode=render_mode,
        res_sequence=res_sequence,
        route_df=route_df,
        route_labels=route_labels,
        route_popups=route_popups,
        routing_cache=routing_cache,
        seg_durations=seg_durations,
        settings=settings,
        use_3d_res=use_3d_res,
        waypoints=waypoints,
        wp_indices=wp_indices,
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
        _OVERVIEW_MIN_DURATION_SECONDS,
        min(
            _OVERVIEW_MAX_DURATION_SECONDS,
            num_legs * _OVERVIEW_SECONDS_PER_LEG + total_distance_km * _OVERVIEW_SECONDS_PER_KM,
        ),
    )
    # Overall playback speed for the overview — 4x by default (i.e. a
    # quarter of the paced-out duration above), tunable via
    # job_config.json's settings.overview_speed_multiplier. This scales
    # everything uniformly (mode-to-mode ratios from mode_speeds_kmh are
    # unaffected), unlike that setting which only controls relative pacing
    # between modes.
    overview_speed_multiplier = float(settings.get("overview_speed_multiplier", 4.0))
    overview_duration = max(
        _OVERVIEW_MIN_FINAL_DURATION_SECONDS, base_overview_duration / overview_speed_multiplier
    )
    # The overview clip's narration is muxed on with `-shortest` (see
    # VideoEditor.mux_audio_to_video), which truncates the MUXED OUTPUT to
    # whichever of video/audio is shorter -- since this duration is paced
    # off the route (leg count/distance), not the narration script, a
    # longer overview_narration than the route-paced duration above used
    # to get its own tail cut off by mux, ending mid-sentence. Stretching
    # the render to at least cover the narration (plus a short tail so the
    # last word isn't clipped right at the final frame) means the video is
    # never the shorter stream once mux runs.
    if overview_audio_duration:
        overview_duration = max(overview_duration, overview_audio_duration + 1.0)

    # Resolved once up front: the arrived-pin color derives from it when
    # the project doesn't name one of its own (see _arrived_marker_color).
    marker_color_bgr = _project_color(settings, "marker_color", (235, 150, 60))

    animator_config = build_animator_config(
        config_path=config_path,
        force=force,
        is_full_pipeline_render=is_full_pipeline_render,
        marker_base_dir=marker_base_dir,
        marker_color_bgr=marker_color_bgr,
        output_video_dir=output_video_dir,
        overview_audio_duration=overview_audio_duration,
        overview_cue_times=overview_cue_times,
        overview_duration=overview_duration,
        overview_stale=overview_stale,
        project_config=project_config,
        project_config_path=project_config_path,
        route_marker=route_marker,
        seg_durations=seg_durations,
        settings=settings,
        use_3d_res=use_3d_res,
        use_pydeck_pedestrian=use_pydeck_pedestrian,
    )

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

    # Only a fallback for the use_3d_res branch above -- the far more common
    # pydeck/2D branch already filtered res_sequence down to just leg_index
    # at its own process_residential_sequence(leg_index=...) call, well
    # before any per-leg map tile fetch ever ran, so res_sequence there is
    # already length <= 1 and does NOT need (or want) re-slicing here.
    if leg_index is not None and use_3d_res and res_sequence:
        if not (0 <= leg_index < len(res_sequence)):
            raise ValueError(
                f"leg_index {leg_index} out of range — this route has {len(res_sequence)} leg(s) (0-{len(res_sequence) - 1})."
            )
        logger.info(
            "Step 4: leg_index=%d given — rendering only that one leg of %d.",
            leg_index, len(res_sequence),
        )
        res_sequence = [res_sequence[leg_index]]

    output_paths = animator.render(
        img_path=map_output_path,
        points=route_points,
        labels=route_labels,
        popups=route_popups,
        res_sequence=res_sequence,
        summary=summary,
        wp_indices=wp_indices,
        point_modes=point_modes,
        point_colors=point_colors,
        render_mode=render_mode,
        # Same bbox the overview background (map_output_path) was just
        # fetched with — needed by the dynamic pydeck zoom-in intro (see
        # overview.py) to re-render fresh, correctly-zoomed frames toward
        # the start pin from the SAME base view the static background
        # already shows, rather than an unrelated one.
        overview_bounding_box=bbox,
        # Pixel-projection extent for the SAME overview background image
        # (map_output_path/route_points above) — lets a stop-by waypoint's
        # pin be re-projected from its own true lat/lng (see route_popups
        # above) onto this exact image instead of only ever using the
        # nearest matched point on the recorded track.
        overview_extent=extent,
    )

    # [NOTE] [Editor] Narration audio is deliberately NOT muxed into these
    # clips here (or anywhere else in the pipeline) — every rendered video
    # (overview, residential legs, attraction clips) stays silent all the
    # way through, and its narration stays a separate file. timeline.json
    # (see timeline_step.build_timeline) carries each clip's video AND
    # audio paths as two independent tracks so a frontend NLE editor can
    # trim/swap/re-time either one without re-touching the other; only the
    # VERY LAST step — VideoExporter.concat_from_timeline, at final export —
    # actually muxes each track's audio onto its video, once, right before
    # concatenation. (This used to mux audio in here per-clip, which baked
    # narration into the video file itself with no way to edit it
    # separately afterward.)
    tracker.clear()
    logger.info("Step 4 complete: %d video file(s) produced.", len(output_paths))

    # Only a "both" (full-pipeline) render's output set is a complete,
    # resumable checkpoint — see this function's own docstring. Writing
    # a manifest for a standalone overview/residential-only render would
    # let a LATER full_pipeline run read it back and wrongly skip
    # rendering whichever half this run never produced.
    if is_full_pipeline_render:
        try:
            Path(output_video_dir).mkdir(parents=True, exist_ok=True)
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"output_paths": output_paths, "input_hash": checkpoint_key, "input_parts": checkpoint_parts},
                    f, ensure_ascii=False, indent=2,
                )
        except OSError as e:
            logger.warning("Step 4: Failed to write render manifest: %s", e)

    return output_paths
