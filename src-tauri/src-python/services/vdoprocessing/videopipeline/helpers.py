"""Shared constants and small pure helpers used across the pipeline steps."""

import os
from pathlib import Path
from typing import Optional

import numpy as np
import pyproj

from services.logger.logger import setup_logger
from services import tuning

# Standardized logger — writes to logs/app.log AND stderr, matching
# every other service module in this codebase.
logger = setup_logger("VideoPipeline")

# Re-exported so existing `from .helpers import PIPELINE_LABELS` call sites
# don't need to know it actually lives in tuning.py — it's defined there
# (not here) because spatial_renderer/overview.py also needs it and can't
# import this videopipeline package without a circular import
# (videopipeline/__init__.py eagerly imports render_step.py, which imports
# spatial_renderer).
PIPELINE_LABELS = tuning.PIPELINE_LABELS

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_FRONTEND_CONFIG = (
    BASE_DIR
    / "data"
    / "inputs"
    / "gpsdata"
    / "processdata"
    / "json"
    / "example_frontend.json"
)
DEFAULT_MAP_BACKGROUND = (
    BASE_DIR / "data" / "inputs" / "fullmap_image" / "map_background.png"
)

_WGS84_TO_WEBMERCATOR = pyproj.Transformer.from_crs(
    "EPSG:4326", "EPSG:3857", always_xy=True
)


def clear_console():
    os.system("cls" if os.name == "nt" else "clear")


def output_is_valid(path, min_bytes: int = 1024) -> bool:
    """Checkpoint helper: True only if `path` exists and is above
    `min_bytes` — guards against treating a zero-byte/truncated file left
    behind by a killed process as a finished, skippable output."""
    try:
        p = Path(path)
        return p.is_file() and p.stat().st_size >= min_bytes
    except OSError:
        return False


def safe_label(label, fallback: str) -> str:
    """The one canonical filename-safe label sanitizer, shared by every
    domain (TTS, attraction, subtitles) — strips to alnum/space/underscore/
    hyphen, then replaces spaces with underscores. Previously reimplemented
    independently as services/cli/helpers.py's _video_safe_label,
    audio_step.py's _safe_audio_label, and (looser, punctuation-preserving)
    inline in attraction_step.py — those three could disagree on the same
    label, silently desyncing filenames across domains."""
    cleaned = "".join(
        char for char in str(label) if char.isalnum() or char in (" ", "_", "-")
    ).strip().replace(" ", "_")
    return cleaned or fallback


def waypoint_audio_filename(idx: int, label) -> str:
    """Canonical TTS audio filename for waypoint `idx` (0-based)."""
    return f"02_waypoint_{idx + 1:02d}_{safe_label(label, f'leg{idx + 1}')}.wav"


def attraction_output_filename(idx: int, label) -> str:
    """Canonical attraction-video filename for waypoint `idx` (0-based).
    timeline_step.py's _ATTRACTION_RE depends on this exact format."""
    return f"04_attraction_{idx:02d}_{safe_label(label, f'waypoint_{idx}')}.mp4"


def attraction_audio_filename(idx: int, label) -> str:
    """Canonical TTS audio filename for waypoint `idx`'s ATTRACTION-only
    narration (0-based) — deliberately its own "04_attraction_" namespace,
    distinct from waypoint_audio_filename's "02_waypoint_" arrival+
    attraction COMBINED audio. The attraction clip must only ever play its
    own attractionNarration text (or nothing, when that field is blank),
    never the arrival narration that combined audio also carries."""
    return f"04_attraction_{idx:02d}_{safe_label(label, f'waypoint_{idx}')}.wav"


# Every generated output (audio, video, subtitles) lives grouped under the
# project's assets/ folder, alongside the raw input assets (popup images)
# that already live there — e.g. <project>/assets/audio, not
# <project>/audio. Centralized here so every step/CLI command agrees on the
# same layout instead of each independently joining "audio"/"video"/
# "subtitles" onto a project directory.
def project_audio_dir(project_dir) -> Path:
    return Path(project_dir) / "assets" / "audio"


