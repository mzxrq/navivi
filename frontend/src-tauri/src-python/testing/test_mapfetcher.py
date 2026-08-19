# testing/test_mapfetcher.py

from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from PIL import Image
from unittest.mock import MagicMock, patch

from services.mapfetcher import MapFetcher

@pytest.fixture
def mock_job_config():
    """Fixture that returns a mocked JobConfigManager with sample data."""
    config = MagicMock()
    config.get.side_effect = lambda key, default=None: {
        "project_name": "Map Test Project",
        "directory_path": "./dummy_dir",
    }.get(key, default)
    
    config.get_settings.return_value = {"fps": 30}
    config.get_waypoints.return_value = [
        {"lat": 35.6812, "lng": 139.7671, "label": "Start"},
        {"lat": 35.6850, "lng": 139.7680, "label": "Mid"},
        {"lat": 35.6900, "lng": 139.7700, "label": "End"}
    ]
    return config

def test_get_bounding_box(mock_job_config):
    """Test bounding box calculation with and without padding."""
    fetcher = MapFetcher(mock_job_config)
    waypoints = pd.DataFrame([
        {"lat": 10.0, "lng": 20.0},
        {"lat": 30.0, "lng": 40.0}
    ])
    
    # Test without padding
    bbox = fetcher.get_bounding_box(waypoints, padding=0.0)
    assert bbox == (10.0, 30.0, 20.0, 40.0)
    
    # Test with padding
    bbox_padded = fetcher.get_bounding_box(waypoints, padding=0.1)
    assert bbox_padded == (8.0, 32.0, 18.0, 42.0)

def test_get_bounding_box_empty_raises_error(mock_job_config):
    """Test that an empty waypoints DataFrame raises a ValueError[cite: 4]."""
    fetcher = MapFetcher(mock_job_config)
    empty_df = pd.DataFrame(columns=['lat', 'lng'])
    
    with pytest.raises(ValueError, match="Waypoints DataFrame is empty"):
        fetcher.get_bounding_box(empty_df)

def test_douglas_peucker(mock_job_config):
    """Test path simplification using the Douglas-Peucker algorithm[cite: 4]."""
    fetcher = MapFetcher(mock_job_config)
    
    with pytest.raises(ValueError, match="Points array is empty"):
        fetcher.douglas_peucker(np.array([]), epsilon=0.1)
        
    short_points = np.array([[1.0, 1.0], [2.0, 2.0]])
    np.testing.assert_array_equal(fetcher.douglas_peucker(short_points, 0.1), short_points)
    
    path = np.array([
        [0.0, 0.0],
        [0.1, 0.01],
        [1.0, 1.0]
    ])
    simplified = fetcher.douglas_peucker(path, epsilon=0.5)
    assert len(simplified) == 2

def test_get_smoothed_path(mock_job_config):
    """Test spline interpolation smoothing on coordinate points[cite: 4]."""
    fetcher = MapFetcher(mock_job_config)
    
    with pytest.raises(ValueError, match="Points array is empty"):
        fetcher.get_smoothed_path(np.array([]))
        
    few_points = np.array([[1.0, 1.0], [2.0, 2.0]])
    np.testing.assert_array_equal(fetcher.get_smoothed_path(few_points), few_points)
    
    # Use at least 4 points for cubic spline interpolation (k=3 requirement)
    points = np.array([
        [0.0, 0.0],
        [1.0, 1.0],
        [2.0, 2.0],
        [3.0, 3.0]
    ])
    smoothed = fetcher.get_smoothed_path(points, num_points=10)
    assert smoothed.shape == (10, 2)

def test_crop_and_resize_map(mock_job_config):
    """Test cropping and resizing logic to match target aspect ratio and widths[cite: 4]."""
    fetcher = MapFetcher(mock_job_config)
    
    # Create a smaller image (800x800) so it triggers the MIN_MAP_WIDTH upscale resize logic
    img = Image.new("RGB", (800, 800), color="white")
    
    processed_img = fetcher.crop_and_resize_map(img, target_aspect_ratio=16/9)
    
    width, height = processed_img.size
    assert width == 1280  # MIN_MAP_WIDTH
    assert abs((width / height) - (16 / 9)) < 0.01

@patch("services.mapfetcher.plt")
@patch("services.mapfetcher.cx")
@patch("PIL.Image.open")
def test_fetch_map(mock_image_open, mock_cx, mock_plt, mock_job_config, tmp_path):
    """Test map tile fetching wrapper and file persistence handling[cite: 4]."""
    fetcher = MapFetcher(mock_job_config)
    
    # Properly mock plt.subplots to return a (fig, ax) tuple
    mock_fig = MagicMock()
    mock_ax = MagicMock()
    mock_plt.subplots.return_value = (mock_fig, mock_ax)
    
    dummy_img = Image.new("RGB", (100, 100))
    mock_image_open.return_value = dummy_img
    
    bbox = (35.0, 36.0, 139.0, 140.0)
    img = fetcher.fetch_map(bbox)
    
    assert img == dummy_img
    mock_plt.subplots.assert_called_once()
    mock_cx.add_basemap.assert_called_once()