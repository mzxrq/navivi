"""
Route2VDO Service (route2vdo.py)
"""
'''
This module provides a service for converting route data into video format. It is designed to
be used within the Tauri application framework, allowing for seamless integration with the
frontend.

How to Use:
    r2v = Route2VDO(map_fetcher, file_handler)
    output_paths = r2v.render_route_animation(img_path, points, labels, ...)
'''

# Import necessary modules
import os
import logging
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Import custom services
from filehandler import FileHandler
from mapfetcher import MapFetcher
from frame_sink import FrameSink


# Define path for the FFMPEG executable (bundled alongside this module)
FFMPEG_PATH = Path(__file__).parent / "FFmpeg" / "bin" / "ffmpeg.exe"


<<<<<<< HEAD
class Route2VDO:
    """
    A class to convert route data into video format.
    """

    # =========================
    # Initialization
    # =========================
    def __init__(self, map_fetcher: MapFetcher, file_handler: FileHandler):
        self.map_fetcher = map_fetcher
        self.file_handler = file_handler
        self.font = cv2.FONT_HERSHEY_SIMPLEX

    # ========================
    # Resolve ffmpeg path
    # ========================
    def resolve_ffmpeg_path(self) -> Path:
        """Resolve the path to the FFMPEG executable."""
        if FFMPEG_PATH.exists():
            return FFMPEG_PATH
        raise FileNotFoundError(f"FFMPEG executable not found at {FFMPEG_PATH}")
=======
def _is_real_label(lbl) -> bool:
    if lbl is None:
        return False
    if isinstance(lbl, float) and math.isnan(lbl):
        return False
    return str(lbl).strip() != ""
