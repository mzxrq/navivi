"""
Spatial Renderer Service (spatial_renderer.py)
---------------------------------------------------------------------------
Handles proximity-based triggering for the legacy overview and waypoint maps.
---------------------------------------------------------------------------
"""

import json
import math
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import cv2
import numpy as np

from services.mapfetcher.mapfetcher import MapFetcher
from services.mapfetcher.mapgeometry import RouteGeometryProcessor
from services.vdoprocessing.vdoexporter import VideoExporter
from services.mapfetcher.graphicengine import GraphicsEngine
from services.logger.logger import setup_logger

logger = setup_logger("SpatialRenderer")


class SpatialRenderer:
    # Fallback real-world average speed (km/h) per travel mode — overridable
    # per-project via job_config.json's settings.mode_speeds_kmh, e.g.
    # {"walking": 3, "car": 70, "ferry": 36}. These are what the on-screen
    # speed-up between modes is actually computed from (see
    # _mode_speed_factor below), not arbitrary multipliers.
    _DEFAULT_MODE_SPEED_KMH = {
        "walking": 6.0,
        "ferry": 75.0,
        "car": 70.0,
        "driving": 70.0,
        "airplane": 500.0,
    }
    # Fixed anchor "1x" pace that every mode's factor (including walking's
    # own) is computed against — NOT whatever "walking" happens to be
    # configured as. Self-normalizing against walking would make walking's
    # own configured speed a no-op (any value divided by itself is always
    # 1.0), which defeats the point of it being a tunable setting.
    _REFERENCE_KMH = 3.0

    def __init__(self, config: Dict[str, Any], graphics: GraphicsEngine, out_dir: Path):
        self.config = config
        self.graphics = graphics
        self.out_dir = out_dir

        mode_speed_kmh = {
            **self._DEFAULT_MODE_SPEED_KMH,
            **{
                str(k).lower(): float(v)
                for k, v in (config.get("mode_speeds_kmh") or {}).items()
            },
        }
        # How much faster each travel mode's leg is animated on screen —
        # derived from the configured real-world speeds rather than a
        # hand-picked ratio, so "car: 70 km/h" vs "walking: 4.5 km/h"
        # produces a genuinely proportionate speed-up, and tuning walking's
        # own speed actually changes its own on-screen pace too. Clamped so
        # no leg is compressed to a barely-visible handful of frames or, at
        # the other extreme, made slower than a near-standstill.
        self._mode_speed_factor = {
            mode: max(0.3, min(60.0, kmh / self._REFERENCE_KMH))
            for mode, kmh in mode_speed_kmh.items()
        }

        self.trigger_radius_padding = {
            # "overview" was generous enough (marker_radius + 25px) that a
            # waypoint's pin/popup could fire while the traveler was still
            # visibly short of it — tightened so arrival reads as actually
            # reaching the pin, not just passing near it. Both remain
            # overridable per-project via job_config.json's settings.
            **{"overview": 10, "waypoint": 15},
            **config.get("trigger_radius_padding", {}),
        }
        self.transition_cfg = {
            **{
                "scale_seconds": 0.8,
                "fade_out_seconds": 0.5,
                "hold_ratio_of_freeze": 0.4,
                "min_hold_seconds": 0.5,
                "min_small_hold_seconds": 0.1,
            },
            **config.get("fullscreen_transition", {}),
        }
        self.post_arrival_hold_seconds: float = config.get(
            "post_arrival_hold_seconds", 1.0
        )
        # Global kill switch for the "scale up to fill the screen" popup
        # style — when off, every waypoint (regardless of its own
        # image_display setting) uses the small pip card instead.
        self.enable_fullscreen_popups: bool = bool(
            config.get("enable_fullscreen_popups", True)
        )
        # When True, the route line is hidden (only pins/points stay visible)
        # for the duration a popup card is frozen on screen.
        self.hide_route_on_popup: bool = bool(config.get("hide_route_on_popup", False))
        # When True, only already-arrived waypoint pins are drawn during the
        # arrival pause/popup — with many stops on screen, every not-yet-
        # reached pin competing for attention makes it hard to tell which
        # one just triggered.
        self.hide_upcoming_pins_on_popup: bool = bool(
            config.get("hide_upcoming_pins_on_popup", False)
        )
        self.last_frame = None

    def _build_freeze_frame(
        self,
        current_bg: np.ndarray,
        path_history: List,
        mode_history: List[str],
        last_leg_boundary: int,
        active_popups: List[Dict],
        total_points: int,
    ) -> np.ndarray:
        """Background + route line (respecting hide_route_on_popup) + pins
        for ONLY already-arrived waypoints — used for the arrival pause and
        popup when hide_upcoming_pins_on_popup is on, so a route with many
        stops doesn't bury the one that just triggered under a scatter of
        still-ahead pins."""
        base = current_bg.copy()
        if self.hide_route_on_popup:
            self.graphics.draw_path(
                base,
                path_history[: last_leg_boundary + 1],
                mode_history[: last_leg_boundary + 1],
            )
        else:
            self.graphics.draw_path(base, path_history, mode_history)
        for order, wp in enumerate(active_popups, start=1):
            if wp["data"].get("triggered"):
                self._draw_pin(base, wp, order, total_points)
        return base

    def _layout_beside_popups(
        self,
        group: List[Dict],
        w: int,
        h: int,
        card_w: int = 190,
        card_h: int = 150,
        margin: int = 30,
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
            spot = free_spot(popup["x"], popup["y"], id(popup))
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

        for ap in recap_popups:
            if not ap.get("beside_box"):
                continue
            hud_popup = ap.copy()
            hud_popup["hud_corner"] = None
            hud_popup["draw_leader_line"] = True
            recap_frame = self.graphics.render_popup_box(recap_frame, hud_popup)
        return recap_frame

    # Target fade in/out duration for a popup, in seconds — kept within a
    # 1-3s window so it reads as a deliberate soft transition rather than
    # either an abrupt snap or a slow dissolve. Still capped per-popup (see
    # _make_baked_popup) to at most 40% of that popup's OWN display time on
    # each end, so a short leg doesn't end up all-fade with no solid hold.
    _POPUP_FADE_SECONDS = 1.5

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
        fade_frames = max(1, min(int(cls._POPUP_FADE_SECONDS * fps), total_frames * 2 // 5))
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
        ones always draw, in their fixed HUD corner, uncapped."""
        MAX_CONCURRENT_FLOW_POPUPS = 3

        flowing = [
            bp for bp in baked_popups if not bp["popup"]["data"].get("freeze_frame", False)
        ]
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

        survivors = []
        for bp in baked_popups:
            hud_popup = bp["popup"].copy()
            drawn = False
            if hud_popup["data"].get("freeze_frame", False):
                hud_popup.setdefault("hud_corner", "bottom_left")
                frame = self.graphics.render_popup_box(
                    frame, hud_popup, alpha=self._popup_fade_alpha(bp)
                )
                drawn = True
            elif hud_popup.get("beside_box"):
                hud_popup["hud_corner"] = None
                hud_popup["draw_leader_line"] = True
                frame = self.graphics.render_popup_box(
                    frame, hud_popup, alpha=self._popup_fade_alpha(bp)
                )
                drawn = True

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

    def _pin_color(self, wp: Dict):
        """Arrived waypoints get GraphicsEngine.arrived_marker_color; ones
        still ahead keep the default marker_color (return None so
        draw_marker falls back to it)."""
        return self.graphics.arrived_marker_color if wp["data"].get("triggered") else None

    def _declutter_pins(self, active_popups: List[Dict]) -> None:
        """When two or more waypoints sit within a marker's width of each
        other (a cluster of stops on the same small island, say), their
        pins fully overlap when drawn at their real pixel position — the
        later one painted on top completely hides the earlier one, not
        just crowds it. This fans clustered pins out in a small circle
        around their shared center (storing the result as "pin_x"/"pin_y",
        separate from the pin's real "x"/"y" — trigger detection, popup
        placement, etc. all keep using the real position) so every pin
        stays visible; _draw_pin then draws a short connector line back to
        the true spot for any pin that got moved."""
        n = len(active_popups)
        parent = list(range(n))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(i: int, j: int) -> None:
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[ri] = rj

        min_gap = self.graphics.marker_radius * 2.4
        for i in range(n):
            for j in range(i + 1, n):
                dx = active_popups[i]["x"] - active_popups[j]["x"]
                dy = active_popups[i]["y"] - active_popups[j]["y"]
                if math.hypot(dx, dy) < min_gap:
                    union(i, j)

        clusters: Dict[int, List[int]] = {}
        for i in range(n):
            clusters.setdefault(find(i), []).append(i)

        for members in clusters.values():
            if len(members) == 1:
                idx = members[0]
                active_popups[idx]["pin_x"] = active_popups[idx]["x"]
                active_popups[idx]["pin_y"] = active_popups[idx]["y"]
                continue

            cx = sum(active_popups[i]["x"] for i in members) / len(members)
            cy = sum(active_popups[i]["y"] for i in members) / len(members)
            fan_radius = min_gap * 0.8
            for k, idx in enumerate(
                sorted(members, key=lambda i: active_popups[i]["order"])
            ):
                angle = 2 * math.pi * k / len(members)
                active_popups[idx]["pin_x"] = cx + fan_radius * math.cos(angle)
                active_popups[idx]["pin_y"] = cy + fan_radius * math.sin(angle)

    # Start/end pins get a fixed, conventional color (green/red, matching
    # standard map-app iconography) regardless of arrival state — every
    # other pin still uses _pin_color's default/arrived coloring.
    _START_PIN_COLOR = (60, 180, 60)  # green (BGR)
    _END_PIN_COLOR = (0, 0, 220)  # red (BGR)

    def _draw_pin(
        self, frame: np.ndarray, wp: Dict, order: int, total_points: int
    ) -> None:
        """Draws one waypoint's pin at its (possibly decluttered) position,
        with a thin connector line back to its true spot when the two
        differ — see _declutter_pins. The very first and last points of the
        route (the trip's actual start/end) are labeled "S"/"E" instead of
        a visit number, even when a waypoint happens to share that exact
        coordinate with the configured start_point/end_point."""
        pin_color = self._pin_color(wp)
        if wp["index"] == 0:
            label: Any = "S"
            pin_color = self._START_PIN_COLOR
        elif wp["index"] == total_points - 1:
            label = "E"
            pin_color = self._END_PIN_COLOR
        else:
            label = order
        px, py = int(wp.get("pin_x", wp["x"])), int(wp.get("pin_y", wp["y"]))
        tx, ty = int(wp["x"]), int(wp["y"])
        if (px, py) != (tx, ty):
            cv2.line(frame, (px, py), (tx, ty), (150, 150, 150), 2, cv2.LINE_AA)
            cv2.circle(frame, (tx, ty), 3, (150, 150, 150), -1, cv2.LINE_AA)
        self.graphics.draw_marker(frame, px, py, number=label, color=pin_color)

    @staticmethod
    def _smoothed_heading(
        prev_angle: float,
        cx: int,
        cy: int,
        prev_cx: Optional[int],
        prev_cy: Optional[int],
        min_dist: float = 1.5,
        alpha: float = 0.35,
    ) -> float:
        """Blends the new frame-to-frame heading into the previous smoothed
        heading, and ignores movement smaller than `min_dist` outright.

        The animated path is now straight-line interpolation between the
        real (simplified) route points, so through a winding, non-straight
        stretch the true heading changes abruptly at every vertex — and
        `path_history` stores rounded integer pixel coordinates, so on a
        short step the raw atan2 direction is dominated by rounding noise
        rather than the actual travel direction. Both together make the
        travel icon visibly shake as it moves. Blending (circularly, via
        the sin/cos components — angles can't be linearly averaged across
        the 359°/0° wrap) trades a little turning responsiveness for a
        stable-looking heading.
        """
        if prev_cx is None or prev_cy is None:
            return prev_angle
        if math.hypot(cx - prev_cx, cy - prev_cy) < min_dist:
            return prev_angle
        raw_angle = math.degrees(math.atan2(cy - prev_cy, cx - prev_cx))
        prev_rad, raw_rad = math.radians(prev_angle), math.radians(raw_angle)
        x = math.cos(prev_rad) * (1 - alpha) + math.cos(raw_rad) * alpha
        y = math.sin(prev_rad) * (1 - alpha) + math.sin(raw_rad) * alpha
        return math.degrees(math.atan2(y, x))

    def _get_job_config(self) -> Optional[Dict]:
        for p in [self.out_dir] + list(self.out_dir.parents):
            potential_path = p / "job_config.json"
            if potential_path.exists():
                try:
                    with open(potential_path, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    pass
        return None

    def _get_job_waypoints(self) -> List[Dict]:
        return (self._get_job_config() or {}).get("waypoints", [])

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

    @staticmethod
    def _cut_fade_transition(
        video: VideoExporter,
        from_frame: np.ndarray,
        to_frame: np.ndarray,
        fps: int,
        duration_sec: float = 0.8,
    ) -> None:
        """Jump cut then fade: writes `from_frame` once more (the cut),
        then a plain crossfade dissolve into `to_frame` — no push/zoom
        motion, since `to_frame` is a different, non-geo-aligned image
        (a freshly fetched higher-zoom map) that a zoom/pan would not
        actually be zooming "into"."""
        video.write(from_frame)
        n = max(1, int(duration_sec * fps))
        for i in range(n):
            alpha = (i + 1) / n
            video.write(cv2.addWeighted(to_frame, alpha, from_frame, 1 - alpha, 0))

    def _blur_out(
        self, video: VideoExporter, frame: np.ndarray, fps: int, duration_sec: float = 0.5
    ) -> np.ndarray:
        """Writes a progressive out-of-focus blur of `frame` (increasing
        Gaussian blur radius each frame) as a soft closing beat, and
        returns the final, most-blurred frame. Used as the video's actual
        last frames instead of a hard cut or fade-to-black — a bare cut
        would jump straight into whatever plays next, and this reads
        smoothly even when the next clip opens on this exact picture."""
        n = max(1, int(duration_sec * fps))
        max_ksize = max(3, (min(frame.shape[:2]) // 20) | 1)  # odd, ~5% of the short edge
        blurred = frame
        for i in range(n):
            ksize = max(1, round((i + 1) / n * max_ksize)) | 1
            blurred = cv2.GaussianBlur(frame, (ksize, ksize), 0)
            video.write(blurred)
        return blurred

    def _render_recap_and_summary(
        self,
        video: VideoExporter,
        stop_popup: Optional[Dict],
        summary_card: Optional[np.ndarray],
        active_popups: List[Dict],
        w: int,
        h: int,
        fps: int,
        route_obstacle_arr: np.ndarray,
        reserved_boxes: List[Tuple[float, float, float, float]],
        pre_popup_frame: Optional[np.ndarray],
    ) -> float:
        """Builds the end-of-video recap (every waypoint's card at once,
        each with a leader line back to its own pin) if there's a
        stop_popup, fades the summary stat card in on top of it, and
        returns how long (seconds) the caller should hold on the result
        before moving on — the longer of the recap's own freeze_seconds
        and the summary card's configured hold, so the two read as one
        continuous ending beat rather than the recap being shown alone
        first and the card only appearing afterward in its own pause.
        Updates self.last_frame; does not write the hold itself, since
        the highlight (_render_ending_highlight) may still need to run
        first."""
        outro_hold_sec = 0.0

        if stop_popup:
            # Clean plate (see pre_popup_frame's own comment above) rather
            # than self.last_frame, which can still have a not-yet-finished
            # popup fade-out baked into it — and it already has every
            # numbered pin drawn on it, so the recap doesn't need to
            # redraw them. The end waypoint's own image_display
            # ("fullscreen"/"pip") is honored later, by
            # _render_ending_highlight AFTER the zoom-to-higher-tile
            # transition — never here.
            outro_frame = (
                pre_popup_frame.copy() if pre_popup_frame is not None
                else self.last_frame.copy()
            )
            self.last_frame = self._render_recap_frame(
                outro_frame, active_popups, w, h,
                route_obstacles=route_obstacle_arr,
                reserved_boxes=reserved_boxes,
            )
            outro_hold_sec = float(stop_popup["data"].get("freeze_seconds", 3.0))

        if summary_card is not None:
            fade_frames = max(1, int(self.config.get("summary_fade", 0.5) * fps))
            for i in range(fade_frames):
                video.write(
                    self.graphics.composite_card_on_frame(
                        self.last_frame, summary_card, alpha=(i + 1) / fade_frames
                    )
                )
            self.last_frame = self.graphics.composite_card_on_frame(
                self.last_frame, summary_card, alpha=1.0
            )
            outro_hold_sec = max(
                outro_hold_sec, float(self.config.get("summary_hold", 4.0))
            )

        return outro_hold_sec

    # How long to hold the higher-zoom map (with its marker + leader-lined
    # popup) before handing off to the fullscreen photo transition — the
    # "switch to higher map, then wait a bit" beat.
    _ENDING_HIGHLIGHT_WAIT_SECONDS = 1.5

    def _render_ending_highlight(
        self,
        video: VideoExporter,
        w: int,
        h: int,
        fps: int,
        stop_popup: Dict,
        start_popup: Optional[Dict] = None,
    ) -> bool:
        """End-of-video highlight: cut+fade from the recap into a freshly
        fetched, genuinely higher-zoom map centered on the trip's START
        point — with its own marker and a leader-lined popup, featuring
        the start waypoint's own photo — then, after a short hold, hand
        off to a fullscreen photo transition (if that waypoint's
        image_display is "fullscreen") or just hold on the pip card. A
        "callback to where the journey began" reveal to close the video,
        rather than repeating the end waypoint's own photo (already shown
        in the recap). Falls back to the end waypoint/point if there's no
        start one available.

        Returns True if the fullscreen photo transition played and the
        caller should treat this as the video's hard ending (write nothing
        further) — the fullscreen photo, once reached, is meant to be the
        last thing the video shows, not fade back down to the map for a
        trailing pause. Returns False otherwise (pip hold, or this highlight
        didn't run at all — no point to zoom to, or the image fetch
        failed — never worth losing an otherwise-finished render over), in
        which case the caller's normal trailing pause still applies."""
        job_config = self._get_job_config() or {}
        is_start = bool(job_config.get("start_point"))
        zoom_point = job_config.get("start_point") or job_config.get("end_point") or {}
        lat, lng = zoom_point.get("lat"), zoom_point.get("lng")
        if lat is None or lng is None:
            return False

        fetched = self._fetch_highlight_image(lat, lng, (w, h))
        if not fetched:
            return False
        highlight_path, highlight_extent = fetched
        highlight_bg = self.graphics.read_image_safe(highlight_path)
        if highlight_bg is None:
            return False
        if highlight_bg.shape[:2] != (h, w):
            highlight_bg = cv2.resize(highlight_bg, (w, h))

        px, py = RouteGeometryProcessor.project_latlon_to_pixel(
            lat, lng, highlight_extent, w, h
        )
        px, py = int(px), int(py)
        self.graphics.draw_marker(
            highlight_bg, px, py,
            number="S" if is_start else "E",
            color=self._START_PIN_COLOR if is_start else self._END_PIN_COLOR,
        )

        featured_popup = start_popup or stop_popup
        highlight_popup = featured_popup.copy()
        highlight_popup["data"] = featured_popup["data"].copy()
        highlight_popup["x"], highlight_popup["y"] = px, py
        highlight_popup["hud_corner"] = None  # forces the leader-lined "beside" card style
        highlight_popup["draw_leader_line"] = True
        # Same short-leader-line placement flow-through popups use
        # elsewhere (starts ~55px from the pin, spiraling out only if that
        # spot's taken) — without this, render_popup_box's own fallback
        # placement (meant for corner-avoidance, not a tight leader line)
        # can land the card far across the frame.
        self._layout_beside_popups([{"popup": highlight_popup, "frames_left": 1}], w, h)
        highlight_frame = self.graphics.render_popup_box(highlight_bg, highlight_popup)

        self._cut_fade_transition(video, self.last_frame, highlight_frame, fps)
        for _ in range(int(self._ENDING_HIGHLIGHT_WAIT_SECONDS * fps)):
            video.write(highlight_frame)
        self.last_frame = highlight_frame

        if (
            self.enable_fullscreen_popups
            and highlight_popup["data"].get("image_display") == "fullscreen"
        ):
            scale_sec = self.transition_cfg["scale_seconds"]
            hold_sec = self.transition_cfg["min_hold_seconds"]
            t_frames = self.graphics.generate_fullscreen_popup_transition(
                base_frame=highlight_frame,
                popup_info=highlight_popup,
                fps=fps,
                duration_sec=scale_sec,
                hold_sec=hold_sec,
                fade_out_sec=self.transition_cfg["fade_out_seconds"],
            )
            if t_frames:
                # Drop the trailing fade-BACK-to-the-map portion — this
                # fullscreen photo is meant to be the video's actual last
                # frame, not a cutaway that returns to the map afterward.
                keep = max(1, int(scale_sec * fps)) + max(1, int(hold_sec * fps))
                t_frames = t_frames[:keep]
                for tf in t_frames:
                    video.write(tf)

                # Blur out rather than hard-cutting on the photo — a bare
                # cut here would jump straight into whatever plays next;
                # softening out of focus first reads smoothly even when
                # the next clip opens on this exact same picture.
                self.last_frame = self._blur_out(video, t_frames[-1], fps)
                return True
        else:
            highlight_hold_sec = float(highlight_popup["data"].get("freeze_seconds", 3.0))
            for _ in range(int(highlight_hold_sec * fps)):
                video.write(highlight_frame)
        return False

    @staticmethod
    def _build_mode_breakpoints(points: List, point_modes: List[str]) -> List[Tuple[float, str]]:
        """Cumulative-distance fractions (0..1 along the route) at which the
        travel mode changes, so the animated trail/icon can react to
        routeMode transitions (e.g. walking -> ferry)."""
        if not points or not point_modes or len(points) != len(point_modes):
            return []

        cum = [0.0]
        for i in range(1, len(points)):
            cum.append(
                cum[-1]
                + math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1])
            )
        total = cum[-1] or 1.0

        breakpoints = [(0.0, point_modes[0])]
        for i in range(1, len(points)):
            if point_modes[i] != breakpoints[-1][1]:
                breakpoints.append((cum[i] / total, point_modes[i]))
        return breakpoints

    @staticmethod
    def _mode_at_fraction(breakpoints: List[Tuple[float, str]], frac: float) -> str:
        if not breakpoints:
            return "walking"
        mode = breakpoints[0][1]
        for bp_frac, bp_mode in breakpoints:
            if frac >= bp_frac:
                mode = bp_mode
            else:
                break
        return mode

    def render_overview(
        self,
        bg_path: str,
        points: List,
        labels: List,
        popups: List,
        fps: int,
        summary: Optional[Dict] = None,
        point_modes: Optional[List[str]] = None,
    ) -> str:
        is_video = False

        if is_video:
            cap = cv2.VideoCapture(str(bg_path))
            ret, current_bg = cap.read()
            if not ret:
                raise FileNotFoundError(f"Cannot read video frames from: {bg_path}")
        else:
            current_bg = self.graphics.read_image_safe(str(bg_path))
            if current_bg is None:
                raise FileNotFoundError(f"Cannot read background image: {bg_path}")
            cap = None

        h, w = current_bg.shape[:2]
        if h % 2 != 0 or w % 2 != 0:
            h, w = h - (h % 2), w - (w % 2)
            current_bg = cv2.resize(current_bg, (w, h))

        duration = self.config.get("duration", 30.0)
        num_frames = max(10, int(duration * fps))

        start_label, end_label = "開始", "終点"
        for p in [self.out_dir] + list(self.out_dir.parents):
            potential_path = p / "job_config.json"
            if potential_path.exists():
                try:
                    with open(potential_path, "r", encoding="utf-8") as f:
                        job_data = json.load(f)
                        start_label = job_data.get("start_point", {}).get(
                            "label", start_label
                        )
                        end_label = job_data.get("end_point", {}).get(
                            "label", end_label
                        )
                except Exception:
                    pass
                break

        cleaned_labels = []
        for i, lbl in enumerate(labels):
            if i == 0:
                cleaned_labels.append(start_label)
            elif i == len(points) - 1:
                cleaned_labels.append(end_label)
            else:
                cleaned_labels.append(
                    lbl.replace("Start: ", "")
                    .replace("Stop: ", "")
                    .replace("Start", "")
                    .replace("Stop", "")
                    .strip()
                    if lbl
                    else None
                )


        # Light dedup only — drop literal near-duplicate points so the spline
        # fit doesn't choke on zero-length segments. We deliberately do NOT
        # thin more aggressively than this by raw distance: a tight turn has
        # its points close together too, and stripping those is exactly what
        # let the smoothed path swing wide of sharp corners (cutting across
        # ground the real road never touches). get_smooth_path's own
        # Douglas-Peucker pass below reduces density based on actual
        # curvature (perpendicular deviation), which is the correct signal.
        filtered_points = [points[0]]
        for pt in points[1:]:
            if (
                math.hypot(
                    pt[0] - filtered_points[-1][0], pt[1] - filtered_points[-1][1]
                )
                > 0.5
            ):
                filtered_points.append(pt)
        # Ensure the final destination is always included
        if filtered_points[-1] != points[-1]:
            filtered_points.append(points[-1])

        mode_breakpoints = self._build_mode_breakpoints(points, point_modes) if point_modes else []

        if mode_breakpoints:
            # Faster real-world modes (ferry, car) should visually cover
            # ground quicker on screen than a walking leg of the same
            # length — sample the path densely first, then pick out
            # `num_frames` of those samples spaced by "speed-weighted"
            # distance rather than raw pixel distance. That compresses the
            # frame budget spent on fast legs and leaves more of it for
            # walking ones, instead of moving at one constant on-screen
            # speed regardless of travel mode.
            dense_n = max(num_frames * 4, 400)
            dense_arr = np.asarray(
                MapFetcher.get_smooth_path(
                    filtered_points, dense_n, ease=True, simplify_tolerance_px=2.2
                ),
                dtype=float,
            )
            seg_lens = np.hypot(np.diff(dense_arr[:, 0]), np.diff(dense_arr[:, 1]))
            cum_dense = np.concatenate([[0.0], np.cumsum(seg_lens)])
            total_dense = cum_dense[-1] or 1.0
            fracs = cum_dense / total_dense
            speeds = np.array(
                [
                    self._mode_speed_factor.get(
                        self._mode_at_fraction(mode_breakpoints, f), 1.0
                    )
                    for f in fracs
                ]
            )
            seg_speed = (speeds[:-1] + speeds[1:]) / 2.0
            virtual_seg = np.where(seg_speed > 0, seg_lens / seg_speed, seg_lens)
            virtual_cum = np.concatenate([[0.0], np.cumsum(virtual_seg)])
            total_virtual = virtual_cum[-1] or 1.0

            target = np.linspace(0.0, total_virtual, num_frames)
            idx = np.clip(np.searchsorted(virtual_cum, target), 1, len(virtual_cum) - 1)
            v0, v1 = virtual_cum[idx - 1], virtual_cum[idx]
            t = np.where(v1 > v0, (target - v0) / (v1 - v0), 0.0)
            smooth_path = dense_arr[idx - 1] + (dense_arr[idx] - dense_arr[idx - 1]) * t[:, None]

            smooth_arr = smooth_path
            final_seg_lens = np.hypot(
                np.diff(smooth_arr[:, 0]), np.diff(smooth_arr[:, 1])
            )
            total_smooth_dist = float(final_seg_lens.sum()) or 1.0
            cum_smooth_dist = np.concatenate([[0.0], np.cumsum(final_seg_lens)])
        else:
            smooth_path = MapFetcher.get_smooth_path(
                filtered_points, num_frames, ease=True, simplify_tolerance_px=2.2
            )
            cum_smooth_dist, total_smooth_dist = None, 1.0

        active_popups = [
            {
                "x": points[i][0],
                "y": points[i][1],
                "data": popups[i],
                "label": cleaned_labels[i],
                "index": i,
            }
            for i in range(len(points))
            if popups and popups[i] is not None
        ]
        # 1-based visit order, used to number each waypoint's pin and to
        # sort concurrently-visible popups in _layout_beside_popups.
        for order, ap in enumerate(active_popups, start=1):
            ap["order"] = order
        self._declutter_pins(active_popups)

        job_waypoints = self._get_job_waypoints()
        for i, popup in enumerate(active_popups):
            if i < len(job_waypoints):
                jw = job_waypoints[i]
                if (
                    "image_display" in jw
                    and popup["data"].get("image_display", "box") == "box"
                ):
                    popup["data"]["image_display"] = jw["image_display"]
                if "popup_video" in jw and not popup["data"].get("popup_video"):
                    popup["data"]["popup_video"] = jw["popup_video"]
                # Waypoints flow through by default (the traveler never
                # stops, all the way to the end) — set "freeze_frame": true
                # on a waypoint in job_config.json to opt IT back into the
                # old held-frame arrival pause. Flow-through popup cards
                # ride along beside the pin (see _layout_beside_popups)
                # rather than holding the frame.
                if "freeze_frame" in jw:
                    popup["data"]["freeze_frame"] = bool(jw["freeze_frame"])

        # Static footprint (the full route line + every pin) used to pick a
        # HUD corner that the popup card won't sit on top of. Computed once
        # from the whole route rather than the animated path-so-far, so a
        # given waypoint's card always lands in the same corner regardless
        # of when in the animation it triggers.
        route_avoid_points = list(points) + [
            (p["x"], p["y"]) for p in active_popups
        ]

        # Same footprint, as a decimated numpy array — lets
        # _layout_beside_popups check a candidate card position against the
        # route line itself (cheaply, vectorized) so a flow-through card
        # doesn't get planted right on top of the path it's next to.
        route_obstacle_arr = np.asarray(route_avoid_points, dtype=float)
        if len(route_obstacle_arr) > 400:
            step = max(1, len(route_obstacle_arr) // 400)
            route_obstacle_arr = route_obstacle_arr[::step]

        logger.info(f"Rendering Overview Map ({duration}s)")
        overview_path = str(self.out_dir / "01_overview.mp4")
        video = VideoExporter(overview_path, w, h, fps)
        baked_popups = []

        intro_frame = current_bg.copy()
        start_popup = next((p for p in active_popups if p["index"] == 0), None)
        stop_popup = next(
            (p for p in active_popups if p["index"] == len(points) - 1), None
        )

        # A flow-through popup's display duration defaults to a fixed
        # freeze_seconds regardless of how long that leg of the route
        # actually takes to animate — so on a short leg the NEXT waypoint's
        # popup could trigger while the previous one is still showing, and
        # on a long leg it could vanish long before the traveler arrives.
        # Instead, tie it to the leg itself: find each waypoint's own
        # expected frame (nearest point along the animated path) and set
        # its popup to last exactly from there until the next waypoint's
        # expected frame — "2 to 3" shows popup 2, and the moment 3 is
        # reached popup 2 hides and popup 3 takes over.
        smooth_arr_lookup = np.asarray(smooth_path, dtype=float)

        def _expected_frame(px: float, py: float) -> int:
            dists = np.hypot(smooth_arr_lookup[:, 0] - px, smooth_arr_lookup[:, 1] - py)
            return int(np.argmin(dists))

        triggerable = [
            ap for ap in active_popups
            if ap["index"] != 0 and (not stop_popup or ap["index"] != stop_popup["index"])
        ]
        triggerable.sort(key=lambda ap: _expected_frame(ap["x"], ap["y"]))
        stop_expected_frame = (
            _expected_frame(stop_popup["x"], stop_popup["y"]) if stop_popup else None
        )
        min_leg_frames = int(fps * 1.5)
        for i, ap in enumerate(triggerable):
            this_frame = _expected_frame(ap["x"], ap["y"])
            next_frame = (
                _expected_frame(triggerable[i + 1]["x"], triggerable[i + 1]["y"])
                if i + 1 < len(triggerable)
                else stop_expected_frame
            )
            if next_frame is not None:
                ap["leg_display_seconds"] = (
                    max(min_leg_frames, next_frame - this_frame) / fps
                )

        intro_freeze_sec = 3.0
        if start_popup and "freeze_seconds" in start_popup["data"]:
            intro_freeze_sec = float(start_popup["data"]["freeze_seconds"])

        if start_popup:
            temp_sp = start_popup.copy()
            temp_sp["data"] = start_popup["data"].copy()
            temp_sp["data"]["triggered"] = True
            temp_sp["hud_corner"], temp_sp["x"], temp_sp["y"] = (
                self.graphics.pick_hud_corner(w, h, route_avoid_points),
                start_popup["x"],
                start_popup["y"],
            )
            start_popup["data"]["triggered"] = True

            if not is_video:
                # Show every waypoint marker up front on the intro frame,
                # not just the start point, so the whole route's stops are
                # visible before the animation begins.
                for order, wp in enumerate(active_popups, start=1):
                    self._draw_pin(intro_frame, wp, order, len(points))

            # The intro always opens as a plain pip card, regardless of
            # this waypoint's own image_display setting — "fullscreen"
            # is only ever honored by the end-of-video zoom-tile highlight
            # (_render_ending_highlight), not here.
            intro_frame = self.graphics.render_popup_box(intro_frame, temp_sp)
            for _ in range(int(intro_freeze_sec * fps)):
                video.write(intro_frame)
            self.last_frame = intro_frame

        path_history = []
        mode_history = []
        prev_cx, prev_cy = None, None
        smoothed_angle = 0.0
        # path_history index where the most recently reached waypoint sits —
        # marks the boundary between "earlier, completed legs" (always kept
        # visible) and "the current leg" (the only part hidden while its
        # arrival popup is showing).
        last_leg_boundary = 0
        # The last frame's state right before baked-popup cards are
        # composited that iteration — i.e. pins and route, no popup card
        # overlay. Captured only on the loop's final iteration (see below)
        # rather than using self.last_frame, which can carry a still-fading
        # popup card baked in: without this, a card mid-fade-out exactly
        # when the animation ends gets baked into the recap's background at
        # partial opacity, and then _render_recap_frame draws that SAME
        # waypoint's card again on top at full opacity — a blurry/ghosted
        # double-image for whichever popup happened to still be fading.
        pre_popup_frame = None

        for current_frame, p in enumerate(smooth_path):
            if is_video:
                ret, vid_frame = cap.read()
                if ret:
                    if vid_frame.shape[0] != h or vid_frame.shape[1] != w:
                        vid_frame = cv2.resize(vid_frame, (w, h))
                    current_bg = vid_frame

            frame = current_bg.copy()

            path_history.append((int(p[0]), int(p[1])))

            if cum_smooth_dist is not None:
                frac = cum_smooth_dist[current_frame] / total_smooth_dist
                current_mode = self._mode_at_fraction(mode_breakpoints, frac)
            else:
                current_mode = "walking"
            mode_history.append(current_mode)

            if not is_video:
                self.graphics.draw_path(frame, path_history, mode_history)

            # Detected here, BEFORE the pin/popup drawing below, so a
            # waypoint's pin and its popup card appear on the very same
            # frame it's reached — detecting it after drawing (as this used
            # to) left the just-arrived pin (and, for a frozen waypoint,
            # its popup entirely) invisible for the whole held/flowing
            # display, only catching up once the NEXT frame drew fresh.
            cx, cy = path_history[-1]
            px, py = path_history[-2] if len(path_history) > 1 else path_history[-1]

            triggered_popup = None
            for popup in active_popups:
                if popup["index"] == 0 or (
                    stop_popup and popup["index"] == stop_popup["index"]
                ):
                    continue
                if not popup["data"]["triggered"]:
                    if RouteGeometryProcessor.point_to_segment_distance(
                        popup["x"], popup["y"], px, py, cx, cy
                    ) < (
                        self.graphics.marker_radius
                        + self.trigger_radius_padding["overview"]
                    ):
                        popup["data"]["triggered"] = True
                        triggered_popup = popup
                        break

            # "Point to point" snapshot for hide_route_on_popup — every
            # earlier, already-completed leg stays drawn; only the CURRENT
            # leg (since the last waypoint reached) is left off, so arriving
            # at a stop doesn't erase the whole route travelled so far.
            # Built separately (rather than copying `frame` before the line
            # is drawn) because pins still need to render on top of the
            # route line for normal display below.
            frame_no_route = None
            if not is_video and self.hide_route_on_popup:
                frame_no_route = current_bg.copy()
                self.graphics.draw_path(
                    frame_no_route,
                    path_history[: last_leg_boundary + 1],
                    mode_history[: last_leg_boundary + 1],
                )
                for order, wp in enumerate(active_popups, start=1):
                    if wp["data"].get("triggered") or wp["index"] == 0:
                        self._draw_pin(frame_no_route, wp, order, len(points))

            if not is_video:
                # Every waypoint is shown once up front on the intro frame
                # (a preview of the whole route), but from here on a pin
                # only reappears once the traveler actually reaches it —
                # not-yet-visited stops stay hidden instead of cluttering
                # the map with numbers for places not reached yet.
                for order, wp in enumerate(active_popups, start=1):
                    if wp["data"].get("triggered") or wp["index"] == 0:
                        self._draw_pin(frame, wp, order, len(points))

            # Only the very last iteration's pre-popup frame is ever read
            # (see the recap's use of it, below) — smooth_path's length is
            # fixed and known up front (no early-exit branch in this loop),
            # so skip the per-frame copy everywhere else instead of paying
            # for a full-resolution frame copy on every single frame of
            # the animation.
            if stop_popup and current_frame == len(smooth_path) - 1:
                pre_popup_frame = frame.copy()
            frame, baked_popups = self._composite_baked_popups(
                frame, baked_popups, w, h, route_obstacle_arr
            )

            if frame_no_route is None:
                frame_no_route = frame

            if triggered_popup:
                # Everything up to (and including) this point becomes part
                # of an "earlier leg" for the NEXT popup's hide effect.
                last_leg_boundary = len(path_history) - 1

                # Pick a corner clear of the route/pins once, and keep it on
                # the popup itself so the lingering baked-popup HUD (below)
                # doesn't jump to a different corner mid-display.
                triggered_popup["hud_corner"] = self.graphics.pick_hud_corner(
                    w, h, route_avoid_points
                )

                # Shared base for BOTH the arrival-hold pause and the popup
                # itself — decluttered to only already-arrived pins when
                # requested, and with the per-leg stat card baked in up
                # front so the pause and the popup read as one continuous
                # "you arrived" beat instead of the card popping in only
                # once the popup shows.
                if self.hide_upcoming_pins_on_popup:
                    popup_base_frame = self._build_freeze_frame(
                        current_bg, path_history, mode_history,
                        last_leg_boundary, active_popups, len(points),
                    )
                else:
                    popup_base_frame = frame_no_route if self.hide_route_on_popup else frame

                # Fullscreen popups are an inherent full-screen takeover —
                # they always freeze regardless of the waypoint's
                # freeze_frame setting, since "flow through" wouldn't mean
                # anything for a shot that covers the whole frame. Every
                # other waypoint now flows through by default — the
                # traveler continues moving past each stop all the way to
                # the end; a waypoint only freezes if it opts in with
                # "freeze_frame": true in job_config.json.
                is_fullscreen = (
                    self.enable_fullscreen_popups
                    and triggered_popup["data"].get("image_display") == "fullscreen"
                )
                freeze_frame_on = (
                    triggered_popup["data"].get("freeze_frame", False) or is_fullscreen
                )

                if not freeze_frame_on:
                    # Flow-through: the traveler keeps moving — no held
                    # frame, no arrival pause. The popup card rides along as
                    # a HUD overlay beside the waypoint's own pin (with a
                    # leader line back to it, drawn in render_popup_box) for
                    # roughly the duration of this leg (see
                    # leg_display_seconds above) rather than always the
                    # fixed freeze_seconds, so it hands off to the next
                    # popup right around when that waypoint is reached
                    # instead of lingering past it or vanishing early.
                    display_seconds = float(
                        triggered_popup.get("leg_display_seconds")
                        or triggered_popup["data"].get("freeze_seconds", 4.0)
                    )
                    new_bp = self._make_baked_popup(triggered_popup, display_seconds, fps)
                    baked_popups.append(new_bp)
                    frame = popup_base_frame
                    if not is_video:
                        smoothed_angle = self._smoothed_heading(
                            smoothed_angle, cx, cy, prev_cx, prev_cy
                        )
                        self.graphics.draw_transport_icon(
                            frame, cx, cy, current_frame, smoothed_angle, mode=current_mode
                        )
                        # Render its card immediately too — otherwise the
                        # pin (already on this frame above) would show a
                        # full frame before its popup catches up on the
                        # next one. Faded in from the start (see
                        # _popup_fade_alpha), same as every later frame
                        # _composite_baked_popups draws it for.
                        self._layout_beside_popups(
                            [new_bp], w, h, route_obstacles=route_obstacle_arr
                        )
                        hud_new = triggered_popup.copy()
                        hud_new["hud_corner"] = None
                        hud_new["draw_leader_line"] = True
                        frame = self.graphics.render_popup_box(
                            frame, hud_new, alpha=self._popup_fade_alpha(new_bp)
                        )
                    self.last_frame = frame
                    video.write(frame)
                    prev_cx, prev_cy = cx, cy
                    continue

                # Hold on the traveler having just reached the pin for a
                # beat before the fullscreen/pip transition kicks in — but
                # the popup photo itself is already visible (as its small
                # pip card) through this hold, so the pause reads as "the
                # popup has arrived and is settling in" rather than a gap
                # with nothing shown yet.
                if not is_video and self.post_arrival_hold_seconds > 0:
                    pause_frame = popup_base_frame.copy()
                    smoothed_angle = self._smoothed_heading(
                        smoothed_angle, cx, cy, prev_cx, prev_cy
                    )
                    self.graphics.draw_transport_icon(
                        pause_frame, cx, cy, current_frame, smoothed_angle, mode=current_mode
                    )
                    pause_frame = self.graphics.render_popup_box(pause_frame, triggered_popup)
                    for _ in range(int(self.post_arrival_hold_seconds * fps)):
                        video.write(pause_frame)

                if is_fullscreen:
                    self.last_frame, _ = self.graphics.play_fullscreen_popup_sequence(
                        video=video,
                        base_frame=popup_base_frame,
                        popup_info=triggered_popup,
                        fps=fps,
                        transition_cfg=self.transition_cfg,
                        exit_frame=frame,
                    )
                else:
                    display_seconds = float(
                        triggered_popup["data"].get("freeze_seconds", 4.0)
                    )
                    # Kept as its own baked_popups entry so it lingers as a
                    # HUD overlay (with its own fade in/out) once the
                    # camera resumes moving — see _composite_baked_popups.
                    lingering_bp = self._make_baked_popup(
                        triggered_popup, display_seconds, fps
                    )
                    baked_popups.append(lingering_bp)
                    hud_triggered = triggered_popup.copy()

                    # The frame itself is frozen (unchanging) for this
                    # whole hold, but the card still fades in rather than
                    # snapping on at full opacity — re-rendered once per
                    # frame (instead of one frame written repeatedly) so
                    # its alpha can ramp up. Reuses the same fade_frames as
                    # the lingering entry above for a consistent ramp.
                    total_hold_frames = lingering_bp["total_frames"]
                    fade_in_frames = lingering_bp["fade_frames"]
                    temp_frame = popup_base_frame
                    for i in range(total_hold_frames):
                        alpha = min(1.0, (i + 1) / fade_in_frames)
                        temp_frame = self.graphics.render_popup_box(
                            popup_base_frame, hud_triggered, alpha=alpha
                        )
                        video.write(temp_frame)

                    self.last_frame = temp_frame

            else:
                if not is_video:
                    smoothed_angle = self._smoothed_heading(
                        smoothed_angle, cx, cy, prev_cx, prev_cy
                    )
                    self.graphics.draw_transport_icon(
                        frame, cx, cy, current_frame, smoothed_angle, mode=current_mode
                    )

                self.last_frame = frame
                video.write(frame)

            prev_cx, prev_cy = cx, cy

        # Built once, up front, so its exact footprint can be reserved
        # (see reserved_boxes below) before the recap frame lays out its
        # popup cards — otherwise a card could land right where this gets
        # composited over the video in the bottom-right corner, later.
        summary_card = None
        if summary:
            summary_card = self.graphics.create_summary_card(
                distance_km=summary.get("total_distance_km", 0.0),
                duration_seconds=summary.get("total_duration_seconds", 0.0),
                mode_breakdown=summary.get("mode_breakdown"),
                mode_duration=summary.get("mode_duration"),
            )
        summary_card_margin = 40
        reserved_boxes = (
            [
                (
                    w - summary_card.shape[1] - summary_card_margin,
                    h - summary_card.shape[0] - summary_card_margin,
                    float(w - summary_card_margin),
                    float(h - summary_card_margin),
                )
            ]
            if summary_card is not None
            else []
        )

        outro_hold_sec = self._render_recap_and_summary(
            video, stop_popup, summary_card, active_popups, w, h, fps,
            route_obstacle_arr, reserved_boxes, pre_popup_frame,
        )
        for _ in range(int(outro_hold_sec * fps)):
            video.write(self.last_frame)

        hard_ended = False
        if stop_popup and self.config.get("enable_ending_highlight", True):
            hard_ended = self._render_ending_highlight(
                video, w, h, fps, stop_popup, start_popup
            )

        for p in popups:
            if p:
                p["triggered"] = False

        # The fullscreen ending highlight, when it plays, IS the video's
        # last frame — no trailing pause on the map afterward.
        if not hard_ended:
            for _ in range(int(self.config.get("pause", 2.0) * fps)):
                video.write(self.last_frame)

        if cap:
            cap.release()
        return video.release(overview_path)

    def render_waypoints(self, res_sequence: List[Dict], fps: int) -> List[str]:
        output_paths = []
        show_segment_summary = self.config.get("show_segment_summary", True)
        fade_sec = self.config.get("summary_fade", 0.5)
        clip_hold_sec = self.config.get("clip_summary_hold", 2.0)
        job_waypoints = self._get_job_waypoints()

        for i, res_data in enumerate(res_sequence):
            bg_path = res_data["img_path"]

            is_video = (
                str(bg_path).lower().endswith((".mp4", ".webm", ".avi", ".mov", ".mkv"))
            )
            if is_video:
                cap = cv2.VideoCapture(str(bg_path))
                ret, current_bg = cap.read()
                if not ret:
                    continue
            else:
                current_bg = self.graphics.read_image_safe(str(bg_path))
                if current_bg is None:
                    continue
                cap = None

            h, w = current_bg.shape[:2]
            if h % 2 != 0 or w % 2 != 0:
                h, w = h - (h % 2), w - (w % 2)
                current_bg = cv2.resize(current_bg, (w, h))

            res_points = res_data["points"]
            res_labels = res_data["labels"]
            res_popups = res_data.get("popups", [None] * len(res_points))
            res_mode = str(res_data.get("mode", "walking")).lower()

            total_duration = res_data.get(
                "segment_duration", self.config.get("res_duration", 12.0)
            )
            travel_duration = res_data.get("travel_duration", total_duration)
            pauses = res_data.get("pauses", [])

            total_frames = max(10, int(total_duration * fps))
            is_paused_per_frame = [
                (
                    any(p["start"] <= (f / fps) <= p["end"] for p in pauses)
                    if pauses
                    else False
                )
                for f in range(total_frames)
            ]

            total_pause_seconds = sum(p["duration"] for p in pauses) if pauses else 0.0

            # --- FIX 2: Apply the same pixel filter to the residential maps ---
            filtered_res = [res_points[0]]
            for pt in res_points[1:]:
                if (
                    math.hypot(pt[0] - filtered_res[-1][0], pt[1] - filtered_res[-1][1])
                    > 3.0
                ):
                    filtered_res.append(pt)
            if filtered_res[-1] != res_points[-1]:
                filtered_res.append(res_points[-1])

            actual_travel_seconds = max(1.0, travel_duration - total_pause_seconds)

            res_smooth_path = MapFetcher.get_smooth_path(
                filtered_res, max(2, int(actual_travel_seconds * fps)), ease=True
            )

            res_named = [
                (int(res_points[j][0]), int(res_points[j][1]), res_labels[j])
                for j in range(len(res_points))
                if RouteGeometryProcessor.is_real_label(res_labels[j])
            ]
            active_res_popups = [
                {
                    "x": res_points[j][0],
                    "y": res_points[j][1],
                    "data": res_popups[j],
                    "label": res_labels[j],
                }
                for j in range(len(res_points))
                if res_popups[j] is not None
            ]

            for popup in active_res_popups:
                lbl = str(popup.get("label", ""))
                for jw in job_waypoints:
                    jw_lbl = str(jw.get("label", ""))
                    if jw_lbl and (jw_lbl in lbl or lbl in jw_lbl):
                        if (
                            "image_display" in jw
                            and popup["data"].get("image_display", "box") == "box"
                        ):
                            popup["data"]["image_display"] = jw["image_display"]
                        if "popup_video" in jw and not popup["data"].get("popup_video"):
                            popup["data"]["popup_video"] = jw["popup_video"]
                        break

            res_landmark_sprites = {
                lbl: self.graphics.prebake_landmark_sprite(lbl)
                for _, _, lbl in res_named
            }
            safe_suffix = (
                "".join(
                    c
                    for c in str(res_named[-1][2] if res_named else f"leg{i+1}")
                    if c.isalnum() or c in (" ", "_", "-")
                )
                .strip()
                .replace(" ", "_")
                or f"leg{i+1}"
            )
            chunk_filename = f"02_waypoint_{i + 1:02d}_{safe_suffix}.mp4"

            video = VideoExporter(str(self.out_dir / chunk_filename), w, h, fps)
            path_idx = 0
            prev_cx, prev_cy = None, None
            smoothed_angle = 0.0

            for current_frame in range(total_frames):
                is_paused = is_paused_per_frame[current_frame]
                just_arrived = False

                if not is_paused and path_idx < len(res_smooth_path) - 1:
                    path_idx += 1
                    if path_idx == len(res_smooth_path) - 1:
                        just_arrived = True

                if is_video and not is_paused:
                    ret, vid_frame = cap.read()
                    if ret:
                        if vid_frame.shape[0] != h or vid_frame.shape[1] != w:
                            vid_frame = cv2.resize(vid_frame, (w, h))
                        current_bg = vid_frame

                p = res_smooth_path[path_idx]
                frame = current_bg.copy()
                current_chunk_px = res_smooth_path[: path_idx + 1]

                if len(current_chunk_px) > 1:
                    cx, cy = int(current_chunk_px[-1][0]), int(current_chunk_px[-1][1])
                else:
                    cx, cy = int(p[0]), int(p[1])

                if not is_video:
                    if len(current_chunk_px) > 1:
                        cv2.polylines(
                            frame,
                            [current_chunk_px.astype(np.int32)],
                            False,
                            self.graphics.line_color,
                            self.graphics.line_thickness,
                            cv2.LINE_AA,
                        )

                    for x, y, lbl in res_named:
                        sprite, anchor = res_landmark_sprites[lbl]
                        self.graphics.blit_sprite(frame, sprite, anchor, x, y)

                    smoothed_angle = self._smoothed_heading(
                        smoothed_angle, cx, cy, prev_cx, prev_cy
                    )

                    self.graphics.draw_transport_icon(
                        frame, cx, cy, current_frame, smoothed_angle, mode=res_mode
                    )

                for popup in active_res_popups:
                    if popup["data"]["triggered"]:
                        continue
                    near_segment = (
                        prev_cx is not None
                        and prev_cy is not None
                        and RouteGeometryProcessor.point_to_segment_distance(
                            popup["x"], popup["y"], prev_cx, prev_cy, cx, cy
                        )
                        < (
                            self.graphics.marker_radius
                            + self.trigger_radius_padding["waypoint"]
                        )
                    )
                    if near_segment or just_arrived:
                        popup["data"]["triggered"] = True
                        if popup["data"].get("image_display") == "fullscreen":
                            self.graphics.play_fullscreen_popup_sequence(
                                video=video,
                                base_frame=frame,
                                popup_info=popup,
                                fps=fps,
                                transition_cfg=self.transition_cfg,
                                exit_frame=frame,
                            )
                        else:
                            total_f = int(popup["data"]["freeze_seconds"] * fps)
                            fade_f = min(int(0.5 * fps), total_f // 3)
                            cinematic_frame = self.graphics.render_cinematic_pause(
                                frame, popup
                            )
                            self.graphics.write_fade_clip(
                                video, frame, cinematic_frame, total_f, fade_f
                            )

                video.write(frame)
                self.last_frame = frame
                prev_cx, prev_cy = cx, cy

            for _ in range(int(self.post_arrival_hold_seconds * fps)):
                video.write(self.last_frame)

            if show_segment_summary:
                seg_card = self.graphics.create_summary_card(
                    distance_km=res_data.get("distance_km", 0.0),
                    duration_seconds=res_data.get(
                        "real_duration_seconds", total_duration
                    ),
                    card_size=(480, 110),
                )
                fade_frames = max(1, int(fade_sec * fps))
                for f in range(fade_frames):
                    video.write(
                        self.graphics.composite_card_on_frame(
                            self.last_frame, seg_card, alpha=(f + 1) / fade_frames
                        )
                    )
                held_frame = self.graphics.composite_card_on_frame(
                    self.last_frame, seg_card, alpha=1.0
                )
                for _ in range(max(0, int(clip_hold_sec * fps) - fade_frames)):
                    video.write(held_frame)

            output_paths.append(video.release(str(self.out_dir / chunk_filename)))
            if cap:
                cap.release()

        return output_paths