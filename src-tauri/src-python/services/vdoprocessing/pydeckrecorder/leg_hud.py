"""The walking leg's HUD: its CSS, mode icons and labels, the compass, and the remaining distance/time text."""

from __future__ import annotations

import bisect
import math
import string
from typing import Dict, List, Optional, Tuple

from services import tuning, video_text

# ---------------------------------------------------------------------------
# RESIDENTIAL: per-leg tilted chase camera + turn-by-turn HUD
# ---------------------------------------------------------------------------

_HUD_CSS_TEMPLATE = string.Template("""
#hud-banner {
    position: fixed; top: 24px; right: 24px;
    background: $pill_bg; color: $pill_text;
    font-family: "Noto Sans JP", sans-serif; font-weight: 700; font-size: 30px;
    padding: 14px 34px; border-radius: 999px; box-shadow: 0 4px 14px rgba(0,0,0,0.35);
    white-space: nowrap; z-index: 1000;
}
#hud-card {
    position: fixed; bottom: 32px; right: 32px;
    background: $card_bg; border: 3px solid $card_text; border-radius: 30px;
    padding: 28px 56px; display: flex; align-items: center; gap: 44px;
    font-family: "Noto Sans JP", sans-serif; box-shadow: 0 6px 20px rgba(0,0,0,0.35);
    z-index: 1000;
}
#hud-card .metric { text-align: center; }
#hud-card .metric .label { font-size: 20px; color: $card_label; display: flex; align-items: center; justify-content: center; gap: 6px; }
#hud-card .metric .value { font-size: 46px; font-weight: 700; color: $card_text; margin-top: 2px; }
#hud-card .divider { width: 1px; height: 64px; background: $divider; }
#hud-card .icon { width: 26px; height: 26px; line-height: 1; }
#hud-card .icon svg { display: block; width: 100%; height: 100%; }
#hud-card.hidden { display: none; }
#hud-card-img { position: fixed; bottom: ${card_bottom}px; right: ${card_right}px; z-index: 1000; }
/* Destination pill + compass stacked in the top-right corner, compass underneath. */
#hud-top-right {
    position: fixed; top: 24px; right: 24px; z-index: 1000;
    display: flex; flex-direction: column; align-items: flex-end; gap: 12px;
}
#hud-top-right #hud-banner { position: static; }
#hud-compass { display: block; filter: drop-shadow(0 4px 10px rgba(0,0,0,0.35)); }
#hud-compass .dial { fill: $card_bg; stroke: $card_text; stroke-width: 3; }
#hud-compass .tick { stroke: $card_label; stroke-width: 2; stroke-linecap: round; }
#hud-compass .tick.n { stroke: $card_text; stroke-width: 3; }
#hud-compass .letter { fill: $card_text; font: 700 15px "Noto Sans JP", sans-serif; }
#hud-compass .tail { fill: $card_label; }
#hud-compass-label {
    margin-top: -4px; min-width: 104px; box-sizing: border-box; text-align: center;
    background: $pill_bg; color: $pill_text;
    font-family: "Noto Sans JP", sans-serif; font-weight: 700; font-size: 16px;
    padding: 4px 12px; border-radius: 999px; box-shadow: 0 3px 10px rgba(0,0,0,0.3);
    white-space: nowrap; font-variant-numeric: tabular-nums;
}
#hud-banner .icon { font-size: 28px; line-height: 1; }
/* Same size as #hud-banner, the pill opposite it. */
#hud-chain {
    position: fixed; top: 24px; left: 24px;
    background: $pill_bg; color: $pill_text;
    font-family: "Noto Sans JP", sans-serif; font-weight: 700; font-size: 30px;
    padding: 14px 34px; border-radius: 999px; box-shadow: 0 4px 14px rgba(0,0,0,0.35);
    white-space: nowrap; z-index: 1000;
}
#hud-chain .arrow { opacity: 0.6; margin: 0 6px; }
""")


def _css_rgba(rgba) -> str:
    r, g, b, a = rgba
    return f"rgba({r}, {g}, {b}, {a / 255:.2f})"


def _hud_css(theme: Optional[str] = None) -> str:
    """Leg HUD CSS in the light/dark palette from tuning.UI_THEMES."""
    # The card picture has ~20 px of transparent shadow around it: these are NOT the visible gaps.
    return _HUD_CSS_TEMPLATE.substitute({
        **{k: _css_rgba(v) for k, v in tuning.ui_theme(theme).items()},
        "card_bottom": tuning.LEG_CARD_MARGIN_BOTTOM_PX, "card_right": tuning.LEG_CARD_MARGIN_PX,
    })

