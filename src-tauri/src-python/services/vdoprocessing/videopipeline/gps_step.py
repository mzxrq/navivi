"""Step 1: Parse & clean GPS."""

import json
from pathlib import Path

from tqdm import tqdm

from services.gpsparser.gpsparser import GPSParser
from services.config.job_config import JobConfigManager

from .helpers import logger


def process_gps(raw_source_path: str) -> dict:
    """Extracts the GPS path from job_config.json, then converts and cleans the data."""
    logger.info("Processing GPS data from config: %s", raw_source_path)

    config_path = Path(raw_source_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Project configuration file missing: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config_data = json.load(f)

    gps_route_file = config_data.get("source_files", {}).get("gps_route", "N/A")
    tqdm.write(f"[Step 1/5] Processing GPS Data from: {Path(gps_route_file).name}")

    job_config = JobConfigManager(str(config_path))
    cleaned = GPSParser(job_config=job_config).clean_data()

    summary = cleaned.get("summary", {})
    logger.info(
        "Step 1 complete: %d route points, %.2f km, %s",
        summary.get("total_route_points", 0),
        summary.get("total_distance_km", 0.0),
        summary.get("total_duration_formatted", "N/A"),
    )

    return cleaned
