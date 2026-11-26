"""The overview's cards on a circle round each group of pins (docs/OVERVIEW_RULES.md 8.18, approved 2026-11-26).

Every card is one given size. No card covers the route line, a pin, a panel or another card; no leader (a straight
line from a pin to the nearest point of its card) crosses or lies on another leader, or passes under a card. Leaders
may cross the route. `circle_layout` returns None when it finds no such arrangement at that size.

The search is deterministic and bounded by counts (never by time: the same inputs must give the same video)."""
import math
from typing import Iterator, List, Optional, Sequence, Tuple

import numpy as np
from scipy.optimize import linear_sum_assignment

from services import tuning

Point = Tuple[float, float]
Box = Tuple[float, float, float, float]

_CELL = 4  # the occupancy grid's resolution, px
_ANGLES = np.radians(np.arange(0, 360, 2))
_RADIUS_STEP = 10.0  # how far a card steps out along its angle until it is clear
_CIRCLE_STEP = 24  # px between the circle radii tried
_LARGEST_RADIUS = 700
# A true circle first (cards may step out where something is in the way), then one a little wider and looser.
_SLACKS = (0.12, 0.3)
_SHIFTS = ((0, 0), (0, 50), (-60, 30), (60, 30), (0, 100))  # the circle may sit a little off the pins' middle
_STRETCHES = (1.0, 1.15)
_PICKS = 16  # card sets tried per circle
_DEALS = 150  # card sets dealt out to the pins per group before giving up at this size
_OTHER_CIRCLES = 6  # further circles tried for one group when a later group cannot be placed
_SAME_PIN_PX = 26  # leaders from pins this close may meet where they start


def _point_to_segment(p: Point, a: Point, b: Point) -> float:
    ax, ay = b[0] - a[0], b[1] - a[1]
    n = ax * ax + ay * ay
    t = 0.0 if not n else min(1.0, max(0.0, ((p[0] - a[0]) * ax + (p[1] - a[1]) * ay) / n))
    return math.hypot(p[0] - a[0] - t * ax, p[1] - a[1] - t * ay)


