"""Turn-by-turn leg scripts for the "course" style (the user's reference, see
.agents/scratch/course-type/reference_scripts.md): each stop's arriving script
gives the way from the previous stop, read off the leg's own line; its
attraction script opens by naming the place."""

import math
import re
from typing import Dict, List, Optional

from services import tuning
from services.localization.route_brief import (
    _COMPASS,
    _leg_mode,
    _leg_points,
    _length_km,
    clean_label,
    on_route,
    split_crossings,
)
from services.localization.route_brief import heading as route_heading

# Douglas-Peucker tolerances tried in turn until the leg has at most MAX_TURNS
# turns: GPS wiggles and a road's gentle curves are not turns.
SIMPLIFY_STEPS_M = (12.0, 20.0, 35.0, 60.0, 100.0, 160.0)
MAX_TURNS = 8
MERGE_M = 20.0  # bends closer than this are one turn
EDGE_M = 15.0  # a bend this close to either end is the stop itself
BEAR_DEG, TURN_DEG, SHARP_DEG, BACK_DEG = 25.0, 50.0, 120.0, 160.0
STRAIGHT_M = 300.0  # a stretch this long without a turn is told as 道なりに
ARRIVE_NEAR_M = 150.0  # a last turn this close to the stop leads into it
SOON_M = 60.0  # a turn this soon after the last one is すぐに
RETURN_NEAR_KM = 0.15

ARRIVALS = ("{to}が見えてきます。", "{to}はすぐ先です。", "{to}が目の前です。")
STRAIGHTS = ("そのまま道なりに進みます。", "しばらく道なりに直進します。")
START_LINE = "ここは{name}。このコースの出発点です。"
STOPBY_LINE = "時間に余裕があれば立ち寄れる地点、{name}です。"
PLACE_LINE = "{name}です。"
RETURN_LINE = "出発地の{name}に戻ってきました。"
GOAL_LINE = "ゴールの{name}に到着しました。"


def _xy(points: List[List[float]]) -> List[tuple]:
    lat0 = math.radians(sum(p[0] for p in points) / len(points))
    lng0 = points[0][1]
    lat_m, lng_m = 110540.0, 111320.0 * math.cos(lat0)
    return [((p[1] - lng0) * lng_m, (p[0] - points[0][0]) * lat_m) for p in points]


