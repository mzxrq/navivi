"""
Map Engine Service (map_engine.py)
---------------------------------------------------------------------------
Handles geometry smoothing, time pacing, and downloading map tiles.
Extracted from mapfetcher.py to improve modularity.
---------------------------------------------------------------------------
"""
# [I/O] Import libraries for map fetching and geometry processing

# [I/O] Import service dependencies for Integration
from services.logger.logger import setup_logger
from services.mapfetcher.mapgeometry import RouteGeometryProcessor as RouteGeometry
from services.mapfetcher.mappacing import RoutePacingProcessor as RoutePacing
from services.mapfetcher.maptile import TileDownloader

# [Utility] Log setup for debugging and monitoring
logger = setup_logger("MapEngine")


__all__ = ["RouteGeometry", "RoutePacing", "TileDownloader"]