def project_video_dir(project_dir) -> Path:
    return Path(project_dir) / "assets" / "video"


# Route outputs (overview map, residential leg clips, the render manifest)
# and attraction outputs (ComfyUI/Wan2.2 image-to-video clips) used to share
# one flat assets/video/ folder, which made it hard to tell the two domains'
# files apart at a glance. Split into their own subfolders; intro/outro and
# the final subtitled/concatenated videos still live directly under
# project_video_dir since they aren't specific to either domain.
def project_route_video_dir(project_dir) -> Path:
    return project_video_dir(project_dir) / "route"


def project_attraction_video_dir(project_dir) -> Path:
    return project_video_dir(project_dir) / "attraction"


def project_subtitle_dir(project_dir) -> Path:
    return Path(project_dir) / "assets" / "subtitles"


def _project_route_to_pixels(
    lats,
    lons,
    extent: tuple[float, float, float, float],
    img_width_px: int,
    img_height_px: int,
) -> list[list[float]]:
    """Helper to convert GPS coordinates to pixel space on the map."""
    # [NOTE] [Map] extent is (west, east, south, north) in Web Mercator meters — unpack order must match contextily's own extent convention or pixels land mirrored/flipped.
    w, e, s, n = extent
    merc_x, merc_y = _WGS84_TO_WEBMERCATOR.transform(lons, lats)
    px = (np.asarray(merc_x) - w) / (e - w) * img_width_px
    py = (n - np.asarray(merc_y)) / (n - s) * img_height_px
    return [[float(x), float(y)] for x, y in zip(px, py)]


def _find_leg_cache_key(
    from_wp: dict, to_wp: dict, routing_cache: dict
) -> Optional[str]:
    """Finds the .routecache.json entry for the leg from_wp -> to_wp, by
    nearest-coordinate match on the key's own start/end points (tolerant of
    the key's 5-decimal rounding). Shared by the mode and geometry lookups
    below so both agree on exactly the same cache entry for a given leg.

    A key is "lat,lng|lat,lng|mode|customHash" — FOUR fields, the last one
    a hand-drawn leg's own geometry hash (empty for every other mode). See
    the frontend's own key builders (src/services/fileSystem.ts and
    src/features/map/hooks/useMapRouting.tsx), which have always written
    that trailing field. Unpacking exactly three fields here (as this did)
    raised ValueError on EVERY key and skipped it, so the whole route
    cache silently resolved to nothing: no leg ever got its cached mode,
    and _resolve_leg_geometry_from_cache never returned a routed polyline
    either, leaving hand-drawn legs to fall back to the raw GPS track."""
    if not routing_cache:
        return None
    from_lat, from_lng = from_wp.get("lat"), from_wp.get("lng", from_wp.get("lon"))
    to_lat, to_lng = to_wp.get("lat"), to_wp.get("lng", to_wp.get("lon"))
    if from_lat is None or to_lat is None:
        return None

    best_key, best_dist = None, float("inf")
    for route_key in routing_cache:
        parts = route_key.split("|")
        if len(parts) < 3:
            continue
        try:
            s_lat, s_lng = (float(v) for v in parts[0].split(","))
            e_lat, e_lng = (float(v) for v in parts[1].split(","))
        except ValueError:
            continue
        dist = (
            (s_lat - from_lat) ** 2 + (s_lng - from_lng) ** 2
            + (e_lat - to_lat) ** 2 + (e_lng - to_lng) ** 2
        )
        if dist < best_dist:
            best_dist, best_key = dist, route_key

    # [NOTE] [Util] ~0.0005 in summed-squared-degrees is well under a city block — reject anything looser so an unrelated cache entry never gets matched.
    if best_key is None or best_dist > 0.0005:
        return None
    return best_key


