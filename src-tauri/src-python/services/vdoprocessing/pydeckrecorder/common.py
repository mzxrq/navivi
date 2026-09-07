"""Shared setup for the pydeckrecorder package: path bootstrap, logger, Mapbox key.

Kept dependency-free (no sibling imports) so every other module in this
package — recorder.py, routedata.py, renderer.py — can import from here
without risking a circular import.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Walk up from this file until we hit the `src-python/` dir (this file
# lives 3 levels under it: src-python/services/vdoprocessing/pydeckrecorder/).
# A fixed `.parent.parent` here previously landed one level short, on
# `src-python/services/` instead -- which silently broke both the '/assets/'
# 3D model URLs (recorder.py serves them from project_root/assets) and the
# .env lookup below (MAPBOX_API_KEY never loaded, models 404'd as a result).
# Walking up by name instead of a fixed depth survives future re-nesting.
project_root = Path(__file__).resolve().parent
while project_root.name != "src-python" and project_root.parent != project_root:
    project_root = project_root.parent
sys.path.append(str(project_root))

from services.logger.logger import setup_logger

logger = setup_logger("3D Video Recorder")

# Load src-python/.env (MAPBOX_API_KEY, etc.) into the process environment.
# Explicit path rather than dotenv's auto-search, since the CWD this runs
# from (launched by the Tauri sidecar) isn't guaranteed to be src-python --
# same reasoning as mapfetcher/maptile.py's load_dotenv call.
load_dotenv(project_root / ".env")

# Set your Mapbox Access Token here or load it from environment/config
MAPBOX_API_KEY = os.getenv("MAPBOX_API_KEY", "YOUR_MAPBOX_ACCESS_TOKEN_HERE")
