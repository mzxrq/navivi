"""The overview map render entry point: sets up the route (labels, speed-
weighted path, intro beat), delegates the frame-by-frame animation to
_OverviewAnimationMixin, then closes out with the recap/summary/ending
highlight. The mode-breakpoint/path-pacing helpers live in
overview_pacing.py and the animation loop itself in overview_animation.py —
both split out of this file to keep it to the setup/wrap-up orchestration."""

import json
from typing import Dict, List, Optional

import cv2
import numpy as np

from services.vdoprocessing.vdoexporter import VideoExporter

from .base import logger


class _OverviewRenderMixin:
    def render_overview(
        self,
        bg_path: str,
        points: List,
        labels: List,
        popups: List,
        fps: int,
        summary: Optional[Dict] = None,
        point_modes: Optional[List[str]] = None,
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


        smooth_path, mode_breakpoints, cum_smooth_dist, total_smooth_dist = (
            self._build_overview_path(points, point_modes, num_frames)
        )

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
        # 1-based visit order, used to number each waypoint's pin and to
        # sort concurrently-visible popups in _layout_beside_popups.
        for order, ap in enumerate(active_popups, start=1):
            ap["order"] = order
        self._declutter_pins(active_popups)

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
                # Waypoints flow through by default (the traveler never
                # stops, all the way to the end) — set "freeze_frame": true
                # on a waypoint in job_config.json to opt IT back into the
                # old held-frame arrival pause. Flow-through popup cards
                # ride along beside the pin (see _layout_beside_popups)
                # rather than holding the frame.
                if "freeze_frame" in jw:
                    popup["data"]["freeze_frame"] = bool(jw["freeze_frame"])

        # Static footprint (the full route line + every pin) used to pick a
        # HUD corner that the popup card won't sit on top of. Computed once
        # from the whole route rather than the animated path-so-far, so a
        # given waypoint's card always lands in the same corner regardless
        # of when in the animation it triggers.
        route_avoid_points = list(points) + [
            (p["x"], p["y"]) for p in active_popups
        ]

        # Same footprint, as a decimated numpy array — lets
        # _layout_beside_popups check a candidate card position against the
        # route line itself (cheaply, vectorized) so a flow-through card
        # doesn't get planted right on top of the path it's next to.
        route_obstacle_arr = np.asarray(route_avoid_points, dtype=float)
        if len(route_obstacle_arr) > 400:
            step = max(1, len(route_obstacle_arr) // 400)
            route_obstacle_arr = route_obstacle_arr[::step]

        logger.info(f"Rendering Overview Map ({duration}s)")
        overview_path = str(self.out_dir / "01_overview.mp4")
        video = VideoExporter(overview_path, w, h, fps)

        intro_frame = current_bg.copy()
        start_popup = next((p for p in active_popups if p["index"] == 0), None)
        stop_popup = next(
            (p for p in active_popups if p["index"] == len(points) - 1), None
        )

        # A flow-through popup's display duration defaults to a fixed
        # freeze_seconds regardless of how long that leg of the route
        # actually takes to animate — so on a short leg the NEXT waypoint's
        # popup could trigger while the previous one is still showing, and
        # on a long leg it could vanish long before the traveler arrives.
        # Instead, tie it to the leg itself: find each waypoint's own
        # expected frame (nearest point along the animated path) and set
        # its popup to last exactly from there until the next waypoint's
        # expected frame — "2 to 3" shows popup 2, and the moment 3 is
        # reached popup 2 hides and popup 3 takes over.
        smooth_arr_lookup = np.asarray(smooth_path, dtype=float)

        def _expected_frame(px: float, py: float) -> int:
            dists = np.hypot(smooth_arr_lookup[:, 0] - px, smooth_arr_lookup[:, 1] - py)
            return int(np.argmin(dists))

        triggerable = [
            ap for ap in active_popups
            if ap["index"] != 0 and (not stop_popup or ap["index"] != stop_popup["index"])
        ]
        triggerable.sort(key=lambda ap: _expected_frame(ap["x"], ap["y"]))
        stop_expected_frame = (
            _expected_frame(stop_popup["x"], stop_popup["y"]) if stop_popup else None
        )
        min_leg_frames = int(fps * 1.5)
        for i, ap in enumerate(triggerable):
            this_frame = _expected_frame(ap["x"], ap["y"])
            next_frame = (
                _expected_frame(triggerable[i + 1]["x"], triggerable[i + 1]["y"])
                if i + 1 < len(triggerable)
                else stop_expected_frame
            )
            if next_frame is not None:
                ap["leg_display_seconds"] = (
                    max(min_leg_frames, next_frame - this_frame) / fps
                )

        intro_freeze_sec = 3.0
        if start_popup and "freeze_seconds" in start_popup["data"]:
            intro_freeze_sec = float(start_popup["data"]["freeze_seconds"])

        if start_popup:
            temp_sp = start_popup.copy()
            temp_sp["data"] = start_popup["data"].copy()
            temp_sp["data"]["triggered"] = True
            temp_sp["hud_corner"], temp_sp["x"], temp_sp["y"] = (
                self.graphics.pick_hud_corner(w, h, route_avoid_points),
                start_popup["x"],
                start_popup["y"],
            )
            # Smaller than the HUD-corner card's 440px default — full-size
            # felt dominant sitting over the whole-route intro map, next to
            # every waypoint pin already drawn on it.
            temp_sp["card_scale"] = self.config.get("overview_intro_card_scale", 0.6)
            start_popup["data"]["triggered"] = True

            if not is_video:
                # Show every waypoint marker up front on the intro frame,
                # not just the start point, so the whole route's stops are
                # visible before the animation begins.
                for order, wp in enumerate(active_popups, start=1):
                    self._draw_pin(intro_frame, wp, order, len(points))

            # The intro always opens as a plain pip card, regardless of
            # this waypoint's own image_display setting — "fullscreen"
            # is only ever honored by the end-of-video zoom-tile highlight
            # (_render_ending_highlight), not here.
            intro_frame = self.graphics.render_popup_box(intro_frame, temp_sp)
            for _ in range(int(intro_freeze_sec * fps)):
                video.write(intro_frame)
            self.last_frame = intro_frame

        pre_popup_frame = self._animate_overview_frames(
            video, current_bg, cap, is_video, w, h, fps,
            smooth_path, mode_breakpoints, cum_smooth_dist, total_smooth_dist,
            active_popups, stop_popup, points, route_avoid_points, route_obstacle_arr,
        )

        # Built once, up front, so its exact footprint can be reserved
        # (see reserved_boxes below) before the recap frame lays out its
        # popup cards — otherwise a card could land right where this gets
        # composited over the video in the bottom-right corner, later.
        summary_card = None
        if summary:
            summary_card = self.graphics.create_summary_card(
                distance_km=summary.get("total_distance_km", 0.0),
                duration_seconds=summary.get("total_duration_seconds", 0.0),
                mode_breakdown=summary.get("mode_breakdown"),
                mode_duration=summary.get("mode_duration"),
            )
        summary_card_margin = 20
        reserved_boxes = (
            [
                (
                    w - summary_card.shape[1] - summary_card_margin,
                    h - summary_card.shape[0] - summary_card_margin,
                    float(w - summary_card_margin),
                    float(h - summary_card_margin),
                )
            ]
            if summary_card is not None
            else []
        )

        outro_hold_sec = self._render_recap_and_summary(
            video, stop_popup, summary_card, active_popups, w, h, fps,
            route_obstacle_arr, reserved_boxes, pre_popup_frame,
        )
        for _ in range(int(outro_hold_sec * fps)):
            video.write(self.last_frame)

        hard_ended = False
        if stop_popup and self.config.get("enable_ending_highlight", True):
            hard_ended = self._render_ending_highlight(
                video, w, h, fps, stop_popup, start_popup,
                clean_map_frame=pre_popup_frame,
            )

        for p in popups:
            if p:
                p["triggered"] = False

        # The fullscreen ending highlight, when it plays, IS the video's
        # last frame — no trailing pause on the map afterward.
        if not hard_ended:
            for _ in range(int(self.config.get("pause", 2.0) * fps)):
                video.write(self.last_frame)

        self.last_ending_hard_ended = hard_ended

        if cap:
            cap.release()
        return video.release(overview_path)
