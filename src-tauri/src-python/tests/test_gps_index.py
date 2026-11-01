"""The cleaned route is numbered 0..n-1 even after repeated points are dropped (services/gpsparser/gpsparser.py)."""

from services.gpsparser.gpsparser import GPSParser


def test_dropped_repeats_leave_no_gap_in_the_route_index(tmp_path):
    csv = tmp_path / "gpsdata.csv"
    # The GPS sat still twice: rows 1 and 4 repeat the point before them.
    csv.write_text(
        "latitude,longitude\n35.0,135.0\n35.0,135.0\n35.001,135.0\n35.002,135.0\n35.002,135.0\n35.003,135.0\n",
        encoding="utf-8",
    )
    parser = GPSParser(gps_babel_path=None, job_config=object())
    route = parser.clean_data(csv)["route"]
    assert len(route) == 4
    assert list(route.index) == [0, 1, 2, 3]  # a label is its position (mapfetcher matches the arrival row by it)
