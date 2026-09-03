"""Resolves the current routeMode/place name for a cached routing leg."""

from typing import Dict, List, Optional, Tuple

# "direct" is a straight-line routing choice, not a distinct travel mode —
# render it as walking (matches the same alias in videopipeline.py).
_MODE_ALIASES = {"direct": "walking"}


def _resolve_leg(
    route_key: str, waypoints: List[Dict]
) -> Tuple[Optional[str], Optional[str], Optional[Dict]]:
    """Looks up the CURRENT routeMode/place name for a .routecache.json leg
    by matching its cached start/end coordinates against the live
    `waypoints` array, instead of trusting enumerate(routing_cache.items())
    ordering to line up with `waypoints[leg_idx]`.

    routing_cache preserves INSERTION order (i.e. whenever each leg was
    first computed/fetched by the frontend), not the current leg sequence —
    dragging a waypoint to reorder the route, or editing its mode after the
    leg was cached, leaves that ordering (and the mode baked into the cache
    key itself, e.g. "...|direct") stale. Re-deriving both from the live
    waypoints array by coordinate keeps this in sync with whatever the
    project currently says, the same way the frontend's own routing hook
    keys each leg by its FROM-waypoint's routeMode.

    Returns (mode, place_name, from_waypoint) — any of which may be None if
    the key couldn't be parsed or no close-enough waypoint was found.
    """
    try:
        start_str, end_str, _ = route_key.split("|")
        start_lat, start_lng = (float(v) for v in start_str.split(","))
        end_lat, end_lng = (float(v) for v in end_str.split(","))
    except (ValueError, AttributeError):
        return None, None, None

    def _closest(lat: float, lng: float) -> Optional[Dict]:
        best, best_dist = None, float("inf")
        for wp in waypoints:
            wp_lat, wp_lng = wp.get("lat"), wp.get("lng", wp.get("lon"))
            if wp_lat is None or wp_lng is None:
                continue
            dist = (wp_lat - lat) ** 2 + (wp_lng - lng) ** 2
            if dist < best_dist:
                best, best_dist = wp, dist
        return best

    from_wp = _closest(start_lat, start_lng)
    to_wp = _closest(end_lat, end_lng)

    mode = None
    if from_wp is not None:
        raw_mode = str(from_wp.get("routeMode") or "").strip().lower()
        if raw_mode:
            mode = _MODE_ALIASES.get(raw_mode, raw_mode)

    place_name = to_wp.get("label") if to_wp is not None else None
    return mode, place_name, from_wp
