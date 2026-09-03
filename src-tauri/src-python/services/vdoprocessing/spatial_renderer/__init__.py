"""Spatial Renderer Service — proximity-based triggering for the legacy
overview and waypoint maps, split by concern:

- base.py: __init__, mode-speed config, job-config/heading helpers (_SpatialRendererBase)
- pins.py: waypoint pin coloring, declutter fan-out, drawing (_PinMixin)
- popups.py: flow-through popup layout, baked-popup lifecycle, recap frame (_PopupMixin)
- transitions.py: cut/fade + blur-out transitions, recap/summary, ending highlight (_TransitionMixin)
- overview.py: render_overview — the full-route animation entry point (_OverviewRenderMixin)
- waypoints.py: render_waypoints — the per-residential-leg entry point (_WaypointRenderMixin)

`SpatialRenderer` composes all of the above, preserving the exact same
method set/behavior as the original single-file class.
"""

from .base import _SpatialRendererBase
from .overview import _OverviewRenderMixin
from .pins import _PinMixin
from .popups import _PopupMixin
from .transitions import _TransitionMixin
from .waypoints import _WaypointRenderMixin


class SpatialRenderer(
    _OverviewRenderMixin,
    _WaypointRenderMixin,
    _TransitionMixin,
    _PinMixin,
    _PopupMixin,
    _SpatialRendererBase,
):
    pass


__all__ = ["SpatialRenderer"]
