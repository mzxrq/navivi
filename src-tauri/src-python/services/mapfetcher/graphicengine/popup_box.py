"""Cinematic pause overlay and popup/HUD card rendering."""

import os
from typing import Dict, List, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from services.mapfetcher.mapgeometry import RouteGeometryProcessor

from .base import _GraphicsEngineBase


class _PopupBoxMixin:
    # Base (card_scale=1.0) pixel width of a "beside the pin" popup card —
    # the single source of truth for both how render_popup_box actually
    # draws one and how _layout_beside_popups sizes its collision boxes
    # (see beside_card_footprint below). Keeping these in one place is what
    # keeps the two in sync — they'd previously drifted apart (280x192
    # actual vs. a hardcoded 190x150 layout box), which is what let
    # concurrently-visible cards overlap.
    BESIDE_CARD_BASE_W = 210

    def beside_card_footprint(self, card_scale: float = 1.0) -> Tuple[int, int]:
        """Returns the (total_w, total_h) footprint render_popup_box will
        actually draw for a "beside the pin" card at this card_scale —
        assumes a label is present (has_label=True), a safe upper-bound
        estimate for collision-avoidance sizing even on the rare card with
        no real label."""
        target_ratio = 16.0 / 9.0
        target_img_w = int(self.BESIDE_CARD_BASE_W * card_scale)
        target_img_h = int(target_img_w / target_ratio)
        border = int(10 * card_scale)
        font_size = max(11, int(self.font_size * 0.6 * card_scale))
        text_block_h = font_size + 14
        return target_img_w + border * 2, target_img_h + border * 2 + text_block_h

    def popup_card_geometry(
        self, popup_info: Dict, w: int, h: int
    ) -> Tuple[int, int, int, int, int]:
        """Returns (box_x, box_y, total_w, total_h, border) for the exact
        card render_popup_box would draw for this popup_info — the single
        source of truth for where/how big that card is, so anything else
        that needs to start from (or match) it — e.g. the fullscreen
        scale-up transition — can't drift out of sync with what's actually
        on screen. Pure geometry, no image I/O, so it's cheap to call
        ahead of the real draw."""
        target_ratio = 16.0 / 9.0
        hud_corner = popup_info.get("hud_corner")
        is_beside = hud_corner not in self.HUD_CORNERS
        card_scale = float(popup_info.get("card_scale", 1.0))
        base_img_w = self.BESIDE_CARD_BASE_W if is_beside else 440
        target_img_w = int(base_img_w * card_scale)
        target_img_h = int(target_img_w / target_ratio)
        border = int((10 if is_beside else 14) * card_scale)
        font_size = max(
            11, int(self.font_size * (0.6 if is_beside else 1.0) * card_scale)
        )
        has_label = RouteGeometryProcessor.is_real_label(popup_info.get("label"))
        text_block_h = (font_size + 14) if has_label else 0
        total_h = target_img_h + (border * 2) + text_block_h
        total_w = target_img_w + (border * 2)
        margin = 24

        if not is_beside:
            box_x, box_y = self._hud_corner_box(hud_corner, w, h, total_w, total_h)
        else:
            point_x, point_y = int(popup_info["x"]), int(popup_info["y"])
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

        return box_x, box_y, total_w, total_h, border

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
                card_scale = float(popup_info.get("card_scale", 1.0))

                box_x, box_y, total_w, total_h, border = self.popup_card_geometry(
                    popup_info, w, h
                )
                target_img_w = total_w - border * 2
                target_img_h = int(target_img_w / target_ratio)
                pop_img = cv2.resize(pop_img, (target_img_w, target_img_h))
                ph, pw = pop_img.shape[:2]

                label_text = popup_info.get("label")
                font_size = max(
                    11,
                    int(self.font_size * (0.6 if is_beside else 1.0) * card_scale),
                )
                font = self._load_font(self.FONT_CANDIDATES_REGULAR, font_size)
                has_label = RouteGeometryProcessor.is_real_label(label_text)

                if is_beside:
                    point_x = int(popup_info["x"])
                    point_y = int(popup_info["y"])
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
