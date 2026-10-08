"""Whether the walk visits a stop-by.

A connected stop-by (connectToRoute) is always visited: the leg pauses there
on a fullscreen photo, it has its own narration and attraction clip. An
unconnected one is only passed. The "course" overview type (settings.
overview_style) visits every stop-by that has a photo, connected or not: the
leg pauses at the nearest point of the route. The pipeline sets this once per
run (set_visit_all_stopbys), the same way audio_step.set_route_only_legs works.
"""

_VISIT_ALL = False


def set_visit_all_stopbys(on: bool) -> None:
    global _VISIT_ALL
    _VISIT_ALL = bool(on)


def visit_all_stopbys() -> bool:
    return _VISIT_ALL


def visits_stopby(waypoint: dict) -> bool:
    """A stop-by the walk stops at (see the module docstring); False for any
    other waypoint and for one skipped in video export."""
    if not isinstance(waypoint, dict) or not waypoint.get("isStopBy") or waypoint.get("skipAssetGeneration"):
        return False
    return bool(waypoint.get("connectToRoute")) or (_VISIT_ALL and bool(waypoint.get("popup_image")))
