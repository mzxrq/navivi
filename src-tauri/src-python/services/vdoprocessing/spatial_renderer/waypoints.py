"""The per-residential-leg (waypoint chunk) video render entry point."""

import math
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from services.logger.progress import tracker
from services.mapfetcher.mapfetcher import MapFetcher
from services.mapfetcher.mapgeometry import RouteGeometryProcessor
from services.vdoprocessing.vdoexporter import VideoExporter
from services import tuning


class _WaypointRenderMixin:
    @staticmethod
    def _ease_in_out(t: float) -> float:
        """Same easing curve local_pan_generator.py uses for its Ken-Burns
        pans — kept as its own copy rather than imported since that module
        is coupled to its own photo pipeline/VideoWriter."""
        return 0.5 - 0.5 * math.cos(math.pi * t)

    def _play_leg_summary_card(
        self,
        video: VideoExporter,
        base_frame: np.ndarray,
        seg_card: np.ndarray,
        fps: int,
        fade_sec: float,
        clip_hold_sec: float,
        play_exit: bool = True,
        play_hold: bool = True,
        margin: int = 20,
        corner: str = "bottom_right",
    ) -> None:
        """Slides this leg's summary card/bar up from off-screen at the
        bottom (rather than just fading it in in place), holds it, then
        (when `play_exit`) slides it back down and out — same ease-out-
        cubic shape _popup_slide_offset_y uses elsewhere for the
        overview's own popup cards, just with a distance sized to the
        card's own height so it starts genuinely below the frame instead
        of a few px below its resting spot. `play_exit=False` for a leg
        whose clip ends right here (no next frame for a slide-out to play
        into) — it just holds until the clip cuts. `play_hold=False`
        skips the static hold entirely (entrance only) — used when the
        caller wants to composite the hold/exit itself on top of OTHER,
        already-moving frames instead of a static one (see
        render_waypoints' own intro_card_hold_frames/
        intro_card_exit_frames) so the card stays visible while the route
        animation is already playing, not just before it starts.
        `margin`/`corner` forward to composite_card_on_frame — pass
        margin=0 for a create_leg_summary_bar full-width bar so it sits
        flush against both side edges instead of floating with the usual
        card margin."""
        card_h = seg_card.shape[0]
        slide_distance = card_h + 40
        fade_frames = max(1, int(fade_sec * fps))

        for f in range(fade_frames):
            t = (f + 1) / fade_frames
            eased = 1 - (1 - t) ** 3
            video.write(
                self.graphics.composite_card_on_frame(
                    base_frame, seg_card, alpha=t, margin=margin, corner=corner,
                    slide_offset_y=slide_distance * (1 - eased),
                )
            )

        if play_hold:
            held_frame = self.graphics.composite_card_on_frame(
                base_frame, seg_card, alpha=1.0, margin=margin, corner=corner,
            )
            for _ in range(max(0, int(clip_hold_sec * fps) - fade_frames)):
                video.write(held_frame)

        if play_exit:
            for f in range(fade_frames):
                t = (f + 1) / fade_frames
                eased = 1 - (1 - t) ** 3
                video.write(
                    self.graphics.composite_card_on_frame(
                        base_frame, seg_card, alpha=1.0 - t, margin=margin, corner=corner,
                        slide_offset_y=slide_distance * eased,
                    )
                )

    def _play_leg_wide_intro(
        self, video: VideoExporter, res_data: Dict, current_bg: np.ndarray, fps: int
    ) -> None:
        """Holds this leg's wide establishing shot, then crossfades (scale-
        free — both tiles already share the same canvas size) into the
        close/tight tile the rest of this leg's clip will animate on top
        of. A no-op when this res_data has no wide tile (only a leg's
        first chunk ever does — see mapfetcher.py's is_first_chunk_of_leg)
        or the wide tile can't be read/doesn't match current_bg's size."""
        wide_path = res_data.get("wide_img_path")
        if not wide_path:
            return
        wide_bg = self.graphics.read_image_safe(str(wide_path))
        if wide_bg is None:
            return
        if wide_bg.shape[:2] != current_bg.shape[:2]:
            # Both tiles are fetched at the same output_size, but
            # current_bg may have been snapped to even dimensions after
            # the wide tile was already saved — resize rather than skip
            # the whole intro over a 1px mismatch.
            wide_bg = cv2.resize(wide_bg, (current_bg.shape[1], current_bg.shape[0]))

        hold_frames = max(1, int(tuning.RESIDENTIAL_WIDE_HOLD_SECONDS * fps))
        zoom_frames = max(1, int(tuning.RESIDENTIAL_WIDE_ZOOM_SECONDS * fps))
        for _ in range(hold_frames):
            video.write(wide_bg)
        for frame_i in range(zoom_frames):
            t = self._ease_in_out(frame_i / max(1, zoom_frames - 1))
            blended = cv2.addWeighted(wide_bg, 1.0 - t, current_bg, t, 0.0)
            video.write(blended)
        self.last_frame = current_bg
    def render_waypoints(self, res_sequence: List[Dict], fps: int) -> List[str]:
        output_paths = []
        show_segment_summary = self.config.get("show_segment_summary", True)
        fade_sec = self.config.get("summary_fade", 0.5)
        clip_hold_sec = self.config.get("clip_summary_hold", 2.0)
        job_waypoints = self._get_job_waypoints()

        # 1-based visit order per position (skipping stop-by entries,
        # matching overview.py's own numbering), keyed by job_config's own
        # "id" field where present — the reliable way to find a leg
        # endpoint's real position in the WHOLE route. Label text alone is
        # NOT reliable for this: the same place name can legitimately
        # appear at several different waypoints in one project (e.g. a
        # route that passes through "大阪市" multiple times), so matching
        # by label would collapse them all onto whichever one happens to
        # come first in job_waypoints.
        # job_config.json's own "waypoints" array holds only the
        # INTERMEDIATE stops — the trip's true start/end live in separate
        # "start_point"/"end_point" keys (see render_step.py) — so a raw
        # 0-indexed position here is one less than that waypoint's real
        # index in the FULL route (points[0] is always the true start).
        # Stored/returned as `_pos + 1` throughout so it lines up with
        # _pin_label_and_color's own index==0 ("S") / index==total-1
        # ("E") checks, which are written assuming the full route's index
        # space — without the +1, whichever waypoint happened to sit at
        # job_waypoints position 0 got mislabeled "S" (and the one at the
        # last position "E"), overwriting its real visit-order number.
        _wp_by_id: Dict[str, Tuple[int, int, bool]] = {}
        # Geographic fallback candidates — every job_waypoint PLUS the
        # true start/end points (which live outside job_waypoints
        # entirely, in their own job_config keys) — each as
        # (lat, lng, index, order, is_stopby). Used instead of matching
        # by label text: this route revisits the same generic place name
        # ("大阪市") at several genuinely different physical locations, so
        # comparing real coordinates is the only way to actually tell
        # those apart — a label match would (and did) conflate them.
        _location_candidates: List[Tuple[float, float, int, Optional[int], bool]] = []
        _job_config_for_resolve = self._get_job_config() or {}
        _start_pt = _job_config_for_resolve.get("start_point") or {}
        _end_pt = _job_config_for_resolve.get("end_point") or {}
        if _start_pt.get("lat") is not None:
            _location_candidates.append(
                (_start_pt["lat"], _start_pt.get("lng", _start_pt.get("lon")), 0, None, False)
            )
        _order = 0
        for _pos, _jw in enumerate(job_waypoints):
            # job_config.json's own key is "isStopBy" (camelCase, as saved
            # by the frontend) — "is_stopby" only exists on the NORMALIZED
            # dicts built downstream (see render_step.py), never on these
            # raw job_waypoints entries.
            _is_stopby = bool(_jw.get("isStopBy", False))
            if not _is_stopby:
                _order += 1
            _wp_id = _jw.get("id")
            if _wp_id:
                _wp_by_id[_wp_id] = (_pos + 1, _order, _is_stopby)
            _lat, _lng = _jw.get("lat"), _jw.get("lng", _jw.get("lon"))
            if _lat is not None and _lng is not None:
                _location_candidates.append((_lat, _lng, _pos + 1, _order, _is_stopby))
        _total_route_points = len(job_waypoints) + 2
        if _end_pt.get("lat") is not None:
            _location_candidates.append((
                _end_pt["lat"], _end_pt.get("lng", _end_pt.get("lon")),
                _total_route_points - 1, None, False,
            ))
        # ~30m in degrees at this latitude — a real GPS/routing match
        # should land far closer than this; anything farther means "no
        # real match found" rather than a wrong one.
        _LOCATION_MATCH_MAX_DEGREES = 0.0003

        def _resolve_global_waypoint(
            waypoint_id: Optional[str], label: str,
            lat: Optional[float] = None, lng: Optional[float] = None,
        ):
            """Finds this leg endpoint's real position in the whole
            route's waypoint list and its 1-based visit order — by exact
            "id" match when available (see _wp_by_id above), else by
            nearest real coordinate among _location_candidates (this
            route's own generic repeated place names make label-text
            matching unreliable — see _location_candidates' own comment),
            falling back to a fuzzy label match only as a last resort for
            older data with neither an id nor usable lat/lng. Needed
            because a leg's OWN first/last point (index 0 / len-1 within
            just that leg) is not the trip's actual start/end — using
            those local indices directly would mislabel every leg's
            arrival pin "E" (and every leg's departure pin "S"), not just
            the true first and last legs of the whole route."""
            if waypoint_id and waypoint_id in _wp_by_id:
                return _wp_by_id[waypoint_id]
            if lat is not None and lng is not None and _location_candidates:
                best = min(
                    _location_candidates,
                    key=lambda c: (c[0] - lat) ** 2 + (c[1] - lng) ** 2,
                )
                if math.hypot(best[0] - lat, best[1] - lng) <= _LOCATION_MATCH_MAX_DEGREES:
                    return best[2], best[3], best[4]
            if not label:
                return None
            order = 0
            for pos, jw in enumerate(job_waypoints):
                is_stopby = bool(jw.get("isStopBy", False))
                if not is_stopby:
                    order += 1
                jw_lbl = str(jw.get("label", ""))
                if jw_lbl and (jw_lbl in label or label in jw_lbl):
                    return pos + 1, order, is_stopby
            return None

        for i, res_data in enumerate(res_sequence):
            bg_path = res_data["img_path"]

            is_video = (
                str(bg_path).lower().endswith((".mp4", ".webm", ".avi", ".mov", ".mkv"))
            )
            if is_video:
                cap = cv2.VideoCapture(str(bg_path))
                ret, current_bg = cap.read()
                if not ret:
                    # [NOTE] [IO] Release the handle before skipping this leg — otherwise it leaks for the rest of the render.
                    cap.release()
                    continue
            else:
                current_bg = self.graphics.read_image_safe(str(bg_path))
                if current_bg is None:
                    continue
                cap = None

            h, w = current_bg.shape[:2]
            if h % 2 != 0 or w % 2 != 0:
                h, w = h - (h % 2), w - (w % 2)
                current_bg = cv2.resize(current_bg, (w, h))

            show_map_border = self.config.get("waypoint_map_border", True)
            if show_map_border:
                self.graphics.draw_frame_border(current_bg)
            if self.config.get("show_compass", True):
                self.graphics.draw_compass(current_bg)

            res_points = res_data["points"]
            res_labels = res_data["labels"]
            res_popups = res_data.get("popups", [None] * len(res_points))
            res_mode = str(res_data.get("mode", "walking")).lower()

            # This leg's own departure/arrival place names, cleaned of the
            # "出発: "/"到着: " prefixes route_labels carries (see
            # render_step.py) — used by the per-leg summary card's route
            # line ("{from} → {to}") further down.
            def _clean_leg_label(raw: Optional[str]) -> str:
                if not raw:
                    return ""
                return (
                    raw.replace(tuning.PIPELINE_LABELS["start_prefix"], "")
                    .replace(tuning.PIPELINE_LABELS["stop_prefix"], "")
                    .replace(tuning.PIPELINE_LABELS["start_prefix"].strip(": "), "")
                    .replace(tuning.PIPELINE_LABELS["stop_prefix"].strip(": "), "")
                    .strip()
                )

            leg_from_label = _clean_leg_label(res_labels[0] if res_labels else None)
            leg_to_label = _clean_leg_label(res_labels[-1] if res_labels else None)

            total_duration = res_data.get(
                "segment_duration", self.config.get("res_duration", 12.0)
            )
            travel_duration = res_data.get("travel_duration", total_duration)
            # "real_duration_seconds" is explicitly 0.0 (not absent) when
            # the chunk has no timestamp data — showed no time at all on
            # the summary card. Falling back to total_duration/
            # travel_duration would be wrong here: those are the leg's
            # ANIMATION length in video-seconds, not a real-world travel
            # time, and showing e.g. "6 sec" for a real ferry ride (or the
            # nonsense speed that implies) is worse than an estimate.
            # Instead, estimate real-world time from this leg's own
            # distance and its mode's configured speed — the same
            # distance/speed relationship the rest of the pipeline already
            # uses for mode-aware pacing.
            seg_real_duration = res_data.get("real_duration_seconds") or 0.0
            if seg_real_duration <= 0:
                seg_distance_km = res_data.get("distance_km", 0.0)
                if seg_distance_km > 0:
                    fallback_speed = self.mode_speed_kmh.get("walking", 5.0) or 5.0
                    speed_kmh = self.mode_speed_kmh.get(res_mode, fallback_speed) or fallback_speed
                    seg_real_duration = (seg_distance_km / speed_kmh) * 3600.0
                else:
                    seg_real_duration = total_duration
            pauses = res_data.get("pauses", [])

            # [NOTE] [Animation] Floors total_frames at 10 so a very short/near-zero-duration leg still produces a playable clip instead of 0-1 frames.
            total_frames = max(10, int(total_duration * fps))
            is_paused_per_frame = [
                (
                    any(p["start"] <= (f / fps) <= p["end"] for p in pauses)
                    if pauses
                    else False
                )
                for f in range(total_frames)
            ]

            total_pause_seconds = sum(p["duration"] for p in pauses) if pauses else 0.0

            # --- FIX 2: Apply the same pixel filter to the residential maps ---
            filtered_res = [res_points[0]]
            for pt in res_points[1:]:
                if (
                    math.hypot(pt[0] - filtered_res[-1][0], pt[1] - filtered_res[-1][1])
                    > 3.0
                ):
                    filtered_res.append(pt)
            if filtered_res[-1] != res_points[-1]:
                filtered_res.append(res_points[-1])

            actual_travel_seconds = max(1.0, travel_duration - total_pause_seconds)

            res_smooth_path = MapFetcher.get_smooth_path(
                filtered_res,
                max(2, int(actual_travel_seconds * fps)),
                ease=True,
                # Real routed geometry (e.g. from .routecache.json) carries
                # small GPS/routing jitter that the default 3px tolerance
                # barely touches — a noticeably looser tolerance smooths
                # that out into a cleaner line without cutting real turns.
                simplify_tolerance_px=6.0,
            )

            res_named = [
                (int(res_points[j][0]), int(res_points[j][1]), res_labels[j])
                for j in range(len(res_points))
                if RouteGeometryProcessor.is_real_label(res_labels[j])
            ]
            leg_label = (
                res_named[-1][2]
                if res_named
                else (res_labels[-1] if res_labels else f"Leg {i + 1}")
            )
            tracker.show(
                f"Rendering waypoint leg {i + 1}/{len(res_sequence)}: {leg_label}"
            )
            active_res_popups = [
                {
                    "x": res_points[j][0],
                    "y": res_points[j][1],
                    "data": res_popups[j],
                    "label": res_labels[j],
                    "index": j,
                }
                for j in range(len(res_points))
                if res_popups[j] is not None
            ]

            for popup in active_res_popups:
                lbl = str(popup.get("label", ""))
                for jw in job_waypoints:
                    jw_lbl = str(jw.get("label", ""))
                    if jw_lbl and (jw_lbl in lbl or lbl in jw_lbl):
                        if (
                            "image_display" in jw
                            and popup["data"].get("image_display", "box") == "box"
                        ):
                            popup["data"]["image_display"] = jw["image_display"]
                        if "popup_video" in jw and not popup["data"].get("popup_video"):
                            popup["data"]["popup_video"] = jw["popup_video"]
                        break

            res_landmark_sprites = {
                lbl: self.graphics.prebake_landmark_sprite(lbl)
                for _, _, lbl in res_named
            }
            safe_suffix = (
                "".join(
                    c
                    for c in str(res_named[-1][2] if res_named else f"leg{i+1}")
                    if c.isalnum() or c in (" ", "_", "-")
                )
                .strip()
                .replace(" ", "_")
                or f"leg{i+1}"
            )
            # 1-based departure-waypoint RAW position when render_step.py
            # supplies one (see its "start_pos" field) — falls back to the
            # old purely-sequential `i` for any other caller that doesn't.
            # render_step.py's audio-mux loop and timeline_step.py both
            # parse this number back out of the filename (RESIDENTIAL_LEG_RE)
            # to find this leg's correct narration by position rather than
            # a blind per-clip counter, which stop-by leg-merging can throw
            # out of sync with a purely sequential `i`.
            leg_file_num = res_data.get("start_pos")
            leg_file_num = (leg_file_num + 1) if leg_file_num is not None else (i + 1)
            chunk_filename = f"02_waypoint_{leg_file_num:02d}_{safe_suffix}.mp4"

            video = VideoExporter(str(self.out_dir / chunk_filename), w, h, fps)

            # Wide establishing shot -> zoom crossfade into this leg's
            # close/tight tile — plays once per leg (only res_data entries
            # for a leg's first chunk carry a wide_img_path at all), before
            # anything else (pins, popups, animation) is drawn. Off by
            # default (settings.show_leg_wide_intro) — the clip now opens
            # straight on the waypoint-level map instead of a "big map"
            # beat first.
            if self.config.get("show_leg_wide_intro", False):
                self._play_leg_wide_intro(video, res_data, current_bg, fps)

            # This leg's departure/arrival waypoints, resolved to their
            # REAL position in the whole route (see _resolve_global_waypoint
            # above) — computed once and reused by both the intro beat
            # below AND the main animation loop's own start/end markers,
            # so a leg passing through a repeated place name (e.g. a route
            # that visits "大阪市" several times) shows the same correct
            # S/E/stop-by/number label in both places, instead of the
            # intro getting it right and the animated drive-through
            # falling back to a hardcoded "S"/"E" regardless of whether
            # this leg is actually the trip's true first/last one.
            start_label = res_labels[0] if res_labels else ""
            end_label = res_labels[-1] if res_labels else ""
            _res_lats, _res_lons = res_data.get("lats"), res_data.get("lons")
            start_match = _resolve_global_waypoint(
                res_data.get("start_waypoint_id"), start_label,
                lat=_res_lats[0] if _res_lats is not None and len(_res_lats) else None,
                lng=_res_lons[0] if _res_lons is not None and len(_res_lons) else None,
            )
            end_match = _resolve_global_waypoint(
                res_data.get("end_waypoint_id"), end_label,
                lat=_res_lats[-1] if _res_lats is not None and len(_res_lats) else None,
                lng=_res_lons[-1] if _res_lons is not None and len(_res_lons) else None,
            )
            # +2 for the true start/end points, which live outside
            # job_waypoints entirely (see _resolve_global_waypoint's own
            # comment) — matches the +1 offset applied to every resolved
            # index above, so _pin_label_and_color's index==total-1 ("E")
            # check lines up with the real last position in the FULL
            # route instead of the last position within job_waypoints
            # alone.
            total_wp = len(job_waypoints) + 2

            # Merged-in stop-bys along this leg (see mapfetcher.py's
            # merge_stopbys) — drawn as plain pins for the whole leg's
            # clip, same as res_named's landmark sprites just below (always
            # visible from frame 1, not gated on the traveler having
            # actually reached them yet) — no popup, no arrival sequence.
            mid_marker_pins = [
                {
                    "x": m["px"][0], "y": m["px"][1], "index": -1, "order": None,
                    "label": m.get("label"), "data": {"is_stopby": True},
                }
                for m in res_data.get("mid_markers", [])
            ]

            def _leg_pin(x, y, label, data, match):
                # A resolved match carries this waypoint's real position
                # in the WHOLE route, so _draw_pin's / _pin_label_and_color's
                # S/E/stop-by/number precedence reflects the trip as a
                # whole — not just this one leg's own endpoints.
                # Unresolved (shouldn't normally happen — these labels
                # come from the same job_waypoints in the first place)
                # falls back to a plain number-less pin rather than
                # risking a wrong S/E/number label.
                index, order, is_stopby = match if match else (-1, None, False)
                return {
                    "x": x, "y": y, "index": index, "order": order,
                    "label": label, "data": {**(data or {}), "is_stopby": is_stopby},
                }

            start_wp = _leg_pin(
                res_points[0][0], res_points[0][1], start_label, res_popups[0], start_match
            )
            end_wp = _leg_pin(
                res_points[-1][0], res_points[-1][1], end_label, res_popups[-1], end_match
            )
            start_pin_label, start_pin_color = self._pin_label_and_color(start_wp, total_wp)
            end_pin_label, end_pin_color = self._pin_label_and_color(end_wp, total_wp)

            # Built ONCE, always (not just when the popup-card intro below
            # plays) — the full route line for this whole leg (a preview
            # of where it's headed, at reduced opacity so it doesn't read
            # as an already-traveled path — that's still drawn fresh,
            # frame by frame, once the animation itself starts) plus
            # every pin along it (mid-route stop-bys, and the departure/
            # arrival points). Both the popup-card intro hold below AND
            # the summary bar intro use THIS frame as their base — a
            # previous version had the summary bar slide up on a bare
            # current_bg with none of this drawn on it at all.
            route_preview_frame = current_bg.copy()
            if len(res_smooth_path) > 1:
                overlay = route_preview_frame.copy()
                cv2.polylines(
                    overlay,
                    [np.asarray(res_smooth_path, dtype=np.int32)],
                    False, self.graphics.line_color, self.graphics.line_thickness,
                    cv2.LINE_AA,
                )
                cv2.addWeighted(overlay, 0.45, route_preview_frame, 0.55, 0, route_preview_frame)
            for marker_pin in mid_marker_pins:
                self._draw_pin(route_preview_frame, marker_pin, total_wp)
            self._draw_pin(route_preview_frame, start_wp, total_wp)
            self._draw_pin(route_preview_frame, end_wp, total_wp)

            # Intro beat: show the departure and arrival pins (each with a
            # leader-lined popup card, when they have a photo) together on
            # the still, zoomed-in leg map before the route animates —
            # mirrors render_overview()'s "preview every stop up front"
            # intro, scoped to this leg's own start/end.
            waypoint_intro_freeze = float(self.config.get("waypoint_intro_freeze", 2.0))
            if waypoint_intro_freeze > 0 and len(res_points) >= 2:
                intro_frame = route_preview_frame.copy()
                popup_cards = []
                for wp, wp_color in ((start_wp, start_pin_color), (end_wp, end_pin_color)):
                    if wp["data"].get("popup_image"):
                        popup_card = dict(wp)
                        popup_card["hud_corner"] = None
                        popup_card["draw_leader_line"] = True
                        # Card border matches this waypoint's own pin
                        # color (S=green, E=red, stop-by=brown, etc).
                        popup_card["border_color"] = wp_color or self.graphics.marker_color
                        popup_cards.append(popup_card)

                # Line, then pin, then card — in that order — so each
                # leader line sits BEHIND both its own pin and its card,
                # instead of drawing the pins first and letting the lines
                # (drawn afterward, as part of the card) land on top of
                # them.
                for popup_card in popup_cards:
                    intro_frame = self.graphics.render_popup_box(
                        intro_frame, popup_card, line_only=True
                    )
                self._draw_pin(intro_frame, start_wp, total_wp)
                self._draw_pin(intro_frame, end_wp, total_wp)
                for popup_card in popup_cards:
                    intro_frame = self.graphics.render_popup_box(
                        intro_frame, popup_card, skip_line=True
                    )
                for _ in range(int(waypoint_intro_freeze * fps)):
                    video.write(intro_frame)
                self.last_frame = intro_frame
                route_preview_frame = intro_frame

            # Show this leg's own summary bar UP FRONT too, right before
            # the traveler starts moving — not just at arrival (see
            # show_segment_summary further down) — so the viewer knows
            # where this leg is headed, by what mode, and how long it'll
            # take before watching it play out. Only the ENTRANCE (slide
            # up) plays here, as a brief static beat on route_preview_frame
            # — the HOLD and EXIT are deliberately NOT played yet. They're
            # composited instead on top of the real travel animation's own
            # first frames below (see intro_card_hold_frames/
            # intro_card_exit_frames), so the card is still genuinely
            # visible while the route is already moving, not fully gone
            # before any motion starts.
            intro_seg_card = None
            intro_card_hold_frames = 0
            intro_card_exit_frames = 0
            intro_card_slide_distance = 0.0
            if show_segment_summary:
                intro_seg_card = self.graphics.create_leg_summary_bar(
                    frame_width=w,
                    distance_km=res_data.get("distance_km", 0.0),
                    duration_seconds=seg_real_duration,
                    mode=res_mode,
                    from_label=leg_from_label,
                    to_label=leg_to_label,
                )
                self._play_leg_summary_card(
                    video, route_preview_frame, intro_seg_card, fps, fade_sec, clip_hold_sec,
                    margin=0, play_exit=False, play_hold=False,
                )
                fade_frames_n = max(1, int(fade_sec * fps))
                intro_card_hold_frames = max(0, int(clip_hold_sec * fps) - fade_frames_n)
                intro_card_exit_frames = fade_frames_n
                intro_card_slide_distance = intro_seg_card.shape[0] + 40
                self.last_frame = route_preview_frame

            path_idx = 0
            prev_cx, prev_cy = None, None
            smoothed_angle = self._initial_heading(res_smooth_path)
            ended_at_destination = False
            summary_shown_inline = False
            arrival_hold_seconds = max(
                1.0, min(2.0, float(self.post_arrival_hold_seconds))
            )

            for current_frame in range(total_frames):
                is_paused = is_paused_per_frame[current_frame]
                just_arrived = False

                if not is_paused and path_idx < len(res_smooth_path) - 1:
                    path_idx += 1
                    if path_idx == len(res_smooth_path) - 1:
                        just_arrived = True

                if is_video and not is_paused:
                    ret, vid_frame = cap.read()
                    if ret:
                        if vid_frame.shape[0] != h or vid_frame.shape[1] != w:
                            vid_frame = cv2.resize(vid_frame, (w, h))
                        current_bg = vid_frame
                        if show_map_border:
                            self.graphics.draw_frame_border(current_bg)
                        if self.config.get("show_compass", True):
                            self.graphics.draw_compass(current_bg)

                p = res_smooth_path[path_idx]
                frame = current_bg.copy()
                current_chunk_px = res_smooth_path[: path_idx + 1]

                if len(current_chunk_px) > 1:
                    cx, cy = int(current_chunk_px[-1][0]), int(current_chunk_px[-1][1])
                else:
                    cx, cy = int(p[0]), int(p[1])

                if not is_video:
                    if len(current_chunk_px) > 1:
                        cv2.polylines(
                            frame,
                            [current_chunk_px.astype(np.int32)],
                            False,
                            self.graphics.line_color,
                            self.graphics.line_thickness,
                            cv2.LINE_AA,
                        )

                    for x, y, lbl in res_named:
                        sprite, anchor = res_landmark_sprites[lbl]
                        self.graphics.blit_sprite(frame, sprite, anchor, x, y)

                    for marker_pin in mid_marker_pins:
                        self._draw_pin(frame, marker_pin, total_wp)

                    smoothed_angle = self._smoothed_heading(
                        smoothed_angle, cx, cy, prev_cx, prev_cy
                    )

                    self.graphics.draw_transport_icon(
                        frame, cx, cy, current_frame, smoothed_angle, mode=res_mode
                    )
                    if res_points:
                        # Same resolved label/color as the intro beat
                        # above (start_pin_label/end_pin_label) — this
                        # leg's own departure/arrival aren't necessarily
                        # the trip's true start/end.
                        self.graphics.draw_marker(
                            frame,
                            int(res_points[0][0]),
                            int(res_points[0][1]),
                            number=start_pin_label,
                            color=start_pin_color,
                        )
                        self.graphics.draw_marker(
                            frame,
                            int(res_points[-1][0]),
                            int(res_points[-1][1]),
                            number=end_pin_label,
                            color=end_pin_color,
                        )

                for popup in active_res_popups:
                    if popup["data"]["triggered"]:
                        continue
                    # The departure pin's popup was already shown in the
                    # intro beat before the animation started — without
                    # this, the traveler starting right on top of it
                    # triggers it again within the first few frames (it's
                    # well inside the trigger radius from frame 1), ending
                    # the clip almost immediately instead of animating to
                    # the actual destination.
                    if popup["index"] == 0:
                        continue
                    near_segment = (
                        prev_cx is not None
                        and prev_cy is not None
                        and RouteGeometryProcessor.point_to_segment_distance(
                            popup["x"], popup["y"], prev_cx, prev_cy, cx, cy
                        )
                        < (
                            self.graphics.marker_radius
                            + self.trigger_radius_padding["waypoint"]
                        )
                    )
                    if near_segment or just_arrived:
                        popup["data"]["triggered"] = True
                        # Hold plain on the arrival frame for a beat before
                        # any fade/scale transition starts — without this,
                        # the fullscreen scale-up (or the cinematic-pause
                        # fade) kicked in the instant the traveler reached
                        # the pin, reading as an abrupt cut rather than
                        # "arrived, then transitioning".
                        for _ in range(max(1, int(arrival_hold_seconds * fps))):
                            video.write(frame)

                        # Show the segment summary (this leg's own travel
                        # mode, distance, and time spent) on the plain
                        # arrival frame first, hold it, then fade it back
                        # off — BEFORE the popup/fullscreen transition, not
                        # composited onto the destination photo afterward.
                        if show_segment_summary:
                            summary_shown_inline = True
                            seg_card = self.graphics.create_leg_summary_bar(
                                frame_width=w,
                                distance_km=res_data.get("distance_km", 0.0),
                                duration_seconds=seg_real_duration,
                                mode=res_mode,
                                from_label=leg_from_label,
                                to_label=leg_to_label,
                            )
                            self._play_leg_summary_card(
                                video, frame, seg_card, fps, fade_sec, clip_hold_sec,
                                margin=0,
                            )

                        # Every arrival now transitions the same way —
                        # scale-up-with-blur straight to fullscreen, then
                        # cut — regardless of this waypoint's own
                        # image_display setting. The old "box" style
                        # (blurred-background cinematic pause + fade) is
                        # gone; only the freeze_seconds duration differs.
                        arrival_popup = {
                            **popup,
                            "data": {
                                **popup["data"],
                                "freeze_seconds": arrival_hold_seconds,
                            },
                        }
                        end_frame, _ = self.graphics.play_fullscreen_popup_sequence(
                            video=video,
                            base_frame=frame,
                            popup_info=arrival_popup,
                            fps=fps,
                            transition_cfg=self.transition_cfg,
                            exit_frame=frame,
                        )
                        self.last_frame = end_frame
                        ended_at_destination = True

                if not ended_at_destination:
                    # Intro card's hold, then exit — see
                    # intro_card_hold_frames/intro_card_exit_frames above
                    # — composited on top of these real, already-moving
                    # animation frames instead of a static pre-roll, so
                    # the card is still visibly up while the route
                    # animation plays, not fully gone before any motion.
                    intro_window = intro_card_hold_frames + intro_card_exit_frames
                    if intro_seg_card is not None and current_frame < intro_window:
                        if current_frame < intro_card_hold_frames:
                            alpha, slide = 1.0, 0.0
                        else:
                            t = (current_frame - intro_card_hold_frames + 1) / intro_card_exit_frames
                            eased = 1 - (1 - t) ** 3
                            alpha, slide = 1.0 - t, intro_card_slide_distance * eased
                        frame = self.graphics.composite_card_on_frame(
                            frame, intro_seg_card, alpha=alpha, margin=0,
                            slide_offset_y=slide,
                        )
                    video.write(frame)
                    self.last_frame = frame
                prev_cx, prev_cy = cx, cy
                if ended_at_destination:
                    break

            if not ended_at_destination:
                for _ in range(int(arrival_hold_seconds * fps)):
                    video.write(self.last_frame)

            # Fallback for a leg whose destination has no popup at all (so
            # the block above never ran) — same summary card, shown once
            # at the very end instead of before a transition that doesn't
            # happen here.
            if show_segment_summary and not summary_shown_inline:
                seg_card = self.graphics.create_leg_summary_bar(
                    frame_width=w,
                    distance_km=res_data.get("distance_km", 0.0),
                    duration_seconds=seg_real_duration,
                    mode=res_mode,
                    from_label=leg_from_label,
                    to_label=leg_to_label,
                )
                self._play_leg_summary_card(
                    video, self.last_frame, seg_card, fps, fade_sec, clip_hold_sec,
                    play_exit=False, margin=0,
                )

            output_paths.append(video.release(str(self.out_dir / chunk_filename)))
            if cap:
                cap.release()

        tracker.clear()
        return output_paths
