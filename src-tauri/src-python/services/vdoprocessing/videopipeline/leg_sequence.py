"""Step 4's walking legs: the stops' pop-up data on the overview route, and each leg's render entry
(positions, mode, ferry geometry, the audio-first walk plan, pins and pop-ups)."""

import math
from pathlib import Path
from typing import Callable, NamedTuple

import numpy as np
import pandas as pd

from services import tuning, video_text
from services.gpsparser.gpscalculator import GPSMath
from services.localization.localization import format_waypoint_label
from services.mapfetcher.graphicengine.pinimage import marker_for
from services.vdoprocessing.route_inputs import route_inputs_hash, same_place
from services.vdoprocessing.stopby_visits import visits_stopby

from .helpers import (
    _project_route_to_pixels,
    _resolve_leg_geometry_from_cache,
    leg_line_color_rgb,
    logger,
)
from .narration_step import MAX_EARLY_ARRIVAL_SECONDS, at_spans, leg_walk_plan, pace_spans, waypoint_cue_key
from .render_look import _is_return_stop, _leg_pin, _returns_to, _project_rgb, overview_pin_glyphs

# Bounds on how many points a synthetic straight-line ferry crossing is
# sampled into when there's no cached routed polyline for that leg (see the
# "No cached route for this leg" fallback below).
_MIN_FERRY_SAMPLE_POINTS = 2
_MAX_FERRY_SAMPLE_POINTS = 120
_DEFAULT_LEG_SECONDS = 10.0  # a leg or piece with no measured duration walks this long

def _same_spot(point: dict, waypoint) -> bool:
    """A project's start/end point that is its first/last stop (the app saves both): no extra leg between them."""
    return isinstance(waypoint, dict) and same_place(point, waypoint)


def stopbys_near_the_route(waypoints: list, positions: list, lats, lons) -> dict:
    """{position: index of the closest leg point} for each not-connected stop-by within STOPBY_WALK_NEAR_METERS of
    the leg's line, or farther but visible in the leg's frame and closest to a point past the leg's start: the walk
    goes there first and its photo pops up on the way. The others (off-frame, or closest to the start, where the
    walk would be empty) pop at the stop before them with the camera fly-out instead: a pop-up for a spot that is
    not on screen reads as a mistake.
    shortcut: distance to the line's points, not its segments; fine while routed points are dense (tens of metres)."""
    near = {}
    for p in positions:
        if waypoints[p].get("connectToRoute"):
            continue
        metres = _metres_to_leg(waypoints[p], lats, lons)
        if metres is not None and (
            metres.min() <= tuning.STOPBY_WALK_NEAR_METERS
            or (metres.argmin() > 0 and _in_leg_frame(waypoints[p], lats, lons))
        ):
            near[p] = int(metres.argmin())
    return near


def _in_leg_frame(wp: dict, lats, lons, aspect: float = 16 / 9) -> bool:
    """Roughly on screen in the leg's locked framing: that view fits the whole path, so the path's box grows to the
    frame's shape (the shorter side gains the slack) and then by STOPBY_VISIBLE_FRAME_PAD each side.
    shortcut: no pixel margins (the HUD band), so it reads a little wider than the real frame; the margins only
    make it stricter, and a wrongly excluded spot still gets the camera fly-out, which looks right either way."""
    lat, lng = float(wp["lat"]), float(wp.get("lng", wp.get("lon")))
    lat_lo, lat_hi, lon_lo, lon_hi = min(lats), max(lats), min(lons), max(lons)
    mid_lat, mid_lon = (lat_lo + lat_hi) / 2, (lon_lo + lon_hi) / 2
    squash = math.cos(math.radians(mid_lat)) or 1.0  # a degree of longitude is shorter away from the equator
    high, wide = lat_hi - lat_lo, (lon_hi - lon_lo) * squash
    grow = 0.5 + tuning.STOPBY_VISIBLE_FRAME_PAD
    return (
        abs(lat - mid_lat) <= max(high, wide / aspect) * grow
        and abs((lng - mid_lon) * squash) <= max(wide, high * aspect) * grow
    )


def _metres_to_leg(wp: dict, lats, lons):
    lat, lng = wp.get("lat"), wp.get("lng", wp.get("lon"))
    if lat is None or lng is None or len(lats) == 0:
        return None
    lats, lons = np.asarray(lats, float), np.asarray(lons, float)
    return GPSMath.haversine_vectorized(np.full_like(lats, float(lat)), np.full_like(lons, float(lng)), lats, lons) * 1000


def closest_leg_index(wp: dict, lats, lons) -> int:
    """Where along the leg a stop-by sits (its closest leg point); 0 without coordinates."""
    metres = _metres_to_leg(wp, lats, lons)
    return 0 if metres is None else int(metres.argmin())


