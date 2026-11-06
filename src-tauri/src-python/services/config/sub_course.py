"""The project's sub course as a small project of its own, so the per-stop steps (voice, subtitles, attraction clips,
legs) run on it unchanged: `<project>/.navivi/sub_course/job_config.json` (the app writes job_config's `sub_course`,
src/utils/courses.ts). Its waypoints are the branch stop, the sub stops and, when it rejoins the main course, the main
stop it ends at. Those two main stops are already shown in the main video: no photo clip, no attraction narration, and
the branch stop says nothing (the first leg speaks the stop it walks toward)."""

import copy
from pathlib import Path
from typing import Optional

from services.projectfiles import meta_dir, write_json_atomic

_ASSET_KEYS = ("images", "videos", "popup_image")
_ANCHOR_BLANK = {"images": [], "videos": [], "videoSound": [], "popup_image": [], "attractionNarration": ""}


def sub_course_dir(project_dir) -> Path:
    return meta_dir(project_dir) / "sub_course"


def _absolute(wp: dict, project_dir: Path) -> dict:
    """Asset paths of the main project, absolute so they resolve from the sub course's folder."""
    out = dict(wp)
    for key in _ASSET_KEYS:
        if isinstance(out.get(key), list):
            out[key] = [str((project_dir / p).resolve()) if p else p for p in out[key]]
    for key in ("customMarker", "audioUrl", "videoUrl"):
        if out.get(key):
            out[key] = str((project_dir / out[key]).resolve())
    credits = out.get("imageCredits")
    if isinstance(credits, dict):
        out["imageCredits"] = {str((project_dir / k).resolve()): v for k, v in credits.items()}
    return out


def sub_config(job_config: dict, project_dir) -> Optional[dict]:
    """The sub course's job config, or None when the project has none (fewer than two stops)."""
    sub = job_config.get("sub_course") or {}
    stops = sub.get("waypoints") or []
    if len(stops) < 2:
        return None
    project_dir = Path(project_dir)
    main = {wp.get("id"): wp for wp in job_config.get("waypoints") or []}
    waypoints = []
    for pos, wp in enumerate(stops):
        wp = _absolute(wp, project_dir)
        if wp.get("branchOf"):
            wp.update(_ANCHOR_BLANK)
            # The end arrives with the main stop's own arrival line; the branch stop is where we already are.
            wp["arrivingNarration"] = "" if pos == 0 else (main.get(wp["branchOf"]) or {}).get("arrivingNarration", "")
        waypoints.append(wp)

    config = copy.deepcopy({k: v for k, v in job_config.items() if k not in ("sub_course", "waypoints")})
    for key in ("overview_narration", "overview_narration_is_auto", "overview_narration_source_ids"):
        config.pop(key, None)
    gps = (job_config.get("source_files") or {}).get("sub_gps_route") or "raw_track_sub.gpx"
    first, last = waypoints[0], waypoints[-1]
    config.update(
        project_id=f"{job_config.get('project_id', 'project')}_sub",
        directory_path=str(sub_course_dir(project_dir)),
        enable_intro=False,
        source_files={"gps_route": str((project_dir / gps).resolve())},
        start_point={"lat": first["lat"], "lng": first["lng"], "label": first.get("label")},
        end_point={"lat": last["lat"], "lng": last["lng"], "label": last.get("label")},
        waypoints=waypoints,
        sub_course_of=str(project_dir.resolve()),
    )
    return config


def write_sub_config(main_config_path) -> Optional[Path]:
    """Writes the sub course's job_config.json; None (nothing written) when the project has no sub course."""
    import json

    main_config_path = Path(main_config_path)
    with open(main_config_path, "r", encoding="utf-8") as f:
        job_config = json.load(f)
    config = sub_config(job_config, main_config_path.parent)
    if config is None:
        return None
    path = sub_course_dir(main_config_path.parent) / "job_config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, config)
    return path


def main_route_lonlat(job_config: dict) -> Optional[list]:
    """For a sub course's own config: the main course's track as [lon, lat] points (its raw_track.gpx); else None."""
    main_dir = job_config.get("sub_course_of")
    if not main_dir:
        return None
    return [[lon, lat] for lat, lon in _track_latlon(Path(main_dir) / "raw_track.gpx")] or None


def _track_latlon(gpx_path: Path) -> list:
    import re

    try:
        text = gpx_path.read_text(encoding="utf-8")
    except OSError:
        return []
    return [(float(lat), float(lon)) for lat, lon in re.findall(r'<trkpt lat="([-\d.]+)" lon="([-\d.]+)"', text)]


def sub_course_overview(job_config: dict, project_dir) -> Optional[dict]:
    """What the main overview needs to play the sub course after the main course: its track [(lat, lon)], its
    stops (anchors marked), the main stop it leaves from (`from_index`) and its title. None without one."""
    sub = job_config.get("sub_course") or {}
    stops = sub.get("waypoints") or []
    gps = (job_config.get("source_files") or {}).get("sub_gps_route") or "raw_track_sub.gpx"
    track = _track_latlon(Path(project_dir) / gps) if len(stops) > 1 else []
    if len(track) < 2:
        return None
    return {
        "track": track,
        "stops": [
            {"lat": w.get("lat"), "lng": w.get("lng"), "label": w.get("label") or w.get("name") or "", "anchor": bool(w.get("branchOf"))}
            for w in stops
        ],
        "from_index": int(sub.get("from_index", -1)),
        "mode": stops[0].get("routeMode") or "walking",
        "name": sub_course_name(job_config),
    }


def sub_course_name(job_config: dict) -> str:
    return str((job_config.get("sub_course") or {}).get("name") or "").strip()
