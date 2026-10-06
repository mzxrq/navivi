"""The user's own image as a map pin (settings.routeMarker / waypoint customMarker).

Shared by the 2D renderer (cv2 frames) and the pydeck leg clips (IconLayer data URLs).
A marker value is "" (the built-in teardrop), "/defaults/markers/*.svg" (the editor's
bundled presets: the video keeps its teardrop for those) or a path to the user's file.
Anything missing or unreadable resolves to None, so the caller falls back to the teardrop.
"""

from __future__ import annotations

import base64
import os
import threading
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

from services.logger.logger import setup_logger

logger = setup_logger("PinImage")

SPRITE_MAX_PX = 256
MAX_FILE_BYTES = 25 * 1024 * 1024
RASTER_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
# The pydeck pins are 384x512 images (pedestrian.py's teardrop); an image pin is
# composited onto the same canvas so the layer's size and anchor code stay as they are.
DECK_CANVAS = (384, 512)

_ALPHA_SOLID = 250
_sprites: Dict[Tuple[str, int, int], Optional["PinSprite"]] = {}
_warned: set = set()


class PinSprite:
    """A prepared pin image (BGRA, longest side <= SPRITE_MAX_PX) plus its resized copies."""

    def __init__(self, bgra: np.ndarray):
        self.bgra = bgra
        self._fitted: Dict[Tuple[int, int], np.ndarray] = {}

    def fitted(self, box_w: int, box_h: int) -> np.ndarray:
        """The sprite scaled to fit inside box_w x box_h, keeping its proportions."""
        key = (max(1, int(box_w)), max(1, int(box_h)))
        cached = self._fitted.get(key)
        if cached is not None:
            return cached
        h, w = self.bgra.shape[:2]
        k = min(key[0] / w, key[1] / h)
        size = (max(1, round(w * k)), max(1, round(h * k)))
        out = cv2.resize(self.bgra, size, interpolation=cv2.INTER_AREA if k < 1 else cv2.INTER_LINEAR)
        if len(self._fitted) > 200:  # a pin popping in asks for many sizes
            self._fitted.clear()
        self._fitted[key] = out
        return out


def is_builtin_marker(value) -> bool:
    """"" and the editor's bundled presets are not the user's image."""
    return not isinstance(value, str) or not value.strip() or value.strip().startswith("/defaults/")


def resolve_marker_path(value, base_dir: Optional[str] = None) -> Optional[str]:
    """The user's marker file as an absolute path, or None (built-in value, missing file)."""
    if is_builtin_marker(value):
        return None
    path = os.path.expanduser(value.strip())
    if not os.path.isabs(path) and base_dir:
        path = os.path.join(base_dir, path)
    path = os.path.abspath(path)
    return path if os.path.isfile(path) else None


def marker_for(waypoint: Optional[dict], settings: Optional[dict], base_dir: Optional[str] = None) -> Optional[str]:
    """The pin image for one stop: its own customMarker, else the project's routeMarker."""
    own = resolve_marker_path((waypoint or {}).get("customMarker"), base_dir)
    return own or resolve_marker_path((settings or {}).get("routeMarker"), base_dir)


def _warn_once(path: str, why: str) -> None:
    if path not in _warned:
        _warned.add(path)
        logger.warning("Marker image %s not used (%s); drawing the built-in pin.", path, why)


def _to_bgra(img: np.ndarray) -> Optional[np.ndarray]:
    if img.dtype == np.uint16:
        img = (img >> 8).astype(np.uint8)
    elif img.dtype != np.uint8:
        return None
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    if img.shape[2] == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    if img.shape[2] == 4:
        return img
    return None


