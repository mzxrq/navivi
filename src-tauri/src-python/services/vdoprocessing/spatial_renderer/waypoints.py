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

            res_points = res_data["points"]
            res_labels = res_data["labels"]
            res_popups = res_data.get("popups", [None] * len(res_points))
            res_mode = str(res_data.get("mode", "walking")).lower()

            total_duration = res_data.get(
                "segment_duration", self.config.get("res_duration", 12.0)
            )
            travel_duration = res_data.get("travel_duration", total_duration)
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
                filtered_res, max(2, int(actual_travel_seconds * fps)), ease=True
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
            path_idx = 0
            prev_cx, prev_cy = None, None
            smoothed_angle = 0.0

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

                for popup in active_res_popups:
                    if popup["data"]["triggered"]:
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
                        if popup["data"].get("image_display") == "fullscreen":
                            self.graphics.play_fullscreen_popup_sequence(
                                video=video,
                                base_frame=frame,
                                popup_info=popup,
                                fps=fps,
                                transition_cfg=self.transition_cfg,
                                exit_frame=frame,
                            )
                        else:
                            total_f = int(popup["data"]["freeze_seconds"] * fps)
                            fade_f = min(int(0.5 * fps), total_f // 3)
                            cinematic_frame = self.graphics.render_cinematic_pause(
                                frame, popup
                            )
                            self.graphics.write_fade_clip(
                                video, frame, cinematic_frame, total_f, fade_f
                            )

                video.write(frame)
                self.last_frame = frame
                prev_cx, prev_cy = cx, cy

            for _ in range(int(self.post_arrival_hold_seconds * fps)):
                video.write(self.last_frame)

            if show_segment_summary:
                seg_card = self.graphics.create_summary_card(
                    distance_km=res_data.get("distance_km", 0.0),
                    duration_seconds=res_data.get(
                        "real_duration_seconds", total_duration
                    ),
                    card_size=(480, 110),
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
