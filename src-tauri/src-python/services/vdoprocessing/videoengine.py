"""
VDO Engine Service (video_engine.py) — COMPATIBILITY SHIM
---------------------------------------------------------------------------
[REFACTOR NOTE — read this before adding anything to this file]

This module used to contain a full, INDEPENDENTLY MAINTAINED copy of
`MathUtils`, `VideoExporter`, and `GraphicsEngine` — near-duplicates of
the classes already living in `math_util.py`, `vdo_exporter.py`, and
`graphic_engine.py` respectively.

Diffing the two `GraphicsEngine` implementations during this refactor
found they had ALREADY drifted out of sync: this file's copy was missing
`load_walking_sprites()` / `draw_walking_human()`, which exist only in
`graphic_engine.GraphicsEngine`. That's the textbook failure mode of
duplicated modules — a feature or bugfix lands in one copy and silently
never reaches the other, and nothing in the type system or test suite
enforces that they stay identical. Given three duplicate ~150-300 line
classes, the probability of *at least one* further silent divergence
compounds badly over time; consolidating removes the possibility
entirely rather than just fixing today's instance of it.

Rather than delete this module outright (something outside the reviewed
scope of this refactor may still do `from services.video_engine import
GraphicsEngine`), it is now a thin re-export layer. There is exactly ONE
`VideoExporter`, ONE `GraphicsEngine`, and ONE `MathUtils` in the
codebase after this change — every caller, regardless of which module
path they import from, gets the same object identity and the same
(non-drifted, walking-sprite-capable) behavior.

Net effect: ~700 lines of duplicate implementation collapse to a handful
of import lines. Nothing about this module's PUBLIC API (the three class
names) changes, so no call site elsewhere needs to be touched.
---------------------------------------------------------------------------
"""

from services.math_util import MathUtils
from services.vdoprocessing.vdoexporter import VideoExporter
from services.graphic_engine import GraphicsEngine

__all__ = ["MathUtils", "VideoExporter", "GraphicsEngine"]