"""3D route recorder (pydeck + Playwright + ffmpeg), split by concern:

- common.py: path bootstrap, logger, Mapbox key
- httpserver.py: local static file server for Playwright
- geomath.py: bearing/offset/haversine helpers
- routedata.py: project/route loading and pydeck HTML generation
- legresolve.py: current routeMode/place-name resolution per cached leg
- popupsequence.py: final-destination-only PIP/fullscreen photo reveal
- recorder.py: route-line GeoJSON features shared by the leg and overview renderers
"""
