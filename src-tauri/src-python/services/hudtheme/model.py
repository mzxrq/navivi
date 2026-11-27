"""Route data -> what the themed cards show. Pure functions, apart from reading the theme folders."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

from services import tuning

THEMES_DIR = Path(__file__).parent / "themes"
MOUNTAIN_CLIMB_M = 300.0
_CLIMB_STEP_M = 3.0  # smaller rises are GPS jitter
_MIN_WALK_SHARE = 0.05  # a shorter walk with no numbered stop (pier to station) gets no segment of its own
_EVEN_SHARE = 0.5  # of the strip's width split evenly between segments, so a short one still fits its chip
_PIER_SHARE = 0.02  # of the route: a stop this close to a stretch counts as touching it

Stop = Tuple[float, str, str]  # (distance along the route, pin glyph, name)


class Segment(NamedTuple):
    mode: str
    start: float
    end: float
    glyphs: str  # the numbered stops on it, "1–3"
    place: str


def normalize_mode(mode: str) -> str:
    mode = str(mode or "walking").lower()
    return {"car": "driving"}.get(mode, mode)


def theme_ids() -> List[str]:
    return sorted(p.parent.name for p in THEMES_DIR.glob("*/theme.json"))


def _hex(bgr: Sequence[int]) -> str:
    return "#%02X%02X%02X" % (bgr[2], bgr[1], bgr[0])


def pin_color(theme: Dict, glyph) -> str:
    """The colour of the map pin showing this glyph: its number circle on a card wears the same."""
    glyph = str(glyph)
    kind = {"S": "start", "E": "end", "×": "closed"}.get(glyph, "stopby" if glyph[:1] in ("+", "・") else "stop")
    return theme["pins"][kind]


def load_theme(theme_id: str, dark: bool = False) -> Dict:
    """A theme's colors and artwork; `dark` lays its "dark" colors over them (the project's light/dark setting)."""
    folder = THEMES_DIR / theme_id
    data = json.loads((folder / "theme.json").read_text(encoding="utf-8"))
    layout = data.get("layout") or {}
    if dark:
        night = data["dark"]
        data = {"colors": {**data["colors"], **night["colors"]}, "mode_colors": night["mode_colors"]}
    # The map's own pins, whatever the theme; only a closed place's red is picked per theme, off its banner.
    pins = {"stop": _hex(tuning.DEFAULT_MARKER_COLOR), "stopby": _hex(tuning.STOPBY_PIN_COLOR),
            "start": _hex(tuning.START_PIN_COLOR), "end": _hex(tuning.END_PIN_COLOR),
            "closed": data["colors"]["closed"]}
    return {
        "id": f"{theme_id}-dark" if dark else theme_id, "dark": dark, **data["colors"],
        "mode_colors": data["mode_colors"], "pins": pins, "layout": layout,
        "scene": (folder / ("scene_dark.svg" if dark else "scene.svg")).read_text(encoding="utf-8"),
        "pattern": (folder / "pattern.svg").read_text(encoding="utf-8"),
    }


def resolve_theme(setting: Optional[str], modes: Sequence[str], climb: float) -> Optional[str]:
    """settings.hud_theme -> a theme id, or None for the classic look (also for an unknown name)."""
    have = theme_ids()
    if setting != "auto":
        return setting if setting in have else None
    if any(normalize_mode(m) == "ferry" for m in modes):
        wanted = "sea"
    else:
        wanted = "mountain" if climb >= MOUNTAIN_CLIMB_M else "town"
    return wanted if wanted in have else "sea"


def climb_m(elevations: Sequence[float]) -> float:
    total, low = 0.0, None
    for ele in elevations:
        if low is None or ele < low:
            low = ele
        elif ele - low >= _CLIMB_STEP_M:
            total += ele - low
            low = ele
    return total


def _is_numbered(glyph: str) -> bool:
    return str(glyph).isdigit()


def stopby_marks(counts: Sequence[int]) -> List[List[str]]:
    """How many stop-bys each leg has, in route order -> each leg's marks, "+1", "+2" … counted on through
    the whole route (a plus, so none reads as a numbered stop)."""
    out, last = [], 0
    for n in counts:
        out.append([f"+{i}" for i in range(last + 1, last + n + 1)])
        last += n
    return out


def is_dark(settings: Dict) -> bool:
    """The themed design is light unless the project picked dark (the classic look's own default is dark)."""
    return settings.get("theme") == "dark"


def notice_colors(theme: Dict) -> Optional[Tuple[Tuple[int, ...], Tuple[int, ...]]]:
    """(body, text) RGBA for the app's stop-by / closed banners (engine.stopby_notice_colors); None in the light
    themes, which keep the app's white card."""
    if not theme["dark"]:
        return None
    body, text = (tuple(int(theme[k][i:i + 2], 16) for i in (1, 3, 5)) for k in ("paper", "ink"))
    return (*body, 245), (*text, 255)


def _place_name(names: Sequence[str]) -> str:
    """What the stops share ("友ヶ島"), else the first one's name."""
    if not names:
        return ""
    shared = os.path.commonprefix(list(names)).strip()
    return shared if len(names) > 1 and len(shared) >= 2 else names[0]


def route_segments(cum: Sequence[float], modes: Sequence[str], stops: Sequence[Stop]) -> List[Segment]:
    """The route as runs of one travel mode, each with its numbered stops. `cum` is the distance at each
    path point and `modes` that point's mode."""
    if not len(cum):
        return []
    total = float(cum[-1])
    runs: List[List] = []  # [mode, start, end]
    for d, mode in zip(cum, modes):
        mode = normalize_mode(mode)
        if runs and runs[-1][0] == mode:
            runs[-1][2] = float(d)
        else:
            runs.append([mode, runs[-1][2] if runs else 0.0, float(d)])
    inner = [s for s in stops if _is_numbered(s[1])]

    def on(run) -> List[Stop]:
        return [s for s in inner if run[1] < s[0] <= run[2]]

    merged: List[List] = []
    carry: Optional[float] = None  # a dropped first run: the next one starts where it did
    for run in runs:
        if len(runs) > 1 and run[0] == "walking" and not on(run) and run[2] - run[1] < total * _MIN_WALK_SHARE:
            if merged:
                merged[-1][2] = run[2]
            else:
                carry = run[1]
            continue
        if carry is not None:
            run[1], carry = carry, None
        if merged and merged[-1][0] == run[0]:
            merged[-1][2] = run[2]
        else:
            merged.append(run)

    # A stop where two runs meet (a pier) belongs to the one on foot, not the boat.
    owned: List[List[Stop]] = [[] for _ in merged]
    for stop in inner:
        # (A pier's own distance never falls exactly on the change of mode in real route data.)
        near = [i for i, r in enumerate(merged)
                if r[1] - total * _PIER_SHARE <= stop[0] <= r[2] + total * _PIER_SHARE]
        if not near:
            continue
        owned[next((i for i in near if merged[i][0] == "walking"), near[0])].append(stop)

    out = []
    for run, found in zip(merged, owned):
        glyphs = ""
        if found:  # lowest to highest: a return stop wears an earlier number again
            first, last = (pick((s[1] for s in found), key=int) for pick in (min, max))
            glyphs = first if first == last else f"{first}–{last}"
        out.append(Segment(run[0], run[1], run[2], glyphs, _place_name([s[2] for s in found])))
    return out


def strip_spans(segments: Sequence[Segment], x0: float, x1: float) -> List[Tuple[float, float]]:
    """Each segment's (left, right) on the progress strip."""
    n = len(segments)
    length = sum(s.end - s.start for s in segments) or 1.0
    spans, x = [], float(x0)
    for i, s in enumerate(segments):
        share = _EVEN_SHARE / n + (1 - _EVEN_SHARE) * (s.end - s.start) / length
        right = float(x1) if i == n - 1 else x + (x1 - x0) * share
        spans.append((x, right))
        x = right
    return spans


def strip_x(segments: Sequence[Segment], spans: Sequence[Tuple[float, float]], dist: float) -> float:
    """Where `dist` along the route sits on the strip."""
    for s, (left, right) in zip(segments, spans):
        if dist <= s.end:
            u = min(1.0, max(0.0, (dist - s.start) / ((s.end - s.start) or 1.0)))
            return left + (right - left) * u
    return spans[-1][1]


def mode_cards(breakdown: Dict[str, float], durations: Dict[str, float]) -> List[Tuple[str, float, float]]:
    """(mode, km, seconds) per mode the route uses: walking first, the rest as the breakdown lists them."""
    found: Dict[str, List[float]] = {}
    for mode, km in (breakdown or {}).items():
        if km and km > 0:
            entry = found.setdefault(normalize_mode(mode), [0.0, 0.0])
            entry[0] += km
            entry[1] += (durations or {}).get(mode, 0.0)
    return sorted(((m, km, s) for m, (km, s) in found.items()), key=lambda c: c[0] != "walking")
