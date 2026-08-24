# testing/test_gpsparser.py

from pathlib import Path
import pandas as pd
import json
from services.gpsparser import GPSParser

def test_detect_format():
    """Test that file extensions map to correct GPS Babel format strings[cite: 2]."""
    assert GPSParser.detect_format(Path("track.gpx")) == "gpx"
    assert GPSParser.detect_format(Path("track.kml")) == "kml"
    assert GPSParser.detect_format(Path("track.fit")) == "garmin_fit"
    assert GPSParser.detect_format(Path("track.unknown")) is None

def test_haversine_vertorized():
    """Test great-circle distance calculation between coordinates[cite: 2]."""
    # Coordinates for Tokyo Station to Shinjuku Station (~6 km apart)
    lat1, lon1 = 35.6812, 139.7671
    lat2, lon2 = 35.6938, 139.7034
    
    distance = GPSParser.haversine_vertorized(lat1, lon1, lat2, lon2)
    assert 5.5 < distance < 6.5

def test_compute_summary_distance():
    """Test computing total summary distance from a pandas DataFrame[cite: 2]."""
    data = {
        'lat': [35.6812, 35.6850, 35.6900],
        'lng': [139.7671, 139.7680, 139.7700],
        'timestamp': pd.to_datetime(['2026-06-01 10:00:00', '2026-06-01 10:05:00', '2026-06-01 10:10:00'])
    }
    df = pd.DataFrame(data)
    
    # Compute distance covering the full range of rows
    dist = GPSParser.compute_summary_distance(df, start_idx=0, end_idx=len(df))
    assert dist > 0.0

def test_detect_and_format_waypoint_stops():
    """Test dwell time analysis and JSON report generation for waypoint stops[cite: 2]."""
    # Create mock GPS tracking points clustered closely around a target location for 10 minutes (600s)
    data = {
        'lat': [35.6812, 35.6813, 35.6812],
        'lng': [139.7671, 139.7672, 139.7671],
        'timestamp': pd.to_datetime([
            '2026-06-01 10:00:00', 
            '2026-06-01 10:05:00', 
            '2026-06-01 10:10:00'
        ])
    }
    df = pd.DataFrame(data)
    
    job_config = {
        "waypoints": [
            {
                "lat": 35.6812,
                "lng": 139.7671,
                "label": "Checkpoint A",
                "routeMode": "walking",
                "freeze_seconds": 3
            }
        ]
    }
    
    json_result = GPSParser.detect_and_format_waypoint_stops(df, job_config)
    parsed = json.loads(json_result)
    
    assert isinstance(parsed, list)
    assert len(parsed) == 1
    assert parsed[0]["label"] == "Checkpoint A"
    assert parsed[0]["dwell_time_seconds"] == 600.0  # 10 minutes duration
    assert parsed[0]["is_extended_stop"] is True   # Exceeds the 300s threshold[cite: 2]