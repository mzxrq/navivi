"""Sprite blitting and cached procedural walker/vehicle icon sprites."""

import math
from typing import Dict, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter


class _SpriteMixin:
    def prebake_landmark_sprite(self, label: str) -> Tuple[np.ndarray, Tuple[int, int]]:
        """Builds just the label chip for a waypoint — draw_marker()
        already draws the actual numbered pin at this same anchor point, so
        this no longer duplicates it with its own circle. Drawn as a small
        rounded, soft-shadowed card (matching the popup cards' look)
        instead of a plain hard-edged rectangle."""
        font_size = max(13, int(self.font_size * 0.6))
        font = self._load_font(self.FONT_CANDIDATES_REGULAR, font_size)
        measure_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        bbox = measure_draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        pad_x, pad_y = 10, 6

        sprite_w = int(self.marker_radius + 4 + tw + pad_x * 2 + self.marker_radius + 4)
        sprite_h = int(max(2 * (self.marker_radius + 3), th + pad_y * 2) + 8)

        # cx/cy is the pin's own anchor point (kept for spacing math below,
        # and as the sprite's blit anchor so it still lines up with the pin).
        cx = int(self.marker_radius + 4)
        cy = sprite_h // 2

        bx1 = cx + int(self.marker_radius + 4)
        by1 = cy - (th // 2) - pad_y
        bx2 = bx1 + tw + pad_x * 2
        by2 = cy + (th // 2) + pad_y

        canvas = Image.new("RGBA", (sprite_w, sprite_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle(
            [bx1 - 2, by1, bx2 + 2, by2 + 4], radius=8, fill=(0, 0, 0, 40)
        )
        canvas = canvas.filter(ImageFilter.GaussianBlur(radius=2))
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle(
            [bx1, by1, bx2, by2],
            radius=8,
            fill=(255, 255, 255, 235),
            outline=(220, 220, 220, 255),
            width=1,
        )
        draw.text(
            (bx1 + pad_x, by1 + pad_y - bbox[1]), label, font=font, fill=(45, 45, 45, 255)
        )

        sprite = cv2.cvtColor(np.array(canvas), cv2.COLOR_RGBA2BGRA)
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
        if hasattr(self, "walk_sprites") and self.walk_sprites:
            sprite_idx = (frame_count // 5) % len(self.walk_sprites)
            sprite = self.walk_sprites[sprite_idx]
            anchor_x, anchor_y = sprite.shape[1] // 2, sprite.shape[0]
            self.blit_sprite(frame, sprite, (anchor_x, anchor_y), cx, cy)
            return

        # No sprite images loaded via load_walking_sprites() — draw a small
        # two-pose vector walker (legs alternate) instead of falling back to
        # a plain marker.
        sprite = self._get_walking_sprite(frame_count)
        anchor = (sprite.shape[1] // 2, sprite.shape[0] - 2)
        self.blit_sprite(frame, sprite, anchor, cx, cy)

    def _mode_icon_cache(self) -> Dict[str, np.ndarray]:
        if not hasattr(self, "_mode_icons"):
            self._mode_icons: Dict[str, np.ndarray] = {}
        return self._mode_icons

    def _get_walking_sprite(self, frame_count: int) -> np.ndarray:
        """Builds (and caches per walk-cycle phase) a simple stick-figure
        walker with alternating leg spread, upright regardless of heading."""
        cache = self._mode_icon_cache()
        phase = (frame_count // 6) % 2
        key = f"walking_{phase}"
        if key in cache:
            return cache[key]

        size = max(24, int(self.marker_radius * 2.4))
        canvas = np.zeros((size, size, 4), dtype=np.uint8)
        color = (*self.marker_color, 255)
        white = (255, 255, 255, 255)
        cx, cy = size // 2, size - 2
        head_r = max(3, size // 8)
        hip = (cx, cy - size // 2)
        head_c = (cx, hip[1] - head_r - 2)
        leg_spread = size // 4 if phase == 0 else size // 8
        thickness = max(2, size // 12)
        arm_y = hip[1] + size // 6

        # White halo pass first (thicker), then the colored figure on top.
        for col, extra in ((white, 3), (color, 0)):
            cv2.circle(canvas, head_c, head_r + extra, col, -1, cv2.LINE_AA)
            cv2.line(canvas, hip, head_c, col, thickness + extra, cv2.LINE_AA)
            cv2.line(canvas, hip, (cx - leg_spread, cy), col, thickness + extra, cv2.LINE_AA)
            cv2.line(canvas, hip, (cx + leg_spread // 2, cy), col, thickness + extra, cv2.LINE_AA)
            cv2.line(
                canvas, (cx, arm_y), (cx - size // 5, arm_y + size // 8),
                col, max(2, thickness - 1) + extra, cv2.LINE_AA,
            )
            cv2.line(
                canvas, (cx, arm_y), (cx + size // 5, arm_y - size // 8),
                col, max(2, thickness - 1) + extra, cv2.LINE_AA,
            )

        cache[key] = canvas
        return canvas

    def _get_vehicle_sprite(self, mode: str) -> np.ndarray:
        """Builds (and caches) a simple top-down vehicle silhouette pointing
        east (angle=0), for draw_transport_icon to rotate to heading."""
        cache = self._mode_icon_cache()
        if mode in cache:
            return cache[mode]

        size = max(28, int(self.marker_radius * 3.2))
        canvas = np.zeros((size, size, 4), dtype=np.uint8)
        color = (*self.MODE_COLORS.get(mode, self.marker_color), 255)
        white = (255, 255, 255, 255)
        cx, cy = size // 2, size // 2

        if mode == "airplane":
            body = np.array(
                [
                    [cx + int(size * 0.46), cy],
                    [cx - int(size * 0.30), cy - int(size * 0.32)],
                    [cx - int(size * 0.10), cy],
                    [cx - int(size * 0.30), cy + int(size * 0.32)],
                ],
                dtype=np.int32,
            )
        elif mode == "ferry":  # boat — pointed bow, flat stern
            body = np.array(
                [
                    [cx + int(size * 0.45), cy],
                    [cx + int(size * 0.05), cy - int(size * 0.28)],
                    [cx - int(size * 0.40), cy - int(size * 0.16)],
                    [cx - int(size * 0.40), cy + int(size * 0.16)],
                    [cx + int(size * 0.05), cy + int(size * 0.28)],
                ],
                dtype=np.int32,
            )
        else:  # car / driving — top-down rounded-rectangle silhouette
            body = np.array(
                [
                    [cx + int(size * 0.42), cy - int(size * 0.10)],
                    [cx + int(size * 0.32), cy - int(size * 0.22)],
                    [cx - int(size * 0.32), cy - int(size * 0.22)],
                    [cx - int(size * 0.42), cy - int(size * 0.10)],
                    [cx - int(size * 0.42), cy + int(size * 0.10)],
                    [cx - int(size * 0.32), cy + int(size * 0.22)],
                    [cx + int(size * 0.32), cy + int(size * 0.22)],
                    [cx + int(size * 0.42), cy + int(size * 0.10)],
                ],
                dtype=np.int32,
            )

        outline = ((body - [cx, cy]) * 1.22 + [cx, cy]).astype(np.int32)
        cv2.fillPoly(canvas, [outline], white, cv2.LINE_AA)
        cv2.fillPoly(canvas, [body], color, cv2.LINE_AA)

        if mode == "ferry":
            # A deckhouse + funnel on top of the hull, so it silhouettes as
            # an actual ferry rather than a generic pointed hull that could
            # as easily read as a canoe or sailboat.
            cabin = np.array(
                [
                    [cx - int(size * 0.05), cy - int(size * 0.14)],
                    [cx + int(size * 0.20), cy - int(size * 0.14)],
                    [cx + int(size * 0.20), cy + int(size * 0.14)],
                    [cx - int(size * 0.05), cy + int(size * 0.14)],
                ],
                dtype=np.int32,
            )
            cv2.fillPoly(canvas, [cabin], white, cv2.LINE_AA)
            mast_x = cx - int(size * 0.08)
            cv2.line(
                canvas,
                (mast_x, cy - int(size * 0.14)),
                (mast_x, cy - int(size * 0.32)),
                white,
                max(2, size // 14),
                cv2.LINE_AA,
            )
        elif mode != "airplane":
            # Windshield accent so the car silhouette doesn't read as just
            # a generic rounded rectangle.
            cv2.rectangle(
                canvas,
                (cx + int(size * 0.06), cy - int(size * 0.16)),
                (cx + int(size * 0.24), cy + int(size * 0.16)),
                white,
                -1,
                cv2.LINE_AA,
            )

        cache[mode] = canvas
        return canvas

    @staticmethod
    def _rotate_sprite(sprite: np.ndarray, angle_deg: float) -> np.ndarray:
        h, w = sprite.shape[:2]
        # atan2(dy, dx) on a y-down image is clockwise-positive; cv2's
        # rotation angle is counter-clockwise-positive, hence the negation.
        m = cv2.getRotationMatrix2D((w / 2, h / 2), -angle_deg, 1.0)
        return cv2.warpAffine(
            sprite, m, (w, h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0, 0),
        )

    def draw_transport_icon(
        self,
        frame: np.ndarray,
        cx: int,
        cy: int,
        frame_count: int,
        angle: float,
        mode: str = "walking",
    ):
        """Draws the traveler marker for the current leg's travel mode: an
        animated stick-figure walker for walking, and a heading-rotated
        vehicle silhouette for airplane/ferry/car(driving) legs. Any other
        unrecognized mode falls back to a mode-colored marker with a
        heading arrow."""
        mode = (mode or "walking").lower()
        if mode == "walking":
            self.draw_walking_human(frame, cx, cy, frame_count, angle)
            return

        if mode in ("airplane", "ferry", "car", "driving"):
            sprite = self._rotate_sprite(self._get_vehicle_sprite(mode), angle)
            anchor = (sprite.shape[1] // 2, sprite.shape[0] // 2)
            self.blit_sprite(frame, sprite, anchor, cx, cy)
            return

        color = self.MODE_COLORS.get(mode, self.marker_color)
        radius = int(self.marker_radius)

        cv2.circle(frame, (cx, cy), radius + 6, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(frame, (cx, cy), radius + 6, (200, 200, 200), 1, cv2.LINE_AA)
        cv2.circle(frame, (cx, cy), radius, color, -1, cv2.LINE_AA)

        # Heading arrow so unrecognized modes still show travel direction.
        rad = math.radians(angle)
        tip = (cx + int(radius * 0.9 * math.cos(rad)), cy + int(radius * 0.9 * math.sin(rad)))
        back_rad_l = rad + math.radians(150)
        back_rad_r = rad - math.radians(150)
        left = (cx + int(radius * 0.6 * math.cos(back_rad_l)), cy + int(radius * 0.6 * math.sin(back_rad_l)))
        right = (cx + int(radius * 0.6 * math.cos(back_rad_r)), cy + int(radius * 0.6 * math.sin(back_rad_r)))
        cv2.fillPoly(frame, [np.array([tip, left, right], dtype=np.int32)], (255, 255, 255), cv2.LINE_AA)
