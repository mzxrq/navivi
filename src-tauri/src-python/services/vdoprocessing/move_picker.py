"""Picks an attraction photo's second shot from what the photo shows, instead
of at random (ATTRACTION_SECOND_SHOT = "auto").

CPU only: the Depth-Anything map the 3D photo already uses, plus edge
density. Each candidate move is scored from a few measurements; near-ties
are broken by a seed from the photo, so a rerun picks the same move.
"""

import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from services.logger.logger import setup_logger

logger = setup_logger("MovePicker")

_SIZE = 384
_TIE = 0.05


@dataclass
class Features:
    cx: float          # detail centre, -1 left .. 1 right
    cy: float          # detail centre, -1 top .. 1 bottom
    spread_x: float    # detail spread, 0 compact .. ~0.6 everywhere
    spread_y: float
    tall: float        # vertical edges over horizontal ones
    sky: float         # share of the photo that is sky
    open_view: float   # 0..1, sky plus far land/sea: a view, not a subject
    path: float        # 0..1, a way leading into the picture
    path_x: float      # where it leads, -1 left .. 1 right
    busy: Dict[str, float]  # edge detail along each border vs. the whole photo


def _small(photo_bgr: np.ndarray) -> np.ndarray:
    h, w = photo_bgr.shape[:2]
    s = _SIZE / max(h, w)
    return cv2.resize(photo_bgr, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)