>>>>>>> chore/backend-unit-testing

    # ========================
    # Geometry helpers
    # ========================
    @staticmethod
    def _point_to_segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
        """Calculate the distance from point P(px, py) to the line segment AB(ax, ay)-(bx, by)."""

        # 1. Handle degenerate case where A and B are the same point
        abx, aby = bx - ax, by - ay

        # 2. Compute the squared length of segment AB
        seg_len_sq = abx * abx + aby * aby

        # 3. If the segment is a point, return distance from P to A
        if seg_len_sq < 1e-9:
            return float(np.hypot(px - ax, py - ay))

        # 4. Project point P onto the line defined by A and B, clamping to the segment
        t = max(0.0, min(1.0, ((px - ax) * abx + (py - ay) * aby) / seg_len_sq))

        # 5. Compute the closest point on the segment and return the distance
        closest_x, closest_y = ax + t * abx, ay + t * aby

        # 6. Return the Euclidean distance from P to the closest point on the segment
        return float(np.hypot(px - closest_x, py - closest_y))

    @staticmethod
    def latlon_to_pixel(lats: np.ndarray, lons: np.ndarray, extent: tuple, img_w: int, img_h: int) -> np.ndarray:
        """Convert lat and lng to pixel coordinates within a specific tile."""

        # 1. Handle empty input arrays
        if len(lats) == 0:
            return np.empty((0, 2), dtype=np.float32)

        # 2. Unpack the extent and compute Mercator projection
        min_x, max_x, min_y, max_y = extent

        # 3. Convert lat/lon to Mercator coordinates
        r = 6378137.0
        mx = lons * (r * np.pi / 180.0)
        my = np.log(np.tan((90.0 + lats) * np.pi / 360.0)) * r
        px = (mx - min_x) / (max_x - min_x) * img_w
        py = (max_y - my) / (max_y - min_y) * img_h

        # 4. Return pixel coordinates as a 2D array
        return np.column_stack([px, py])

    # ========================
    # Label / drawing helpers
    # ========================
    @staticmethod
    def _is_real_label(label: Optional[str]) -> bool:
        """
        True if `label` is a usable, non-placeholder waypoint label.

        NOTE: this helper was referenced throughout the animation-rendering code but its
        original implementation wasn't present in the uploaded file. This is a reasonable
        reconstruction (rejects None/empty/whitespace and common placeholder tokens) —
        replace with your original logic if it differs.
        """

        # 1. Check for None or empty string
        if not label:
            return False

        # 2. Strip whitespace and check for common placeholder tokens
        text = str(label).strip()

        # 3. Return False for known placeholder values, True otherwise
        if not text or text.lower() in {"none", "null", "unnamed", "n/a", "-"}:
            return False

        # 4. If it passes all checks, consider it a real label
        return True

    @staticmethod
    def draw_waypoint_labels(image: np.ndarray, waypoints: List[Dict[str, Any]], extent: tuple) -> np.ndarray:
        """Draw waypoint labels on the image."""

        # 1. Get image dimensions
        img_h, img_w = image.shape[:2]

        # 2. Loop through waypoints and draw labels
        for wp in waypoints:
            # 2.1 Extract lat, lng, and label safely
            lat = float(wp.get('lat') or wp.get('latitude') or 0.0)
            lon = float(wp.get('lon') or wp.get('lng') or wp.get('longitude') or 0.0)
            label = wp.get('label', '')
        # 3. Return the modified image with labels
        return image

    @staticmethod
    def draw_walking_person_icons(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color: tuple) -> None:
        """Draw a simple walking-person icon on the image."""

        # 1. Draw the head as a circle
        r = size // 6
        draw.ellipse([cx - r, cy - size // 2, cx + r, cy - size // 2 + 2 * r], fill=color)

        # 2. Draw the torso and legs as lines
        torso_top = (cx, cy - size // 2 + 2 * r)
        torso_bottom = (cx - size // 8, cy)

        # 3. Draw the torso and legs with appropriate line widths
        draw.line([torso_top, torso_bottom], fill=color, width=max(2, size // 12))
        draw.line([torso_bottom, (cx - size // 3, cy + size // 2)], fill=color, width=max(2, size // 12))
        draw.line([torso_bottom, (cx + size // 4, cy + size // 2 - r // 2)], fill=color, width=max(2, size // 12))

    @staticmethod
    def draw_ruler_icon(draw: ImageDraw.ImageDraw, extent: tuple, img_w: int, img_h: int, color: tuple) -> None:
        """Draw a ruler icon on the image."""

        # 1. Unpack the extent and compute the center point in pixel coordinates
        min_x, max_x, min_y, max_y = extent
        lat_center = (min_y + max_y) / 2
        lon_center = (min_x + max_x) / 2

        # 2. Convert the center lat/lon to pixel coordinates
        pixel_coords = Route2VDO.latlon_to_pixel(np.array([lat_center]), np.array([lon_center]), extent, img_w, img_h)

        # 3. Draw the ruler icon as a simple crosshair at the center point
        cx, cy = int(pixel_coords[0][0]), int(pixel_coords[0][1])
        size = min(img_w, img_h) // 10

        # 4. Draw the crosshair lines with appropriate width
        draw.line([cx - size // 2, cy, cx + size // 2, cy], fill=color, width=max(2, size // 20))
        draw.line([cx - size // 2, cy - size // 10, cx - size // 2, cy + size // 10], fill=color, width=max(2, size // 20))
        draw.line([cx + size // 2, cy - size // 10, cx + size // 2, cy + size // 10], fill=color, width=max(2, size // 20))

    @staticmethod
    def format_duration(duration: float) -> str:
        """Format a duration in seconds into a human-readable string."""

        # 1. Handle durations less than a minute
        if duration < 60:
            return f"{duration:.1f} sec"

        # 2. Handle durations less than an hour
        elif duration < 3600:
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            return f"{minutes} min {seconds} sec"

        # 3. Handle durations of an hour or more
        else:
            hours = int(duration // 3600)
            minutes = int((duration % 3600) // 60)
            return f"{hours} hr {minutes} min"

    @staticmethod
    def render_summary_card(image: np.ndarray, summary_data: Dict[str, Any], extent: Optional[tuple] = None) -> np.ndarray:
        """Render a summary card (key/value list in a white box) onto a copy of `image`."""

        # 1. Get image dimensions and define card size and position
        img_h, img_w = image.shape[:2]
        card_width, card_height = img_w // 4, img_h // 6
        card_x, card_y = img_w - card_width - 10, 10

        # 2. Draw the white card with a black border
        cv2.rectangle(image, (card_x, card_y), (card_x + card_width, card_y + card_height), (255, 255, 255), -1)
        cv2.rectangle(image, (card_x, card_y), (card_x + card_width, card_y + card_height), (0, 0, 0), 2)

        # 3. Draw each key/value pair inside the card with appropriate spacing
        font_scale = 0.5
        font_thickness = 1
        line_height = int(20 * font_scale) + 15

        # 4. Loop through the summary data and draw each line of text
        for i, (key, value) in enumerate(summary_data.items()):
            text = f"{key}: {value}"
            text_x = card_x + 10
            text_y = card_y + 20 + i * line_height
            cv2.putText(image, text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 0, 0), font_thickness)

        # 5. Optionally draw the extent box if provided
        if extent:
            x1, y1, x2, y2 = extent
            cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)

        # 6. Return the modified image with the summary card
        return image

    @staticmethod
    def composite_video_frame(image: np.ndarray, overlays: List[np.ndarray]) -> np.ndarray:
        """Composite a list of same-size overlays onto `image` with fixed 0.5 weighting."""

        # 1. Loop through each overlay and alpha-blend it onto the base image
        for overlay in overlays:
            image = cv2.addWeighted(image, 1, overlay, 0.5, 0)

        # 2. Return the final composited image
        return image

    # ========================
    # Landmark sprite helpers
    # ========================
    @staticmethod
    def _prebake_landmark_sprite(label: str, pin_color: tuple = (0, 0, 255)) -> Tuple[np.ndarray, Tuple[int, int]]:
        """
        Build a small pin-shaped BGRA sprite with the label text, and return
        (sprite, anchor) where `anchor` is the (x, y) point within the sprite that
        should be aligned to the waypoint's pixel coordinate (the tip of the pin).

        NOTE: like `_is_real_label`, this was referenced by the animation code but its
        original implementation wasn't in the uploaded file. This is a reasonable
        reconstruction — swap in your original asset-based sprite loader if you have one.
        """

        # 1. Define the pin dimensions and text padding
        pin_w, pin_h = 30, 40
        pad_top = 20
        text = str(label)

        # 2. Load a default font for the label text
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None

        # 3. Measure the text size using PIL's ImageDraw
        dummy = Image.new("RGBA", (1, 1))
        ddraw = ImageDraw.Draw(dummy)

<<<<<<< HEAD
        # 4. Calculate the bounding box of the text to determine its width and height
        if font is not None:
            bbox = ddraw.textbbox((0, 0), text, font=font)
            text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
=======
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
                self._fallback_path, cv2.VideoWriter_fourcc(*"XVID"), fps, (w, h) # type: ignore
            )
            if not self._fallback_writer.isOpened():
                raise RuntimeError("Neither ffmpeg nor OpenCV VideoWriter is available.")

    def write(self, frame: np.ndarray) -> None:
        if self.proc is not None:
            # .tobytes() is a single contiguous memcpy — cheap relative
            # to the encode work itself.
            self.proc.stdin.write(frame.tobytes()) # type: ignore
>>>>>>> chore/backend-unit-testing
        else:
            text_w, text_h = len(text) * 6, 10

        # 5. Calculate the overall canvas size to accommodate both the pin and the text
        canvas_w = max(pin_w, text_w + 4)
        canvas_h = pad_top + text_h + 4 + pin_h

        # 6. Create a transparent RGBA image for the sprite and prepare to draw on it
        sprite = Image.new("RGBA", (int(canvas_w), int(canvas_h)), (0, 0, 0, 0))
        draw = ImageDraw.Draw(sprite)

<<<<<<< HEAD
        # 7. Draw the pin shape (circle + triangle) in the specified color
        # Draw the circular part of the pin and the triangular tip
        cx = int(canvas_w // 2)
        circle_cy = pad_top + text_h + 4 + (pin_h - pin_w // 2) // 2
        r = pin_w // 2
        bgra_color = (pin_color[2], pin_color[1], pin_color[0], 255) 
=======
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
>>>>>>> chore/backend-unit-testing

        draw.ellipse([cx - r, circle_cy - r, cx + r, circle_cy + r], fill=bgra_color, outline=(255, 255, 255, 255), width=2)

        # Draw the triangular tip of the pin
        tip = (cx, int(canvas_h - 1))

        draw.polygon([(cx - r * 0.6, circle_cy + r * 0.4), (cx + r * 0.6, circle_cy + r * 0.4), tip], fill=bgra_color)

        # 8. Draw the label text centered above the pin
        if font is not None:
            draw.text((cx - text_w / 2, 0), text, fill=(0, 0, 0, 255), font=font)

<<<<<<< HEAD
        # 9. Convert the PIL image to a NumPy array in BGRA format and return it along with the anchor point
        sprite_bgra = cv2.cvtColor(np.array(sprite), cv2.COLOR_RGBA2BGRA)
        anchor = (cx, tip[1])
=======
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
>>>>>>> chore/backend-unit-testing

        # 10. Return the sprite and the anchor point for alignment
        return sprite_bgra, anchor

    @staticmethod
    def _blit_sprite(frame: np.ndarray, sprite: np.ndarray, anchor: Tuple[int, int], x: int, y: int) -> None:
        """Alpha-composite a BGRA `sprite` onto `frame` (BGR) so that `anchor` lands at (x, y)."""

        # 1. Get the dimensions of the sprite and calculate the offset for placement
        sh, sw = sprite.shape[:2]
        ox, oy = x - anchor[0], y - anchor[1]

<<<<<<< HEAD
        # 2. Determine the region of the frame where the sprite will be drawn, handling clipping
        frame_h, frame_w = frame.shape[:2]
        src_x0, src_y0 = max(0, -ox), max(0, -oy)
        dst_x0, dst_y0 = max(0, ox), max(0, oy)
        dst_x1 = min(frame_w, ox + sw)
        dst_y1 = min(frame_h, oy + sh)

        # 3. If the destination region is invalid (no overlap), return early
        if dst_x1 <= dst_x0 or dst_y1 <= dst_y0:
            return

        # 4. Calculate the corresponding source region of the sprite to be drawn
        src_x1 = src_x0 + (dst_x1 - dst_x0)
        src_y1 = src_y0 + (dst_y1 - dst_y0)

        # 5. Extract the relevant region of the sprite and compute the alpha mask for blending
        sprite_region = sprite[src_y0:src_y1, src_x0:src_x1]
        alpha = (sprite_region[:, :, 3:4].astype(np.float32)) / 255.0
        frame_region = frame[dst_y0:dst_y1, dst_x0:dst_x1]
        blended = frame_region.astype(np.float32) * (1 - alpha) + sprite_region[:, :, :3].astype(np.float32) * alpha
        frame[dst_y0:dst_y1, dst_x0:dst_x1] = blended.astype(np.uint8)

    @staticmethod
    def _draw_position_marker(frame: np.ndarray, cx: int, cy: int, marker_color: tuple, marker_radius: int) -> None:
        """Draws the traveling dot marker (fill + white ring + outline ring)."""
        
        # 1. Force absolute primitive scalar integer conversion via float rounding
        # This completely guarantees clean primitive integers for strict OpenCV signatures
        x_val = int(round(float(cx)))
        y_val = int(round(float(cy)))
        
        # 2. Use a list sequence to satisfy strict cv::Point bindings in newer OpenCV builds
        center = [x_val, y_val]
        radius = int(round(float(marker_radius)))
        
        # 3. Force color into a pure primitive integer tuple
        color = (int(marker_color[0]), int(marker_color[1]), int(marker_color[2]))

        # 4. Draw the filled circle for the marker (using standard line type fallback if LINE_AA overloads)
        try:
            cv2.circle(frame, center, radius, color, -1, cv2.LINE_AA)
            cv2.circle(frame, center, radius + 4, (255, 255, 255), 2, cv2.LINE_AA)
            cv2.circle(frame, center, radius + 7, (0, 0, 0), 1, cv2.LINE_AA)
        except Exception:
            # Safe fallback if strict keyword/lineType matching fails on the sequence signature
            cv2.circle(frame, center, radius, color, -1)
            cv2.circle(frame, center, radius + 4, (255, 255, 255), 2)
            cv2.circle(frame, center, radius + 7, (0, 0, 0), 1)
    
    # ========================
    # Image / IO helpers
    # ========================
    @staticmethod
    def read_image_safe(image_path) -> Optional[np.ndarray]:
        """Safely read an image from the given path. Returns None if it can't be read."""
=======
def render_route_animation(
    img_path: str, points: list, labels: list, popups: list = None, # type: ignore
    output_dir: str = "data\\outputs\\video", fps: int = 30,
    duration_seconds: float = 8.0, line_color: tuple = (0, 200, 255),
    line_thickness: int = 10, marker_color: tuple = (0, 0, 255),
    marker_radius: int = 18, res_sequence: list = None, # type: ignore
    res_duration_per_slice: float = 5.0, pause_seconds: float = 2.0,
    summary: dict = None, summary_hold_seconds: float = 4.0, summary_fade_seconds: float = 0.5, # type: ignore
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
>>>>>>> chore/backend-unit-testing

        # 1. Check if the image path exists
        if not os.path.exists(image_path):
            logging.warning(f"Image path does not exist: {image_path}")
            return None

        # 2. Attempt to read the image using OpenCV and handle any exceptions
        try:
            # Read the image using OpenCV
            image = cv2.imread(str(image_path))

<<<<<<< HEAD
            # Check if the image was successfully read
            if image is None:
                logging.warning(f"Image at {image_path} could not be read.")
=======
    def _sink_for(filename: str) -> _FrameSink:
        # Every phase gets its own ffmpeg subprocess/container instead of
        # one writer spanning the whole animation — see docstring above.
        return _FrameSink(str(out_dir / filename), w, h, fps)
>>>>>>> chore/backend-unit-testing

            # Return the image (or None if it couldn't be read)
            return image

<<<<<<< HEAD
        # 3. Catch any exceptions that occur during reading and log the error
        except Exception as e:
            logging.error(f"Error reading image at {image_path}: {e}")
            return None

    @staticmethod
    def load_font(font_path: Path, font_size: int) -> ImageFont.FreeTypeFont:
        """Load a font for text rendering. Raises an error if the font cannot be loaded."""

        # 1. Attempt to load the font using PIL's ImageFont
        try:
            return ImageFont.truetype(str(font_path), font_size)
        
        # 2. Catch any exceptions that occur during font loading and log the error
        except Exception as e:
            logging.error(f"Error loading font from {font_path}: {e}")
            raise

    def open_ffmpeg_process(self, output_path: Path, fps: int, width: int, height: int) -> subprocess.Popen:
        """Open a raw FFMPEG process for video encoding (kept for callers that need direct access)."""

        # 1. Construct the FFMPEG command with the appropriate parameters for raw video input and H.264 output
        ffmpeg_cmd = [
            str(self.resolve_ffmpeg_path()),
            '-y',
            '-f', 'rawvideo',
            '-vcodec', 'rawvideo',
            '-pix_fmt', 'bgr24',
            '-s', f'{width}x{height}',
            '-r', str(fps),
            '-i', '-',
            '-an',
            '-vcodec', 'libx264',
            '-pix_fmt', 'yuv420p',
            str(output_path)
        ]

        # 2. Attempt to open the FFMPEG process and return the Popen object
        try:
            return subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)
        except Exception as e:
            logging.error(f"Error opening FFMPEG process for {output_path}: {e}")
            raise

    # =========================
    # Route animation — popup / sprite drawing
    # =========================
    def _render_popup_box(self, target_frame: np.ndarray, popup_info: dict, w: int, h: int, marker_radius: int, font) -> np.ndarray:
        """
        Draws the white info-box (with optional image) for a triggered popup.
        Shared by both the overview phase and the residential-segment phase.
        """

        # 1. Make a copy of the target frame to draw on
        f_frame = target_frame.copy()
        img_url = popup_info["data"].get("popup_image")

        # 2. Check if the image URL exists and is valid; if not, return the frame as-is
        if not (img_url and os.path.exists(img_url)):
            return f_frame

        # 3. Safely read the image from the provided URL
        pop_img = self.read_image_safe(img_url)

        # 4. If the image could not be read, return the frame as-is
        if pop_img is None:
            return f_frame

        # 5. Resize the popup image to a target width while maintaining aspect ratio
        target_img_w = 350
        ph, pw = pop_img.shape[:2]

        pop_img = cv2.resize(pop_img, (target_img_w, int(target_img_w / (pw / ph))))

        # 6. Get the new dimensions of the resized popup image
        ph, pw = pop_img.shape[:2]

        # 7. Calculate the border size and retrieve the label text from the popup info
        border, label_text = 6, popup_info.get("label")
        text_offset = cv2.getTextSize(str(label_text or ""), font, 0.6, 1)[0][1] + 15 if self._is_real_label(label_text) else 0
        total_w, total_h = pw + (border * 2), ph + (border * 2)

        # 8. If there is a label, calculate the total height to include the text
        if text_offset > 0:
            total_h += text_offset
        
        # 9. Calculate the position of the popup box, ensuring it stays within the frame boundaries
        margin = 40

        # 10. Determine the x-coordinate of the popup box based on its position relative to the frame width
        box_x = int(popup_info["x"]) - total_w - marker_radius - 4 if popup_info["x"] > w * 0.6 else int(popup_info["x"]) + marker_radius + 4
        box_y = int(popup_info["y"]) + marker_radius + 10 if int(popup_info["y"]) - total_h - text_offset - 10 < margin else int(popup_info["y"]) - total_h - text_offset - 10
        box_x = max(margin, min(box_x, w - total_w - margin))
        box_y = max(margin, min(box_y, h - total_h - margin))

        # 11. Draw the white background rectangle for the popup box and its border
        cv2.rectangle(f_frame, (box_x, box_y), (box_x + total_w, box_y + total_h), (255, 255, 255), -1)
        cv2.rectangle(f_frame, (box_x, box_y), (box_x + total_w, box_y + total_h), (100, 100, 100), 2)

        # 12. If there is a label, draw the label text above the popup box
        if text_offset > 0:
            cv2.putText(f_frame, str(label_text), (box_x + border, box_y - 10), font, 0.6, (0, 0, 0), 1, cv2.LINE_AA)
        
        # 13. Blit the resized popup image onto the frame within the popup box, accounting for the border
        f_frame[box_y + border:box_y + border + ph, box_x + border:box_x + border + pw] = pop_img

        # 14. Return the modified frame with the popup box drawn
        return f_frame

    def _draw_prioritized_sprites(self, target_frame: np.ndarray, items_to_draw: list, points: list, landmark_sprites: dict) -> None:
        """
        Draws sprites with collision detection. Intermediate waypoints
        are prioritized over start/stop points if there's an overlap.
        """

        # 1. Initialize a list to keep track of drawn bounding boxes for collision detection
        drawn_boxes = []

        # 2. Define a helper function to determine the drawing priority of each item
        def get_priority(item):
            # 2.1 Assign a priority based on whether the item is a start/stop point or an intermediate waypoint
            idx = item.get("index", -1)

            # 2.2 Return a priority value: 1 for start/stop points, 2 for intermediate waypoints
            return 1 if idx == 0 or idx == len(points) - 1 else 2

        # 3. Sort the items to draw based on their priority, with higher priority items drawn first
        sorted_items = sorted(items_to_draw, key=get_priority, reverse=True)

        # 4. Loop through the sorted items and draw each sprite if it doesn't overlap with previously drawn sprites
        for item in sorted_items:
            # 4.1 Get the label of the item and check if it's a real label and has a corresponding sprite
            lbl = item.get("label")

            # 4.2 If the label is not real or doesn't have a sprite, skip to the next item
            if not self._is_real_label(lbl) or lbl not in landmark_sprites:
                continue

            # 4.3 Retrieve the sprite and its anchor point for the current label
            sprite, anchor = landmark_sprites[lbl]

            # 4.4 Calculate the position of the sprite based on the item's coordinates and the anchor point
            x, y = int(item["x"]), int(item["y"])
            sh, sw = sprite.shape[:2]

            # 4.5 Calculate the bounding box of the sprite in the target frame
            ox, oy = x - anchor[0], y - anchor[1]
            box = (ox, oy, ox + sw, oy + sh)

            # 4.6 Check for overlap with previously drawn boxes to avoid collisions
            overlap = any(
                not (box[2] <= db[0] or box[0] >= db[2] or box[3] <= db[1] or box[1] >= db[3])
                for db in drawn_boxes
            )

            # 4.7 If there is no overlap, blit the sprite onto the target frame and add the box to the drawn list
            if not overlap:
                self._blit_sprite(target_frame, sprite, anchor, x, y)
                drawn_boxes.append(box)

    # =========================
    # Route animation — Phase 1 (overview + pause)
    # =========================
    def _render_phase1_overview(
        self, img, points, labels, popups, out_dir, w, h, fps, font,
        line_color, line_thickness, marker_color, marker_radius,
        duration_seconds, pause_seconds,
    ):
        """
        PHASE 1: Big picture route animation (+ PHASE 2 pause, same file).
        Returns (output_path, last_frame).
        """

        # 1. Calculate the number of frames for the overview animation based on duration and FPS
        num_frames = max(10, int(duration_seconds * fps))

        # 2. Filter the points and labels to include only those with real labels for sprite rendering
        named = [(int(points[i][0]), int(points[i][1]), labels[i]) for i in range(len(points)) if self._is_real_label(labels[i])]

        # 3. Create a copy of the base image to draw on and generate a smoothed path for the animation
        base_img = img.copy()

        # 4. Generate a smoothed path from the given points for smoother animation
        smooth_path = self.map_fetcher.get_smoothed_path(points, num_frames)
        
        # 5. Initialize a list to keep track of the path history for drawing the route line
        path_history: List[Tuple[int, int]] = []

        # 6. Initialize the last frame variable to the base image
        last_frame = base_img.copy()

        # 7. Prepare the list of active popups by filtering out None values and associating them with their coordinates and labels
        active_popups = []

        # 7.1 If there are popups, loop through the points and add the corresponding popup information to the active_popups list
        if popups:
            for i in range(len(points)):
                if popups[i] is not None:
                    active_popups.append({
                        "x": points[i][0],
                        "y": points[i][1],
                        "data": popups[i],
                        "label": labels[i],
                        "index": i,
                    })

        # 8. Pre-bake landmark sprites for all real labels to optimize rendering
        landmark_sprites = {lbl: self._prebake_landmark_sprite(lbl) for _, _, lbl in named}
=======
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
>>>>>>> chore/backend-unit-testing

        # 9. Initialize the video writer for the overview phase
        overview_video = FrameSink(os.path.join(out_dir, "01_overview.mp4"), w, h, fps, FFMPEG_PATH)

        # 10. Log the rendering phase and duration for debugging purposes
        logging.info(f"Rendering Phase 1: Big Picture ({duration_seconds}s)")

<<<<<<< HEAD
=======
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
>>>>>>> chore/backend-unit-testing

        # =========================================================
        # Render the overview animation with popups and route line
        # =========================================================

        # --- STEP 1: Show Start & Stop Popups first (Intro) ---

<<<<<<< HEAD
        # 1.1 Create a copy of the base image for the intro frame and filter the active popups to include only the start and stop points
        intro_frame = base_img.copy()

        # 1.2 Filter the active popups to include only those at the start (index 0) and stop (last index) points
        start_stop_popups = [p for p in active_popups if p["index"] == 0 or p["index"] == len(points) - 1]

        # 1.3 If there are start/stop popups, render them on the intro frame and write the frames to the video for a brief duration
        if start_stop_popups:
            # 1.3.1 Mark the start/stop popups as triggered and render their popup boxes on the intro frame
            for sp in start_stop_popups:
                # Mark the popup as triggered to prevent it from being rendered again during the main animation
                sp["data"]["triggered"] = True

                # 1.3.2 Render the popup box for the start/stop popup on the intro frame
                intro_frame = self._render_popup_box(intro_frame, sp, w, h, marker_radius, font)

            # 1.3.3 Draw the prioritized sprites (start/stop popups) on the intro frame
            self._draw_prioritized_sprites(intro_frame, start_stop_popups, points, landmark_sprites)

            # 1.3.4 Write the intro frame to the video for a brief duration (2.5 seconds) to allow viewers to see the start/stop popups
            for _ in range(int(2.5 * fps)):
                # Write the intro frame to the video for a brief duration (2.5 seconds) to allow viewers to see the start/stop popups
                overview_video.write(intro_frame)

        # --- STEP 2: Animate Line & Trigger Waypoints Dynamically ---

        # 2.1 Loop through the smoothed path points to animate the route line and trigger popups dynamically as the marker moves along the path
        for p in smooth_path:
            # 2.1.1 Create a copy of the base image for the current frame and append the current point to the path history
            frame = base_img.copy()

            # 2.1.2 Append the current point (x, y) to the path history for drawing the route line
            path_history.append((int(p[0]), int(p[1])))
=======
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
>>>>>>> chore/backend-unit-testing

            # 2.1.3 Draw the route line on the current frame using the path history if there are at least two points in the history
            if len(path_history) > 1:
                # Draw the route line on the current frame using the path history with anti-aliasing for smoother appearance
                cv2.polylines(frame, [np.array(path_history, dtype=np.int32)], False, line_color, line_thickness, cv2.LINE_AA)

            # 2.1.4 Get the current and previous coordinates from the path history for distance calculations
            cx_, cy_ = path_history[-1]
            px_, py_ = path_history[-2] if len(path_history) > 1 else path_history[-1]

<<<<<<< HEAD
            # 2.1.5 Loop through the active popups to check if any should be triggered based on the current marker position
            for popup in active_popups:
                # 2.1.5.1 Calculate the distance from the current marker position to the popup's position and determine if it should be triggered based on the trigger radius
                trigger_radius = marker_radius + 6.0

                # 2.1.5.2 Calculate the distance from the current marker position to the popup's position
                dist = self._point_to_segment_distance(popup["x"], popup["y"], px_, py_, cx_, cy_)

                # 2.1.5.3 Check if the distance is within the trigger radius and the popup hasn't been triggered yet
                if dist < trigger_radius and not popup["data"]["triggered"]:
                    # Trigger the popup and create a freeze frame
                    popup["data"]["triggered"] = True

                    # Create a freeze frame for the triggered popup
                    freeze_frame = self._render_popup_box(frame, popup, w, h, marker_radius, font)

                    # Draw the triggered popups on the freeze frame and write it to the video for the specified freeze duration
                    triggered_popups = [ap for ap in active_popups if ap["data"]["triggered"]]

                    self._draw_prioritized_sprites(freeze_frame, triggered_popups, points, landmark_sprites)

                    # Write the freeze frame to the video for the specified freeze duration (in seconds) multiplied by the frames per second (fps)
                    for _ in range(int(popup["data"]["freeze_seconds"] * fps)):
                        overview_video.write(freeze_frame)

            # 2.1.6 After checking for triggered popups, draw the triggered popups on the current frame and write it to the video
            triggered_popups = [ap for ap in active_popups if ap["data"]["triggered"]]

            self._draw_prioritized_sprites(frame, triggered_popups, points, landmark_sprites)

            # 2.1.7 Draw the position marker (traveling dot) on the current frame at the current marker position
            self._draw_position_marker(frame,cx_, cy_, marker_color, marker_radius)

            # 2.1.8 Update the last frame variable to the current frame and write it to the video
            last_frame = frame

            overview_video.write(frame)

        # --- STEP 3: Pause at the end of the overview animation ---
        # 3.1 After the overview animation is complete, write the last frame to the video for the specified pause duration (in seconds) multiplied by the frames per second (fps)
        for _ in range(int(pause_seconds * fps)):
            # Write the last frame to the video for the specified pause duration (in seconds) multiplied by the frames per second (fps)
            overview_video.write(last_frame)

        # 4. Release the video writer and return the output path and last frame
        output_path = overview_video.release(str(out_dir / "01_overview.mp4"))

        # 5. Return the output path of the generated video and the last frame for further processing
        return output_path, last_frame

    # =========================
    # Route animation — Phase 3 (residential segments)
    # =========================
    def _render_residential_segment(
        self, i, res_data, out_dir, w, h, fps, font,
        line_color, line_thickness, marker_color, marker_radius,
        res_duration_per_slice,
    ):
        """
        PHASE 3 (single segment): renders one residential waypoint video file.
        Returns (output_path, last_frame) or (None, None) if the image is unreadable.
        """

        # 1. Log the rendering of the residential map segment for debugging purposes
        logging.info(f"Rendering Residential Map {i + 1}")

        # 2. Safely read the base image for the residential segment; if it fails, return None
        res_img = self.read_image_safe(res_data["img_path"])

        if res_img is None:
            return None, None

        # 3. Extract points, labels, and popups from the residential data; if popups are not provided, create a list of None values
        res_points = res_data["points"]
        res_labels = res_data["labels"]
        res_popups = res_data.get("popups", [None] * len(res_points))

        # 4. Resize the residential image to the specified width and height if it doesn't match the target dimensions
        if res_img.shape[:2] != (h, w):
            res_img = cv2.resize(res_img, (w, h))

        # 5. Create a copy of the resized residential image to use as the base frame for rendering
        res_base = res_img.copy()

        # 6. Extract the total duration, travel duration, and pauses from the residential data; if not provided, use default values
        total_duration = res_data.get("segment_duration", res_duration_per_slice)
        travel_duration = res_data.get("travel_duration", total_duration)
        pauses = res_data.get("pauses", [])

        # 7. Calculate the total number of frames for the residential segment based on the total duration and frames per second (fps)
        total_frames = max(10, int(total_duration * fps))

        # 8. Precompute a list indicating whether each frame is within a pause period based on the provided pauses
        is_paused_per_frame = []

        # 9. Loop through each frame index and determine if it falls within any of the defined pause intervals
        for current_frame in range(total_frames):
            # 9.1 Calculate the current time in seconds for the current frame based on the frame index and frames per second (fps)
            current_time_sec = current_frame / fps
            is_p = any(p["start"] <= current_time_sec <= p["end"] for p in pauses)
            is_paused_per_frame.append(is_p)

        # 10. Calculate the total pause duration in seconds by summing the durations of all defined pauses
        total_pause_seconds = sum(p["duration"] for p in pauses)
        actual_travel_seconds = max(1.0, travel_duration - total_pause_seconds)
        movement_frames = max(2, int(actual_travel_seconds * fps))

        # 11. Generate a smoothed path for the residential segment based on the provided points and the calculated number of movement frames
        res_smooth_path = self.map_fetcher.get_smoothed_path(res_points, movement_frames)

        # 12. Prepare the list of named points (x, y, label) for real labels and the list of active popups with their coordinates and data
        res_named = [(int(res_points[j][0]), int(res_points[j][1]), res_labels[j]) for j in range(len(res_points)) if self._is_real_label(res_labels[j])]

        # 13. Prepare the list of active popups by filtering out None values and associating them with their coordinates, data, and labels
        active_res_popups = [
            {"x": res_points[j][0], "y": res_points[j][1], "data": res_popups[j], "label": res_labels[j]}
            for j in range(len(res_points)) if res_popups[j] is not None
        ]

        # 14. Pre-bake landmark sprites for all real labels in the residential segment to optimize rendering
        res_landmark_sprites = {lbl: self._prebake_landmark_sprite(lbl) for _, _, lbl in res_named}

        # 15. Generate a safe filename for the residential segment video based on the last named label or a default name if no labels are present
        named_labels = [lbl for _, _, lbl in res_named]
        raw_suffix = named_labels[-1] if named_labels else f"leg{i + 1}"
        safe_suffix = "".join(c for c in str(raw_suffix) if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_") or f"leg{i + 1}"
        chunk_filename = f"02_waypoint_{i + 1:02d}_{safe_suffix}.mp4"

        chunk_output_path = os.path.join(out_dir, chunk_filename)
        chunk_video = FrameSink(chunk_output_path, w, h, fps, FFMPEG_PATH)

        # 16. Initialize the path index, previous coordinates, and last frame for rendering the residential segment
        path_idx = 0
        prev_cx, prev_cy = None, None

        # 17. Loop through each frame index for the residential segment, updating the path index based on whether the current frame is paused or not, and rendering the route line, position marker, and triggered popups accordingly
        last_frame = res_base.copy()

        for current_frame in range(total_frames):
            # 17.1 Determine if the current frame is within a pause period based on the precomputed list of paused frames
            is_paused = is_paused_per_frame[current_frame]

            # 17.2 Initialize a flag to indicate whether the marker has just arrived at the end of the path
            just_arrived = False

            # 17.3 If the current frame is not paused and the path index is less than the last index of the smoothed path, increment the path index to move the marker along the path
            if not is_paused and path_idx < len(res_smooth_path) - 1:
                # 17.3.1 Increment the path index to move the marker along the smoothed path
                path_idx += 1

                # 17.3.2 If the path index has reached the last index of the smoothed path, set the just_arrived flag to True to indicate that the marker has reached its destination
                if path_idx == len(res_smooth_path) - 1:
                    just_arrived = True

            # 17.4 Get the current point from the smoothed path based on the updated path index and create a copy of the base frame for rendering
            p = res_smooth_path[path_idx]

            # 17.5 Create a copy of the base frame for rendering the current frame of the residential segment
            frame = res_base.copy()

            # 17.6 Get the current chunk of the smoothed path up to the current path index for drawing the route line
            current_chunk_px = res_smooth_path[:path_idx + 1]

            # 17.7 Draw the route line on the current frame using the current chunk of the smoothed path if there are at least two points in the chunk
            if len(current_chunk_px) > 1:
                # 17.7.1 Draw the route line on the current frame using the current chunk of the smoothed path with anti-aliasing for smoother appearance
                cv2.polylines(frame, [current_chunk_px.astype(np.int32)], False, line_color, line_thickness, cv2.LINE_AA)

                # 17.7.2 Get the current coordinates (cx_, cy_) from the last point in the current chunk of the smoothed path for drawing the position marker
                cx_, cy_ = int(current_chunk_px[-1][0]), int(current_chunk_px[-1][1])
            else:
                # 17.7.3 If there is only one point in the current chunk, get the current coordinates (cx_, cy_) from that point for drawing the position marker
                cx_, cy_ = int(p[0]), int(p[1])

            # 17.8 Loop through the named points in the residential segment and blit their corresponding sprites onto the current frame at their respective coordinates
            for x, y, lbl in res_named:
                # 17.8.1 Retrieve the pre-baked sprite and anchor point for the current label from the landmark sprites dictionary
                sprite, anchor = res_landmark_sprites[lbl]

                # 17.8.2 Blit the sprite onto the current frame at the specified coordinates (x, y) using the anchor point for alignment
                self._blit_sprite(frame, sprite, anchor, x, y)

            # 17.9 Draw the position marker (traveling dot) on the current frame at the current coordinates (cx_, cy_) with the specified marker color and radius
            self._draw_position_marker(frame, cx_, cy_, marker_color, marker_radius)

            # 17.10 Calculate the trigger radius for popups based on the marker radius and an additional offset
            trigger_radius = marker_radius + 8.0

            # 17.11 Loop through the active popups in the residential segment to check if any should be triggered based on the current marker position and the trigger radius
            for popup in active_res_popups:
                # 17.11.1 If the popup has already been triggered, skip to the next popup
                if popup["data"]["triggered"]:
                    continue

                # 17.11.2 Safely extract popup coordinates
                popup_x = float(popup.get("x") or 0.0)
                popup_y = float(popup.get("y") or 0.0)

                # 17.11.3 Ensure prev_cx and prev_cy are not None and convert them to float safely
                if prev_cx is not None and prev_cy is not None:
                    p1_x = float(prev_cx)
                    p1_y = float(prev_cy)
                    
                    # 17.11.4 Now compute distance safely knowing no value is None
                    near_segment = (
                        self._point_to_segment_distance(popup_x, popup_y, p1_x, p1_y, cx_, cy_) < trigger_radius
                    )
                else:
                    near_segment = False
=======
                for popup in active_res_popups:
                    if np.hypot(cx_ - popup["x"], cy_ - popup["y"]) < 30.0 and not popup["data"]["triggered"]:
                        popup["data"]["triggered"] = True
                        freeze_frame = frame.copy()
                        img_url = popup["data"].get("popup_image")
>>>>>>> chore/backend-unit-testing

                # 17.11.5 If the marker is near the popup segment or has just arrived at the end of the path, trigger the popup and create a freeze frame
                if near_segment or just_arrived:
                    popup["data"]["triggered"] = True
                    freeze_frame = self._render_popup_box(frame, popup, w, h, marker_radius, font)
                    for _ in range(int(popup["data"]["freeze_seconds"] * fps)):
                        chunk_video.write(freeze_frame)

            # 17.12 Write the current frame to the video and update the last frame and previous coordinates for the next iteration
            chunk_video.write(frame)

            # 17.13 Update the last frame and previous coordinates for the next iteration
            last_frame = frame
            prev_cx, prev_cy = cx_, cy_

        # 18. After the residential segment animation is complete, write the last frame to the video for a brief duration (1 second) to allow viewers to see the final state
        for _ in range(fps):
            chunk_video.write(last_frame)

        # 19. Release the video writer for the residential segment and return the output path and last frame for further processing
        output_path = chunk_video.release(str(out_dir / chunk_filename))

<<<<<<< HEAD
        return output_path, last_frame
=======
                chunk_video.write(frame)
                last_frame = frame
>>>>>>> chore/backend-unit-testing

    def _render_phase3_residential(
        self, res_sequence, out_dir, w, h, fps, font,
        line_color, line_thickness, marker_color,
        marker_radius, res_duration_per_slice, fallback_last_frame,
    ):
        """PHASE 3: renders one file per waypoint segment. Returns (output_paths, last_frame)."""
        output_paths = []
        last_frame = fallback_last_frame

<<<<<<< HEAD
        for i, res_data in enumerate(res_sequence):
            path, seg_last_frame = self._render_residential_segment(
                i, res_data, out_dir, w, h, fps, font,
                line_color, line_thickness, marker_color, marker_radius,
                res_duration_per_slice,
            )
            if path is None:
                continue
            output_paths.append(path)
            last_frame = seg_last_frame

        return output_paths, last_frame

    # =========================
    # Route animation — Phase 4 (summary card)
    # =========================
    def _render_phase4_summary(
        self, summary, out_dir, w, h, fps, last_frame,
        summary_hold_seconds, summary_fade_seconds,
    ):
        """PHASE 4: renders the summary-card video (fade in, then hold). Returns output_path."""

        # 1. Initialize the video writer for the summary card phase with the specified output path, width, height, frames per second (fps), and FFMPEG path
        summary_video = FrameSink(os.path.join(out_dir, "03_summary.mp4"), w, h, fps, FFMPEG_PATH)

        # 2. Prepare the summary data to be displayed on the summary card, including total distance and formatted duration
        summary_data = {
            "Distance": f"{summary.get('total_distance_km', 0.0):.2f} km",
            "Duration": self.format_duration(summary.get("total_duration_seconds", 0.0)),
        }

        # 3. Render the summary card frame by calling the render_summary_card method with a copy of the last frame and the prepared summary data
        card_frame = self.render_summary_card(last_frame.copy(), summary_data)

        # 4. Calculate the number of frames for the fade-in effect and the hold duration based on the specified summary fade seconds, summary hold seconds, and frames per second (fps)
=======
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
>>>>>>> chore/backend-unit-testing
        fade_frames = max(1, int(summary_fade_seconds * fps))
        hold_frames = max(0, int(summary_hold_seconds * fps) - fade_frames)
        
        # 5. Loop through the fade frames to create a fade-in effect by blending the last frame with the summary card frame using weighted addition, and write each blended frame to the video
        for i in range(fade_frames):
            # Calculate the alpha value for blending based on the current frame index and total fade frames
            alpha = (i + 1) / fade_frames

            # Blend the last frame and the summary card frame using weighted addition to create a fade-in effect
            blended = cv2.addWeighted(last_frame, 1 - alpha, card_frame, alpha, 0)

            # Write the blended frame to the video for the fade-in effect
            summary_video.write(blended)

        # 6. Loop through the hold frames to display the summary card frame for the specified hold duration, and write each frame to the video
        for _ in range(hold_frames):
            # Write the summary card frame to the video for the specified hold duration
            summary_video.write(card_frame)

        # 7. Release the video writer for the summary card phase and return the output path of the generated video
        return summary_video.release(str(out_dir / "03_summary.mp4"))

    # =========================
    # Route animation — orchestration
    # =========================
    def render_route_animation(
        self,
        img_path: str, points: list, labels: list, popups: Optional[list] = None,
        output_dir: str = "data/outputs/video", fps: int = 30,
        duration_seconds: float = 30.0, line_color: tuple = (0, 200, 255),
        line_thickness: int = 10, marker_color: tuple = (0, 0, 255),
        marker_radius: int = 18, res_sequence: Optional[list] = None,
        res_duration_per_slice: float = 5.0, pause_seconds: float = 2.0,
        summary: Optional[dict] = None, summary_hold_seconds: float = 4.0, summary_fade_seconds: float = 0.5,
    ) -> List[str]:
        """
        Renders a full route animation: overview (phase 1+2), one clip per residential
        waypoint segment (phase 3), and an optional summary card (phase 4).
        Returns the list of output video file paths, in render order.
        """

        # 1. Safely read the base image from the provided image path; if it fails, raise a FileNotFoundError
        img = self.read_image_safe(img_path)

<<<<<<< HEAD
        # 2. If the image could not be read (img is None), raise a FileNotFoundError with a descriptive message
        if img is None:
            raise FileNotFoundError(f"Cannot read: {img_path}")
=======
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
>>>>>>> chore/backend-unit-testing

        # 3. Extract the height and width of the image and retrieve the font to be used for rendering text
        h, w = img.shape[:2]    
        font = self.font

        # 4. Create the output directory if it doesn't exist, and initialize an empty list to store the output video file paths
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        output_paths: List[str] = []

        # 5. PHASE 1 + 2: overview route animation & pause
        overview_path, last_frame = self._render_phase1_overview(
            img, points, labels, popups, out_dir, w, h, fps, font,
            line_color, line_thickness, marker_color, marker_radius,
            duration_seconds, pause_seconds,
        )
        output_paths.append(overview_path)

        if popups:
            for p_data in popups:
                if p_data is not None:
                    p_data["triggered"] = False

        # 6. PHASE 3: residential maps, one file per waypoint segment
        if res_sequence:
            res_paths, last_frame = self._render_phase3_residential(
                res_sequence, out_dir, w, h, fps, font,
                line_color, line_thickness, marker_color, marker_radius,
                res_duration_per_slice, last_frame,
            )
            output_paths.extend(res_paths)

        # 7. PHASE 4: summary card
        if summary:
            summary_path = self._render_phase4_summary(
                summary, out_dir, w, h, fps, last_frame,
                summary_hold_seconds, summary_fade_seconds,
            )
            output_paths.append(summary_path)

        return output_paths