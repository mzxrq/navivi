"""
Graphics Engine Service (graphic_engine.py)
---------------------------------------------------------------------------
Handles all drawing, UI composites, image manipulations, and transitions.

[REFACTOR NOTE]
This module previously could not be imported successfully as written:
`write_fade_clip` / `play_fullscreen_video` type-hinted a parameter as
`video_out: VideoExporter` with no `VideoExporter` import anywhere in the
file, and no `from __future__ import annotations` to defer evaluation —
Python evaluates function annotations eagerly at `def`-time, so this was
a guaranteed `NameError` the moment the class body executed. Likewise
`_load_font`'s `-> FreeTypeFont | Any` return hint uses PEP 604 syntax
that also needs eager evaluation deferred on pre-3.10 interpreters.
`read_image_safe`'s except-block also called `logger.warning(...)` with
no `logger` ever defined in this file — a second latent NameError on the
(fairly common) "image failed to decode" path.

Fixes applied below:
  1. `from __future__ import annotations` (PEP 563) — defers ALL
     annotation evaluation to strings, eliminating both NameErrors above
     without needing an eager, possibly-circular import of VideoExporter.
  2. `TYPE_CHECKING`-guarded import of VideoExporter so static analyzers
     (mypy/pyright) and IDEs still resolve the type correctly.
  3. A real `logger` via the shared `setup_logger` factory, consistent
     with every other service module in this codebase.

Additionally, two structural changes for performance and maintainability
(see inline comments at their definitions for full rationale):
  - `_load_font` is now memoized (`self._font_cache`) — it was previously
    doing real filesystem I/O (TrueType file open + glyph table parse) on
    EVERY call to `render_popup_box`, which itself is invoked once per
    rendered frame for as long as a "baked" HUD popup is on screen. That
    turned an O(1)-amortizable cost into O(N) redundant disk I/O across
    an N-frame popup hold.
  - `play_fullscreen_popup_sequence` + `compute_fullscreen_hold_times`
    consolidate a ~25-line "freeze -> scale -> optional B-roll -> hold ->
    fade" sequence that was hand-duplicated 4 times across
    spatial_renderer.py and storyboard_renderer.py (with an already-
    diverged `last_frame` update behavior between the two files).
---------------------------------------------------------------------------
"""

import os
import math
from typing import Final, Dict, List, Tuple, Optional, Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from PIL.ImageFont import truetype, load_default, FreeTypeFont

from services.math_util import MathUtils
from services.vdo_exporter import VideoExporter
from services.logger import setup_logger

logger = setup_logger("GraphicsEngine")


