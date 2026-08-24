# testing/test_job_config.py

import json
from pathlib import Path
import pytest
from services.job_config import JobConfigManager

@pytest.fixture
def sample_config_file(tmp_path):
    """Fixture that creates a temporary valid JSON configuration file for testing."""
    config_data = {
        "project_name": "Test Project",
        "status": "idle",
        "settings": {
            "fps": 30,
            "duration": 60
        },
        "waypoints": [
            {"label": "Start", "lat": 35.6812, "lng": 139.7671}
        ]
    }
    file_path = tmp_path / "job_config.json"
    file_path.write_text(json.dumps(config_data, indent=2), encoding="utf-8")
    return file_path

def test_load_config_success(sample_config_file):
    """Test successful loading of a configuration file."""
    manager = JobConfigManager(sample_config_file)
    assert manager.get("project_name") == "Test Project"
    assert manager.get("status") == "idle"

def test_load_config_not_found(tmp_path):
    """Test that a FileNotFoundError is raised if the config file doesn't exist."""
    missing_file = tmp_path / "nonexistent.json"
    with pytest.raises(FileNotFoundError):
        JobConfigManager(missing_file)

def test_load_config_invalid_json(tmp_path):
    """Test that a JSONDecodeError is raised if the JSON syntax is malformed."""
    bad_file = tmp_path / "bad_config.json"
    bad_file.write_text("{ invalid json content", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        JobConfigManager(bad_file)

def test_get_and_set_properties(sample_config_file):
    """Test getting and setting custom configuration keys."""
    manager = JobConfigManager(sample_config_file)
    
    # Test getting with and without defaults
    assert manager.get("project_name") == "Test Project"
    assert manager.get("nonexistent_key", "default_val") == "default_val"
    
    # Test setting a property
    manager.set("status", "processing")
    assert manager.get("status") == "processing"

def test_waypoints_and_settings_helpers(sample_config_file):
    """Test helper functions for retrieving settings and waypoints."""
    manager = JobConfigManager(sample_config_file)
    
    settings = manager.get_settings()
    assert settings.get("fps") == 30
    
    waypoints = manager.get_waypoints()
    assert len(waypoints) == 1
    assert waypoints[0]["label"] == "Start"
    
    # Test adding a new waypoint
    new_wp = {"label": "End", "lat": 35.6938, "lng": 139.7034}
    manager.add_waypoint(new_wp)
    assert len(manager.get_waypoints()) == 2
    assert manager.get_waypoints()[1]["label"] == "End"

def test_save_config(sample_config_file, tmp_path):
    """Test saving changes back to the configuration file."""
    manager = JobConfigManager(sample_config_file)
    
    # Modify data
    manager.set("status", "completed")
    
    # Save to a new target file path
    target_path = tmp_path / "saved_config.json"
    manager.save(target_path)
    
    # Verify the file was saved and contains updated data
    assert target_path.exists()
    saved_manager = JobConfigManager(target_path)
    assert saved_manager.get("status") == "completed"