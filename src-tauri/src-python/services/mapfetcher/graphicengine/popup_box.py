"""Cinematic pause overlay and popup/HUD card rendering."""

import os
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from services.mapfetcher.mapgeometry import RouteGeometryProcessor
from services import tuning

from .base import _GraphicsEngineBase


class _PopupBoxMixin:
    # Base (card_scale=1.0) pixel width of a "beside the pin" popup card —
    # the single source of truth for both how render_popup_box actually
    # draws one and how _layout_beside_popups sizes its collision boxes
    # (see beside_card_footprint below). Keeping these in one place is what
    # keeps the two in sync — they'd previously drifted apart (280x192
    # actual vs. a hardcoded 190x150 layout box), which is what let
    # concurrently-visible cards overlap.
    # [NOTE] [Animation] Single source of truth for beside-card sizing so render and collision-layout geometry can't drift apart again.
    BESIDE_CARD_BASE_W = 210

    def beside_card_footprint(self, card_scale: float = 1.0) -> Tuple[int, int]:
        """Returns the (total_w, total_h) footprint render_popup_box will
        actually draw for a "beside the pin" card at this card_scale —
        assumes a label is present (has_label=True), a safe upper-bound
        estimate for collision-avoidance sizing even on the rare card with
        no real label. Sized for a WORST-CASE two-line label (see
        _fit_label_caption) since this is called without knowing the
        actual label text — a one-line label just leaves a little extra
        clearance below its card instead of the two cards ever visually
        overlapping because this estimate came in short."""
        target_ratio = 16.0 / 9.0
        target_img_w = int(self.BESIDE_CARD_BASE_W * card_scale)
        target_img_h = int(target_img_w / target_ratio)
        border = int(10 * card_scale)
        font_size = max(
            11, int(self.font_size * tuning.POPUP_LABEL_FONT_SCALE_BESIDE * card_scale)
        )
        line_gap = 4
        text_block_h = font_size * 2 + line_gap + 14
        return target_img_w + border * 2, target_img_h + border * 2 + text_block_h

    # Minimum caption font size _fit_label_caption will shrink to before
    # giving up and letting a still-too-wide second line clip — matches
    # the floor every other font-size calc in this file already uses.
    _LABEL_MIN_FONT_SIZE = 11

    def _fit_label_caption(
        self, draw: ImageDraw.ImageDraw, text: str, font: Any, font_candidates: List[str], max_width: float
    ) -> Tuple[List[str], Any]:
        """Fits a popup's label caption within max_width — one line if it
        already fits, otherwise two, split at whichever character position
        best balances the two resulting line widths (most labels here are
        Japanese place names/addresses with no spaces to break on, so a
        word-boundary wrap isn't an option). Shrinks the font (down to
        _LABEL_MIN_FONT_SIZE) only if the longer of the two lines still
        doesn't fit even after splitting. Returns (lines, font) — `font`
        may be a smaller instance than the one passed in."""
        if draw.textlength(text, font=font) <= max_width:
            return [text], font

        best_split, best_diff = 1, None
        for i in range(1, len(text)):
            diff = abs(
                draw.textlength(text[:i], font=font) - draw.textlength(text[i:], font=font)
            )
            if best_diff is None or diff < best_diff:
                best_diff, best_split = diff, i
        lines = [text[:best_split], text[best_split:]]

        size = font.size
        longest = max(draw.textlength(line, font=font) for line in lines)
        while longest > max_width and size > self._LABEL_MIN_FONT_SIZE:
            size = max(self._LABEL_MIN_FONT_SIZE, int(size * 0.9))
            font = self._load_font(font_candidates, size)
            longest = max(draw.textlength(line, font=font) for line in lines)
        return lines, font

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
        font_scale = (
            tuning.POPUP_LABEL_FONT_SCALE_BESIDE
            if is_beside
            else tuning.POPUP_LABEL_FONT_SCALE_CORNER
        )
        # Caller override (e.g. the overview intro's preview cards, which
        # want a larger photo via card_scale but NOT a proportionally
        # larger caption) — defaults to 1.0, a no-op, for every ordinary
        # popup.
        font_scale *= float(popup_info.get("label_font_scale", 1.0))
        font_size = max(11, int(self.font_size * font_scale * card_scale))
        total_w = target_img_w + (border * 2)
        has_label = RouteGeometryProcessor.is_real_label(popup_info.get("label"))
        text_block_h = 0
        if has_label:
            probe_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
            font = self._load_font(self.FONT_CANDIDATES_REGULAR, font_size)
            label_lines, font = self._fit_label_caption(
                probe_draw, popup_info["label"], font,
                self.FONT_CANDIDATES_REGULAR, max(1, total_w - 16),
            )
            line_gap = 4
            text_block_h = (
                font.size * len(label_lines) + line_gap * (len(label_lines) - 1) + 14
            )
        total_h = target_img_h + (border * 2) + text_block_h
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
        self,
        target_frame: np.ndarray,
        popup_info: Dict,
        alpha: float = 1.0,
        line_only: bool = False,
        skip_line: bool = False,
    ) -> np.ndarray:
        """`alpha` (0-1) fades the whole card — image, caption, leader
        line, shadow — as one unit by blending the fully-composited result
        back with `target_frame`, rather than needing every drawn piece to
        carry its own opacity.

        `line_only`/`skip_line` split the leader line from the card box
        itself, for callers that draw several cards on one frame at once
        (e.g. the end-of-video recap): drawing each card's line+box
        together, one popup at a time, lets a LATER popup's line cross
        over and render on top of an EARLIER popup's already-drawn card —
        since each render_popup_box call composites onto whatever's
        already on the frame. Calling with `line_only=True` for every
        popup first (drawing just the lines, cheaply — no image I/O),
        then `skip_line=True` for every popup afterward (drawing just the
        cards on top), guarantees every line sits behind every card
        regardless of draw order."""
        f_frame = target_frame.copy()
        img_url = popup_info["data"].get("popup_image")
        h, w = f_frame.shape[:2]

        # [NOTE] [Animation] Missing/unreadable popup_image silently skips the entire card draw, returning the frame unchanged rather than raising or drawing a placeholder.
        if img_url and (line_only or os.path.exists(img_url)):
            pop_img = None if line_only else self.read_image_safe(img_url)
            if line_only or pop_img is not None:
                hud_corner = popup_info.get("hud_corner")
                is_beside = hud_corner not in self.HUD_CORNERS
                card_scale = float(popup_info.get("card_scale", 1.0))

                box_x, box_y, total_w, total_h, border = self.popup_card_geometry(
                    popup_info, w, h
                )

                if is_beside and popup_info.get("draw_leader_line") and not skip_line:
                    # Anchor to the pin's actual on-screen position — when
                    # waypoints cluster, _declutter_pins fans the drawn
                    # marker out to "pin_x"/"pin_y", separate from the
                    # waypoint's true "x"/"y". Anchoring here to the raw
                    # x/y points the leader line at empty space instead of
                    # the pin it's meant to connect to.
                    point_x = int(popup_info.get("pin_x", popup_info["x"]))
                    point_y = int(popup_info.get("pin_y", popup_info["y"]))
                    # Connects the card back to the waypoint's own pin —
                    # used when the card is riding beside a waypoint the
                    # traveler is flowing through rather than sitting in
                    # a fixed HUD corner, so it's still clear which stop
                    # it belongs to. The grid layout can place the card
                    # anywhere, so pick whichever edge (or corner) of
                    # the box is actually nearest the pin.
                    anchor_x = min(max(point_x, box_x), box_x + total_w)
                    anchor_y = min(max(point_y, box_y), box_y + total_h)
                    # Defaults to a neutral gray; callers with several
                    # leader lines on screen at once (e.g. the
                    # end-of-video recap) pass "leader_line_color" —
                    # matched to the card's own pin — so a line can
                    # still be traced back to its pin despite crossing
                    # others.
                    line_color = popup_info.get("leader_line_color", (130, 130, 130))
                    cv2.line(
                        f_frame,
                        (point_x, point_y),
                        (anchor_x, anchor_y),
                        line_color,
                        2,
                        cv2.LINE_AA,
                    )
                    cv2.circle(
                        f_frame, (point_x, point_y), 4, line_color, -1, cv2.LINE_AA
                    )

                if line_only:
                    if alpha < 1.0:
                        a = max(0.0, alpha)
                        f_frame = cv2.addWeighted(f_frame, a, target_frame, 1 - a, 0)
                    return f_frame

                target_ratio = 16.0 / 9.0
                target_img_w = total_w - border * 2
                target_img_h = int(target_img_w / target_ratio)

                # Cover-fit (scale to fill the 16:9 box, then crop the
                # overflow) rather than contain-fit — a contain-fit
                # letterboxes any photo that isn't already 16:9, which
                # reads as a solid bar of empty space above/below the
                # photo. Cropping the overflow instead keeps the card
                # fully filled at the cost of trimming the photo's edges,
                # matching the "no black bar" look most photo cards use.
                src_h, src_w = pop_img.shape[:2]
                scale = max(target_img_w / src_w, target_img_h / src_h)
                fit_w = max(1, int(round(src_w * scale)))
                fit_h = max(1, int(round(src_h * scale)))
                resized = cv2.resize(pop_img, (fit_w, fit_h))

                crop_x = max(0, (fit_w - target_img_w) // 2)
                crop_y = max(0, (fit_h - target_img_h) // 2)
                pop_img = resized[
                    crop_y : crop_y + target_img_h, crop_x : crop_x + target_img_w
                ]
                ph, pw = pop_img.shape[:2]

                label_text = popup_info.get("label")
                font_scale = (
                    tuning.POPUP_LABEL_FONT_SCALE_BESIDE
                    if is_beside
                    else tuning.POPUP_LABEL_FONT_SCALE_CORNER
                )
                # Must match popup_card_geometry's own font_scale exactly
                # (that's what text_block_h/total_h were sized against) —
                # see its own comment on label_font_scale.
                font_scale *= float(popup_info.get("label_font_scale", 1.0))
                font_size = max(11, int(self.font_size * font_scale * card_scale))
                # Regular, not bold — LINE Seed JP's regular weight reads
                # clearly enough at this size (unlike the old Kosugi Maru
                # default this used to be bumped to bold for), and matches
                # the smaller, lighter caption look under the photo.
                font = self._load_font(self.FONT_CANDIDATES_REGULAR, font_size)
                has_label = RouteGeometryProcessor.is_real_label(label_text)

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

                # Border color is stored BGR (like every other color in
                # job_config.json's settings) — reversed here since this
                # canvas is later converted RGBA->BGR as a whole, the same
                # convention cards.py's mode_accent uses. Defaults to the
                # global card_border_color, but a caller can pass
                # "border_color" (e.g. matching this popup's own pin
                # color) so the card visually ties back to its pin — used
                # by the recap and flow-through cards, where several
                # differently-colored pins can be on screen at once.
                border_color = popup_info.get("border_color", self.card_border_color)
                border_rgba = tuple(reversed(border_color)) + (255,)
                card_box = [box_x, box_y, box_x + total_w, box_y + total_h]
                draw.rounded_rectangle(
                    card_box,
                    radius=14,
                    fill=(255, 255, 255, 250),
                    outline=border_rgba if self.card_border_thickness else None,
                    width=self.card_border_thickness,
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
                    # Wraps to a second line (or shrinks the font, as a last
                    # resort) rather than letting a long place name/address
                    # run past the card's own edges — see _fit_label_caption.
                    label_lines, label_font = self._fit_label_caption(
                        draw_text_layer, label_text, font,
                        self.FONT_CANDIDATES_REGULAR, max(1, total_w - 16),
                    )
                    line_gap = 4
                    line_y = photo_y + ph + 10
                    for line in label_lines:
                        line_w = draw_text_layer.textlength(line, font=label_font)
                        draw_text_layer.text(
                            (box_x + (total_w - line_w) // 2, line_y),
                            line, font=label_font, fill=(40, 40, 40, 255),
                        )
                        line_y += label_font.size + line_gap

                f_frame = cv2.cvtColor(np.array(base_pil), cv2.COLOR_RGBA2BGR)

        if alpha < 1.0:
            a = max(0.0, alpha)
            f_frame = cv2.addWeighted(f_frame, a, target_frame, 1 - a, 0)
        return f_frame
