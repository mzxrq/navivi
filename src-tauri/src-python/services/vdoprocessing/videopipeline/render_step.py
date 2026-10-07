"""Step 4: Render the visual map animation, synced to audio timing."""

import hashlib
import json
import math
import re
from services.localization.cues import tags_at_sentence_start
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from services.gpsparser.gpscalculator import GPSMath
from services.logger.progress import tracker
from services.projectfiles import NARRATION_CUES, ROUTE_CACHE, meta_file
from services.mapfetcher.mapfetcher import MapFetcher
from services.vdoprocessing.route2vdo import RouteAnimator
from services.vdoprocessing.route_inputs import overview_flags_hash, photo_inputs_hash, route_inputs_hash
from services.vdoprocessing.spatial_renderer import SpatialRenderer
from services.localization.localization import format_waypoint_label
from services.config.job_config import JobConfigManager
from services.config.upscaled_images import IMAGE_KEYS, apply_upscaled_images
from services import tuning, video_text

from .audio_step import overview_tagged_script
from .narration_step import MAX_EARLY_ARRIVAL_SECONDS, CueStore, leg_walk_plan
from .helpers import (
    BASE_DIR,
    DEFAULT_FRONTEND_CONFIG,
    DEFAULT_MAP_BACKGROUND,
    _build_point_colors,
    _build_point_modes,
    leg_line_color_rgb,
    _project_route_to_pixels,
    _resolve_leg_geometry_from_cache,
    attraction_videos_enabled,
    logger,
    output_is_valid,
    project_route_video_dir,
)

def _project_color(
    settings: dict, key: str, default_bgr: tuple
) -> tuple:
    """Reads one color setting out of job_config.json, as BGR.

    The app writes colors as RGB triples (it stores exactly what the color
    picker produced — settings.marker_color [59, 130, 246] is #3B82F6, the
    blue shown in the editor), while every renderer downstream draws in
    OpenCV's BGR. Handing the value straight through — which is what this
    used to do — rendered a project's chosen blue as #F6823B orange, i.e.
    a configured color came out as its own channel-reversed twin. The
    channels are swapped here, at the single point where a project's
    settings become renderer config, so there is exactly one place that
    knows about the difference.

    `default_bgr` is used unchanged when the project didn't set the key:
    the defaults live in tuning.py and are already authored in BGR.
    """
    raw = settings.get(key)
    if raw is None:
        return tuple(default_bgr)
    try:
        r, g, b = (int(v) for v in list(raw)[:3])
    except (TypeError, ValueError):
        logger.warning(
            "Step 4: settings.%s is not an [r, g, b] triple (%r) — using the default.",
            key, raw,
        )
        return tuple(default_bgr)
    return (b, g, r)


# How much darker a pin goes once its waypoint has been reached, when the
# project sets marker_color but no arrived_marker_color of its own: the
# two defaults in tuning.py sit about this far apart, so one configured
# color still yields the same "deepens on arrival" pairing rather than
# leaving every arrived pin on an unrelated stock blue.
_ARRIVED_COLOR_DARKEN = 0.78


def overview_pin_glyphs(waypoints: list) -> dict:
    """{waypoint position: the glyph its pin shows on the overview}: "S" for
    the first, "E" for the last, "・" for a stop-by, and 1, 2, 3... for the
    rest in visit order - the same numbering as spatial_renderer's
    _pin_label_and_color (S and stop-bys don't take a number), so a leg's
    map can show "pin 1 -> pin 2" exactly as the overview does."""
    glyphs = {}
    order = 0
    last = len(waypoints) - 1
    for pos, wp in enumerate(waypoints):
        # A waypoint skipped in video export is drawn like a stop-by too.
        if wp.get("isStopBy") or (wp.get("skipAssetGeneration") and 0 < pos < last):
            glyphs[pos] = "・"
            continue
        if pos == 0:
            glyphs[pos] = "S"
            continue
        order += 1
        glyphs[pos] = "E" if pos == last and order != 1 else str(order)
    return glyphs


def _leg_pin(glyph, settings: dict, arrived: bool) -> Optional[dict]:
    """One end of a leg's pin, in the overview's colors: S green, E red, a
    stop-by brown, a numbered stop the marker color (the darker "arrived"
    shade for the pin the leg departs from, which is already visited)."""
    if not glyph:
        return None
    if glyph == "S":
        color = tuning.START_PIN_COLOR
    elif glyph == "E":
        color = tuning.END_PIN_COLOR
    elif glyph == "・":
        color = tuning.STOPBY_PIN_COLOR
    else:
        marker = _project_color(settings, "marker_color", (235, 150, 60))
        color = _arrived_marker_color(settings, marker) if arrived else marker
    return {"glyph": glyph, "color": tuple(int(c) for c in color)}