def _play_order(markers: list, marker_plans: dict, id_to_position: dict):
    """Sort key for a leg's markers: route order (`pos_in_chunk`), an off-route stop-by ("pops_after") right after
    the stop-by it pops up at ("" = the departure stop, first), several in waypoint order, closed places last."""
    route_index = {
        m.get("waypoint_id"): i for i, m in enumerate(sorted(markers, key=lambda m: m.get("pos_in_chunk", 0)))
    }

    def key(m):
        after = marker_plans.get(m.get("waypoint_id"), {}).get("pops_after")
        if after is None:
            return (route_index.get(m.get("waypoint_id"), 0), 0, 0, 0)
        return (route_index.get(after, -1), 1, bool(m.get("inaccessible")), id_to_position.get(m.get("waypoint_id"), 0))
    return key


class _Pins(NamedTuple):
    """The call-wide lookups every leg's pins and positions are resolved through."""

    id_to_position: dict
    glyph_by_pos: dict
    glyph_by_id: dict
    image_by_id: dict
    pin_id: dict
    closed_points: set


class _Leg(NamedTuple):
    """One leg being built: its fetcher item, route_df rows and raw waypoint positions."""

    item: dict
    seq_idx: int
    start_idx: int
    end_idx: int
    start_pos: int
    end_pos: int
    chunk: pd.DataFrame
    mode: str


class _Narration(NamedTuple):
    """What the narration decides about a leg: its walk time, opening cue and the stops it plans."""

    total_time: float
    start_cue_seconds: object
    piece_start_cues: list  # each piece's {start} (the first is start_cue_seconds); [] when no later piece has one
    arrival_wait_seconds: object
    marker_plans: dict
    piece_targets: list
    near: dict


def _with_true_ends(project_config: dict, waypoints: list, wp_indices: list, route_rows: int):
    """(waypoints, route indices, whether a start was added) with the trip's TRUE start/end prepended/appended.

    [NOTE] job_config's "waypoints" excludes start_point/end_point, so without them the first/last leg would begin/end
    at the first/last WAYPOINT and the true ends would get no leg, pin or "S"/"E" label. These are LOCAL copies: the
    shared lists stay as they are because audio_durations/seg_durations/route_labels are indexed against the originals.
    Skipped when the true end already coincides with the first/last row. Neither point has a "popup_image", so
    they get a leg and a pin but no photo."""
    start_pt = project_config.get("start_point") or {}
    end_pt = project_config.get("end_point") or {}
    res_waypoints = list(waypoints)
    res_wp_indices = list(wp_indices)
    added_start = (start_pt.get("lat") is not None and (not res_wp_indices or res_wp_indices[0] != 0)
                   and not _same_spot(start_pt, waypoints[0] if waypoints else None))
    if added_start:
        res_waypoints = [{
            "lat": start_pt["lat"],
            "lng": start_pt.get("lng", start_pt.get("lon")),
            "label": start_pt.get("label"),
            "isStopBy": False,
        }] + res_waypoints
        res_wp_indices = [0] + res_wp_indices
    if end_pt.get("lat") is not None and (
        not res_wp_indices or res_wp_indices[-1] != route_rows - 1
    ) and not _same_spot(end_pt, waypoints[-1] if waypoints else None):
        res_waypoints = res_waypoints + [{
            "lat": end_pt["lat"],
            "lng": end_pt.get("lng", end_pt.get("lon")),
            "label": end_pt.get("label"),
            "isStopBy": False,
        }]
        res_wp_indices = res_wp_indices + [route_rows - 1]
    return res_waypoints, res_wp_indices, added_start


def _pin_tables(res_waypoints: list, waypoints: list, wp_indices: list, settings: dict, marker_base_dir) -> _Pins:
    """The lookups by waypoint id/position: raw position, overview glyph (S, 1, 2 ... E), pin image, the stop a
    return stop shows the pin of, and the closed places' route points.

    [NOTE] audio_durations/audio_pauses/seg_durations are indexed by the RAW position in `waypoints` (audio_step's
    `enumerate(waypoints)`), but stop-by merging can skip a waypoint as a leg boundary, so a leg's position in the
    fetcher's sequence no longer equals its departure's raw position: every lookup resolves through id_to_position.
    Glyphs count over res_waypoints, which carries the separate start/end points exactly as the overview does."""
    id_to_position = {
        wp.get("id"): pos for pos, wp in enumerate(waypoints) if wp.get("id")
    }
    glyph_by_pos = overview_pin_glyphs(res_waypoints)
    glyph_by_id = {
        wp.get("id"): glyph_by_pos[pos]
        for pos, wp in enumerate(res_waypoints) if wp.get("id")
    }
    image_by_id = {
        wp.get("id"): marker_for(wp, settings, marker_base_dir)
        for wp in res_waypoints if wp.get("id")
    }
    pin_id = {
        wp.get("id"): (_returns_to(waypoints, pos) or wp).get("id")
        for pos, wp in enumerate(waypoints) if wp.get("id")
    }
    closed_points = {
        wp_indices[pos] for pos, wp in enumerate(waypoints)
        if wp.get("inaccessible") and pos < len(wp_indices)
    }
    return _Pins(id_to_position, glyph_by_pos, glyph_by_id, image_by_id, pin_id, closed_points)


