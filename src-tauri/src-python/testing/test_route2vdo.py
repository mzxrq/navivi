# testing/test_route2vdo.py

import pytest
import numpy as np
import cv2
from pathlib import Path
from unittest.mock import MagicMock, patch
from services.route2vdo import Route2VDO

@pytest.fixture
def dummy_r2v():
    """Fixture providing a Route2VDO instance with mocked map fetcher and file handler dependencies."""
    mock_map_fetcher = MagicMock()
    mock_file_handler = MagicMock()
    return Route2VDO(mock_map_fetcher, mock_file_handler)

def test_format_duration(dummy_r2v):
    """Test formatting various duration lengths into human-readable strings."""
    assert Route2VDO.format_duration(45.1) == "45.1 sec"
    assert Route2VDO.format_duration(125.0) == "2 min 5 sec"
    assert Route2VDO.format_duration(3665.0) == "1 hr 1 min"

def test_is_real_label(dummy_r2v):
    """Test filtering of valid landmark labels versus placeholder tokens."""
    assert Route2VDO._is_real_label("Main Station") is True
    assert Route2VDO._is_real_label(None) is False
    assert Route2VDO._is_real_label("none") is False
    assert Route2VDO._is_real_label("  ") is False
    assert Route2VDO._is_real_label("N/A") is False
    assert Route2VDO._is_real_label("-") is False

def test_point_to_segment_distance(dummy_r2v):
    """Test mathematical distance calculation from a point to a line segment."""
    # Point directly on horizontal segment (0,0) to (10,0)
    dist_on = Route2VDO._point_to_segment_distance(5.0, 0.0, 0.0, 0.0, 10.0, 0.0)
    assert dist_on == 0.0

    # Point perpendicularly offset from segment
    dist_off = Route2VDO._point_to_segment_distance(5.0, 3.0, 0.0, 0.0, 10.0, 0.0)
    assert dist_off == 3.0

def test_latlon_to_pixel(dummy_r2v):
    """Test conversion of latitude and longitude arrays to pixel coordinate arrays."""
    lats = np.array([0.0])
    lons = np.array([0.0])
    extent = (-1000.0, 1000.0, -1000.0, 1000.0)
    pixels = Route2VDO.latlon_to_pixel(lats, lons, extent, 800, 600)
    
    assert isinstance(pixels, np.ndarray)
    assert pixels.shape == (1, 2)

    # Empty array handling
    empty_pixels = Route2VDO.latlon_to_pixel(np.array([]), np.array([]), extent, 800, 600)
    assert empty_pixels.shape == (0, 2)

def test_composite_video_frame(dummy_r2v):
    """Test alpha-blending overlay composition on frames."""
    base_img = np.zeros((100, 100, 3), dtype=np.uint8)
    overlay = np.ones((100, 100, 3), dtype=np.uint8) * 100
    
    composited = Route2VDO.composite_video_frame(base_img, [overlay])
    assert composited.shape == (100, 100, 3)

def test_read_image_safe_not_exists(dummy_r2v):
    """Test that reading a non-existent image safely returns None."""
    result = Route2VDO.read_image_safe("nonexistent_path_abc_123.png")
    assert result is None

@patch("services.route2vdo.FFMPEG_PATH")
def test_resolve_ffmpeg_path(mock_ffmpeg_path, dummy_r2v):
    """Test FFMPEG executable path resolution logic."""
    mock_ffmpeg_path.exists.return_value = True
    path = dummy_r2v.resolve_ffmpeg_path()
    assert path == mock_ffmpeg_path

    mock_ffmpeg_path.exists.return_value = False
    with pytest.raises(FileNotFoundError):
        dummy_r2v.resolve_ffmpeg_path()