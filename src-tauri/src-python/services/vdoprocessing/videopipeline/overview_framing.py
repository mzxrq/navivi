"""The overview map's framing: padding by route size, the bands kept clear for captions, the bounding box,
map images dropped when the map language changes, and the course overview's extra config."""

import math
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from services.localization.overview_script import course_summary, course_taglines, overview_style
from services.localization.route_brief import load_brief
from services.gpsparser.gpscalculator import GPSMath
from services import tuning

from .helpers import logger


def _adaptive_overview_padding(route_df: pd.DataFrame) -> float:
    """Picks the overview map's padding_factor from the route's own
    bounding-box diagonal distance (km) — see tuning.OVERVIEW_PADDING_BY_SPAN_KM.
    Falls back to the old flat 10% if the span can't be computed (e.g. a
    single-point route)."""
    try:
        min_lat, max_lat = route_df["latitude"].min(), route_df["latitude"].max()
        min_lon, max_lon = route_df["longitude"].min(), route_df["longitude"].max()
        span_km = float(
            GPSMath.haversine_vectorized(
                np.array([min_lat]), np.array([min_lon]),
                np.array([max_lat]), np.array([max_lon]),
            )[0]
        )
    except (KeyError, ValueError, IndexError):
        return 0.10

    for max_span, padding in tuning.OVERVIEW_PADDING_BY_SPAN_KM:
        if span_km <= max_span:
            return padding
    return tuning.OVERVIEW_PADDING_MAX_SPAN


# The overview map's size (MapFetcher.fetch_image's default output_size).
OVERVIEW_FRAME_SIZE = (1920, 1080)


def _reserve_overview_bands(
    bbox: dict, frame_size: tuple[int, int], top_px: float, bottom_px: float
) -> dict:
    """Grows `bbox` to the frame's aspect (Web Mercator) so the route fits between
    a top band of `top_px` and a bottom band of `bottom_px`, centered in that gap."""
    R = 6378137.0
    w, h = frame_size
    usable_h = max(1.0, h - top_px - bottom_px)

    def merc_y(lat):
        return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * R

    def merc_lat(y):
        return math.degrees(2 * math.atan(math.exp(y / R)) - math.pi / 2)

    y_min, y_max = merc_y(bbox["min_lat"]), merc_y(bbox["max_lat"])
    x_span = math.radians(bbox["max_lon"] - bbox["min_lon"]) * R
    scale = max(x_span / w, (y_max - y_min) / usable_h)

    top_y = y_max + top_px * scale + (usable_h * scale - (y_max - y_min)) / 2
    half_lon = math.degrees(w * scale / R) / 2
    mid_lon = (bbox["min_lon"] + bbox["max_lon"]) / 2
    return {
        "min_lat": merc_lat(top_y - h * scale),
        "max_lat": merc_lat(top_y),
        "min_lon": mid_lon - half_lon,
        "max_lon": mid_lon + half_lon,
    }


_MAP_LANGUAGE_STAMP = ".map_language"


def purge_map_images_on_language_change(project_dir, language: Optional[str]) -> bool:
    """Deletes the project's map pictures (overview and each leg's tile) when the map
    language they were made for is not the current one; they are fetched again right
    after. The language is remembered in a small file beside them. True when purged."""
    folder = Path(project_dir) / "assets" / "image" / "map"
    stamp = folder / _MAP_LANGUAGE_STAMP
    current = str(language or "")
    try:
        previous = stamp.read_text(encoding="utf-8").strip() if stamp.exists() else None
    except OSError:
        previous = None
    purged = False
    # Images with no note were made before the language was remembered: language unknown, so fetched again once.
    if previous != current and (previous is not None or any(folder.glob("*.png"))):
        for image in folder.glob("*.png"):
            try:
                image.unlink()
                purged = True
            except OSError as exc:
                logger.warning("Could not delete the old map image %s: %s", image, exc)
        logger.info("Map language changed (%s -> %s): old map images deleted, fetching them again.", previous if previous is not None else "unknown", current or "none")
    if previous != current and folder.is_dir():
        try:
            stamp.write_text(current, encoding="utf-8")
        except OSError:
            pass
    return purged


def overview_bounding_box(fetcher, route_df: pd.DataFrame, project_config: dict) -> dict:
    """The overview map's box: the route padded by its span; in the "course"
    style also clear of the headline above, and both styles clear of the subtitles below."""
    bbox = fetcher.get_bounding_box(route_df, padding_factor=_adaptive_overview_padding(route_df))
    if overview_style(project_config) == "course":
        bbox = _reserve_overview_bands(
            bbox, OVERVIEW_FRAME_SIZE,
            OVERVIEW_FRAME_SIZE[1] * tuning.COURSE_TOP_BAND_FRACTION,
            OVERVIEW_FRAME_SIZE[1] * tuning.COURSE_BOTTOM_BAND_FRACTION,
        )
    else:
        bbox = _reserve_overview_bands(
            bbox, OVERVIEW_FRAME_SIZE, 0.0, OVERVIEW_FRAME_SIZE[1] * tuning.OVERVIEW_BOTTOM_BAND_FRACTION
        )
    return bbox


def _course_config(project_config: dict, config_path: Path) -> dict:
    """The overview type, plus what the "course" overview needs from the route:
    headline taglines and the stats card's numbers (the same the script speaks)."""
    style = overview_style(project_config)
    if style != "course":
        return {"overview_style": style}
    try:
        brief = load_brief(str(config_path))
    except (OSError, ValueError, KeyError) as exc:
        logger.warning("Course overview: could not read the route brief (%s).", exc)
        return {"overview_style": style}
    return {
        "overview_style": style,
        "overview_taglines": course_taglines(project_config, brief),
        "course_summary": course_summary(brief),
    }
