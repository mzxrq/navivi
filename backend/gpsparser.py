import subprocess
import shutil
from pathlib import Path

GPSBABEL_BIN = Path(__file__).resolve().parent / "bin" / "GPSBabel" / "gpsbabel.exe"


def convert_nmea(input_file, output_file, output_format, input_format="nmea", extra_args=None):
    """
    Convert an NMEA GPS file to any format supported by gpsbabel.

    Args:
        input_file (str): Path to the input NMEA file.
        output_file (str): Path where the converted file will be saved.
        output_format (str): gpsbabel output format code (e.g. 'gpx', 'kml',
            'garmin_gpi', 'csv', 'igc', etc.)
        input_format (str): gpsbabel input format code. Default 'nmea'.
        extra_args (list[str] | None): Any additional gpsbabel CLI args
            (e.g. ['-x', 'track,merge'] for filters).

    Returns:
        str: Path to the created output file.

    Raises:
        FileNotFoundError: If gpsbabel isn't installed or input file missing.
        RuntimeError: If gpsbabel exits with an error.

    Calling function example:
        convert_nmea("track.nmea", "track.gpx", "gpx")
    """
    
    if GPSBABEL_BIN.exists():
        gpsbabel_cmd = str(GPSBABEL_BIN)
    else:
        gpsbabel_cmd = shutil.which("gpsbabel")

    if gpsbabel_cmd is None:
        raise FileNotFoundError(
            f"gpsbabel not found. Expected bundled binary at {GPSBABEL_BIN} or a PATH install."
        )

    input_path = Path(input_file)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [gpsbabel_cmd, "-i", input_format, "-f", str(input_path)]

    if extra_args:
        cmd.extend(extra_args)

    cmd.extend(["-o", output_format, "-F", str(output_path)])

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(
            f"gpsbabel failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )

    return str(output_path)