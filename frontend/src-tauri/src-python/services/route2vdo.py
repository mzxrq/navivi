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

    canvas = canvas.resize((w, h), Image.LANCZOS)
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


# def _get_exact_path(pts_list: list, frames: int) -> np.ndarray:
#     filtered_pts = [pts_list[0]]
#     for p in pts_list[1:]:
#         if np.hypot(p[0] - filtered_pts[-1][0], p[1] - filtered_pts[-1][1]) > 0.1:
#             filtered_pts.append(p)

#     pts = np.array(filtered_pts, dtype=float)
#     diffs = np.diff(pts, axis=0)
#     dists = np.hypot(diffs[:, 0], diffs[:, 1])
#     cum_dists = np.concatenate(([0], np.cumsum(dists)))
#     total_dist = cum_dists[-1]

#     t = cum_dists / total_dist if total_dist > 0 else np.linspace(0, 1, len(pts))
#     t_fine = np.linspace(0, 1, frames)

#     k = min(3, len(pts) - 1)
#     sx = make_interp_spline(t, pts[:, 0], k=max(1, k))
#     sy = make_interp_spline(t, pts[:, 1], k=max(1, k))
#     return np.vstack([sx(t_fine), sy(t_fine)]).T


def _open_ffmpeg_writer(output_path: str, w: int, h: int, fps: int) -> subprocess.Popen | None:
    """
    Opens a persistent ffmpeg subprocess that reads raw BGR24 frames from
    stdin and encodes directly to H.264, one pass, no intermediate file.

    Why this matters: the previous design wrote every frame twice —
    once as a raw/XVID .avi via cv2.VideoWriter, then a *second* full
    decode+encode pass via a separate ffmpeg subprocess.run() call.
    That's O(2 * frame_count) of heavy image I/O and codec work for a
    single logical operation. Streaming raw frames straight into libx264
    collapses this to O(frame_count) with no disk round-trip for the
    intermediate representation.
    """
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
    # bufsize=0: no Python-side buffering of the pipe, so backpressure
    # from a slow encoder propagates immediately to the writer loop
    # instead of silently ballooning memory.
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, bufsize=0)


class _FrameSink:
    """
    Drop-in replacement for cv2.VideoWriter's .write()/.release() surface.
    Streams frames directly into a single-pass ffmpeg H.264 encode when
    ffmpeg is available; falls back to the legacy AVI + reencode_to_h264
    path only when it isn't, so behavior on ffmpeg-less machines is
    unchanged.
    """
    def __init__(self, output_path: str, w: int, h: int, fps: int):
        self.proc = _open_ffmpeg_writer(output_path, w, h, fps)
        self._fallback_path = None
        self._fallback_writer = None
        if self.proc is None:
            self._fallback_path = tempfile.mktemp(suffix=".avi")
            self._fallback_writer = cv2.VideoWriter(
                self._fallback_path, cv2.VideoWriter_fourcc(*"XVID"), fps, (w, h)
            )
            if not self._fallback_writer.isOpened():
                raise RuntimeError("Neither ffmpeg nor OpenCV VideoWriter is available.")

    def write(self, frame: np.ndarray) -> None:
        if self.proc is not None:
            # .tobytes() is a single contiguous memcpy — cheap relative
            # to the encode work itself.
            self.proc.stdin.write(frame.tobytes())
        else:
            self._fallback_writer.write(frame)

    def release(self, output_path: str) -> str:
        if self.proc is not None:
            self.proc.stdin.close()
            self.proc.wait()
            return output_path
        self._fallback_writer.release()
        if output_path.lower().endswith(".mp4") and reencode_to_h264(self._fallback_path, output_path):
            os.remove(self._fallback_path)
            return output_path
        avi_path = str(Path(output_path).with_suffix(".avi"))
        os.rename(self._fallback_path, avi_path)
        return avi_path