def _leg_positions(leg_item: dict, seq_idx: int, id_to_position: dict) -> tuple:
    """The leg's departure/arrival RAW positions, by id; the positional guess only for a waypoint with no "id"
    (older data saved before ids were assigned)."""
    start_pos = id_to_position.get(leg_item.get("start_waypoint_id"))
    if start_pos is None:
        start_pos = seq_idx
    end_pos = id_to_position.get(leg_item.get("end_waypoint_id"))
    if end_pos is None:
        end_pos = seq_idx + 1
    return start_pos, end_pos


def _leg_mode(waypoints: list, start_pos: int, start_idx: int, point_modes: list) -> str:
    leg_mode = (
        str(waypoints[start_pos].get("routeMode", "")).lower()
        if start_pos < len(waypoints)
        else ""
    )
    if not leg_mode and start_idx + 1 < len(point_modes):
        leg_mode = point_modes[start_idx + 1]
    leg_mode = leg_mode or "walking"
    return tuning.MODE_ALIASES.get(leg_mode, leg_mode)


def _ferry_chunk(leg_item: dict, seq_idx: int, start_wp: dict, end_wp: dict, count: int, routing_cache: dict,
                 fetcher, img_size: tuple) -> pd.DataFrame:
    """A ferry leg's own line, with its map refetched around it (leg_item's img_path/extent are replaced).

    [NOTE] route_df's GPS track for a ferry crossing may be sparse or road-snapped, so use the routed polyline from
    the route cache (the one the map UI draws), else a straight crossing between the stops sampled `count` points."""
    cached_geometry = _resolve_leg_geometry_from_cache(start_wp, end_wp, routing_cache)
    if cached_geometry:
        ferry_lats = np.asarray([float(pt[0]) for pt in cached_geometry])
        ferry_lons = np.asarray([float(pt[1]) for pt in cached_geometry])
    else:
        ferry_count = max(_MIN_FERRY_SAMPLE_POINTS, min(_MAX_FERRY_SAMPLE_POINTS, count))
        ferry_lats = np.linspace(float(start_wp["lat"]), float(end_wp["lat"]), ferry_count)
        ferry_lons = np.linspace(float(start_wp["lng"]), float(end_wp["lng"]), ferry_count)
    chunk = pd.DataFrame({"latitude": ferry_lats, "longitude": ferry_lons})
    ferry_map_path = str(Path(leg_item["img_path"]).with_name(f"res_map_ferry_{seq_idx + 1}.png"))
    leg_item["img_path"] = ferry_map_path
    leg_item["extent"] = fetcher.downloader.fetch_residential_chunk(chunk, ferry_map_path, img_size)
    return chunk


def _natural_seconds(seg_durations: list, first: int, last: int) -> float:
    """The walk's own length over the raw gaps [first, last): their seg_durations summed, else a default."""
    return sum(seg_durations[p] for p in range(first, last) if p < len(seg_durations)) or _DEFAULT_LEG_SECONDS


def _route_stops(waypoints: list, start_pos: int, end_pos: int, leg_item: dict) -> tuple:
    """(stop positions in walk order, those walked to, {position: id of the stop it pops up at}) for the stop-bys
    with a photo between the leg's ends.

    An off-route stop-by pops up at the stop before it in waypoint order, without walking: the departure stop ("")
    or the connected stop-by before it, right after that one's photo. One close to the leg's line is walked to
    like a connected one."""
    stop_positions = [
        p for p in range(start_pos + 1, min(end_pos, len(waypoints)))
        if (visits_stopby(waypoints[p]) or waypoints[p].get("inaccessible")) and waypoints[p].get("popup_image")
    ]
    near = stopbys_near_the_route(waypoints, stop_positions, leg_item["lats"], leg_item["lons"])
    stop_positions.sort(key=lambda p: near.get(p, closest_leg_index(waypoints[p], leg_item["lats"], leg_item["lons"])))
    pops_after: dict = {}
    anchor = ""
    for p in stop_positions:
        if waypoints[p].get("connectToRoute") or p in near:
            anchor = waypoints[p].get("id") or ""
        else:
            pops_after[p] = anchor
    return stop_positions, near, pops_after


