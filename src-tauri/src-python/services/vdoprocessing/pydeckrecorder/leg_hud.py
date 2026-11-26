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
/* overflow:hidden on every pill is a hard guarantee: whatever is inside never paints past the pill's own
   background, regardless of a late font swap or a flex child briefly measuring wider than its final box. */
#hud-banner {
    position: fixed; top: 40px; right: 24px; overflow: hidden;
    background: $pill_bg; color: $pill_text; border: 1px solid $divider;
    font-family: "Noto Sans JP", sans-serif; font-weight: 700; font-size: 30px;
    padding: 14px 34px; border-radius: 14px; box-shadow: 0 4px 14px rgba(0,0,0,0.35);
    white-space: nowrap; z-index: 1000;
}
/* Until its first text is set (the opening photo plays first) the banner was an empty red bar. */
#hud-banner:has(#hud-banner-text:empty) { display: none; }
#hud-banner .icon { font-size: 28px; line-height: 1; }
#hud-banner .icon svg { display: inline-block; width: 0.8em; height: 0.8em; vertical-align: -0.1em; }
#hud-chain {
    position: fixed; top: 40px; left: 24px; overflow: hidden;
    background: $pill_bg; color: $pill_text; border: 1px solid $divider;
    font-family: "Noto Sans JP", sans-serif; font-weight: 700; font-size: 30px;
    padding: 14px 34px; border-radius: 14px; box-shadow: 0 4px 14px rgba(0,0,0,0.35);
    white-space: nowrap; z-index: 1000; box-sizing: border-box;
    display: flex; align-items: center;
}
#hud-chain .arrow { opacity: 0.6; margin: 0 6px; display: inline-flex; align-items: center; }
/* The start/end circle badge beside a place name (S/E/a visit-order number) -- same glyph as that
   waypoint's own map pin, inverted (pill_text fill, pill_bg text) so it reads as a badge ON the pill
   rather than another same-colored patch of it. #hud-chain is a flex row so this centers against the
   place text's own box, not an inline vertical-align guess (CJK glyphs sit high under "middle"). */
#hud-chain .badge {
    display: inline-flex; align-items: center; justify-content: center; flex: none;
    width: 1.6em; height: 1.6em; margin-right: 10px; border-radius: 50%;
    background: $pill_text; color: $pill_bg; font-size: 0.62em; font-weight: 900;
    line-height: 1; text-align: center; -webkit-text-stroke: 0.4px $pill_bg;
}
/* A stop-by between the numbered places: same line, lighter and smaller so it reads as a pass-by. */
#hud-chain .place.via { font-weight: 500; font-size: 0.8em; opacity: 0.85; }
/* Small standalone pill, centered at the very top: which numbered stop this leg is walking toward. */
#hud-stopcount {
    position: fixed; top: 40px; left: 50%; transform: translateX(-50%); z-index: 1000; overflow: hidden;
    background: $pill_bg; color: $pill_text; border: 1px solid $divider;
    font-family: "Noto Sans JP", sans-serif; font-weight: 700; font-size: 22px; line-height: 1.1;
    padding: 9px 26px; border-radius: 14px; box-shadow: 0 4px 14px rgba(0,0,0,0.35);
    display: flex; flex-direction: column; align-items: center; gap: 6px; white-space: nowrap;
}
#hud-stopcount .dots { display: flex; gap: 6px; flex-wrap: nowrap; }
#hud-stopcount .dots i { width: 9px; height: 9px; border-radius: 50%; background: $divider; display: inline-block; }
#hud-stopcount .dots i.on { background: $pill_text; }
#hud-card {
    position: fixed; bottom: 32px; right: 32px;
    background: $card_bg; border: 1px solid $divider; border-radius: 16px;
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
/* Below the bar's right end, its own fixed spot rather than stacked inside the bar (which is full-width now). */
#hud-compass-wrap {
    position: fixed; top: 128px; right: 24px; z-index: 1000;
    display: flex; flex-direction: column; align-items: center;
}
#hud-compass { display: block; filter: drop-shadow(0 4px 10px rgba(0,0,0,0.35)); }
/* Same ground as every other pill (orange in light, black in dark) with the needle/letter in pill_text
   (white in both), so the compass follows the theme instead of staying a fixed orange in dark mode. */
#hud-compass .dial { fill: $pill_bg; }
#hud-compass .pointer { fill: $accent; }
#hud-compass .letter { fill: $pill_text; font: 700 30px "Noto Sans JP", sans-serif; }
/* Pulled up to overlap the dial's bottom edge, like a badge, instead of sitting below it with a gap.
   Inverted from the dial (bg/text swapped) so it still reads against pill_bg's own color each theme. */
