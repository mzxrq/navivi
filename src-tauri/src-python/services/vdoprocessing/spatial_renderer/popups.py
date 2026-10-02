"""Flow-through/beside popup card layout, baked-popup lifecycle, recap frame,
and the end-of-video highlight's higher-zoom image fetch."""

import math
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.spatial import ConvexHull, QhullError

from services import tuning

from .base import logger

# Archimedean-spiral search step sizes used by _layout_beside_popups's
# free_spot — how far the radius grows and the angle advances per
# iteration while probing outward for a free card spot.
_SPIRAL_RADIUS_STEP_PX = 5.0
_SPIRAL_ANGLE_STEP_RAD = 0.45


def _anchor_point(
    pin_x: float, pin_y: float, bx: float, by: float, card_w: float, card_h: float
) -> Tuple[float, float]:
    """Where a leader line actually meets its card: the pin clamped onto
    the card box's nearest edge — matches render_popup_box's own anchor
    exactly (popup_box.py's anchor_x/anchor_y). Shared (module-level, not
    a method) so both layout functions below check crossings against the
    same line the frame will actually draw, not an approximation (e.g. the
    box center) that could clear a crossing check the real drawn line
    doesn't."""
    return (
        min(max(pin_x, bx), bx + card_w),
        min(max(pin_y, by), by + card_h),
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


def _leader_crosses_placed(
    polyline: List[Tuple[float, float]],
    placed: List[Tuple[float, float, float, float]],
    placed_lines: List[List[Tuple[float, float]]],
) -> bool:
    """Checks every segment of a candidate leader-line polyline (pin -> its
    own card's real anchor point) against every OTHER already-placed
    card's box edges AND every other already-placed popup's own leader-
    line polyline — a candidate whose line would visually cut across a
    different card, or simply cross another line out in the open, should
    be deprioritized by the caller even when the candidate box itself
    doesn't overlap anything. Takes a polyline (not just a single
    straight segment) so a caller with a multi-point leader line (pin ->
    an intermediate routing point -> card) can still be checked the same
    way as a plain 2-point pin -> card line."""
    for (ax0, ay0), (ax1, ay1) in zip(polyline[:-1], polyline[1:]):
        for (rx0, ry0, rx1, ry1) in placed:
            edges = (
                (rx0, ry0, rx1, ry0), (rx1, ry0, rx1, ry1),
                (rx1, ry1, rx0, ry1), (rx0, ry1, rx0, ry0),
            )
            if any(
                _segments_intersect(ax0, ay0, ax1, ay1, ex0, ey0, ex1, ey1)
                for ex0, ey0, ex1, ey1 in edges
            ):
                return True
        for placed_poly in placed_lines:
            for (bx0, by0), (bx1, by1) in zip(placed_poly[:-1], placed_poly[1:]):
                if _segments_intersect(ax0, ay0, ax1, ay1, bx0, by0, bx1, by1):
                    return True
    return False


def _cluster_points_by_distance(
    points: List[Tuple[float, float]], link_dist: float
) -> List[List[int]]:
    """Groups point INDICES into clusters via union-find: two points join
    the same cluster if within `link_dist` of each other, directly or
    transitively through a chain of other points — so a tight run of
    waypoints (e.g. several attractions on the same small island) forms
    one cluster even though the two farthest-apart members of it might
    exceed link_dist on their own. Used to detect the "many pins packed
    into a small area" case where individual straight leader lines
    tangle no matter how carefully each one is placed (see
    _padded_boundary's own docstring for the fix)."""
    n = len(points)
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if math.hypot(points[i][0] - points[j][0], points[i][1] - points[j][1]) <= link_dist:
                union(i, j)

    groups: Dict[int, List[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _padded_boundary(points: List[Tuple[float, float]], padding: float) -> List[Tuple[float, float]]:
    """A closed polygon comfortably wrapping every point in `points` plus
    `padding` px of clearance on every side — the convex hull of the
    cluster, pushed outward from its own centroid. Falls back to a
    padded circle around the centroid when the points are collinear (a
    degenerate hull ConvexHull can't wrap) or when there are fewer than
    3 points to hull at all.

    Every line in a tight cluster first travels to the NEAREST point on
    this shared outer boundary (see _nearest_point_on_polygon), then out
    to its card from there, instead of anchoring straight at the pin —
    measured (on a real dense cluster) to reduce total leader-line
    crossings across the whole map from 6 to 4 versus anchoring every
    line straight at its own pin."""
    pts = np.asarray(points, dtype=float)
    centroid = pts.mean(axis=0)
    if len(pts) >= 3:
        try:
            hull = ConvexHull(pts)
            hull_pts = pts[hull.vertices]
            if len(hull_pts) >= 3:
                polygon = []
                for p in hull_pts:
                    direction = p - centroid
                    norm = float(np.hypot(direction[0], direction[1]))
                    pushed = p if norm < 1e-6 else p + (direction / norm) * padding
                    polygon.append((float(pushed[0]), float(pushed[1])))
                return polygon
        except QhullError:
            pass
    max_r = max(float(np.hypot(p[0] - centroid[0], p[1] - centroid[1])) for p in pts) + padding
    max_r = max(max_r, padding)
    n_samples = 16
    return [
        (
            float(centroid[0] + max_r * math.cos(2 * math.pi * i / n_samples)),
            float(centroid[1] + max_r * math.sin(2 * math.pi * i / n_samples)),
        )
        for i in range(n_samples)
    ]


def _closest_point_on_segment(
    ax: float, ay: float, bx: float, by: float, px: float, py: float
) -> Tuple[float, float]:
    dx, dy = bx - ax, by - ay
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-9:
        return (ax, ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len_sq))
    return (ax + t * dx, ay + t * dy)


def _nearest_point_on_polygon(
    polygon: List[Tuple[float, float]], target: Tuple[float, float]
) -> Tuple[float, float]:
    tx, ty = target
    best_pt, best_dist = polygon[0], float("inf")
    n = len(polygon)
    for i in range(n):
        ax, ay = polygon[i]
        bx, by = polygon[(i + 1) % n]
        pt = _closest_point_on_segment(ax, ay, bx, by, tx, ty)
        d = math.hypot(pt[0] - tx, pt[1] - ty)
        if d < best_dist:
            best_dist, best_pt = d, pt
    return best_pt


class _PopupMixin:
    @staticmethod
    def _attach_stopby_groups(active_popups: List[Dict]) -> None:
        """Works out which stop-by waypoints are shown as part of which
        stop, stamping "stopby_group" on each host and "stopby_host" on
        each stop-by it owns.

        A whole run of consecutive stop-bys — connected or not
        (job_config's `connectToRoute`, reaching us as
        data["connect_to_route"] — see render_step.py) — plays as ONE
        continuous stop: the video stays frozen, showing each stop-by's
        own card in turn (see _play_stopby_batch), all the way through
        the run and not resuming the traveling animation again until it
        reaches the next REAL (non-stop-by) waypoint.

        WHERE that stop freezes depends on whether the run has a
        connected member:

        * If the run's FIRST stop-by is connected, the route genuinely
          runs through it — so the traveling animation continues up to
          THAT point (not stopping short at the real waypoint before it),
          and it becomes the host every other stop-by in the run (later
          connected ones included) attaches to. Several connected stops
          in a row don't each get their own separate freeze/resume —
          only the first one triggers the stop; the rest just join its
          group like any other member.
        * Otherwise (the run starts with an unconnected stop-by), there's
          no real path point to travel to yet, so it's shown during the
          previous NORMAL waypoint's stop instead, same as every other
          member behind it.

        This also covers the route's own start pin (index 0): a stop-by
        right at the beginning of the trip is played as its own little
        stop before the traveler sets off, same as any other waypoint's
        batch — see _animate_overview_frames' own dedicated call for the
        start pin's group, made once up front rather than through the
        main per-frame trigger loop (index 0 never "arrives" there the
        way every other waypoint does).

        A stop-by with no preceding real waypoint at all (nothing to host
        it) is left ungrouped, and keeps the old pop-on-proximity
        behaviour — never shown at all would be worse."""
        host = None
        # True only for the very next stop-by right after a real waypoint
        # (or at the very start of active_popups) — i.e. "is `ap` the
        # FIRST stop-by of a fresh run". Only that first one ever gets a
        # chance to promote itself to host; every later stop-by in the
        # same run (connected or not) just joins whatever host the run
        # already settled on. Cleared the instant any stop-by is seen,
        # and set again only by the next real waypoint.
        first_stopby_of_run = False
        for ap in active_popups:
            data = ap.get("data") or {}
            if data.get("is_skipped"):
                # Skipped in video export: pops up on its own as the walker
                # passes (see _is_loose_stopby), never part of a batch.
                continue
            if not data.get("is_stopby"):
                host = ap
                ap["stopby_group"] = []
                first_stopby_of_run = True
                continue
            if host is not None and first_stopby_of_run and data.get("connect_to_route"):
                # The first stop-by since the last real waypoint, and it's
                # connected: the traveling animation genuinely runs all
                # the way here, so it becomes the new host for the rest
                # of the run instead of everything sitting back at the
                # real waypoint before it.
                host = ap
                ap["stopby_group"] = []
                first_stopby_of_run = False
                continue
            first_stopby_of_run = False
            if host is not None:
                host.setdefault("stopby_group", []).append(ap)
                ap["stopby_host"] = host

    @staticmethod
    def _is_loose_stopby(popup: Dict) -> bool:
        """True for a stop-by that still pops on its own, on proximity,
        exempt from the sequential-arrival gate — i.e. an UNCONNECTED one
        with no host waypoint to be batched at (see _attach_stopby_groups,
        which only leaves a stop-by hostless when nothing precedes it).

        A connected stop-by is deliberately NOT "loose": the route runs
        through it, so it arrives in sequence like any ordinary stop. This
        is the single place that distinction is made, so the trigger loop
        can't apply one half of it and miss the other."""
        data = popup.get("data") or {}
        return (
            bool(data.get("is_stopby"))
            and not data.get("connect_to_route")
            and popup.get("stopby_host") is None
        )

    def _nearest_lattice_slot(
        self,
        pin_x: float,
        pin_y: float,
        w: int,
        h: int,
        card_w: int,
        card_h: int,
        placed: List[Tuple[float, float, float, float]],
        reserved_boxes: Optional[List[Tuple[float, float, float, float]]] = None,
        route_obstacles: Optional[np.ndarray] = None,
    ) -> Optional[Tuple[float, float]]:
        """The free lattice slot closest to (pin_x, pin_y), or None if the
        lattice is full. Last-resort placement for a card whose own
        near-pin search came up empty (see _layout_beside_popups) — the
        same disjoint grid the recap lays every card out on, so whatever
        it returns cannot overlap another card, only sit further from its
        own pin than the near-pin search would have liked.

        `route_obstacles` is honoured here as well as by the near-pin
        search: without it the fallback would happily plant a card on the
        route line or on a pin, which is exactly what the near-pin search
        had just refused to do — the card would end up further from its pin
        AND covering the map.

        The lattice for a given frame/card size is the same every frame, so
        it's built once and cached: this is called per un-placed card per
        frame, and rebuilding it each time would be pure waste."""
        # reserved_boxes is part of the key, not just the frame/card size:
        # the slots it excludes differ per caller (the summary card's own
        # corner is reserved for the recap but not during the animation), so
        # keying without it would hand back a lattice that still contains
        # slots this caller had asked to keep clear.
        obstacle_key = (
            None if route_obstacles is None or not len(route_obstacles)
            else (route_obstacles.shape, hash(route_obstacles.tobytes()))
        )
        key = (
            w, h, card_w, card_h,
            tuple(map(tuple, reserved_boxes or ())),
            obstacle_key,
        )
        cache = getattr(self, "_lattice_slot_cache", None)
        if cache is None:
            cache = self._lattice_slot_cache = {}
        if key not in cache:
            cache[key] = self._recap_card_slots(
                w, h, card_w, card_h, reserved_boxes, route_obstacles
            )
        best, best_d2 = None, None
        for sx, sy in cache[key]:
            if any(
                sx < px2 and sx + card_w > px1 and sy < py2 and sy + card_h > py1
                for px1, py1, px2, py2 in placed
            ):
                continue
            d2 = (sx + card_w / 2 - pin_x) ** 2 + (sy + card_h / 2 - pin_y) ** 2
            if best_d2 is None or d2 < best_d2:
                best, best_d2 = (float(sx), float(sy)), d2
        return best

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
        fps: Optional[float] = None,
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

        Beyond not overlapping, a candidate spot's leader line is also
        checked against every other already-placed card's box AND every
        other already-placed card's own leader line (via
        _leader_crosses_placed) — a busy
        cluster of nearby waypoints used to produce tangled, crossing
        leader lines even though no two CARDS actually overlapped, which
        read as genuinely ambiguous about which card belonged to which
        pin. The spiral prefers a spot with no crossing at all, falling
        back to the first merely-non-overlapping spot only if nothing
        crossing-free turns up within `max_radius` — a transient card
        showing with an imperfect line for one busy frame beats it
        disappearing entirely because avoidance was too strict. This
        does NOT check against the route line itself (only route-vs-BOX
        overlap, same as before) — leader-line-vs-route-line crossing is
        a separate, deliberately out-of-scope concern for now.

        Also used (via _render_recap_frame, with a much larger max_radius
        so the spiral effectively covers the whole frame instead of
        giving up nearby) for the end-of-video recap, where every card
        needs a spot at once rather than just the ones that fit within a
        tight radius of their own pin."""
        if card_w is None or card_h is None:
            # Matches render_popup_box's actual drawn card size exactly
            # (see beside_card_footprint) — a mismatch here is what let
            # concurrently-visible cards visually overlap despite this
            # layout step believing they didn't.
            footprint_w, footprint_h = self.graphics.beside_card_footprint()
            card_w = card_w if card_w is not None else footprint_w
            card_h = card_h if card_h is not None else footprint_h
        placed: List[Tuple[float, float, float, float]] = list(reserved_boxes or [])
        # Every already-placed card's own leader line (pin -> its card's
        # real anchor point) — threaded across the whole call (every
        # popup in `group`, including ones locked into an existing spot
        # from a previous frame) so a card still searching this frame
        # can't have its line cross one that's already settled and
        # visible. See _leader_crosses_placed.
        placed_lines: List[List[Tuple[float, float]]] = []
        route_x = route_obstacles[:, 0] if route_obstacles is not None else None
        route_y = route_obstacles[:, 1] if route_obstacles is not None else None

        # Leader-line length: how far the card starts from its pin before
        # any avoidance kicks in — tied to the pin's own drawn size (rather
        # than a flat pixel constant) so the card starts right at its edge
        # plus a small gap, long enough that a route line passing close to
        # the pin (very common, it just arrived there) doesn't get planted
        # on immediately, but no longer than that.
        lead_offset = self.graphics.marker_radius + 20
        # Every pin's drawn silhouette (overview.py sets it), kept apart from
        # the route line so "straight above the pin" can ignore the line but
        # never cover another pin. See free_spot.
        pin_pts = getattr(self, "_layout_pin_obstacles", None)
        own_half_w = float(self.graphics.marker_radius) + 4.0
        own_head = 2.5 * float(self.graphics.marker_radius) + 4.0

        def free_spot(x: float, y: float) -> Optional[Tuple[float, float]]:
            # Seed the search directly above the pin (centered on it)
            # rather than beside it — a card beside the pin routinely sat
            # right on top of the route line leading into/out of that
            # same pin, since the route passes close by on either side of
            # where it just arrived. A pin near the top of the frame
            # (where "above" would run off-screen) seeds below instead.
            # --- MODIFICATION: Add extra vertical clearance ---
            extra_lift = 30  # Increase this value to push the card higher
            
            start_x = x - card_w / 2
            start_y = (
                y - card_h - lead_offset - extra_lift
                if y - card_h - lead_offset - extra_lift >= margin
                else y + lead_offset + extra_lift
            )

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

            def crosses(bx: float, by: float) -> bool:
                ax, ay = _anchor_point(x, y, bx, by, card_w, card_h)
                return _leader_crosses_placed([(x, y), (ax, ay)], placed, placed_lines)

            def _above_is_clear(bx: float, by: float, pin_x: float, pin_y: float) -> bool:
                rx0, ry0, rx1, ry1 = (
                    bx - card_gap, by - card_gap,
                    bx + card_w + card_gap, by + card_h + card_gap,
                )
                if any(
                    rx0 < px1 and rx1 > px0 and ry0 < py1 and ry1 > py0
                    for (px0, py0, px1, py1) in placed
                ):
                    return False
                if pin_pts is None or not len(pin_pts):
                    return True
                px, py = pin_pts[:, 0], pin_pts[:, 1]
                inside = (px >= rx0) & (px <= rx1) & (py >= ry0) & (py <= ry1)
                own = (
                    (np.abs(px - pin_x) <= own_half_w)
                    & (py >= pin_y - own_head) & (py <= pin_y + 4.0)
                )
                return not bool(np.any(inside & ~own))

            # Two passes: prefer a spot whose leader line crosses nothing, but track
            # the first merely-non-overlapping spot as a fallback in case
            # nothing crossing-free turns up before the spiral runs out.
            fallback: Optional[Tuple[float, float]] = None

            bx, by = clamp(start_x, start_y)
            # The photo belongs on top of its pin: straight above wins even
            # when it lies over the route line, as long as it covers no other
            # card and no OTHER pin (its own pin's head sits just below it).
            if start_y < y and _above_is_clear(bx, by, x, y) and not crosses(bx, by):
                return bx, by
            if not overlaps(bx, by):
                fallback = (bx, by)
                if not crosses(bx, by):
                    return bx, by

            # [NOTE] [Animation] Archimedean-spiral search outward from the pin until a non-overlapping (and preferably non-crossing) spot is found or max_radius is exhausted.
            angle, radius = 0.0, 0.0
            while radius < max_radius:
                radius += _SPIRAL_RADIUS_STEP_PX
                angle += _SPIRAL_ANGLE_STEP_RAD
                bx, by = clamp(
                    start_x + radius * math.cos(angle),
                    start_y + radius * math.sin(angle),
                )
                if not overlaps(bx, by):
                    if fallback is None:
                        fallback = (bx, by)
                    if not crosses(bx, by):
                        return bx, by

            return fallback  # crossing-free spot never found; use the fallback (None if not even that exists — too crowded nearby, sit this frame out)

        # Trigger order, not screen position — so a cluster's cards fill in
        # the order the traveler actually reaches them.
        lock_frames = (
            fps * tuning.POPUP_POSITION_LOCK_SECONDS if fps else 0
        )
        for bp in sorted(group, key=lambda b: b["popup"].get("order", 0)):
            popup = bp["popup"]

            # Already-positioned and still within its lock window — keep
            # the existing spot instead of recomputing (see
            # tuning.POPUP_POSITION_LOCK_SECONDS). Still reserved into
            # `placed` below so a card processed after this one (lower
            # priority order) can't be given the same spot.
            existing_box = popup.get("beside_box")
            total_frames = bp.get("total_frames")
            frames_left = bp.get("frames_left")
            pin_x, pin_y = popup.get("pin_x", popup["x"]), popup.get("pin_y", popup["y"])
            if (
                existing_box is not None
                and total_frames is not None
                and frames_left is not None
                and (total_frames - frames_left) < lock_frames
            ):
                box_x, box_y = existing_box
                placed.append((box_x, box_y, box_x + card_w, box_y + card_h))
                # This card's line is already settled and visible on
                # screen — a card still searching this frame must not be
                # allowed to cross it, so it goes into placed_lines same
                # as a freshly-placed one does below.
                anchor_x, anchor_y = _anchor_point(pin_x, pin_y, box_x, box_y, card_w, card_h)
                placed_lines.append([(pin_x, pin_y), (anchor_x, anchor_y)])
                continue

            # The card's leader line actually anchors on pin_x/pin_y when
            # set (render_popup_box's own preference — see its docstring)
            # — searching for a spot relative to the true x/y instead
            # would start the search from a different point than where
            # the line will actually connect, for any waypoint whose pin
            # got fanned out by _declutter_pins.
            spot = free_spot(pin_x, pin_y)
            if spot is None:
                # The near-pin spiral found nothing within max_radius —
                # a real dense cluster, where the room beside every pin is
                # already taken. Rather than let the card sit this frame
                # out (it would keep sitting out for as long as the cluster
                # is on screen, so a waypoint the traveler genuinely
                # reached could go unshown for seconds or never), fall back
                # to the nearest slot on the frame-wide lattice: disjoint
                # by construction, so the card is placed with a guaranteed
                # non-overlapping spot at the cost of a longer leader line.
                spot = self._nearest_lattice_slot(
                    pin_x, pin_y, w, h, card_w, card_h, placed, reserved_boxes,
                    route_obstacles,
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
            anchor_x, anchor_y = _anchor_point(pin_x, pin_y, box_x, box_y, card_w, card_h)
            placed_lines.append([(pin_x, pin_y), (anchor_x, anchor_y)])

    def _place_cards_above_pins(
        self,
        cards: List[Dict],
        w: int,
        h: int,
        card_w: int,
        card_h: int,
        margin: int = 20,
        gap: int = 12,
    ) -> None:
        """Moves each card to sit straight above its own pin, centred on it,
        with its bottom edge just over the pin's head (a pin is drawn upward
        from its coordinate, ~2.5 radii tall - see _pin_obstacle_points).
        A card keeps its current spot when there is no room above the pin
        (a pin near the top edge) or when the spot above would overlap a
        card already placed here."""
        head_top = 2.5 * float(self.graphics.marker_radius) + 4.0
        placed: List[Tuple[float, float, float, float]] = []
        for card in cards:
            pin_x = card.get("pin_x", card["x"])
            pin_y = card.get("pin_y", card["y"])
            box_y = pin_y - head_top - gap - card_h
            box_x = max(margin, min(pin_x - card_w / 2, w - card_w - margin))
            fits = box_y >= margin and not any(
                box_x < px1 + gap and box_x + card_w > px0 - gap
                and box_y < py1 + gap and box_y + card_h > py0 - gap
                for (px0, py0, px1, py1) in placed
            )
            if fits:
                card["beside_box"] = (int(box_x), int(box_y))
            box = card.get("beside_box")
            if box is not None:
                placed.append((box[0], box[1], box[0] + card_w, box[1] + card_h))

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
        fps: Optional[float] = None,
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

        Pins packed within `marker_radius * 3.0` px of 2 or more other
        pins (e.g. several attractions on one small island) route their
        leader line via the nearest point on a shared padded convex-hull
        boundary around the whole cluster (see _padded_boundary) instead
        of anchoring straight at the pin — measured to cut total leader-
        line crossings on a real dense cluster from 6 to 4, since
        straight-line anchoring guarantees a crossing whenever two of the
        cluster's cards land on opposite sides of it.

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
        # Every already-placed popup's OWN leader line (pin -> its card's
        # nearest edge, same anchor formula render_popup_box actually
        # draws with — see _anchor_point) — checked alongside `placed`
        # (the card boxes themselves) so a new candidate can't cut across
        # another line that isn't touching any box directly.
        placed_lines: List[List[Tuple[float, float]]] = []
        route_x = route_obstacles[:, 0] if route_obstacles is not None else None
        route_y = route_obstacles[:, 1] if route_obstacles is not None else None
        # Wider than the flow-through popups' own gap (14px) — the recap
        # shows every card at once, so a tight 14px pack read as one
        # solid, cramped block rather than a set of distinct cards. Was
        # 34px, brought down to 26 (still real breathing room, just not
        # as generous): measured against a real project's dense cluster,
        # 34px let cards run out of nearby packed spots sooner, forcing
        # the spiral search to travel much further out — longest line
        # 929px, only 8 of the cluster's cards fitting within max_radius
        # at all. 26px measurably shortens lines (longest 646px) and
        # lets more cards fit nearby (11 shown instead of 8), at the cost
        # of more total crossings (7 vs 4) — a real tradeoff, chosen
        # because shorter/more-cards was the priority here.
        card_gap = 26

        # --- Tight-cluster detection: route lines around the cluster's
        # own outer edge instead of straight through its middle ---------
        pin_positions: List[Tuple[float, float]] = [
            (bp["popup"].get("pin_x", bp["popup"]["x"]), bp["popup"].get("pin_y", bp["popup"]["y"]))
            for bp in group
        ]
        link_dist = self.graphics.marker_radius * 3.0
        hull_padding = self.graphics.marker_radius + 24.0
        hull_anchor_by_id: Dict[int, Tuple[float, float]] = {}
        cluster_centroid_by_id: Dict[int, Tuple[float, float]] = {}
        for idxs in _cluster_points_by_distance(pin_positions, link_dist):
            if len(idxs) < 3:
                continue
            cluster_pts = [pin_positions[i] for i in idxs]
            boundary = _padded_boundary(cluster_pts, hull_padding)
            cx = sum(p[0] for p in cluster_pts) / len(cluster_pts)
            cy = sum(p[1] for p in cluster_pts) / len(cluster_pts)
            for i in idxs:
                popup_id = id(group[i]["popup"])
                hull_anchor_by_id[popup_id] = _nearest_point_on_polygon(boundary, pin_positions[i])
                cluster_centroid_by_id[popup_id] = (cx, cy)

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

        def leader_crosses_placed(
            pin_x: float, pin_y: float, bx: float, by: float,
            via: Optional[Tuple[float, float]] = None,
        ) -> bool:
            if via is not None:
                ax, ay = _anchor_point(via[0], via[1], bx, by, card_w, card_h)
                polyline = [(pin_x, pin_y), via, (ax, ay)]
            else:
                ax, ay = _anchor_point(pin_x, pin_y, bx, by, card_w, card_h)
                polyline = [(pin_x, pin_y), (ax, ay)]
            return _leader_crosses_placed(polyline, placed, placed_lines)

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

        pin_r = float(self.graphics.marker_radius)

        def covers_pin(bx: float, by: float, pin_x: float, pin_y: float) -> bool:
            # the pin's head sits above its tip (pin_x, pin_y)
            return (
                bx - 8 < pin_x + pin_r and bx + card_w + 8 > pin_x - pin_r
                and by - 8 < pin_y + 4 and by + card_h + 8 > pin_y - 2.6 * pin_r
            )

        def near_spot(
            x: float, y: float, ox: float, oy: float, hside: str, vside: str,
            via: Optional[Tuple[float, float]],
        ) -> Optional[Tuple[float, float]]:
            """The spot round (ox, oy) with the shortest leader line: rings of
            candidates (tuning.POPUP_NEAR_DIRECTIONS directions, out to
            tuning.POPUP_NEAR_MAX_LEADER_PX), each card placed so the edge
            nearest the pin faces it. A card may not overlap another card or
            the route, cover its own pin, or cut across another card's line;
            one on the far side of its pin from its frame side costs a
            little more (tuning.POPUP_NEAR_OFF_SIDE_PX). None when nothing
            fits that close."""
            best, best_cost = None, float("inf")
            steps = int(tuning.POPUP_NEAR_DIRECTIONS)
            gap = pin_r + 14.0
            while gap <= tuning.POPUP_NEAR_MAX_LEADER_PX:
                for k in range(steps):
                    theta = 2 * math.pi * k / steps
                    cos_t, sin_t = math.cos(theta), math.sin(theta)
                    ax, ay = ox + gap * cos_t, oy - pin_r + gap * sin_t  # round the pin's head
                    bx, by = clamp(
                        ax - card_w / 2 + cos_t * card_w / 2, ay - card_h / 2 + sin_t * card_h / 2
                    )
                    if covers_pin(bx, by, x, y) or overlaps(bx, by):
                        continue
                    if leader_crosses_placed(x, y, bx, by, via):
                        continue
                    start = via if via is not None else (x, y)
                    anchor = _anchor_point(start[0], start[1], bx, by, card_w, card_h)
                    cost = math.hypot(anchor[0] - start[0], anchor[1] - start[1])
                    if not quadrant_ok(hside, vside, bx, by, x, y):
                        cost += tuning.POPUP_NEAR_OFF_SIDE_PX
                    if cost < best_cost:
                        best, best_cost = (bx, by), cost
                if best is not None and best_cost <= gap:
                    break  # nothing further out can be shorter
                gap += 16.0
            return best

        def free_spot(
            x: float, y: float,
            origin: Optional[Tuple[float, float]] = None,
            via: Optional[Tuple[float, float]] = None,
        ) -> Optional[Tuple[float, float]]:
            # `origin` overrides WHERE THE SEARCH STARTS (a cluster's
            # pin uses its outward-pushed hull anchor here, so cards ring
            # the cluster's outside instead of starting from a point
            # potentially deep in its interior) — `x, y` (the true pin)
            # still governs side_for/vside_for/quadrant_ok below, so the
            # "never cross to the wrong side of your OWN pin" guarantee
            # is unaffected by which point the search happens to start
            # from.
            ox, oy = origin if origin is not None else (x, y)
            hside = side_for(x)
            vside = vside_for(y)
            # Anchor gap scales with how much genuinely open room this
            # pin's required side actually has, rather than a flat 50px —
            # a pin sitting well into a spacious empty region (say, the
            # far side of the frame from a dense cluster of other pins)
            # used to still anchor its card right up against itself,
            # leaving that open space unused and cards crowded in toward
            # the middle. Capped so it doesn't stretch absurdly far on a
            # huge frame.
            avail_x = (ox - margin) if hside == "left" else (w - margin - ox)
            gap_x = max(50.0, min(avail_x * 0.35, 200.0))
            start_x = ox - card_w - gap_x if hside == "left" else ox + gap_x
            avail_y = (oy - margin) if vside == "top" else (h - margin - oy)
            gap_y = max(50.0, min(avail_y * 0.35, 200.0))
            start_y = oy - card_h - gap_y if vside == "top" else oy + gap_y

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
            # Nearest first: a card as close round its own pin as it fits
            # (any side - the side rules above are only a preference here),
            # so the leader line stays short. The searches below, which keep
            # to the pin's side of the frame, are the fallback for a pin
            # with nothing free close by.
            near = near_spot(x, y, ox, oy, hside, vside, via)
            if near is not None:
                return near

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
            # doesn't cut across another card. `fallback` (the closest
            # merely-non-overlapping spot) is tracked here but NOT
            # returned yet — the masonry candidate set is a small,
            # tightly-packed sample, and giving up on crossing-avoidance
            # the moment IT runs dry skips the far larger spiral search
            # below entirely, even though the spiral routinely finds a
            # genuinely crossing-free spot the masonry set never
            # considered. Both passes share one fallback, only ever used
            # once NEITHER pass finds a crossing-free spot.
            fallback: Optional[Tuple[float, float]] = None
            for cbx, cby in deduped:
                if overlaps(cbx, cby):
                    continue
                if fallback is None:
                    fallback = (cbx, cby)
                if not leader_crosses_placed(x, y, cbx, cby, via):
                    return cbx, cby

            # Nothing in the masonry candidate set was crossing-free —
            # widen the search with a continuous spiral, still confined
            # to the required quadrant (candidates violating quadrant_ok
            # are skipped, not just deprioritized — the leader line grows
            # as long as it needs to rather than ever crossing to the
            # wrong side on either axis), still preferring a non-crossing
            # spot over the masonry pass's own fallback.
            angle, radius = 0.0, 0.0
            max_radius = float(max(w, h)) * 1.5
            while radius < max_radius:
                radius += _SPIRAL_RADIUS_STEP_PX
                angle += _SPIRAL_ANGLE_STEP_RAD
                bx, by = clamp(
                    start_x + radius * math.cos(angle), start_y + radius * math.sin(angle)
                )
                if not quadrant_ok(hside, vside, bx, by, x, y):
                    continue
                if overlaps(bx, by):
                    continue
                if fallback is None:
                    fallback = (bx, by)
                if not leader_crosses_placed(x, y, bx, by, via):
                    return bx, by
            if fallback is not None:
                return fallback

            # A pin sitting close enough to the frame's own edge that
            # there's no room at all for a full card in its required
            # quadrant (e.g. a left-zone pin within one card-width of the
            # left margin) — showing the card off-quadrant beats not
            # showing it at all, so this absolute last resort drops the
            # quadrant_ok requirement (everything else — no overlap,
            # prefer no line-crossing — still applies).
            angle, radius = 0.0, 0.0
            while radius < max_radius:
                radius += _SPIRAL_RADIUS_STEP_PX
                angle += _SPIRAL_ANGLE_STEP_RAD
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

        def is_locked(bp: Dict) -> bool:
            """Once a flow-through popup has settled into a spot, it keeps
            it for the rest of its own display — not just
            tuning.POPUP_POSITION_LOCK_SECONDS after first appearing.

            That constant used to be the whole lock window: a card's box
            was only protected from recomputation for its first 2 seconds
            on screen, then became fair game again for every later frame
            of a still-long display. Near a dense cluster where several
            waypoints trigger close together in time, each new arrival's
            layout pass can re-sort the competing cards and hand an
            already-settled one a DIFFERENT spot — the card visibly jumps,
            and for a display lasting well past that 2s window (a long
            leg's worth of flow-through time), it could jump more than
            once. A settled card is only ever a genuine obstacle for
            everyone placed after it (see `reserve` below); nothing
            requires it to keep re-competing for its own spot once it has
            one."""
            return bp["popup"].get("beside_box") is not None

        def reserve(bp: Dict) -> None:
            popup = bp["popup"]
            pin_x, pin_y = popup.get("pin_x", popup["x"]), popup.get("pin_y", popup["y"])
            via = hull_anchor_by_id.get(id(popup))
            box_x, box_y = popup["beside_box"]
            placed.append((box_x, box_y, box_x + card_w, box_y + card_h))
            if via is not None:
                anchor_x, anchor_y = _anchor_point(via[0], via[1], box_x, box_y, card_w, card_h)
                placed_lines.append([(pin_x, pin_y), via, (anchor_x, anchor_y)])
            else:
                anchor_x, anchor_y = _anchor_point(pin_x, pin_y, box_x, box_y, card_w, card_h)
                placed_lines.append([(pin_x, pin_y), (anchor_x, anchor_y)])

        # EVERY locked card is reserved up front, before a single free
        # placement runs — not as its turn comes round in angular order.
        # A locked card's box can't move this frame, so a card placed
        # before it in the ring order has to treat it as an obstacle:
        # reserving them in-order instead let an earlier free card be
        # placed straight on top of a locked one that simply hadn't been
        # reached yet, and the two then stayed stacked until the lock
        # expired.
        locked_ids = set()
        for bp in ordered:
            if is_locked(bp):
                locked_ids.add(id(bp))
                reserve(bp)

        for bp in ordered:
            if id(bp) in locked_ids:
                continue
            popup = bp["popup"]
            pin_x, pin_y = popup.get("pin_x", popup["x"]), popup.get("pin_y", popup["y"])
            via = hull_anchor_by_id.get(id(popup))

            search_origin = None
            if via is not None:
                # Push the search's own starting point further outward
                # from the cluster centroid, past the padded hull, so
                # cards seed OUTSIDE the boundary (a halo around the
                # cluster) rather than right on its edge.
                cx, cy = cluster_centroid_by_id[id(popup)]
                dx, dy = via[0] - cx, via[1] - cy
                norm = math.hypot(dx, dy) or 1.0
                push = self.graphics.marker_radius + 20.0
                search_origin = (via[0] + dx / norm * push, via[1] + dy / norm * push)
            spot = free_spot(pin_x, pin_y, origin=search_origin, via=via)
            popup["leader_via"] = via
            if spot is None:
                popup.pop("beside_box", None)
                continue
            box_x, box_y = spot
            popup["beside_box"] = (int(box_x), int(box_y))
            reserve(bp)

    # --- End-of-video recap: card layout --------------------------------
    # Card scales tried largest-first until the frame has enough free slots
    # to give every card one at once. Floored at the last entry — below
    # that a card's photo and label stop being legible, so a route with
    # more stops than that many slots shows as many as fit rather than
    # shrinking into illegibility.
    _RECAP_CARD_SCALES: Tuple[float, ...] = (0.85, 0.75, 0.65, 0.55, 0.46, 0.38)
    _RECAP_CARD_MARGIN = 16
    # Breathing room between neighbouring cards. Generous on purpose: at a
    # tight 10px, cards placed near each other read as one solid slab and
    # the leader lines threading between them had no visible channel to run
    # through, so an individual line was hard to follow back to its pin.
    _RECAP_CARD_GAP = 24
    # Leader lines in the recap are drawn thicker than the default 2px — a
    # hairline is easy to lose against a busy map with this many cards up.
    _RECAP_LEADER_WIDTH = 3
    # Clearance kept between a card and the route line/pins it must not
    # cover — the map underneath is the whole point of the recap frame.
    _RECAP_CARD_OBSTACLE_PAD = 10

    def _recap_card_slots(
        self,
        w: int,
        h: int,
        card_w: int,
        card_h: int,
        reserved_boxes: Optional[List[Tuple[float, float, float, float]]] = None,
        route_obstacles: Optional[np.ndarray] = None,
        centers: Optional[List[Tuple[float, float]]] = None,
    ) -> List[Tuple[int, int]]:
        """Candidate card positions on a disjoint lattice covering the WHOLE
        frame — not just its border — minus any that would cover the route
        line, a pin, or `reserved_boxes` (the summary card's own corner,
        composited over the recap afterwards).

        Spanning the interior is what lets a card sit in open space near
        its own pin instead of being pushed out to the frame edge: a route
        with a big empty region in the middle (open water, say) has plenty
        of room there, and leaving it unused both wastes the frame and
        makes every leader line longer than it needs to be. The lattice
        pitch is the card's own size plus a gap, so two slots can never
        overlap however many cards end up placed, and it is centred in the
        leftover space so the arrangement doesn't bias to one side."""
        margin, gap = self._RECAP_CARD_MARGIN, self._RECAP_CARD_GAP
        pad = self._RECAP_CARD_OBSTACLE_PAD
        ox = oy = None
        if route_obstacles is not None and len(route_obstacles):
            ox, oy = route_obstacles[:, 0], route_obstacles[:, 1]

        def slot_ok(x: int, y: int) -> bool:
            if x < margin or y < margin or x + card_w > w - margin or y + card_h > h - margin:
                return False
            if any(
                x < rx2 and x + card_w > rx1 and y < ry2 and y + card_h > ry1
                for rx1, ry1, rx2, ry2 in (reserved_boxes or ())
            ):
                return False
            if ox is not None and bool(
                np.any(
                    (ox >= x - pad) & (ox <= x + card_w + pad)
                    & (oy >= y - pad) & (oy <= y + card_h + pad)
                )
            ):
                return False
            return True

        if centers is not None:
            max_ring_r = math.hypot(w, h)
            slots: List[Tuple[int, int]] = []
            
            golden_angle = math.pi * (3.0 - math.sqrt(5.0))
            n = 0
            target_slots = len(centers) * 2
            
            while len(slots) < target_slots and n < 8000:
                r = 5.0 * math.sqrt(n)
                if r > max_ring_r:
                    break
                
                theta = n * golden_angle
                n += 1
                
                for cx, cy in centers:
                    sx = int(cx + r * math.cos(theta) - card_w / 2.0)
                    sy = int(cy + r * math.sin(theta) - card_h / 2.0)
                    
                    if not slot_ok(sx, sy):
                        continue
                        
                    overlap = False
                    for ex, ey in slots:
                        if not (sx + card_w + gap <= ex or ex + card_w + gap <= sx or sy + card_h + gap <= ey or ey + card_h + gap <= sy):
                            overlap = True
                            break
                    if not overlap:
                        slots.append((sx, sy))
                        
            return slots

        def axis(available: int, size: int) -> List[int]:
            pitch = size + gap
            count = int((available + gap) // pitch)
            if count <= 0:
                return []
            slack = available - (count * size + (count - 1) * gap)
            first = margin + slack // 2
            return [first + i * pitch for i in range(count)]

        xs = axis(w - 2 * margin, card_w)
        ys = axis(h - 2 * margin, card_h)
        if not xs or not ys:
            return []

        slots = []
        for y in ys:
            for x in xs:
                if slot_ok(x, y):
                    slots.append((int(x), int(y)))
        return slots

    def _layout_recap_cards(
        self,
        popups: List[Dict],
        w: int,
        h: int,
        reserved_boxes: Optional[List[Tuple[float, float, float, float]]] = None,
        route_obstacles: Optional[np.ndarray] = None,
    ) -> List[Dict]:
        """Places EVERY recap card at once and returns them in the order
        they should be revealed.

        Used for the recap instead of _layout_recap_popups' spiral/masonry
        search, which packs each card in beside its own pin. That reads
        well for a handful of cards but cannot show a real route's full set
        together: with nothing like enough free space beside a dense
        cluster, its cards spiral far away and their leader lines tangle.
        Here the candidate positions are a disjoint lattice of free space
        (see _recap_card_slots), so no two cards can overlap however many
        there are, and cards are matched to them by MINIMUM TOTAL leader
        length via linear_sum_assignment. Minimising the total is what
        keeps the lines untangled as well as short: if two leaders crossed,
        trading the two cards' slots would shorten both (triangle
        inequality), so a minimum-total matching cannot hold a crossing in
        the first place.

        Each card's "card_scale" and "recap_line_color" are stamped onto
        the popup here too, so the per-frame draw never re-derives either —
        a card must not move, resize or change color as later cards join it
        on screen (see _render_recap_frame)."""
        if not popups:
            return []

        def pin_of(popup: Dict) -> Tuple[float, float]:
            return popup.get("pin_x", popup["x"]), popup.get("pin_y", popup["y"])

        card_scale = self._RECAP_CARD_SCALES[-1]
        card_w, card_h = self.graphics.beside_card_footprint(card_scale)
        slots: List[Tuple[int, int]] = []
        # Second pass drops the keep-off-the-route rule: a map whose route
        # sprawls across most of the frame would otherwise leave too few
        # free slots to show every stop, and drawing them over the line
        # beats silently dropping some.
        all_pins = [pin_of(p) for p in popups]
        cx = sum(p[0] for p in all_pins) / len(all_pins)
        cy = sum(p[1] for p in all_pins) / len(all_pins)

        for obstacles in (route_obstacles, None):
            for scale in self._RECAP_CARD_SCALES:
                cw, ch = self.graphics.beside_card_footprint(scale)
                candidate = self._recap_card_slots(
                    w, h, cw, ch, reserved_boxes, obstacles, centers=all_pins
                )
                if len(candidate) > len(slots):
                    card_scale, card_w, card_h, slots = scale, cw, ch, candidate
                if len(candidate) >= len(popups):
                    break
            if len(slots) >= len(popups):
                break

        # Revealed in angular order around the cluster, so consecutive
        # reveals land next to each other on screen rather than jumping
        # about the frame.
        ordered = sorted(
            popups, key=lambda p: math.atan2(pin_of(p)[1] - cy, pin_of(p)[0] - cx)
        )

        if len(slots) < len(ordered):
            logger.warning(
                "Recap layout: only %d free card slots for %d popup cards at "
                "the smallest card scale — showing %d of them.",
                len(slots), len(ordered), len(slots),
            )
            ordered = ordered[: len(slots)]

        pins_xy = [pin_of(p) for p in ordered]
        pin_arr = np.asarray(pins_xy, dtype=float)
        slot_arr = np.asarray(slots, dtype=float) + np.array(
            [card_w / 2.0, card_h / 2.0]
        )
        # Use SQUARED Euclidean distance. This mathematically prevents leader
        # line crossings even in 1D collinear cases where standard Euclidean
        # distance would result in a tie and arbitrary assignment.
        cost = (
            (slot_arr[None, :, 0] - pin_arr[:, None, 0]) ** 2
            + (slot_arr[None, :, 1] - pin_arr[:, None, 1]) ** 2
        )
        slot_for = list(linear_sum_assignment(cost)[1])

        # Safety net. The matching above minimises pin-to-card-CENTRE
        # distance, while a leader actually stops at the card's near edge
        # (see _anchor_point), so the no-crossing property it guarantees is
        # very slightly approximate. Any pair that does still cross gets
        # its slots traded, which shortens both — so this strictly reduces
        # total leader length and always terminates.
        n = len(ordered)

        def leader(j: int) -> Tuple[Tuple[float, float], Tuple[float, float]]:
            sx, sy = slots[slot_for[j]]
            px, py = pins_xy[j]
            return (px, py), _anchor_point(px, py, sx, sy, card_w, card_h)

        def crosses(a1, a2, b1, b2) -> bool:
            def turn(p, q, r):
                return (r[1] - p[1]) * (q[0] - p[0]) - (q[1] - p[1]) * (r[0] - p[0])

            return (
                (turn(b1, b2, a1) > 0) != (turn(b1, b2, a2) > 0)
                and (turn(a1, a2, b1) > 0) != (turn(a1, a2, b2) > 0)
            )

        for _ in range(n * n):
            swapped = False
            for a in range(n):
                for b in range(a + 1, n):
                    if crosses(*leader(a), *leader(b)):
                        slot_for[a], slot_for[b] = slot_for[b], slot_for[a]
                        swapped = True
            if not swapped:
                break

        palette = tuning.RECAP_LINE_COLOR_PALETTE
        for j, popup in enumerate(ordered):
            sx, sy = slots[slot_for[j]]
            popup["beside_box"] = (int(sx), int(sy))
            popup["card_scale"] = card_scale
            # Straight pin -> card lines only; the dense-cluster hull detour
            # _layout_recap_popups adds would bend a leader away from the
            # shortest path this layout is built around.
            popup.pop("leader_via", None)
            popup["recap_line_color"] = palette[j % len(palette)]

        return ordered

    def _render_recap_frame(
        self,
        base_frame: np.ndarray,
        active_popups: List[Dict],
        group_popups: Optional[List[Dict]] = None,
    ) -> np.ndarray:
        """End-of-video recap: every waypoint with a photo gets its popup
        card, each with a leader line back to its own pin — start and end
        (see _draw_pin's "S"/"E" pins) treated the same as every other
        waypoint, no special fixed corner or enlarged card. Replaces just
        showing the LAST waypoint's card alone in a fixed HUD corner
        through the whole summary.

        Purely a draw pass: where each card sits, how big it is and what
        color its line is were all decided once by _layout_recap_cards,
        which the caller runs over the WHOLE set before the first frame.

        `group_popups` (a caller-chosen subset — see
        _render_recap_and_summary's progressive reveal) restricts which
        popups get a CARD drawn this frame; `active_popups` below still
        draws EVERY pin regardless, so the whole route's stops stay
        visible even before their own card has appeared."""
        recap_frame = base_frame.copy()
        recap_popups = (
            group_popups if group_popups is not None
            else [ap for ap in active_popups if ap["data"].get("popup_image")]
        )
        if not recap_popups:
            return recap_frame

        total_points = 1 + max((ap["index"] for ap in active_popups), default=0)
        hud_popups = []
        for ap in recap_popups:
            if not ap.get("beside_box"):
                continue
            hud_popup = ap.copy()
            hud_popup["hud_corner"] = None
            hud_popup["draw_leader_line"] = True
            # By recap time every waypoint has "arrived", which collapses
            # _pin_label_and_color down to two flat colors (one shared by
            # every numbered stop, one by every stop-by landmark), so
            # matching each line to its own pin's color would leave most
            # of them identical. _layout_recap_cards hands out a distinct
            # palette color per card instead, which is
            # what makes an individual line followable back to its card.
            line_color = ap.get("recap_line_color") or self.graphics.marker_color
            hud_popup["leader_line_color"] = line_color
            hud_popup["leader_line_width"] = self._RECAP_LEADER_WIDTH
            # Override the card's own border_color (set once, early in
            # render_overview's setup, back when no waypoint had "arrived"
            # yet — see _pin_color) with this SAME color the line uses, so
            # each card visually matches the line leading to it.
            hud_popup["border_color"] = line_color
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
        min_hold_seconds: float = 0.0, min_display_seconds: Optional[float] = None,
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
        # Floored at POPUP_MIN_DISPLAY_SECONDS: this is the single point
        # every popup's display duration passes through on its way to
        # frames, so enforcing the minimum here covers every caller.
        # `min_display_seconds`: an explicit override for a caller that
        # deliberately wants a shorter floor than the global default (e.g.
        # a stop-by batch card, tuning.STOPBY_BATCH_SECONDS - several of
        # these play back to back, so the usual "long enough to read one
        # name" floor stacks into a much longer freeze than intended; see
        # _play_stopby_batch). Falls back to POPUP_MIN_DISPLAY_SECONDS.
        # `min_hold_seconds`: fully shown at least this long between its
        # fades - for a card that stays up while the walker moves on
        # (tuning.OVERVIEW_POPUP_MIN_HOLD_SECONDS). Not for a card played
        # over a frozen map: that would lengthen the freeze itself.
        floor = tuning.POPUP_MIN_DISPLAY_SECONDS if min_display_seconds is None else min_display_seconds
        display_seconds = max(float(display_seconds), floor)
        if min_hold_seconds > 0:
            display_seconds = max(display_seconds, min_hold_seconds + 2 * cls._POPUP_FADE_SECONDS)
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
    def _popup_fade_frames(bp: Dict) -> int:
        """The `fade_frames` window (in frames) for a baked popup: the
        explicit value set at creation (see _make_baked_popup) when
        present, else a default of 1/5 of its total display duration —
        shared by _popup_fade_alpha and _popup_slide_offset_y, which both
        ramp their own envelope over exactly this same window so the fade
        and the slide finish together."""
        return bp.get("fade_frames") or max(1, bp.get("total_frames", 1) // 5)

    @classmethod
    def _popup_fade_alpha(cls, bp: Dict) -> float:
        """Fade envelope (0-1) for a baked popup at its current countdown
        position — ramps up over its first `fade_frames` and back down
        over its last, full opacity in between."""
        fade_frames = cls._popup_fade_frames(bp)
        elapsed = bp.get("total_frames", bp["frames_left"]) - bp["frames_left"]
        alpha_in = min(1.0, elapsed / fade_frames)
        alpha_out = min(1.0, bp["frames_left"] / fade_frames)
        t = max(0.0, min(alpha_in, alpha_out))
        return t * t * (3 - 2 * t)  # smoothstep: eases in and out, no linear snap at either end

    # A card grows from this fraction of its size as it fades in (and shrinks
    # back toward it as it fades out), about its centre - a soft pop rather
    # than a flat cross-fade.
    _POPUP_ENTER_SCALE = 0.88

    @classmethod
    def _popup_enter_scale(cls, bp: Dict) -> float:
        """Size factor for a baked popup's card at its current countdown
        position: ease-out cubic from _POPUP_ENTER_SCALE to 1 over its fade-in,
        back down over its fade-out, 1 in between."""
        fade_frames = cls._popup_fade_frames(bp)
        elapsed = bp.get("total_frames", bp["frames_left"]) - bp["frames_left"]
        t = max(0.0, min(1.0, elapsed / fade_frames, bp["frames_left"] / fade_frames))
        eased = 1 - (1 - t) ** 3
        return cls._POPUP_ENTER_SCALE + (1 - cls._POPUP_ENTER_SCALE) * eased

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
        fade_frames = cls._popup_fade_frames(bp)
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

    def _active_card_boxes(
        self,
        baked_popups: List[Dict],
        exclude: Optional[Dict] = None,
    ) -> List[Tuple[float, float, float, float]]:
        """The on-screen rectangles of every baked popup that currently has
        a leader-lined card placed — for handing to a layout call that is
        only positioning ONE new card (see overview_animation.py's
        trigger-time placement).

        Without this, a card laid out on its own has an empty `placed`
        list and so happily lands exactly where an already-visible card
        sits: two waypoints close together on the same side of the frame
        seed their search from nearly the same point and both get clamped
        into the same corner, and since a freshly placed card is then
        pinned there for tuning.POPUP_POSITION_LOCK_SECONDS, the
        per-frame full layout in _composite_baked_popups cannot pull
        them apart either — they simply sit stacked on top of each other
        for the whole lock window."""
        boxes: List[Tuple[float, float, float, float]] = []
        for bp in baked_popups:
            popup = bp["popup"]
            if exclude is not None and popup is exclude:
                continue
            box = popup.get("beside_box")
            if not box:
                continue
            card_w, card_h = self.graphics.beside_card_footprint(
                popup.get("card_scale", 1.0)
            )
            boxes.append((box[0], box[1], box[0] + card_w, box[1] + card_h))
        return boxes

    def _composite_baked_popups(
        self,
        frame: np.ndarray,
        baked_popups: List[Dict],
        w: int,
        h: int,
        route_obstacles: Optional[np.ndarray],
        active_popups: Optional[List[Dict]] = None,
        total_points: int = 0,
        fps: Optional[float] = None,
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
        MAX_CONCURRENT_FLOW_POPUPS = tuning.MAX_CONCURRENT_FLOW_POPUPS

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
            self._layout_recap_popups(
                flowing_visible, w, h, route_obstacles=route_obstacles, fps=fps
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
                by = int(by + self._popup_slide_offset_y(bp))
                # ...and grows into its full size about its centre.
                grow = self._popup_enter_scale(bp)
                if grow < 0.999:
                    base = float(hud_popup.get("card_scale", 1.0))
                    full_w, full_h = self.graphics.beside_card_footprint(base)
                    now_w, now_h = self.graphics.beside_card_footprint(base * grow)
                    bx, by = int(bx + (full_w - now_w) / 2), int(by + (full_h - now_h) / 2)
                    hud_popup["card_scale"] = base * grow
                hud_popup["beside_box"] = (bx, by)
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
                    self._draw_pin(frame, wp, total_points, scale=self._pin_pop_scale(
                        wp, getattr(self, "_pop_now", 0), fps or 30))

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

    # Bounds for the highlight's close-up: a plain fixed ~300m-across crop
    # (this used to be the ONLY option) is the tightest the search may go;
    # roughly 4x that across is the widest it'll pull back to in order to
    # keep the route through the point in shot. Anything wider than that
    # stops reading as a "close-up" at all.
    _HIGHLIGHT_TIGHT_WIDTH_M = 300.0
    _HIGHLIGHT_WIDE_WIDTH_M = 1200.0

    def _fetch_highlight_image(
        self, lat: float, lng: float, output_size: Tuple[int, int],
        next_lat: Optional[float] = None, next_lon: Optional[float] = None,
    ) -> Optional[Tuple[str, Tuple[float, float, float, float]]]:
        """Fetches a fresh, higher-zoom map image centered on one lat/lng
        for the end-of-video "zoom into this place" highlight — framed by
        choose_route_focus_view so the shot shows as much of the route
        running through this point as it can, rather than a fixed ~300m
        crop that happens to catch the line or happens to cut it off
        depending on where the point sits relative to it.

        Returns (path, extent) so the caller can still project the same
        lat/lng onto this new image's pixels (for the marker/popup), or
        None (rather than raising) on any failure — a tile-download hiccup
        here shouldn't take down a render that's otherwise already
        finished."""
        try:
            from services.mapfetcher.mapfetcher import MapFetcher
            from services.mapfetcher.mapgeometry import (
                bbox_for_view, choose_route_focus_view, zoom_for_ground_width,
            )

            job_config = self._get_job_config()
            if not job_config:
                return None
            fetcher = MapFetcher(job_config=job_config)

            route_latlon = getattr(self, "_route_latlon_path", None)
            out_w, _out_h = output_size
            tight_zoom = zoom_for_ground_width(self._HIGHLIGHT_TIGHT_WIDTH_M, out_w)
            wide_zoom = zoom_for_ground_width(self._HIGHLIGHT_WIDE_WIDTH_M, out_w)
            if route_latlon:
                job_waypoints = job_config.get("waypoints") or []
                must_fit_latlon = [
                    (jw["lat"], jw.get("lng", jw.get("lon")))
                    for jw in job_waypoints
                    if jw.get("lat") is not None and jw.get("lng", jw.get("lon")) is not None
                ]
                center_lon, center_lat, zoom = choose_route_focus_view(
                    route_latlon, lat, lng, output_size,
                    min_zoom=wide_zoom, max_zoom=tight_zoom,
                    next_lat=next_lat, next_lon=next_lon,
                    must_fit_latlon=must_fit_latlon,
                )
                bbox = bbox_for_view(center_lon, center_lat, zoom, output_size)
            else:
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
