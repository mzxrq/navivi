"""The overview's cards placed freely round their pins (docs/OVERVIEW_RULES.md 8.18, approved 2026-11-27).

Every card is one given size. No card covers the route line, a pin, a panel or another card. A leader (a straight line
from a pin to the nearest point of its card) is at most OVERVIEW_CARD_MAX_LEADER_PX long, crosses or lies on no other
leader, passes under no card and over no other pin. Leaders may cross the route. A card prefers the side facing away
from its group of pins. `place_cards` returns None when it finds no such arrangement at that size.

The search is deterministic and bounded by counts (never by time: the same inputs must give the same video)."""
import math
from typing import List, Optional, Sequence, Tuple

import numpy as np

from services import tuning

Point = Tuple[float, float]
Box = Tuple[float, float, float, float]

_CELL = 4  # the occupancy grid's resolution, px
_STEP = 8  # px between the card spots tried
_TRIES = 40  # spots tried for one pin before the order is changed
_RESTARTS = 10  # orders tried at one size
_SAME_PIN_PX = 26  # leaders from pins this close may meet where they start
_OWN_PIN_PX = 45  # a leader's start, never tested against other pins
_SHORT_LEADER_PX = 65  # a leader this short is not tested against other pins at all


def _point_to_segment(p, a, b) -> np.ndarray:
    ab = b - a
    n = (ab ** 2).sum(-1)
    t = np.clip(((p - a) * ab).sum(-1) / np.where(n == 0, 1, n), 0, 1)
    v = p - a - t[..., None] * ab
    return np.hypot(v[..., 0], v[..., 1])


def _side(a, b, c) -> np.ndarray:
    return (b[..., 0] - a[..., 0]) * (c[..., 1] - a[..., 1]) - (b[..., 1] - a[..., 1]) * (c[..., 0] - a[..., 0])


def _proper_cross(p1, q1, p2, q2) -> np.ndarray:
    return (_side(p1, q1, p2) * _side(p1, q1, q2) < 0) & (_side(p2, q2, p1) * _side(p2, q2, q1) < 0)


def _crosses(p1: np.ndarray, q1: np.ndarray, p2: np.ndarray, q2: np.ndarray) -> np.ndarray:
    """Which of the leaders p1-q1[k] cross, or run within a few px of, the leader p2-q2. Leaders from pins that are
    close together anyway are compared only away from their starts."""
    gap = math.dist(p1, p2)
    p1 = np.broadcast_to(p1, q1.shape)
    hit = _proper_cross(p1, q1, p2, q2) if gap >= _SAME_PIN_PX else np.zeros(len(q1), bool)
    compared = np.ones(len(q1), bool)
    clear = 2.5 * _SAME_PIN_PX
    if gap < clear:
        d2 = math.dist(p2, q2)
        if d2 <= clear:
            return hit
        d1 = np.hypot(*(q1 - p1).T)
        compared = d1 > clear
        p2 = p2 + (q2 - p2) * clear / d2
        p1 = p1 + (q1 - p1) * (clear / np.where(compared, d1, 1))[:, None]
        hit |= compared & _proper_cross(p1, q1, p2, q2)
    near = np.minimum.reduce([_point_to_segment(p1, p2, q2), _point_to_segment(q1, p2, q2),
                              _point_to_segment(p2, p1, q1), _point_to_segment(q2, p1, q1)]) < 6
    return hit | (compared & near)


def crossing(p1: Point, q1: Point, p2: Point, q2: Point) -> bool:
    """Whether the leaders p1-q1 and p2-q2 cross, or run within a few px of each other."""
    p1, q1, p2, q2 = (np.array(v, float) for v in (p1, q1, p2, q2))
    return bool(_crosses(p1, q1[None], p2, q2)[0])


def _under(pin: np.ndarray, end: np.ndarray, box: np.ndarray) -> np.ndarray:
    """Which leaders pin-end enter which boxes (grown 3 px), broadcast over either."""
    t0, t1, outside = 0.0, 0.98, False
    for k in (0, 1):
        p, d = pin[..., k], end[..., k] - pin[..., k]
        lo, hi = box[..., k] - 3, box[..., k + 2] + 3
        flat = np.abs(d) < 1e-9
        div = np.where(flat, 1.0, d)
        a, b = (lo - p) / div, (hi - p) / div
        t0 = np.maximum(t0, np.where(flat, 0.0, np.minimum(a, b)))
        t1 = np.minimum(t1, np.where(flat, 0.98, np.maximum(a, b)))
        outside = outside | (flat & ((p <= lo) | (p >= hi)))
    return (t0 < t1) & ~outside


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


