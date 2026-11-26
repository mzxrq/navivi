"""What the user actually edits about a route: the waypoints' positions and
how each leg is travelled. Render checkpoints key on this, not on the saved
GPX line, because the app re-fetches walking routes from the routing services
on load and can save a different line (or straight-line placeholders) without
any edit."""

import hashlib
import os
import json
from typing import Iterable

_ROUTE_INPUT_FIELDS = (
    "lat", "lng", "routeMode", "customRoute", "viaPoints", "drawStyle", "isStopBy", "connectToRoute",
)


# Added later: hashed only when set, so older waypoints keep the same hash.
_OPTIONAL_ROUTE_INPUT_FIELDS = ("skipAssetGeneration", "inaccessible")


def _row(wp):
    if not isinstance(wp, dict):
        return wp
    row = {k: wp.get(k) for k in _ROUTE_INPUT_FIELDS}
    row.update({k: wp[k] for k in _OPTIONAL_ROUTE_INPUT_FIELDS if wp.get(k)})
    return row


def route_inputs_hash(waypoints: Iterable) -> str:
    rows = [_row(wp) for wp in waypoints or []]
    blob = json.dumps(rows, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def labels_hash(waypoints: Iterable) -> str:
    """The stops' names, which the overview's cards and the legs' banners show."""
    rows = [wp.get("label") if isinstance(wp, dict) else None for wp in waypoints or []]
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def overview_flags_hash(waypoints: Iterable) -> str:
    """The per-waypoint toggles only the overview uses ("Pause at Location")."""
    rows = [
        wp.get("pauseAtWaypoint") is not False if isinstance(wp, dict) else True
        for wp in waypoints or []
    ]
    return hashlib.sha256(json.dumps(rows).encode("utf-8")).hexdigest()[:16]


_PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".svg")


def photo_inputs_hash(obj) -> str:
    """The photos a render shows: every image path found anywhere in `obj`,
    with its size and mtime, so a different (e.g. upscaled) or replaced
    photo re-renders while every other edit still doesn't."""
    found = []

    def walk(value):
        if isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, (list, tuple)):
            for v in value:
                walk(v)
        elif isinstance(value, str) and value.lower().endswith(_PHOTO_EXTS):
            try:
                st = os.stat(value)
                found.append((value, st.st_size, int(st.st_mtime)))
            except OSError:
                found.append((value, None, None))

    walk(obj)
    blob = json.dumps(found, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def stop_is_numbered(waypoints: list, pos: int) -> bool:
    """Whether the stop at `pos` takes the next overview pin number (overview.py's order): every stop, never a
    stop-by (the walker passes every one of them, connected to the route or not), never a stop skipped in video
    export, and never a return stop - it shows again the number of the stop it comes back to."""
    waypoint = waypoints[pos]
    return (not waypoint.get("skipAssetGeneration") and not waypoint.get("isStopBy")
            and returns_to(waypoints, pos) is None)


def returns_to(waypoints: list, pos: int):
    """The position of the earlier stop that a return stop ("Add return stop": a copy at the same spot) comes
    back to, else None. A stop-by beside an earlier stop is its own place; the trip's last stop ends the video
    like any finish. `waypoints` may be popup dicts, which spell the flag "is_stopby"."""
    if not 0 < pos < len(waypoints) - 1 or waypoints[pos].get("isStopBy") or waypoints[pos].get("is_stopby"):
        return None
    return next((i for i, w in enumerate(waypoints[:pos])
                 if not (w.get("isStopBy") or w.get("is_stopby")) and same_place(waypoints[pos], w)), None)


def stopby_labels(waypoints: list) -> dict:
    """{position: "+N"} for every stop-by and stop skipped in video export, counted in route order. The start, the
    end and closed places take none; a return to one of them shows the first visit's."""
    labels, count = {}, 0
    for pos in range(1, len(waypoints) - 1):
        wp = waypoints[pos]
        if wp.get("inaccessible"):
            continue
        back = returns_to(waypoints, pos)
        if back in labels:
            labels[pos] = labels[back]
        elif wp.get("isStopBy") or wp.get("skipAssetGeneration"):
            count += 1
            labels[pos] = f"+{count}"
    return labels


def is_stopby_label(label) -> bool:
    """Whether a pin glyph is a stop-by's: "+N", or the plain "・" of one with no number (closed, start or end)."""
    return label == "・" or str(label or "").startswith("+")


def same_place(a: dict, b: dict) -> bool:
    """Two waypoints at the same real-world spot (a return stop and the stop it copies), within
    tuning.LOOP_ROUTE_MATCH_DEGREES (~30 m) - the one rule the legs and the overview both use."""
    from services import tuning

    if a.get("lat") is None or b.get("lat") is None:
        return False
    tol = tuning.LOOP_ROUTE_MATCH_DEGREES
    return (abs(float(a["lat"]) - float(b["lat"])) <= tol
            and abs(float(a.get("lng", a.get("lon")) or 0) - float(b.get("lng", b.get("lon")) or 0)) <= tol)
