"""3D route recorder (pydeck + Playwright + ffmpeg), split by concern:

- common.py: path bootstrap, logger, Mapbox key
- httpserver.py: local static file server for Playwright
- geomath.py: haversine distances
- routedata.py: route interpolation and pydeck HTML patching
- popupsequence.py: _wait_for_paint
- recorder.py: route-line GeoJSON features shared by the leg and overview renderers
"""