def _proper_cross(p1: Point, q1: Point, p2: Point, q2: Point) -> bool:
    def side(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return side(p1, q1, p2) * side(p1, q1, q2) < 0 and side(p2, q2, p1) * side(p2, q2, q1) < 0


def crossing(p1: Point, q1: Point, p2: Point, q2: Point) -> bool:
    """Whether the leaders p1-q1 and p2-q2 cross, or run within a few px of each other. Leaders from pins that are
    close together anyway are compared only away from their starts."""
    gap = math.dist(p1, p2)
    if gap >= _SAME_PIN_PX and _proper_cross(p1, q1, p2, q2):
        return True
    if gap < 2.5 * _SAME_PIN_PX:
        def away(p, q):
            d = math.dist(p, q)
            if d <= 2.5 * _SAME_PIN_PX:
                return None
            t = 2.5 * _SAME_PIN_PX / d
            return p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
        p1, p2 = away(p1, q1), away(p2, q2)
        if p1 is None or p2 is None:
            return False
        if _proper_cross(p1, q1, p2, q2):
            return True
    return min(_point_to_segment(p1, p2, q2), _point_to_segment(q1, p2, q2),
               _point_to_segment(p2, p1, q1), _point_to_segment(q2, p1, q1)) < 6


def _under(pin: Point, end: Point, box: Box) -> bool:
    """The leader enters `box` (grown 3 px)."""
    t0, t1 = 0.0, 0.98
    for p, d, lo, hi in ((pin[0], end[0] - pin[0], box[0] - 3, box[2] + 3),
                         (pin[1], end[1] - pin[1], box[1] - 3, box[3] + 3)):
        if abs(d) < 1e-9:
            if p <= lo or p >= hi:
                return False
            continue
        a, b = sorted(((lo - p) / d, (hi - p) / d))
        t0, t1 = max(t0, a), min(t1, b)
    return t0 < t1


def _nearest(pin: Point, box: Box) -> Point:
    return min(max(pin[0], box[0]), box[2]), min(max(pin[1], box[1]), box[3])


def _touches(box: Box, others: Sequence[Box], gap: float) -> bool:
    return any(box[0] < o[2] + gap and o[0] < box[2] + gap and box[1] < o[3] + gap and o[1] < box[3] + gap
               for o in others)


class _Grid:
    """What a card must keep off, as a grid of occupied cells."""

    def __init__(self, cells: np.ndarray):
        self.cells = cells
        self._sums: Optional[np.ndarray] = None

    @classmethod
    def empty(cls, w: int, h: int) -> "_Grid":
        return cls(np.zeros((h // _CELL + 1, w // _CELL + 1), dtype=np.int32))

    def stamp(self, x0: float, y0: float, x1: float, y1: float) -> None:
        rows, cols = self.cells.shape
        c0, r0 = max(0, int(x0 // _CELL)), max(0, int(y0 // _CELL))
        c1, r1 = min(cols, int(math.ceil(x1 / _CELL))), min(rows, int(math.ceil(y1 / _CELL)))
        if c1 > c0 and r1 > r0:
            self.cells[r0:r1, c0:c1] = 1
            self._sums = None

    def clear(self, x: np.ndarray, y: np.ndarray, cw: float, ch: float) -> np.ndarray:
        """Which of the cw x ch boxes at (x, y) - all inside the frame - cover no occupied cell."""
        if self._sums is None:
            self._sums = np.pad(self.cells.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
        c0, r0 = (x // _CELL).astype(int), (y // _CELL).astype(int)
        c1, r1 = np.ceil((x + cw) / _CELL).astype(int), np.ceil((y + ch) / _CELL).astype(int)
        s = self._sums
        return s[r1, c1] - s[r0, c1] - s[r1, c0] + s[r0, c0] == 0


class _Search:
    def __init__(self, w: int, h: int, cw: int, ch: int):
        self.w, self.h, self.cw, self.ch = w, h, cw, ch
        self.gap = tuning.OVERVIEW_CARD_GAP_PX * h / 1080
        self.margin = tuning.OVERVIEW_CARD_EDGE_PX * h / 1080

    # --- spots on one circle -------------------------------------------
    def _first_clear(self, grid: _Grid, centre: Point, stretch: float, radii: np.ndarray) -> List[Tuple[float, Box]]:
        """Per angle, the first of `radii` at which a card is clear: [(angle, box)]."""
        x = centre[0] + radii[None, :] * stretch * np.cos(_ANGLES)[:, None] - self.cw / 2
        y = centre[1] + radii[None, :] * np.sin(_ANGLES)[:, None] - self.ch / 2
        inside = ((x >= self.margin) & (y >= self.margin)
                  & (x + self.cw <= self.w - self.margin) & (y + self.ch <= self.h - self.margin))
        ok = np.zeros_like(inside)
        ok[inside] = grid.clear(x[inside], y[inside], self.cw, self.ch)
        out = []
        for a in np.flatnonzero(ok.any(axis=1)):
            r = int(np.argmax(ok[a]))
            x0, y0 = float(x[a, r]), float(y[a, r])
            out.append((float(_ANGLES[a]), (x0, y0, x0 + self.cw, y0 + self.ch)))
        return out

    def _spread(self, inner, outer, need: int) -> List[List[Box]]:
        """Up to _PICKS sets of `need` separate boxes, evenly spaced round the circle: from `inner` first, topped
        up from the `outer` ring only for what does not fit there."""
        def pick(angle_gap: float, start: int) -> List[Box]:
            chosen: List[Box] = []
            last = 0.0
            for k in range(len(inner)):
                a, box = inner[(start + k) % len(inner)]
                if (chosen and (a - last) % (2 * math.pi) < angle_gap) or _touches(box, chosen, self.gap):
                    continue
                chosen.append(box)
                last = a
                if len(chosen) == need:
                    return chosen
            for k in range(len(outer)):
                box = outer[(start * 3 + k * 7) % len(outer)][1]
                if not _touches(box, chosen, self.gap):
                    chosen.append(box)
                    if len(chosen) == need:
                        break
            return chosen

        count = max(len(inner), 1)
        starts = range(0, count, max(1, count // 16))
        if all(len(pick(0.0, s)) < need for s in starts):  # as tightly as they go, they do not fit
            return []
        best: List[List[Box]] = []
        for angle_gap in np.radians(np.arange(360 / need, -1, -3)):
            for start in starts:
                got = pick(float(angle_gap), start)
                if len(got) == need and got not in best:
                    best.append(got)
            if len(best) >= _PICKS:
                break
        return best[:_PICKS]

    # --- which card each pin gets --------------------------------------
    def _deal(self, pins: List[Point], boxes: List[Box], done: List) -> Tuple[List[Box], int]:
        """(each pin's box, clashing pairs left): shortest squared leaders or the pins' own order round the circle,
        whichever clashes least, then swaps until nothing clashes."""
        n = len(pins)
        ends = [[_nearest(p, b) for b in boxes] for p in pins]
        cost = np.array([[math.dist(pins[i], ends[i][b]) ** 2 for b in range(n)] for i in range(n)])
        # under a card of this circle, or tangled with a group already placed: fixed per pin and spot
        alone = [[sum(_under(pins[i], ends[i][b], boxes[c]) for c in range(n) if c != b)
                  + sum(_under(pins[i], ends[i][b], box) + _under(op, oq, boxes[b])
                        + crossing(pins[i], ends[i][b], op, oq) for op, oq, box in done)
                  for b in range(n)] for i in range(n)]
        seen: dict = {}

        def total(assign: List[int]) -> int:
            bad = sum(alone[i][assign[i]] for i in range(n))
            for i in range(n):
                for j in range(i + 1, n):
                    key = (i, assign[i], j, assign[j])
                    if key not in seen:
                        seen[key] = crossing(pins[i], ends[i][assign[i]], pins[j], ends[j][assign[j]])
                    bad += seen[key]
            return bad

        _, cheapest = linear_sum_assignment(cost)
        mid = np.mean(pins, axis=0)
        pin_order = sorted(range(n), key=lambda i: math.atan2(pins[i][1] - mid[1], pins[i][0] - mid[0]))
        box_order = sorted(range(n), key=lambda b: math.atan2((boxes[b][1] + boxes[b][3]) / 2 - mid[1],
                                                              (boxes[b][0] + boxes[b][2]) / 2 - mid[0]))
        starts = [list(cheapest)]
        for k in range(n):
            turned = [0] * n
            for at, i in enumerate(pin_order):
                turned[i] = box_order[(at + k) % n]
            starts.append(turned)
        bad, _, assign = min((total(s), float(sum(cost[i][s[i]] for i in range(n))), s) for s in starts)
        improved = True
        while bad and improved:
            improved = False
            for i in range(n):
                for j in range(i + 1, n):
                    assign[i], assign[j] = assign[j], assign[i]
                    now = total(assign)
                    if now < bad:
                        bad, improved = now, True
                    else:
                        assign[i], assign[j] = assign[j], assign[i]
        return [boxes[assign[i]] for i in range(n)], bad

    def _clashing(self, pins: List[Point], boxes: List[Box], done: List) -> List[int]:
        """The pins whose leader (boxes[i] is pin i's card) is part of a clash, once per clash."""
        n, out = len(pins), []
        ends = [_nearest(pins[i], boxes[i]) for i in range(n)]
        for i in range(n):
            out += [i for j in range(n) if j != i and _under(pins[i], ends[i], boxes[j])]
            out += [i for j in range(i + 1, n) if crossing(pins[i], ends[i], pins[j], ends[j])]
            out += [i for op, oq, box in done if _under(pins[i], ends[i], box) or _under(op, oq, boxes[i])
                    or crossing(pins[i], ends[i], op, oq)]
        return out

    def _repair(self, pins: List[Point], boxes: List[Box], done: List, spots: List[Box]) -> Tuple[List[Box], int]:
        """Moves single clashing cards to another spot of the circle while that leaves fewer clashes."""
        boxes = list(boxes)
        bad = self._clashing(pins, boxes, done)
        improved = True
        while bad and improved:
            improved = False
            for i in sorted(set(bad)):
                for spot in sorted(spots, key=lambda b: math.dist(pins[i], _nearest(pins[i], b))):
                    if _touches(spot, boxes[:i] + boxes[i + 1:], self.gap):
                        continue
                    was, boxes[i] = boxes[i], spot
                    now = self._clashing(pins, boxes, done)
                    if len(now) < len(bad):
                        bad, improved = now, True
                        break
                    boxes[i] = was
                if not bad:
                    break
        return boxes, len(bad)

    # --- the groups ------------------------------------------------------
    def circles(self, pins: List[Point], grid: _Grid, done: List) -> Iterator[List[Box]]:
        """Clean arrangements of one group's cards, the roundest circles first."""
        centre = np.mean(pins, axis=0)
        reach = max(math.dist(centre, p) for p in pins)
        start = int(reach + max(self.cw, self.ch) / 2 + 20)
        dealt_out = 0
        for slack in _SLACKS:
            for shift in _SHIFTS:
                for stretch in _STRETCHES:
                    for radius in range(start, _LARGEST_RADIUS, _CIRCLE_STEP):
                        at = (centre[0] + shift[0], centre[1] + shift[1])
                        radii = np.arange(radius, radius * (1 + slack) + 1, _RADIUS_STEP)
                        inner = self._first_clear(grid, at, stretch, radii)
                        outer = []
                        if slack > _SLACKS[0]:
                            far = radius * (1 + slack) + max(self.cw, self.ch)
                            outer = self._first_clear(
                                grid, at, stretch, np.arange(far, far + max(self.cw, self.ch), 14.0))
                        if len(inner) + len(outer) < len(pins):
                            continue
                        for boxes in self._spread(inner, outer, len(pins))[:4]:
                            if dealt_out >= _DEALS:
                                return
                            dealt_out += 1
                            dealt, bad = self._deal(pins, boxes, done)
                            if 0 < bad <= 3:
                                dealt, bad = self._repair(pins, dealt, done, [b for _, b in inner + outer])
                            away = [math.dist(centre, ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)) for b in dealt]
                            if not bad and max(away) <= tuning.OVERVIEW_CARD_CIRCLE_ROUNDNESS * min(away):
                                yield dealt
                                break  # the next radius gives a different circle

    def place(self, pins: List[Point], groups: List[List[int]], base: _Grid) -> Optional[List[Box]]:
        """Every group's circle, in `groups` order, trying other circles of a group when a later one has no room."""
        def fill(k: int, grid: _Grid, boxes: List, lines: List) -> Optional[List[Box]]:
            if k == len(groups):
                return boxes
            group = groups[k]
            for tried, got in enumerate(self.circles([pins[i] for i in group], grid, lines)):
                here, placed, now = _Grid(grid.cells.copy()), list(boxes), list(lines)
                for i, box in zip(group, got):
                    placed[i] = box
                    here.stamp(box[0] - self.gap, box[1] - self.gap, box[2] + self.gap, box[3] + self.gap)
                    now.append((pins[i], _nearest(pins[i], box), box))
                out = fill(k + 1, here, placed, now)
                if out is not None or tried >= _OTHER_CIRCLES:
                    return out
            return None

        return fill(0, base, [None] * len(pins), [])


def densify(path, step: float = 6.0) -> np.ndarray:
    """A drawn route resampled every `step` px: a ferry leg is one long segment whose own points are only its ends,
    so a card on the middle of it counted as covering no route."""
    path = np.asarray(path, dtype=float)
    if len(path) < 2:
        return path
    along = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(path, axis=0).T))])
    at = np.append(np.arange(0.0, along[-1], step), along[-1])
    return np.column_stack([np.interp(at, along, path[:, i]) for i in (0, 1)])


def _groups(pins: List[Point], link: float) -> List[List[int]]:
    """Pins chained together by gaps under `link`, the biggest group first."""
    left, out = list(range(len(pins))), []
    while left:
        group, queue = [], [left.pop(0)]
        while queue:
            i = queue.pop()
            group.append(i)
            near = [j for j in left if math.dist(pins[i], pins[j]) < link]
            left = [j for j in left if j not in near]
            queue += near
        out.append(sorted(group))
    return sorted(out, key=len, reverse=True)


def circle_layout(
    pins: Sequence[Point], w: int, h: int, reserved: Optional[Sequence[Box]], route: Optional[np.ndarray],
    marker_radius: float, card_w: int, card_h: int,
) -> Optional[List[Box]]:
    """One card_w x card_h box per pin, in pin order, or None. `reserved` are the frame's panels; `route` the
    route line's pixel points, dense enough that none of it hides between two (and any other pins to keep off)."""
    pins = [(float(x), float(y)) for x, y in pins]
    if not pins:
        return []
    scale = h / 1080
    base = _Grid.empty(w, h)
    for box in reserved or ():
        base.stamp(*box)
    if route is not None:
        pad = tuning.OVERVIEW_CARD_ROUTE_PAD_PX * scale
        for x, y in np.asarray(route, dtype=float):
            base.stamp(x - pad, y - pad, x + pad, y + pad)
    r, pad = float(marker_radius), 6 * scale
    for x, y in pins:  # a teardrop stands above its point
        base.stamp(x - 1.2 * r - pad, y - 3.0 * r - pad, x + 1.2 * r + pad, y + 0.5 * r + pad)
    search = _Search(w, h, int(card_w), int(card_h))
    groups = _groups(pins, tuning.OVERVIEW_CARD_GROUP_LINK_PX * scale)
    if len(groups[0]) > tuning.OVERVIEW_CARD_CIRCLE_MAX_PINS:  # the biggest group comes first
        return None
    for order in (groups, groups[::-1]) if len(groups) > 1 else (groups,):
        boxes = search.place(pins, order, base)
        if boxes is not None:
            return boxes
    return None
