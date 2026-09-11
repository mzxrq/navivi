"""Flow-through/beside popup card layout, baked-popup lifecycle, recap frame,
and the end-of-video highlight's higher-zoom image fetch."""

import math
from typing import Dict, List, Optional, Tuple

import numpy as np

from services import tuning

from .base import logger


class _PopupMixin:
    def _layout_beside_popups(
        self,
        group: List[Dict],
        w: int,
        h: int,
        card_w: Optional[int] = None,
        card_h: Optional[int] = None,
        margin: int = 20,
        route_obstacles: Optional[np.ndarray] = None,
        max_radius: float = 260.0,
        reserved_boxes: Optional[List[Tuple[float, float, float, float]]] = None,
    ) -> None:
        """For waypoints flowing through without a freeze, their popup cards
        ride along the frame instead of holding it — small thumbnail cards
        with a leader line back to their own pin (see render_popup_box's
        non-HUD-corner branch).

        A cluster of close-together waypoints can trigger within seconds of
        each other, so several cards are often on screen at once. Rather
        than forcing them into a fixed column grid (which reads as a rigid
        wall of cards, and still overlaps once a column runs out of room),
        each card starts at a short leader-line's distance beside its own
        pin and, if that spot is already taken (by another card, OR by the
        route line itself — see `route_obstacles`), spirals outward —
        checking against every previously placed card's actual rectangle,
        not just ones in the same column/row — until it lands somewhere on
        the frame that's genuinely free. Cards end up scattered near their
        own waypoint rather than lined up, and never overlap another
        visible card or sit on top of the path they're next to.

        The spiral is capped to a fairly tight radius: if a card can't find
        room reasonably close to its own pin (a big cluster with many
        concurrent cards), it's simply left undrawn for this frame instead
        of drifting off into an empty, unrelated corner of the map — it
        gets another chance to appear on a later frame once other cards
        nearby have expired and freed up space.

        Also used (with a generous `max_radius`) for the end-of-video
        recap, where every card is shown at once — every card still seeds
        right beside its OWN pin first (not spread across the frame by
        rank), so a card only ends up far from its pin when the spiral
        search genuinely couldn't find room nearby; this used to seed
        recap cards by left-to-right rank across the whole frame width
        instead, which routinely produced long leader lines crossing the
        entire map even when the card's own pin had free space right next
        to it."""
        if card_w is None or card_h is None:
            # Matches render_popup_box's actual drawn card size exactly
            # (see beside_card_footprint) — a mismatch here is what let
            # concurrently-visible cards visually overlap despite this
            # layout step believing they didn't.
            footprint_w, footprint_h = self.graphics.beside_card_footprint()
            card_w = card_w if card_w is not None else footprint_w
            card_h = card_h if card_h is not None else footprint_h
        placed: List[Tuple[float, float, float, float]] = list(reserved_boxes or [])
        route_x = route_obstacles[:, 0] if route_obstacles is not None else None
        route_y = route_obstacles[:, 1] if route_obstacles is not None else None

        # Leader-line length: how far the card starts from its pin before
        # any avoidance kicks in — tied to the pin's own drawn size (rather
        # than a flat pixel constant) so the card starts right at its edge
        # plus a small gap, long enough that a route line passing close to
        # the pin (very common, it just arrived there) doesn't get planted
        # on immediately, but no longer than that.
        lead_offset = self.graphics.marker_radius + 20

        def free_spot(x: float, y: float) -> Optional[Tuple[float, float]]:
            start_x = x + lead_offset if x < w * 0.5 else x - card_w - lead_offset
            start_y = y - card_h / 2

            def clamp(bx: float, by: float) -> Tuple[float, float]:
                return (
                    max(margin, min(bx, w - card_w - margin)),
                    max(margin, min(by, h - card_h - margin)),
                )

            # A small buffer on top of the raw rectangles so two cards end
            # up with a visible gap between them instead of just touching
            # edge-to-edge (which, at video resolution, reads as
            # overlapping even though it technically isn't).
            card_gap = 14

            def overlaps(bx: float, by: float) -> bool:
                rx0, ry0, rx1, ry1 = (
                    bx - card_gap, by - card_gap,
                    bx + card_w + card_gap, by + card_h + card_gap,
                )
                if any(
                    rx0 < px1 and rx1 > px0 and ry0 < py1 and ry1 > py0
                    for (px0, py0, px1, py1) in placed
                ):
                    return True
                if route_x is not None and len(route_x) > 0:
                    return bool(
                        np.any(
                            (route_x >= rx0) & (route_x <= rx1)
                            & (route_y >= ry0) & (route_y <= ry1)
                        )
                    )
                return False

            bx, by = clamp(start_x, start_y)
            if not overlaps(bx, by):
                return bx, by

            # [NOTE] [Animation] Archimedean-spiral search outward from the pin until a non-overlapping spot is found or max_radius is exhausted.
            angle, radius = 0.0, 0.0
            while radius < max_radius:
                radius += 5.0
                angle += 0.45
                bx, by = clamp(
                    start_x + radius * math.cos(angle),
                    start_y + radius * math.sin(angle),
                )
                if not overlaps(bx, by):
                    return bx, by

            return None  # too crowded nearby — sit this frame out

        # Trigger order, not screen position — so a cluster's cards fill in
        # the order the traveler actually reaches them.
        for bp in sorted(group, key=lambda b: b["popup"].get("order", 0)):
            popup = bp["popup"]
            # The card's leader line actually anchors on pin_x/pin_y when
            # set (render_popup_box's own preference — see its docstring)
            # — searching for a spot relative to the true x/y instead
            # would start the search from a different point than where
            # the line will actually connect, for any waypoint whose pin
            # got fanned out by _declutter_pins.
            spot = free_spot(
                popup.get("pin_x", popup["x"]), popup.get("pin_y", popup["y"])
            )
            if spot is None:
                # Clear any position from a previous frame — don't let it
                # keep rendering at a now-stale spot that may itself have
                # since become occupied by another card.
                popup.pop("beside_box", None)
                continue
            box_x, box_y = spot
            popup["beside_box"] = (int(box_x), int(box_y))
            placed.append((box_x, box_y, box_x + card_w, box_y + card_h))

    def _layout_recap_popups(
        self,
        group: List[Dict],
        w: int,
        h: int,
        card_w: Optional[int] = None,
        card_h: Optional[int] = None,
        margin: int = 20,
        reserved_boxes: Optional[List[Tuple[float, float, float, float]]] = None,
        route_obstacles: Optional[np.ndarray] = None,
    ) -> None:
        """End-of-video recap layout: a pin in the frame's left third
        always gets its card placed on the left, a pin in the right third
        always on the right — a card never crosses the frame to the
        opposite side from its own pin, which is disorienting regardless
        of how clean the packing looks otherwise. A pin in the middle
        third isn't tied to either side and picks whichever currently has
        more free room. Within its required side, a card still starts as
        close as possible to its own pin (mirrors _layout_beside_popups's
        own near-pin start) and packs like masonry tiles against already-
        placed neighbors' edges — tight, with no big empty holes — but
        the leader line is free to stretch as long or short as necessary
        to stay in bounds; it never wins by crossing sides.

        Processed in ANGULAR order around the whole recap cluster's
        centroid — not trigger order — so pins that are geographically
        next to each other get their cards placed one after another too;
        processing them in an unrelated order is what let two nearby
        pins' lines end up crossing even though nothing forced them to."""
        if card_w is None or card_h is None:
            footprint_w, footprint_h = self.graphics.beside_card_footprint()
            card_w = card_w if card_w is not None else footprint_w
            card_h = card_h if card_h is not None else footprint_h

        placed: List[Tuple[float, float, float, float]] = list(reserved_boxes or [])
        route_x = route_obstacles[:, 0] if route_obstacles is not None else None
        route_y = route_obstacles[:, 1] if route_obstacles is not None else None
        # Wider than the flow-through popups' own gap (14px) — the recap
        # shows every card at once, so a tight 14px pack read as one
        # solid, cramped block rather than a set of distinct cards; more
        # breathing room between neighbors makes the layout read as
        # deliberately separated instead of jammed together.
        card_gap = 34

        def overlaps(bx: float, by: float) -> bool:
            rx0, ry0, rx1, ry1 = (
                bx - card_gap, by - card_gap,
                bx + card_w + card_gap, by + card_h + card_gap,
            )
            if any(
                rx0 < px1 and rx1 > px0 and ry0 < py1 and ry1 > py0
                for (px0, py0, px1, py1) in placed
            ):
                return True
            if route_x is not None and len(route_x) > 0:
                return bool(
                    np.any(
                        (route_x >= rx0) & (route_x <= rx1)
                        & (route_y >= ry0) & (route_y <= ry1)
                    )
                )
            return False

        def clamp(bx: float, by: float) -> Tuple[float, float]:
            return (
                max(margin, min(bx, w - card_w - margin)),
                max(margin, min(by, h - card_h - margin)),
            )

        def _segments_intersect(
            ax0: float, ay0: float, ax1: float, ay1: float,
            bx0: float, by0: float, bx1: float, by1: float,
        ) -> bool:
            def cross(o, a, b):
                return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

            p, q, r, s = (ax0, ay0), (ax1, ay1), (bx0, by0), (bx1, by1)
            d1, d2 = cross(r, s, p), cross(r, s, q)
            d3, d4 = cross(p, q, r), cross(p, q, s)
            return (d1 * d2 < 0) and (d3 * d4 < 0)

        def leader_crosses_placed(pin_x: float, pin_y: float, bx: float, by: float) -> bool:
            # Approximates this card's own leader line as pin -> card
            # center, then checks it against every OTHER already-placed
            # card's box — a candidate spot whose line would visually cut
            # across a different card is deprioritized (see free_spot),
            # even when the spot itself doesn't overlap anything.
            cx, cy = bx + card_w / 2, by + card_h / 2
            for (rx0, ry0, rx1, ry1) in placed:
                edges = (
                    (rx0, ry0, rx1, ry0), (rx1, ry0, rx1, ry1),
                    (rx1, ry1, rx0, ry1), (rx0, ry1, rx0, ry0),
                )
                if any(
                    _segments_intersect(pin_x, pin_y, cx, cy, ex0, ey0, ex1, ey1)
                    for ex0, ey0, ex1, ey1 in edges
                ):
                    return True
            return False

        left_zone = w / 3.0
        right_zone = w * 2.0 / 3.0
        top_zone = h / 3.0
        bottom_zone = h * 2.0 / 3.0

        def side_for(x: float) -> str:
            if x < left_zone:
                return "left"
            if x > right_zone:
                return "right"
            # A middle-third pin isn't tied to either side of its own map
            # position — pick whichever side of the FRAME currently has
            # more untouched room, so a center cluster spreads into
            # whichever direction actually has space instead of always
            # defaulting to one.
            return "left" if (x - margin) >= (w - margin - x) else "right"

        def vside_for(y: float) -> str:
            # Same thirds rule as side_for, on the vertical axis — a pin
            # near the top or bottom of the frame gets the same
            # above/below lock a left/right-zone pin gets horizontally.
            if y < top_zone:
                return "top"
            if y > bottom_zone:
                return "bottom"
            return "top" if (y - margin) >= (h - margin - y) else "bottom"

        def quadrant_ok(
            hside: str, vside: str, cbx: float, cby: float, pin_x: float, pin_y: float
        ) -> bool:
            # Hard rule: a card must sit entirely on its required side of
            # ITS OWN pin on BOTH axes — never past it horizontally OR
            # vertically. The leader line's length is unconstrained (see
            # free_spot below), only its direction.
            horiz_ok = (cbx + card_w <= pin_x + 1) if hside == "left" else (cbx >= pin_x - 1)
            vert_ok = (cby + card_h <= pin_y + 1) if vside == "top" else (cby >= pin_y - 1)
            return horiz_ok and vert_ok

        def free_spot(x: float, y: float) -> Optional[Tuple[float, float]]:
            hside = side_for(x)
            vside = vside_for(y)
            # Anchor gap scales with how much genuinely open room this
            # pin's required side actually has, rather than a flat 55px —
            # a pin sitting well into a spacious empty region (say, the
            # far side of the frame from a dense cluster of other pins)
            # used to still anchor its card right up against itself,
            # leaving that open space unused and cards crowded in toward
            # the middle. Capped so it doesn't stretch absurdly far on a
            # huge frame.
            avail_x = (x - margin) if hside == "left" else (w - margin - x)
            gap_x = max(55.0, min(avail_x * 0.4, 260.0))
            start_x = x - card_w - gap_x if hside == "left" else x + gap_x
            avail_y = (y - margin) if vside == "top" else (h - margin - y)
            gap_y = max(55.0, min(avail_y * 0.4, 260.0))
            start_y = y - card_h - gap_y if vside == "top" else y + gap_y

            # A uniform grid (an earlier version of this) guaranteed no
            # gaps but made every card across the whole frame snap onto
            # the same fixed rows/columns — unrelated clusters on
            # opposite sides of the frame ended up suspiciously
            # ruler-straight with each other. Instead, pack like tiles in
            # a masonry layout: try the pin's own near spot plus snapping
            # directly against the edges of cards already placed nearby
            # (right/left/top/bottom of each) — a new card then butts up
            # against a real neighbor's actual (organic, pin-derived)
            # position rather than an abstract lattice line, which is
            # what keeps the pack tight with no big empty holes without
            # looking like a table. Every candidate is still filtered by
            # quadrant_ok — packing against a neighbor on the WRONG side
            # of this pin (horizontally OR vertically) is exactly the
            # "left pin's card popped up on the right" bug, so that's
            # rejected same as an overlap would be.
            candidates: List[Tuple[float, float]] = [(start_x, start_y)]
            for (px0, py0, px1, py1) in placed:
                candidates.append((px1 + card_gap, py0))
                candidates.append((px0 - card_w - card_gap, py0))
                candidates.append((px0, py1 + card_gap))
                candidates.append((px0, py0 - card_h - card_gap))
            seen = set()
            deduped: List[Tuple[float, float]] = []
            for cx, cy in candidates:
                cbx, cby = clamp(cx, cy)
                if not quadrant_ok(hside, vside, cbx, cby, x, y):
                    continue
                key = (round(cbx), round(cby))
                if key in seen:
                    continue
                seen.add(key)
                deduped.append((cbx, cby))
            deduped.sort(key=lambda p: (p[0] - start_x) ** 2 + (p[1] - start_y) ** 2)

            # Two passes: first only accept a spot whose own leader line
            # doesn't cut across another card ("as much as possible" —
            # the hard rule is still just non-overlap, now alongside
            # quadrant_ok); only if nothing in the whole candidate set
            # manages that do we fall back to the closest merely-
            # non-overlapping (but still same-quadrant) spot.
            fallback: Optional[Tuple[float, float]] = None
            for cbx, cby in deduped:
                if overlaps(cbx, cby):
                    continue
                if fallback is None:
                    fallback = (cbx, cby)
                if not leader_crosses_placed(x, y, cbx, cby):
                    return cbx, cby
            if fallback is not None:
                return fallback

            # Nothing in the masonry candidate set worked (a very
            # dense/irregular cluster) — fall back to a continuous
            # spiral, still confined to the required quadrant (candidates
            # violating quadrant_ok are skipped, not just deprioritized —
            # the leader line grows as long as it needs to rather than
            # ever crossing to the wrong side on either axis), still
            # preferring a non-crossing spot if one turns up before a
            # plain non-overlapping one does.
            angle, radius = 0.0, 0.0
            max_radius = float(max(w, h)) * 1.5
            spiral_fallback: Optional[Tuple[float, float]] = None
            while radius < max_radius:
                radius += 5.0
                angle += 0.45
                bx, by = clamp(
                    start_x + radius * math.cos(angle), start_y + radius * math.sin(angle)
                )
                if not quadrant_ok(hside, vside, bx, by, x, y):
                    continue
                if overlaps(bx, by):
                    continue
                if spiral_fallback is None:
                    spiral_fallback = (bx, by)
                if not leader_crosses_placed(x, y, bx, by):
                    return bx, by
            if spiral_fallback is not None:
                return spiral_fallback

            # A pin sitting close enough to the frame's own edge that
            # there's no room at all for a full card in its required
            # quadrant (e.g. a left-zone pin within one card-width of the
            # left margin) — showing the card off-quadrant beats not
            # showing it at all, so this absolute last resort drops the
            # quadrant_ok requirement (everything else — no overlap,
            # prefer no line-crossing — still applies).
            angle, radius = 0.0, 0.0
            while radius < max_radius:
                radius += 5.0
                angle += 0.45
                bx, by = clamp(
                    start_x + radius * math.cos(angle), start_y + radius * math.sin(angle)
                )
                if not overlaps(bx, by):
                    return bx, by
            return None

        xs = [bp["popup"].get("pin_x", bp["popup"]["x"]) for bp in group]
        ys = [bp["popup"].get("pin_y", bp["popup"]["y"]) for bp in group]
        centroid_x = sum(xs) / len(xs) if xs else w / 2
        centroid_y = sum(ys) / len(ys) if ys else h / 2
        ordered = sorted(
            group,
            key=lambda bp: math.atan2(
                bp["popup"].get("pin_y", bp["popup"]["y"]) - centroid_y,
                bp["popup"].get("pin_x", bp["popup"]["x"]) - centroid_x,
            ),
        )

        for bp in ordered:
            popup = bp["popup"]
            spot = free_spot(popup.get("pin_x", popup["x"]), popup.get("pin_y", popup["y"]))
            if spot is None:
                popup.pop("beside_box", None)
                continue
            box_x, box_y = spot
            popup["beside_box"] = (int(box_x), int(box_y))
            placed.append((box_x, box_y, box_x + card_w, box_y + card_h))

    def _render_recap_frame(
        self,
        base_frame: np.ndarray,
        active_popups: List[Dict],
        w: int,
        h: int,
        route_obstacles: Optional[np.ndarray] = None,
        reserved_boxes: Optional[List[Tuple[float, float, float, float]]] = None,
    ) -> np.ndarray:
        """End-of-video recap: every waypoint with a photo gets its popup
        card shown at once, each with a leader line back to its own pin —
        start and end (see _draw_pin's "S"/"E" pins) laid out the same way
        as every other waypoint, no special fixed corner or enlarged card.
        A pin in the frame's left third always gets its card on the left,
        a right-third pin on the right, a middle-third pin on whichever
        side has more room (see _layout_recap_popups) — never crossing to
        the opposite side from its own pin, which for a real cluster of
        many nearby pins used to scatter cards unpredictably across the
        whole frame with leader lines crossing half the map. Replaces
        just showing the LAST waypoint's card alone
        in a fixed HUD corner through the whole summary. `reserved_boxes`
        blocks off any other fixed UI (e.g. the summary stat card,
        composited over this same frame afterward) so a card doesn't land
        right where that's about to be drawn."""
        recap_frame = base_frame.copy()
        recap_popups = [ap for ap in active_popups if ap["data"].get("popup_image")]
        if not recap_popups:
            return recap_frame

        group = [{"popup": ap, "frames_left": 1} for ap in recap_popups]
        self._layout_recap_popups(
            group, w, h, reserved_boxes=list(reserved_boxes or []),
            route_obstacles=route_obstacles,
        )

        total_points = 1 + max((ap["index"] for ap in active_popups), default=0)
        hud_popups = []
        for ap in recap_popups:
            if not ap.get("beside_box"):
                continue
            hud_popup = ap.copy()
            hud_popup["hud_corner"] = None
            hud_popup["draw_leader_line"] = True
            # With every waypoint's card shown at once, their leader lines
            # cross each other constantly — coloring each line to match its
            # own pin (rather than one flat gray for all of them) makes it
            # possible to actually trace a given card back to its pin
            # despite the crossings.
            _, pin_color = self._pin_label_and_color(ap, total_points)
            pin_color = pin_color or self.graphics.marker_color
            hud_popup["leader_line_color"] = pin_color
            # Override the card's own border_color (set once, early in
            # render_overview's setup, back when no waypoint had "arrived"
            # yet — see _pin_color) with this SAME color the line just
            # used, computed fresh right now instead — by the time the
            # recap plays, every waypoint genuinely has arrived, so a
            # border still showing the pre-arrival default color no
            # longer matched its own leader line's (freshly-computed,
            # arrived) color.
            hud_popup["border_color"] = pin_color
            hud_popups.append(hud_popup)

        # Three passes — every line, then every pin, then every card —
        # rather than each card's line+box together in one pass per
        # popup: with several cards on screen at once, a later popup's
        # line drawn together with its own card would otherwise land on
        # top of an earlier popup's already-drawn card (or pin) whenever
        # it happened to cross it. This guarantees every line sits behind
        # every pin AND every card, regardless of draw order — the pins
        # are already baked into `recap_frame` from the main animation
        # loop, so without redrawing them here on top of the lines, a
        # line whose path crosses near a DIFFERENT waypoint's pin would
        # visually run right through/over it.
        for hud_popup in hud_popups:
            recap_frame = self.graphics.render_popup_box(
                recap_frame, hud_popup, line_only=True
            )
        for ap in active_popups:
            self._draw_pin(recap_frame, ap, total_points)
        for hud_popup in hud_popups:
            recap_frame = self.graphics.render_popup_box(
                recap_frame, hud_popup, skip_line=True
            )
        return recap_frame

    # Target fade in/out duration for a popup, in seconds — kept within a
    # 1-3s window so it reads as a deliberate soft transition rather than
    # either an abrupt snap or a slow dissolve. Still capped per-popup (see
    # _make_baked_popup) to at most 25% of that popup's OWN display time on
    # each end (was 40% — for a short leg, fading in and out ate up to 80%
    # of its total display time, leaving the card looking half-transparent
    # for most of a quick, closely-spaced-waypoint stretch), so a short leg
    # still gets a solid, mostly-opaque hold rather than being dominated by
    # the fade.
    _POPUP_FADE_SECONDS = tuning.POPUP_FADE_SECONDS

    @classmethod
    def _make_baked_popup(
        cls, popup: Dict, display_seconds: float, fps: int, queue_depth: int = 0,
    ) -> Dict:
        """A baked_popups entry: `popup` is the waypoint dict itself (later
        copied and handed to render_popup_box); the rest is bookkeeping for
        _composite_baked_popups. `total_frames` is fixed at creation and,
        together with `fade_frames`, defines the fade envelope (see
        _popup_fade_alpha); `frames_left` counts down as it's actually
        shown; `waited_frames`/`max_wait_frames` bound how long a
        flow-through card can sit queued for a concurrency slot (see
        _composite_baked_popups) before giving up rather than finally
        appearing long after the traveler has moved on. The wait budget
        itself is at least tuning.POPUP_MIN_WAIT_SECONDS, not just
        `total_frames` — a tightly-clustered waypoint's own display
        duration can be floored quite short (see leg_display_seconds),
        which used to also cap how long it was willing to wait for a
        concurrency slot, sometimes shorter than the wait itself: a real
        cluster of 4+ nearby waypoints could make a later one wait longer
        than its own short display time for one of only
        MAX_CONCURRENT_FLOW_POPUPS slots, and it would give up having
        never been shown at all.

        `queue_depth` — how many OTHER already-triggered popups are still
        waiting behind this one for their own turn at the trigger cooldown
        (see the pending_popups queue in _animate_overview_frames) — further
        stretches the wait budget for a genuinely deep backlog. A fixed
        POPUP_MIN_WAIT_SECONDS was sized for one or two popups queued at
        once; for a real cluster of 5+ waypoints spaced close enough to all
        queue up within a couple of seconds of each other, the ones near the
        back of that queue still needed to wait roughly
        queue_depth * OVERVIEW_POPUP_MIN_TRIGGER_GAP_SECONDS just for their
        turn to even be dequeued, on top of then waiting for a free display
        slot — a wait budget sized without accounting for that backlog let
        several of them time out and vanish, having genuinely been reached
        by the traveler but never shown at all."""
        total_frames = max(1, int(display_seconds * fps))
        fade_frames = max(1, min(int(cls._POPUP_FADE_SECONDS * fps), total_frames // 4))
        backlog_wait_seconds = queue_depth * tuning.OVERVIEW_POPUP_MIN_TRIGGER_GAP_SECONDS
        max_wait_frames = max(
            total_frames,
            int((tuning.POPUP_MIN_WAIT_SECONDS + backlog_wait_seconds) * fps),
        )
        return {
            "popup": popup,
            "frames_left": total_frames,
            "total_frames": total_frames,
            "fade_frames": fade_frames,
            "waited_frames": 0,
            "max_wait_frames": max_wait_frames,
        }

    @staticmethod
    def _popup_fade_alpha(bp: Dict) -> float:
        """Fade envelope (0-1) for a baked popup at its current countdown
        position — ramps up over its first `fade_frames` and back down
        over its last, full opacity in between."""
        fade_frames = bp.get("fade_frames") or max(1, bp.get("total_frames", 1) // 5)
        elapsed = bp.get("total_frames", bp["frames_left"]) - bp["frames_left"]
        alpha_in = min(1.0, elapsed / fade_frames)
        alpha_out = min(1.0, bp["frames_left"] / fade_frames)
        return max(0.0, min(alpha_in, alpha_out))

    # How far below its final resting spot a popup card starts before
    # sliding up into place (and how far it slides back down when it's
    # dismissed), in pixels — a fixed distance (not proportional to card
    # size) so the slide reads the same regardless of how big any
    # particular card is.
    _POPUP_SLIDE_DISTANCE_PX = 40

    @classmethod
    def _popup_slide_offset_y(cls, bp: Dict) -> float:
        """Downward Y offset (pixels) for a baked popup's card at its
        current position in its lifecycle: eases DOWN from
        _POPUP_SLIDE_DISTANCE_PX to 0 while entering (so it slides UP into
        its real spot as it fades in), sits at exactly 0 for the rest of
        its display, then eases back UP from 0 to
        _POPUP_SLIDE_DISTANCE_PX while leaving (so it slides back DOWN —
        "archived" away — as it fades out), over the same `fade_frames`
        window _popup_fade_alpha ramps opacity over on each end, so each
        slide finishes right as its matching fade does. Ease-out cubic on
        both ends — no overshoot, just a smooth glide, not a bounce."""
        fade_frames = bp.get("fade_frames") or max(1, bp.get("total_frames", 1) // 5)
        total_frames = bp.get("total_frames", bp["frames_left"])
        frames_left = bp["frames_left"]
        elapsed = total_frames - frames_left

        if elapsed < fade_frames:
            t = max(0.0, min(1.0, elapsed / fade_frames))
            eased = 1 - (1 - t) ** 3
            return cls._POPUP_SLIDE_DISTANCE_PX * (1 - eased)

        if frames_left < fade_frames:
            t = max(0.0, min(1.0, 1 - frames_left / fade_frames))
            eased = 1 - (1 - t) ** 3
            return cls._POPUP_SLIDE_DISTANCE_PX * eased

        return 0.0

    def _composite_baked_popups(
        self,
        frame: np.ndarray,
        baked_popups: List[Dict],
        w: int,
        h: int,
        route_obstacles: Optional[np.ndarray],
        active_popups: Optional[List[Dict]] = None,
        total_points: int = 0,
    ) -> Tuple[np.ndarray, List[Dict]]:
        """Draws every currently-active popup (flow-through or lingering
        frozen) onto `frame` for this one frame, fading each in/out per
        _popup_fade_alpha, and returns (frame, survivors) — the entries
        whose countdown hasn't run out and haven't given up waiting.

        Flow-through cards (no freeze_frame) are capped to
        MAX_CONCURRENT_FLOW_POPUPS competing for layout space at once —
        oldest-triggered first, and already-visible ones keep priority
        over any new arrival so a shown popup is never evicted early — see
        _layout_beside_popups for how each one's position is found. Frozen
        ones always draw, in their fixed HUD corner, uncapped.

        Leader-lined (beside_box) cards are drawn line-first, then every
        already-triggered pin in `active_popups` is redrawn on top, then
        the cards themselves — same three-pass ordering as the recap and
        the per-leg intro — so a card's own leader line (or one it merely
        crosses on its way to a differently-placed pin) never renders on
        top of any pin. `active_popups` is optional only so callers that
        never have leader-lined cards (none currently) don't need to pass
        it; every real caller does."""
        MAX_CONCURRENT_FLOW_POPUPS = 3

        flowing = [
            bp for bp in baked_popups if not bp["popup"]["data"].get("freeze_frame", False)
        ]
        # [NOTE] [Animation] Already-visible cards (beside_box set) sort first so the concurrency cap slices them off last, keeping a shown popup from being evicted mid-display.
        flowing.sort(
            key=lambda b: (
                0 if b["popup"].get("beside_box") else 1,
                b["popup"].get("order", 0),
            )
        )
        flowing_visible = flowing[:MAX_CONCURRENT_FLOW_POPUPS]
        for bp in flowing[MAX_CONCURRENT_FLOW_POPUPS:]:
            bp["popup"].pop("beside_box", None)
        if flowing_visible:
            self._layout_beside_popups(
                flowing_visible, w, h, route_obstacles=route_obstacles
            )

        hud_popups: List[Optional[Dict]] = [None] * len(baked_popups)
        for i, bp in enumerate(baked_popups):
            hud_popup = bp["popup"].copy()
            if hud_popup["data"].get("freeze_frame", False):
                hud_popup.setdefault("hud_corner", "bottom_left")
            elif hud_popup.get("beside_box"):
                hud_popup["hud_corner"] = None
                hud_popup["draw_leader_line"] = True
            else:
                continue  # no free spot this frame — nothing to draw
            # Slide-up: each leader-lined card eases up into its real spot
            # from slightly below as it fades in, rather than just fading
            # in place — see _popup_slide_offset_y. Only for leader-lined
            # (beside_box) cards; a fixed-HUD-corner freeze_frame card has
            # no "below its real spot" that would read as a slide.
            if hud_popup.get("beside_box"):
                bx, by = hud_popup["beside_box"]
                hud_popup["beside_box"] = (bx, int(by + self._popup_slide_offset_y(bp)))
            hud_popups[i] = hud_popup

        any_leader_line = False
        for i, bp in enumerate(baked_popups):
            hud_popup = hud_popups[i]
            if hud_popup is not None and hud_popup.get("draw_leader_line"):
                any_leader_line = True
                frame = self.graphics.render_popup_box(
                    frame, hud_popup, alpha=self._popup_fade_alpha(bp), line_only=True
                )

        # Pins were already drawn once this frame, before this function
        # ran (see overview_animation.py) — only worth redrawing them here
        # (on top of the line(s) just drawn above) when there's actually a
        # leader line that could have crossed one; skip the redundant
        # redraw on every other frame.
        if any_leader_line:
            for wp in active_popups or []:
                if wp["data"].get("arrived") or wp["index"] == 0:
                    self._draw_pin(frame, wp, total_points)

        survivors = []
        for i, bp in enumerate(baked_popups):
            hud_popup = hud_popups[i]
            drawn = hud_popup is not None
            if drawn:
                frame = self.graphics.render_popup_box(
                    frame, hud_popup, alpha=self._popup_fade_alpha(bp),
                    skip_line=bool(hud_popup.get("draw_leader_line")),
                )

            # A popup's countdown only ticks while it's actually being
            # shown — one sitting out this frame (no free spot/no
            # concurrency slot) doesn't burn its display time invisibly
            # and get cut short once it does get a slot.
            if drawn:
                bp["frames_left"] -= 1
            else:
                bp["waited_frames"] += 1

            # Every waypoint the traveler actually reached must eventually
            # be shown — a popup no longer gives up and silently vanishes
            # just for having waited past max_wait_frames for a
            # concurrency slot (see _make_baked_popup's own docstring for
            # why that budget existed and why it still wasn't enough for
            # a deep-enough backlog). It only leaves the survivors list
            # once it has actually been displayed for its own full
            # duration (frames_left only decrements while drawn, so a
            # still-waiting popup can't run out this way either).
            # max_wait_frames/waited_frames are kept on the dict purely
            # as diagnostic bookkeeping now, not an eviction trigger.
            if bp["frames_left"] > 0:
                survivors.append(bp)

        return frame, survivors

    def _fetch_highlight_image(
        self, lat: float, lng: float, output_size: Tuple[int, int]
    ) -> Optional[Tuple[str, Tuple[float, float, float, float]]]:
        """Fetches a fresh, tightly-cropped (~300m across) map image
        centered on one lat/lng — a genuinely higher zoom level than the
        overview's own background, used for the end-of-video "zoom into
        this place" highlight. Returns (path, extent) so the caller can
        still project the same lat/lng onto this new image's pixels (for
        the marker/popup), or None (rather than raising) on any failure —
        a tile-download hiccup here shouldn't take down a render that's
        otherwise already finished."""
        try:
            from services.mapfetcher.mapfetcher import MapFetcher

            job_config = self._get_job_config()
            if not job_config:
                return None
            fetcher = MapFetcher(job_config=job_config)
            delta = 0.0015  # ~150-160m in latitude degrees either side
            bbox = {
                "min_lat": lat - delta, "max_lat": lat + delta,
                "min_lon": lng - delta, "max_lon": lng + delta,
            }
            out_path = str(self.out_dir / "01_overview_highlight.png")
            path, extent, _size = fetcher.fetch_image(bbox, out_path, output_size)
            return path, extent
        except Exception as e:
            logger.warning(f"Highlight zoom-in image fetch failed, skipping: {e}")
            return None
