"""Cinematic pause overlay and popup/HUD card rendering."""

import math
import os
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from services.localization.localization import is_japanese
from services.mapfetcher.mapgeometry import RouteGeometryProcessor
from services import tuning

from .glyphs import drawable


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

    # "Pill badge" style (see _render_pill_badge): a slim vertical capsule
    # used by the end-of-video recap instead of the big photo card, so many
    # can sit side by side without the lattice running out of slots at a
    # waypoint-heavy route (was overflowing past ~20 stops). Fixed WIDTH,
    # but the name is shown in full (no truncation) — its height grows with
    # the name's character count, so _layout_recap_cards sizes its lattice
    # off the longest name among the popups actually being shown, and each
    # individual badge is only as tall as its own (possibly shorter) name
    # needs.
    # Sized 1.4x the original drawing (34/20/46): the badges are what the recap IS, and at the
    # old size they read as footnotes on a 1920-wide frame. Not larger still - the lattice is
    # pitched for the longest NAME, and past ~1.5x a ten-character name leaves room for one row.
    _PILL_BADGE_W = 48
    _PILL_BADGE_NAME_CHARS = 4  # fallback length when the caller has no real name yet
    _PILL_BADGE_LINE_H = 28
    _PILL_BADGE_PHOTO_H = 64

    def beside_card_footprint(
        self, card_scale: float = 1.0, has_label: bool = True,
        is_pill_badge: bool = False,
        pill_name_chars: Optional[int] = None, pill_scale: float = 1.0,
    ) -> Tuple[int, int]:
        """Returns the (total_w, total_h) footprint render_popup_box will
        actually draw for a "beside the pin" card at this card_scale —
        assumes a label is present (has_label=True), a safe upper-bound
        estimate for collision-avoidance sizing even on the rare card with
        no real label. Sized for a WORST-CASE two-line label (see
        _fit_label_caption) since this is called without knowing the
        actual label text — a one-line label just leaves a little extra
        clearance below its card instead of the two cards ever visually
        overlapping because this estimate came in short.

        `is_pill_badge`: the vertical pill-badge footprint (see
        _render_pill_badge) — also ignores card_scale/has_label. Pass
        `pill_name_chars` (the real name's character count) for an exact
        fit, or leave it out for the fallback _PILL_BADGE_NAME_CHARS
        estimate (e.g. sizing ahead of knowing the real name)."""
        if is_pill_badge:
            return self.pill_badge_footprint(pill_name_chars, pill_scale)
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

    def pill_badge_footprint(
        self, name_chars: Optional[int] = None, scale: float = 1.0
    ) -> Tuple[int, int]:
        """(w, h) of the vertical pill badge (see _render_pill_badge):
        number circle + `name_chars` name lines (the full name, no
        truncation — pass the real name's character count) + photo. Every
        badge draws at the SAME `scale`/text size — only `name_chars`
        (and so the height) differs per badge, never the text itself.
        `name_chars=None` falls back to _PILL_BADGE_NAME_CHARS, a rough
        estimate for a caller sizing ahead of knowing the real name."""
        w = max(1, round(self._PILL_BADGE_W * scale))
        line_h = self._PILL_BADGE_LINE_H * scale
        photo_h = self._PILL_BADGE_PHOTO_H * scale
        bd = w - round(8 * scale)
        chars = self._PILL_BADGE_NAME_CHARS if name_chars is None else max(1, name_chars)
        h = round(5 * scale + bd + 6 * scale + chars * line_h + photo_h)
        return w, h

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

        text = drawable(text)
        if draw.textlength(text, font=font) <= max_width:
            return [text], font

        best_split, best_diff = 1, None
        # Text with no Japanese breaks between words ("Katsuragi Mi|kumari" read as two broken words).
        spaces = [i for i, ch in enumerate(text) if ch == " "] if not is_japanese(text) else []
        for i in spaces or range(1, len(text)):
            diff = abs(
                draw.textlength(text[:i], font=font) - draw.textlength(text[i:], font=font)
            )
            if best_diff is None or diff < best_diff:
                best_diff, best_split = diff, i
        lines = [text[:best_split], text[best_split:]]
        if spaces:
            lines = [lines[0].rstrip(), lines[1].lstrip()]

        size = font.size
        longest = max(draw.textlength(line, font=font) for line in lines)
        while longest > max_width and size > self._LABEL_MIN_FONT_SIZE:
            size = max(self._LABEL_MIN_FONT_SIZE, int(size * 0.9))
            font = self._card_font(font_candidates, size)
            longest = max(draw.textlength(line, font=font) for line in lines)
        return lines, font

    def slide_to_card(self, data: Dict, photo: np.ndarray) -> np.ndarray:
        """The "map" overview's pop-up: the photo for OVERVIEW_MAP_PHOTO_SECONDS of being shown, then it slides
        left and the stop's leg card (data["leg_card_bgr"], map_style.attach_leg_cards) slides in after it.
        Counts the frames each stop's card has been drawn (one draw per frame)."""
        card = data.get("leg_card_bgr")
        if card is None:
            return photo
        counts = self.__dict__.setdefault("_slide_frames", {})
        shown = counts[id(data)] = counts.get(id(data), 0) + 1
        p = (shown / getattr(self, "slide_fps", 30) - tuning.OVERVIEW_MAP_PHOTO_SECONDS) / tuning.OVERVIEW_MAP_SLIDE_SECONDS
        if p <= 0:
            return photo
        p = min(1.0, p)
        p = p * p * (3 - 2 * p)
        h, w = card.shape[:2]
        ph, pw = photo.shape[:2]
        s = max(w / pw, h / ph)
        fit = cv2.resize(photo, (math.ceil(pw * s), math.ceil(ph * s)), interpolation=cv2.INTER_AREA)
        y0, x0 = (fit.shape[0] - h) // 2, (fit.shape[1] - w) // 2
        fit = fit[y0:y0 + h, x0:x0 + w]
        shift = int(round(p * w))
        out = card.copy()
        out[:, : w - shift] = fit[:, shift:]
        out[:, w - shift:] = card[:, :shift]
        return out

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
            font = self._card_font(self.FONT_CANDIDATES_REGULAR, font_size)
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
        if popup_info.get("is_pill_badge"):
            name = drawable(popup_info.get("label") or "")
            total_w, total_h = self.pill_badge_footprint(
                len(name), popup_info.get("pill_scale", 1.0)
            )
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

    def _render_pill_badge(
        self, working_frame: np.ndarray, popup_info: Dict, pop_img: Any,
        box_x: int, box_y: int, total_w: int, total_h: int,
    ) -> np.ndarray:
        """Draws the "pill badge" style used by the end-of-video recap: a
        slim VERTICAL capsule, top to bottom — number badge, place name
        (one character per line), then the photo bleeding edge-to-edge and
        clipped flush to the capsule's own rounded bottom corner (not a
        separate inset thumbnail). Narrow enough that many can sit side by
        side in the recap's lattice without the capacity wall a full photo
        card hits past ~20 waypoints. `popup_info["pill_scale"]` (1.0 for
        every badge today) scales the name font and line pitch along with
        the capsule itself — total_w/total_h already reflect it (see
        pill_badge_footprint), so only the two pieces sized off the fixed
        constants directly (font, line pitch) need it applied here too."""
        pill_scale = float(popup_info.get("pill_scale", 1.0))
        h, w = working_frame.shape[:2]
        pad = 10
        rx0, ry0 = max(0, box_x - pad), max(0, box_y - pad)
        rx1, ry1 = min(w, box_x + total_w + pad), min(h, box_y + total_h + pad)
        bx, by = box_x - rx0, box_y - ry0
        canvas = Image.new("RGBA", (rx1 - rx0, ry1 - ry0), (0, 0, 0, 0))
        radius = total_w / 2.0

        border_color = popup_info.get("border_color") or self.card_border_color
        circle_rgba = tuple(reversed(border_color)) + (255,)

        shadow_box = [bx - 6, by - 4, bx + total_w + 6, by + total_h + 6]
        m = 24
        sx0, sy0 = int(shadow_box[0]) - m, int(shadow_box[1]) - m
        shadow_canvas = Image.new(
            "RGBA", (int(shadow_box[2]) - sx0 + m + 1, int(shadow_box[3]) - sy0 + m + 1), (0, 0, 0, 0)
        )
        ImageDraw.Draw(shadow_canvas).rounded_rectangle(
            [shadow_box[0] - sx0, shadow_box[1] - sy0, shadow_box[2] - sx0, shadow_box[3] - sy0],
            radius=radius, fill=circle_rgba[:3] + (55,),
        )
        canvas.paste(shadow_canvas.filter(ImageFilter.GaussianBlur(radius=10)), (sx0, sy0))
        draw = ImageDraw.Draw(canvas)

        draw.rounded_rectangle(
            [bx, by, bx + total_w - 1, by + total_h - 1], radius=radius,
            fill=self.ui["card_bg"][:3] + (250,),
        )

        # 1. number badge, top of the pill
        bd = total_w - 8
        cbx, cby = bx + 4, by + 5
        draw.ellipse([cbx, cby, cbx + bd, cby + bd], fill=circle_rgba)
        # "badge_label" is the glyph its own pin shows — "S"/"E"/"・"/the
        # visit number (see overview.py) — so the badge and the pin agree;
        # "order" is the fallback for a caller that sets no label.
        order_text = str(popup_info.get("badge_label") or popup_info.get("order") or "")
        if order_text:
            num_font = self._card_font(self.FONT_CANDIDATES_BOLD, max(11, int(bd * 0.5)))
            tw = draw.textlength(order_text, font=num_font)
            draw.text(
                (cbx + bd / 2 - tw / 2, cby + bd / 2 - num_font.size / 2),
                order_text, font=num_font, fill=(255, 255, 255, 255),
            )

        # 2. place name, one character per line, under the number, shown
        # in FULL (no truncation) — total_h was already sized for this
        # exact name's length (see popup_card_geometry's is_pill_badge
        # branch / pill_badge_footprint).
        name = drawable(popup_info.get("label") or "")
        # Off the line pitch, so the badge's three sizes stay one decision.
        name_font = self._card_font(
            self.FONT_CANDIDATES_REGULAR, max(9, round(self._PILL_BADGE_LINE_H * 0.75 * pill_scale))
        )
        line_h = self._PILL_BADGE_LINE_H * pill_scale
        ty = cby + bd + 6
        cx = bx + total_w / 2.0
        for ch in name:
            cw = draw.textlength(ch, font=name_font)
            draw.text((cx - cw / 2, ty), ch, font=name_font, fill=self.ui["card_text"])
            ty += line_h
        photo_y0 = ty

        # 3. photo, bleeding edge-to-edge at the bottom, clipped to the
        # pill's OWN outline — square at the top where it meets the name,
        # rounded at the bottom to match the capsule's own corner.
        if pop_img is not None:
            photo_h = (by + total_h) - photo_y0
            if photo_h > 1:
                src_h, src_w = pop_img.shape[:2]
                scale = max(total_w / src_w, photo_h / src_h)
                fit_w, fit_h = max(1, math.ceil(src_w * scale)), max(1, math.ceil(src_h * scale))
                resized = cv2.resize(pop_img, (fit_w, fit_h))
                cx0, cy0 = max(0, (fit_w - total_w) // 2), max(0, (fit_h - int(photo_h)) // 2)
                photo = resized[cy0 : cy0 + int(photo_h), cx0 : cx0 + total_w]
                photo_pil = Image.fromarray(cv2.cvtColor(photo, cv2.COLOR_BGR2RGB))
                pmask = Image.new("L", (total_w, int(photo_h)), 0)
                pmask_radius = max(1, min(radius, photo_h / 2.0) - 1)
                ImageDraw.Draw(pmask).rounded_rectangle(
                    [0, 0, total_w - 1, int(photo_h) - 1], radius=pmask_radius,
                    fill=255, corners=(False, False, True, True),
                )
                canvas.paste(photo_pil, (bx, int(photo_y0)), mask=pmask)

        base_pil = Image.fromarray(cv2.cvtColor(working_frame[ry0:ry1, rx0:rx1], cv2.COLOR_BGR2RGBA))
        base_pil.alpha_composite(canvas)
        working_frame[ry0:ry1, rx0:rx1] = cv2.cvtColor(np.array(base_pil), cv2.COLOR_RGBA2BGR)
        return working_frame

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
            pop_img = None if line_only else self.read_image_safe(image_path, copy=False)  # only resized below
            if pop_img is not None and "recap_line_color" not in popup_info:
                pop_img = self.slide_to_card(popup_info["data"], pop_img)
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
                    # the pin it's meant to connect to. "leader_from"
                    # overrides both: a point this ONE line should start
                    # from instead of its own pin (the recap's shared
                    # line for a cluster of near pins — see
                    # _layout_recap_cards), without moving the pin itself.
                    leader_from = popup_info.get("leader_from")
                    if leader_from is not None:
                        point_x, point_y = int(leader_from[0]), int(leader_from[1])
                    else:
                        point_x = int(popup_info.get("pin_x", popup_info["x"]))
                        point_y = int(popup_info.get("pin_y", popup_info["y"]))
                    # Defaults to the card's own pin color (same as its
                    # shadow tint below) rather than a flat neutral gray,
                    # so the line, pin and card read as one color family;
                    # a caller with several lines on screen at once (e.g.
                    # the end-of-video recap) still passes its own
                    # "leader_line_color" to tell cards apart.
                    line_color = popup_info.get("leader_line_color") or popup_info.get("border_color") or (130, 130, 130)
                    # Callers showing many lines at once (the end-of-video
                    # recap) thicken theirs — a 2px hairline gets lost
                    # against a busy map once there are a dozen-plus cards.
                    line_width = int(popup_info.get("leader_line_width", 3))
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
                        # — pick whichever edge (or corner) of the box is
                        # actually nearest the pin, then route through one
                        # elbow bend (horizontal, then vertical) rather
                        # than a raw diagonal: the common editorial-map
                        # leader-line convention, and it reads as drafted
                        # rather than a stray line cutting across the map.
                        # Skipped when the pin and card already share an
                        # axis (anchor equals the pin on one coordinate) —
                        # a straight segment there is just as tidy.
                        anchor_x = min(max(point_x, box_x), box_x + total_w)
                        anchor_y = min(max(point_y, box_y), box_y + total_h)
                        if point_x != anchor_x and point_y != anchor_y:
                            via_x, via_y = anchor_x, point_y
                            cv2.line(
                                working_frame, (point_x, point_y), (via_x, via_y),
                                line_color, line_width, cv2.LINE_AA,
                            )
                            cv2.line(
                                working_frame, (via_x, via_y), (anchor_x, anchor_y),
                                line_color, line_width, cv2.LINE_AA,
                            )
                        else:
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

                if popup_info.get("is_pill_badge"):
                    working_frame = self._render_pill_badge(
                        working_frame, popup_info, pop_img, box_x, box_y, total_w, total_h,
                    )
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
                # Rounded UP (never to nearest, never floored): rounding a
                # cover-fit's scaled size DOWN can undershoot the target box
                # by a pixel, leaving a thin sliver of whatever is behind
                # the photo (the card's own white background) visible along
                # its cropped edge instead of photo all the way to the edge.
                fit_w = max(1, math.ceil(src_w * scale))
                fit_h = max(1, math.ceil(src_h * scale))
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
                    font = self._card_font(
                        self.FONT_CANDIDATES_BOLD,
                        max(self._LABEL_MIN_FONT_SIZE, int(cover_scrim_h * 0.55)),
                    )
                else:
                    # Regular, not bold — LINE Seed JP's regular weight reads
                    # clearly enough at this size (unlike the old Kosugi Maru
                    # default this used to be bumped to bold for), and matches
                    # the smaller, lighter caption look under the photo.
                    font = self._card_font(self.FONT_CANDIDATES_REGULAR, font_size)
                has_label = RouteGeometryProcessor.is_real_label(label_text)
                has_label = (
                    RouteGeometryProcessor.is_real_label(label_text)
                    and bool(popup_info.get("show_label", True))
                )

                # Composited on the card's own patch (the shadow's reach below), not the whole frame: a full-frame
                # canvas and two full-frame conversions per card per frame made each card cost ~28 ms.
                rx0, ry0 = max(0, box_x - 50), max(0, box_y - 48)
                rx1, ry1 = min(w, box_x + total_w + 51), min(h, box_y + total_h + 59)
                box_x, box_y = box_x - rx0, box_y - ry0
                pil_canvas = Image.new("RGBA", (rx1 - rx0, ry1 - ry0), (0, 0, 0, 0))
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
                    box_x - 8,
                    box_y - 6,
                    box_x + total_w + 8,
                    box_y + total_h + 18,
                ]
                # Neutral black for the cover style specifically — no
                # border to tie a colored shadow back to, and a colored
                # glow around an otherwise borderless full-bleed photo
                # read as a border that was never actually removed.
                shadow_rgba = (0, 0, 0, 60) if is_cover else border_rgba[:3] + (60,)
                # Blurred on a small canvas around the shadow, not the whole frame (most of the overview's time).
                m = 44
                sx0, sy0 = int(shadow_box[0]) - m, int(shadow_box[1]) - m
                small = Image.new("RGBA", (int(shadow_box[2]) - sx0 + m + 1, int(shadow_box[3]) - sy0 + m + 1), (0, 0, 0, 0))
                ImageDraw.Draw(small).rounded_rectangle(
                    [shadow_box[0] - sx0, shadow_box[1] - sy0, shadow_box[2] - sx0, shadow_box[3] - sy0],
                    radius=18, fill=shadow_rgba,
                )
                pil_canvas.paste(small.filter(ImageFilter.GaussianBlur(radius=17)), (sx0, sy0))
                draw = ImageDraw.Draw(pil_canvas)

                # PIL's rectangle coordinates are INCLUSIVE of the second
                # point, so [box_x, ..., box_x + total_w, ...] actually
                # fills total_w + 1 columns (and total_h + 1 rows) - one
                # pixel wider/taller than the photo below, which uses the
                # same -1 the mask does. That extra column/row of white
                # card showed as a thin white line along the photo's right
                # (and bottom) edge, since the photo never reached it.
                card_box = [box_x, box_y, box_x + total_w - 1, box_y + total_h - 1]
                draw.rounded_rectangle(
                    card_box,
                    radius=18,
                    fill=self.ui["card_bg"][:3] + (250,),
                )

                base_pil = Image.fromarray(cv2.cvtColor(working_frame[ry0:ry1, rx0:rx1], cv2.COLOR_BGR2RGBA))
                base_pil.paste(pil_canvas, (0, 0), pil_canvas)

                pil_img = Image.fromarray(cv2.cvtColor(pop_img, cv2.COLOR_BGR2RGB))
                # Transparent everywhere but the rounded photo shape: the mask
                # used to start fully opaque (255), so drawing the rounded
                # rectangle in 255 changed nothing and the photo was pasted
                # square over the card's rounded top corners.
                mask = Image.new("L", (pw, ph), 0)
                mask_draw = ImageDraw.Draw(mask)
                # Photo is full-bleed (flush to the card's left/right/top
                # edges, no white margin) — its mask uses the SAME corner
                # radius as the outer card (14) so the photo's own rounded
                # corners line up with the card's, instead of a smaller
                # radius leaving a sliver of white card visible behind it.
                # With the name printed under it, the photo's bottom edge
                # meets that white caption area, so only its top is rounded.
                caption_below = has_label and not is_cover
                mask_draw.rounded_rectangle(
                    [0, 0, pw - 1, ph - 1], radius=18, fill=255,
                    corners=(True, True, not caption_below, not caption_below),
                )

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
                        # clipped to the photo's rounded corners, so the dark
                        # gradient does not square them off again
                        scrim.putalpha(ImageChops.multiply(
                            scrim.getchannel("A"), mask.crop((0, 0, pw, scrim_h))
                        ))
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
                                line, font=label_font, fill=self.ui["card_text"],
                            )
                            line_y += label_font.size + line_gap

                working_frame[ry0:ry1, rx0:rx1] = cv2.cvtColor(np.array(base_pil), cv2.COLOR_RGBA2BGR)

        if alpha < 1.0:
            working_frame = self._fade_to_base(working_frame, alpha, target_frame)
        return working_frame