def _arrived_marker_color(settings: dict, marker_bgr: tuple) -> tuple:
    """The color a pin turns once its waypoint has been reached: the
    project's own arrived_marker_color if it set one, else a darker shade
    of its marker_color, else the stock default."""
    if settings.get("arrived_marker_color") is not None:
        return _project_color(
            settings, "arrived_marker_color", tuning.DEFAULT_ARRIVED_MARKER_COLOR
        )
    if settings.get("marker_color") is not None:
        return tuple(max(0, min(255, int(c * _ARRIVED_COLOR_DARKEN))) for c in marker_bgr)
    return tuple(tuning.DEFAULT_ARRIVED_MARKER_COLOR)


def _project_rgb(settings: dict, key: str) -> Optional[list]:
    """A project colour setting as an RGB list (pydeck's order), or None."""
    value = settings.get(key)
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return [int(c) for c in value[:3]]
    return None


# Modes drawn with the project's Route Line color, matching the editor.
# Flights keep their own accent. "direct"/"draw" alias to walking.
_LINE_COLOR_MODES = ("walking", "driving", "car", "ferry")


def _mode_line_color_overrides(settings: dict) -> dict:
    """Per-mode route-line colors as BGR: settings.line_color for every
    ordinary mode, then settings.mode_line_colors per mode on top."""
    overrides = {}
    if settings.get("line_color") is not None:
        for mode in _LINE_COLOR_MODES:
            overrides[mode] = _project_color(settings, "line_color", tuning.MODE_LINE_COLORS[mode])
    per_mode = settings.get("mode_line_colors") or {}
    if isinstance(per_mode, dict):
        for mode, value in per_mode.items():
            key = str(mode).strip().lower()
            key = tuning.MODE_ALIASES.get(key, key)
            overrides[key] = _project_color(
                {key: value}, key, tuning.MODE_LINE_COLORS.get(key, (110, 110, 110))
            )
    return overrides


_RENDER_MANIFEST_NAME = ".render_manifest.json"


