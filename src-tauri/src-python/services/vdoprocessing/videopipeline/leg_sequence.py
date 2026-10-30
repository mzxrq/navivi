"""Step 4's walking legs: the stops' pop-up data on the overview route, and each leg's render entry
(positions, mode, ferry geometry, the audio-first walk plan, pins and pop-ups)."""

import math
from pathlib import Path

import numpy as np
import pandas as pd

from services import tuning, video_text
from services.gpsparser.gpscalculator import GPSMath
from services.localization.localization import format_waypoint_label
from services.mapfetcher.graphicengine.pinimage import marker_for
from services.vdoprocessing.route_inputs import route_inputs_hash
from services.vdoprocessing.stopby_visits import visits_stopby

from .helpers import (
    _project_route_to_pixels,
    _resolve_leg_geometry_from_cache,
    leg_line_color_rgb,
    logger,
)
from .narration_step import MAX_EARLY_ARRIVAL_SECONDS, leg_walk_plan
from .render_look import _is_return_stop, _leg_pin, _returns_to, _project_rgb, overview_pin_glyphs

# Bounds on how many points a synthetic straight-line ferry crossing is
# sampled into when there's no cached routed polyline for that leg (see the
# "No cached route for this leg" fallback below).
_MIN_FERRY_SAMPLE_POINTS = 2
_MAX_FERRY_SAMPLE_POINTS = 120