def _prebake_landmark_sprite(label: str, radius: int = 16, font=cv2.FONT_HERSHEY_SIMPLEX) -> tuple[np.ndarray, tuple[int, int]]:
    """
    Renders a landmark's marker+label as a standalone BGRA sprite ONE TIME,
    outside the frame loop. Label text and box geometry are invariant
    across every frame they appear in, so recomputing cv2.getTextSize /
    cv2.putText / cv2.rectangle per-frame is pure waste — this hoists
    that loop-invariant work out of the hot path.

    Returns (sprite, anchor) where anchor is the (x, y) offset within
    the sprite that corresponds to the landmark's true map coordinate,
    so callers can alpha-blit it directly at (map_x, map_y).
    """
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
    """In-place alpha blit of a prebaked sprite — bounded-region float
    multiply-add, no glyph rasterization or shape recompute per call."""
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
    img_path: str, points: list, labels: list, popups: list = None,
    output_dir: str = "data\\outputs\\video", fps: int = 30,
    duration_seconds: float = 8.0, line_color: tuple = (0, 200, 255),
    line_thickness: int = 10, marker_color: tuple = (0, 0, 255),
    marker_radius: int = 18, res_sequence: list = None,
    res_duration_per_slice: float = 5.0, pause_seconds: float = 2.0,
    summary: dict = None, summary_hold_seconds: float = 4.0, summary_fade_seconds: float = 0.5,
) -> list[str]:
    """
    Renders the navigation animation as SEPARATE video files instead of
    one continuous MP4:
      01_overview.mp4               - Phase 1 (big picture) + Phase 2 (pause)
      02_waypoint_XX_<label>.mp4    - one file per residential chunk (Phase 3)
      03_summary.mp4                - Phase 4 (summary card), if `summary` given

    Splitting into separate files (rather than one _FrameSink spanning
    the whole timeline) means each phase gets its own ffmpeg encode
    process and its own container — useful for downstream consumers
    that want to play/re-order/drop individual legs (e.g. a frontend
    stepping through "leg 2 of 4") without re-cutting a monolithic MP4.

    Returns the list of output file paths in playback order.
    """
    img = _read_image_safe(img_path)
    if img is None:
        raise FileNotFoundError(f"Cannot read: {img_path}")

    h, w = img.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_paths: list[str] = []

    def _sink_for(filename: str) -> _FrameSink:
        # Every phase gets its own ffmpeg subprocess/container instead of
        # one writer spanning the whole animation — see docstring above.
        return _FrameSink(str(out_dir / filename), w, h, fps)

    # ==========================================
    # PHASE 1: BIG PICTURE ROUTE  (+ PHASE 2: PAUSE, same file)
    # ==========================================
    num_frames = max(10, int(duration_seconds * fps))
    named = [(int(points[i][0]), int(points[i][1]), labels[i]) for i in range(len(points)) if _is_real_label(labels[i])]

    base_img = img.copy()
    # ease=True: deliberate deceleration into landmarks/turns rather than
    # constant-speed traversal — see MapFetcher.get_smooth_path.
    smooth_path = MapFetcher.get_smooth_path(points, num_frames, ease=True)
    path_history: list[tuple[int, int]] = []
    last_frame = base_img.copy()

    active_popups = []
    if popups:
        for i in range(len(points)):
            if popups[i] is not None:
                active_popups.append({"x": points[i][0], "y": points[i][1], "data": popups[i], "label": labels[i]})

    # Bake each landmark's marker+label once — label text and geometry
    # never change across the `num_frames` iterations below, so this
    # replaces O(frames * landmarks) putText/getTextSize/rectangle calls
    # with O(landmarks) bakes + cheap per-frame alpha blits.
    landmark_sprites = {lbl: _prebake_landmark_sprite(lbl) for _, _, lbl in named}

    overview_video = _sink_for("01_overview.mp4")
    print(f"🎬 Rendering Phase 1: Big Picture ({duration_seconds}s)")
    for p in smooth_path:
        frame = base_img.copy()
        path_history.append((int(p[0]), int(p[1])))

        if len(path_history) > 1:
            cv2.polylines(frame, [np.array(path_history, dtype=np.int32)], False, line_color, line_thickness, cv2.LINE_AA)

        for x, y, lbl in named:
            sprite, anchor = landmark_sprites[lbl]
            _blit_sprite(frame, sprite, anchor, x, y)

        cx_, cy_ = path_history[-1]
        cv2.circle(frame, (cx_, cy_), marker_radius, marker_color, -1, cv2.LINE_AA)
        cv2.circle(frame, (cx_, cy_), marker_radius + 4, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.circle(frame, (cx_, cy_), marker_radius + 7, marker_color, 1, cv2.LINE_AA)

        for popup in active_popups:
            if np.hypot(p[0] - popup["x"], p[1] - popup["y"]) < 5.0 and not popup["data"]["triggered"]:
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
                        text_offset = cv2.getTextSize(label_text, font, 0.6, 1)[0][1] + 15 if _is_real_label(label_text) else 0
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
                    overview_video.write(freeze_frame)

        last_frame = frame
        overview_video.write(frame)

    # Phase 2 (pause) rides in the SAME file as Phase 1 — it's a hold on
    # the overview's final frame, not a distinct navigational unit, so
    # splitting it out as its own file would just add a near-static clip
    # with no content of its own.
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
        historical_lats, historical_lons = [], []

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
            # Distance-proportional duration (falls back to the flat
            # res_duration_per_slice if the caller didn't supply a
            # per-chunk value) so long stretches get more screen time
            # and short hops stay brisk, while averaging to the
            # target seconds/waypoint across the whole route.
            chunk_duration = res_data.get("segment_duration", res_duration_per_slice)
            res_frames = max(10, int(chunk_duration * fps))

            # ease=True gives the marker a deliberate, decelerating
            # arrival into each waypoint instead of constant-speed
            # travel — this is what actually reads as "slow"
            # regardless of how many seconds are allocated.
            res_smooth_path = MapFetcher.get_smooth_path(res_points, res_frames, ease=True)

            res_named = [(int(res_points[j][0]), int(res_points[j][1]), res_labels[j]) for j in range(len(res_points)) if _is_real_label(res_labels[j])]
            active_res_popups = [{"x": res_points[j][0], "y": res_points[j][1], "data": res_popups[j], "label": res_labels[j]} for j in range(len(res_points)) if res_popups[j] is not None]

            # Same hoist-out-of-loop rationale as Phase 1: bake once
            # per residential chunk, blit per frame.
            res_landmark_sprites = {lbl: _prebake_landmark_sprite(lbl) for _, _, lbl in res_named}

            # Filesystem-safe label suffix for the filename — falls back
            # to a plain index if every point in this chunk is unlabeled.
            named_labels = [lbl for _, _, lbl in res_named]
            raw_suffix = named_labels[-1] if named_labels else f"leg{i + 1}"
            safe_suffix = "".join(c for c in str(raw_suffix) if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_") or f"leg{i + 1}"
            chunk_filename = f"02_waypoint_{i + 1:02d}_{safe_suffix}.mp4"
            chunk_video = _sink_for(chunk_filename)

            for f_idx, p in enumerate(res_smooth_path):
                frame = res_base.copy()

                # 1. Draw historical paths from previous chunks smoothly
                if len(historical_lats) > 0:
                    hist_px = _project_latlons_to_pixels(np.array(historical_lats), np.array(historical_lons), extent, w, h)
                    if len(hist_px) > 1:
                        cv2.polylines(frame, [hist_px.astype(np.int32)], False, line_color, line_thickness, cv2.LINE_AA)

                # 2. Draw current chunk's path smoothly up to current frame index
                current_chunk_px = res_smooth_path[:f_idx + 1]
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

                for popup in active_res_popups:
                    if np.hypot(cx_ - popup["x"], cy_ - popup["y"]) < 30.0 and not popup["data"]["triggered"]:
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
                                text_offset = cv2.getTextSize(label_text, font, 0.6, 1)[0][1] + 15 if _is_real_label(label_text) else 0
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

            for _ in range(fps):
                chunk_video.write(last_frame)

            output_paths.append(chunk_video.release(str(out_dir / chunk_filename)))

            if len(chunk_lats) > 0:
                historical_lats.extend(chunk_lats)
                historical_lons.extend(chunk_lons)

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
    parser.add_argument("--output", default="data\\outputs\\video", help="Output DIRECTORY — render_route_animation now writes multiple files (01_overview.mp4, 02_waypoint_XX_*.mp4, 03_summary.mp4) into this directory instead of a single file.")
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
        res_sequence=res_sequence, res_duration_per_slice=args.res_duration,
        pause_seconds=args.pause, summary=summary,
        summary_hold_seconds=args.summary_hold, summary_fade_seconds=args.summary_fade,
    )
    print(f"✅ Rendered {len(output_files)} file(s):")
    for f in output_files:
        print(f"   {f}")


if __name__ == "__main__":
    main()