def _simplify(xy: List[tuple], tolerance: float) -> List[tuple]:
    if len(xy) < 3:
        return list(xy)
    keep = [False] * len(xy)
    keep[0] = keep[-1] = True
    stack = [(0, len(xy) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = xy[a], xy[b]
        length = math.hypot(bx - ax, by - ay)
        far, at = 0.0, None
        for i in range(a + 1, b):
            px, py = xy[i]
            d = (abs((bx - ax) * (ay - py) - (ax - px) * (by - ay)) / length if length
                 else math.hypot(px - ax, py - ay))
            if d > far:
                far, at = d, i
        if at is not None and far > tolerance:
            keep[at] = True
            stack += [(a, at), (at, b)]
    return [p for p, k in zip(xy, keep) if k]


def _bearing(a: tuple, b: tuple) -> float:
    return (math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) + 360.0) % 360.0


def _compass(degrees: float) -> str:
    return _COMPASS[int((degrees + 22.5) // 45) % 8]


def _turns_at(line: List[tuple]) -> List[dict]:
    """[{"at": metres along the leg, "angle": signed degrees (+ = right)}]."""
    turns, along = [], 0.0
    for i in range(1, len(line) - 1):
        along += math.hypot(line[i][0] - line[i - 1][0], line[i][1] - line[i - 1][1])
        angle = (_bearing(line[i], line[i + 1]) - _bearing(line[i - 1], line[i]) + 540.0) % 360.0 - 180.0
        if turns and along - turns[-1]["at"] < MERGE_M:
            turns[-1]["angle"] = (turns[-1]["angle"] + angle + 540.0) % 360.0 - 180.0
        else:
            turns.append({"at": along, "angle": angle, "vertex": i})
    total = along + math.hypot(line[-1][0] - line[-2][0], line[-1][1] - line[-2][1]) if len(line) > 1 else 0.0
    return [t for t in turns if abs(t["angle"]) >= BEAR_DEG and EDGE_M <= t["at"] <= total - EDGE_M]


def leg_turns(points: List[List[float]]) -> dict:
    """The leg's turns, each with the heading it leaves on and how far it runs:
    {"heading": first heading, "first_run": metres, "turns": [{"angle",
    "heading", "run", "to_end"}], "length": metres}."""
    xy = _xy(points)
    line, turns = xy, []
    for tolerance in SIMPLIFY_STEPS_M:
        line = _simplify(xy, tolerance)
        turns = _turns_at(line)
        if len(turns) <= MAX_TURNS:
            break
    lengths = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(line, line[1:])]
    total = sum(lengths)
    marks = [0.0, *[t["at"] for t in turns], total]

    def heading_between(start: float, end: float) -> str:
        return _compass(_bearing(_point_at(line, lengths, start), _point_at(line, lengths, end)))

    out = []
    for k, turn in enumerate(turns):
        out.append({
            "angle": turn["angle"],
            "heading": heading_between(marks[k + 1], marks[k + 2]),
            "run": marks[k + 2] - marks[k + 1],
            "to_end": total - marks[k + 1],
            "at": marks[k + 1],
        })
    return {"heading": heading_between(0.0, marks[1]), "first_run": marks[1], "turns": out, "length": total,
            "heading_between": heading_between}


def _point_at(line: List[tuple], lengths: List[float], at: float) -> tuple:
    for a, b, length in zip(line, line[1:], lengths):
        if at <= length:
            f = at / length if length else 0.0
            return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
        at -= length
    return line[-1]


def _turn_phrase(angle: float) -> str:
    side = "右" if angle > 0 else "左"
    size = abs(angle)
    if size < TURN_DEG:
        return f"{side}に寄って"
    if size < SHARP_DEG:
        return f"{side}に曲がって"
    if size < BACK_DEG:
        return f"鋭く{side}に曲がって"
    return f"折り返すように{side}へ曲がって"


def walking_directions(origin: str, to: str, points: List[List[float]], variant: int = 0) -> str:
    """「Aから西へ進みます。右に曲がって南へ。…左に曲がって東へ入ると、Bが見えてきます。」"""
    plan = leg_turns(points)
    arrival = ARRIVALS[variant % len(ARRIVALS)].format(to=to)
    turns = plan["turns"]
    if not turns:
        return f"{origin}から{plan['heading']}へ、道なりに進むと、" + arrival
    sentences = [f"{origin}から{plan['heading']}へ進みます。"]
    straight = plan["first_run"] >= STRAIGHT_M
    if straight:
        sentences.append(STRAIGHTS[0])
    previous, last_phrase, run_before = plan["heading"], "", plan["first_run"]
    for k, turn in enumerate(turns):
        phrase = _turn_phrase(turn["angle"])
        if phrase == last_phrase and "寄って" not in phrase:
            said = "ふたたび" + phrase
        elif k and run_before < SOON_M and not sentences[-1].startswith("すぐに"):
            said = "すぐに" + phrase
        else:
            said = phrase
        last_phrase, run_before = phrase, turn["run"]
        same = turn["heading"] == previous
        previous = turn["heading"]
        if k == len(turns) - 1 and turn["to_end"] <= ARRIVE_NEAR_M:
            sentences.append((f"{said}進むと、" if same else f"{said}{turn['heading']}へ入ると、") + arrival)
            return "".join(sentences)
        sentences.append(f"{said}進みます。" if same else f"{said}{turn['heading']}へ。")
        straight = turn["run"] >= STRAIGHT_M
        if straight:
            sentences.append(STRAIGHTS[(k + 1) % len(STRAIGHTS)])
    sentences.append(f"やがて、{to}が見えてきます。" if straight else f"道なりに進むと、{arrival}")
    return "".join(sentences)


# The brief arriving script: 2-5 sentences (start, a long straight, at most two
# real turns or one summary of many, arrival), worded differently at each stop.
BRIEF_STARTS = (
    "{origin}から{heading}へ{far}歩きます。",
    "{origin}を出て、まずは{heading}へ向かいます。",
    "ここからは{heading}へ進みます。",
    "{origin}をあとに、{heading}の方角へ歩き出します。",
    "{heading}へ延びる道を{far}たどります。",
)
BRIEF_ARRIVALS = ("{to}が見えてきます。", "その先に{to}があります。", "まもなく{to}に着きます。",
                  "{to}はすぐ先です。", "{to}に到着です。")
BRIEF_ARRIVALS_AFTER_TURN = ("{to}が見えてきます。", "{to}はすぐそこです。", "{to}が目の前です。")
BRIEF_MAX_TURNS = 2


def _far(points: List[List[float]]) -> str:
    km = _length_km(points)
    return "少し" if km < 0.3 else "" if km < 1.5 else "しばらく"


def _brief_walk(origin: str, to: str, points: List[List[float]], variant: int) -> str:
    plan = leg_turns(points)
    overall = route_heading(*points[0], *points[-1])
    turns = [t for t in plan["turns"] if abs(t["angle"]) >= TURN_DEG]
    summarized = len(turns) > BRIEF_MAX_TURNS
    # Headings over the stretches between real turns: the small bends between are not told.
    marks = [0.0, *[t["at"] for t in turns], plan["length"]]
    headings = [plan["heading_between"](a, b) for a, b in zip(marks, marks[1:])]
    start = BRIEF_STARTS[variant % len(BRIEF_STARTS)]
    far = _far(points)
    sentences = [start.format(origin=origin, heading=overall if summarized else headings[0], far=far)]
    arrival = BRIEF_ARRIVALS[(variant + 2) % len(BRIEF_ARRIVALS)].format(to=to)
    if marks[1] >= STRAIGHT_M and not summarized:
        sentences.append("そのまま道なりに進みます。" if far and far in sentences[0] else "しばらく道なりに進みます。")
    last_near = bool(turns) and turns[-1]["to_end"] <= ARRIVE_NEAR_M
    told = list(enumerate(turns))
    if summarized:
        sentences.append(f"何度か角を曲がりながら、{overall}へ進んでいきます。")
        told = told[-1:] if last_near else []
    for k, (i, turn) in enumerate(told):
        # Told from the two stretches' headings, so the turn and the heading after it agree.
        delta = (_COMPASS.index(headings[i + 1]) - _COMPASS.index(headings[i])) * 45
        delta = (delta + 540) % 360 - 180
        phrase = _turn_phrase(delta) if delta else _turn_phrase(turn["angle"])
        if k == len(told) - 1 and last_near:
            near = BRIEF_ARRIVALS_AFTER_TURN[variant % len(BRIEF_ARRIVALS_AFTER_TURN)].format(to=to)
            sentences.append(f"{'最後に' if k or summarized else ''}{phrase[:-2]}ると、{near}")
            return "".join(sentences)
        sentences.append(f"{'続いて' if k else ''}{phrase}{headings[i + 1]}へ。")
    sentences.append(arrival)
    return "".join(sentences)


def brief_directions(origin: str, to: str, mode: str, pieces: List[dict], points: List[List[float]], variant: int = 0) -> str:
    """The way to go in 2-5 sentences: the heading, how far it feels, the
    main turns only and, off foot, how it is travelled."""
    heading = route_heading(*points[0], *points[-1]) if len(points) > 1 else ""
    toward = f"{heading}へ" if heading else ""
    if mode in ("ferry", "boat"):
        boat = "フェリー" if mode == "ferry" else "船"
        return f"{origin}から{boat}に乗り込みます。船は{toward}進み、{to}へ渡ります。"
    if any(p["mode"] == "ferry" for p in pieces):
        return f"{origin}から港へ歩き、フェリーで海を渡ります。{to}はその先です。"
    if mode == "airplane":
        return f"{origin}から空路で{to}へ向かいます。"
    if mode != "walking":
        return f"{origin}から車に乗り、{toward}走ります。まもなく{to}に到着します。"
    if not heading:
        return f"{origin}から{to}へ歩きます。"
    return _brief_walk(origin, to, points, variant)


def transit_directions(origin: str, to: str, mode: str, pieces: List[dict], points: List[List[float]]) -> str:
    if mode in ("ferry", "boat"):
        boat = "フェリー" if mode == "ferry" else "船"
        return f"{origin}から{boat}に乗り、{to}へ渡ります。船はまもなく{to}に到着します。"
    if any(p["mode"] == "ferry" for p in pieces):
        return f"{origin}から港へ向かい、フェリーで海を渡って、{to}へ向かいます。まもなく{to}に到着します。"
    heading = route_heading(*points[0], *points[-1]) if len(points) > 1 else ""
    if mode == "airplane":
        return f"{origin}から空路で{to}へ向かいます。"
    toward = f"{heading}へ" if heading else ""
    return f"{origin}から車で{toward}向かいます。まもなく{to}に到着します。"


def _opening(text: str, name: str, line: str) -> Optional[str]:
    """`text` opened by `line`, or None when it already names the place first."""
    body = (text or "").strip()
    if body.startswith(line):
        return None
    first = re.split(r"[。！？!?]", body, maxsplit=1)[0]
    if line == STOPBY_LINE.format(name=name):
        rest = re.sub(rf"^{re.escape(name)}\s*は、?", "", body)
        return line + rest
    if name and name in first:
        return None
    return line + body


def _is_return(project_route: List[dict]) -> bool:
    first, last = project_route[0], project_route[-1]
    near = _length_km([[first["lat"], first["lng"]], [last["lat"], last["lng"]]]) <= RETURN_NEAR_KM
    return near or "return" in (last.get("label") or last.get("name") or "").lower()


def _directions(origin: str, to: str, set_mode: str, points: List[List[float]], variant: int, brief: bool = True) -> str:
    mode = tuning.MODE_ALIASES.get(set_mode, set_mode)
    pieces = split_crossings(points, mode) if mode == "walking" and set_mode == mode else []
    if brief:
        return brief_directions(origin, to, mode, pieces if len(pieces) > 1 else [], points, variant)
    if mode != "walking":
        return transit_directions(origin, to, mode, [], points)
    if len(pieces) > 1:
        return transit_directions(origin, to, mode, pieces, points)
    return walking_directions(origin, to, points, variant=variant)


def _cut_at(points: List[List[float]], lat: float, lng: float) -> tuple:
    """(segment index + fraction, [lat, lng]) of the leg's point nearest (lat, lng)."""
    *line, (px, py) = _xy(points + [[lat, lng]])
    best = (math.inf, 0.0, points[0])
    for i, ((ax, ay), (bx, by)) in enumerate(zip(line, line[1:])):
        dx, dy = bx - ax, by - ay
        seg = dx * dx + dy * dy
        u = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg)) if seg else 0.0
        d = math.hypot(ax + dx * u - px, ay + dy * u - py)
        if d < best[0]:
            a, b = points[i], points[i + 1]
            best = (d, i + u, [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u])
    return best[1], best[2]