def place_cards(
    pins: Sequence[Point], w: int, h: int, reserved: Optional[Sequence[Box]], route: Optional[np.ndarray],
    marker_radius: float, card_w: int, card_h: int, others: Sequence[Point] = (),
) -> Optional[List[Box]]:
    """One card_w x card_h box per pin, in pin order, or None. `reserved` are the frame's panels; `route` the
    route line's pixel points, dense enough that none of it hides between two; `others` the pins that get no card
    here, which cards and leaders keep off all the same."""
    pins = [(float(x), float(y)) for x, y in pins]
    if not pins:
        return []
    groups = _groups(pins, tuning.OVERVIEW_CARD_GROUP_LINK_PX * h / 1080)
    if len(groups[0]) > tuning.OVERVIEW_CARD_FREE_MAX_PINS:  # the biggest group comes first
        return None
    scale, r = h / 1080, float(marker_radius)
    gap = tuning.OVERVIEW_CARD_GAP_PX * scale
    grid = _Grid.empty(w, h)
    for box in reserved or ():
        grid.stamp(*box)
    if route is not None:
        pad = tuning.OVERVIEW_CARD_ROUTE_PAD_PX * scale
        for x, y in np.asarray(route, dtype=float):
            grid.stamp(x - pad, y - pad, x + pad, y + pad)
    pad = 6 * scale
    extra = np.array([(float(x), float(y)) for x, y in others]).reshape(-1, 2)
    for x, y in pins + extra.tolist():  # a teardrop stands above its point
        grid.stamp(x - 1.2 * r - pad, y - 3.0 * r - pad, x + 1.2 * r + pad, y + 0.5 * r + pad)

    at = np.array(pins)
    heads = at - (0, 1.8 * r)
    middle, alone = np.zeros_like(at), np.zeros(len(pins), bool)
    for group in groups:
        middle[group], alone[group] = at[group].mean(0), len(group) == 1
    spots = []
    for i, pin in enumerate(at):
        apart = extra[np.hypot(*(extra - pin).T) >= _SAME_PIN_PX]  # one on its own spot cannot be avoided
        keep_off = np.vstack([np.delete(heads, i, 0), apart - (0, 1.8 * r)])
        boxes, ends = _spots(grid, pin, keep_off, r, w, h, int(card_w), int(card_h))
        if not len(boxes):
            return None
        spots.append(_preferred(pin, None if alone[i] else pin - middle[i], boxes, ends, scale))

    order = sorted(range(len(pins)), key=lambda i: len(spots[i][0]))  # the most hemmed-in pin first
    for _ in range(_RESTARTS):
        placed, stuck = _deal(at, spots, order, gap)
        if placed is not None:
            return [tuple(float(v) for v in placed[i]) for i in range(len(pins))]
        order.remove(stuck)
        order.insert(0, stuck)
    return None


def _spots(grid: _Grid, pin: np.ndarray, others: np.ndarray, r: float, w: int, h: int, cw: int, ch: int):
    """(boxes, leader ends) of every clear card spot within a leader's reach of `pin` whose leader passes over none
    of the `others` pin heads."""
    reach = tuning.OVERVIEW_CARD_MAX_LEADER_PX * h / 1080
    margin = tuning.OVERVIEW_CARD_EDGE_PX * h / 1080
    px, py = pin
    xs = np.arange(max(margin, px - reach - cw), min(w - margin - cw, px + reach) + 1, _STEP)
    ys = np.arange(max(margin, py - reach - ch), min(h - margin - ch, py + reach) + 1, _STEP)
    x, y = (v.ravel() for v in np.meshgrid(xs, ys))
    ends = np.stack([np.clip(px, x, x + cw), np.clip(py, y, y + ch)], 1)
    length = np.hypot(ends[:, 0] - px, ends[:, 1] - py)
    keep = length <= reach
    keep[keep] = grid.clear(x[keep], y[keep], cw, ch)
    x, y, ends, length = x[keep], y[keep], ends[keep], length[keep]
    start = pin + (ends - pin) * np.minimum(1, _OWN_PIN_PX / np.maximum(length, 1e-9))[:, None]
    over = np.zeros(len(length), bool)
    for head in others:
        over |= (length > _SHORT_LEADER_PX) & (_point_to_segment(head, start, ends) < r)
    return np.stack([x, y, x + cw, y + ch], 1)[~over], ends[~over]


def _preferred(pin: np.ndarray, outward: Optional[np.ndarray], boxes: np.ndarray, ends: np.ndarray, scale: float):
    """The spots best first: the shortest leader, plus a charge for pointing back toward the group's middle."""
    cost = np.hypot(*(ends - pin).T)
    if outward is not None and np.hypot(*outward) >= 1:
        toward = (boxes[:, :2] + boxes[:, 2:]) / 2 - pin
        cos = (toward @ outward) / (np.hypot(*toward.T) * np.hypot(*outward) + 1e-9)
        cost = cost + tuning.OVERVIEW_CARD_OUTWARD_PX * scale * (1 - cos)
    order = np.argsort(cost, kind="stable")
    return boxes[order], ends[order]


def _deal(pins: np.ndarray, spots: list, order: List[int], gap: float) -> Tuple[Optional[dict], Optional[int]]:
    """({pin: box}, None) with each pin, in `order`, on its best spot that leaves every later pin a spot; or
    (None, the first pin left with none)."""
    alive = [np.ones(len(boxes), bool) for boxes, _ in spots]
    placed: dict = {}
    for i in order:
        for c in np.flatnonzero(alive[i])[:_TRIES]:
            box, end = spots[i][0][c], spots[i][1][c]
            left = {}
            for k in order:
                if k in placed or k == i:
                    continue
                mask = alive[k].copy()
                live = np.flatnonzero(mask)
                boxes, ends = spots[k][0][live], spots[k][1][live]
                ok = ~((boxes[:, 0] < box[2] + gap) & (box[0] < boxes[:, 2] + gap)
                       & (boxes[:, 1] < box[3] + gap) & (box[1] < boxes[:, 3] + gap))
                ok &= ~_under(pins[k], ends, box)
                ok &= ~_under(pins[i], end, boxes)
                mask[live] = ok & ~_crosses(pins[k], ends, pins[i], end)
                if not mask.any():
                    break
                left[k] = mask
            else:
                placed[i] = box
                for k, mask in left.items():
                    alive[k] = mask
                break
        else:
            return None, i
    return placed, None
