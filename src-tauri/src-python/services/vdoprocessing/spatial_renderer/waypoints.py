"""The per-residential-leg (waypoint chunk) video render entry point."""

import math
from typing import Dict, List

import cv2
import numpy as np

from services.mapfetcher.mapfetcher import MapFetcher
from services.mapfetcher.mapgeometry import RouteGeometryProcessor
from services.vdoprocessing.vdoexporter import VideoExporter


class _WaypointRenderMixin:
    def render_waypoints(self, res_sequence: List[Dict], fps: int) -> List[str]:
        output_paths = []
        show_segment_summary = self.config.get("show_segment_summary", True)
        fade_sec = self.config.get("summary_fade", 0.5)
        clip_hold_sec = self.config.get("clip_summary_hold", 2.0)
        job_waypoints = self._get_job_waypoints()

        for i, res_data in enumerate(res_sequence):
            bg_path = res_data["img_path"]

            is_video = (
                str(bg_path).lower().endswith((".mp4", ".webm", ".avi", ".mov", ".mkv"))
            )
            if is_video:
                cap = cv2.VideoCapture(str(bg_path))
                ret, current_bg = cap.read()
                if not ret:
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
            chunk_filename = f"02_waypoint_{i + 1:02d}_{safe_suffix}.mp4"

            video = VideoExporter(str(self.out_dir / chunk_filename), w, h, fps)

            # Intro beat: show the departure and arrival pins (each with a
            # leader-lined popup card, when they have a photo) together on
            # the still, zoomed-in leg map before the route animates —
            # mirrors render_overview()'s "preview every stop up front"
            # intro, scoped to this leg's own start/end.
            waypoint_intro_freeze = float(self.config.get("waypoint_intro_freeze", 2.0))
            if waypoint_intro_freeze > 0 and len(res_points) >= 2:
                intro_frame = current_bg.copy()
                end_idx = len(res_points) - 1
                start_wp = {
                    "x": res_points[0][0],
                    "y": res_points[0][1],
                    "index": 0,
                    "label": res_labels[0] if res_labels else "",
                    "data": res_popups[0] or {},
                }
                end_wp = {
                    "x": res_points[-1][0],
                    "y": res_points[-1][1],
                    "index": end_idx,
                    "label": res_labels[-1] if res_labels else "",
                    "data": res_popups[-1] or {},
                }
                self._draw_pin(intro_frame, start_wp, 1, len(res_points))
                self._draw_pin(intro_frame, end_wp, 2, len(res_points))
                for wp in (start_wp, end_wp):
                    if wp["data"].get("popup_image"):
                        popup_card = dict(wp)
                        popup_card["hud_corner"] = None
                        popup_card["draw_leader_line"] = True
                        intro_frame = self.graphics.render_popup_box(intro_frame, popup_card)
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

                    smoothed_angle = self._smoothed_heading(
                        smoothed_angle, cx, cy, prev_cx, prev_cy
                    )

                    self.graphics.draw_transport_icon(
                        frame, cx, cy, current_frame, smoothed_angle, mode=res_mode
                    )
                    if res_points:
                        self.graphics.draw_marker(
                            frame,
                            int(res_points[0][0]),
                            int(res_points[0][1]),
                            number="S",
                            color=self._START_PIN_COLOR,
                        )
                        self.graphics.draw_marker(
                            frame,
                            int(res_points[-1][0]),
                            int(res_points[-1][1]),
                            number="E",
                            color=self._END_PIN_COLOR,
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
                            seg_card = self.graphics.create_summary_card(
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
                seg_card = self.graphics.create_summary_card(
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

        return output_paths
