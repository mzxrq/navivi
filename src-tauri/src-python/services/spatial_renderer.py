"""
Spatial Renderer Service (spatial_renderer.py)
---------------------------------------------------------------------------
Handles proximity-based triggering for the legacy overview and waypoint maps.
---------------------------------------------------------------------------
"""

import json
import math
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import cv2
import numpy as np

from services.mapfetcher import MapFetcher
from services.math_util import MathUtils
from services.vdo_exporter import VideoExporter
from services.graphic_engine import GraphicsEngine
from services.logger import setup_logger

logger = setup_logger("SpatialRenderer")


class SpatialRenderer:
    def __init__(self, config: Dict[str, Any], graphics: GraphicsEngine, out_dir: Path):
        self.config = config
        self.graphics = graphics
        self.out_dir = out_dir

        self.trigger_radius_padding = {
            **{"overview": 25, "waypoint": 15},
            **config.get("trigger_radius_padding", {}),
        }
        self.transition_cfg = {
            **{
                "scale_seconds": 0.8,
                "fade_out_seconds": 0.5,
                "hold_ratio_of_freeze": 0.4,
                "min_hold_seconds": 0.5,
                "min_small_hold_seconds": 0.1,
            },
            **config.get("fullscreen_transition", {}),
        }
        self.post_arrival_hold_seconds: float = config.get(
            "post_arrival_hold_seconds", 1.0
        )
        self.last_frame = None

    def _get_job_waypoints(self) -> List[Dict]:
        for p in [self.out_dir] + list(self.out_dir.parents):
            potential_path = p / "job_config.json"
            if potential_path.exists():
                try:
                    with open(potential_path, "r", encoding="utf-8") as f:
                        return json.load(f).get("waypoints", [])
                except Exception:
                    pass
        return []

    def _draw_prioritized_sprites(
        self, target_frame: np.ndarray, items_to_draw: List[Dict], sprites_dict: Dict
    ):
        drawn_boxes = []

        def get_priority(item):
            idx = item.get("index", -1)
            return (
                1 if (idx == 0 or idx == getattr(self, "_total_points", 0) - 1) else 2
            )

        for item in sorted(items_to_draw, key=get_priority, reverse=True):
            lbl = item.get("label")
            if not MathUtils.is_real_label(lbl) or lbl not in sprites_dict:
                continue
            sprite, anchor = sprites_dict[lbl]
            x, y = int(item["x"]), int(item["y"])
            sh, sw = sprite.shape[:2]
            ox, oy = x - anchor[0], y - anchor[1]
            box = (ox, oy, ox + sw, oy + sh)

            if not any(
                not (
                    box[2] <= db[0]
                    or box[0] >= db[2]
                    or box[3] <= db[1]
                    or box[1] >= db[3]
                )
                for db in drawn_boxes
            ):
                self.graphics.blit_sprite(target_frame, sprite, anchor, x, y)
                drawn_boxes.append(box)

    def render_overview(
        self,
        bg_path: str,
        points: List,
        labels: List,
        popups: List,
        fps: int,
        summary: Optional[Dict] = None,
    ) -> str:
        is_video = False

        if is_video:
            cap = cv2.VideoCapture(str(bg_path))
            ret, current_bg = cap.read()
            if not ret:
                raise FileNotFoundError(f"Cannot read video frames from: {bg_path}")
        else:
            current_bg = self.graphics.read_image_safe(str(bg_path))
            if current_bg is None:
                raise FileNotFoundError(f"Cannot read background image: {bg_path}")
            cap = None

        h, w = current_bg.shape[:2]
        if h % 2 != 0 or w % 2 != 0:
            h, w = h - (h % 2), w - (w % 2)
            current_bg = cv2.resize(current_bg, (w, h))

        duration = self.config.get("duration", 30.0)
        num_frames = max(10, int(duration * fps))
        self._total_points = len(points)

        start_label, end_label = "開始", "終点"
        for p in [self.out_dir] + list(self.out_dir.parents):
            potential_path = p / "job_config.json"
            if potential_path.exists():
                try:
                    with open(potential_path, "r", encoding="utf-8") as f:
                        job_data = json.load(f)
                        start_label = job_data.get("start_point", {}).get(
                            "label", start_label
                        )
                        end_label = job_data.get("end_point", {}).get(
                            "label", end_label
                        )
                except Exception:
                    pass
                break

        cleaned_labels = []
        for i, lbl in enumerate(labels):
            if i == 0:
                cleaned_labels.append(start_label)
            elif i == len(points) - 1:
                cleaned_labels.append(end_label)
            else:
                cleaned_labels.append(
                    lbl.replace("Start: ", "")
                    .replace("Stop: ", "")
                    .replace("Start", "")
                    .replace("Stop", "")
                    .strip()
                    if lbl
                    else None
                )

        named = [
            (int(points[i][0]), int(points[i][1]), cleaned_labels[i])
            for i in range(len(points))
            if MathUtils.is_real_label(cleaned_labels[i])
        ]
        landmark_sprites = {
            lbl: self.graphics.prebake_landmark_sprite(lbl) for _, _, lbl in named
        }

        # --- FIX 1: Prevent wild spline curves by filtering clustered GPS points ---
        filtered_points = [points[0]]
        for pt in points[1:]:
            # Keep point only if it's at least 3 pixels away from the last one
            if (
                math.hypot(
                    pt[0] - filtered_points[-1][0], pt[1] - filtered_points[-1][1]
                )
                > 3.0
            ):
                filtered_points.append(pt)
        # Ensure the final destination is always included
        if filtered_points[-1] != points[-1]:
            filtered_points.append(points[-1])

        smooth_path = MapFetcher.get_smooth_path(filtered_points, num_frames, ease=True)

        active_popups = [
            {
                "x": points[i][0],
                "y": points[i][1],
                "data": popups[i],
                "label": cleaned_labels[i],
                "index": i,
            }
            for i in range(len(points))
            if popups and popups[i] is not None
        ]

        job_waypoints = self._get_job_waypoints()
        for i, popup in enumerate(active_popups):
            if i < len(job_waypoints):
                jw = job_waypoints[i]
                if (
                    "image_display" in jw
                    and popup["data"].get("image_display", "box") == "box"
                ):
                    popup["data"]["image_display"] = jw["image_display"]
                if "popup_video" in jw and not popup["data"].get("popup_video"):
                    popup["data"]["popup_video"] = jw["popup_video"]

        logger.info(f"Rendering Overview Map ({duration}s)")
        overview_path = str(self.out_dir / "01_overview.mp4")
        video = VideoExporter(overview_path, w, h, fps)
        baked_popups, triggered_markers = [], []

        intro_frame = current_bg.copy()
        start_popup = next((p for p in active_popups if p["index"] == 0), None)
        stop_popup = next(
            (p for p in active_popups if p["index"] == len(points) - 1), None
        )

        intro_freeze_sec = 3.0
        if start_popup and "freeze_seconds" in start_popup["data"]:
            intro_freeze_sec = float(start_popup["data"]["freeze_seconds"])

        if start_popup:
            temp_sp = start_popup.copy()
            temp_sp["data"] = start_popup["data"].copy()
            temp_sp["data"]["triggered"] = True
            temp_sp["hud_corner"], temp_sp["x"], temp_sp["y"] = (
                "bottom_left",
                start_popup["x"],
                start_popup["y"],
            )
            start_popup["data"]["triggered"] = True
            triggered_markers.append({"x": start_popup["x"], "y": start_popup["y"]})

            if temp_sp["data"].get("image_display") == "fullscreen":
                self.graphics.play_fullscreen_popup_sequence(
                    video=video,
                    base_frame=intro_frame,
                    popup_info=temp_sp,
                    fps=fps,
                    transition_cfg=self.transition_cfg,
                    exit_frame=intro_frame,
                )
            else:
                intro_frame = self.graphics.render_popup_box(intro_frame, temp_sp)
                if not is_video:
                    self.graphics.draw_marker(
                        intro_frame, int(start_popup["x"]), int(start_popup["y"])
                    )
                    start_stop_list = [
                        p for p in [start_popup, stop_popup] if p is not None
                    ]
                    self._draw_prioritized_sprites(
                        intro_frame, start_stop_list, landmark_sprites
                    )
                for _ in range(int(intro_freeze_sec * fps)):
                    video.write(intro_frame)

        path_history = []
        prev_cx, prev_cy = None, None

        for current_frame, p in enumerate(smooth_path):
            if is_video:
                ret, vid_frame = cap.read()
                if ret:
                    if vid_frame.shape[0] != h or vid_frame.shape[1] != w:
                        vid_frame = cv2.resize(vid_frame, (w, h))
                    current_bg = vid_frame

            frame = current_bg.copy()

            if not is_video:
                for tm in triggered_markers:
                    self.graphics.draw_marker(frame, int(tm["x"]), int(tm["y"]))

            surviving_popups = []
            for bp in baked_popups:
                hud_popup = bp["popup"].copy()
                hud_popup["hud_corner"] = "bottom_left"
                frame = self.graphics.render_popup_box(frame, hud_popup)
                bp["frames_left"] -= 1
                if bp["frames_left"] > 0:
                    surviving_popups.append(bp)
            baked_popups = surviving_popups

            path_history.append((int(p[0]), int(p[1])))

            if not is_video:
                self.graphics.draw_path(frame, path_history)

            cx, cy = path_history[-1]
            px, py = path_history[-2] if len(path_history) > 1 else path_history[-1]

            triggered_popup = None
            for popup in active_popups:
                if popup["index"] == 0 or (
                    stop_popup and popup["index"] == stop_popup["index"]
                ):
                    continue
                if not popup["data"]["triggered"]:
                    if MathUtils.point_to_segment_distance(
                        popup["x"], popup["y"], px, py, cx, cy
                    ) < (
                        self.graphics.marker_radius
                        + self.trigger_radius_padding["overview"]
                    ):
                        popup["data"]["triggered"] = True
                        triggered_popup = popup
                        break

            if triggered_popup:
                triggered_markers.append(
                    {"x": triggered_popup["x"], "y": triggered_popup["y"]}
                )

                if triggered_popup["data"].get("image_display") == "fullscreen":
                    self.last_frame, _ = self.graphics.play_fullscreen_popup_sequence(
                        video=video,
                        base_frame=frame,
                        popup_info=triggered_popup,
                        fps=fps,
                        transition_cfg=self.transition_cfg,
                        exit_frame=frame,
                    )
                else:
                    display_seconds = float(
                        triggered_popup["data"].get("freeze_seconds", 4.0)
                    )
                    baked_popups.append(
                        {
                            "popup": triggered_popup,
                            "frames_left": int(display_seconds * fps),
                        }
                    )
                    hud_triggered = triggered_popup.copy()
                    hud_triggered["hud_corner"] = "bottom_left"
                    temp_frame = self.graphics.render_popup_box(frame, hud_triggered)

                    if not is_video:
                        for tm in triggered_markers:
                            self.graphics.draw_marker(
                                temp_frame, int(tm["x"]), int(tm["y"])
                            )
                        trig_popups = [
                            ap for ap in active_popups if ap["data"]["triggered"]
                        ]
                        self._draw_prioritized_sprites(
                            temp_frame, trig_popups, landmark_sprites
                        )
                        self.graphics.draw_marker(temp_frame, cx, cy)

                    self.last_frame = temp_frame

                    for _ in range(int(display_seconds * fps)):
                        video.write(temp_frame)

            else:
                if not is_video:
                    for tm in triggered_markers:
                        self.graphics.draw_marker(frame, int(tm["x"]), int(tm["y"]))
                    trig_popups = [
                        ap for ap in active_popups if ap["data"]["triggered"]
                    ]
                    self._draw_prioritized_sprites(frame, trig_popups, landmark_sprites)

                    angle = 0.0
                    if prev_cx is not None and prev_cy is not None:
                        angle = math.degrees(math.atan2(cy - prev_cy, cx - prev_cx))
                    self.graphics.draw_walking_human(
                        frame, cx, cy, current_frame, angle
                    )

                self.last_frame = frame
                video.write(frame)

            prev_cx, prev_cy = cx, cy

        if stop_popup:
            triggered_markers.append({"x": stop_popup["x"], "y": stop_popup["y"]})
            outro_frame = self.last_frame.copy()
            temp_stop = stop_popup.copy()
            temp_stop["data"] = stop_popup["data"].copy()
            temp_stop["hud_corner"], temp_stop["x"], temp_stop["y"] = (
                "bottom_left",
                stop_popup["x"],
                stop_popup["y"],
            )

            if temp_stop["data"].get("image_display") == "fullscreen":
                self.last_frame, _ = self.graphics.play_fullscreen_popup_sequence(
                    video=video,
                    base_frame=outro_frame,
                    popup_info=temp_stop,
                    fps=fps,
                    transition_cfg=self.transition_cfg,
                    exit_frame=outro_frame,
                )
            else:
                outro_frame = self.graphics.render_popup_box(outro_frame, temp_stop)

                if not is_video:
                    for tm in triggered_markers:
                        self.graphics.draw_marker(
                            outro_frame, int(tm["x"]), int(tm["y"])
                        )
                stop_freeze_sec = float(stop_popup["data"].get("freeze_seconds", 3.0))
                for _ in range(int(stop_freeze_sec * fps)):
                    video.write(outro_frame)
                self.last_frame = outro_frame

        for _ in range(int(self.config.get("pause", 2.0) * fps)):
            video.write(self.last_frame)
        for p in popups:
            if p:
                p["triggered"] = False

        if summary:
            card = self.graphics.create_summary_card(
                distance_km=summary.get("total_distance_km", 0.0),
                duration_seconds=summary.get("total_duration_seconds", 0.0),
            )
            fade_frames = max(1, int(self.config.get("summary_fade", 0.5) * fps))
            hold_frames = max(
                0, int(self.config.get("summary_hold", 4.0) * fps) - fade_frames
            )
            for i in range(fade_frames):
                video.write(
                    self.graphics.composite_card_on_frame(
                        self.last_frame, card, alpha=(i + 1) / fade_frames
                    )
                )
            held_frame = self.graphics.composite_card_on_frame(
                self.last_frame, card, alpha=1.0
            )
            for _ in range(hold_frames):
                video.write(held_frame)
        else:
            for _ in range(int(self.config.get("pause", 2.0) * fps)):
                video.write(self.last_frame)

        if cap:
            cap.release()
        return video.release(overview_path)

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
                if MathUtils.is_real_label(res_labels[j])
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

                    angle = 0.0
                    if prev_cx is not None and prev_cy is not None:
                        angle = math.degrees(math.atan2(cy - prev_cy, cx - prev_cx))

                    self.graphics.draw_walking_human(
                        frame, cx, cy, current_frame, angle
                    )

                for popup in active_res_popups:
                    if popup["data"]["triggered"]:
                        continue
                    near_segment = (
                        prev_cx is not None
                        and prev_cy is not None
                        and MathUtils.point_to_segment_distance(
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
