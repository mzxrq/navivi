"""
services/math_utils.py
---------------------------------------------------------------------------
Pure mathematical and geometric utilities.
---------------------------------------------------------------------------
"""

import math
from typing import Any
import numpy as np


class MathUtils:
    @staticmethod
    def point_to_segment_distance(
        px: float, py: float, ax: float, ay: float, bx: float, by: float
    ) -> float:
        abx, aby = bx - ax, by - ay
        seg_len_sq = abx * abx + aby * aby
        if seg_len_sq < 1e-9:
            return float(np.hypot(px - ax, py - ay))
        t = max(0.0, min(1.0, ((px - ax) * abx + (py - ay) * aby) / seg_len_sq))
        closest_x, closest_y = ax + t * abx, ay + t * aby
        return float(np.hypot(px - closest_x, py - closest_y))

    @staticmethod
    def is_real_label(lbl: Any) -> bool:
        if lbl is None:
            return False
        if isinstance(lbl, float) and math.isnan(lbl):
            return False
        return str(lbl).strip() != ""