# Per-mode distance-card icon: a plain black line-drawing SVG (currentColor
# stroke, no fill) instead of a platform emoji -- emoji glyphs are
# multicolor bitmaps that ignore CSS `color`, which is what "colored icon"
# meant here; a stroked SVG reads as a clean black/white pictogram matching
# the rest of the card's plain black-on-white styling regardless of the
# host's emoji font.
_MODE_ICON_SVG = {
    # Traced from assets/image/icon/walking.svg (potrace output) rather than
    # hand-drawn like the other modes below -- a solid walking-pictogram
    # silhouette instead of a thin line icon.
    "walking": (
        '<svg viewBox="0 0 757 1280" fill="#111" stroke="none">'
        '<g transform="translate(0,1280) scale(0.1,-0.1)">'
        """<path d="M4084 12786 c-416 -68 -756 -378 -860 -785 -125 -485 105 -988 553
-1210 165 -82 277 -106 478 -105 139 1 173 4 257 27 363 97 649 374 752 728
75 260 51 520 -69 764 -139 281 -387 483 -690 561 -123 31 -301 40 -421 20z"/>
<path d="M3765 10455 c-149 -24 -309 -86 -443 -172 -74 -46 -2133 -1715 -2202
-1783 -60 -59 -99 -121 -124 -197 -22 -70 -474 -2108 -482 -2173 -8 -72 15
-180 56 -260 87 -172 293 -278 483 -249 91 14 195 68 266 140 91 91 122 163
177 409 55 250 351 1598 356 1623 2 13 738 620 745 614 1 -1 -254 -1134 -567
-2518 l-568 -2516 -685 -1150 c-377 -633 -697 -1177 -710 -1209 -91 -218 -88
-412 9 -613 38 -78 60 -108 132 -181 99 -99 186 -152 304 -187 250 -72 497
-13 689 164 33 31 80 84 103 117 81 114 1517 2546 1576 2669 l59 122 178 823
c97 452 180 821 184 820 12 -6 1529 -1669 1529 -1677 0 -16 459 -2425 476
-2496 58 -253 250 -466 488 -541 330 -104 696 50 852 358 71 140 93 324 60
499 -8 41 -45 233 -81 425 -36 192 -115 608 -175 924 -60 316 -139 733 -175
925 -65 345 -95 462 -134 526 -11 18 -442 532 -958 1142 -516 609 -937 1114
-936 1120 8 44 475 2093 478 2096 2 2 96 -181 208 -406 158 -315 215 -420 251
-460 57 -63 1612 -1139 1711 -1184 189 -85 399 -46 539 100 173 182 179 463
13 647 -31 35 -269 204 -785 560 l-740 509 -145 290 c-643 1278 -931 1841
-966 1888 -257 349 -656 525 -1046 462z"/>"""
        "</g></svg>"
    ),
    "ferry": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="#111" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M4 15l1.5 4h13L20 15"/><path d="M6 15l1-8h3v8M14 15V7h3l1 8"/>'
        '<path d="M12 3v4"/></svg>'
    ),
    "driving": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="#111" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M4 16V12l2-5h12l2 5v4"/><path d="M4 16h16"/>'
        '<circle cx="7.5" cy="16.5" r="1.5"/><circle cx="16.5" cy="16.5" r="1.5"/></svg>'
    ),
    "airplane": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="#111" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M3 13l7-2 5-9 2 1-3 8 6-1 2 2-8 3-2 5-2-1 1-5-6 2z"/></svg>'
    ),
}

# Per-mode HUD chrome: the reference video swaps both the banner's leading
# icon/suffix and the distance card's icon/time-label depending on how this
# leg is being traveled (walking vs. a ferry crossing was the confirmed
# case; driving/airplane are extrapolated the same way from
# pydeckrecorder.recorder's own _VEHICLE_PROFILES mode set, so this dict's
# keys intentionally match that one). "en_route_suffix" is appended to the
# non-arriving banner text for modes where the traveler is a passenger
# rather than on foot (e.g. "〜へ 乗船中" for a ferry) -- walking has none.
_JA = tuning.LABELS_JA
_MODE_HUD = {
    "walking": {"mode": "walking", "icon": _MODE_ICON_SVG["walking"], "banner_icon": "●", "time_label": _JA["mode_duration_label"]["walking"], "en_route_suffix": "", "default_speed_kmh": 4.5},
    "ferry": {"mode": "ferry", "icon": _MODE_ICON_SVG["ferry"], "banner_icon": "⛴", "time_label": _JA["mode_duration_label"]["ferry"], "en_route_suffix": _JA["en_route_suffix"]["ferry"], "default_speed_kmh": 30.0},
    "driving": {"mode": "driving", "icon": _MODE_ICON_SVG["driving"], "banner_icon": "\U0001F697", "time_label": _JA["mode_duration_label"]["driving"], "en_route_suffix": "", "default_speed_kmh": 40.0},
    "airplane": {"mode": "airplane", "icon": _MODE_ICON_SVG["airplane"], "banner_icon": "✈", "time_label": _JA["mode_duration_label"]["airplane"], "en_route_suffix": _JA["en_route_suffix"]["airplane"], "default_speed_kmh": 500.0},
}
_DEFAULT_MODE_HUD = _MODE_HUD["walking"]