def _prepare(bgra: np.ndarray) -> np.ndarray:
    """Trim a transparent icon to its content and give it a white halo; crop an
    opaque picture to a circle with a white ring (a photo pin)."""
    alpha = bgra[:, :, 3]
    h, w = alpha.shape
    if (alpha < _ALPHA_SOLID).mean() > 0.005:
        ys, xs = np.where(alpha > 8)
        if len(xs) == 0:
            return bgra
        bgra = bgra[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        halo = max(2, round(max(bgra.shape[:2]) * 0.04))
        padded = cv2.copyMakeBorder(bgra, halo, halo, halo, halo, cv2.BORDER_CONSTANT, value=(0, 0, 0, 0))
        grown = cv2.dilate(
            padded[:, :, 3], cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (halo * 2 + 1, halo * 2 + 1))
        )
        out = np.zeros_like(padded)
        out[:, :, :3] = 255
        out[:, :, 3] = grown
        a = padded[:, :, 3:4].astype(np.float32) / 255.0
        out[:, :, :3] = (padded[:, :, :3] * a + out[:, :, :3] * (1 - a)).astype(np.uint8)
        return out
    side = min(h, w)
    y0, x0 = (h - side) // 2, (w - side) // 2
    square = cv2.resize(bgra[y0:y0 + side, x0:x0 + side, :3], (SPRITE_MAX_PX, SPRITE_MAX_PX), interpolation=cv2.INTER_AREA)
    ring = max(3, SPRITE_MAX_PX // 24)
    mask = np.zeros((SPRITE_MAX_PX * 4,) * 2, dtype=np.uint8)
    c = SPRITE_MAX_PX * 2
    cv2.circle(mask, (c, c), c - 1, 255, -1, cv2.LINE_AA)
    mask = cv2.resize(mask, (SPRITE_MAX_PX, SPRITE_MAX_PX), interpolation=cv2.INTER_AREA)
    inner = np.zeros_like(mask)
    cv2.circle(inner, (SPRITE_MAX_PX // 2, SPRITE_MAX_PX // 2), SPRITE_MAX_PX // 2 - ring, 255, -1, cv2.LINE_AA)
    out = np.full((SPRITE_MAX_PX, SPRITE_MAX_PX, 4), 255, dtype=np.uint8)
    k = (inner.astype(np.float32) / 255.0)[:, :, None]
    out[:, :, :3] = (square * k + 255 * (1 - k)).astype(np.uint8)
    out[:, :, 3] = mask
    return out


def _rasterize_svg(path: str) -> Optional[np.ndarray]:
    """An SVG file as BGRA, drawn by headless Chromium (the renderer already needs it).
    Runs in its own thread so it works with or without an asyncio loop on the caller."""
    result: list = []

    def work() -> None:
        try:
            from playwright.sync_api import sync_playwright

            with open(path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("ascii")
            size = SPRITE_MAX_PX
            page_html = (
                f'<body style="margin:0;background:transparent"><img src="data:image/svg+xml;base64,{encoded}" '
                f'style="display:block;width:{size}px;height:{size}px;object-fit:contain"></body>'
            )
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    page = browser.new_page(viewport={"width": size, "height": size})
                    page.set_content(page_html)
                    page.wait_for_timeout(50)
                    result.append(page.screenshot(omit_background=True))
                finally:
                    browser.close()
        except Exception as exc:
            logger.warning("Could not draw SVG marker %s: %s", path, exc)

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(60)
    if not result:
        return None
    return cv2.imdecode(np.frombuffer(result[0], dtype=np.uint8), cv2.IMREAD_UNCHANGED)


def load_pin(path: Optional[str]) -> Optional[PinSprite]:
    """The sprite for a marker file (cached by path, size and modified time), or None."""
    if not path:
        return None
    try:
        stat = os.stat(path)
    except OSError:
        return None
    key = (path, stat.st_mtime_ns, stat.st_size)
    if key in _sprites:
        return _sprites[key]
    sprite: Optional[PinSprite] = None
    try:
        if stat.st_size > MAX_FILE_BYTES:
            raise ValueError("file is too large")
        if os.path.splitext(path)[1].lower() == ".svg":
            decoded = _rasterize_svg(path)
        else:
            decoded = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        bgra = _to_bgra(decoded) if decoded is not None else None
        if bgra is None:
            raise ValueError("not a readable image")
        h, w = bgra.shape[:2]
        if max(h, w) > SPRITE_MAX_PX:
            k = SPRITE_MAX_PX / max(h, w)
            bgra = cv2.resize(bgra, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA)
        sprite = PinSprite(_prepare(bgra))
    except Exception as exc:
        _warn_once(path, str(exc))
    _sprites[key] = sprite
    return sprite


def deck_icon(path: Optional[str]) -> Optional[Dict]:
    """A pydeck IconLayer icon for a marker file: the pin on a transparent
    384x512 canvas, tip at the bottom centre, as a PNG data URL."""
    sprite = load_pin(path)
    if sprite is None:
        return None
    cw, ch = DECK_CANVAS
    fitted = sprite.fitted(cw, ch)
    canvas = np.zeros((ch, cw, 4), dtype=np.uint8)
    h, w = fitted.shape[:2]
    x0 = (cw - w) // 2
    canvas[ch - h:ch, x0:x0 + w] = fitted
    ok, png = cv2.imencode(".png", canvas)
    if not ok:
        return None
    return {
        "url": "data:image/png;base64," + base64.b64encode(png.tobytes()).decode("ascii"),
        "width": cw, "height": ch, "anchorY": ch,
    }
