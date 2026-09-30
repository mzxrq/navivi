"""What the user actually edits about a route: the waypoints' positions and
how each leg is travelled. Render checkpoints key on this, not on the saved
GPX line, because the app re-fetches walking routes from the routing services
on load and can save a different line (or straight-line placeholders) without
any edit."""

import hashlib
import json
from typing import Iterable

_ROUTE_INPUT_FIELDS = (
    "lat", "lng", "routeMode", "customRoute", "viaPoints", "drawStyle", "isStopBy", "connectToRoute",
)


def route_inputs_hash(waypoints: Iterable) -> str:
    rows = [
        {k: wp.get(k) for k in _ROUTE_INPUT_FIELDS} if isinstance(wp, dict) else wp
        for wp in waypoints or []
    ]
    blob = json.dumps(rows, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