def _piece_plan(cue_store, waypoints: list, target: int, audio_durations: list, natural: float, k: int,
                use_cues: bool, max_wait: float, at_start: set):
    """(plan, silent) for the piece walking toward `target`: leg_walk_plan's (walk, start cue, wait), None past the
    waypoints or when nothing is narrated and the leg is to walk at one pace."""
    if target >= len(waypoints):
        return None, False
    audio_seconds = audio_durations[target] if target < len(audio_durations) else 0.0
    plan = leg_walk_plan(
        cue_store, waypoints[target], target, audio_seconds,
        natural_seconds=natural, use_cues=use_cues, max_wait_seconds=max_wait,
        ignore_start=k > 0 and target in at_start,  # a pop-up without walking has no walk to start
    )
    if plan is None:
        # No voice for this stop (an empty script): it keeps its natural walk (a pop-up at a stop takes none)
        # instead of dropping the whole leg's plan, which made every piece one slow speed.
        return (0.0 if target in at_start else natural, None, 0.0), True
    if target in at_start:
        walk, start, wait = plan
        return (0.0, start, walk + wait), False
    return plan, False


def _plan_pieces(cue_store, waypoints: list, start_pos: int, piece_targets: list, audio_durations: list,
                 seg_durations: list, use_cues: bool, max_wait: float, at_start: set) -> tuple:
    """(plans by target, silent targets, log lines) for a leg cut into pieces, each walked toward its own stop."""
    piece_plans: dict = {}
    silent: set = set()
    piece_log = []
    previous = start_pos
    for k, target in enumerate(piece_targets):
        natural = _natural_seconds(seg_durations, previous, target)
        plan, is_silent = _piece_plan(
            cue_store, waypoints, target, audio_durations, natural, k, use_cues, max_wait, at_start,
        )
        piece_plans[target] = plan
        if is_silent:
            silent.add(target)
        if plan is not None:
            walk, _, wait = plan
            piece_log.append(
                f"-> {waypoints[target].get('label')}: walk {walk:.1f}s "
                f"({walk / natural:.2f}x natural pace), waits {wait:.1f}s"
            )
        if target not in at_start:
            previous = target
    return piece_plans, silent, piece_log


def _leg_narration(*, waypoints: list, leg_item: dict, start_pos: int, end_pos: int, cue_store, audio_durations: list,
                   seg_durations: list, use_cues: bool, max_wait: float) -> _Narration:
    """Audio first: the narration that plays over each walk is its DESTINATION's (leg_pieces.py), so its length
    decides how long the walk is (narration_step.leg_walk_plan): the walker may arrive early (waiting there, at
    most max_early_arrival_seconds) but never late. A leg cut at connected stop-bys is planned piece by piece."""
    distance_fallback = _natural_seconds(seg_durations, start_pos, end_pos)
    stop_positions, near, pops_after = _route_stops(waypoints, start_pos, end_pos, leg_item)
    at_start = set(pops_after)
    piece_targets = stop_positions + [end_pos]
    piece_plans, silent, piece_log = _plan_pieces(
        cue_store, waypoints, start_pos, piece_targets, audio_durations, seg_durations, use_cues, max_wait, at_start,
    )
    if end_pos >= len(waypoints) or any(v is None for v in piece_plans.values()) or silent >= set(piece_plans):
        piece_plans = {}  # nothing in this leg is narrated: it walks at one pace
    if piece_plans:
        total_time = sum(v[0] for v in piece_plans.values())
        start_cue_seconds = piece_plans[piece_targets[0]][1]  # the first piece opens the leg
        piece_start_cues = [piece_plans[p][1] for p in piece_targets]
        if not any(s is not None for s in piece_start_cues[1:]):
            piece_start_cues = []
        arrival_wait_seconds = piece_plans[end_pos][2]
        marker_plans = {
            waypoints[p].get("id"): {
                "walk_seconds": piece_plans[p][0], "wait_seconds": piece_plans[p][2],
                # The renderer keeps the small card up until this piece's voice is done (the markers came without it).
                "narration_audio_seconds": audio_durations[p] if p < len(audio_durations) and audio_durations[p] else None,
            }
            for p in stop_positions
        }
        logger.info(
            "Step 4: leg %d->%d follows its narration: %s.",
            start_pos + 1, end_pos + 1, "; ".join(piece_log),
        )
    else:
        total_time, start_cue_seconds, arrival_wait_seconds, marker_plans = distance_fallback, None, None, {}
        piece_start_cues = []
    for p, after in pops_after.items():
        marker_plans.setdefault(waypoints[p].get("id"), {})["pops_after"] = after
    return _Narration(
        total_time, start_cue_seconds, piece_start_cues, arrival_wait_seconds, marker_plans, piece_targets, near,
    )