def measure(photo_bgr: np.ndarray, depth: np.ndarray) -> Features:
    """depth: 0 far .. 1 near, any size."""
    img = _small(photo_bgr)
    h, w = img.shape[:2]
    depth = cv2.resize(depth.astype(np.float32), (w, h), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    edges = cv2.GaussianBlur(np.hypot(gx, gy), (0, 0), 3)

    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    nx, ny = xs / (w - 1) * 2 - 1, ys / (h - 1) * 2 - 1

    texture = cv2.GaussianBlur(edges, (0, 0), 6)
    sky = (depth < 0.08) & (texture < np.percentile(texture, 40)) & (ny < 0.2)

    # Interest: what stands out (spectral-residual saliency), weighted to the
    # middle (where people frame the subject); the nearest things are usually
    # ground or a cut-off foreground branch.
    centre = np.exp(-(nx ** 2 + ny ** 2) / 0.6)
    interest = _saliency(gray) * centre * (1 - 0.7 * (depth > 0.8)) * ~sky
    interest[ny > 0.85] *= 0.3
    interest = np.maximum(interest - np.percentile(interest, 80), 0)
    mass = interest.sum() + 1e-6
    cx = float((interest * nx).sum() / mass)
    cy = float((interest * ny).sum() / mass)
    spread_x = float(np.sqrt((interest * (nx - cx) ** 2).sum() / mass))
    spread_y = float(np.sqrt((interest * (ny - cy) ** 2).sum() / mass))
    tall = float(np.abs(gx).sum() / (np.abs(gy).sum() + 1e-6))
    open_view = float(np.clip(sky.mean() + ((depth < 0.2) & ~sky).mean() - 0.25, 0, 1))

    # Path: in the central half, a far opening that isn't sky, with near
    # ground climbing into it - a street, a corridor, steps, a gate.
    far = (1 - depth) * ~sky
    col_far = far[int(h * 0.35):int(h * 0.75)].mean(axis=0)
    col_far = np.convolve(col_far, np.ones(w // 8) / (w // 8), mode="same")
    lo, hi = w // 4, w - w // 4
    peak = lo + int(np.argmax(col_far[lo:hi]))
    path_x = peak / (w - 1) * 2 - 1
    sides = np.concatenate([col_far[: w // 6], col_far[-w // 6:]]).mean()
    c0, c1 = max(0, peak - w // 12), min(w, peak + w // 12)
    ground = depth[int(h * 0.8):, w // 3:w - w // 3].mean() - depth[int(h * 0.4):int(h * 0.6), c0:c1].mean()
    path = float(np.clip((col_far[peak] - sides) * 2.5, 0, 1) * np.clip(ground * 2.5, 0, 1))

    whole = edges.mean() + 1e-6
    bx, by = max(2, w // 12), max(2, h // 12)
    busy = {
        "left": float(edges[:, :bx].mean() / whole), "right": float(edges[:, -bx:].mean() / whole),
        "top": float(edges[:by].mean() / whole), "bottom": float(edges[-by:].mean() / whole),
    }
    return Features(cx, cy, spread_x, spread_y, tall, float(sky.mean()), open_view, path, path_x, busy)


def _saliency(gray: np.ndarray) -> np.ndarray:
    """Spectral residual saliency (Hou & Zhang 2007), 0..1, gray's size."""
    small = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA)
    spec = np.fft.fft2(small)
    log_amp = np.log(np.abs(spec) + 1e-6)
    residual = log_amp - cv2.blur(log_amp, (3, 3))
    sal = np.abs(np.fft.ifft2(np.exp(residual + 1j * np.angle(spec)))) ** 2
    sal = cv2.GaussianBlur(sal.astype(np.float32), (0, 0), 2.5)
    sal = cv2.resize(sal, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_LINEAR)
    return sal / (sal.max() + 1e-9)


def score(move: str, f: Features) -> Tuple[float, str]:
    """(score, why) for one move."""
    def edge(side: str) -> float:
        return max(0.0, f.busy[side] - 1.3) * 0.3

    spread = max(f.spread_x, f.spread_y)
    if move == "closein":
        s = 0.45 + 0.35 * (1 - min(1, abs(f.cx) * 3)) + 0.8 * (0.35 - spread) - 0.3 * f.open_view
        return s, f"subject x {f.cx:+.2f}, spread {spread:.2f}, open view {f.open_view:.2f}"
    if move == "closeout":
        s = 0.3 + 0.8 * max(0.0, spread - 0.35)
        return s, f"detail spread {spread:.2f}"
    if move in ("closepanleft", "closepanright"):
        side = 1 if move == "closepanright" else -1
        s = (0.3 + 1.4 * f.cx * side + 0.6 * f.open_view + max(0.0, f.spread_x - f.spread_y)
             - edge("right" if side > 0 else "left"))
        return s, f"subject x {f.cx:+.2f}, open view {f.open_view:.2f}"
    if move == "closepanup":
        s = (0.2 + 0.5 * min(1.0, max(0.0, f.tall - 1.0)) + 1.2 * max(0.0, -f.cy)
             - edge("top") - 0.6 * f.sky)
        return s, f"vertical/horizontal edges {f.tall:.2f}, subject y {f.cy:+.2f}, sky {f.sky:.2f}"
    if move == "closepandown":
        s = 0.1 + 1.2 * max(0.0, f.cy - 0.1) - edge("bottom")
        return s, f"subject y {f.cy:+.2f}"
    if move in ("walkthrough", "walkthroughleft", "walkthroughright"):
        # The turns walk in, then look toward the side the subject is on.
        turn = {"walkthroughleft": -1, "walkthroughright": 1}.get(move, 0)
        s = 0.15 + 1.0 * f.path - 0.4 * f.open_view
        if turn:
            s = s - 0.2 + 1.2 * max(0.0, f.cx * turn - 0.15) - edge("left" if turn < 0 else "right")
        return s, f"path {f.path:.2f} at x {f.path_x:+.2f}, subject x {f.cx:+.2f}"
    return 0.0, "no rule"


def pick(candidates: Sequence[str], f: Features, seed: str = "") -> Tuple[Optional[str], List[Tuple[str, float, str]]]:
    """(best move, every candidate's (move, score, why) best first)."""
    ranked = sorted(((m, *score(m, f)) for m in candidates), key=lambda r: -r[1])
    if not ranked:
        return None, ranked
    top = [r[0] for r in ranked if r[1] >= ranked[0][1] - _TIE]
    return random.Random(f"{seed}|auto").choice(sorted(top)), ranked


def pick_for_photo(photo_path: str, candidates: Sequence[str], seed: str = "") -> Optional[str]:
    """Best move for the photo file, or None when it can't be read or measured."""
    from services.vdoprocessing.clip_qc import read_image
    from services.vdoprocessing.parallax_generator import estimate_depth

    try:
        photo = read_image(photo_path)
        if photo is None:
            return None
        small = _small(photo)
        f = measure(small, estimate_depth(small))
    except Exception as exc:
        logger.warning("Move picker failed for %s (%s) - falling back to random.", photo_path, exc)
        return None
    move, ranked = pick(candidates, f, seed)
    logger.info("Auto move for %s: %s (%s)", photo_path, move,
                "; ".join(f"{m} {s:.2f} [{why}]" for m, s, why in ranked[:3]))
    return move
