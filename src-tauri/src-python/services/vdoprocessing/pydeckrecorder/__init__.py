"""3D route recorder (pydeck + Playwright + ffmpeg), split by concern:

- common.py: path bootstrap, logger, Mapbox key
- httpserver.py: local static file server for Playwright
- geomath.py: bearing/offset/haversine helpers
- routedata.py: project/route loading and pydeck HTML generation
- legresolve.py: current routeMode/place-name resolution per cached leg
- popupsequence.py: shared arrival popup freeze/spin/scale/fade animation
- renderer.py: per-leg Playwright/deck.gl frame renderer
- recorder.py: top-level orchestrator (record_headless_video)
"""

from .recorder import record_headless_video

__all__ = ["record_headless_video"]
