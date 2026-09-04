"""Shared setup for GraphicsEngine: __init__, font/image loading, shared constants.

[REFACTOR NOTE — carried over from the original single-file graphicengine.py]
This module previously could not be imported successfully as written:
`write_fade_clip` / `play_fullscreen_video` type-hinted a parameter as
`video_out: VideoExporter` with no `VideoExporter` import anywhere in the
file, and no `from __future__ import annotations` to defer evaluation —
Python evaluates function annotations eagerly at `def`-time, so this was
a guaranteed `NameError` the moment the class body executed. Likewise
`_load_font`'s `-> FreeTypeFont | Any` return hint uses PEP 604 syntax
that also needs eager evaluation deferred on pre-3.10 interpreters.
`read_image_safe`'s except-block also called `logger.warning(...)` with
no `logger` ever defined in this file — a second latent NameError on the
(fairly common) "image failed to decode" path.

Fixes applied below:
  1. `from __future__ import annotations` (PEP 563) — defers ALL
     annotation evaluation to strings, eliminating both NameErrors above
     without needing an eager, possibly-circular import of VideoExporter.
  2. A real `logger` via the shared `setup_logger` factory, consistent
     with every other service module in this codebase.
  3. `_load_font` is memoized (`self._font_cache`) — it was previously
     doing real filesystem I/O (TrueType file open + glyph table parse) on
     EVERY call to `render_popup_box`, which itself is invoked once per
     rendered frame for as long as a "baked" HUD popup is on screen. That
     turned an O(1)-amortizable cost into O(N) redundant disk I/O across
     an N-frame popup hold.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Final, List, Optional, Tuple

import cv2
import numpy as np
from PIL.ImageFont import FreeTypeFont, load_default, truetype

from services.logger.logger import setup_logger
from services import tuning

logger = setup_logger("GraphicsEngine")

# Bundled in the repo (services/mapfetcher/graphicengine/ -> up to src-python/
# -> assets/fonts/) rather than relied on as a system font — Kosugi Maru
# isn't preinstalled on Windows the way meiryo/msgothic are, so a bare
# filename candidate would silently fall through to those instead unless
# it's actually findable on disk.
_BUNDLED_FONTS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "assets", "fonts"
)


class _GraphicsEngineBase:
    FONT_CANDIDATES_REGULAR: Final[List[str]] = [
        os.path.join(_BUNDLED_FONTS_DIR, "KosugiMaru-Regular.ttf"),
        "NotoSansJP-Regular.ttf",
        "NotoSansJP-Regular.otf",
        "meiryo.ttc",
        "msgothic.ttc",
        "YuGothic.ttc",
        "segoeui.ttf",
        "DejaVuSans.ttf",
    ]
    # Kosugi Maru only ships one weight (no dedicated bold cut) — listed
    # here too so bold text still renders in the same rounded style
    # instead of jumping to a different typeface for headings/values.
    FONT_CANDIDATES_BOLD: Final[List[str]] = [
        os.path.join(_BUNDLED_FONTS_DIR, "KosugiMaru-Regular.ttf"),
        "NotoSansJP-Bold.ttf",
        "NotoSansJP-Bold.otf",
        "meiryob.ttc",
        "msgothic.ttc",
        "YuGothic-Bold.ttc",
        "seguisb.ttf",
        "DejaVuSans-Bold.ttf",
    ]

    def __init__(
        self,
        line_color=(0, 200, 255),
        line_thickness=10,
        marker_color=tuning.DEFAULT_MARKER_COLOR,  # blue (BGR) — every pin except S/E
        arrived_marker_color=tuning.DEFAULT_ARRIVED_MARKER_COLOR,  # deeper blue once visited
        marker_radius=18,
        font_size: int = 18,
    ):
        self.line_color = line_color
        # Clamp to a sane minimum: a sub-pixel radius/thickness (e.g. a
        # stray 0.25 from a malformed settings file) would otherwise
        # render the marker/path as an invisible sliver. The pin needs
        # enough room for its teardrop shape AND a legible number inside —
        # 6px reads as a bare dot, so the marker floor is higher than the
        # line-thickness floor.
        self.line_thickness = max(2, int(round(line_thickness)))
        self.marker_color = marker_color
        # Color a pin switches to once its waypoint has been reached, so
        # visited stops read differently from ones still ahead.
        self.arrived_marker_color = arrived_marker_color
        self.marker_radius = max(16, int(round(marker_radius))) + 3
        self.font_size = font_size
        self.font_cv = cv2.FONT_HERSHEY_SIMPLEX

    @staticmethod
    def read_image_safe(path: str) -> Optional[np.ndarray]:
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as f:
                chunk = f.read()
            img_array = np.frombuffer(chunk, dtype=np.uint8)
            return cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        except Exception as e:
            logger.warning(f"Failed to load image {path}: {e}")
            return None

    # Per-travel-mode line colors (BGR). Modes without an entry fall back to
    # self.line_color (the existing single-color behavior). Also used by
    # the summary card (cards.py) so each mode's stat column matches its
    # own route-line color. Values live in services/tuning.py.
    MODE_COLORS: Final[Dict[str, Tuple[int, int, int]]] = tuning.MODE_LINE_COLORS

    # Supported fixed corners for popup/HUD cards. Order is the default
    # fallback preference when picking a corner automatically. Shared by
    # both _PopupBoxMixin and _FullscreenMixin, so it lives here rather
    # than in either leaf mixin.
    HUD_CORNERS: Final[Tuple[str, ...]] = (
        "bottom_left", "bottom_right", "top_left", "top_right",
    )

    @staticmethod
    def _hud_corner_box(
        corner: str, w: int, h: int, total_w: int, total_h: int
    ) -> Tuple[int, int]:
        x = 40 if "left" in corner else w - total_w - 40
        y = h - total_h - 40 if "bottom" in corner else 40
        return x, y

    def _load_font(self, candidates: List[str], size: int) -> FreeTypeFont | Any:
        for name in candidates:
            try:
                return truetype(name, size)
            except OSError:
                continue
        return load_default()
