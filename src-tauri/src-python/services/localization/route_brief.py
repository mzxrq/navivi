"""The route as facts a narrator can tell: how each leg is travelled.

An overview narration that guides like a tour ("from the station, walk
north-west through the old town for about 12 minutes to 常行寺") needs facts
the map already has: each leg's mode, length, time, direction, how winding it
is, and the stop-bys it passes. This works them out in plain code from
job_config.json and .routecache.json - no model, no network - so a writer (an
LLM, or `transition_text` below) only has to put them into words, and every
number it may say can be checked against the brief.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from services import tuning
from services.gpsparser.gpscalculator import GPSMath

# 8-point compass, clockwise from north.
_COMPASS = ("北", "北東", "東", "南東", "南", "南西", "西", "北西")
# A leg this much longer than the straight line between its ends winds.
WINDING_RATIO = 1.4
# An unconnected stop-by at most this far from a leg's line is passed on it.
PASS_NEAR_KM = 0.3
# A walking leg's line can hide a boat: the router follows ferry lines as part
# of a walk, and those come as a long run of sparse points (land paths are
# points 10-50 m apart). A run of at least CROSSING_MIN_HOPS hops, each at
# least CROSSING_HOP_KM, adding up to CROSSING_MIN_KM, is told as a crossing.
CROSSING_HOP_KM = 0.1
CROSSING_MIN_HOPS = 6
CROSSING_MIN_KM = 1.5


def clean_label(waypoint: dict) -> str:
    label = (waypoint.get("label") or waypoint.get("name") or "").strip()
    return re.sub(r"\s*\((Return|return)\)\s*$", "", label)


# How long a stop-by's own short fact snippet (below) may run, folded into
# the via_batches line alongside its bare name — kept short since several of
# these can share one clause (see overview_script.py's via_batches insertion).
_STOPBY_FACT_CHARS = 18
# A leading "have arrived at X" announcement sentence - attractionNarration
# routinely opens with one before its real descriptive content (_short_fact
# below skips it rather than grabbing it as the "fact").
_ARRIVAL_ANNOUNCEMENT = re.compile(r"到着|たどり着")


def _is_bare_naming(sentence: str, label: str) -> bool:
    """A sentence that does little more than name the place itself
    ("こちらは『称念寺』", "『第四砲台跡』です") - not caught by
    _ARRIVAL_ANNOUNCEMENT (no 到着/たどり着), but just as empty a "fact":
    folded as "{fact}の{name}" in overview_script.py's via_batches line, it
    reads as "the X of 'this is X'" - the same place named twice in a row.
    Skipped in _short_fact the same way, so it picks the next sentence with
    real content instead."""
    from services.localization.overview_cues import name_variants

    bare = re.sub(r"[『』「」]", "", sentence).strip()
    for variant in sorted(name_variants(label), key=len, reverse=True):
        if variant in bare and len(bare) - len(variant) <= 6:
            return True
    return False


def _balance_brackets(s: str) -> str:
    """Drops a trailing unmatched opening 『 - a hard character-cut (below)
    can land inside a bracketed name, leaving it dangling with no close."""
    if s.count("『") > s.count("』"):
        s = s[: s.rfind("『")]
    return s.rstrip()


def _short_fact(waypoint: dict) -> str:
    """One short clause of what's known about an UNCONNECTED stop-by, from
    whatever the user already wrote in its attractionNarration - the field
    meant for the place's OWN descriptive content, same as
    audio_step._resolve_attraction_narration_script's own rule: "deliberately
    never arrivingNarration", since that field is a leg-arrival announcement
    ("have arrived at X"), not a description of X, and reads as broken
    nonsense spliced into a noun-phrase modifier here ("...に到着しましたの
    常行寺や..."). "" when nothing written, so the caller falls back to a
    bare name-only mention, same as before this existed."""
    text = (waypoint.get("attractionNarration") or "").strip()
    if not text:
        return ""
    text = re.sub(r"\{[^}]*\}", "", text).strip()
    # attractionNarration itself often opens with its own "arrived at X"
    # announcement sentence, or a bare "this is X" naming sentence, before
    # the real descriptive content (e.g. "『常行寺』に到着しました。天正年間に
    # 再建された歴史ある寺院で…") - skip that leading sentence rather than
    # grabbing it as the "fact", which read as broken nonsense spliced into a
    # noun-phrase modifier ("…に到着しましたの常行寺や…") or a duplicated name
    # ("…こちらは『称念寺』の称念寺や…").
    sentences = [s.strip() for s in re.split(r"[。！？\n]", text) if s.strip()]
    label = clean_label(waypoint)
    first = next(
        (s for s in sentences if not _ARRIVAL_ANNOUNCEMENT.search(s) and not _is_bare_naming(s, label)),
        "",
    )
    if not first:
        return ""
    if len(first) <= _STOPBY_FACT_CHARS:
        candidate = first
    else:
        # Too long for the shared clause (this is folded alongside other
        # names in via_batches's one sentence - see overview_script.py). Cut
        # at the last comma within budget rather than a hard character cut +
        # "…": a comma is already a natural clause break in Japanese, so
        # "天正年間に再建された歴史ある寺院で" reads as a complete noun-phrase
        # modifier on its own, spoken cleanly - a trailing ellipsis
        # mid-clause (TTS doesn't pronounce it cleanly, and "…の{name}" sounds
        # like the sentence just stops and restarts) doesn't. Either way,
        # _balance_brackets guards against the cut landing inside a
        # 『bracketed name』.
        within_budget = first[:_STOPBY_FACT_CHARS]
        cut_at = within_budget.rfind("、")
        candidate = _balance_brackets(within_budget[:cut_at] if cut_at > 0 else within_budget)
    # Only usable as the "{fact}の{name}" noun-phrase modifier (see
    # overview_script.py's via_batches insertion) when it actually ends in a
    # connector that attaches that way - で/な (the "〜でのX"/"〜なX" pattern,
    # e.g. "歴史ある寺院での常行寺") or a bare の. A full predicate clause
    # ("小さなお寺ですが") or a plain verb ("…として知られる") doesn't, and
    # gluing "の" onto one of those reads as broken Japanese
    # ("ですがの常行寺", "知られるの加太春日神社"). Safer to fall back to the
    # bare name for this one than ship broken grammar.
    return candidate if re.search(r"[でなの]$", candidate) else ""


def on_route(waypoint: dict) -> bool:
    """A waypoint the walker actually goes to (an unconnected stop-by is only
    seen from the route)."""
    return not (waypoint.get("isStopBy") and not waypoint.get("connectToRoute"))


def heading(from_lat: float, from_lng: float, to_lat: float, to_lng: float) -> str:
    """Compass direction from one point to another, as the 8-point name."""
    phi1, phi2 = math.radians(from_lat), math.radians(to_lat)
    dlng = math.radians(to_lng - from_lng)
    x = math.sin(dlng) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlng)
    degrees = (math.degrees(math.atan2(x, y)) + 360.0) % 360.0
    return _COMPASS[int((degrees + 22.5) // 45) % 8]


def _length_km(points: List[List[float]]) -> float:
    if len(points) < 2:
        return 0.0
    import numpy as np

    arr = np.asarray(points, dtype=float)
    return float(np.nansum(GPSMath.haversine_vectorized(arr[:-1, 0], arr[:-1, 1], arr[1:, 0], arr[1:, 1])))


def _nearest_km(points: List[List[float]], lat: float, lng: float) -> float:
    import numpy as np

    arr = np.asarray(points, dtype=float)
    return float(np.min(GPSMath.haversine_vectorized(arr[:, 0], arr[:, 1], lat, lng)))


def _hops_km(points: List[List[float]]):
    import numpy as np

    arr = np.asarray(points, dtype=float)
    return GPSMath.haversine_vectorized(arr[:-1, 0], arr[:-1, 1], arr[1:, 0], arr[1:, 1])


def split_crossings(points: List[List[float]], mode: str) -> List[dict]:
    """The leg as [{"mode", "km"}] pieces: one piece, unless a walking leg
    hides a boat crossing (see CROSSING_*), which splits it walk/ferry/walk."""
    whole = [{"mode": mode, "km": _length_km(points)}]
    if mode != "walking" or len(points) < CROSSING_MIN_HOPS + 1:
        return whole
    hops = [float(h) for h in _hops_km(points)]
    runs, start = [], None
    for i, h in enumerate(hops + [0.0]):
        if h >= CROSSING_HOP_KM and start is None:
            start = i
        elif h < CROSSING_HOP_KM and start is not None:
            runs.append((start, i))
            start = None
    runs = [(a, b) for a, b in runs if b - a >= CROSSING_MIN_HOPS and sum(hops[a:b]) >= CROSSING_MIN_KM]
    if not runs:
        return whole
    pieces, at = [], 0
    for a, b in runs:
        if a > at:
            pieces.append({"mode": "walking", "km": sum(hops[at:a])})
        pieces.append({"mode": "ferry", "km": sum(hops[a:b])})
        at = b
    if at < len(hops):
        pieces.append({"mode": "walking", "km": sum(hops[at:])})
    return pieces


def _leg_mode(from_wp: dict, to_wp: dict, cache: dict) -> str:
    """The leg's mode as the project set it ("draw" and "direct" included)."""
    from services.vdoprocessing.videopipeline.helpers import _resolve_leg_mode_from_cache

    mode = from_wp.get("routeMode") or _resolve_leg_mode_from_cache(from_wp, to_wp, cache) or "walking"
    return str(mode).lower()


def _leg_points(from_wp: dict, to_wp: dict, cache: dict) -> List[List[float]]:
    from services.vdoprocessing.videopipeline.helpers import _resolve_leg_geometry_from_cache

    geometry = _resolve_leg_geometry_from_cache(from_wp, to_wp, cache)
    if geometry:
        return [[float(p[0]), float(p[1])] for p in geometry]
    return [[from_wp["lat"], from_wp["lng"]], [to_wp["lat"], to_wp["lng"]]]


def stopby_holds(project: dict) -> Tuple[Dict[int, float], float]:
    """({id(waypoint): seconds}, start seconds): how long the overview freezes
    at a waypoint that hosts a batch of stop-by cards, the same way the
    renderer groups them (SpatialRenderer._attach_stopby_groups): each real
    waypoint hosts the stop-bys after it, unless the first of them is
    connected, which then hosts the rest. A host freezes for the post-arrival
    hold + its own card + STOPBY_BATCH_SECONDS per stop-by
    (overview.py's _hold_frames); the start pin only plays the batch."""
    settings = project.get("settings", {})
    post = float(settings.get("post_arrival_hold_seconds", 1.0))
    waypoints = [w for w in project.get("waypoints", []) if isinstance(w, dict)]
    groups: Dict[int, int] = {}
    names: Dict[int, List[str]] = {}
    facts: Dict[int, List[str]] = {}
    places: Dict[int, List[List[float]]] = {}
    host, first_of_run = None, False
    for w in waypoints:
        if w.get("skipAssetGeneration") and w is not waypoints[0] and w is not waypoints[-1]:
            continue  # passed with a pip card, never part of a batch (popups.py)
        is_effectively_stopby = w.get("isStopBy") and not (w.get("connectToRoute") and w.get("pauseAtWaypoint") is not False)
        if not is_effectively_stopby:
            host, first_of_run = w, True
            groups[id(w)] = 0
            continue
        if host is not None and first_of_run and w.get("connectToRoute"):
            host, first_of_run = w, False
            groups[id(w)] = 0
            continue
        first_of_run = False
        if host is not None:
            groups[id(host)] += 1
            names.setdefault(id(host), []).append(clean_label(w))
            facts.setdefault(id(host), []).append(_short_fact(w))
            places.setdefault(id(host), []).append([w.get("lat"), w.get("lng")])
    stopby_holds.names = names  # the stop-bys each host shows (see build_brief)
    stopby_holds.facts = facts  # each one's own short fact, "" when none written
    stopby_holds.places = places  # each one's [lat, lng] (the outro finds its photo by it)
    holds: Dict[int, float] = {}
    start = 0.0
    for w in waypoints:
        count = groups.get(id(w), 0)
        if not count:
            continue
        # Only STOPBY_BATCH_MAX_HELD of them get a held card in the actual
        # render (overview.py's _hold_frames / overview_animation.py's
        # _play_stopby_batch) — mirror that cap here so the script's own
        # time budget matches what the video actually holds for.
        held = min(count, tuning.STOPBY_BATCH_MAX_HELD)
        if w is waypoints[0]:
            start = held * tuning.STOPBY_BATCH_SECONDS
            continue
        card = min(float(w.get("freeze_seconds", 2.0)), tuning.POPUP_FREEZE_SECONDS_MAX)
        holds[id(w)] = post + max(card, tuning.POPUP_MIN_DISPLAY_SECONDS) + held * tuning.STOPBY_BATCH_SECONDS
    return holds, start


def build_brief(project: dict, routing_cache: Optional[dict] = None) -> dict:
    """{"start": label, "legs": [...], "total_km", "total_minutes"}. Each leg:
    {"from", "to", "to_number" (the overview's {n} for the stop it reaches, or
    None), "mode", "km", "minutes", "pieces": [{"mode", "km", "minutes"}] (more
    than one when a walk includes a boat crossing), "heading", "winding",
    "passes": [labels], "is_return"}."""
    from services.localization.overview_script import visible_waypoints

    cache = routing_cache or {}
    waypoints = [w for w in project.get("waypoints", []) if isinstance(w, dict) and "lat" in w]
    numbers = {id(w): n for n, w in enumerate(visible_waypoints(project), start=1)}
    speeds = {
        **tuning.REPORTED_MODE_SPEED_KMH,
        **{str(k).lower(): float(v) for k, v in (project.get("settings", {}).get("mode_speeds_kmh") or {}).items()},
    }
    route = [w for w in waypoints if on_route(w)]
    seen_only = [w for w in waypoints if not on_route(w)]
    holds, start_hold = stopby_holds(project)

    legs = []
    for a, b in zip(route, route[1:]):
        set_mode = _leg_mode(a, b, cache)
        mode = tuning.MODE_ALIASES.get(set_mode, set_mode)
        points = _leg_points(a, b, cache)
        km = _length_km(points)
        straight = _length_km([[a["lat"], a["lng"]], [b["lat"], b["lng"]]])
        pieces = [
            {
                "mode": piece["mode"],
                "km": round(piece["km"], 2),
                "minutes": max(1, int(round(
                    piece["km"] / (speeds.get(piece["mode"]) or speeds.get("walking", 3.0)) * 60
                ))),
            }
            # Only a routed line can hide a crossing: a hand-drawn one ("draw")
            # is as sparse as the user clicked it, and "direct" is a straight line.
            for piece in (
                split_crossings(points, mode) if set_mode == mode
                else [{"mode": mode, "km": km}]
            )
        ]
        legs.append({
            "from": clean_label(a),
            "to": clean_label(b),
            "to_number": numbers.get(id(b)),
            "mode": mode,
            "km": round(km, 2),
            "minutes": sum(piece["minutes"] for piece in pieces),
            "pieces": pieces,
            "heading": heading(a["lat"], a["lng"], b["lat"], b["lng"]),
            "winding": bool(straight > 0.05 and km / straight >= WINDING_RATIO),
            "passes": [],
            "is_return": b is route[-1] and "return" in (b.get("label") or "").lower(),
            # seconds the overview freezes on arriving at `to` (a stop-by batch)
            # and the stop-bys whose cards it shows then
            "hold_at_to": round(holds.get(id(b), 0.0), 2),
            "batch": list(stopby_holds.names.get(id(b), [])),
            "batch_facts": list(stopby_holds.facts.get(id(b), [])),
            "batch_at": list(stopby_holds.places.get(id(b), [])),
            "from_id": a.get("id"),
            "to_id": b.get("id"),
            "from_at": [a["lat"], a["lng"]],
            "to_at": [b["lat"], b["lng"]],
            "_points": points,
        })
    # Each unconnected stop-by is passed on the leg whose line comes closest.
    for w in seen_only:
        near = [(_nearest_km(leg["_points"], w["lat"], w["lng"]), leg) for leg in legs]
        near = [(d, leg) for d, leg in near if d <= PASS_NEAR_KM]
        if near:
            min(near, key=lambda item: item[0])[1]["passes"].append(clean_label(w))
    for leg in legs:
        del leg["_points"]
    return {
        "start": clean_label(route[0]) if route else "",
        "start_hold": start_hold,
        # the stop-bys shown at the start pin, which no leg arrives at
        "start_batch": list(stopby_holds.names.get(id(route[0]), [])) if route else [],
        "start_batch_at": list(stopby_holds.places.get(id(route[0]), [])) if route else [],
        "legs": legs,
        "total_km": round(sum(l["km"] for l in legs), 2),
        "total_minutes": sum(l["minutes"] for l in legs),
    }


def load_brief(project_config_path: str) -> dict:
    """build_brief for a project on disk (its route cache in .navivi)."""
    from services.projectfiles import ROUTE_CACHE, meta_file

    config_path = Path(project_config_path)
    project = json.loads(config_path.read_text(encoding="utf-8"))
    try:
        cache = json.loads(meta_file(config_path.parent, ROUTE_CACHE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cache = {}
    return build_brief(project, cache)


def journeys(brief: dict, stops: Optional[set] = None) -> List[dict]:
    """The legs grouped into the trips between the overview stops the walker
    stops at (`stops`: their numbers; default every numbered stop): from the
    start (or a stop) to the next, and from the last to the end. Places passed
    on the way are `via`; `via_hold` is how long the map freezes on the way
    (stop-by batches there, and at the start for the first trip), `hold_at_to`
    the freeze on arriving. Same shape as a leg, so `transition_text` tells
    either."""
    groups: List[List[dict]] = [[]]
    for leg in brief["legs"]:
        groups[-1].append(leg)
        if leg["to_number"] is not None and (stops is None or leg["to_number"] in stops):
            groups.append([])
    out = []
    for legs in (g for g in groups if g):
        pieces: List[dict] = []
        for leg in legs:
            for piece in leg.get("pieces") or [{"mode": leg["mode"], "km": leg["km"], "minutes": leg["minutes"]}]:
                if pieces and pieces[-1]["mode"] == piece["mode"]:
                    pieces[-1] = {
                        "mode": piece["mode"],
                        "km": round(pieces[-1]["km"] + piece["km"], 2),
                        "minutes": pieces[-1]["minutes"] + piece["minutes"],
                    }
                else:
                    pieces.append(dict(piece))
        by_mode: Dict[str, float] = {}
        for piece in pieces:
            by_mode[piece["mode"]] = by_mode.get(piece["mode"], 0.0) + piece["km"]
        first, last = legs[0], legs[-1]
        out.append({
            "from": first["from"],
            "to": last["to"],
            "to_number": last["to_number"],
            "mode": max(by_mode, key=by_mode.get),
            "km": round(sum(l["km"] for l in legs), 2),
            "minutes": sum(p["minutes"] for p in pieces),
            "pieces": pieces,
            "heading": heading(*first["from_at"], *last["to_at"]),
            "winding": any(l["winding"] for l in legs),
            "passes": [p for l in legs for p in l["passes"]],
            "via": [l["to"] for l in legs[:-1]],
            "via_numbers": [l["to_number"] for l in legs[:-1]],
            # km into the trip at which each via place is reached
            "via_km": [round(sum(x["km"] for x in legs[:k + 1]), 2) for k in range(len(legs) - 1)],
            "leg_facts": [(l["heading"], l["minutes"], l["km"]) for l in legs],
            "via_hold": round(
                sum(l.get("hold_at_to", 0.0) for l in legs[:-1])
                + (brief.get("start_hold", 0.0) if not out else 0.0), 2
            ),
            "hold_at_to": last.get("hold_at_to", 0.0),
            "batch": list(last.get("batch", [])),
            "legs": len(legs),
            # (host, [stop-bys], [each one's own short fact, "" when none
            # written]) for every batch shown on the way
            "via_batches": [
                (l["to"], l["batch"], l.get("batch_facts") or [""] * len(l["batch"]))
                for l in legs[:-1] if l.get("batch")
            ],
            "is_return": last["is_return"],
            "from_at": first["from_at"],
            "to_at": last["to_at"],
        })
    return out


def _minutes_phrase(minutes: int) -> str:
    return f"{minutes}分ほど" if minutes < 60 else f"{minutes // 60}時間{minutes % 60}分ほど" if minutes % 60 else f"{minutes // 60}時間ほど"


# (lead, how the walk ends) for a walking leg, rotated per leg so five legs
# in a row don't all say "次は…へ。…歩くと、…です。"
_WALK_WORDINGS = [
    ("次は{h}へ。", "{time}歩くと、{to}です。"),
    ("続いて{h}へ。", "{time}進むと、{to}に着きます。"),
    ("ここから{h}へ。", "{time}歩いて、{to}を目指します。"),
    ("道は{h}へと続きます。", "{time}で、{to}です。"),
]
LONGEST_LEG_MIN_MINUTES = 30


def transition_texts(leg: dict, variant: int = 0) -> List[str]:
    """Ways to tell one leg from its facts only, longest first: the fallback
    when no model is used or its text fails the checks. The long form names
    what is passed on the way; the shortest only where it goes. `variant`
    picks the walking wording; leg["longest"] adds a "longest stretch" lead."""
    to = leg["to"]
    arrive = "へ戻ります" if leg["is_return"] else "へ向かいます"
    via = leg.get("via") or []
    # Every via/passes name, never truncated: this used to cap at the first
    # 2 (via[:2]/passes[:2]), silently dropping any further waypoint from
    # ever being named ANYWHERE in the script if this leg's own "through"
    # variant (below) also didn't fit the character budget and lost out to
    # this fallback. A waypoint not chosen as its own numbered stop by
    # plan_budget still deserves to be named once, here.
    passes = (
        f"{'や'.join(via)}に立ち寄りながら、" if via
        else f"{'や'.join(leg['passes'])}を眺めながら、" if leg["passes"] else ""
    )
    pieces = leg.get("pieces") or [{"mode": leg["mode"], "minutes": leg["minutes"]}]
    time = _minutes_phrase(leg["minutes"])
    short = f"{to}{arrive}。"
    if len(pieces) > 1:  # walk / boat / walk
        steps = []
        for piece in pieces:
            piece_time = _minutes_phrase(piece["minutes"])
            steps.append(f"船で{piece_time}渡り" if piece["mode"] == "ferry" else f"{piece_time}歩き")
        head = "最後は" if leg["is_return"] else "ここからは"
        boat = _minutes_phrase(next(p["minutes"] for p in pieces if p["mode"] == "ferry"))
        return [f"{head}、{passes}{'、'.join(steps)}、{to}{arrive}。",
                f"船で{boat}渡り、{to}{arrive}。", f"船で{to}{arrive}。"]
    if leg["mode"] == "ferry":
        return [f"{leg['from']}から船に乗り、{time}で{to}へ渡ります。", f"船で{time}、{to}へ。", f"船で{to}へ。"]
    if leg["mode"] in ("car", "driving"):
        return [f"ここからは車で{leg['heading']}へ。{passes}{time}走って、{to}{arrive}。",
                f"車で{time}、{to}{arrive}。", short]
    if leg["mode"] == "airplane":
        return [f"ここからは空の旅。{time}で{to}{arrive}。", f"空路で{to}へ。"]
    if leg["is_return"]:
        return [f"最後は、{passes}{time}歩いて{to}{arrive}。", f"{time}歩いて{to}{arrive}。", short]
    road = "曲がりくねった道を" if leg["winding"] else ""
    # Past several stops: name them all, so the line lasts while the walker
    # goes by each one (a bare "南西へ33分ほど" is over before the second).
    through = [f"{leg['heading']}へ。{'、'.join(via)}を通って、{time}で{to}へ。"] if len(via) > 1 else []
    # A winding leg's road phrase can push the longest candidate just over
    # its budget, dropping straight to the much shorter "heading+time+へ"
    # one below and leaving most of that budget unused - this middle tier
    # (same sentence, no road phrase) catches that case.
    lead, walk = _WALK_WORDINGS[variant % len(_WALK_WORDINGS)]
    lead = lead.format(h=leg["heading"])
    walk = walk.format(time=time, to=to)
    full = f"{lead}{passes}{road}{walk}"
    longest = [f"ここからが一番長い区間です。{full}"] if leg.get("longest") else []
    plain = [f"{lead}{passes}{walk}"] if road else []
    return [*longest, full, *plain, *through, f"{leg['heading']}へ{time}、{to}へ。", f"{to}へ。"]


def transition_text(leg: dict, limit: Optional[int] = None, variant: int = 0) -> str:
    """The longest of `transition_texts` that fits in about `limit` characters
    (the shortest when none does) - but never one that drops a via/passes
    name the longer candidates named: some of transition_texts's own
    shorter fallbacks (e.g. the walk/boat/walk branch's "船で13分渡り、Xへ"
    variant) exist for legs with NO via/passes at all, yet still get
    offered as a fallback even when one exists, silently dropping the only
    place this leg's own via/passes waypoint would ever be named. Filters
    to only the candidates that still name everyone first; only falls back
    to the unfiltered list if somehow none do (shouldn't happen -
    transition_texts's own longest candidate always includes them)."""
    texts = transition_texts(leg, variant)
    required = list(leg.get("via") or []) + list(leg.get("passes") or [])
    if required:
        named = [t for t in texts if all(name in t for name in required)]
        texts = named or texts
    if limit is None:
        return texts[0]
    fit = next((t for t in texts if len(t) <= limit * 1.15), None)
    if fit is not None:
        return fit
    if required:
        # None of the full-detail named candidates fit even loosely (they
        # carry mode/time/distance breakdowns on top of every name) -
        # rather than either falling through to texts[-1] (which drops
        # every name, defeating the guarantee above) or keeping a
        # far-over-budget sentence, name everyone in the fewest words:
        # just the names and the destination.
        return f"{'、'.join(required)}を経て、{leg['to']}へ。"
    return texts[-1]
