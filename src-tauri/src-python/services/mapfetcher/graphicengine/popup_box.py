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

    # Screen-edge inset a "beside the pin" popup card is clamped to, so it
    # can't be placed flush against (or past) the very edge of the frame.
    _BESIDE_POPUP_EDGE_MARGIN = 24

    def beside_card_footprint(self, card_scale: float = 1.0, has_label: bool = True) -> Tuple[int, int]:
        """Returns the (total_w, total_h) footprint render_popup_box will
        actually draw for a "beside the pin" card at this card_scale —
        assumes a label is present (has_label=True), a safe upper-bound
        estimate for collision-avoidance sizing even on the rare card with
        no real label. Sized for a WORST-CASE two-line label (see
        _fit_label_caption) since this is called without knowing the
        actual label text — a one-line label just leaves a little extra
        clearance below its card instead of the two cards ever visually
        overlapping because this estimate came in short."""
        # The photo itself is full-bleed (flush to the card's left/right/
        # top edges, no white margin) — only a label caption, when present,
        # adds a strip of height below it.
        target_ratio = 16.0 / 9.0
        target_img_w = int(self.BESIDE_CARD_BASE_W * card_scale)
        target_img_h = int(target_img_w / target_ratio)
        text_block_h = 0
        if has_label:
            font_size = max(
                11, int(self.font_size * tuning.POPUP_LABEL_FONT_SCALE_BESIDE * card_scale)
            )
            line_gap = 4
            text_block_h = font_size * 2 + line_gap + 14
        caption_gap = 10 if has_label else 0
        return target_img_w, target_img_h + caption_gap + text_block_h

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
    ) -> Tuple[int, int, int, int]:
        """Returns (box_x, box_y, total_w, total_h) for the exact card
        render_popup_box would draw for this popup_info — the single
        source of truth for where/how big that card is, so anything else
        that needs to start from (or match) it — e.g. the fullscreen
        scale-up transition — can't drift out of sync with what's actually
        on screen. Pure geometry, no image I/O, so it's cheap to call
        ahead of the real draw.

        The photo is always full-bleed within the card — flush to its
        left/right/top edges with no white margin around it. A label
        caption, when shown (and not the overlaid "cover" style), adds a
        white strip of height below the photo instead."""
        target_ratio = 16.0 / 9.0
        hud_corner = popup_info.get("hud_corner")
        is_beside = hud_corner not in self.HUD_CORNERS
        card_scale = float(popup_info.get("card_scale", 1.0))
        base_img_w = self.BESIDE_CARD_BASE_W if is_beside else 440
        target_img_w = int(base_img_w * card_scale)
        target_img_h = int(target_img_w / target_ratio)
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
        total_w = target_img_w
        # "cover" (settings/job_config image_display: "cover") — the photo
        has_label = (
            RouteGeometryProcessor.is_real_label(popup_info.get("label"))
            and bool(popup_info.get("show_label", True))
        )
        # fills the entire card with no separate caption strip below it;
        # the label overlays the photo itself instead (see
        # render_popup_box), so it adds no extra height here.
        is_cover = str((popup_info.get("data") or {}).get("image_display", "")).lower() == "cover"
        text_block_h = 0
        if has_label and not is_cover:
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
        caption_gap = 10 if (has_label and not is_cover) else 0
        total_h = target_img_h + caption_gap + text_block_h
        margin = self._BESIDE_POPUP_EDGE_MARGIN

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

        return box_x, box_y, total_w, total_h

    @staticmethod
    def _fade_to_base(frame: np.ndarray, alpha: float, base_frame: np.ndarray) -> np.ndarray:
        """Blends `frame` back toward `base_frame` by `alpha` (0-1) — the
        shared "fade the whole composited card result as one unit"
        behavior render_popup_box uses both for its line_only early-return
        and its own final return. Only called when alpha < 1.0."""
        blend_alpha = max(0.0, alpha)
        return cv2.addWeighted(frame, blend_alpha, base_frame, 1 - blend_alpha, 0)

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
        working_frame = target_frame.copy()
        image_path = popup_info["data"].get("popup_image")
        h, w = working_frame.shape[:2]

        # [NOTE] [Animation] Missing/unreadable popup_image silently skips the entire card draw, returning the frame unchanged rather than raising or drawing a placeholder.
        if image_path and (line_only or os.path.exists(image_path)):
            pop_img = None if line_only else self.read_image_safe(image_path)
            if line_only or pop_img is not None:
                hud_corner = popup_info.get("hud_corner")
                is_beside = hud_corner not in self.HUD_CORNERS
                card_scale = float(popup_info.get("card_scale", 1.0))

                box_x, box_y, total_w, total_h = self.popup_card_geometry(
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
                    # Defaults to a neutral gray; callers with several
                    # leader lines on screen at once (e.g. the
                    # end-of-video recap) pass "leader_line_color" —
                    # matched to the card's own pin — so a line can
                    # still be traced back to its pin despite crossing
                    # others.
                    line_color = popup_info.get("leader_line_color", (130, 130, 130))
                    # Callers showing many lines at once (the end-of-video
                    # recap) thicken theirs — a 2px hairline gets lost
                    # against a busy map once there are a dozen-plus cards.
                    line_width = int(popup_info.get("leader_line_width", 2))
                    # "leader_via" (set by _layout_recap_popups for a pin
                    # that's part of a tight cluster — see its own
                    # _padded_boundary docstring) routes the line through
                    # an extra point on the cluster's shared outer
                    # boundary first: pin -> via -> card, instead of a
                    # single straight pin -> card line that would cut
                    # through the cluster's interior. The FINAL segment's
                    # anchor is computed from the via point (whichever
                    # edge of the box is nearest to where the line is
                    # actually arriving FROM), not the pin, so that last
                    # stretch still reads as "coming from the cluster's
                    # edge", not from the pin itself.
                    via = popup_info.get("leader_via")
                    if via is not None:
                        via_x, via_y = int(via[0]), int(via[1])
                        anchor_x = min(max(via_x, box_x), box_x + total_w)
                        anchor_y = min(max(via_y, box_y), box_y + total_h)
                        cv2.line(
                            working_frame, (point_x, point_y), (via_x, via_y),
                            line_color, line_width, cv2.LINE_AA,
                        )
                        cv2.line(
                            working_frame, (via_x, via_y), (anchor_x, anchor_y),
                            line_color, line_width, cv2.LINE_AA,
                        )
                    else:
                        # Connects the card back to the waypoint's own pin
                        # directly — the grid layout can place the card
                        # anywhere, so pick whichever edge (or corner) of
                        # the box is actually nearest the pin.
                        anchor_x = min(max(point_x, box_x), box_x + total_w)
                        anchor_y = min(max(point_y, box_y), box_y + total_h)
                        cv2.line(
                            working_frame, (point_x, point_y), (anchor_x, anchor_y),
                            line_color, line_width, cv2.LINE_AA,
                        )
                    cv2.circle(
                        working_frame, (point_x, point_y), 4, line_color, -1, cv2.LINE_AA
                    )

                if line_only:
                    if alpha < 1.0:
                        working_frame = self._fade_to_base(working_frame, alpha, target_frame)
                    return working_frame

                target_ratio = 16.0 / 9.0
                target_img_w = total_w
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
                is_cover = str(popup_info["data"].get("image_display", "")).lower() == "cover"
                if is_cover:
                    # Sized off the FIXED 1:4 scrim zone (ph // 5 — same
                    # formula the scrim itself uses below), not off
                    # font_size*multiplier — a flat multiplier ignored how
                    # big the photo/card actually was, so a short label on
                    # a small card could render far larger than its
                    # reserved text zone could actually hold (clipping
                    # into/past the photo instead of the intended bold-
                    # but-contained title-card look).
                    cover_scrim_h = max(1, ph // 5)
                    font = self._load_font(
                        self.FONT_CANDIDATES_BOLD,
                        max(self._LABEL_MIN_FONT_SIZE, int(cover_scrim_h * 0.55)),
                    )
                else:
                    # Regular, not bold — LINE Seed JP's regular weight reads
                    # clearly enough at this size (unlike the old Kosugi Maru
                    # default this used to be bumped to bold for), and matches
                    # the smaller, lighter caption look under the photo.
                    font = self._load_font(self.FONT_CANDIDATES_REGULAR, font_size)
                has_label = RouteGeometryProcessor.is_real_label(label_text)
                has_label = (
                    RouteGeometryProcessor.is_real_label(label_text)
                    and bool(popup_info.get("show_label", True))
                )

                pil_canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
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
                # Computed BEFORE the shadow below so the shadow can tint
                # to this same color instead of a flat neutral black.
                # `or` (not just a .get default) — a caller can legitimately
                # pass "border_color": None (e.g. a not-yet-"arrived" pin's
                # own color resolves to None — see pins.py's _pin_color),
                # and a plain dict .get(key, default) only falls back to
                # the default when the KEY is absent, not when it's present
                # with value None.
                border_color = popup_info.get("border_color") or self.card_border_color
                border_rgba = tuple(reversed(border_color)) + (255,)

                # A softer, more pronounced "elevated card" shadow — wider
                # blur radius and padding, and offset further down than up
                # (light-from-above cue) so the card reads as genuinely
                # floating above the map rather than merely outlined
                # against it. Tinted to the card's own border color
                # (low alpha) rather than plain black, so the shadow
                # visually ties back to the same color as the border/pin
                # instead of reading as a generic drop-shadow.
                shadow_box = [
                    box_x - 6,
                    box_y - 4,
                    box_x + total_w + 6,
                    box_y + total_h + 14,
                ]
                # Neutral black for the cover style specifically — no
                # border to tie a colored shadow back to, and a colored
                # glow around an otherwise borderless full-bleed photo
                # read as a border that was never actually removed.
                shadow_rgba = (0, 0, 0, 60) if is_cover else border_rgba[:3] + (60,)
                draw.rounded_rectangle(shadow_box, radius=18, fill=shadow_rgba)
                pil_canvas = pil_canvas.filter(ImageFilter.GaussianBlur(radius=11))
                draw = ImageDraw.Draw(pil_canvas)

                card_box = [box_x, box_y, box_x + total_w, box_y + total_h]
                draw.rounded_rectangle(
                    card_box,
                    radius=14,
                    fill=(255, 255, 255, 250),
                )

                base_pil = Image.fromarray(cv2.cvtColor(working_frame, cv2.COLOR_BGR2RGBA))
                base_pil.paste(pil_canvas, (0, 0), pil_canvas)

                pil_img = Image.fromarray(cv2.cvtColor(pop_img, cv2.COLOR_BGR2RGB))
                mask = Image.new("L", (pw, ph), 255)
                mask_draw = ImageDraw.Draw(mask)
                # Photo is full-bleed (flush to the card's left/right/top
                # edges, no white margin) — its mask uses the SAME corner
                # radius as the outer card (14) so the photo's own rounded
                # corners line up with the card's, instead of a smaller
                # radius leaving a sliver of white card visible behind it.
                mask_draw.rounded_rectangle([0, 0, pw, ph], radius=14, fill=255)

                photo_x = box_x
                photo_y = box_y
                base_pil.paste(pil_img, (photo_x, photo_y), mask=mask)

                # No colored outline on any popup card — the photo is
                # full-bleed against the card's rounded edges, so a drawn
                # border would frame it like the old pip card instead of
                # reading as a clean, borderless photo card. (A stroke
                # outline was tried here — it didn't follow the photo's
                # own rounded corners cleanly, leaving a square-cornered
                # notch at the top instead of tracing the curve.)
                if has_label:
                    draw_text_layer = ImageDraw.Draw(base_pil)
                    # Wraps to a second line (or shrinks the font, as a last
                    # resort) rather than letting a long place name/address
                    # run past the card's own edges — see _fit_label_caption.
                    label_lines, label_font = self._fit_label_caption(
                        draw_text_layer, label_text, font,
                        self.FONT_CANDIDATES_BOLD if is_cover else self.FONT_CANDIDATES_REGULAR,
                        max(1, (pw - 20) if is_cover else (total_w - 16)),
                    )
                    line_gap = 4
                    if is_cover:
                        # Overlaid in the top-left corner, directly on
                        # the photo — a dark gradient scrim (fading out
                        # top-to-bottom, not a solid box) sits behind the
                        # text just to keep it legible over any part of
                        # the image, rather than covering the photo with
                        # an opaque caption strip the way the default
                        # style does below it.
                        #
                        # The scrim zone is a FIXED 1:4 ratio of the
                        # photo's own height (not sized off the text
                        # content) — text : picture — so the split stays
                        # consistent across cards regardless of how much
                        # label text there is, and the text itself sits
                        # vertically CENTERED within that zone (equal
                        # top/bottom margin) rather than pinned to its
                        # own top edge, for a symmetric, balanced look.
                        pad = 10
                        text_h = (
                            label_font.size * len(label_lines)
                            + line_gap * (len(label_lines) - 1)
                        )
                        scrim_h = max(1, ph // 5)
                        scrim = Image.new("RGBA", (pw, scrim_h), (0, 0, 0, 0))
                        scrim_draw = ImageDraw.Draw(scrim)
                        for gy in range(scrim_h):
                            t = gy / max(1, scrim_h - 1)
                            scrim_draw.line(
                                [(0, gy), (pw, gy)], fill=(0, 0, 0, int(150 * (1 - t)))
                            )
                        base_pil.paste(scrim, (photo_x, photo_y), scrim)
                        line_y = photo_y + max(pad, (scrim_h - text_h) // 2)
                        for line in label_lines:
                            draw_text_layer.text(
                                (photo_x + pad, line_y),
                                line, font=label_font, fill=(255, 255, 255, 255),
                            )
                            line_y += label_font.size + line_gap
                    else:
                        line_y = photo_y + ph + 10
                        for line in label_lines:
                            line_w = draw_text_layer.textlength(line, font=label_font)
                            draw_text_layer.text(
                                (box_x + (total_w - line_w) // 2, line_y),
                                line, font=label_font, fill=(40, 40, 40, 255),
                            )
                            line_y += label_font.size + line_gap

                working_frame = cv2.cvtColor(np.array(base_pil), cv2.COLOR_RGBA2BGR)

        if alpha < 1.0:
            working_frame = self._fade_to_base(working_frame, alpha, target_frame)
        return working_frame
