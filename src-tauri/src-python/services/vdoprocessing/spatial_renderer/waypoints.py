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
        _wp_by_id: Dict[str, Tuple[int, int, bool]] = {}
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
                _wp_by_id[_wp_id] = (_pos, _order, _is_stopby)

        def _resolve_global_waypoint(waypoint_id: Optional[str], label: str):
            """Finds this leg endpoint's real position in the whole
            route's waypoint list and its 1-based visit order — by exact
            "id" match when available (see _wp_by_id above), falling back
            to a fuzzy label match (ambiguous when a label repeats, but
            better than nothing) for older data saved before waypoints
            carried an id. Needed because a leg's OWN first/last point
            (index 0 / len-1 within just that leg) is not the trip's
            actual start/end — using those local indices directly would
            mislabel every leg's arrival pin "E" (and every leg's
            departure pin "S"), not just the true first and last legs of
            the whole route."""
            if waypoint_id and waypoint_id in _wp_by_id:
                return _wp_by_id[waypoint_id]
            if not label:
                return None
            order = 0
            for pos, jw in enumerate(job_waypoints):
                is_stopby = bool(jw.get("isStopBy", False))
                if not is_stopby:
                    order += 1
                jw_lbl = str(jw.get("label", ""))
                if jw_lbl and (jw_lbl in label or label in jw_lbl):
                    return pos, order, is_stopby
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

            res_points = res_data["points"]
            res_labels = res_data["labels"]
            res_popups = res_data.get("popups", [None] * len(res_points))
            res_mode = str(res_data.get("mode", "walking")).lower()

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
            # anything else (pins, popups, animation) is drawn.
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
            start_match = _resolve_global_waypoint(
                res_data.get("start_waypoint_id"), start_label
            )
            end_match = _resolve_global_waypoint(
                res_data.get("end_waypoint_id"), end_label
            )
            total_wp = len(job_waypoints)

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

            # Intro beat: show the departure and arrival pins (each with a
            # leader-lined popup card, when they have a photo) together on
            # the still, zoomed-in leg map before the route animates —
            # mirrors render_overview()'s "preview every stop up front"
            # intro, scoped to this leg's own start/end.
            waypoint_intro_freeze = float(self.config.get("waypoint_intro_freeze", 2.0))
            if waypoint_intro_freeze > 0 and len(res_points) >= 2:
                intro_frame = current_bg.copy()
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
                            seg_card = self.graphics.render_summary_card(
                                distance_km=res_data.get("distance_km", 0.0),
                                duration_seconds=seg_real_duration,
                                mode_breakdown={
                                    res_mode: res_data.get("distance_km", 0.0)
                                },
                                mode_duration={res_mode: seg_real_duration},
                                card_size=(480, 170),
                            )
                            card_fade_frames = max(1, int(fade_sec * fps))
                            for f in range(card_fade_frames):
                                video.write(
                                    self.graphics.composite_card_on_frame(
                                        frame, seg_card, alpha=(f + 1) / card_fade_frames
                                    )
                                )
                            card_frame = self.graphics.composite_card_on_frame(
                                frame, seg_card, alpha=1.0
                            )
                            for _ in range(
                                max(0, int(clip_hold_sec * fps) - card_fade_frames)
                            ):
                                video.write(card_frame)
                            for f in range(card_fade_frames):
                                video.write(
                                    self.graphics.composite_card_on_frame(
                                        frame,
                                        seg_card,
                                        alpha=1.0 - (f + 1) / card_fade_frames,
                                    )
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
                seg_card = self.graphics.render_summary_card(
                    distance_km=res_data.get("distance_km", 0.0),
                    duration_seconds=seg_real_duration,
                    mode_breakdown={res_mode: res_data.get("distance_km", 0.0)},
                    mode_duration={res_mode: seg_real_duration},
                    card_size=(480, 170),
                )
                fade_frames = max(1, int(fade_sec * fps))
                for f in range(fade_frames):
                    video.write(
                        self.graphics.composite_card_on_frame(
                            self.last_frame, seg_card, alpha=(f + 1) / fade_frames
                        )
                    )
                held_frame = self.graphics.composite_card_on_frame(
                    self.last_frame, seg_card, alpha=1.0
                )
                for _ in range(max(0, int(clip_hold_sec * fps) - fade_frames)):
                    video.write(held_frame)

            output_paths.append(video.release(str(self.out_dir / chunk_filename)))
            if cap:
                cap.release()

        tracker.clear()
        return output_paths