def _cue_spans(cue_store, waypoints: list, piece_targets: list, use_cues: bool, spans_of: Callable) -> list:
    """The cue spans of every piece's narration, `spans_of(cue times, piece number)` each."""
    return [
        span
        for k, target in enumerate(piece_targets) if use_cues and target < len(waypoints)
        for span in spans_of(cue_store.cue_times_for(waypoint_cue_key(waypoints[target], target)), k)
    ]


def _leg_cues(cue_store, waypoints: list, piece_targets: list, use_cues: bool) -> tuple:
    """(street_view_cues, turn_cues, pace_cues, at_cues) for route2vdo, one list each (cue times from the store).

    {view} … {/view} / {turn}: when the street view cards pop in and out; {slow} / {fast} / {stop} … {/…}: the
    walker's pace (pedestrian._paced_plan); {at N}: the walker must be at the leg's Nth turn when the voice reaches
    it (pedestrian._at_points_plan)."""
    from services.mapfetcher.street_photos import view_cue_spans

    def of(spans_of):
        return _cue_spans(cue_store, waypoints, piece_targets, use_cues, spans_of)

    street_view_cues = of(lambda times, k: view_cue_spans(times, k, "view"))
    turn_cues = of(lambda times, k: view_cue_spans(times, k, "turn"))
    return street_view_cues, turn_cues, of(pace_spans), of(at_spans)


def _distance_km(lats_arr, lons_arr) -> float:
    if len(lats_arr) <= 1:
        return 0.0
    return float(np.nansum(GPSMath.haversine_vectorized(lats_arr[:-1], lons_arr[:-1], lats_arr[1:], lons_arr[1:])))


def _first_image(raw_img):
    if isinstance(raw_img, list) and raw_img:
        return str(raw_img[0])
    return str(raw_img) if raw_img else None


def _leg_map_fields(leg: _Leg, route_labels: list, route_popups: list, settings: dict, waypoints: list,
                    pins: _Pins, img_size: tuple) -> dict:
    """The entry's map, projected points, per-point labels and the pop-ups at the leg's two ends."""
    lats_arr, lons_arr = leg.item["lats"], leg.item["lons"]
    chunk, end_idx = leg.chunk, leg.end_idx
    # A residential clip starts at the previous waypoint, so only the destination popup may end its route
    # animation: including the start popup would end the renderer on the first frame of every leg.
    leg_popups = [None] * len(chunk)
    if len(leg_popups) > 0:
        leg_popups[-1] = route_popups[end_idx]
    # [NOTE] [Heatmap] The app writes each track point's elevation into raw_track.gpx (GPSBabel's csv: `height`);
    # only with the switch on, and only when it lines up with the leg's points (a ferry leg's chunk is synthetic).
    leg_heights = (
        chunk["height"].tolist()
        if settings.get("show_route_heatmap") and "height" in chunk.columns and len(chunk) == len(lats_arr)
        else None
    )
    return {
        **({"elevations": leg_heights} if leg_heights else {}),
        "img_path": _first_image(leg.item.get("img_path")),
        "extent": leg.item["extent"],
        "lats": lats_arr,
        "lons": lons_arr,
        "points": _project_route_to_pixels(
            chunk["latitude"].to_numpy(), chunk["longitude"].to_numpy(), leg.item["extent"], *img_size,
        ),
        # A closed place is never walked to: not in the leg's "A → B" chain.
        "labels": [
            None if leg.start_idx + k in pins.closed_points else label
            for k, label in enumerate(route_labels[leg.start_idx : end_idx + 1])
        ],
        # Per label: a stop-by (route2vdo puts those on the leg's own stop-by pill, not the place chain).
        "stopbys": [bool((route_popups[j] or {}).get("is_stopby")) for j in range(leg.start_idx, end_idx + 1)],
        "popups": leg_popups,
        # Each leg gets its own departure + arrival pair (shown at its opening, shrink) instead of relying on the
        # previous leg's arrival preview.
        "leg_start_popup": route_popups[leg.start_idx],
        # route2vdo falls back to this when a trailing synthetic end_point leg has no popup of its own (the last
        # REAL waypoint's), so the video's final clip does not arrive on no photo.
        "trip_end_popup": route_popups[end_idx] if leg.end_pos == len(waypoints) - 1 else None,
    }


def _end_pin(waypoint_id, fallback_glyph, arrived: bool, settings: dict, pins: _Pins):
    pid = pins.pin_id.get(waypoint_id, waypoint_id)
    return _leg_pin(
        pins.glyph_by_id.get(pid) or fallback_glyph, settings, arrived=arrived, image=pins.image_by_id.get(pid),
    )


