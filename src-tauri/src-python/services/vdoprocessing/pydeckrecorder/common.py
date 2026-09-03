"""Shared setup for the pydeckrecorder package: path bootstrap, logger, Mapbox key.

Kept dependency-free (no sibling imports) so every other module in this
package — recorder.py, routedata.py, renderer.py — can import from here
without risking a circular import.
"""

import os
import sys
from pathlib import Path

# One level up from this file's own package dir is `vdoprocessing/` — the
# same directory the original standalone pydeckrecorder.py lived in, so this
# reproduces its sys.path bootstrap (for running this package's __main__
# block directly) unchanged. Must run before the `services.*` import below.
current_dir = Path(__file__).resolve().parent.parent
project_root = current_dir if current_dir.name == "src-python" else current_dir.parent
sys.path.append(str(project_root))

from services.logger.logger import setup_logger

logger = setup_logger("3D Video Recorder")

# Set your Mapbox Access Token here or load it from environment/config
MAPBOX_API_KEY = os.getenv("MAPBOX_API_KEY", "YOUR_MAPBOX_ACCESS_TOKEN_HERE")
