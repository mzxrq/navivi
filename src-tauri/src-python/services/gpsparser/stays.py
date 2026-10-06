"""
Stays (stays.py)
---------------------------------------------------------------------------
Reads any GPS file GPSBabel understands (GPX, NMEA, FIT, TCX, KML, ...) for
the import dialog, and finds the places the track stayed at: runs of points
that keep within `radius_m` of their centre for at least `min_stay_sec`.
---------------------------------------------------------------------------
"""

import io
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from services.gpsparser.gpscalculator import GPSMath
from services.gpsparser.gpsparser import GPSParser

DEFAULT_RADIUS_M = 50.0
DEFAULT_MIN_STAY_SEC = 300.0


def _distances_m(lat: np.ndarray, lon: np.ndarray, c_lat: float, c_lon: float) -> np.ndarray:
    return GPSMath.haversine_vectorized(lat, lon, np.full_like(lat, c_lat), np.full_like(lon, c_lon)) * 1000.0


def detect_stays(
    lat: np.ndarray,
    lon: np.ndarray,
    start_sec: np.ndarray,
    end_sec: np.ndarray,
    radius_m: float = DEFAULT_RADIUS_M,
    min_stay_sec: float = DEFAULT_MIN_STAY_SEC,
) -> List[Dict[str, Any]]:
    """Stays as {lat, lon, start_index, end_index, start_sec, end_sec}. start_sec/end_sec are each
    point's time span (a point the GPS sat on spans its whole dwell). Uses the median point so
    jitter spikes don't drag the centre; two stays at the same place split by a short wander merge."""
    n = len(lat)
    stays: List[Dict[str, Any]] = []
    i = 0
    while i < n:
        sum_lat, sum_lon, j = lat[i], lon[i], i + 1
        while j < n:
            c_lat, c_lon = sum_lat / (j - i), sum_lon / (j - i)
            if _distances_m(lat[j:j + 1], lon[j:j + 1], c_lat, c_lon)[0] > radius_m:
                break
            sum_lat += lat[j]
            sum_lon += lon[j]
            j += 1
        if end_sec[i:j].max() - start_sec[i] >= min_stay_sec:
            stays.append({"start_index": i, "end_index": j - 1})
            i = j
        else:
            i += 1

    merged: List[Dict[str, Any]] = []
    for stay in stays:
        s, e = stay["start_index"], stay["end_index"]
        stay.update(lat=float(np.median(lat[s:e + 1])), lon=float(np.median(lon[s:e + 1])),
                    start_sec=float(start_sec[s]), end_sec=float(end_sec[s:e + 1].max()))
        prev = merged[-1] if merged else None
        if (prev and stay["start_sec"] - prev["end_sec"] < min_stay_sec
                and _distances_m(np.array([stay["lat"]]), np.array([stay["lon"]]), prev["lat"], prev["lon"])[0] <= radius_m):
            s = prev["start_index"]
            prev.update(end_index=e, end_sec=stay["end_sec"],
                        lat=float(np.median(lat[s:e + 1])), lon=float(np.median(lon[s:e + 1])))
        else:
            merged.append(stay)
    return merged


def _named_waypoints(parser: GPSParser, path: Path, fmt: str) -> List[Dict[str, Any]]:
    """The file's named waypoints; the track CSV that clean_data reads carries no names."""
    try:
        result = subprocess.run(
            [str(parser.gps_babel_path), "-w", "-i", fmt, "-f", str(path), "-o", "unicsv", "-F", "-"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=parser.TIMEOUT_SECONDS,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        df = pd.read_csv(io.StringIO(result.stdout))
    except Exception:
        return []
    df.columns = [c.strip().lower() for c in df.columns]
    if not {"latitude", "longitude"} <= set(df.columns):
        return []
    names = df["name"].fillna("").astype(str) if "name" in df.columns else pd.Series([""] * len(df))
    return [{"lat": float(la), "lon": float(lo), "name": nm}
            for la, lo, nm in zip(df["latitude"], df["longitude"], names) if np.isfinite(la) and np.isfinite(lo)]


class _ImportConfig:
    """The minimal job config GPSParser needs, pointing it at a scratch folder."""

    def __init__(self, input_file: Path, work_dir: Path):
        self.config_path = str(work_dir / "job_config.json")
        self.data = {"input_file": str(input_file)}


def import_track(input_file: str, radius_m: float = DEFAULT_RADIUS_M,
                 min_stay_sec: float = DEFAULT_MIN_STAY_SEC) -> Dict[str, Any]:
    path = Path(input_file)
    if not path.exists():
        raise FileNotFoundError(f"GPS file not found: {path}")

    with tempfile.TemporaryDirectory(prefix="navivi_gps_") as work_dir:
        parser = GPSParser(job_config=_ImportConfig(path, Path(work_dir)))
        route = parser.clean_data()["route"].reset_index(drop=True)
        waypoints = _named_waypoints(parser, path, parser.detect_format(str(path)))

    lat = route["latitude"].to_numpy(dtype=float)
    lon = route["longitude"].to_numpy(dtype=float)
    ele = route["height"] if "height" in route.columns else route.get("altitude")
    points = [[la, lo] + ([float(e)] if e is not None and np.isfinite(e) else [])
              for la, lo, e in zip(lat, lon, ele if ele is not None else [None] * len(lat))]

    stays: List[Dict[str, Any]] = []
    if parser.has_real_time and len(route) > 1:
        times = pd.to_datetime(route["timestamp"])
        t0 = times.iloc[0]
        start_sec = (times - t0).dt.total_seconds().to_numpy()
        dwell = route["dwell_sec"].fillna(0).to_numpy(dtype=float) if "dwell_sec" in route.columns else np.zeros(len(route))
        for stay in detect_stays(lat, lon, start_sec, start_sec + dwell, radius_m, min_stay_sec):
            stays.append({
                "lat": stay["lat"],
                "lon": stay["lon"],
                "index": stay["start_index"],
                "start": (t0 + pd.Timedelta(seconds=stay["start_sec"])).isoformat(),
                "end": (t0 + pd.Timedelta(seconds=stay["end_sec"])).isoformat(),
                "duration_sec": round(stay["end_sec"] - stay["start_sec"]),
            })

    return {"points": points, "waypoints": waypoints, "stays": stays, "has_time": parser.has_real_time}