def _resolve_leg_mode_from_cache(
    from_wp: dict, to_wp: dict, routing_cache: dict
) -> Optional[str]:
    """Returns the leg's mode ("walking"/"ferry"/...) from its
    .routecache.json entry — the mode a project that no longer records
    `routeMode` on its waypoints falls back to (see _build_point_modes,
    where an explicit routeMode wins).

    The mode is the key's THIRD field, not its last: a key ends with a
    hand-drawn leg's geometry hash ("...|draw|[[34.27,135.06],...]"), so
    reading the last field (as this did) returned that hash — or, for
    every other mode, the empty string it ends with."""
    best_key = _find_leg_cache_key(from_wp, to_wp, routing_cache)
    if best_key is None:
        return None
    parts = best_key.split("|")
    if len(parts) < 3:
        return None
    return parts[2].strip().lower() or None


def _resolve_leg_geometry_from_cache(
    from_wp: dict, to_wp: dict, routing_cache: dict
) -> Optional[list[list[float]]]:
    """Returns the leg's actual routed polyline (a list of [lat, lon] pairs,
    ordered from_wp -> to_wp) from its .routecache.json entry, or None if no
    matching entry exists. This is the same path the map UI itself draws
    (see src/utils/mapUtils.ts's routeCache), as opposed to route_df's own
    GPS track, which for some travel modes (e.g. a ferry crossing) may not
    reflect the real route at all."""
    best_key = _find_leg_cache_key(from_wp, to_wp, routing_cache)
    if best_key is None:
        return None
    geometry = routing_cache.get(best_key)
    if not isinstance(geometry, list) or len(geometry) < 2:
        return None
    return geometry


def _build_point_modes(
    num_points: int,
    wp_indices: list[int],
    waypoints: list[dict],
    routing_cache: Optional[dict] = None,
) -> list[str]:
    """Assigns a travel mode ("walking"/"ferry"/"airplane"/...) to every
    route point. Each leg's mode comes from the DEPARTING waypoint's own
    `routeMode` field, falling back to that leg's `routing_cache` entry
    (.routecache.json, keyed "lat,lon|lat,lon|mode|customHash" by the
    departing waypoint — matches the frontend's own routing/cache-pruning
    convention) for projects that don't record routeMode. The mode carries
    forward past the last waypoint for the final leg to the destination.

    routeMode wins because it is the field a project is actually edited
    through: the cache records what a leg was last ROUTED with, so a leg
    whose mode was changed without re-routing (a ferry crossing the
    router has no water route for, say) would otherwise keep reporting
    the stale mode its geometry happened to be computed with."""
    modes = ["walking"] * num_points
    if num_points == 0:
        return modes

    # "direct" (a straight-line routing choice) and "draw" (a hand-drawn
    # custom-route leg) both render/report as walking rather than getting
    # their own distinct identity — see tuning.MODE_ALIASES.
    mode_aliases = tuning.MODE_ALIASES

    boundaries = list(wp_indices) + [num_points - 1]
    prev_end = 0
    current_mode = "walking"
    for leg_idx, end_idx in enumerate(boundaries):
        # [NOTE] [Animation] boundaries[leg_idx] is where waypoint `leg_idx` sits; the leg ending there departs from waypoint `leg_idx - 1`. leg_idx == 0 has no real leg before it, and leg_idx == len(waypoints) is the trailing stretch past the last waypoint — both just keep whatever current_mode already is.
        if 0 < leg_idx < len(waypoints):
            from_wp, to_wp = waypoints[leg_idx - 1], waypoints[leg_idx]
            leg_mode = from_wp.get("routeMode")
            if not leg_mode:
                leg_mode = _resolve_leg_mode_from_cache(from_wp, to_wp, routing_cache)
            if leg_mode:
                leg_mode = str(leg_mode).lower()
                current_mode = mode_aliases.get(leg_mode, leg_mode)
        for i in range(prev_end, min(end_idx + 1, num_points)):
            modes[i] = current_mode
        prev_end = end_idx + 1
    return modes
