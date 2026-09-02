"""
Map Engine Service (map_engine.py)
---------------------------------------------------------------------------
Handles geometry smoothing, time pacing, and downloading map tiles.
Extracted from mapfetcher.py to improve modularity.
---------------------------------------------------------------------------
"""
# [I/O] Import libraries for map fetching and geometry processing
from typing import Final

# [I/O] Import service dependencies for Integration
from services.logger.logger import setup_logger
from services.config.job_config import JobConfigManager
from services.mapfetcher.mapgeometry import RouteGeometryProcessor as RouteGeometry
from services.mapfetcher.mappacing import RoutePacingProcessor as RoutePacing
from services.mapfetcher.maptile import TileDownloader

# [Utility] Log setup for debugging and monitoring
logger = setup_logger("MapEngine")

# [Final] Constants for map tile downloading and geometry processing
TARGET_ASPECT_RATIO: Final[float] = 16 / 9
MIN_MAP_WIDTH_PX: Final[int] = 800

__all__ = ["RouteGeometry", "RoutePacing", "TileDownloader"]