def stopbys_near_the_route(waypoints: list, positions: list, lats, lons) -> dict:
    """{position: index of the closest leg point} for each not-connected stop-by within STOPBY_WALK_NEAR_METERS of
    the leg's line: the walk goes there first and its photo pops up on the way, instead of at the stop before it.
    shortcut: distance to the line's points, not its segments; fine while routed points are dense (tens of metres)."""
    near = {}
    for p in positions:
        if waypoints[p].get("connectToRoute"):
            continue
        metres = _metres_to_leg(waypoints[p], lats, lons)
        if metres is not None and metres.min() <= tuning.STOPBY_WALK_NEAR_METERS:
            near[p] = int(metres.argmin())
    return near


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
    the stop-by it pops up at ("" = the departure stop, first), several in waypoint order."""
    route_index = {
        m.get("waypoint_id"): i for i, m in enumerate(sorted(markers, key=lambda m: m.get("pos_in_chunk", 0)))
    }

    def key(m):
        after = marker_plans.get(m.get("waypoint_id"), {}).get("pops_after")
        if after is None:
            return (route_index.get(m.get("waypoint_id"), 0), 0, 0)
        return (route_index.get(after, -1), 1, id_to_position.get(m.get("waypoint_id"), 0))
    return key


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
    use_3d_res,
    waypoints,
    wp_indices,
):
    """Fills `res_sequence` with one entry per leg (nothing for an overview-only render)."""
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
        added_start = _start_pt.get("lat") is not None and (not res_wp_indices or res_wp_indices[0] != 0)
        if added_start:
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
        pin_image_by_id = {
            wp.get("id"): marker_for(wp, settings, marker_base_dir)
            for wp in res_waypoints if wp.get("id")
        }
        # A return stop shows the pin of the stop it comes back to.
        pin_id = {
            wp.get("id"): (_returns_to(waypoints, pos) or wp).get("id")
            for pos, wp in enumerate(waypoints) if wp.get("id")
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
                if visits_stopby(waypoints[p]) and waypoints[p].get("popup_image")
            ]
            # An off-route stop-by pops up at the stop before it in waypoint order, without walking: the departure
            # stop ("") or the connected stop-by before it, right after that one's photo. One close to the leg's
            # line is walked to like a connected one.
            near = stopbys_near_the_route(waypoints, stop_positions, leg_item["lats"], leg_item["lons"])
            stop_positions.sort(key=lambda p: near.get(p, closest_leg_index(waypoints[p], leg_item["lats"], leg_item["lons"])))
            pops_after: dict = {}
            anchor = ""
            for p in stop_positions:
                if waypoints[p].get("connectToRoute") or p in near:
                    anchor = waypoints[p].get("id") or ""
                else:
                    pops_after[p] = anchor
            at_start = set(pops_after)
            piece_targets = stop_positions + [end_pos]
            piece_plans: dict = {}
            silent: set = set()
            piece_log = []
            previous = start_pos
            for k, target in enumerate(piece_targets):
                natural = sum(
                    seg_durations[p] for p in range(previous, target) if p < len(seg_durations)
                ) or 10.0
                audio_seconds = audio_durations[target] if target < len(audio_durations) else 0.0
                piece_plans[target] = (
                    leg_walk_plan(
                        cue_store, waypoints[target], target, audio_seconds,
                        natural_seconds=natural, use_cues=use_cues, max_wait_seconds=max_wait,
                        ignore_start=k > 0,
                    )
                    if target < len(waypoints) else None
                )
                if piece_plans[target] is None and target < len(waypoints):
                    # No voice for this stop (an empty script): it keeps its natural walk (a pop-up at a stop takes
                    # none) instead of dropping the whole leg's plan, which made every piece one slow speed.
                    silent.add(target)
                    piece_plans[target] = (0.0 if target in at_start else natural, None, 0.0)
                elif piece_plans[target] is not None and target in at_start:
                    walk, start, wait = piece_plans[target]
                    piece_plans[target] = (0.0, start, walk + wait)
                if piece_plans[target] is not None:
                    walk, _, wait = piece_plans[target]
                    piece_log.append(
                        f"-> {waypoints[target].get('label')}: walk {walk:.1f}s "
                        f"({walk / natural:.2f}x natural pace), waits {wait:.1f}s"
                    )
                if target not in at_start:
                    previous = target
            if end_pos >= len(waypoints) or any(v is None for v in piece_plans.values()) or silent >= set(piece_plans):
                piece_plans = {}  # nothing in this leg is narrated: it walks at one pace
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
            for p, after in pops_after.items():
                marker_plans.setdefault(waypoints[p].get("id"), {})["pops_after"] = after

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

            # [NOTE] [Heatmap] The app writes each track point's elevation into raw_track.gpx (GPSBabel's csv: `height`);
            # only with the switch on, and only when it lines up with the leg's points (a ferry leg's chunk is synthetic).
            leg_heights = (
                chunk["height"].tolist()
                if settings.get("show_route_heatmap") and "height" in chunk.columns and len(chunk) == len(lats_arr)
                else None
            )

            res_sequence.append(
                {
                    **({"elevations": leg_heights} if leg_heights else {}),
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
                        glyph_by_id.get(pin_id.get(leg_item.get("start_waypoint_id"), leg_item.get("start_waypoint_id")))
                        or ("S" if seq_idx == 0 else None),
                        settings, arrived=True,
                        image=pin_image_by_id.get(pin_id.get(leg_item.get("start_waypoint_id"), leg_item.get("start_waypoint_id"))),
                    ),
                    "start_is_return": _is_return_stop(waypoints, start_pos),
                    "dest_is_return": _is_return_stop(waypoints, end_pos),
                    "dest_pin": _leg_pin(
                        glyph_by_id.get(pin_id.get(leg_item.get("end_waypoint_id"), leg_item.get("end_waypoint_id")))
                        or ("E" if seq_idx == len(sequence_data) - 1 else None),
                        settings, arrived=_is_return_stop(waypoints, end_pos),
                        image=pin_image_by_id.get(pin_id.get(leg_item.get("end_waypoint_id"), leg_item.get("end_waypoint_id"))),
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
                    # -1 for the leg from a separate start point (file 02_waypoint_00_*): it has no waypoint of
                    # its own and would otherwise share 01 with the first stop's leg, each run deleting the other.
                    "start_pos": -1 if added_start and seq_idx == 0 else start_pos,
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
                    # In the order the pauses play (the leg's pieces are cut in it): route order, each off-route
                    # stop-by right after the stop it pops up at.
                    "mid_markers": sorted(
                        markers := [
                            {
                                **m,
                                "pos_in_chunk": near.get(id_to_position.get(m.get("waypoint_id")), m["row_idx"] - start_idx),
                                **marker_plans.get(m.get("waypoint_id"), {}),
                            }
                            for m in leg_item.get("mid_markers", [])
                        ],
                        key=_play_order(markers, marker_plans, id_to_position),
                    ),
                }
            )


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
    if waypoints:
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
                **({"pin_image": _pin_image} if _pin_image else {}),
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
