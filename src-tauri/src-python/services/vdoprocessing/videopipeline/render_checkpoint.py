"""Step 4's render manifest: the hash of everything the route render is made from, per input, so a rerun
only renders again when the route itself changed."""

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from services.projectfiles import NARRATION_CUES, meta_file
from services.mapfetcher.maplanguage import map_style_inputs
from services.vdoprocessing.route_inputs import labels_hash, overview_flags_hash, photo_inputs_hash, route_inputs_hash
from services.config.upscaled_images import IMAGE_KEYS, apply_upscaled_images
from services.mapfetcher.graphicengine.pinimage import marker_inputs_hash

from .helpers import logger, output_is_valid

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
    # Map labels and on-screen text follow this; a project saved before it was written has none.
    language = config_data.get("map_language")
    if language:
        parts["route.map_language"] = _short_hash(str(language))
    style_part = map_style_inputs(config_data.get("settings"))
    if style_part:
        parts["route.map_style"] = _short_hash(style_part)
    marker_part = marker_inputs_hash(shown, str(Path(project_config_path).parent))
    if marker_part:
        parts["route.markers"] = marker_part
    for key, value in config_data.items():
        if key == "updated_at":
            continue
        if key == "waypoints" and isinstance(value, list):
            parts["route.waypoints"] = route_inputs_hash(value)
            parts["route.overview_flags"] = overview_flags_hash(value)
            parts["route.labels"] = labels_hash(value)
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
# route.markers: a new pin picture too (absent, so unchanged, for a project with none).
# route.map_style: the video's map style or tile sharpness (absent, so unchanged, until a project sets one).
# route.overview_voice: the overview's cue times and voice length (set by render_route_video).
# route.map_language: the label/on-screen text language (absent for a config that never had one).
ROUTE_CHECKPOINT_PARTS = (
    "route.waypoints", "route.overview_flags", "route.photos", "route.markers", "route.map_style",
    "route.overview_voice", "route.map_language", "route.labels",
)


def _describe_changed_parts(old: dict, new: dict, limit: int = 25) -> str:
    changed = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
    labels = [
        f"{k} ({'added' if k not in old else 'removed' if k not in new else 'changed'})"
        for k in changed
    ]
    more = f", +{len(labels) - limit} more" if len(labels) > limit else ""
    return ", ".join(labels[:limit]) + more if labels else "nothing per-part (hash format differs)"


def reuse_render_manifest(manifest_path, checkpoint_key, checkpoint_parts, project_config_path):
    """(the manifest's paths when the route is unchanged and every output exists, else None; whether the
    overview must be rendered again because the route changed)."""
    overview_stale = False
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
        # Recorded before stop names were checked: taken as unchanged, so no project re-renders for it.
        old_parts.setdefault("route.labels", checkpoint_parts.get("route.labels"))
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
        return cached_paths, False
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
    return None, overview_stale
