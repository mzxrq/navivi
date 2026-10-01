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
_OPTIONAL_ROUTE_INPUT_FIELDS = ("skipAssetGeneration",)


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
