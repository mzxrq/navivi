"""
gps_converter.py
---------------------------------------------------------------------------
Handles vector-based spatial math and GPSBabel binary execution.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Final, Optional, Dict, Any, List
import numpy as np
import pandas as pd

from services.job_config import JobConfigManager
from services.logger import setup_logger

logger = setup_logger("GPSConverter")

# =============================================================================
# [CORE] GEOMETRY & MATH UTILITIES
# =============================================================================


class GPSMath:
    """Handles vector-based spatial and geographic calculations."""

    # [GPS] Haversine formula for distance between two lat/lon points
    @staticmethod
    def haversine_vectorized(
        lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray
    ) -> np.ndarray:
        """Calculate the great circle distance between points using NumPy."""
        R = 6371.0
        lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])

        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = (
            np.sin(dlat / 2.0) ** 2
            + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
        )
        c = 2 * np.arcsin(np.sqrt(a))
        return R * c

    # [GPS] Compute total distance and duration from a route DataFrame
    @staticmethod
    def compute_route_summary(
        route_df: pd.DataFrame, waypoints_df: pd.DataFrame
    ) -> Dict[str, Any]:
        """Single source of truth for route-level distance and duration metrics."""
        total_distance_km = 0.0
        total_duration_seconds = 0.0

        if not route_df.empty:
            if "timestamp" in route_df.columns:
                ordered = route_df.sort_values("timestamp")
                total_duration_seconds = (
                    ordered["timestamp"].max() - ordered["timestamp"].min()
                ).total_seconds()

            if "latitude" in route_df.columns and "longitude" in route_df.columns:
                lat1, lon1 = route_df["latitude"], route_df["longitude"]
                lat2, lon2 = route_df["latitude"].shift(-1), route_df[
                    "longitude"
                ].shift(-1)
                total_distance_km = float(
                    np.nansum(
                        GPSMath.haversine_vectorized(
                            lat1.to_numpy(),
                            lon1.to_numpy(),
                            lat2.to_numpy(),
                            lon2.to_numpy(),
                        )
                    )
                )

        duration_td = pd.Timedelta(seconds=total_duration_seconds)

        return {
            "total_route_points": len(route_df),
            "total_waypoints": len(waypoints_df),
            "total_landmarked_stops": (
                int(route_df["is_landmarked"].sum())
                if "is_landmarked" in route_df.columns
                else 0
            ),
            "total_distance_km": round(total_distance_km, 3),
            "total_duration_seconds": total_duration_seconds,
            "total_distance_km_formatted": f"{total_distance_km:.2f} km",
            "total_duration_formatted": str(duration_td),
        }


# =============================================================================
# [CORE] GPSBABEL CONVERTER ENGINE
# =============================================================================


class GPSBabelConverter:
    """Manages binary execution, format detection, and file conversion via GPSBabel."""

    # [CONFIG] Default bundled variables and constants
    GPSBABEL_BIN: Final[Path] = (
        Path(__file__).resolve().parent.parent / "bin" / "GPSBabel" / "gpsbabel.exe"
    )

    EXTENSION_TO_FORMAT: Final[Dict[str, str]] = {
        ".gpx": "gpx",
        ".kml": "kml",
        ".nmea": "nmea",
        ".fit": "garmin_fit",
        ".tcx": "gtrnctr",
        ".loc": "geo",
        ".txt": "nmea",
    }

    TIMEOUT_SECONDS: Final[int] = 120

    # [Config] Initialize with optional binary path and dynamic job configuration
    def __init__(self, binary_path: Optional[Path] = None, job_config=None):
        self.binary_path = binary_path if binary_path else self.GPSBABEL_BIN
        # Bring in the dynamic JobConfigManager just like mapfetcher
        self.config = job_config or JobConfigManager()

    # [Validation] Resolve the GPSBabel binary path, checking both bundled and system PA
    def resolve_binary(self) -> str:
        if self.binary_path.exists():
            return str(self.binary_path)

        system_binary = shutil.which("gpsbabel")
        if system_binary is None:
            raise FileNotFoundError(
                f"gpsbabel not found. Expected bundled binary at '{self.binary_path}' or a PATH install."
            )
        return system_binary

    # [Validation] Detect input format based on file extension, raising an error if unsupported
    def detect_input_format(self, input_path: Path) -> str:
        ext = input_path.suffix.lower()
        fmt = self.EXTENSION_TO_FORMAT.get(ext)
        if fmt is None:
            raise ValueError(
                f"Could not auto-detect format for extension '{ext}'. "
                f"Supported: {sorted(self.EXTENSION_TO_FORMAT)}."
            )
        return fmt

    # [Util/IO] Generate a unique output path to prevent overwrites
    def generate_unique_output_path(
        self, target_dir: Path, stem: str, suffix: str
    ) -> Path:
        target_dir.mkdir(parents=True, exist_ok=True)
        datetime_str = datetime.now().strftime("%Y%m%d_%H%M%S")

        for sequence in range(1, 100):
            candidate = target_dir / f"{stem}_raw_{datetime_str}_{sequence:02d}{suffix}"
            if not candidate.exists():
                return candidate

        raise FileExistsError(
            f"Could not generate unique filename; 99 files already exist for {datetime_str}."
        )

    # [Util/IO] Convert input file to desired output format, handling GPSBabel execution and errors
    def convert(
        self,
        input_file: str,
        output_filename: str,
        output_format: str,
        input_format: Optional[str] = None,
        extra_args: Optional[List[str]] = None,
    ) -> str:
        gpsbabel_cmd = self.resolve_binary()
        input_path = Path(input_file)

        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_file}")

        if input_format is None:
            input_format = self.detect_input_format(input_path)

        base_path = Path(self.config.get("directory_path", "assets"))
        target_dir = (base_path / "csv").resolve()

        requested = Path(output_filename)
        output_path = self.generate_unique_output_path(
            target_dir, requested.stem, requested.suffix
        )

        cmd = [gpsbabel_cmd, "-i", input_format, "-f", str(input_path.resolve())]
        if extra_args:
            cmd.extend(extra_args)

        dummy_bin: Optional[Path] = None

        if output_format.lower() == "mtk-bin" and output_path.suffix.lower() == ".csv":
            cmd.extend(["-o", f"mtk-bin,csv={output_path.resolve()}"])
            dummy_bin = output_path.parent / "dummy.bin"
            cmd.extend(["-F", str(dummy_bin.resolve())])
        else:
            cmd.extend(["-o", output_format, "-F", str(output_path.resolve())])

        logger.info("Running gpsbabel: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.TIMEOUT_SECONDS
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"gpsbabel timed out after {self.TIMEOUT_SECONDS}s for {input_file}"
            ) from exc
        finally:
            if dummy_bin and dummy_bin.exists():
                dummy_bin.unlink()

        if result.returncode != 0:
            raise RuntimeError(
                f"gpsbabel failed (exit {result.returncode}):\n{result.stderr.strip()}"
            )

        logger.info("Converted '%s' -> '%s'", input_file, output_path)
        return str(output_path)
