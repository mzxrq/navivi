"""Cinematic pause overlay and popup/HUD card rendering."""

import os
from typing import Dict, List, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from services.mapfetcher.mapgeometry import RouteGeometryProcessor

from .base import _GraphicsEngineBase


class _PopupBoxMixin:
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
        has_label = RouteGeometryProcessor.is_real_label(label_text)

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

    def pick_hud_corner(
        self,
        w: int,
        h: int,
        avoid_points: List[Tuple[float, float]],
        card_w: int = 420,
        card_h: int = 320,
        margin: int = 40,
        preference: Tuple[str, ...] = _GraphicsEngineBase.HUD_CORNERS,
    ) -> str:
        """Picks a HUD corner for a popup card whose (generously estimated)
        footprint doesn't overlap any of `avoid_points` (e.g. the route path
        and waypoint pins) — falling back to the first preferred corner if
        every corner collides."""
        rects = {
            "bottom_left": (margin, h - card_h - margin, margin + card_w, h - margin),
            "bottom_right": (w - card_w - margin, h - card_h - margin, w - margin, h - margin),
            "top_left": (margin, margin, margin + card_w, margin + card_h),
            "top_right": (w - card_w - margin, margin, w - margin, margin + card_h),
        }
        for corner in preference:
            x0, y0, x1, y1 = rects[corner]
            if not any(x0 <= px <= x1 and y0 <= py <= y1 for px, py in avoid_points):
                return corner
        return preference[0]

    def render_popup_box(
        self, target_frame: np.ndarray, popup_info: Dict, alpha: float = 1.0
    ) -> np.ndarray:
        """`alpha` (0-1) fades the whole card — image, caption, leader
        line, shadow — as one unit by blending the fully-composited result
        back with `target_frame`, rather than needing every drawn piece to
        carry its own opacity."""
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

                hud_corner = popup_info.get("hud_corner")
                is_beside = hud_corner not in self.HUD_CORNERS

                # Flow-through ("beside the pin") cards are drawn much
                # smaller than the HUD-corner ones — several can be on
                # screen at once (nearby waypoints triggering close
                # together), so keeping them small is what lets the grid
                # layout in _layout_beside_popups fit them without overlap.
                # `card_scale` bumps a specific beside-style card back up
                # (e.g. the end-of-video recap's start/end pair, which get
                # a dedicated fixed corner instead of competing for space).
                card_scale = float(popup_info.get("card_scale", 1.0)) if is_beside else 1.0
                target_img_w = int(160 * card_scale) if is_beside else 340
                target_img_h = int(target_img_w / target_ratio)
                pop_img = cv2.resize(pop_img, (target_img_w, target_img_h))
                ph, pw = pop_img.shape[:2]

                border = int(10 * card_scale) if is_beside else 14
                label_text = popup_info.get("label")
                font_size = (
                    max(11, int(self.font_size * 0.6 * card_scale))
                    if is_beside
                    else self.font_size
                )
                font = self._load_font(self.FONT_CANDIDATES_REGULAR, font_size)

                has_label = RouteGeometryProcessor.is_real_label(label_text)
                text_block_h = (font_size + 14) if has_label else 0
                total_h = ph + (border * 2) + text_block_h
                total_w = pw + (border * 2)
                margin = 50

                if not is_beside:
                    box_x, box_y = self._hud_corner_box(hud_corner, w, h, total_w, total_h)
                else:
                    point_x = int(popup_info["x"])
                    point_y = int(popup_info["y"])
                    beside_box = popup_info.get("beside_box")
                    if beside_box:
                        box_x, box_y = beside_box
                    else:
                        box_x = (
                            point_x - total_w - 40 if point_x > w * 0.5 else point_x + 40
                        )
                        box_y = point_y - (total_h // 2)
                    box_x = max(margin, min(box_x, w - total_w - margin))
                    box_y = max(margin, min(box_y, h - total_h - margin))

                    if popup_info.get("draw_leader_line"):
                        # Connects the card back to the waypoint's own pin —
                        # used when the card is riding beside a waypoint the
                        # traveler is flowing through rather than sitting in
                        # a fixed HUD corner, so it's still clear which stop
                        # it belongs to. The grid layout can place the card
                        # anywhere, so pick whichever edge (or corner) of
                        # the box is actually nearest the pin.
                        anchor_x = min(max(point_x, box_x), box_x + total_w)
                        anchor_y = min(max(point_y, box_y), box_y + total_h)
                        cv2.line(
                            f_frame,
                            (point_x, point_y),
                            (anchor_x, anchor_y),
                            (130, 130, 130),
                            2,
                            cv2.LINE_AA,
                        )
                        cv2.circle(
                            f_frame, (point_x, point_y), 4, (130, 130, 130), -1, cv2.LINE_AA
                        )

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

        if alpha < 1.0:
            a = max(0.0, alpha)
            f_frame = cv2.addWeighted(f_frame, a, target_frame, 1 - a, 0)
        return f_frame