def _leg_pin_fields(leg: _Leg, waypoints: list, settings: dict, pins: _Pins, leg_count: int) -> dict:
    """The leg's two pins and the HUD's "stop N of total" count (the one dest_pin's own glyph is drawn from)."""
    item, seq_idx = leg.item, leg.seq_idx
    return {
        "start_pin": _end_pin(item.get("start_waypoint_id"), "S" if seq_idx == 0 else None, True, settings, pins),
        "start_is_return": _is_return_stop(waypoints, leg.start_pos),
        "dest_is_return": _is_return_stop(waypoints, leg.end_pos),
        "dest_pin": _end_pin(
            item.get("end_waypoint_id"), "E" if seq_idx == leg_count - 1 else None,
            _is_return_stop(waypoints, leg.end_pos), settings, pins,
        ),
        "total_stops": sum(1 for g in pins.glyph_by_pos if g),
    }


def _leg_mid_markers(leg: _Leg, narration: _Narration, pins: _Pins) -> list:
    """The merged-in stop-bys along the leg, in the order the pauses play (the leg's pieces are cut in it): route
    order, each off-route stop-by right after the stop it pops up at. "pos_in_chunk" (0-based into the leg's own
    points, not the route_df row) is what waypoints.py needs to know the traveler has passed one."""
    markers = [
        {
            **m,
            "pos_in_chunk": narration.near.get(pins.id_to_position.get(m.get("waypoint_id")), m["row_idx"] - leg.start_idx),
            **narration.marker_plans.get(m.get("waypoint_id"), {}),
        }
        for m in leg.item.get("mid_markers", [])
    ]
    return sorted(markers, key=_play_order(markers, narration.marker_plans, pins.id_to_position))


def _leg_timing_fields(leg: _Leg, narration: _Narration, cues: tuple, waypoints: list, settings: dict) -> dict:
    """The mode, line color and walk timing with the leg's cue lists."""
    street_view_cues, turn_cues, pace_cues, at_cues = cues
    return {
        "mode": leg.mode,
        "line_color": (
            leg_line_color_rgb(waypoints[leg.start_pos]) if leg.start_pos < len(waypoints) else None
        ) or _project_rgb(settings, "line_color"),
        "travel_duration": narration.total_time,
        "segment_duration": narration.total_time,
        "start_cue_seconds": narration.start_cue_seconds,
        "piece_start_cues": narration.piece_start_cues,
        "street_view_cues": street_view_cues,
        "turn_cues": turn_cues,  # {turn} … {/turn}: the leg's automatic turn photos
        "pace_cues": pace_cues,
        "at_cues": at_cues,
        # Arrived early: hold on the arrived map until the voice is done, then the fullscreen photo transition.
        "arrival_wait_seconds": narration.arrival_wait_seconds,
    }


def _leg_identity_fields(leg: _Leg, narration: _Narration, waypoints: list, audio_pauses: list, pins: _Pins,
                         added_start: bool) -> dict:
    """The leg's real duration, distance, pauses and the keys the later steps look it up by."""
    chunk, item = leg.chunk, leg.item
    return {
        "real_duration_seconds": (
            (chunk["timestamp"].iloc[-1] - chunk["timestamp"].iloc[0]).total_seconds()
            if "timestamp" in chunk.columns and len(chunk) > 1
            else 0.0
        ),
        "distance_km": _distance_km(item["lats"], item["lons"]),
        "pauses": audio_pauses[leg.start_pos] if leg.start_pos < len(audio_pauses) else [],
        # The departure waypoint's RAW position goes into the output clip's filename (waypoints.py), so the audio-mux
        # loop and timeline_step resolve the narration by position, not a clip counter that stop-by merging would
        # throw out of sync. -1 for the leg from a separate start point (file 02_waypoint_00_*): it has no waypoint
        # of its own and would otherwise share 01 with the first stop's leg, each run deleting the other.
        "start_pos": -1 if added_start and leg.seq_idx == 0 else leg.start_pos,
        # The leg's checkpoint key (route2vdo): its waypoints' route inputs.
        "route_inputs": route_inputs_hash(waypoints[leg.start_pos:leg.end_pos + 1]),
        # route2vdo writes the destination into the leg's _pieces.json so leg_pieces.py plays the DESTINATION's
        # narration over the walk toward it.
        "start_waypoint_id": item.get("start_waypoint_id"),
        "end_waypoint_id": item.get("end_waypoint_id"),
        "wide_img_path": item.get("wide_img_path"),
        "wide_extent": item.get("wide_extent"),
        "mid_markers": _leg_mid_markers(leg, narration, pins),
    }


