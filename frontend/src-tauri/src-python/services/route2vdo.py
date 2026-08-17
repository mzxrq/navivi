"""
route2vdo.py
---------------------------------------------------------------------------
STAGE 5 of the pipeline: turns a pixel-space route (points already
projected onto a static map image) into an animated MP4 navigation video.
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
from typing import Final

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from services.mapfetcher import MapFetcher

FFMPEG_BIN = Path(__file__).resolve().parent.parent / "bin" / "FFmpeg" / "bin" / "ffmpeg.exe"


def _resolve_ffmpeg() -> str | None:
    if FFMPEG_BIN.exists():
        return str(FFMPEG_BIN)
    return shutil.which("ffmpeg")


def _point_to_segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    abx, aby = bx - ax, by - ay
    seg_len_sq = abx * abx + aby * aby
    if seg_len_sq < 1e-9:
        return float(np.hypot(px - ax, py - ay))
    t = max(0.0, min(1.0, ((px - ax) * abx + (py - ay) * aby) / seg_len_sq))
    closest_x, closest_y = ax + t * abx, ay + t * aby
    return float(np.hypot(px - closest_x, py - closest_y))


def _is_real_label(lbl) -> bool:
    if lbl is None:
        return False
    if isinstance(lbl, float) and math.isnan(lbl):
        return False
    return str(lbl).strip() != ""


def _read_image_safe(path: str) -> np.ndarray | None:
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


def _project_latlons_to_pixels(lats: np.ndarray, lons: np.ndarray, extent: tuple, img_w: int, img_h: int) -> np.ndarray:
    if len(lats) == 0:
        return np.empty((0, 2), dtype=np.float32)
    min_x, max_x, min_y, max_y = extent
    r = 6378137.0
    mx = lons * (r * np.pi / 180.0)
    my = np.log(np.tan((90.0 + lats) * np.pi / 360.0)) * r
    px = (mx - min_x) / (max_x - min_x) * img_w
    py = (max_y - my) / (max_y - min_y) * img_h
    return np.column_stack([px, py])


def load_route(json_path: str):
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
                popups.append({
                    "freeze_seconds": float(item.get("freeze_seconds", 2.0)),
                    "popup_image": item.get("popup_image"),
                    "triggered": False,
                })
            else:
                popups.append(None)
        else:
            raise ValueError(f"Unknown point format: {item}")

    return points, labels, popups, settings


def draw_landmark(img, x, y, label, radius=16, font=cv2.FONT_HERSHEY_SIMPLEX):
    cv2.circle(img, (x, y), radius, (255, 80, 0), -1, cv2.LINE_AA)
    cv2.circle(img, (x, y), radius + 3, (255, 255, 255), 2, cv2.LINE_AA)

    (tw, th), _ = cv2.getTextSize(label, font, 0.6, 1)

    pad = 5
    bx1, by1 = x + radius + 4, y - th - pad
    bx2, by2 = x + radius + 4 + tw + pad * 2, y + pad

    cv2.rectangle(img, (bx1 - 1, by1 - 1), (bx2 + 1, by2 + 1), (50, 50, 50), -1)
    cv2.rectangle(img, (bx1, by1), (bx2, by2), (255, 255, 255), -1)
    cv2.putText(img, label, (bx1 + pad, y - 2), font, 0.6, (30, 30, 30), 1, cv2.LINE_AA)


_FONT_CANDIDATES_REGULAR: Final[list[str]] = ["segoeui.ttf", "DejaVuSans.ttf"]
_FONT_CANDIDATES_BOLD: Final[list[str]] = ["seguisb.ttf", "DejaVuSans-Bold.ttf"]


def _load_font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()  # type: ignore


def _draw_walking_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color: tuple):
    r = size // 6
    draw.ellipse([cx - r, cy - size // 2, cx + r, cy - size // 2 + 2 * r], fill=color)
    torso_top = (cx, cy - size // 2 + 2 * r)
    torso_bottom = (cx - size // 8, cy)
    draw.line([torso_top, torso_bottom], fill=color, width=max(2, size // 12))
    draw.line([torso_bottom, (cx - size // 3, cy + size // 2)], fill=color, width=max(2, size // 12))
    draw.line([torso_bottom, (cx + size // 4, cy + size // 2 - r // 2)], fill=color, width=max(2, size // 12))


def _draw_ruler_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color: tuple):
    half = size // 2
    p1 = (cx - half, cy + half // 2)
    p2 = (cx + half, cy - half // 2)
    draw.line([p1, p2], fill=color, width=max(3, size // 10))
    for t in (0.25, 0.5, 0.75):
        tx = p1[0] + (p2[0] - p1[0]) * t
        ty = p1[1] + (p2[1] - p1[1]) * t
        draw.line([(tx - 4, ty - 6), (tx + 4, ty + 6)], fill=color, width=2)


def _format_duration_short(seconds: float) -> str:
    total_minutes = int(round(seconds / 60))
    hrs, mins = divmod(total_minutes, 60)
    return f"{hrs} hr {mins:02d} min" if hrs else f"{mins} min"


def render_summary_card(distance_km: float, duration_seconds: float, card_size: tuple[int, int] = (460, 100)) -> np.ndarray:
    w, h = card_size
    scale = 2
    canvas = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    bg_color, text_color, icon_color, divider_color = (250, 250, 250, 235), (40, 40, 40, 255), (80, 80, 80, 255), (210, 210, 210, 255)
    draw.rounded_rectangle([0, 0, w * scale - 1, h * scale - 1], radius=(h * scale) // 2, fill=bg_color)

    font_label = _load_font(_FONT_CANDIDATES_REGULAR, 15 * scale)
    font_value = _load_font(_FONT_CANDIDATES_BOLD, 24 * scale)

    icon_size, pad = 44 * scale, 28 * scale
    _draw_walking_icon(draw, pad + icon_size // 2, h * scale // 2, icon_size, icon_color)

    text_x = pad + icon_size + 14 * scale
    draw.text((text_x, 22 * scale), "Time", font=font_label, fill=text_color)
    draw.text((text_x, 44 * scale), _format_duration_short(duration_seconds), font=font_value, fill=text_color)

    div_x = w * scale // 2
    draw.line([(div_x, 20 * scale), (div_x, h * scale - 20 * scale)], fill=divider_color, width=2 * scale)

    icon_cx2 = div_x + 30 * scale + icon_size // 2
    _draw_ruler_icon(draw, icon_cx2, h * scale // 2, icon_size, icon_color)

    text_x2 = icon_cx2 + icon_size // 2 + 14 * scale
    distance_str = f"{distance_km * 1000:.0f} m" if distance_km < 1 else f"{distance_km:.2f} km"
    draw.text((text_x2, 22 * scale), "Distance", font=font_label, fill=text_color)
    draw.text((text_x2, 44 * scale), distance_str, font=font_value, fill=text_color)

    canvas = canvas.resize((w, h), Image.LANCZOS) # type: ignore
    return np.array(canvas)[:, :, [2, 1, 0, 3]]


def composite_card_on_frame(frame: np.ndarray, card_bgra: np.ndarray, alpha: float, margin: int = 40) -> np.ndarray:
    out = frame.copy()
    h, w = out.shape[:2]
    ch, cw = card_bgra.shape[:2]

    if cw > w - 2 * margin or ch > h - 2 * margin:
        shrink = min((w - 2 * margin) / cw, (h - 2 * margin) / ch)
        card_bgra = cv2.resize(card_bgra, (max(1, int(cw * shrink)), max(1, int(ch * shrink))), interpolation=cv2.INTER_AREA)
        ch, cw = card_bgra.shape[:2]

    x0, y0 = w - cw - margin, h - ch - margin
    card_bgr, card_alpha = card_bgra[:, :, :3].astype(np.float32), (card_bgra[:, :, 3].astype(np.float32) / 255.0) * alpha
    roi = out[y0:y0 + ch, x0:x0 + cw].astype(np.float32)
    out[y0:y0 + ch, x0:x0 + cw] = (card_bgr * card_alpha[..., None] + roi * (1 - card_alpha[..., None])).astype(np.uint8)
    return out


def _open_ffmpeg_writer(output_path: str, w: int, h: int, fps: int) -> subprocess.Popen | None:
    ffmpeg_cmd = _resolve_ffmpeg()
    if ffmpeg_cmd is None:
        return None

    cmd = [
        ffmpeg_cmd, "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", str(fps),
        "-i", "-",
        "-an",
        "-vcodec", "libx264", "-crf", "18", "-preset", "fast",
        "-pix_fmt", "yuv420p", output_path,
    ]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, bufsize=0)


class _FrameSink:
    def __init__(self, output_path: str, w: int, h: int, fps: int):
        self.proc = _open_ffmpeg_writer(output_path, w, h, fps)
        self._fallback_path = None
        self._fallback_writer = None
        if self.proc is None:
            self._fallback_path = tempfile.mktemp(suffix=".avi")
            self._fallback_writer = cv2.VideoWriter(
                self._fallback_path, cv2.VideoWriter_fourcc(*"XVID"), fps, (w, h) # type: ignore
            )
            if not self._fallback_writer.isOpened():
                raise RuntimeError("Neither ffmpeg nor OpenCV VideoWriter is available.")

    def write(self, frame: np.ndarray) -> None:
        if self.proc is not None:
            self.proc.stdin.write(frame.tobytes()) # type: ignore
        else:
            self._fallback_writer.write(frame) # type: ignore

    def release(self, output_path: str) -> str:
        if self.proc is not None:
            self.proc.stdin.close() # type: ignore
            self.proc.wait()
            return output_path
        self._fallback_writer.release() # type: ignore
        if output_path.lower().endswith(".mp4") and reencode_to_h264(self._fallback_path, output_path): # type: ignore
            os.remove(self._fallback_path) # type: ignore
            return output_path
        avi_path = str(Path(output_path).with_suffix(".avi"))
        os.rename(self._fallback_path, avi_path) # type: ignore
        return avi_path


def _prebake_landmark_sprite(label: str, radius: int = 16, font=cv2.FONT_HERSHEY_SIMPLEX) -> tuple[np.ndarray, tuple[int, int]]:
    (tw, th), _ = cv2.getTextSize(label, font, 0.6, 1)
    pad = 5
    sprite_w = radius + 4 + tw + pad * 2 + radius + 4
    sprite_h = max(2 * (radius + 3), th + pad * 2) + 8
    sprite = np.zeros((sprite_h, sprite_w, 4), dtype=np.uint8)

    cx, cy = radius + 4, sprite_h // 2
    cv2.circle(sprite, (cx, cy), radius, (255, 80, 0, 255), -1, cv2.LINE_AA)
    cv2.circle(sprite, (cx, cy), radius + 3, (255, 255, 255, 255), 2, cv2.LINE_AA)

    bx1, by1 = cx + radius + 4, cy - th - pad
    bx2, by2 = bx1 + tw + pad * 2, cy + pad
    cv2.rectangle(sprite, (bx1 - 1, by1 - 1), (bx2 + 1, by2 + 1), (50, 50, 50, 255), -1)
    cv2.rectangle(sprite, (bx1, by1), (bx2, by2), (255, 255, 255, 255), -1)
    cv2.putText(sprite, label, (bx1 + pad, cy - 2), font, 0.6, (30, 30, 30, 255), 1, cv2.LINE_AA)

    return sprite, (cx, cy)


def _blit_sprite(frame: np.ndarray, sprite_bgra: np.ndarray, anchor: tuple[int, int], x: int, y: int) -> None:
    h, w = frame.shape[:2]
    sh, sw = sprite_bgra.shape[:2]
    ox, oy = x - anchor[0], y - anchor[1]
    x0, y0 = max(0, ox), max(0, oy)
    x1, y1 = min(w, ox + sw), min(h, oy + sh)
    if x0 >= x1 or y0 >= y1:
        return
    sx0, sy0 = x0 - ox, y0 - oy
    region = sprite_bgra[sy0:sy0 + (y1 - y0), sx0:sx0 + (x1 - x0)]
    alpha = region[:, :, 3:4].astype(np.float32) / 255.0
    frame[y0:y1, x0:x1] = (region[:, :, :3] * alpha + frame[y0:y1, x0:x1] * (1 - alpha)).astype(np.uint8)


def reencode_to_h264(src: str, dst: str) -> bool:
    ffmpeg_cmd = _resolve_ffmpeg()
    if ffmpeg_cmd is None:
        return False
    try:
        r = subprocess.run(
            [ffmpeg_cmd, "-y", "-i", src, "-vcodec", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p", dst],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return r.returncode == 0
    except FileNotFoundError:
        return False


def render_route_animation(
    img_path: str, points: list, labels: list, popups: list = None, # type: ignore
    output_dir: str = "data\\outputs\\video", fps: int = 30,
    duration_seconds: float = 30.0, line_color: tuple = (0, 200, 255),
    line_thickness: int = 10, marker_color: tuple = (0, 0, 255),
    marker_radius: int = 18, res_sequence: list = None, # type: ignore
    res_duration_per_slice: float = 5.0, pause_seconds: float = 2.0,
    summary: dict = None, summary_hold_seconds: float = 4.0, summary_fade_seconds: float = 0.5, # type: ignore
) -> list[str]:
    
    img = _read_image_safe(img_path)
    if img is None:
        raise FileNotFoundError(f"Cannot read: {img_path}")

    h, w = img.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_paths: list[str] = []

    def _sink_for(filename: str) -> _FrameSink:
        return _FrameSink(str(out_dir / filename), w, h, fps)

    # ==========================================
    # PHASE 1: BIG PICTURE ROUTE  (+ PHASE 2: PAUSE, same file)
    # ==========================================
    num_frames = max(10, int(duration_seconds * fps))
    named = [(int(points[i][0]), int(points[i][1]), labels[i]) for i in range(len(points)) if _is_real_label(labels[i])]

    base_img = img.copy()
    smooth_path = MapFetcher.get_smooth_path(points, num_frames, ease=True)
    path_history: list[tuple[int, int]] = []
    last_frame = base_img.copy()

    active_popups = []
    if popups:
        for i in range(len(points)):
            if popups[i] is not None:
                active_popups.append({
                    "x": points[i][0], 
                    "y": points[i][1], 
                    "data": popups[i], 
                    "label": labels[i],
                    "index": i
                })

    landmark_sprites = {lbl: _prebake_landmark_sprite(lbl) for _, _, lbl in named}
    overview_video = _sink_for("01_overview.mp4")
    print(f"🎬 Rendering Phase 1: Big Picture ({duration_seconds}s)")

    def _render_popup_box(target_frame, popup_info):
        f_frame = target_frame.copy()
        img_url = popup_info["data"].get("popup_image")
        if img_url and os.path.exists(img_url):
            pop_img = _read_image_safe(img_url)
            if pop_img is not None:
                target_img_w = 350
                ph, pw = pop_img.shape[:2]
                pop_img = cv2.resize(pop_img, (target_img_w, int(target_img_w / (pw / ph))))
                ph, pw = pop_img.shape[:2]

                border, label_text = 6, popup_info.get("label")
                text_offset = cv2.getTextSize(label_text, font, 0.6, 1)[0][1] + 15 if _is_real_label(label_text) else 0
                total_w, total_h = pw + (border * 2), ph + (border * 2)

                margin = 40
                box_x = int(popup_info["x"]) - total_w - marker_radius - 4 if popup_info["x"] > w * 0.6 else int(popup_info["x"]) + marker_radius + 4
                box_y = int(popup_info["y"]) + marker_radius + 10 if int(popup_info["y"]) - total_h - text_offset - 10 < margin else int(popup_info["y"]) - total_h - text_offset - 10
                box_x = max(margin, min(box_x, w - total_w - margin))
                box_y = max(margin, min(box_y, h - total_h - margin))

                cv2.rectangle(f_frame, (box_x, box_y), (box_x + total_w, box_y + total_h), (255, 255, 255), -1)
                cv2.rectangle(f_frame, (box_x, box_y), (box_x + total_w, box_y + total_h), (100, 100, 100), 2)
                f_frame[box_y + border:box_y + border + ph, box_x + border:box_x + border + pw] = pop_img
        return f_frame

    def _draw_prioritized_sprites(target_frame, items_to_draw):
        """
        Draws sprites with collision detection. Intermediate waypoints 
        are prioritized over start/stop points if there's an overlap.
        """
        drawn_boxes = []
        # Sort items: Priority 2 for intermediate waypoints, Priority 1 for start/stop (index 0 or last)
        def get_priority(item):
            idx = item.get("index", -1)
            if idx == 0 or idx == len(points) - 1:
                return 1
            return 2

        sorted_items = sorted(items_to_draw, key=get_priority, reverse=True)
        for item in sorted_items:
            lbl = item.get("label")
            if not _is_real_label(lbl) or lbl not in landmark_sprites:
                continue
            sprite, anchor = landmark_sprites[lbl]
            x, y = int(item["x"]), int(item["y"])
            sh, sw = sprite.shape[:2]
            ox, oy = x - anchor[0], y - anchor[1]
            box = (ox, oy, ox + sw, oy + sh)

            overlap = False
            for db in drawn_boxes:
                if not (box[2] <= db[0] or box[0] >= db[2] or box[3] <= db[1] or box[1] >= db[3]):
                    overlap = True
                    break
            if not overlap:
                _blit_sprite(target_frame, sprite, anchor, x, y)
                drawn_boxes.append(box)

    # --- STEP 1: Show Start & Stop Popups first (Intro) ---
    intro_frame = base_img.copy()
    start_stop_popups = [p for p in active_popups if p["index"] == 0 or p["index"] == len(points) - 1]
    
    if start_stop_popups:
        for sp in start_stop_popups:
            sp["data"]["triggered"] = True
            intro_frame = _render_popup_box(intro_frame, sp)

        _draw_prioritized_sprites(intro_frame, start_stop_popups)

        for _ in range(int(2.5 * fps)):
            overview_video.write(intro_frame)

    # --- STEP 2: Animate Line & Trigger Waypoints Dynamically ---
    for p in smooth_path:
        frame = base_img.copy()
        path_history.append((int(p[0]), int(p[1])))

        if len(path_history) > 1:
            cv2.polylines(frame, [np.array(path_history, dtype=np.int32)], False, line_color, line_thickness, cv2.LINE_AA)

        cx_, cy_ = path_history[-1]
        px_, py_ = path_history[-2] if len(path_history) > 1 else path_history[-1]
        
        for popup in active_popups:
            trigger_radius = marker_radius + 6.0
            dist = _point_to_segment_distance(popup["x"], popup["y"], px_, py_, cx_, cy_)
            if dist < trigger_radius and not popup["data"]["triggered"]:
                popup["data"]["triggered"] = True
                freeze_frame = _render_popup_box(frame, popup)
                triggered_popups = [ap for ap in active_popups if ap["data"]["triggered"]]
                _draw_prioritized_sprites(freeze_frame, triggered_popups)
                for _ in range(int(popup["data"]["freeze_seconds"] * fps)):
                    overview_video.write(freeze_frame)

        triggered_popups = [ap for ap in active_popups if ap["data"]["triggered"]]
        _draw_prioritized_sprites(frame, triggered_popups)

        cv2.circle(frame, (cx_, cy_), marker_radius, marker_color, -1, cv2.LINE_AA)
        cv2.circle(frame, (cx_, cy_), marker_radius + 4, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.circle(frame, (cx_, cy_), marker_radius + 7, marker_color, 1, cv2.LINE_AA)

        last_frame = frame
        overview_video.write(frame)

    for _ in range(int(pause_seconds * fps)):
        overview_video.write(last_frame)

    output_paths.append(overview_video.release(str(out_dir / "01_overview.mp4")))

    if popups:
        for p_data in popups:
            if p_data is not None:
                p_data["triggered"] = False

    # ==========================================
    # PHASE 3: RESIDENTIAL MAPS, ONE FILE PER WAYPOINT SEGMENT
    # ==========================================
    if res_sequence:
        for i, res_data in enumerate(res_sequence):
            print(f"🏡 Rendering Residential Map {i + 1}/{len(res_sequence)}")
            res_img = _read_image_safe(res_data["img_path"])
            extent = res_data["extent"]
            chunk_lats = res_data.get("lats", np.array([]))
            chunk_lons = res_data.get("lons", np.array([]))
            res_points = res_data["points"]
            res_labels = res_data["labels"]
            res_popups = res_data.get("popups", [None] * len(res_points))

            if res_img is None:
                continue

            if res_img.shape[:2] != (h, w):
                res_img = cv2.resize(res_img, (w, h))

            res_base = res_img.copy()
            
            total_duration = res_data.get("segment_duration", res_duration_per_slice)
            travel_duration = res_data.get("travel_duration", total_duration)
            pauses = res_data.get("pauses", [])
            
            total_frames = max(10, int(total_duration * fps))
            
            is_paused_per_frame = []
            for current_frame in range(total_frames):
                current_time_sec = current_frame / fps
                is_p = any(p["start"] <= current_time_sec <= p["end"] for p in pauses)
                is_paused_per_frame.append(is_p)

            total_pause_seconds = sum(p["duration"] for p in pauses)
            actual_travel_seconds = max(1.0, travel_duration - total_pause_seconds)
            movement_frames = max(2, int(actual_travel_seconds * fps))

            res_smooth_path = MapFetcher.get_smooth_path(res_points, movement_frames, ease=True)

            res_named = [(int(res_points[j][0]), int(res_points[j][1]), res_labels[j]) for j in range(len(res_points)) if _is_real_label(res_labels[j])]
            active_res_popups = [{"x": res_points[j][0], "y": res_points[j][1], "data": res_popups[j], "label": res_labels[j]} for j in range(len(res_points)) if res_popups[j] is not None]
            res_landmark_sprites = {lbl: _prebake_landmark_sprite(lbl) for _, _, lbl in res_named}

            named_labels = [lbl for _, _, lbl in res_named]
            raw_suffix = named_labels[-1] if named_labels else f"leg{i + 1}"
            safe_suffix = "".join(c for c in str(raw_suffix) if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_") or f"leg{i + 1}"
            chunk_filename = f"02_waypoint_{i + 1:02d}_{safe_suffix}.mp4"
            chunk_video = _sink_for(chunk_filename)

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
                frame = res_base.copy()

                current_chunk_px = res_smooth_path[:path_idx + 1]
                if len(current_chunk_px) > 1:
                    cv2.polylines(frame, [current_chunk_px.astype(np.int32)], False, line_color, line_thickness, cv2.LINE_AA)
                    cx_, cy_ = int(current_chunk_px[-1][0]), int(current_chunk_px[-1][1])
                else:
                    cx_, cy_ = int(p[0]), int(p[1])

                for x, y, lbl in res_named:
                    sprite, anchor = res_landmark_sprites[lbl]
                    _blit_sprite(frame, sprite, anchor, x, y)

                cv2.circle(frame, (cx_, cy_), marker_radius, marker_color, -1, cv2.LINE_AA)
                cv2.circle(frame, (cx_, cy_), marker_radius + 4, (255, 255, 255), 2, cv2.LINE_AA)
                cv2.circle(frame, (cx_, cy_), marker_radius + 7, marker_color, 1, cv2.LINE_AA)

                trigger_radius = marker_radius + 8.0
                for popup in active_res_popups:
                    if popup["data"]["triggered"]:
                        continue
                    near_segment = (
                        prev_cx is not None and
                        _point_to_segment_distance(popup["x"], popup["y"], prev_cx, prev_cy, cx_, cy_) < trigger_radius
                    )
                    if near_segment or just_arrived:
                        popup["data"]["triggered"] = True
                        freeze_frame = frame.copy()
                        img_url = popup["data"].get("popup_image")

                        if img_url and os.path.exists(img_url):
                            pop_img = _read_image_safe(img_url)
                            if pop_img is not None:
                                target_img_w = 350
                                ph, pw = pop_img.shape[:2]
                                pop_img = cv2.resize(pop_img, (target_img_w, int(target_img_w / (pw / ph))))
                                ph, pw = pop_img.shape[:2]

                                border, label_text = 6, popup.get("label")
                                text_offset = cv2.getTextSize(label_text, font, 0.6, 1)[0][1] + 15 if _is_real_label(label_text) else 0 # type: ignore
                                total_w, total_h = pw + (border * 2), ph + (border * 2)

                                margin = 40
                                box_x = int(popup["x"]) - total_w - marker_radius - 4 if popup["x"] > w * 0.6 else int(popup["x"]) + marker_radius + 4
                                box_y = int(popup["y"]) + marker_radius + 10 if int(popup["y"]) - total_h - text_offset - 10 < margin else int(popup["y"]) - total_h - text_offset - 10
                                box_x = max(margin, min(box_x, w - total_w - margin))
                                box_y = max(margin, min(box_y, h - total_h - margin))

                                cv2.rectangle(freeze_frame, (box_x, box_y), (box_x + total_w, box_y + total_h), (255, 255, 255), -1)
                                cv2.rectangle(freeze_frame, (box_x, box_y), (box_x + total_w, box_y + total_h), (100, 100, 100), 2)
                                freeze_frame[box_y + border:box_y + border + ph, box_x + border:box_x + border + pw] = pop_img

                        for _ in range(int(popup["data"]["freeze_seconds"] * fps)):
                            chunk_video.write(freeze_frame)

                chunk_video.write(frame)
                last_frame = frame
                prev_cx, prev_cy = cx_, cy_

            for _ in range(fps):
                chunk_video.write(last_frame)

            output_paths.append(chunk_video.release(str(out_dir / chunk_filename)))
                
    # ==========================================
    # PHASE 4: SUMMARY CARD (own file)
    # ==========================================
    if summary:
        summary_video = _sink_for("03_summary.mp4")
        card = render_summary_card(distance_km=summary.get("total_distance_km", 0.0), duration_seconds=summary.get("total_duration_seconds", 0.0))
        fade_frames = max(1, int(summary_fade_seconds * fps))
        hold_frames = max(0, int(summary_hold_seconds * fps) - fade_frames)

        for i in range(fade_frames):
            summary_video.write(composite_card_on_frame(last_frame, card, alpha=(i + 1) / fade_frames))
        held_frame = composite_card_on_frame(last_frame, card, alpha=1.0)
        for _ in range(hold_frames):
            summary_video.write(held_frame)

        output_paths.append(summary_video.release(str(out_dir / "03_summary.mp4")))

    return output_paths


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--map", required=True)
    parser.add_argument("--route", required=True)
    parser.add_argument("--output", default="data\\outputs\\video", help="Output DIRECTORY")
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
    points, labels, popups, settings = load_route(args.route)

    res_sequence = None
    if args.res_route and args.res_map:
        res_points, res_labels, _, _ = load_route(args.res_route)
        res_sequence = [{"img_path": args.res_map, "points": res_points, "labels": res_labels}]

    summary = json.load(open(args.summary_json, "r", encoding="utf-8")) if args.summary_json else None

    output_files = render_route_animation(
        img_path=args.map, points=points, labels=labels, popups=popups,
        output_dir=args.output, fps=args.fps or settings.get("fps", 30),
        duration_seconds=args.duration or settings.get("duration_seconds", 8),
        line_thickness=args.thickness or settings.get("line_thickness", 10),
        marker_radius=args.radius or settings.get("marker_radius", 18),
        res_sequence=res_sequence, res_duration_per_slice=args.res_duration, # type: ignore
        pause_seconds=args.pause, summary=summary, # type: ignore
        summary_hold_seconds=args.summary_hold, summary_fade_seconds=args.summary_fade,
    )
    print(f"✅ Rendered {len(output_files)} file(s):")
    for f in output_files:
        print(f"   {f}")


if __name__ == "__main__":
    main()