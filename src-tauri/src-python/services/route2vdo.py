"""
route2vdo.py (OOP Refactored)
---------------------------------------------------------------------------
STAGE 5 of the pipeline: turns a pixel-space route into an animated MP4 video.
Refactored into an Object-Oriented architecture for modularity and readability.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Final, Dict, Any, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw
from PIL.ImageFont import truetype, load_default, FreeTypeFont
from services.mapfetcher import MapFetcher

FFMPEG_BIN = (
    Path(__file__).resolve().parent.parent / "bin" / "FFmpeg" / "bin" / "ffmpeg.exe"
)

# =============================================================================
# UTILITY CLASSES
# =============================================================================


class MathUtils:
    """Static utility methods for geometry and math."""

    @staticmethod
    def point_to_segment_distance(
        px: float, py: float, ax: float, ay: float, bx: float, by: float
    ) -> float:
        abx, aby = bx - ax, by - ay
        seg_len_sq = abx * abx + aby * aby
        if seg_len_sq < 1e-9:
            return float(np.hypot(px - ax, py - ay))
        t = max(0.0, min(1.0, ((px - ax) * abx + (py - ay) * aby) / seg_len_sq))
        closest_x, closest_y = ax + t * abx, ay + t * aby
        return float(np.hypot(px - closest_x, py - closest_y))

    @staticmethod
    def is_real_label(lbl: Any) -> bool:
        if lbl is None:
            return False
        if isinstance(lbl, float) and math.isnan(lbl):
            return False
        return str(lbl).strip() != ""


# =============================================================================
# DATA & VIDEO I/O
# =============================================================================


class VideoExporter:
    """Handles writing frames to video files using FFmpeg or OpenCV fallback."""

    def __init__(self, output_path: str, width: int, height: int, fps: int):
        self.width = width
        self.height = height
        self.fps = fps
        self.proc = self._open_ffmpeg_writer(output_path)
        self._fallback_path = None
        self._fallback_writer = None

        if self.proc is None:
            self._fallback_path = tempfile.mktemp(suffix=".avi")
            self._fallback_writer = cv2.VideoWriter(
                self._fallback_path,
                cv2.VideoWriter.fourcc(*"XVID"),
                self.fps,
                (self.width, self.height),
            )
            if not self._fallback_writer.isOpened():
                raise RuntimeError(
                    "Neither ffmpeg nor OpenCV VideoWriter is available."
                )

    @staticmethod
    def resolve_ffmpeg() -> Optional[str]:
        if FFMPEG_BIN.exists():
            return str(FFMPEG_BIN)
        return shutil.which("ffmpeg")

    def _open_ffmpeg_writer(self, output_path: str) -> Optional[subprocess.Popen]:
        ffmpeg_cmd = self.resolve_ffmpeg()
        if ffmpeg_cmd is None:
            return None

        cmd = [
            ffmpeg_cmd,
            "-y",
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{self.width}x{self.height}",
            "-r",
            str(self.fps),
            "-i",
            "-",
            "-an",
            "-vcodec",
            "libx264",
            "-crf",
            "18",
            "-preset",
            "fast",
            "-pix_fmt",
            "yuv420p",
            output_path,
        ]
        return subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )

    def write(self, frame: np.ndarray) -> None:
        if self.proc is not None and self.proc.stdin:
            self.proc.stdin.write(frame.tobytes())
        elif self._fallback_writer:
            self._fallback_writer.write(frame)

    def release(self, output_path: str) -> str:
        if self.proc is not None:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait()
            return output_path

        if self._fallback_writer:
            self._fallback_writer.release()

        if (
            output_path.lower().endswith(".mp4")
            and self._fallback_path
            and self._reencode_to_h264(self._fallback_path, output_path)
        ):
            if self._fallback_path and os.path.exists(self._fallback_path):
                os.remove(self._fallback_path)
            return output_path

        avi_path = str(Path(output_path).with_suffix(".avi"))
        if self._fallback_path:
            os.rename(self._fallback_path, avi_path)
        return avi_path

    @staticmethod
    def _reencode_to_h264(src: str, dst: str) -> bool:
        ffmpeg_cmd = VideoExporter.resolve_ffmpeg()
        if ffmpeg_cmd is None:
            return False
        try:
            r = subprocess.run(
                [
                    ffmpeg_cmd,
                    "-y",
                    "-i",
                    src,
                    "-vcodec",
                    "libx264",
                    "-crf",
                    "18",
                    "-preset",
                    "fast",
                    "-pix_fmt",
                    "yuv420p",
                    dst,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return r.returncode == 0
        except FileNotFoundError:
            return False


# =============================================================================
# GRAPHICS ENGINE
# =============================================================================


class GraphicsEngine:
    """Handles all drawing, UI composites, and image manipulations."""

    FONT_CANDIDATES_REGULAR: Final[List[str]] = ["segoeui.ttf", "DejaVuSans.ttf"]
    FONT_CANDIDATES_BOLD: Final[List[str]] = ["seguisb.ttf", "DejaVuSans-Bold.ttf"]

    def __init__(
        self,
        line_color=(0, 200, 255),
        line_thickness=10,
        marker_color=(0, 0, 255),
        marker_radius=18,
    ):
        self.line_color = line_color
        self.line_thickness = line_thickness
        self.marker_color = marker_color
        self.marker_radius = marker_radius
        self.font_cv = cv2.FONT_HERSHEY_SIMPLEX

    @staticmethod
    def read_image_safe(path: str) -> Optional[np.ndarray]:
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as f:
                chunk = f.read()
            img_array = np.frombuffer(chunk, dtype=np.uint8)
            return cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        except Exception as e:
            print(f"⚠️ Failed to load image {path}: {e}")
            return None

    def draw_path(self, frame: np.ndarray, path_history: List[Tuple[int, int]]):
        if len(path_history) > 1:
            cv2.polylines(
                frame,
                [np.array(path_history, dtype=np.int32)],
                False,
                self.line_color,
                self.line_thickness,
                cv2.LINE_AA,
            )

    def draw_marker(self, frame: np.ndarray, cx: int, cy: int):
        cv2.circle(
            frame, (cx, cy), self.marker_radius, self.marker_color, -1, cv2.LINE_AA
        )
        cv2.circle(
            frame, (cx, cy), self.marker_radius + 4, (255, 255, 255), 2, cv2.LINE_AA
        )
        cv2.circle(
            frame, (cx, cy), self.marker_radius + 7, self.marker_color, 1, cv2.LINE_AA
        )

    def prebake_landmark_sprite(self, label: str) -> Tuple[np.ndarray, Tuple[int, int]]:
        (tw, th), _ = cv2.getTextSize(label, self.font_cv, 0.6, 1)
        pad = 5
        sprite_w = self.marker_radius + 4 + tw + pad * 2 + self.marker_radius + 4
        sprite_h = max(2 * (self.marker_radius + 3), th + pad * 2) + 8
        sprite = np.zeros((sprite_h, sprite_w, 4), dtype=np.uint8)

        cx, cy = self.marker_radius + 4, sprite_h // 2
        cv2.circle(
            sprite, (cx, cy), self.marker_radius, (255, 80, 0, 255), -1, cv2.LINE_AA
        )
        cv2.circle(
            sprite,
            (cx, cy),
            self.marker_radius + 3,
            (255, 255, 255, 255),
            2,
            cv2.LINE_AA,
        )

        bx1, by1 = cx + self.marker_radius + 4, cy - th - pad
        bx2, by2 = bx1 + tw + pad * 2, cy + pad
        cv2.rectangle(
            sprite, (bx1 - 1, by1 - 1), (bx2 + 1, by2 + 1), (50, 50, 50, 255), -1
        )
        cv2.rectangle(sprite, (bx1, by1), (bx2, by2), (255, 255, 255, 255), -1)
        cv2.putText(
            sprite,
            label,
            (bx1 + pad, cy - 2),
            self.font_cv,
            0.6,
            (30, 30, 30, 255),
            1,
            cv2.LINE_AA,
        )

        return sprite, (cx, cy)

    def blit_sprite(
        self,
        frame: np.ndarray,
        sprite_bgra: np.ndarray,
        anchor: Tuple[int, int],
        x: int,
        y: int,
    ):
        h, w = frame.shape[:2]
        sh, sw = sprite_bgra.shape[:2]
        ox, oy = x - anchor[0], y - anchor[1]
        x0, y0 = max(0, ox), max(0, oy)
        x1, y1 = min(w, ox + sw), min(h, oy + sh)
        if x0 >= x1 or y0 >= y1:
            return
        sx0, sy0 = x0 - ox, y0 - oy
        region = sprite_bgra[sy0 : sy0 + (y1 - y0), sx0 : sx0 + (x1 - x0)]
        alpha = region[:, :, 3:4].astype(np.float32) / 255.0
        frame[y0:y1, x0:x1] = (
            region[:, :, :3] * alpha + frame[y0:y1, x0:x1] * (1 - alpha)
        ).astype(np.uint8)

    def render_popup_box(
        self, target_frame: np.ndarray, popup_info: Dict
    ) -> np.ndarray:
        f_frame = target_frame.copy()
        img_url = popup_info["data"].get("popup_image")
        h, w = f_frame.shape[:2]

        if img_url and os.path.exists(img_url):
            pop_img = self.read_image_safe(img_url)
            if pop_img is not None:

                # --- NEW: Force 16:9 Aspect Ratio with Non-Collapsing Center Crop ---
                ph, pw = pop_img.shape[:2]
                target_ratio = 16.0 / 9.0
                current_ratio = pw / float(ph)

                if current_ratio > target_ratio:
                    # Image is too wide: Crop sides evenly
                    new_w = int(ph * target_ratio)
                    offset = (pw - new_w) // 2
                    pop_img = pop_img[:, offset : offset + new_w]
                elif current_ratio < target_ratio:
                    # Image is too tall: Crop top and bottom evenly
                    new_h = int(pw / target_ratio)
                    offset = (ph - new_h) // 2
                    pop_img = pop_img[offset : offset + new_h, :]

                # Resize to standard width (350px) and calculated 16:9 height (~196px)
                target_img_w = 350
                target_img_h = int(target_img_w / target_ratio)
                pop_img = cv2.resize(pop_img, (target_img_w, target_img_h))
                ph, pw = pop_img.shape[:2]
                # --------------------------------------------------------------------

                border, label_text = 6, popup_info.get("label")
                text_offset = (
                    cv2.getTextSize(label_text or "", self.font_cv, 0.6, 1)[0][1] + 15
                    if MathUtils.is_real_label(label_text)
                    else 0
                )
                total_w, total_h = pw + (border * 2), ph + (border * 2)

                margin = 40
                box_x = (
                    int(popup_info["x"]) - total_w - self.marker_radius - 4
                    if popup_info["x"] > w * 0.6
                    else int(popup_info["x"]) + self.marker_radius + 4
                )
                box_y = (
                    int(popup_info["y"]) + self.marker_radius + 10
                    if int(popup_info["y"]) - total_h - text_offset - 10 < margin
                    else int(popup_info["y"]) - total_h - text_offset - 10
                )
                box_x = max(margin, min(box_x, w - total_w - margin))
                box_y = max(margin, min(box_y, h - total_h - margin))

                cv2.rectangle(
                    f_frame,
                    (box_x, box_y),
                    (box_x + total_w, box_y + total_h),
                    (255, 255, 255),
                    -1,
                )
                cv2.rectangle(
                    f_frame,
                    (box_x, box_y),
                    (box_x + total_w, box_y + total_h),
                    (100, 100, 100),
                    2,
                )
                f_frame[
                    box_y + border : box_y + border + ph,
                    box_x + border : box_x + border + pw,
                ] = pop_img
        return f_frame

    def create_summary_card(
        self, distance_km: float, duration_seconds: float, card_size=(460, 100)
    ) -> np.ndarray:
        w, h = card_size
        scale = 2
        canvas = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)

        bg_color, text_color = (250, 250, 250, 235), (40, 40, 40, 255)
        icon_color, divider_color = (80, 80, 80, 255), (210, 210, 210, 255)

        draw.rounded_rectangle(
            [0, 0, w * scale - 1, h * scale - 1], radius=(h * scale) // 2, fill=bg_color
        )

        font_label = self._load_font(self.FONT_CANDIDATES_REGULAR, 15 * scale)
        font_value = self._load_font(self.FONT_CANDIDATES_BOLD, 24 * scale)

        icon_size, pad = 44 * scale, 28 * scale
        self._draw_walking_icon(
            draw, pad + icon_size // 2, h * scale // 2, icon_size, icon_color
        )

        text_x = pad + icon_size + 14 * scale
        draw.text((text_x, 22 * scale), "Time", font=font_label, fill=text_color)
        draw.text(
            (text_x, 44 * scale),
            self._format_duration_short(duration_seconds),
            font=font_value,
            fill=text_color,
        )

        div_x = w * scale // 2
        draw.line(
            [(div_x, 20 * scale), (div_x, h * scale - 20 * scale)],
            fill=divider_color,
            width=2 * scale,
        )

        icon_cx2 = div_x + 30 * scale + icon_size // 2
        self._draw_ruler_icon(draw, icon_cx2, h * scale // 2, icon_size, icon_color)

        text_x2 = icon_cx2 + icon_size // 2 + 14 * scale
        distance_str = (
            f"{distance_km * 1000:.0f} m"
            if distance_km < 1
            else f"{distance_km:.2f} km"
        )
        draw.text((text_x2, 22 * scale), "Distance", font=font_label, fill=text_color)
        draw.text((text_x2, 44 * scale), distance_str, font=font_value, fill=text_color)

        canvas = canvas.resize((w, h), Image.Resampling.LANCZOS)
        return np.array(canvas)[:, :, [2, 1, 0, 3]]

    def composite_card_on_frame(
        self, frame: np.ndarray, card_bgra: np.ndarray, alpha: float, margin: int = 40
    ) -> np.ndarray:
        out = frame.copy()
        h, w = out.shape[:2]
        ch, cw = card_bgra.shape[:2]

        if cw > w - 2 * margin or ch > h - 2 * margin:
            shrink = min((w - 2 * margin) / cw, (h - 2 * margin) / ch)
            card_bgra = cv2.resize(
                card_bgra,
                (max(1, int(cw * shrink)), max(1, int(ch * shrink))),
                interpolation=cv2.INTER_AREA,
            )
            ch, cw = card_bgra.shape[:2]

        x0, y0 = w - cw - margin, h - ch - margin
        card_bgr, card_alpha = (
            card_bgra[:, :, :3].astype(np.float32),
            (card_bgra[:, :, 3].astype(np.float32) / 255.0) * alpha,
        )
        roi = out[y0 : y0 + ch, x0 : x0 + cw].astype(np.float32)
        out[y0 : y0 + ch, x0 : x0 + cw] = (
            card_bgr * card_alpha[..., None] + roi * (1 - card_alpha[..., None])
        ).astype(np.uint8)
        return out

    def _load_font(self, candidates: List[str], size: int) -> FreeTypeFont | Any:
        for name in candidates:
            try:
                return truetype(name, size)
            except OSError:
                continue

        return load_default()

    def _draw_walking_icon(
        self, draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color: Tuple
    ):
        r = size // 6
        draw.ellipse(
            [cx - r, cy - size // 2, cx + r, cy - size // 2 + 2 * r], fill=color
        )
        torso_top = (cx, cy - size // 2 + 2 * r)
        torso_bottom = (cx - size // 8, cy)
        draw.line([torso_top, torso_bottom], fill=color, width=max(2, size // 12))
        draw.line(
            [torso_bottom, (cx - size // 3, cy + size // 2)],
            fill=color,
            width=max(2, size // 12),
        )
        draw.line(
            [torso_bottom, (cx + size // 4, cy + size // 2 - r // 2)],
            fill=color,
            width=max(2, size // 12),
        )

    def _draw_ruler_icon(
        self, draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color: Tuple
    ):
        half = size // 2
        p1 = (cx - half, cy + half // 2)
        p2 = (cx + half, cy - half // 2)
        draw.line([p1, p2], fill=color, width=max(3, size // 10))
        for t in (0.25, 0.5, 0.75):
            tx = p1[0] + (p2[0] - p1[0]) * t
            ty = p1[1] + (p2[1] - p1[1]) * t
            draw.line([(tx - 4, ty - 6), (tx + 4, ty + 6)], fill=color, width=2)

    def _format_duration_short(self, seconds: float) -> str:
        total_minutes = int(round(seconds / 60))
        hrs, mins = divmod(total_minutes, 60)
        return f"{hrs} hr {mins:02d} min" if hrs else f"{mins} min"


# =============================================================================
# ROUTE PIPELINE ORCHESTRATOR
# =============================================================================


class RouteAnimator:
    """Orchestrates the entire animation pipeline (Overview, Waypoints, Summary)."""

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
        print(f"🎬 Rendering Phase 1: Big Picture ({duration}s)")

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
            print("📊 Rendering Summary Card directly onto Overview")
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

    def _render_waypoints(self, res_sequence: List[Dict], fps: int) -> List[str]:
        output_paths = []

        show_segment_summary = self.config.get("show_segment_summary", True)
        fade_sec = self.config.get("summary_fade", 0.5)
        clip_hold_sec = self.config.get("clip_summary_hold", 2.0)

        for i, res_data in enumerate(res_sequence):
            print(f"🏡 Rendering Residential Map {i + 1}/{len(res_sequence)}")
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

    def _render_summary(self, summary: Dict, fps: int) -> str:
        print("📊 Rendering Summary Card")
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


# =============================================================================
# CLI ENTRY POINT
# =============================================================================


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