class _Build(NamedTuple):
    """The call-wide inputs shared by every leg of one build_leg_sequence call."""

    waypoints: list
    settings: dict
    cue_store: object
    fetcher: object
    audio_durations: list
    audio_pauses: list
    seg_durations: list
    route_labels: list
    route_popups: list
    routing_cache: dict
    point_modes: list
    img_size: tuple
    pins: _Pins
    added_start: bool
    leg_count: int


def _leg_of(build: _Build, route_df: pd.DataFrame, seq_idx: int, leg_item: dict) -> _Leg:
    """Resolves the leg's rows, positions and mode; a ferry leg gets its own line and map first."""
    waypoints = build.waypoints
    start_idx, end_idx = leg_item["start_idx"], leg_item["end_idx"]
    chunk = route_df.iloc[start_idx : end_idx + 1]
    start_pos, end_pos = _leg_positions(leg_item, seq_idx, build.pins.id_to_position)
    leg_mode = _leg_mode(waypoints, start_pos, start_idx, build.point_modes)
    if str(leg_mode).lower() == "ferry" and end_pos < len(waypoints):
        chunk = _ferry_chunk(
            leg_item, seq_idx, waypoints[start_pos], waypoints[end_pos], end_idx - start_idx + 1,
            build.routing_cache, build.fetcher, build.img_size,
        )
    return _Leg(leg_item, seq_idx, start_idx, end_idx, start_pos, end_pos, chunk, leg_mode)


def _leg_entry(build: _Build, leg: _Leg) -> dict:
    """One leg's render entry (narration plan first, so its log line precedes the entry's other work)."""
    waypoints, settings = build.waypoints, build.settings
    narration = _leg_narration(
        waypoints=waypoints, leg_item=leg.item, start_pos=leg.start_pos, end_pos=leg.end_pos,
        cue_store=build.cue_store, audio_durations=build.audio_durations, seg_durations=build.seg_durations,
        use_cues=bool(settings.get("use_narration_cues", True)),
        max_wait=float(settings.get("max_early_arrival_seconds", MAX_EARLY_ARRIVAL_SECONDS)),
    )
    cues = _leg_cues(
        build.cue_store, waypoints, narration.piece_targets, bool(settings.get("use_narration_cues", True)),
    )
    return {
        **_leg_map_fields(leg, build.route_labels, build.route_popups, settings, waypoints, build.pins, build.img_size),
        **_leg_timing_fields(leg, narration, cues, waypoints, settings),
        **_leg_pin_fields(leg, waypoints, settings, build.pins, build.leg_count),
        **_leg_identity_fields(leg, narration, waypoints, build.audio_pauses, build.pins, build.added_start),
    }


def build_leg_sequence(
    *,
    audio_durations,
    audio_pauses,
    cue_store,
    fetcher,
    img_h,
    img_w,
    leg_index,
    marker_base_dir,
    point_modes,
    project_config,
    render_mode,
    res_sequence,
    route_df,
    route_labels,
    route_popups,
    routing_cache,
    seg_durations,
    settings,
    waypoints,
    wp_indices,
):
    """Fills `res_sequence` with one entry per leg (nothing for an overview-only render)."""
    if render_mode in ("overview", "recap_frame"):
        # [NOTE] Overview-only (or just its recap frame): no per-leg residential map tile fetches or clips;
        # res_sequence stays [], which RouteAnimator.render already treats as "nothing to render".
        logger.info("Step 4: render_mode=%s — skipping residential sequence.", render_mode)
        return
    logger.info("Step 4: Generating residential leg sequence (lat/lon per leg)...")
    res_waypoints, res_wp_indices, added_start = _with_true_ends(project_config, waypoints, wp_indices, len(route_df))
    # [NOTE] Stop-by leg-merging is a per-project toggle; multi-tile chunk splitting stays off (math.inf): enabling
    # it also needs the audio-mux/timeline position lookups reworked for several clips sharing one leg's narration.
    sequence_data = fetcher.process_residential_sequence(
        route_df,
        res_waypoints,
        output_size=(img_w, img_h),
        max_chunk_distance_meters=math.inf,
        precomputed_indices=res_wp_indices,
        merge_stopbys=bool(
            settings.get("merge_stopby_waypoints", tuning.DEFAULT_MERGE_STOPBY_WAYPOINTS)
        ),
        # Filtered HERE so a single-leg test run skips every other leg's map tile fetch.
        leg_index=leg_index,
    )
    pins = _pin_tables(res_waypoints, waypoints, wp_indices, settings, marker_base_dir)
    build = _Build(
        waypoints, settings, cue_store, fetcher, audio_durations, audio_pauses, seg_durations, route_labels,
        route_popups, routing_cache, point_modes, (img_w, img_h), pins, added_start, len(sequence_data),
    )
    for seq_idx, leg_item in enumerate(sequence_data):
        leg = _leg_of(build, route_df, seq_idx, leg_item)
        res_sequence.append(_leg_entry(build, leg))


