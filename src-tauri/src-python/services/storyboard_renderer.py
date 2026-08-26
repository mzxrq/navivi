"""
Storyboard Renderer Service (storyboard_renderer.py)
---------------------------------------------------------------------------
Handles JSON-driven atomic clip generation and NLE timeline concatenation.

[REFACTOR NOTE]
`_render_storyboard_popup`'s fullscreen branch now delegates to
`GraphicsEngine.play_fullscreen_popup_sequence()` instead of duplicating
the freeze/scale/broll/hold/fade sequence inline. The previously
duplicated `_compute_fullscreen_hold_times` static method has been
removed in favor of `GraphicsEngine.compute_fullscreen_hold_times`.

One deliberate behavior is preserved and now explicitly documented
rather than silently baked into copy-pasted code: in the ORIGINAL
implementation, `self.last_frame` was updated after a static-image
fullscreen popup (`self.last_frame = freeze_frame`) but was NOT updated
after a B-roll fullscreen popup finished playing. That means a
static-image fullscreen popup persists into the background of whatever
`draw_route` action comes next, while a B-roll fullscreen popup does
not — the map animation resumes from the frame as it stood before the
B-roll played. This asymmetry looks intentional (a full-motion B-roll
clip is a one-off cutaway; a static image popup is closer to a
"stamped" annotation on the map) so it is preserved exactly, just made
visible via the `used_broll` flag instead of being an invisible
side-effect of duplicated code.
---------------------------------------------------------------------------
"""

import os
import cv2
import numpy as np
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from services.mapfetcher import MapFetcher
from services.math_util import MathUtils
from services.vdo_exporter import VideoExporter
from services.graphic_engine import GraphicsEngine
from services.logger import setup_logger

logger = setup_logger("StoryboardRenderer")


