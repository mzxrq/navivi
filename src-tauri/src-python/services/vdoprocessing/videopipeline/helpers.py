"""Shared constants and small pure helpers used across the pipeline steps."""

import os
from pathlib import Path
from typing import Optional

import numpy as np
import pyproj

from services.logger.logger import setup_logger

# Standardized logger — writes to logs/app.log AND stderr, matching
# every other service module in this codebase.
logger = setup_logger("VideoPipeline")

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
    below so both agree on exactly the same cache entry for a given leg."""
    if not routing_cache:
        return None
    from_lat, from_lng = from_wp.get("lat"), from_wp.get("lng", from_wp.get("lon"))
    to_lat, to_lng = to_wp.get("lat"), to_wp.get("lng", to_wp.get("lon"))
    if from_lat is None or to_lat is None:
        return None

    best_key, best_dist = None, float("inf")
    for route_key in routing_cache:
        try:
            start_str, end_str, _mode = route_key.split("|")
            s_lat, s_lng = (float(v) for v in start_str.split(","))
            e_lat, e_lng = (float(v) for v in end_str.split(","))
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
    """Returns the leg's mode suffix ("walking"/"ferry"/...) from its
    .routecache.json entry.

    job_config.json's waypoints no longer carry `routeMode` — the frontend
    now leaves that field off entirely and the cache key (the only place
    that still records "...|walking"/"...|ferry"/etc per leg) is the sole
    source of truth for what mode a leg was actually computed with.
    """
    best_key = _find_leg_cache_key(from_wp, to_wp, routing_cache)
    if best_key is None:
        return None
    return best_key.rsplit("|", 1)[-1].strip().lower()


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
    route point. Each leg's mode is resolved primarily from
    `routing_cache` (.routecache.json, keyed "lat,lon|lat,lon|mode" by the
    DEPARTING waypoint — matches the frontend's own routing/cache-pruning
    convention), falling back to that waypoint's own `routeMode` field only
    for older projects that still have it set. The mode carries forward
    past the last waypoint for the final leg to the destination."""
    modes = ["walking"] * num_points
    if num_points == 0:
        return modes

    # [NOTE] [Animation] "direct" is a straight-line routing choice, not a distinct travel mode — render/report it as walking rather than falling through to the generic colored-marker fallback icon.
    mode_aliases = {"direct": "walking"}

    boundaries = list(wp_indices) + [num_points - 1]
    prev_end = 0
    current_mode = "walking"
    for leg_idx, end_idx in enumerate(boundaries):
        # [NOTE] [Animation] boundaries[leg_idx] is where waypoint `leg_idx` sits; the leg ending there departs from waypoint `leg_idx - 1`. leg_idx == 0 has no real leg before it, and leg_idx == len(waypoints) is the trailing stretch past the last waypoint — both just keep whatever current_mode already is.
        if 0 < leg_idx < len(waypoints):
            from_wp, to_wp = waypoints[leg_idx - 1], waypoints[leg_idx]
            leg_mode = _resolve_leg_mode_from_cache(from_wp, to_wp, routing_cache)
            if not leg_mode:
                leg_mode = from_wp.get("routeMode")
            if leg_mode:
                leg_mode = str(leg_mode).lower()
                current_mode = mode_aliases.get(leg_mode, leg_mode)
        for i in range(prev_end, min(end_idx + 1, num_points)):
            modes[i] = current_mode
        prev_end = end_idx + 1
    return modes