def _popup_image_at(popup_img, index: int):
    """One of a waypoint's "popup_image" photos (a str, or the map editor's multi-image list) as a str, or None."""
    if isinstance(popup_img, list) and popup_img:
        return str(popup_img[index])
    return str(popup_img) if popup_img else None


def _waypoint_popup(wp: dict, idx: int, count: int, pin_image, audio_seconds) -> dict:
    """The route point's pop-up data for one waypoint; see inject_waypoint_popups."""
    popup_img = wp.get("popup_image")
    wp_skipped = bool(wp.get("skipAssetGeneration")) and 0 < idx < count - 1
    return {
        "freeze_seconds": min(float(wp.get("freeze_seconds", 3.0)), tuning.POPUP_FREEZE_SECONDS_MAX),
        "audio_duration": audio_seconds,
        # The overview animation (this dict is shared with it) shows the FIRST photo ...
        "popup_image": _popup_image_at(popup_img, 0),
        # ... the residential leg's fullscreen-to-card destination intro the LAST (pedestrian's `dest_popup_image`).
        "popup_image_last": _popup_image_at(popup_img, -1),
        "image_display": str(wp.get("image_display", "cover")).lower(),
        "triggered": False,
        **({"pin_image": pin_image} if pin_image else {}),
        # Like MapArea.tsx, a stop-by is always a "stopby" pin ("・" dot) and skipped by the others' numbering. A
        # waypoint skipped in video export is drawn and numbered like one, but only pops up as the walker passes
        # (is_skipped: never batched, never stopped at - see popups.py).
        "is_stopby": bool(wp.get("isStopBy", False) or wp_skipped),
        "is_skipped": wp_skipped,
        # A closed place (the editor's "Closed"): a red × pin, shown after the stop-bys at {closed}.
        "inaccessible": bool(wp.get("inaccessible")),
        # The editor's "Pause at Location" (default on): off, the overview walker doesn't stop here.
        "pause_at_waypoint": wp.get("pauseAtWaypoint") is not False,
        # A CONNECTED stop-by is one the route runs through: an ordinary stop that merely LOOKS different. An
        # unconnected one is a landmark never walked to, shown with the previous normal stop (overview.py's
        # _attach_stopby_groups).
        "connect_to_route": bool(wp.get("connectToRoute", False) and not wp_skipped),
        "id": wp.get("id"),  # the "map" overview's leg cards (route_brief legs' to_id)
        # The waypoint's own GPS coordinates, apart from the nearest TRACK point used for x/y: overview.py
        # re-projects a stop-by seen from afar to its own lat/lng instead of snapping it onto the route line.
        "lat": wp.get("lat"),
        "lng": wp.get("lng", wp.get("lon")),
    }


def inject_waypoint_popups(
    *,
    audio_durations,
    marker_base_dir,
    project_config,
    route_labels,
    route_popups,
    settings,
    subtitle_lang,
    waypoints,
    wp_indices,
):
    """Puts each waypoint's label and pop-up data on its route point (route_labels / route_popups)."""
    if not waypoints:
        return
    logger.info("Step 4: Injecting %d custom waypoints.", len(waypoints))
    start_label = project_config.get("start_point", {}).get("label")
    end_label = project_config.get("end_point", {}).get("label")
    text_labels = video_text.current_labels()

    for idx, wp in enumerate(waypoints):
        route_point_idx = wp_indices[idx]
        _pin_image = marker_for(wp, settings, marker_base_dir)
        raw_label = wp.get("label", text_labels["waypoint_fallback"])

        if idx == 0 and start_label:
            raw_label = start_label
        elif idx == len(waypoints) - 1 and end_label:
            raw_label = end_label

        # No "出発:"/"到着:" prefix: the leg chain banner marks the start/end with an S/E badge (pedestrian.py).
        route_labels[route_point_idx] = format_waypoint_label(raw_label, subtitle_lang)

        # [NOTE] The waypoint's own narration TTS length (audio_durations, 1:1 with `enumerate(waypoints)`) is
        # stashed on the waypoint dict ITSELF so it rides along wherever that dict is reused, notably
        # process_residential_sequence's mid_markers/landmarks: the fullscreen popup's hold must not cut away
        # before the muxed narration ends ("freeze_seconds" is only the fallback with no narration;
        # see pedestrian.py's `_min_hold_seconds`).
        wp["_narration_audio_seconds"] = (
            float(audio_durations[idx])
            if idx < len(audio_durations) and audio_durations[idx]
            else None
        )
        route_popups[route_point_idx] = _waypoint_popup(
            wp, idx, len(waypoints), _pin_image, wp["_narration_audio_seconds"],
        )
