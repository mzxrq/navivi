"""The per-residential-leg (waypoint chunk) video render entry point."""

import math
from typing import Dict, List

import cv2
import numpy as np

from services.mapfetcher.mapfetcher import MapFetcher
from services.mapfetcher.mapgeometry import RouteGeometryProcessor
from services.vdoprocessing.vdoexporter import VideoExporter


class _WaypointRenderMixin:
    def _draw_reference_hud(
        self,
        frame: np.ndarray,
        destination_label: str,
        destination_image: str,
    ) -> None:
        """Draw the compact destination banner and thumbnail used by 2D legs."""
        h, w = frame.shape[:2]
        label = str(destination_label or "Destination")
        font_scale = max(0.55, self.graphics.font_size / 32.0)
        text_size, _ = cv2.getTextSize(label, self.graphics.font_cv, font_scale, 2)
        pill_w = min(w - 40, max(220, text_size[0] + 90))
        pill_h = 58
        pill_x = (w - pill_w) // 2
        pill_y = 18
        cv2.rectangle(
            frame,
            (pill_x + pill_h // 2, pill_y),
            (pill_x + pill_w - pill_h // 2, pill_y + pill_h),
            (35, 55, 225),
            -1,
            cv2.LINE_AA,
        )
        cv2.circle(frame, (pill_x + pill_h // 2, pill_y + pill_h // 2), pill_h // 2, (35, 55, 225), -1)
        cv2.circle(
            frame,
            (pill_x + pill_w - pill_h // 2, pill_y + pill_h // 2),
            pill_h // 2,
            (35, 55, 225),
            -1,
        )
        cv2.putText(
            frame,
            label,
            (pill_x + (pill_w - text_size[0]) // 2, pill_y + 37),
            self.graphics.font_cv,
            font_scale,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

        if destination_image:
            image = self.graphics.read_image_safe(destination_image)
            if image is not None:
                thumb_w, thumb_h = 112, 76
                image = cv2.resize(image, (thumb_w, thumb_h))
                x, y = 34, 34
                cv2.rectangle(frame, (x - 4, y - 4), (x + thumb_w + 4, y + thumb_h + 4), (255, 255, 255), -1)
                cv2.rectangle(frame, (x - 5, y - 5), (x + thumb_w + 5, y + thumb_h + 5), (35, 55, 225), 2)
                frame[y : y + thumb_h, x : x + thumb_w] = image

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
            destination_popup = next(
                (popup for popup in reversed(res_popups) if popup is not None), None
            )
            destination_label = res_labels[-1] if res_labels else "Destination"
            destination_image = (
                str(destination_popup.get("popup_image"))
                if destination_popup and destination_popup.get("popup_image")
                else ""
            )

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
            ended_at_destination = False
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

                    self._draw_reference_hud(
                        frame, destination_label, destination_image
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
                            fullscreen_popup = {
                                **popup,
                                "data": {
                                    **popup["data"],
                                    # Keep the destination beat short and make
                                    # the fullscreen reveal the clip ending.
                                    "freeze_seconds": arrival_hold_seconds,
                                },
                            }
                            self.graphics.play_fullscreen_popup_sequence(
                                video=video,
                                base_frame=frame,
                                popup_info=fullscreen_popup,
                                fps=fps,
                                transition_cfg=self.transition_cfg,
                                exit_frame=frame,
                            )
                            ended_at_destination = True
                        else:
                            total_f = max(1, int(arrival_hold_seconds * fps))
                            fade_f = min(int(0.25 * fps), total_f // 3)
                            cinematic_frame = self.graphics.render_cinematic_pause(
                                frame, popup
                            )
                            self.graphics.write_fade_clip(
                                video, frame, cinematic_frame, total_f, fade_f
                            )
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

            if ended_at_destination:
                video_path = video.release(str(self.out_dir / chunk_filename))
                output_paths.append(video_path)
                if cap:
                    cap.release()
                continue

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

        return output_paths