class StoryboardRenderer:
    """Renders atomic video clips based on explicit JSON storyboard actions."""

    def __init__(self, config: Dict[str, Any], graphics: GraphicsEngine, out_dir: Path):
        self.config = config
        self.graphics = graphics
        self.out_dir = out_dir

        self.transition_cfg: Dict[str, float] = {
            **{
                "scale_seconds": 0.8,
                "fade_out_seconds": 0.5,
                "hold_ratio_of_freeze": 0.4,
                "min_hold_seconds": 0.5,
                "min_small_hold_seconds": 0.1,
            },
            **config.get("fullscreen_transition", {}),
        }
        self.last_frame = None

        # [NEW] Explicit, in-memory record of every atomic clip produced by
        # the most recent render_storyboard() call, in action order. This
        # replaces the old (broken) pattern of re-discovering clip paths by
        # globbing the output directory for a filename convention that
        # never actually matched what this class writes to disk. Consumers
        # (e.g. RouteAnimator) should read this instead of touching the
        # filesystem — it's a direct, race-free, always-in-sync reference.
        self.last_timeline_tracks: List[Dict[str, str]] = []

    @staticmethod
    def _validate_storyboard(storyboard: Dict[str, Any]) -> None:
        actions = storyboard.get("actions")
        if not isinstance(actions, list) or not actions:
            raise ValueError("Storyboard must contain a non-empty 'actions' list.")

        required_fields = {
            "draw_route": ("from_point_index", "to_point_index"),
            "popup_image": ("point_index", "image"),
            "hold": (),
            "summary_card": (),
        }
        for i, action in enumerate(actions):
            a_type = action.get("type")
            if a_type not in required_fields:
                raise ValueError(
                    f"Storyboard action #{i} has unknown type: {a_type!r}."
                )
            missing = [f for f in required_fields[a_type] if f not in action]
            if missing:
                raise ValueError(
                    f"Storyboard action #{i} (type={a_type!r}) is missing required field(s): {missing}"
                )

    def _render_storyboard_popup(
        self,
        action: Dict[str, Any],
        points: List,
        labels: List,
        fps: int,
        start_new_clip,
    ) -> Dict[str, str]:
        idx = action.get("point_index", action.get("waypoint_index"))
        if idx is None or not (0 <= idx < len(points)):
            raise ValueError(
                f"popup_image action '{action.get('id', '?')}' needs a valid point_index."
            )

        x, y = points[idx]
        label = action.get("label") or (labels[idx] if idx < len(labels) else None)
        duration = float(action.get("duration_seconds", 3.0))
        display = action.get("display", "box")

        popup_info = {
            "x": x,
            "y": y,
            "label": label,
            "data": {
                "freeze_seconds": duration,
                "popup_image": action["image"],
                "image_display": display,
                "triggered": True,
            },
        }

        # 💡 Rescue video tag if it exists in the action
        if "popup_video" in action:
            popup_info["data"]["popup_video"] = action["popup_video"]

        video, clip_path, clip_id = start_new_clip("popup", action.get("id", "popup"))

        if display == "fullscreen":
            # [CONSOLIDATED] See GraphicsEngine.play_fullscreen_popup_sequence
            # and the module-level docstring above for why `used_broll`
            # gates the `self.last_frame` update below — this reproduces
            # the ORIGINAL asymmetric behavior exactly (static popups
            # persist into the background; B-roll popups do not).
            final_frame, used_broll = self.graphics.play_fullscreen_popup_sequence(
                video=video,
                base_frame=self.last_frame,
                popup_info=popup_info,
                fps=fps,
                transition_cfg=self.transition_cfg,
                exit_frame=self.last_frame,
            )
            if not used_broll:
                self.last_frame = final_frame
            clip_type = "fullscreen_cinematic"
        else:
            freeze_frame = self.graphics.render_popup_box(self.last_frame, popup_info)
            total_frames = max(1, int(duration * fps))
            fade_frames = min(int(0.5 * fps), total_frames // 3)

            self.graphics.write_fade_clip(
                video, self.last_frame, freeze_frame, total_frames, fade_frames
            )
            self.last_frame = freeze_frame
            clip_type = "static_popup"

        video.release(clip_path)
        return {"clip_id": clip_id, "file_path": clip_path, "type": clip_type}

    @staticmethod
    def _transition_action_from_popup(
        point_index: int,
        popup_data: Optional[Dict[str, Any]],
        action_id: str,
        default_hold: float,
    ) -> Dict[str, Any]:
        if popup_data and popup_data.get("popup_image"):
            action = {
                "type": "popup_image",
                "id": action_id,
                "point_index": point_index,
                "image": popup_data["popup_image"],
                "display": popup_data.get("image_display", "box"),
                "duration_seconds": float(
                    popup_data.get("freeze_seconds", default_hold)
                ),
            }
            if popup_data.get("popup_video"):
                action["popup_video"] = popup_data["popup_video"]
            return action

        duration = (
            float(popup_data.get("freeze_seconds", default_hold))
            if popup_data
            else default_hold
        )
        return {"type": "hold", "id": action_id, "duration_seconds": duration}

    @staticmethod
    def build_storyboard_from_route(
        points: List,
        labels: List,
        popups: List,
        wp_indices: List[int],
        leg_durations: Optional[List[float]] = None,
        default_leg_seconds: float = 8.0,
        default_transition_hold_seconds: float = 1.5,
        video_id: str = "overview",
        output_filename: str = "01_overview.mp4",
        include_summary: bool = True,
    ) -> Dict[str, Any]:
        if not wp_indices:
            return {
                "video_id": video_id,
                "output_filename": output_filename,
                "actions": [
                    {
                        "type": "draw_route",
                        "id": "full_route",
                        "from_point_index": 0,
                        "to_point_index": max(0, len(points) - 1),
                        "duration_seconds": default_leg_seconds,
                    }
                ],
            }

        sorted_wp = sorted(wp_indices)
        actions: List[Dict[str, Any]] = []

        start_idx = sorted_wp[0]
        start_popup = popups[start_idx] if start_idx < len(popups) else None
        actions.append(
            StoryboardRenderer._transition_action_from_popup(
                start_idx, start_popup, "intro", default_transition_hold_seconds
            )
        )

        for i in range(len(sorted_wp) - 1):
            leg_start, leg_end = sorted_wp[i], sorted_wp[i + 1]
            duration = (
                leg_durations[i]
                if leg_durations and i < len(leg_durations)
                else default_leg_seconds
            )
            actions.append(
                {
                    "type": "draw_route",
                    "id": f"leg_{i + 1}",
                    "from_point_index": leg_start,
                    "to_point_index": leg_end,
                    "duration_seconds": duration,
                }
            )

            end_popup = popups[leg_end] if leg_end < len(popups) else None
            actions.append(
                StoryboardRenderer._transition_action_from_popup(
                    leg_end,
                    end_popup,
                    f"transition_{i + 1}",
                    default_transition_hold_seconds,
                )
            )

        if include_summary:
            actions.append({"type": "summary_card", "id": "summary"})

        return {
            "video_id": video_id,
            "output_filename": output_filename,
            "actions": actions,
        }

    def render_storyboard(
        self,
        img_path: str,
        points: List,
        labels: List,
        storyboard: Dict[str, Any],
        summary: Optional[Dict] = None,
    ) -> str:
        self._validate_storyboard(storyboard)
        base_img = self.graphics.read_image_safe(img_path)
        if base_img is None:
            raise FileNotFoundError(f"Cannot read background image: {img_path}")

        h, w = base_img.shape[:2]
        fps = int(storyboard.get("fps", self.config.get("fps", 30)))
        self.last_frame = base_img.copy()

        path_history: List[Tuple[int, int]] = []
        timeline_tracks: List[Dict[str, str]] = []
        clip_idx = 0

        def start_new_clip(phase_name: str, action_id: str):
            nonlocal clip_idx
            clip_id = f"{clip_idx:03d}_{phase_name}_{action_id}"
            filename = str(self.out_dir / f"story_{clip_id}.mp4")
            clip_idx += 1
            return VideoExporter(filename, w, h, fps), filename, clip_id

        for action in storyboard["actions"]:
            a_type = action["type"]
            a_id = action.get("id", f"action{clip_idx}")

            if a_type == "draw_route":
                video, clip_path, clip_id = start_new_clip("route", a_id)
                start_idx, end_idx = (
                    action["from_point_index"],
                    action["to_point_index"],
                )
                segment = points[start_idx : end_idx + 1]

                num_frames = max(
                    2, int(float(action.get("duration_seconds", 5.0)) * fps)
                )
                smooth = MapFetcher.get_smooth_path(
                    segment, num_frames, ease=action.get("ease", True)
                )

                seg_named = [
                    (int(points[i][0]), int(points[i][1]), labels[i])
                    for i in range(start_idx, min(end_idx + 1, len(labels)))
                    if MathUtils.is_real_label(labels[i])
                ]
                seg_sprites = {
                    lbl: self.graphics.prebake_landmark_sprite(lbl)
                    for _, _, lbl in seg_named
                }

                for p in smooth:
                    frame = base_img.copy()
                    path_history.append((int(p[0]), int(p[1])))
                    self.graphics.draw_path(frame, path_history)
                    for sx, sy, lbl in seg_named:
                        sprite, anchor = seg_sprites[lbl]
                        self.graphics.blit_sprite(frame, sprite, anchor, sx, sy)
                    cx, cy = path_history[-1]
                    self.graphics.draw_marker(frame, cx, cy)
                    video.write(frame)
                    self.last_frame = frame

                video.release(clip_path)
                timeline_tracks.append(
                    {"clip_id": clip_id, "file_path": clip_path, "type": "map_drawing"}
                )

            elif a_type == "popup_image":
                timeline_tracks.append(
                    self._render_storyboard_popup(
                        action, points, labels, fps, start_new_clip
                    )
                )

            elif a_type == "hold":
                video, clip_path, clip_id = start_new_clip("hold", a_id)
                duration = float(action.get("duration_seconds", 1.0))
                for _ in range(max(1, int(duration * fps))):
                    video.write(self.last_frame)
                video.release(clip_path)
                timeline_tracks.append(
                    {"clip_id": clip_id, "file_path": clip_path, "type": "hold"}
                )

            elif a_type == "summary_card":
                video, clip_path, clip_id = start_new_clip("summary", a_id)
                distance_km = action.get(
                    "distance_km", (summary or {}).get("total_distance_km", 0.0)
                )
                stat_duration_seconds = action.get(
                    "stat_duration_seconds",
                    (summary or {}).get("total_duration_seconds", 0.0),
                )
                card = self.graphics.create_summary_card(
                    distance_km=distance_km, duration_seconds=stat_duration_seconds
                )
                fade_sec = float(
                    action.get("fade_seconds", self.config.get("summary_fade", 0.5))
                )
                hold_sec = float(
                    action.get("duration_seconds", self.config.get("summary_hold", 4.0))
                )
                fade_frames = max(1, int(fade_sec * fps))
                hold_frames = max(0, int(hold_sec * fps) - fade_frames)

                for i in range(fade_frames):
                    video.write(
                        self.graphics.composite_card_on_frame(
                            self.last_frame, card, alpha=(i + 1) / fade_frames
                        )
                    )
                held = self.graphics.composite_card_on_frame(
                    self.last_frame, card, alpha=1.0
                )
                for _ in range(hold_frames):
                    video.write(held)
                self.last_frame = held

                video.release(clip_path)
                timeline_tracks.append(
                    {"clip_id": clip_id, "file_path": clip_path, "type": "summary_card"}
                )

            else:
                raise ValueError(f"Unhandled storyboard action type: {a_type!r}")

        output_filename = storyboard.get(
            "output_filename", f"{storyboard.get('video_id', 'story')}.mp4"
        )
        final_path = str(self.out_dir / output_filename)
        timeline_json_path = str(
            self.out_dir.parent / f"{Path(output_filename).stem}_timeline.json"
        )

        final_output = VideoExporter.concat_from_timeline(
            timeline_data={
                "project_name": storyboard.get("video_id", "storyboard_video"),
                "video_tracks": timeline_tracks,
            },
            output_path=final_path,
            save_json_path=timeline_json_path,
        )

        # [NEW] Publish the manifest AFTER a successful concat, so a partial
        # or failed render never leaves stale/misleading state that a caller
        # could read and mistakenly trust.
        self.last_timeline_tracks = timeline_tracks

        return final_output
