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
        spread: bool = False,
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

        `spread=True` (used for the end-of-video recap, where every card
        is shown at once and can land anywhere) instead seeds each card's
        starting column by its LEFT-TO-RIGHT rank among the group — the
        leftmost pin's card starts near the frame's left edge, the
        rightmost near its right edge, evenly spaced between — rather than
        each card starting right beside its own pin. Left beside its own
        pin, cards for pins clustered together (as most waypoints are)
        would all seed from nearby positions and only fan out once they
        collide, leaving whole sides of the frame empty; ranking spreads
        them across the full width from the start."""
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

        rank_by_id: Dict[int, int] = {}
        if spread:
            for rank, bp in enumerate(sorted(group, key=lambda b: b["popup"]["x"])):
                rank_by_id[id(bp["popup"])] = rank

        def free_spot(
            x: float, y: float, popup_id: Optional[int] = None
        ) -> Optional[Tuple[float, float]]:
            if spread and popup_id in rank_by_id:
                n = max(1, len(rank_by_id) - 1)
                frac = rank_by_id[popup_id] / n
                start_x = margin + frac * (w - card_w - 2 * margin)
            else:
                # Leader-line length: how far the card starts from its pin
                # before any avoidance kicks in — long enough that a route
                # line passing close to the pin (very common, it just
                # arrived there) doesn't get planted on immediately.
                start_x = x + 55 if x < w * 0.5 else x - card_w - 55
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
                popup.get("pin_x", popup["x"]), popup.get("pin_y", popup["y"]), id(popup)
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
        Cards are laid out with the same overlap/route-avoidance search as
        the flow-through popups, but with no concurrency cap (all of them
        at once) and a much larger search radius (a card can land anywhere
        on the frame, not just close to its pin), since the point here is
        a complete visual recap rather than staying near the traveler.
        Replaces just showing the LAST waypoint's card alone in a fixed
        HUD corner through the whole summary. `reserved_boxes` blocks off
        any other fixed UI (e.g. the summary stat card, composited over
        this same frame afterward) so a card doesn't land right where
        that's about to be drawn."""
        recap_frame = base_frame.copy()
        recap_popups = [ap for ap in active_popups if ap["data"].get("popup_image")]
        if not recap_popups:
            return recap_frame

        group = [{"popup": ap, "frames_left": 1} for ap in recap_popups]
        self._layout_beside_popups(
            group, w, h, route_obstacles=route_obstacles,
            max_radius=float(max(w, h)), reserved_boxes=list(reserved_boxes or []),
            spread=True,
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
            hud_popup["leader_line_color"] = pin_color or self.graphics.marker_color
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
    def _make_baked_popup(cls, popup: Dict, display_seconds: float, fps: int) -> Dict:
        """A baked_popups entry: `popup` is the waypoint dict itself (later
        copied and handed to render_popup_box); the rest is bookkeeping for
        _composite_baked_popups. `total_frames` is fixed at creation and,
        together with `fade_frames`, defines the fade envelope (see
        _popup_fade_alpha); `frames_left` counts down as it's actually
        shown; `waited_frames`/`max_wait_frames` bound how long a
        flow-through card can sit queued for a concurrency slot (see
        _composite_baked_popups) before giving up rather than finally
        appearing long after the traveler has moved on."""
        total_frames = max(1, int(display_seconds * fps))
        fade_frames = max(1, min(int(cls._POPUP_FADE_SECONDS * fps), total_frames // 4))
        return {
            "popup": popup,
            "frames_left": total_frames,
            "total_frames": total_frames,
            "fade_frames": fade_frames,
            "waited_frames": 0,
            "max_wait_frames": total_frames,
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
                if wp["data"].get("triggered") or wp["index"] == 0:
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

            gave_up = bp["waited_frames"] > bp["max_wait_frames"]
            if bp["frames_left"] > 0 and not gave_up:
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