def _between(points: List[List[float]], start: tuple, end: tuple) -> List[List[float]]:
    (s, first), (e, last) = start, end
    out = [first]
    for p in [*points[int(s) + 1:math.ceil(e)], last]:
        if p != out[-1]:
            out.append(p)
    return out if len(out) > 1 else [first, last]


def _arrivals(project: dict, waypoints: List[dict], route: List[dict], cache: dict) -> Dict[int, str]:
    """{id(waypoint): arriving text}. An unconnected stop-by is told from the
    previous stop to where the leg passes nearest it; when the walk pauses
    there (stopby_visits: the course style, with a photo), the next stop is
    told from the stop-by, as after a connected one."""
    from services.localization.overview_script import overview_style

    course = overview_style(project) == "course"
    style = (project.get("settings") or {}).get("leg_directions", tuning.DEFAULT_LEG_DIRECTIONS)
    brief = style != "turns"
    order = {id(w): i for i, w in enumerate(waypoints)}
    out: Dict[int, str] = {}
    for k in range(1, len(route)):
        a, b = route[k - 1], route[k]
        lo = order[id(a)] + 1 if k > 1 else 0
        hi = order[id(b)] if k < len(route) - 1 else len(waypoints)
        points = _leg_points(a, b, cache)
        set_mode = _leg_mode(a, b, cache)
        loose = [w for w in waypoints[lo:hi] if not on_route(w) and not w.get("skipAssetGeneration")]
        cuts = sorted(((_cut_at(points, w["lat"], w["lng"]), w) for w in loose), key=lambda c: c[0][0])
        origin, start = clean_label(a), (0.0, points[0])
        for at, w in cuts:
            out[id(w)] = _directions(origin, clean_label(w), set_mode, _between(points, start, at),
                                     len(out) if brief else k, brief)
            if course and w.get("popup_image"):
                origin, start = clean_label(w), at
        end = (float(len(points) - 1), points[-1])
        out[id(b)] = _directions(origin, clean_label(b), set_mode, _between(points, start, end),
                                 len(out) if brief else k, brief)
    return out


