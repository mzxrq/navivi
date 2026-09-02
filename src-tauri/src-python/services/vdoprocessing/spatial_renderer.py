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

from services.mapfetcher.mapfetcher import MapFetcher
from services.mapfetcher.mapgeometry import RouteGeometryProcessor
from services.vdoprocessing.vdoexporter import VideoExporter
from services.mapfetcher.graphicengine import GraphicsEngine
from services.logger.logger import setup_logger

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
        # Global kill switch for the "scale up to fill the screen" popup
        # style — when off, every waypoint (regardless of its own
        # image_display setting) uses the small pip card instead.
        self.enable_fullscreen_popups: bool = bool(
            config.get("enable_fullscreen_popups", True)
        )
        # When True, the route line is hidden (only pins/points stay visible)
        # for the duration a popup card is frozen on screen.
        self.hide_route_on_popup: bool = bool(config.get("hide_route_on_popup", False))
        # When True, only already-arrived waypoint pins are drawn during the
        # arrival pause/popup — with many stops on screen, every not-yet-
        # reached pin competing for attention makes it hard to tell which
        # one just triggered.
        self.hide_upcoming_pins_on_popup: bool = bool(
            config.get("hide_upcoming_pins_on_popup", False)
        )
        self.last_frame = None

    # Opposite corner for each HUD corner — the segment-stat card always
    # sits diagonally across from the arrival popup so the two never overlap.
    _OPPOSITE_CORNER = {
        "bottom_left": "top_right",
        "bottom_right": "top_left",
        "top_left": "bottom_right",
        "top_right": "bottom_left",
    }

    def _composite_leg_stat_card(
        self, frame: np.ndarray, leg_stat: Dict, popup_corner: str
    ) -> np.ndarray:
        """Draws this leg's distance/time as a small summary-style card
        (matching the end-of-video summary card) in the corner diagonally
        opposite the arrival popup."""
        card = self.graphics.create_summary_card(
            distance_km=leg_stat.get("distance_km", 0.0),
            duration_seconds=leg_stat.get("duration_seconds", 0.0),
            card_size=(360, 90),
        )
        corner = self._OPPOSITE_CORNER.get(popup_corner, "top_right")
        return self.graphics.composite_card_on_frame(frame, card, alpha=1.0, corner=corner)

    def _build_freeze_frame(
        self,
        current_bg: np.ndarray,
        path_history: List,
        mode_history: List[str],
        last_leg_boundary: int,
        active_popups: List[Dict],
    ) -> np.ndarray:
        """Background + route line (respecting hide_route_on_popup) + pins
        for ONLY already-arrived waypoints — used for the arrival pause and
        popup when hide_upcoming_pins_on_popup is on, so a route with many
        stops doesn't bury the one that just triggered under a scatter of
        still-ahead pins."""
        base = current_bg.copy()
        if self.hide_route_on_popup:
            self.graphics.draw_path(
                base,
                path_history[: last_leg_boundary + 1],
                mode_history[: last_leg_boundary + 1],
            )
        else:
            self.graphics.draw_path(base, path_history, mode_history)
        for order, wp in enumerate(active_popups, start=1):
            if wp["data"].get("triggered"):
                self.graphics.draw_marker(
                    base, int(wp["x"]), int(wp["y"]),
                    number=order, color=self._pin_color(wp),
                )
        return base

    def _layout_beside_popups(
        self,
        group: List[Dict],
        w: int,
        h: int,
        card_w: int = 368,
        card_h: int = 300,
    ) -> None:
        """For waypoints flowing through without a freeze, their popup cards
        sit beside their own pin (see render_popup_box's non-HUD-corner
        branch) instead of a screen corner. When more than one is visible
        at once (nearby waypoints triggering close together in time), their
        default positions can overlap — this stacks the later one below the
        earlier one until they clear, storing the vertical push as
        "beside_nudge_y" on each popup for render_popup_box to apply."""
        placed: List[Tuple[float, float, float, float]] = []
        for bp in sorted(group, key=lambda b: b["popup"]["y"]):
            popup = bp["popup"]
            x, y = popup["x"], popup["y"]
            box_x = x - card_w - 40 if x > w * 0.5 else x + 40
            box_x = max(40, min(box_x, w - card_w - 40))
            box_y = max(40, min(y - card_h / 2, h - card_h - 40))

            nudge = 0.0
            for (px0, py0, px1, py1) in placed:
                if box_x < px1 and box_x + card_w > px0:
                    top, bottom = box_y + nudge, box_y + nudge + card_h
                    if top < py1 and bottom > py0:
                        nudge = py1 - box_y + 12

            final_y = max(40, min(box_y + nudge, h - card_h - 40))
            popup["beside_nudge_y"] = final_y - box_y
            placed.append((box_x, final_y, box_x + card_w, final_y + card_h))

    def _pin_color(self, wp: Dict):
        """Arrived waypoints get GraphicsEngine.arrived_marker_color; ones
        still ahead keep the default marker_color (return None so
        draw_marker falls back to it)."""
        return self.graphics.arrived_marker_color if wp["data"].get("triggered") else None

    @staticmethod
    def _smoothed_heading(
        prev_angle: float,
        cx: int,
        cy: int,
        prev_cx: Optional[int],
        prev_cy: Optional[int],
        min_dist: float = 1.5,
        alpha: float = 0.35,
    ) -> float:
        """Blends the new frame-to-frame heading into the previous smoothed
        heading, and ignores movement smaller than `min_dist` outright.

        The animated path is now straight-line interpolation between the
        real (simplified) route points, so through a winding, non-straight
        stretch the true heading changes abruptly at every vertex — and
        `path_history` stores rounded integer pixel coordinates, so on a
        short step the raw atan2 direction is dominated by rounding noise
        rather than the actual travel direction. Both together make the
        travel icon visibly shake as it moves. Blending (circularly, via
        the sin/cos components — angles can't be linearly averaged across
        the 359°/0° wrap) trades a little turning responsiveness for a
        stable-looking heading.
        """
        if prev_cx is None or prev_cy is None:
            return prev_angle
        if math.hypot(cx - prev_cx, cy - prev_cy) < min_dist:
            return prev_angle
        raw_angle = math.degrees(math.atan2(cy - prev_cy, cx - prev_cx))
        prev_rad, raw_rad = math.radians(prev_angle), math.radians(raw_angle)
        x = math.cos(prev_rad) * (1 - alpha) + math.cos(raw_rad) * alpha
        y = math.sin(prev_rad) * (1 - alpha) + math.sin(raw_rad) * alpha
        return math.degrees(math.atan2(y, x))

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
            if not RouteGeometryProcessor.is_real_label(lbl) or lbl not in sprites_dict:
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

    @staticmethod
    def _build_mode_breakpoints(points: List, point_modes: List[str]) -> List[Tuple[float, str]]:
        """Cumulative-distance fractions (0..1 along the route) at which the
        travel mode changes, so the animated trail/icon can react to
        routeMode transitions (e.g. walking -> ferry)."""
        if not points or not point_modes or len(points) != len(point_modes):
            return []

        cum = [0.0]
        for i in range(1, len(points)):
            cum.append(
                cum[-1]
                + math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1])
            )
        total = cum[-1] or 1.0

        breakpoints = [(0.0, point_modes[0])]
        for i in range(1, len(points)):
            if point_modes[i] != breakpoints[-1][1]:
                breakpoints.append((cum[i] / total, point_modes[i]))
        return breakpoints

    @staticmethod
    def _mode_at_fraction(breakpoints: List[Tuple[float, str]], frac: float) -> str:
        if not breakpoints:
            return "walking"
        mode = breakpoints[0][1]
        for bp_frac, bp_mode in breakpoints:
            if frac >= bp_frac:
                mode = bp_mode
            else:
                break
        return mode

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
            if RouteGeometryProcessor.is_real_label(cleaned_labels[i])
        ]
        landmark_sprites = {
            lbl: self.graphics.prebake_landmark_sprite(lbl) for _, _, lbl in named
        }

        # Light dedup only — drop literal near-duplicate points so the spline
        # fit doesn't choke on zero-length segments. We deliberately do NOT
        # thin more aggressively than this by raw distance: a tight turn has
        # its points close together too, and stripping those is exactly what
        # let the smoothed path swing wide of sharp corners (cutting across
        # ground the real road never touches). get_smooth_path's own
        # Douglas-Peucker pass below reduces density based on actual
        # curvature (perpendicular deviation), which is the correct signal.
        filtered_points = [points[0]]
        for pt in points[1:]:
            if (
                math.hypot(
                    pt[0] - filtered_points[-1][0], pt[1] - filtered_points[-1][1]
                )
                > 0.5
            ):
                filtered_points.append(pt)
        # Ensure the final destination is always included
        if filtered_points[-1] != points[-1]:
            filtered_points.append(points[-1])

        smooth_path = MapFetcher.get_smooth_path(
            filtered_points, num_frames, ease=True, simplify_tolerance_px=1.2
        )

        mode_breakpoints = self._build_mode_breakpoints(points, point_modes) if point_modes else []
        if mode_breakpoints:
            smooth_arr = np.asarray(smooth_path, dtype=float)
            seg_lens = np.hypot(np.diff(smooth_arr[:, 0]), np.diff(smooth_arr[:, 1]))
            total_smooth_dist = float(seg_lens.sum()) or 1.0
            cum_smooth_dist = np.concatenate([[0.0], np.cumsum(seg_lens)])
        else:
            cum_smooth_dist, total_smooth_dist = None, 1.0

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
        # 1-based visit order — also used to look up this waypoint's leg
        # (leg_stats[order - 2], since the leg arriving at order N left
        # order N-1) and to number its pin.
        for order, ap in enumerate(active_popups, start=1):
            ap["order"] = order
        leg_stats: List[Dict] = (summary or {}).get("leg_stats", [])

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

        logger.info(f"Rendering Overview Map ({duration}s)")
        overview_path = str(self.out_dir / "01_overview.mp4")
        video = VideoExporter(overview_path, w, h, fps)
        baked_popups = []

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
                self.graphics.pick_hud_corner(w, h, route_avoid_points),
                start_popup["x"],
                start_popup["y"],
            )
            start_popup["data"]["triggered"] = True

            if self.enable_fullscreen_popups and temp_sp["data"].get("image_display") == "fullscreen":
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
                    # Show every waypoint marker up front on the intro frame,
                    # not just the start point, so the whole route's stops
                    # are visible before the animation begins.
                    for order, wp in enumerate(active_popups, start=1):
                        self.graphics.draw_marker(
                            intro_frame, int(wp["x"]), int(wp["y"]),
                            number=order, color=self._pin_color(wp),
                        )
                    self._draw_prioritized_sprites(
                        intro_frame, active_popups, landmark_sprites
                    )
                for _ in range(int(intro_freeze_sec * fps)):
                    video.write(intro_frame)

        path_history = []
        mode_history = []
        prev_cx, prev_cy = None, None
        smoothed_angle = 0.0
        # path_history index where the most recently reached waypoint sits —
        # marks the boundary between "earlier, completed legs" (always kept
        # visible) and "the current leg" (the only part hidden while its
        # arrival popup is showing).
        last_leg_boundary = 0

        for current_frame, p in enumerate(smooth_path):
            if is_video:
                ret, vid_frame = cap.read()
                if ret:
                    if vid_frame.shape[0] != h or vid_frame.shape[1] != w:
                        vid_frame = cv2.resize(vid_frame, (w, h))
                    current_bg = vid_frame

            frame = current_bg.copy()

            path_history.append((int(p[0]), int(p[1])))

            if cum_smooth_dist is not None:
                frac = cum_smooth_dist[current_frame] / total_smooth_dist
                current_mode = self._mode_at_fraction(mode_breakpoints, frac)
            else:
                current_mode = "walking"
            mode_history.append(current_mode)

            if not is_video:
                self.graphics.draw_path(frame, path_history, mode_history)

            # "Point to point" snapshot for hide_route_on_popup — every
            # earlier, already-completed leg stays drawn; only the CURRENT
            # leg (since the last waypoint reached) is left off, so arriving
            # at a stop doesn't erase the whole route travelled so far.
            # Built separately (rather than copying `frame` before the line
            # is drawn) because pins still need to render on top of the
            # route line for normal display below.
            frame_no_route = None
            if not is_video and self.hide_route_on_popup:
                frame_no_route = current_bg.copy()
                self.graphics.draw_path(
                    frame_no_route,
                    path_history[: last_leg_boundary + 1],
                    mode_history[: last_leg_boundary + 1],
                )
                for order, wp in enumerate(active_popups, start=1):
                    self.graphics.draw_marker(
                        frame_no_route, int(wp["x"]), int(wp["y"]),
                        number=order, color=self._pin_color(wp),
                    )

            if not is_video:
                # Every waypoint pin stays visible for the whole clip, drawn
                # on top of the route line so it's never obscured by it, and
                # numbered so the visit order is readable at a glance.
                for order, wp in enumerate(active_popups, start=1):
                    self.graphics.draw_marker(
                        frame, int(wp["x"]), int(wp["y"]),
                        number=order, color=self._pin_color(wp),
                    )

            flowing_group = [
                bp for bp in baked_popups
                if not bp["popup"]["data"].get("freeze_frame", False)
            ]
            if flowing_group:
                self._layout_beside_popups(flowing_group, w, h)

            surviving_popups = []
            for bp in baked_popups:
                hud_popup = bp["popup"].copy()
                if hud_popup["data"].get("freeze_frame", False):
                    hud_popup.setdefault("hud_corner", "bottom_left")
                else:
                    hud_popup["hud_corner"] = None
                    hud_popup["draw_leader_line"] = True
                frame = self.graphics.render_popup_box(frame, hud_popup)
                bp["frames_left"] -= 1
                if bp["frames_left"] > 0:
                    surviving_popups.append(bp)
            baked_popups = surviving_popups

            if frame_no_route is None:
                frame_no_route = frame

            cx, cy = path_history[-1]
            px, py = path_history[-2] if len(path_history) > 1 else path_history[-1]

            triggered_popup = None
            for popup in active_popups:
                if popup["index"] == 0 or (
                    stop_popup and popup["index"] == stop_popup["index"]
                ):
                    continue
                if not popup["data"]["triggered"]:
                    if RouteGeometryProcessor.point_to_segment_distance(
                        popup["x"], popup["y"], px, py, cx, cy
                    ) < (
                        self.graphics.marker_radius
                        + self.trigger_radius_padding["overview"]
                    ):
                        popup["data"]["triggered"] = True
                        triggered_popup = popup
                        break

            if triggered_popup:
                # Everything up to (and including) this point becomes part
                # of an "earlier leg" for the NEXT popup's hide effect.
                last_leg_boundary = len(path_history) - 1

                # Pick a corner clear of the route/pins once, and keep it on
                # the popup itself so the lingering baked-popup HUD (below)
                # doesn't jump to a different corner mid-display.
                triggered_popup["hud_corner"] = self.graphics.pick_hud_corner(
                    w, h, route_avoid_points
                )
                leg_idx = triggered_popup["order"] - 2

                # Shared base for BOTH the arrival-hold pause and the popup
                # itself — decluttered to only already-arrived pins when
                # requested, and with the per-leg stat card baked in up
                # front so the pause and the popup read as one continuous
                # "you arrived" beat instead of the card popping in only
                # once the popup shows.
                if self.hide_upcoming_pins_on_popup:
                    popup_base_frame = self._build_freeze_frame(
                        current_bg, path_history, mode_history,
                        last_leg_boundary, active_popups,
                    )
                else:
                    popup_base_frame = frame_no_route if self.hide_route_on_popup else frame
                if 0 <= leg_idx < len(leg_stats):
                    popup_base_frame = self._composite_leg_stat_card(
                        popup_base_frame, leg_stats[leg_idx], triggered_popup["hud_corner"]
                    )

                # Fullscreen popups are an inherent full-screen takeover —
                # they always freeze regardless of the waypoint's
                # freeze_frame setting, since "flow through" wouldn't mean
                # anything for a shot that covers the whole frame. Every
                # other waypoint now flows through by default — the
                # traveler continues moving past each stop all the way to
                # the end; a waypoint only freezes if it opts in with
                # "freeze_frame": true in job_config.json.
                is_fullscreen = (
                    self.enable_fullscreen_popups
                    and triggered_popup["data"].get("image_display") == "fullscreen"
                )
                freeze_frame_on = (
                    triggered_popup["data"].get("freeze_frame", False) or is_fullscreen
                )

                if not freeze_frame_on:
                    # Flow-through: the traveler keeps moving — no held
                    # frame, no arrival pause. The popup card rides along as
                    # a HUD overlay beside the waypoint's own pin (with a
                    # leader line back to it, drawn in render_popup_box) for
                    # freeze_seconds, exactly like the frozen case but
                    # without ever stopping the camera.
                    display_seconds = float(
                        triggered_popup["data"].get("freeze_seconds", 4.0)
                    )
                    baked_popups.append(
                        {
                            "popup": triggered_popup,
                            "frames_left": int(display_seconds * fps),
                        }
                    )
                    frame = popup_base_frame
                    if not is_video:
                        self._draw_prioritized_sprites(
                            frame, active_popups, landmark_sprites
                        )
                        smoothed_angle = self._smoothed_heading(
                            smoothed_angle, cx, cy, prev_cx, prev_cy
                        )
                        self.graphics.draw_transport_icon(
                            frame, cx, cy, current_frame, smoothed_angle, mode=current_mode
                        )
                    self.last_frame = frame
                    video.write(frame)
                    prev_cx, prev_cy = cx, cy
                    continue

                # Hold on the traveler having just reached the pin for a
                # beat before the fullscreen/pip transition kicks in — but
                # the popup photo itself is already visible (as its small
                # pip card) through this hold, so the pause reads as "the
                # popup has arrived and is settling in" rather than a gap
                # with nothing shown yet.
                if not is_video and self.post_arrival_hold_seconds > 0:
                    pause_frame = popup_base_frame.copy()
                    smoothed_angle = self._smoothed_heading(
                        smoothed_angle, cx, cy, prev_cx, prev_cy
                    )
                    self.graphics.draw_transport_icon(
                        pause_frame, cx, cy, current_frame, smoothed_angle, mode=current_mode
                    )
                    pause_frame = self.graphics.render_popup_box(pause_frame, triggered_popup)
                    for _ in range(int(self.post_arrival_hold_seconds * fps)):
                        video.write(pause_frame)

                if is_fullscreen:
                    self.last_frame, _ = self.graphics.play_fullscreen_popup_sequence(
                        video=video,
                        base_frame=popup_base_frame,
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
                    temp_frame = self.graphics.render_popup_box(
                        popup_base_frame, hud_triggered
                    )

                    if not is_video:
                        sprite_popups = (
                            [ap for ap in active_popups if ap["data"].get("triggered")]
                            if self.hide_upcoming_pins_on_popup
                            else active_popups
                        )
                        self._draw_prioritized_sprites(
                            temp_frame, sprite_popups, landmark_sprites
                        )

                    self.last_frame = temp_frame

                    for _ in range(int(display_seconds * fps)):
                        video.write(temp_frame)

            else:
                if not is_video:
                    self._draw_prioritized_sprites(frame, active_popups, landmark_sprites)

                    smoothed_angle = self._smoothed_heading(
                        smoothed_angle, cx, cy, prev_cx, prev_cy
                    )
                    self.graphics.draw_transport_icon(
                        frame, cx, cy, current_frame, smoothed_angle, mode=current_mode
                    )

                self.last_frame = frame
                video.write(frame)

            prev_cx, prev_cy = cx, cy

        if stop_popup:
            outro_frame = self.last_frame.copy()
            temp_stop = stop_popup.copy()
            temp_stop["data"] = stop_popup["data"].copy()
            temp_stop["hud_corner"], temp_stop["x"], temp_stop["y"] = (
                self.graphics.pick_hud_corner(w, h, route_avoid_points),
                stop_popup["x"],
                stop_popup["y"],
            )
            stop_leg_idx = stop_popup["order"] - 2
            if 0 <= stop_leg_idx < len(leg_stats):
                outro_frame = self._composite_leg_stat_card(
                    outro_frame, leg_stats[stop_leg_idx], temp_stop["hud_corner"]
                )

            if self.enable_fullscreen_popups and temp_stop["data"].get("image_display") == "fullscreen":
                self.last_frame, _ = self.graphics.play_fullscreen_popup_sequence(
                    video=video,
                    base_frame=outro_frame,
                    popup_info=temp_stop,
                    fps=fps,
                    transition_cfg=self.transition_cfg,
                    exit_frame=outro_frame,
                )
            else:
                # outro_frame is a copy of the final animated frame, which
                # already has every numbered pin drawn on it — no need to
                # redraw them (and doing so here would lose the numbering,
                # since `triggered_markers` only carries bare x/y).
                outro_frame = self.graphics.render_popup_box(outro_frame, temp_stop)

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
                mode_breakdown=summary.get("mode_breakdown"),
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