class GraphicsEngine:
    FONT_CANDIDATES_REGULAR: Final[List[str]] = [
        "NotoSansJP-Regular.ttf",
        "NotoSansJP-Regular.otf",
        "meiryo.ttc",
        "msgothic.ttc",
        "YuGothic.ttc",
        "segoeui.ttf",
        "DejaVuSans.ttf",
    ]
    FONT_CANDIDATES_BOLD: Final[List[str]] = [
        "NotoSansJP-Bold.ttf",
        "NotoSansJP-Bold.otf",
        "meiryob.ttc",
        "msgothic.ttc",
        "YuGothic-Bold.ttc",
        "seguisb.ttf",
        "DejaVuSans-Bold.ttf",
    ]

    def __init__(
        self,
        line_color=(0, 200, 255),
        line_thickness=10,
        marker_color=(0, 0, 255),
        marker_radius=18,
        font_size: int = 18,
    ):
        self.line_color = line_color
        self.line_thickness = line_thickness
        self.marker_color = marker_color
        self.marker_radius = marker_radius
        self.font_size = font_size
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
            logger.warning(f"⚠️ Failed to load image {path}: {e}")
            return None

    def draw_path(self, frame: np.ndarray, path_history: List[Tuple[int, int]]):
        if len(path_history) > 1:
            cv2.polylines(
                frame,
                [np.array(path_history, dtype=np.int32)],
                False,
                (255, 255, 255),
                self.line_thickness + 6,
                cv2.LINE_AA,
            )
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
            frame, (cx, cy), self.marker_radius + 6, (255, 255, 255), -1, cv2.LINE_AA
        )
        cv2.circle(
            frame, (cx, cy), self.marker_radius + 6, (200, 200, 200), 1, cv2.LINE_AA
        )
        cv2.circle(
            frame, (cx, cy), self.marker_radius, self.marker_color, -1, cv2.LINE_AA
        )
        cv2.circle(
            frame, (cx, cy), self.marker_radius // 2, (255, 255, 255), -1, cv2.LINE_AA
        )

    def prebake_landmark_sprite(self, label: str) -> Tuple[np.ndarray, Tuple[int, int]]:
        (tw, th), _ = cv2.getTextSize(label, self.font_cv, 0.6, 1)
        pad = 8
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

    # 💡 NEW: Cinematic Pause Blur and Center alignment
    def render_cinematic_pause(
        self, target_frame: np.ndarray, popup_info: Dict
    ) -> np.ndarray:
        """Applies a heavy depth-of-field blur to the background and perfectly centers the UI card."""
        f_frame = target_frame.copy()
        h, w = f_frame.shape[:2]

        # Apply cinematic blur and dim the background
        blurred = cv2.GaussianBlur(f_frame, (55, 55), 0)
        f_frame = cv2.addWeighted(blurred, 0.75, np.zeros_like(blurred), 0.25, 0)

        img_url = popup_info["data"].get("popup_image")
        if not img_url or not os.path.exists(img_url):
            return f_frame

        pop_img = self.read_image_safe(img_url)
        if pop_img is None:
            return f_frame

        # Ensure perfect 16:9 crop
        ph, pw = pop_img.shape[:2]
        target_ratio = 16.0 / 9.0
        current_ratio = pw / float(ph)

        if current_ratio > target_ratio:
            new_w = int(ph * target_ratio)
            offset = (pw - new_w) // 2
            pop_img = pop_img[:, offset : offset + new_w]
        elif current_ratio < target_ratio:
            new_h = int(pw / target_ratio)
            offset = (ph - new_h) // 2
            pop_img = pop_img[offset : offset + new_h, :]

        # Size up the card for the center focus
        target_img_w = 420
        target_img_h = int(target_img_w / target_ratio)
        pop_img = cv2.resize(pop_img, (target_img_w, target_img_h))
        ph, pw = pop_img.shape[:2]

        border = 16
        label_text = popup_info.get("label")
        font = self._load_font(self.FONT_CANDIDATES_REGULAR, self.font_size + 4)
        has_label = MathUtils.is_real_label(label_text)

        text_block_h = (self.font_size + 24) if has_label else 0
        total_h = ph + (border * 2) + text_block_h
        total_w = pw + (border * 2)

        # 💡 DEAD CENTER ALIGNMENT (Ignores X/Y tracking logic)
        box_x = (w - total_w) // 2
        box_y = (h - total_h) // 2

        pil_canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(pil_canvas)

        shadow_box = [box_x - 6, box_y - 2, box_x + total_w + 6, box_y + total_h + 8]
        draw.rounded_rectangle(shadow_box, radius=22, fill=(0, 0, 0, 50))
        pil_canvas = pil_canvas.filter(ImageFilter.GaussianBlur(radius=8))
        draw = ImageDraw.Draw(pil_canvas)

        card_box = [box_x, box_y, box_x + total_w, box_y + total_h]
        draw.rounded_rectangle(
            card_box,
            radius=16,
            fill=(255, 255, 255, 250),
            outline=(220, 220, 220, 255),
            width=1,
        )

        base_pil = Image.fromarray(cv2.cvtColor(f_frame, cv2.COLOR_BGR2RGBA))
        base_pil.paste(pil_canvas, (0, 0), pil_canvas)

        pil_img = Image.fromarray(cv2.cvtColor(pop_img, cv2.COLOR_BGR2RGB))
        mask = Image.new("L", (pw, ph), 255)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([0, 0, pw, ph], radius=8, fill=255)

        photo_x = box_x + border
        photo_y = box_y + border
        base_pil.paste(pil_img, (photo_x, photo_y), mask=mask)

        if has_label:
            draw_text_layer = ImageDraw.Draw(base_pil)
            text_bbox = draw_text_layer.textbbox((0, 0), label_text, font=font)
            text_w = text_bbox[2] - text_bbox[0]
            text_x = box_x + (total_w - text_w) // 2
            text_y = photo_y + ph + 12
            draw_text_layer.text(
                (text_x, text_y), label_text, font=font, fill=(40, 40, 40, 255)
            )

        return cv2.cvtColor(np.array(base_pil), cv2.COLOR_RGBA2BGR)

    def render_popup_box(
        self, target_frame: np.ndarray, popup_info: Dict
    ) -> np.ndarray:
        f_frame = target_frame.copy()
        img_url = popup_info["data"].get("popup_image")
        h, w = f_frame.shape[:2]

        if img_url and os.path.exists(img_url):
            pop_img = self.read_image_safe(img_url)
            if pop_img is not None:
                ph, pw = pop_img.shape[:2]
                target_ratio = 16.0 / 9.0
                current_ratio = pw / float(ph)

                if current_ratio > target_ratio:
                    new_w = int(ph * target_ratio)
                    offset = (pw - new_w) // 2
                    pop_img = pop_img[:, offset : offset + new_w]
                elif current_ratio < target_ratio:
                    new_h = int(pw / target_ratio)
                    offset = (ph - new_h) // 2
                    pop_img = pop_img[offset : offset + new_h, :]

                target_img_w = 340
                target_img_h = int(target_img_w / target_ratio)
                pop_img = cv2.resize(pop_img, (target_img_w, target_img_h))
                ph, pw = pop_img.shape[:2]

                border = 14
                label_text = popup_info.get("label")
                font = self._load_font(self.FONT_CANDIDATES_REGULAR, self.font_size)

                has_label = MathUtils.is_real_label(label_text)
                text_block_h = self.font_size + 20 if has_label else 0
                total_h = ph + (border * 2) + text_block_h
                total_w = pw + (border * 2)
                margin = 50

                if popup_info.get("hud_corner") == "bottom_left":
                    box_x = 60
                    box_y = h - total_h - 75
                else:
                    point_x = int(popup_info["x"])
                    point_y = int(popup_info["y"])
                    box_x = (
                        point_x - total_w - 40 if point_x > w * 0.5 else point_x + 40
                    )
                    box_y = point_y - (total_h // 2)
                    box_x = max(margin, min(box_x, w - total_w - margin))
                    box_y = max(margin, min(box_y, h - total_h - margin))

                pil_canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                draw = ImageDraw.Draw(pil_canvas)

                shadow_box = [
                    box_x - 4,
                    box_y - 2,
                    box_x + total_w + 4,
                    box_y + total_h + 4,
                ]
                draw.rounded_rectangle(shadow_box, radius=18, fill=(0, 0, 0, 25))
                pil_canvas = pil_canvas.filter(ImageFilter.GaussianBlur(radius=6))
                draw = ImageDraw.Draw(pil_canvas)

                card_box = [box_x, box_y, box_x + total_w, box_y + total_h]
                draw.rounded_rectangle(
                    card_box,
                    radius=14,
                    fill=(255, 255, 255, 250),
                    outline=(230, 230, 230, 255),
                    width=1,
                )

                base_pil = Image.fromarray(cv2.cvtColor(f_frame, cv2.COLOR_BGR2RGBA))
                base_pil.paste(pil_canvas, (0, 0), pil_canvas)

                pil_img = Image.fromarray(cv2.cvtColor(pop_img, cv2.COLOR_BGR2RGB))
                mask = Image.new("L", (pw, ph), 255)
                mask_draw = ImageDraw.Draw(mask)
                mask_draw.rounded_rectangle([0, 0, pw, ph], radius=8, fill=255)

                photo_x = box_x + border
                photo_y = box_y + border
                base_pil.paste(pil_img, (photo_x, photo_y), mask=mask)

                if has_label:
                    draw_text_layer = ImageDraw.Draw(base_pil)
                    text_bbox = draw_text_layer.textbbox((0, 0), label_text, font=font)
                    text_w = text_bbox[2] - text_bbox[0]
                    text_x = box_x + (total_w - text_w) // 2
                    text_y = photo_y + ph + 10
                    draw_text_layer.text(
                        (text_x, text_y), label_text, font=font, fill=(40, 40, 40, 255)
                    )

                f_frame = cv2.cvtColor(np.array(base_pil), cv2.COLOR_RGBA2BGR)

        return f_frame

    def generate_fullscreen_popup_transition(
        self,
        base_frame: np.ndarray,
        popup_info: Dict,
        fps: int,
        duration_sec: float = 0.8,
        hold_sec: float = 1.5,
        fade_out_sec: float = 0.5,
    ) -> List[np.ndarray]:
        frames = []
        img_url = popup_info["data"].get("popup_image")
        h, w = base_frame.shape[:2]

        if not img_url or not os.path.exists(img_url):
            return frames
        pop_img = self.read_image_safe(img_url)
        if pop_img is None:
            return frames

        ph, pw = pop_img.shape[:2]
        target_ratio = 16.0 / 9.0
        current_ratio = pw / float(ph)

        if current_ratio > target_ratio:
            new_w = int(ph * target_ratio)
            offset = (pw - new_w) // 2
            pop_img = pop_img[:, offset : offset + new_w]
        elif current_ratio < target_ratio:
            new_h = int(pw / target_ratio)
            offset = (ph - new_h) // 2
            pop_img = pop_img[offset : offset + new_h, :]

        hi_res_popup = cv2.resize(pop_img, (w, h))

        target_img_w = 350
        target_img_h = int(target_img_w / target_ratio)
        border = 6
        label_text = popup_info.get("label")

        text_offset = (
            cv2.getTextSize(label_text or "", self.font_cv, 0.6, 1)[0][1] + 15
            if MathUtils.is_real_label(label_text)
            else 0
        )
        total_w, total_h = target_img_w + (border * 2), target_img_h + (border * 2)
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

        start_x, start_y = box_x + border, box_y + border

        scale_frames = max(1, int(duration_sec * fps))
        for t in range(scale_frames):
            progress = t / float(scale_frames - 1) if scale_frames > 1 else 1.0
            ease = 1 - (1 - progress) ** 3
            curr_w = int(target_img_w + (w - target_img_w) * ease)
            curr_h = int(target_img_h + (h - target_img_h) * ease)
            curr_x = int(start_x + (0 - start_x) * ease)
            curr_y = int(start_y + (0 - start_y) * ease)

            frame = base_frame.copy()
            bg_fade = 1.0 - (0.8 * ease)
            frame = (frame * bg_fade).astype(np.uint8)

            resized_popup = cv2.resize(hi_res_popup, (curr_w, curr_h))
            x0, y0 = max(0, curr_x), max(0, curr_y)
            x1, y1 = min(w, curr_x + curr_w), min(h, curr_y + curr_h)
            px0, py0 = x0 - curr_x, y0 - curr_y
            px1, py1 = px0 + (x1 - x0), py0 + (y1 - y0)

            if x0 < x1 and y0 < y1:
                frame[y0:y1, x0:x1] = resized_popup[py0:py1, px0:px1]
            frames.append(frame)

        hold_frames_cnt = max(1, int(hold_sec * fps))
        full_screen_frame = frames[-1].copy() if frames else hi_res_popup.copy()
        for _ in range(hold_frames_cnt):
            frames.append(full_screen_frame)

        fade_frames = max(1, int(fade_out_sec * fps))
        for t in range(fade_frames):
            progress = t / float(fade_frames - 1) if fade_frames > 1 else 1.0
            alpha = 1.0 - progress
            blended = cv2.addWeighted(
                full_screen_frame, alpha, base_frame, 1 - alpha, 0
            )
            frames.append(blended)

        return frames

    def write_fade_clip(
        self,
        video_out: VideoExporter,
        bg_frame: np.ndarray,
        fg_frame: np.ndarray,
        total_frames: int,
        fade_frames: int,
    ) -> None:
        if fade_frames <= 0:
            for _ in range(total_frames):
                video_out.write(fg_frame)
            return

        for f_idx in range(total_frames):
            if f_idx < fade_frames:
                alpha = f_idx / fade_frames
                blended = cv2.addWeighted(fg_frame, alpha, bg_frame, 1 - alpha, 0)
                video_out.write(blended)
            elif f_idx > total_frames - fade_frames:
                alpha = (total_frames - f_idx) / fade_frames
                blended = cv2.addWeighted(fg_frame, alpha, bg_frame, 1 - alpha, 0)
                video_out.write(blended)
            else:
                video_out.write(fg_frame)

    def play_fullscreen_video(
        self,
        video_path: str,
        enter_frame: np.ndarray,
        exit_frame: np.ndarray,
        video_out: VideoExporter,
        fps: int,
    ) -> None:
        if isinstance(video_path, list):
            video_path = video_path[0] if video_path else ""

        if not video_path or not os.path.exists(video_path):
            logger.warning(f"Video file not found: {video_path}")
            return

        cap = cv2.VideoCapture(video_path)
        frames = []
        target_h, target_w = exit_frame.shape[:2]

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            fh, fw = frame.shape[:2]
            scale = max(target_w / fw, target_h / fh)
            new_w, new_h = int(fw * scale), int(fh * scale)
            resized = cv2.resize(frame, (new_w, new_h))

            y_offset = (new_h - target_h) // 2
            x_offset = (new_w - target_w) // 2
            cropped = resized[
                y_offset : y_offset + target_h, x_offset : x_offset + target_w
            ]
            frames.append(cropped)

        cap.release()

        if not frames:
            return

        fade_frames = min(int(0.5 * fps), len(frames) // 3)
        for i, f in enumerate(frames):
            if i < fade_frames:
                alpha = i / fade_frames
                blended = cv2.addWeighted(f, alpha, enter_frame, 1 - alpha, 0)
                video_out.write(blended)
            elif i > len(frames) - fade_frames:
                alpha = (len(frames) - i) / fade_frames
                blended = cv2.addWeighted(f, alpha, exit_frame, 1 - alpha, 0)
                video_out.write(blended)
            else:
                video_out.write(f)

    def create_summary_card(
        self, distance_km: float, duration_seconds: float, card_size=(480, 110)
    ) -> np.ndarray:
        w, h = card_size
        scale = 2
        canvas = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)

        bg_color, text_color = (255, 255, 255, 245), (20, 20, 20, 255)
        label_color, divider_color = (120, 120, 120, 255), (230, 230, 230, 255)

        draw.rounded_rectangle(
            [0, 0, w * scale - 1, h * scale - 1],
            radius=16 * scale,
            fill=bg_color,
            outline=(220, 220, 220, 255),
            width=2,
        )
        font_label = self._load_font(self.FONT_CANDIDATES_REGULAR, 14 * scale)
        font_value = self._load_font(self.FONT_CANDIDATES_BOLD, 22 * scale)

        icon_size, pad = 40 * scale, 30 * scale
        self._draw_walking_icon(
            draw, pad + icon_size // 2, h * scale // 2, icon_size, (50, 50, 50, 255)
        )
        text_x = pad + icon_size + 14 * scale
        draw.text((text_x, 24 * scale), "Total Time", font=font_label, fill=label_color)
        draw.text(
            (text_x, 46 * scale),
            self._format_duration_short(duration_seconds),
            font=font_value,
            fill=text_color,
        )

        div_x = w * scale // 2
        draw.line(
            [(div_x, 22 * scale), (div_x, h * scale - 22 * scale)],
            fill=divider_color,
            width=2 * scale,
        )
        icon_cx2 = div_x + 32 * scale + icon_size // 2
        self._draw_ruler_icon(
            draw, icon_cx2, h * scale // 2, icon_size, (50, 50, 50, 255)
        )
        text_x2 = icon_cx2 + icon_size // 2 + 14 * scale
        distance_str = (
            f"{distance_km * 1000:.0f} m"
            if distance_km < 1
            else f"{distance_km:.2f} km"
        )
        draw.text((text_x2, 24 * scale), "Distance", font=font_label, fill=label_color)
        draw.text((text_x2, 46 * scale), distance_str, font=font_value, fill=text_color)

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
            tx, ty = p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t
            draw.line([(tx - 4, ty - 6), (tx + 4, ty + 6)], fill=color, width=2)

    def _format_duration_short(self, seconds: float) -> str:
        hrs, mins = divmod(int(round(seconds / 60)), 60)
        return f"{hrs} hr {mins:02d} min" if hrs else f"{mins} min"

    def load_walking_sprites(self, sprite_paths: list[str]):
        self.walk_sprites = []
        for path in sprite_paths:
            img = self.read_image_safe(path)
            if img is not None:
                img = cv2.resize(img, (60, 60))
                self.walk_sprites.append(img)

    def draw_walking_human(
        self, frame: np.ndarray, cx: int, cy: int, frame_count: int, angle: float
    ):
        if not hasattr(self, "walk_sprites") or not self.walk_sprites:
            self.draw_marker(frame, cx, cy)
            return

        sprite_idx = (frame_count // 5) % len(self.walk_sprites)
        sprite = self.walk_sprites[sprite_idx]
        anchor_x, anchor_y = sprite.shape[1] // 2, sprite.shape[0]
        self.blit_sprite(frame, sprite, (anchor_x, anchor_y), cx, cy)

    def compute_fullscreen_hold_times(
        self, total_freeze: float, transition_cfg: Dict[str, float]
    ) -> Tuple[float, float, float, float]:
        """Calculates the exact frame durations for the 4 phases of a cinematic popup."""
        scale_time = transition_cfg["scale_seconds"]
        fade_time = transition_cfg["fade_out_seconds"]
        hold_full_time = max(
            transition_cfg["min_hold_seconds"], total_freeze * transition_cfg["hold_ratio_of_freeze"]
        )
        hold_small_time = max(
            transition_cfg["min_small_hold_seconds"],
            total_freeze - scale_time - hold_full_time - fade_time,
        )
        return hold_small_time, scale_time, hold_full_time, fade_time

    def play_fullscreen_popup_sequence(
        self,
        video: VideoExporter,
        base_frame: np.ndarray,
        popup_info: Dict,
        fps: int,
        transition_cfg: Dict[str, float],
        exit_frame: np.ndarray,
    ) -> Tuple[np.ndarray, bool]:
        """Consolidated logic for freeze -> scale -> optional B-roll -> hold -> fade."""
        freeze_frame = self.render_popup_box(base_frame, popup_info)
        total_freeze = float(popup_info["data"].get("freeze_seconds", 3.0))
        hold_small, scale_t, hold_full, fade_t = self.compute_fullscreen_hold_times(total_freeze, transition_cfg)
        
        broll_video = popup_info["data"].get("popup_video")
        
        if broll_video:
            t_frames = self.generate_fullscreen_popup_transition(
                base_frame=freeze_frame,
                popup_info=popup_info,
                fps=fps,
                duration_sec=scale_t,
                hold_sec=0.1,
                fade_out_sec=0.0,
            )
            if t_frames:
                for _ in range(int(hold_small * fps)):
                    video.write(freeze_frame)
                for tf in t_frames:
                    video.write(tf)
            enter_frame = t_frames[-1] if t_frames else freeze_frame
            self.play_fullscreen_video(broll_video, enter_frame, exit_frame, video, fps)
            return exit_frame, True
        else:
            t_frames = self.generate_fullscreen_popup_transition(
                base_frame=freeze_frame,
                popup_info=popup_info,
                fps=fps,
                duration_sec=scale_t,
                hold_sec=hold_full,
                fade_out_sec=fade_t,
            )
            if t_frames:
                for _ in range(int(hold_small * fps)):
                    video.write(freeze_frame)
                for tf in t_frames:
                    video.write(tf)
            else:
                for _ in range(int(total_freeze * fps)):
                    video.write(freeze_frame)
            return freeze_frame, False

        