#hud-compass-label {
    box-sizing: border-box; text-align: center; margin-top: -14px; z-index: 1;
    background: $pill_text; color: $pill_bg; border: 1px solid $divider;
    font-family: "Noto Sans JP", sans-serif; font-weight: 700; font-size: 13px;
    padding: 3px 10px; border-radius: 10px; box-shadow: 0 3px 10px rgba(0,0,0,0.3);
    white-space: nowrap; font-variant-numeric: tabular-nums;
}
""")


def _css_rgba(rgba) -> str:
    r, g, b, a = rgba
    return f"rgba({r}, {g}, {b}, {a / 255:.2f})"


def _hud_css(theme: Optional[str] = None) -> str:
    """Leg HUD CSS in the light/dark palette from tuning.UI_THEMES."""
    # The card picture has ~20 px of transparent shadow around it: these are NOT the visible gaps.
    return _HUD_CSS_TEMPLATE.substitute({
        **{k: _css_rgba(v) for k, v in tuning.ui_theme(theme).items()},
        "accent": f"rgb{tuning.ACCENT_COLOR}",
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
# case; driving/airplane are extrapolated the same way). "en_route_suffix" is appended to the
# non-arriving banner text for modes where the traveler is a passenger
# rather than on foot (e.g. "〜へ 乗船中" for a ferry) -- walking has none.
_JA = tuning.LABELS_JA
# The banner's own leading icon reuses the exact same per-mode SVG as the distance card's icon (above),
# just recolored via currentColor instead of its hardcoded dark fill -- not a new vector, the one already
# drawn for the card, now also standing in for the emoji/unicode glyph this banner used to show.
_BANNER_ICON_SVG = {
    mode: svg.replace('fill="#111"', 'fill="currentColor"').replace('stroke="#111"', 'stroke="currentColor"')
    for mode, svg in _MODE_ICON_SVG.items()
}
_MODE_HUD = {
    "walking": {"mode": "walking", "icon": _MODE_ICON_SVG["walking"], "banner_icon": _BANNER_ICON_SVG["walking"], "time_label": _JA["mode_duration_label"]["walking"], "en_route_suffix": "", "default_speed_kmh": 4.5},
    "ferry": {"mode": "ferry", "icon": _MODE_ICON_SVG["ferry"], "banner_icon": _BANNER_ICON_SVG["ferry"], "time_label": _JA["mode_duration_label"]["ferry"], "en_route_suffix": _JA["en_route_suffix"]["ferry"], "default_speed_kmh": 30.0},
    "driving": {"mode": "driving", "icon": _MODE_ICON_SVG["driving"], "banner_icon": _BANNER_ICON_SVG["driving"], "time_label": _JA["mode_duration_label"]["driving"], "en_route_suffix": "", "default_speed_kmh": 40.0},
    "airplane": {"mode": "airplane", "icon": _MODE_ICON_SVG["airplane"], "banner_icon": _BANNER_ICON_SVG["airplane"], "time_label": _JA["mode_duration_label"]["airplane"], "en_route_suffix": _JA["en_route_suffix"]["airplane"], "default_speed_kmh": 500.0},
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


# 120x120 viewBox, dial+pointer centered at (60, 60): the pointer's tip sits 58 units from that
# center, so the center needs 58 units of clearance on every side (118 clipped it on rotations
# toward the edges - e.g. due west/east ran the tip past x=0/120 on the old 100-wide, off-center
# box). The pointer is fixed (it marks "forward") -- the letter in the dial is the current heading,
# both as an exact rotation (rotate(deg, 60, 60), clockwise from up) and as the letter/degree text,
# updated per frame.
_COMPASS_SVG = """<svg id="hud-compass" width="{px_size}" height="{px_size}" viewBox="0 0 120 120">
<polygon id="hud-compass-pointer" class="pointer" points="60,2 70,20 50,20"/>
<circle class="dial" cx="60" cy="60" r="38"/>
<text id="hud-compass-letter" class="letter" x="60" y="71" text-anchor="middle">{north}</text>
</svg>"""


_COMPASS_POINTS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def _compass_points() -> Tuple[str, ...]:
    """N, NE, … clockwise in the video's language (labels_<lang>.json "compass_points"; 北, 北東, … in Japanese)."""
    points = video_text.current_labels().get("compass_points")
    return tuple(points) if isinstance(points, list) and len(points) == 8 else _COMPASS_POINTS


def compass_svg(size: int) -> str:
    # Scaled 120/100 along with the viewBox so the dial keeps its old on-screen size - only the
    # extra clearance around it (previously clipping the pointer) grows.
    return _COMPASS_SVG.format(px_size=round(size * 1.2), north=_compass_points()[0])


def _heading_label(deg: float) -> str:
    """e.g. 47.3 -> "NE 47°" ("北東 47°" in Japanese)."""
    deg = round(deg) % 360
    return f"{_compass_points()[int((deg + 22.5) // 45) % 8]} {deg}°"


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
    dest_label: str, remaining_m: float, arrive_threshold_m: float, mode: str = "walking",
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