def _render_checkpoint_key(
    project_config_path: str,
    cleaned_route: dict,
    audio_durations: Optional[list[float]],
    audio_pauses: Optional[list[Any]],
) -> str:
    """Fingerprint of every input that can change what render_route_video
    produces. The checkpoint below used to trust bare output-file
    existence alone: render once, then edit waypoints/settings/popups in
    job_config.json and render again, and it silently handed back the
    STALE video with nothing to say it hadn't actually re-rendered. This
    hash is stored alongside the manifest and compared on the next run so
    "the output files still exist" and "nothing that affects them has
    changed" are no longer treated as the same thing.

    Hashes job_config.json's raw bytes (the file the app writes every
    edit to — waypoints, settings, popups, colors, all of it) plus the
    route track and narration timing, since those two aren't part of
    job_config.json but still change what gets rendered (a different GPS
    source or re-recorded narration shifts the animation even if the
    config file itself is untouched).

    route_df's own "timestamp" column is normalized to seconds elapsed
    since the route's first point before hashing, rather than hashed as
    the absolute wall-clock values it comes in as. The map editor
    regenerates raw_track.gpx with fresh `<time>` tags anchored to
    whatever moment the project was last SAVED (see fileSystem.ts's
    saveProjectData, not the route itself), on every save whether the
    route actually changed or not — so the absolute timestamps drift on
    every save even for byte-identical waypoints/geometry. Hashing them
    as-is invalidated this checkpoint on every single render regardless
    of whether anything a viewer would notice had changed. The RELATIVE
    spacing between points (how long each leg took) is what actually
    affects the render and is unaffected by when the file was saved, so
    that's what gets hashed instead.
    """
    hasher = hashlib.sha256()
    try:
        with open(project_config_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        # Rewritten by every save, whether or not anything was edited.
        config_data.pop("updated_at", None)
        hasher.update(json.dumps(config_data, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    except (OSError, ValueError):
        pass
    route_df = cleaned_route.get("route")
    if route_df is not None:
        # Geometry only: the GPX times are re-stamped on every save and the CSV
        # keeps whole seconds, so times/durations shift by seconds run to run.
        hasher.update(route_df[["latitude", "longitude"]].round(7).to_json(orient="split").encode("utf-8"))
    summary = {
        k: v for k, v in cleaned_route.get("summary", {}).items()
        if "duration" not in k and "time" not in k
    }
    hasher.update(json.dumps(summary, sort_keys=True, default=str).encode("utf-8"))
    try:
        with open(meta_file(Path(project_config_path).parent, NARRATION_CUES), "rb") as f:
            hasher.update(f.read())  # cue times decide each walk's length
    except OSError:
        pass
    hasher.update(json.dumps(audio_durations or [], default=str).encode("utf-8"))
    hasher.update(json.dumps(audio_pauses or [], default=str).encode("utf-8"))
    return hasher.hexdigest()


def _short_hash(value: Any) -> str:
    raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _checkpoint_parts(
    project_config_path: str,
    cleaned_route: dict,
    audio_durations: Optional[list[float]],
    audio_pauses: Optional[list[Any]],
) -> dict:
    """Per-input hashes behind _render_checkpoint_key, so an invalidation can name what changed."""
    parts: dict = {}
    try:
        with open(project_config_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
    except (OSError, ValueError):
        config_data = {}
    # The photos the render will show (upscaled copies where they exist).
    shown = json.loads(json.dumps(config_data))
    apply_upscaled_images(shown, Path(project_config_path).parent)
    parts["route.photos"] = photo_inputs_hash(
        [[wp.get(k) for k in IMAGE_KEYS] for wp in shown.get("waypoints") or [] if isinstance(wp, dict)]
    )
    for key, value in config_data.items():
        if key == "updated_at":
            continue
        if key == "waypoints" and isinstance(value, list):
            parts["route.waypoints"] = route_inputs_hash(value)
            parts["route.overview_flags"] = overview_flags_hash(value)
            parts["config.waypoints.count"] = _short_hash(len(value))
            for i, wp in enumerate(value):
                label = wp.get("label", "") if isinstance(wp, dict) else ""
                for field, field_value in (wp.items() if isinstance(wp, dict) else [("value", wp)]):
                    parts[f"config.waypoints[{i}:{label}].{field}"] = _short_hash(field_value)
        elif key == "settings" and isinstance(value, dict):
            for field, field_value in value.items():
                parts[f"config.settings.{field}"] = _short_hash(field_value)
        else:
            parts[f"config.{key}"] = _short_hash(value)
    route_df = cleaned_route.get("route")
    if route_df is not None:
        parts["route.geometry"] = _short_hash(
            route_df[["latitude", "longitude"]].round(7).to_json(orient="split").encode("utf-8")
        )
    for key, value in cleaned_route.get("summary", {}).items():
        if "duration" not in key and "time" not in key:
            parts[f"route.summary.{key}"] = _short_hash(value)
    try:
        cues = json.loads(meta_file(Path(project_config_path).parent, NARRATION_CUES).read_text(encoding="utf-8"))
        for key, value in cues.items():
            parts[f"narration_cues.{key}"] = _short_hash(value)
    except (OSError, ValueError):
        pass
    for i, value in enumerate(audio_durations or []):
        parts[f"audio_durations[{i}]"] = _short_hash(value)
    for i, value in enumerate(audio_pauses or []):
        parts[f"audio_pauses[{i}]"] = _short_hash(value)
    return parts


# The route render is reused unless the waypoints' route inputs changed (or
# an output is missing). Not route.geometry: the app can save a different
# GPX line for the same waypoints (see route_inputs.py).
# route.photos: a new or upscaled pop-up photo has to reach the overview and legs.
ROUTE_CHECKPOINT_PARTS = ("route.waypoints", "route.overview_flags", "route.photos")


def _describe_changed_parts(old: dict, new: dict, limit: int = 25) -> str:
    changed = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
    labels = [
        f"{k} ({'added' if k not in old else 'removed' if k not in new else 'changed'})"
        for k in changed
    ]
    more = f", +{len(labels) - limit} more" if len(labels) > limit else ""
    return ", ".join(labels[:limit]) + more if labels else "nothing per-part (hash format differs)"


# Residential-leg clip filename's embedded 1-based departure-waypoint
# position (see waypoints.py's chunk_filename: "02_waypoint_{N:02d}_...") —
# used below (and by timeline_step.py's own mirrored match) to look up that
# leg's narration by the waypoint's actual RAW position instead of a blind
# per-clip counter, which stop-by leg-merging can throw out of sync (a
# merged-away stop-by means consecutive leg clips no longer correspond to
# consecutive audio_paths entries).
RESIDENTIAL_LEG_RE = re.compile(r"02_waypoint_(\d+)_")


# Fallback real-world speed (km/h) used when a leg's own mode has no
# configured speed AND there's no configured "car" speed to fall back to
# either (see mode_speed_kmh.get(mode) or mode_speed_kmh.get("car", ...)
# below).
_FALLBACK_CAR_SPEED_KMH = 70.0

_SECONDS_PER_HOUR = 3600.0

# Bounds on how many points a synthetic straight-line ferry crossing is
# sampled into when there's no cached routed polyline for that leg (see the
# "No cached route for this leg" fallback below).
_MIN_FERRY_SAMPLE_POINTS = 2
_MAX_FERRY_SAMPLE_POINTS = 120

# Overview animation pacing bounds/rates — see the "Pace the overview off
# the route itself" comment further down for the full rationale.
_OVERVIEW_MIN_DURATION_SECONDS = 24.0
_OVERVIEW_MAX_DURATION_SECONDS = 180.0
_OVERVIEW_SECONDS_PER_LEG = 8.0
_OVERVIEW_SECONDS_PER_KM = 1.5
_OVERVIEW_MIN_FINAL_DURATION_SECONDS = 10.0


def _adaptive_overview_padding(route_df: pd.DataFrame) -> float:
    """Picks the overview map's padding_factor from the route's own
    bounding-box diagonal distance (km) — see tuning.OVERVIEW_PADDING_BY_SPAN_KM.
    Falls back to the old flat 10% if the span can't be computed (e.g. a
    single-point route)."""
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

    for max_span, padding in tuning.OVERVIEW_PADDING_BY_SPAN_KM:
        if span_km <= max_span:
            return padding
    return tuning.OVERVIEW_PADDING_MAX_SPAN


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
    overview_stale = False
    if is_full_pipeline_render and not force and manifest_path.exists():
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            cached_paths = manifest.get("output_paths", [])
            cached_key = manifest.get("input_hash")
            cached_parts = manifest.get("input_parts")
        except (OSError, json.JSONDecodeError):
            cached_paths, cached_key, cached_parts = [], None, None
        # Only the route itself (or a missing output) invalidates the render;
        # other input changes are logged and ignored.
        if cached_parts:
            # A manifest from before route.waypoints existed falls back to the line itself.
            keys = ROUTE_CHECKPOINT_PARTS if "route.waypoints" in cached_parts else ("route.geometry",)
            old_parts = dict(cached_parts)
            # Rendered before the pause toggle was read: every stop paused then.
            try:
                with open(project_config_path, "r", encoding="utf-8") as _f:
                    _wp_count = len(json.load(_f).get("waypoints", []))
            except (OSError, json.JSONDecodeError):
                _wp_count = 0
            old_parts.setdefault(
                "route.overview_flags",
                overview_flags_hash([{}] * _wp_count),
            )
            route_changed = [k for k in keys if old_parts.get(k) != checkpoint_parts.get(k)]
        else:
            route_changed = [] if cached_key == checkpoint_key else ["(no per-input record)"]
        outputs_ok = bool(cached_paths) and all(output_is_valid(p) for p in cached_paths)
        if outputs_ok and not route_changed:
            ignored = (
                _describe_changed_parts(cached_parts, checkpoint_parts)
                if cached_parts and cached_key != checkpoint_key else ""
            )
            logger.info(
                "Step 4: route unchanged and all %d output(s) exist — skipping render.%s",
                len(cached_paths), f" Ignored changes: {ignored}" if ignored else "",
            )
            return cached_paths
        if cached_paths and route_changed:
            logger.info(
                "Step 4: route changed since the last render (%s) — re-rendering.",
                ", ".join(route_changed),
            )
            # The overview also skips itself when its file exists; its script,
            # cues and stops may be what changed, so it must be rendered again.
            # The old file is NOT deleted: the new render is written aside and
            # only replaces it once it is complete, so an interrupted run
            # never leaves the project without an overview.
            overview_stale = True
        elif cached_paths:
            missing = [p for p in cached_paths if not output_is_valid(p)]
            logger.info(
                "Step 4: route unchanged but %d output(s) missing/invalid — rendering those: %s",
                len(missing), ", ".join(Path(p).name for p in missing[:10]),
            )

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
    if waypoints:
        logger.info("Step 4: Injecting %d custom waypoints.", len(waypoints))
        start_label = project_config.get("start_point", {}).get("label")
        end_label = project_config.get("end_point", {}).get("label")
        text_labels = video_text.current_labels()

        for idx, wp in enumerate(waypoints):
            route_point_idx = wp_indices[idx]
            raw_label = wp.get("label", text_labels["waypoint_fallback"])

            if idx == 0 and start_label:
                raw_label = start_label
            elif idx == len(waypoints) - 1 and end_label:
                raw_label = end_label

            formatted = format_waypoint_label(raw_label, subtitle_lang)
            prefix = (
                text_labels["start_prefix"] if idx == 0
                else text_labels["stop_prefix"] if idx == len(waypoints) - 1
                else ""
            )
            route_labels[route_point_idx] = (
                f"{prefix}{formatted}" if formatted else prefix.strip(": ")
            )

            popup_img = wp.get("popup_image")
            wp_skipped = bool(wp.get("skipAssetGeneration")) and 0 < idx < len(waypoints) - 1
            # This waypoint's own real narration TTS length (audio_step.py's
            # audio_durations, 1:1 aligned with THIS SAME
            # `enumerate(waypoints)`). Stashed on the waypoint dict ITSELF
            # (mutated in place, not just into route_popups below) so it
            # rides along for free wherever this exact dict object gets
            # reused/copied downstream -- notably `res_waypoints = list(
            # waypoints)` further down, whose entries mapfetcher.py's
            # process_residential_sequence reads directly to build each
            # residential leg's own mid_markers/landmarks, a completely
            # separate code path from route_popups. Residential's
            # fullscreen popup uses this to make sure its hold never cuts
            # away before the narration muxed onto that same clip has
            # actually finished playing -- "freeze_seconds" below is only
            # ever a short user-set/capped fallback for when there's no
            # narration at all. See pedestrian.py's `_min_hold_seconds`.
            wp["_narration_audio_seconds"] = (
                float(audio_durations[idx])
                if idx < len(audio_durations) and audio_durations[idx]
                else None
            )
            route_popups[route_point_idx] = {
                "freeze_seconds": min(
                    float(wp.get("freeze_seconds", 3.0)), tuning.POPUP_FREEZE_SECONDS_MAX
                ),
                "audio_duration": wp["_narration_audio_seconds"],
                # A waypoint's own "popup_image" field can hold several
                # photos (the map editor's multi-image field) -- the
                # overview animation shows the FIRST one (its own long-
                # standing behavior; this dict is shared with the overview
                # path below, not residential-only), same as ever.
                "popup_image": (
                    str(popup_img[0])
                    if isinstance(popup_img, list) and popup_img
                    else (str(popup_img) if popup_img else None)
                ),
                # Residential-only variant: the LAST image, used for the
                # leg's own fullscreen-to-card destination-photo intro (see
                # route2vdo.py's _render_residential_pydeck and
                # pydeckrecorder.pedestrian's `dest_popup_image` docstring)
                # -- kept separate from "popup_image" above so the overview
                # animation, which reads that same key, is unaffected.
                "popup_image_last": (
                    str(popup_img[-1])
                    if isinstance(popup_img, list) and popup_img
                    else (str(popup_img) if popup_img else None)
                ),
                "image_display": str(
                    wp.get("image_display", "cover")
                ).lower(),
                "triggered": False,
                # Matches the map editor's own MapArea.tsx: a stop-by
                # waypoint always renders as pinType="stopby" (dark brown, a
                # "・" dot instead of a number) and is skipped entirely by
                # the OTHER waypoints' sequential numbering — see
                # spatial_renderer/pins.py's _draw_pin/_pin_color.
                # A waypoint skipped in video export is drawn and numbered like
                # a stop-by, but only pops up as the walker passes (is_skipped:
                # never batched, never stopped at - see popups.py).
                "is_stopby": bool(wp.get("isStopBy", False) or wp_skipped),
                "is_skipped": wp_skipped,
                # The editor's "Pause at Location" (default on): off, the
                # overview walker doesn't stop here for the description.
                "pause_at_waypoint": wp.get("pauseAtWaypoint") is not False,
                # The map editor's stop-by-only "Connect to Route" toggle
                # (see src/components/ui/ContextMenu.tsx). A CONNECTED
                # stop-by is one the route actually runs through — the
                # frontend's own routing already includes it in the route
                # geometry for exactly that reason — so the renderer
                # treats it as an ordinary stop that merely LOOKS
                # different (its own arrival, its own popup where it
                # sits, still drawn as a "・" dot and still skipped by the
                # numbering). An unconnected one is a landmark the
                # traveler never actually goes to, and is shown as part
                # of the previous normal waypoint's stop instead — see
                # overview.py's _attach_stopby_groups.
                "connect_to_route": bool(wp.get("connectToRoute", False) and not wp_skipped),
                # This waypoint's own true GPS coordinates — separate from
                # route_points[c_idx] (the nearest point on the RECORDED
                # TRACK, used for x/y). A stop-by that's only observed from
                # a distance rather than actually walked to (a small
                # offshore island seen from the trail, say) can sit well
                # off the track; overview.py re-projects that kind of pin
                # to its own lat/lng instead of snapping it onto the
                # nearest track pixel, which used to draw it right on top
                # of the route line despite the real place being nowhere
                # near it.
                "lat": wp.get("lat"),
                "lng": wp.get("lng", wp.get("lon")),
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
        logger.info("Step 4: Generating residential leg sequence (lat/lon per leg)...")
        # Stop-by leg-merging is toggleable per project (default: merge —
        # see tuning.DEFAULT_MERGE_STOPBY_WAYPOINTS); multi-tile chunk
        # splitting is deliberately kept off here (math.inf) even though
        # process_residential_sequence now supports it — enabling it would
        # also require reworking the audio-mux/timeline position lookups
        # below to handle several clips sharing one leg's narration, which
        # is real follow-up work, not something to fold in silently here.
        # job_config's own "waypoints" array excludes the trip's TRUE
        # start/end (those live in separate "start_point"/"end_point"
        # keys) — passing it to process_residential_sequence unmodified
        # meant the residential leg sequence's very first/last leg began/
        # ended at the first/last WAYPOINT instead of the true start/end,
        # so that point never got its own leg, intro pin, or "S"/"E"
        # popup treatment in the residential video (only the separate
        # overview pipeline ever showed it). Prepending/appending them
        # here — as a LOCAL list used only for this call, not reassigning
        # the shared `waypoints`/`wp_indices` — closes that gap without
        # touching audio_durations/seg_durations/route_labels indexing
        # elsewhere in this function, all of which are sized and indexed
        # against the ORIGINAL waypoints list and would desync by one
        # position if it shifted. Skipped when the true start/end already
        # coincides with row 0 / the last row (nothing to add). Neither
        # start_point nor end_point carries its own "popup_image" field
        # in job_config's schema — only "waypoints" entries do — so this
        # gives the true start/end a real leg + pin + "S"/"E" label, but
        # not a photo unless a future schema change adds one.
        _start_pt = project_config.get("start_point") or {}
        _end_pt = project_config.get("end_point") or {}
        res_waypoints = list(waypoints)
        res_wp_indices = list(wp_indices)
        if _start_pt.get("lat") is not None and (not res_wp_indices or res_wp_indices[0] != 0):
            res_waypoints = [{
                "lat": _start_pt["lat"],
                "lng": _start_pt.get("lng", _start_pt.get("lon")),
                "label": _start_pt.get("label"),
                "isStopBy": False,
            }] + res_waypoints
            res_wp_indices = [0] + res_wp_indices
        if _end_pt.get("lat") is not None and (
            not res_wp_indices or res_wp_indices[-1] != len(route_df) - 1
        ):
            res_waypoints = res_waypoints + [{
                "lat": _end_pt["lat"],
                "lng": _end_pt.get("lng", _end_pt.get("lon")),
                "label": _end_pt.get("label"),
                "isStopBy": False,
            }]
            res_wp_indices = res_wp_indices + [len(route_df) - 1]

        sequence_data = fetcher.process_residential_sequence(
            route_df,
            res_waypoints,
            output_size=(img_w, img_h),
            max_chunk_distance_meters=math.inf,
            precomputed_indices=res_wp_indices,
            merge_stopbys=bool(
                settings.get("merge_stopby_waypoints", tuning.DEFAULT_MERGE_STOPBY_WAYPOINTS)
            ),
            # Filtered HERE (not just on the returned res_sequence below) so
            # a single-leg test run (main.py ... residential <leg_index>)
            # skips every other leg's map tile fetch entirely instead of
            # fetching all of them and discarding everything but one.
            leg_index=leg_index,
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
        # Each leg's two pins show the overview's own glyphs (S, 1, 2 ... E).
        # Counted over res_waypoints, which carries a separate start_point/
        # end_point when the project has one, exactly as the overview does.
        _glyph_by_pos = overview_pin_glyphs(res_waypoints)
        glyph_by_id = {
            wp.get("id"): _glyph_by_pos[pos]
            for pos, wp in enumerate(res_waypoints) if wp.get("id")
        }

        for seq_idx, leg_item in enumerate(sequence_data):
            start_idx, end_idx = leg_item["start_idx"], leg_item["end_idx"]
            chunk = route_df.iloc[start_idx : end_idx + 1]

            # This leg's departure/arrival RAW positions in `waypoints` —
            # resolved by id (see id_to_position above), not by `seq_idx`,
            # since a merged-away stop-by can make them diverge. Falls back
            # to the old positional guess only if a waypoint is missing its
            # "id" field (older data saved before ids were assigned).
            start_pos = id_to_position.get(leg_item.get("start_waypoint_id"))
            if start_pos is None:
                start_pos = seq_idx
            end_pos = id_to_position.get(leg_item.get("end_waypoint_id"))
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
                    ferry_count = max(
                        _MIN_FERRY_SAMPLE_POINTS,
                        min(_MAX_FERRY_SAMPLE_POINTS, end_idx - start_idx + 1),
                    )
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
                    Path(leg_item["img_path"]).with_name(f"res_map_ferry_{seq_idx + 1}.png")
                )
                leg_item["img_path"] = ferry_map_path
                leg_item["extent"] = fetcher.downloader.fetch_residential_chunk(
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
            distance_fallback = sum(
                seg_durations[p] for p in range(start_pos, end_pos) if p < len(seg_durations)
            ) or 10.0
            # Audio first: the narration that plays over each walk is its
            # DESTINATION's (leg_pieces.py), so its length decides how long the
            # walk is (see narration_step.leg_walk_plan): the walker may arrive
            # early (waiting there, at most max_early_arrival_seconds) but never
            # late. A leg cut at connected stop-bys is planned piece by piece,
            # each toward its own stop.
            use_cues = bool(settings.get("use_narration_cues", True))
            max_wait = float(settings.get("max_early_arrival_seconds", MAX_EARLY_ARRIVAL_SECONDS))
            stop_positions = [
                p for p in range(start_pos + 1, min(end_pos, len(waypoints)))
                if waypoints[p].get("connectToRoute") and waypoints[p].get("isStopBy")
                and waypoints[p].get("popup_image") and not waypoints[p].get("skipAssetGeneration")
            ]
            piece_targets = stop_positions + [end_pos]
            piece_plans: dict = {}
            piece_log = []
            previous = start_pos
            for target in piece_targets:
                is_first_piece = previous == start_pos
                natural = sum(
                    seg_durations[p] for p in range(previous, target) if p < len(seg_durations)
                ) or 10.0
                audio_seconds = audio_durations[target] if target < len(audio_durations) else 0.0
                piece_plans[target] = (
                    leg_walk_plan(
                        cue_store, waypoints[target], target, audio_seconds,
                        natural_seconds=natural, use_cues=use_cues, max_wait_seconds=max_wait,
                        ignore_start=not is_first_piece,
                    )
                    if target < len(waypoints) else None
                )
                if piece_plans[target] is not None:
                    walk, _, wait = piece_plans[target]
                    piece_log.append(
                        f"-> {waypoints[target].get('label')}: walk {walk:.1f}s "
                        f"({walk / natural:.2f}x natural pace), waits {wait:.1f}s"
                    )
                previous = target
            if end_pos >= len(waypoints) or any(v is None for v in piece_plans.values()):
                piece_plans = {}
            if piece_plans:
                total_time = sum(v[0] for v in piece_plans.values())
                start_cue_seconds = piece_plans[piece_targets[0]][1]  # the first piece opens the leg
                arrival_wait_seconds = piece_plans[end_pos][2]
                marker_plans = {
                    waypoints[p].get("id"): {"walk_seconds": piece_plans[p][0], "wait_seconds": piece_plans[p][2]}
                    for p in stop_positions
                }
                logger.info(
                    "Step 4: leg %d->%d follows its narration: %s.",
                    start_pos + 1, end_pos + 1, "; ".join(piece_log),
                )
            else:
                total_time = distance_fallback
                start_cue_seconds = None
                arrival_wait_seconds = None
                marker_plans = {}

            lats_arr, lons_arr = leg_item["lats"], leg_item["lons"]
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

            raw_img = leg_item.get("img_path")
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
                    "extent": leg_item["extent"],
                    "lats": lats_arr,
                    "lons": lons_arr,
                    "points": _project_route_to_pixels(
                        chunk["latitude"].to_numpy(),
                        chunk["longitude"].to_numpy(),
                        leg_item["extent"],
                        img_w,
                        img_h,
                    ),
                    "labels": route_labels[start_idx : end_idx + 1],
                    # A residential clip starts at the previous waypoint,
                    # so only the destination popup may end its route
                    # animation. Including the start popup makes the renderer
                    # terminate on the first frame of every leg.
                    "popups": leg_popups,
                    # Every leg's own departure waypoint's popup -- shown at
                    # this leg's OPENING (shrink), independent of whichever
                    # PREVIOUS leg's arrival preview (grow, at actual
                    # arrival) already showed the same waypoint's photo once
                    # -- each leg gets its own self-contained departure +
                    # arrival pair rather than relying on the previous leg's
                    # ending to cover this one's beginning.
                    "leg_start_popup": route_popups[start_idx],
                    # Symmetric case at the other end: when a trailing
                    # synthetic end_point leg is appended past the last REAL
                    # waypoint (see this function's own start/end-point
                    # padding above), THAT leg's own destination is the
                    # synthetic end_point -- which, like start_point, has no
                    # "popup_image" field in job_config's schema, so its
                    # normal dest popup (leg_popups[-1] above) comes back
                    # empty and the video's truly final clip would arrive on
                    # no photo at all. route2vdo.py falls back to this (the
                    # last REAL waypoint's own popup) only when the leg's
                    # normal dest popup is empty, so the common case (no
                    # trailing synthetic leg, the last real waypoint IS the
                    # final destination) is unaffected -- this would just be
                    # a duplicate of what leg_popups[-1] already has.
                    "trip_end_popup": (
                        route_popups[end_idx] if end_pos == len(waypoints) - 1 else None
                    ),
                    "mode": leg_mode,
                    "line_color": (
                        leg_line_color_rgb(waypoints[start_pos])
                        if start_pos < len(waypoints)
                        else None
                    )
                    or _project_rgb(settings, "line_color"),
                    "travel_duration": total_time,
                    "segment_duration": total_time,
                    "start_cue_seconds": start_cue_seconds,
                    # Arrived early: hold on the arrived map until the voice is
                    # done, then the fullscreen photo transition.
                    "arrival_wait_seconds": arrival_wait_seconds,
                    "start_pin": _leg_pin(
                        glyph_by_id.get(leg_item.get("start_waypoint_id"))
                        or ("S" if seq_idx == 0 else None),
                        settings, arrived=True,
                    ),
                    "dest_pin": _leg_pin(
                        glyph_by_id.get(leg_item.get("end_waypoint_id"))
                        or ("E" if seq_idx == len(sequence_data) - 1 else None),
                        settings, arrived=False,
                    ),
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
                    # The leg's checkpoint key (route2vdo): its waypoints' route inputs.
                    "route_inputs": route_inputs_hash(waypoints[start_pos:end_pos + 1]),
                    # Which waypoints this leg runs between: route2vdo writes
                    # the destination into the leg's _pieces.json so
                    # leg_pieces.py plays the DESTINATION's narration over the
                    # walk toward it.
                    "start_waypoint_id": leg_item.get("start_waypoint_id"),
                    "end_waypoint_id": leg_item.get("end_waypoint_id"),
                    "wide_img_path": leg_item.get("wide_img_path"),
                    "wide_extent": leg_item.get("wide_extent"),
                    # "pos_in_chunk" (0-based index into this leg's own
                    # `points`/res_points list, not the route_df row index)
                    # is what waypoints.py actually needs to know when the
                    # traveler has passed a merged-in stop-by along the way.
                    "mid_markers": [
                        {
                            **m,
                            "pos_in_chunk": m["row_idx"] - start_idx,
                            **marker_plans.get(m.get("waypoint_id"), {}),
                        }
                        for m in leg_item.get("mid_markers", [])
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

    animator_config = {
        "output_dir": output_video_dir,
        # Gates the per-leg/per-clip "file already exists, skip it" checks
        # in overview.py/route2vdo.py/waypoints.py — only a real
        # run_full_pipeline render (render_mode == "both") should ever
        # resume from partial output like this. A standalone
        # render_mode="overview"/"residential" call (services/cli/
        # gps_commands.py's test_overview_video/test_residential_video —
        # the map editor's own "recreate this video" actions) exists
        # specifically so a user can force ONE piece to redo; honoring
        # leftover files from a previous run there would silently no-op
        # the very action they asked for, exactly the bug this function's
        # own manifest checkpoint above already had to be fixed for.
        # --force redoes every clip, so no per-file "already exists" skipping either.
        "checkpoint_enabled": is_full_pipeline_render and not force,
        # Inputs changed since the last render: the existing overview is stale.
        "overview_rerender": overview_stale,
        "min_free_ram_gb": settings.get("min_free_ram_gb"),
        "enable_attraction_videos": attraction_videos_enabled(settings),
        # The at-arrival photo grows to fullscreen and the clip ends right
        # there - no hold. The dissolve into the attraction video that follows
        # runs on extra frames added at export (VideoExporter._crossfade_pair),
        # so it starts the moment the photo is fullscreen.
        "arrival_photo_hold_seconds": 0.0,
        # A connected stop-by's fullscreen photo does the same (no hold, no
        # blur-out) when an attraction video follows it.
        "dissolve_into_attraction": (
            attraction_videos_enabled(settings)
            and float(settings.get("attraction_fade_seconds", 0.8)) > 0
        ),
        "use_3d_res": use_3d_res,
        "use_pydeck_pedestrian": use_pydeck_pedestrian,
        "use_pydeck_overview": bool(settings.get("use_pydeck_overview", tuning.DEFAULT_USE_PYDECK_OVERVIEW)),
        # Where the narration's cues fall: the overview reaches each cued stop
        # then (spatial_renderer/overview.py).
        "overview_cue_seconds": dict(overview_cue_times or {}),
        # The narration's length: with cues, the overview's ending is fitted
        # so the video ends with the voice.
        "overview_audio_seconds": float(overview_audio_duration or 0.0),
        # A cue at the start of a sentence: the voice starts talking about that
        # stop at the cue, so the walker waits there a moment (this many seconds)
        # to stay in step with it.
        "overview_cue_wait_tags": tags_at_sentence_start(
            overview_tagged_script(project_config, config_path.parent)
        ),
        "overview_cue_wait_seconds": float(settings.get("overview_cue_wait_seconds", 2.0)),
        "res_route_path": project_config_path,
        "leg_durations": seg_durations or None,
        "duration": settings.get("duration", overview_duration),
        **{
            k: settings.get(k, default)
            for k, default in [
                ("fps", 30),
                ("line_thickness", 10),
                ("marker_radius", 16),
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
                ("default_transition_hold_seconds", 1.5),
                ("hide_route_on_popup", False),
                ("enable_fullscreen_popups", True),
                ("hide_upcoming_pins_on_popup", False),
            ]
        },
        # Colors: authored RGB in job_config.json, drawn BGR — see
        # _project_color. The defaults passed here are already BGR.
        "line_color": _project_color(settings, "line_color", (243, 150, 33)),
        "mode_line_colors": _mode_line_color_overrides(settings),
        "marker_color": marker_color_bgr,
        "arrived_marker_color": _arrived_marker_color(settings, marker_color_bgr),
        "card_border_color": _project_color(
            settings, "card_border_color", tuning.DEFAULT_CARD_BORDER_COLOR
        ),
        "route_line_border_color": _project_color(
            settings, "route_line_border_color", tuning.DEFAULT_LINE_BORDER_COLOR
        ),
        # Pin colors by role. Unset keys fall through to the defaults on
        # SpatialRendererBase (start/end/drawn/stop-by) — a project only
        # needs to name the ones it actually wants to change.
        "start_pin_color": _project_color(settings, "start_pin_color", tuning.START_PIN_COLOR),
        "end_pin_color": _project_color(settings, "end_pin_color", tuning.END_PIN_COLOR),
        "drawn_pin_color": _project_color(settings, "drawn_pin_color", tuning.DRAWN_PIN_COLOR),
        "stopby_pin_color": _project_color(settings, "stopby_pin_color", tuning.STOPBY_PIN_COLOR),
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
        # HUD/card theme: settings.theme or top-level theme ("light"/"dark").
        "theme": tuning.resolve_ui_theme(project_config),
        # Legs keep their path above a band sized to the project's caption.
        "caption_style": settings.get("caption_style"),
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
