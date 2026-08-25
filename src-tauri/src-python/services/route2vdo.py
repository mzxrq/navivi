"""
Route to Video Animator (route2vdo.py)
---------------------------------------------------------------------------
turns a pixel-space route into an animated MP4 video.
Imports Core Graphics and Video Exporter from video_engine.py.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import cv2
import numpy as np

from services.mapfetcher import MapFetcher
from services.video_engine import MathUtils, VideoExporter, GraphicsEngine
from services.logger import setup_logger

# Logging configuration
logger = setup_logger("RouteAnimator")


# [Core] RouteAnimator Class
class RouteAnimator:
    """Orchestrates the entire animation pipeline (Overview, Waypoints, Summary)."""

    # [Config] Initialize with configuration dictionary
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.graphics = GraphicsEngine(
            line_color=config.get("line_color", (0, 200, 255)),
            line_thickness=config.get("line_thickness", 10),
            marker_color=config.get("marker_color", (0, 0, 255)),
            marker_radius=config.get("marker_radius", 18),
        )
        self.out_dir = Path(config.get("output_dir", ""))
        self.out_dir.mkdir(parents=True, exist_ok=True)

    # [IO] Load route data from a JSON file, returning points, labels, popups, and settings
    def load_route_data(self, json_path: str) -> Tuple[List, List, List, Dict]:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            route_data, settings = data, {}
        else:
            route_data = data.get("route", data.get("points", []))
            settings = data.get("settings", {})

        points, labels, popups = [], [], []
        for item in route_data:
            if isinstance(item, (list, tuple)):
                points.append([float(item[0]), float(item[1])])
                labels.append(None)
                popups.append(None)
            elif isinstance(item, dict):
                points.append([float(item["x"]), float(item["y"])])
                labels.append(item.get("label"))
                if "freeze_seconds" in item or "popup_image" in item:
                    popups.append(
                        {
                            "freeze_seconds": float(item.get("freeze_seconds", 2.0)),
                            "popup_image": item.get("popup_image"),
                            "triggered": False,
                        }
                    )
                else:
                    popups.append(None)
            else:
                raise ValueError(f"Unknown point format: {item}")

        return points, labels, popups, settings

    # [Core] Render the entire animation
    def render(
        self,
        img_path: str,
        points: List,
        labels: List,
        popups: List,
        res_sequence: Optional[List] = None,
        summary: Optional[Dict] = None,
    ) -> List[str]:

        base_img = self.graphics.read_image_safe(img_path)
        if base_img is None:
            logger.error(f"Cannot read: {img_path}")
            raise FileNotFoundError(f"Cannot read: {img_path}")

        fps = self.config.get("fps", 30)
        output_paths = []
        self.last_frame = base_img.copy()

        # PHASE 1 & 2: Overview, Popups & Total Summary
        overview_path = self._render_overview(
            base_img, points, labels, popups, fps, summary=summary
        )
        if overview_path:
            output_paths.append(overview_path)

        # PHASE 3: Residential Waypoint Segments (Already has per-leg summaries built-in)
        if res_sequence:
            res_paths = self._render_waypoints(res_sequence, fps)
            output_paths.extend(res_paths)

        return output_paths

    # [Animation/Util] Render the overview animation with popups and optional summary card
    def _draw_prioritized_sprites(
        self, target_frame: np.ndarray, items_to_draw: List[Dict], sprites_dict: Dict
    ):
        """Draws sprites with collision detection, prioritizing intermediate waypoints."""
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

    # [Animation/Util] Render the overview animation with popups and optional summary card
    def _render_overview(
        self,
        base_img: np.ndarray,
        points: List,
        labels: List,
        popups: List,
        fps: int,
        summary: Optional[Dict] = None,
    ) -> str:
        h, w = base_img.shape[:2]
        duration = self.config.get("duration", 30.0)
        num_frames = max(10, int(duration * fps))
        self._total_points = len(points)

        named = [
            (int(points[i][0]), int(points[i][1]), labels[i])
            for i in range(len(points))
            if MathUtils.is_real_label(labels[i])
        ]
        landmark_sprites = {
            lbl: self.graphics.prebake_landmark_sprite(lbl) for _, _, lbl in named
        }
        smooth_path = MapFetcher.get_smooth_path(points, num_frames, ease=True)

        active_popups = [
            {
                "x": points[i][0],
                "y": points[i][1],
                "data": popups[i],
                "label": labels[i],
                "index": i,
            }
            for i in range(len(points))
            if popups and popups[i] is not None
        ]

        video = VideoExporter(str(self.out_dir / "01_overview.mp4"), w, h, fps)
        print(f" Rendering Phase 1: Big Picture ({duration}s)")

        # STEP 1: Intro (Start & Stop Popups)
        intro_frame = base_img.copy()
        start_stop_popups = [
            p for p in active_popups if p["index"] == 0 or p["index"] == len(points) - 1
        ]

        if start_stop_popups:
            for sp in start_stop_popups:
                sp["data"]["triggered"] = True
                intro_frame = self.graphics.render_popup_box(intro_frame, sp)
            self._draw_prioritized_sprites(
                intro_frame, start_stop_popups, landmark_sprites
            )
            for _ in range(int(2.5 * fps)):
                video.write(intro_frame)

        # STEP 2: Animate Route
        path_history = []
        for p in smooth_path:
            frame = base_img.copy()
            path_history.append((int(p[0]), int(p[1])))
            self.graphics.draw_path(frame, path_history)

            cx, cy = path_history[-1]
            px, py = path_history[-2] if len(path_history) > 1 else path_history[-1]

            # Popup triggers
            for popup in active_popups:
                if not popup["data"]["triggered"]:
                    trigger_radius = self.graphics.marker_radius + 6.0
                    if (
                        MathUtils.point_to_segment_distance(
                            popup["x"], popup["y"], px, py, cx, cy
                        )
                        < trigger_radius
                    ):
                        popup["data"]["triggered"] = True
                        freeze_frame = self.graphics.render_popup_box(frame, popup)
                        trig_popups = [
                            ap for ap in active_popups if ap["data"]["triggered"]
                        ]
                        self._draw_prioritized_sprites(
                            freeze_frame, trig_popups, landmark_sprites
                        )
                        for _ in range(int(popup["data"]["freeze_seconds"] * fps)):
                            video.write(freeze_frame)

            trig_popups = [ap for ap in active_popups if ap["data"]["triggered"]]
            self._draw_prioritized_sprites(frame, trig_popups, landmark_sprites)
            self.graphics.draw_marker(frame, cx, cy)

            self.last_frame = frame
            video.write(frame)

        # Pause at the end
        pause_seconds = self.config.get("pause", 2.0)
        for _ in range(int(pause_seconds * fps)):
            video.write(self.last_frame)

        # Reset popups for future phases
        for p in popups:
            if p:
                p["triggered"] = False

        # STEP 3: Summary Card or Pause
        if summary:
            print("Rendering Summary Card directly onto Overview")
            card = self.graphics.create_summary_card(
                distance_km=summary.get("total_distance_km", 0.0),
                duration_seconds=summary.get("total_duration_seconds", 0.0),
            )
            fade_sec = self.config.get("summary_fade", 0.5)
            hold_sec = self.config.get("summary_hold", 4.0)

            fade_frames = max(1, int(fade_sec * fps))
            hold_frames = max(0, int(hold_sec * fps) - fade_frames)

            # Fade the card in
            for i in range(fade_frames):
                video.write(
                    self.graphics.composite_card_on_frame(
                        self.last_frame, card, alpha=(i + 1) / fade_frames
                    )
                )

            # Hold the card on screen
            held_frame = self.graphics.composite_card_on_frame(
                self.last_frame, card, alpha=1.0
            )
            for _ in range(hold_frames):
                video.write(held_frame)
        else:
            # Fallback pause if no summary is provided
            pause_seconds = self.config.get("pause", 2.0)
            for _ in range(int(pause_seconds * fps)):
                video.write(self.last_frame)

        # Reset popups for future phases
        for p in popups:
            if p:
                p["triggered"] = False

        return video.release(str(self.out_dir / "01_overview.mp4"))

    # [Animation/Util] Render residential waypoint segments with per-leg summaries
    def _render_waypoints(self, res_sequence: List[Dict], fps: int) -> List[str]:
        output_paths = []

        show_segment_summary = self.config.get("show_segment_summary", True)
        fade_sec = self.config.get("summary_fade", 0.5)
        clip_hold_sec = self.config.get("clip_summary_hold", 2.0)

        for i, res_data in enumerate(res_sequence):
            print(f"Rendering Residential Map {i + 1}/{len(res_sequence)}")
            res_img = self.graphics.read_image_safe(res_data["img_path"])
            if res_img is None:
                continue

            h, w = res_img.shape[:2]
            res_points = res_data["points"]
            res_labels = res_data["labels"]
            res_popups = res_data.get("popups", [None] * len(res_points))

            total_duration = res_data.get(
                "segment_duration", self.config.get("res_duration", 12.0)
            )
            travel_duration = res_data.get("travel_duration", total_duration)
            pauses = res_data.get("pauses", [])

            total_frames = max(10, int(total_duration * fps))

            is_paused_per_frame = []
            for current_frame in range(total_frames):
                current_time_sec = current_frame / fps
                is_p = (
                    any(p["start"] <= current_time_sec <= p["end"] for p in pauses)
                    if pauses
                    else False
                )
                is_paused_per_frame.append(is_p)

            total_pause_seconds = sum(p["duration"] for p in pauses) if pauses else 0.0
            actual_travel_seconds = max(1.0, travel_duration - total_pause_seconds)
            movement_frames = max(2, int(actual_travel_seconds * fps))

            res_smooth_path = MapFetcher.get_smooth_path(
                res_points, movement_frames, ease=True
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

            res_landmark_sprites = {
                lbl: self.graphics.prebake_landmark_sprite(lbl)
                for _, _, lbl in res_named
            }

            named_labels = [lbl for _, _, lbl in res_named]
            raw_suffix = named_labels[-1] if named_labels else f"leg{i + 1}"
            safe_suffix = (
                "".join(
                    c for c in str(raw_suffix) if c.isalnum() or c in (" ", "_", "-")
                )
                .strip()
                .replace(" ", "_")
                or f"leg{i + 1}"
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

                p = res_smooth_path[path_idx]
                frame = res_img.copy()
                current_chunk_px = res_smooth_path[: path_idx + 1]

                if len(current_chunk_px) > 1:
                    cv2.polylines(
                        frame,
                        [current_chunk_px.astype(np.int32)],
                        False,
                        self.graphics.line_color,
                        self.graphics.line_thickness,
                        cv2.LINE_AA,
                    )
                    cx, cy = int(current_chunk_px[-1][0]), int(current_chunk_px[-1][1])
                else:
                    cx, cy = int(p[0]), int(p[1])

                for x, y, lbl in res_named:
                    sprite, anchor = res_landmark_sprites[lbl]
                    self.graphics.blit_sprite(frame, sprite, anchor, x, y)

                self.graphics.draw_marker(frame, cx, cy)

                trigger_radius = self.graphics.marker_radius + 8.0
                for popup in active_res_popups:
                    if popup["data"]["triggered"]:
                        continue

                    near_segment = (
                        prev_cx is not None
                        and prev_cy is not None
                        and MathUtils.point_to_segment_distance(
                            popup["x"], popup["y"], prev_cx, prev_cy, cx, cy
                        )
                        < trigger_radius
                    )

                    if near_segment or just_arrived:
                        popup["data"]["triggered"] = True
                        freeze_frame = self.graphics.render_popup_box(frame, popup)
                        for _ in range(int(popup["data"]["freeze_seconds"] * fps)):
                            video.write(freeze_frame)

                video.write(frame)
                self.last_frame = frame
                prev_cx, prev_cy = cx, cy

            for _ in range(fps):
                video.write(self.last_frame)

            plain_frame = self.last_frame
            if show_segment_summary:
                seg_card = self.graphics.create_summary_card(
                    distance_km=res_data.get("distance_km", 0.0),
                    duration_seconds=res_data.get(
                        "real_duration_seconds", total_duration
                    ),
                )

                fade_frames = max(1, int(fade_sec * fps))
                hold_frames = max(0, int(clip_hold_sec * fps) - fade_frames)

                for f in range(fade_frames):
                    video.write(
                        self.graphics.composite_card_on_frame(
                            plain_frame, seg_card, alpha=(f + 1) / fade_frames
                        )
                    )

                held_frame = self.graphics.composite_card_on_frame(
                    plain_frame, seg_card, alpha=1.0
                )
                for _ in range(hold_frames):
                    video.write(held_frame)

            output_paths.append(video.release(str(self.out_dir / chunk_filename)))

        return output_paths

    # [Animation/Util] Render the summary card with fade-in and hold duration
    def _render_summary(self, summary: Dict, fps: int) -> str:
        print("Rendering Summary Card")
        h, w = self.last_frame.shape[:2]
        video = VideoExporter(str(self.out_dir / "03_summary.mp4"), w, h, fps)

        card = self.graphics.create_summary_card(
            distance_km=summary.get("total_distance_km", 0.0),
            duration_seconds=summary.get("total_duration_seconds", 0.0),
        )

        fade_sec = self.config.get("summary_fade", 0.5)
        hold_sec = self.config.get("summary_hold", 4.0)

        fade_frames = max(1, int(fade_sec * fps))
        hold_frames = max(0, int(hold_sec * fps) - fade_frames)

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

        return video.release(str(self.out_dir / "03_summary.mp4"))


# [Core] Command-line interface for RouteAnimator
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--map", required=True)
    parser.add_argument("--route", required=True)
    parser.add_argument("--output", default="data\\outputs\\video")
    parser.add_argument("--duration", type=float, default=None)
    parser.add_argument("--fps", type=int, default=None)
    parser.add_argument("--thickness", type=int, default=None)
    parser.add_argument("--radius", type=int, default=None)
    parser.add_argument("--res-map", default=None)
    parser.add_argument("--res-route", default=None)
    parser.add_argument("--res-duration", type=float, default=12.0)
    parser.add_argument("--pause", type=float, default=2.0)
    parser.add_argument("--summary-json", default=None)
    parser.add_argument("--summary-hold", type=float, default=4.0)
    parser.add_argument("--summary-fade", type=float, default=0.5)

    args = parser.parse_args()

    # Build Configuration Object
    config = {
        "output_dir": args.output,
        "pause": args.pause,
        "summary_hold": args.summary_hold,
        "summary_fade": args.summary_fade,
        "res_duration": args.res_duration,
    }

    # Initialize Animator
    animator = RouteAnimator(config)
    points, labels, popups, settings = animator.load_route_data(args.route)

    # Overwrite configs with file settings if CLI args not provided
    animator.config["fps"] = args.fps or settings.get("fps", 30)
    animator.config["duration"] = args.duration or settings.get("duration_seconds", 8)
    animator.graphics.line_thickness = args.thickness or settings.get(
        "line_thickness", 10
    )
    animator.graphics.marker_radius = args.radius or settings.get("marker_radius", 18)

    res_sequence = None
    if args.res_route and args.res_map:
        res_points, res_labels, _, _ = animator.load_route_data(args.res_route)
        res_sequence = [
            {"img_path": args.res_map, "points": res_points, "labels": res_labels}
        ]

    summary = (
        json.load(open(args.summary_json, "r", encoding="utf-8"))
        if args.summary_json
        else None
    )

    # Run the Pipeline
    output_files = animator.render(
        img_path=args.map,
        points=points,
        labels=labels,
        popups=popups,
        res_sequence=res_sequence,
        summary=summary,
    )

    print(f"✅ Rendered {len(output_files)} file(s):")
    for f in output_files:
        print(f"   {f}")


if __name__ == "__main__":
    main()

Route2VDO = RouteAnimator