def build_leg_scripts(project: dict, cache: Optional[dict] = None) -> List[Dict]:
    """[{"id", "name", "arriving", "attraction"}] for every waypoint: the
    suggested text, None where nothing should change. Nothing is written."""
    cache = cache or {}
    waypoints = [w for w in project.get("waypoints", []) if isinstance(w, dict) and "lat" in w]
    route = [w for w in waypoints if on_route(w)]
    if len(route) < 2:
        return []
    position = {id(w): k for k, w in enumerate(route)}
    arrivals = _arrivals(project, waypoints, route, cache)
    returns = _is_return(route)
    start_name = clean_label(route[0])
    out = []
    for w in waypoints:
        name = clean_label(w)
        text = w.get("attractionNarration") or ""
        arriving = arrivals.get(id(w))
        k = position.get(id(w))
        if k == 0:
            attraction = _opening(text, name, START_LINE.format(name=name))
        elif k == len(route) - 1:
            line = RETURN_LINE.format(name=start_name) if returns else GOAL_LINE.format(name=name)
            attraction = None if (text or "").strip().startswith(line) else line + (text or "").strip()
        elif w.get("isStopBy"):
            attraction = _opening(text, name, STOPBY_LINE.format(name=name))
        else:
            attraction = _opening(text, name, PLACE_LINE.format(name=name)) if text.strip() else None
        out.append({"id": w.get("id"), "name": name, "arriving": arriving, "attraction": attraction})
    return out