def _localized_hud(mode_hud: Dict, labels: Optional[Dict] = None) -> Dict:
    """mode_hud with the time label and en-route suffix in the project's on-video language
    (the table above holds the Japanese ones)."""
    labels = labels or video_text.current_labels()
    mode = mode_hud["mode"]
    return {
        **mode_hud,
        "time_label": labels["mode_duration_label"].get(mode, mode_hud["time_label"]),
        "en_route_suffix": labels["en_route_suffix"].get(mode, ""),
    }


# 100x100 viewBox; only #hud-compass-needle rotates (about the centre).
_COMPASS_SVG = """<svg id="hud-compass" width="{size}" height="{size}" viewBox="0 0 100 100">
<circle class="dial" cx="50" cy="50" r="46"/>
<line class="tick n" x1="50" y1="7" x2="50" y2="15"/>
<line class="tick" x1="93" y1="50" x2="87" y2="50"/>
<line class="tick" x1="50" y1="93" x2="50" y2="87"/>
<line class="tick" x1="7" y1="50" x2="13" y2="50"/>
<text class="letter" x="50" y="31" text-anchor="middle">N</text>
<g id="hud-compass-needle">
<polygon class="tail" points="50,82 57,50 43,50"/>
<polygon fill="#d93a32" points="50,18 57,50 43,50"/>
</g>
<circle cx="50" cy="50" r="4" fill="#ffffff" stroke="#555" stroke-width="1.5"/>
</svg>"""


_COMPASS_POINTS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def _heading_label(deg: float) -> str:
    """e.g. 47.3 -> "NE 47°"."""
    deg = round(deg) % 360
    return f"{_COMPASS_POINTS[int((deg + 22.5) // 45) % 8]} {deg}°"


def _walk_headings(lons, lats, window_m: float) -> List[float]:
    """Per-frame compass heading (degrees clockwise from north) of the
    path, measured between the points `window_m` behind and ahead along it.
    Frames where the walker is standing still keep the heading around them."""
    n = len(lons)
    if n == 0:
        return []
    lat0 = math.radians(float(sum(lats)) / n)
    xs = [float(lon) * 111320.0 * math.cos(lat0) for lon in lons]
    ys = [float(lat) * 110540.0 for lat in lats]
    dist = [0.0]
    for i in range(1, n):
        dist.append(dist[-1] + math.hypot(xs[i] - xs[i - 1], ys[i] - ys[i - 1]))

    def at(d: float) -> Tuple[float, float]:
        d = min(max(d, 0.0), dist[-1])
        j = min(max(bisect.bisect_left(dist, d), 1), n - 1) if n > 1 else 0
        if n == 1 or dist[j] == dist[j - 1]:
            return xs[j], ys[j]
        t = (d - dist[j - 1]) / (dist[j] - dist[j - 1])
        return xs[j - 1] + (xs[j] - xs[j - 1]) * t, ys[j - 1] + (ys[j] - ys[j - 1]) * t

    headings: List[Optional[float]] = []
    for d in dist:
        (ax, ay), (bx, by) = at(d - window_m), at(d + window_m)
        if math.hypot(bx - ax, by - ay) < 0.5:
            headings.append(None)
        else:
            headings.append(math.degrees(math.atan2(bx - ax, by - ay)) % 360.0)
    first = next((h for h in headings if h is not None), 0.0)
    out, last = [], first
    for h in headings:
        last = h if h is not None else last
        out.append(last)
    return out


def _remaining_minutes(remaining_m: float, remaining_km: float, travel_speed_kmh: float) -> int:
    """Minutes-left for the HUD card, floored to 1 so a leg that's still
    actually in progress never displays "0 分" -- except when the distance
    itself has already rounded down to "0 m" on the card, where a floored
    "1 分" would contradict the distance sitting right next to it."""
    minutes = round((remaining_km / travel_speed_kmh) * 60.0)
    return minutes if round(remaining_m) == 0 else max(1, minutes)


def _hud_text(
    dest_label: str, remaining_m: float, remaining_min: int, arrive_threshold_m: float, mode: str = "walking",
    labels: Optional[Dict] = None,
) -> Tuple[str, str]:
    """Returns (banner_text, distance_text) for one frame's remaining
    distance -- split out from the render loop so the arrival-threshold,
    mode-suffix, and unit-formatting logic can be exercised by a plain unit
    test without spinning up a browser."""
    labels = labels or video_text.current_labels()
    mode_hud = _localized_hud(_MODE_HUD.get(mode, _DEFAULT_MODE_HUD), labels)
    if remaining_m < arrive_threshold_m:
        banner = labels["soon_banner"].format(dest=dest_label)
    else:
        banner = labels["en_route_banner"].format(dest=dest_label, suffix=mode_hud["en_route_suffix"])
    dist_text = f"{remaining_m:.0f} m" if remaining_m < 1000 else f"{remaining_m / 1000.0:.1f} km"
    return banner, dist_text
