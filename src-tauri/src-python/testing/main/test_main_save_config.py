# testing/test_save_config.py

import json
from pathlib import Path
from services.job_config import JobConfigManager


def save_config(file_path: str, data: dict) -> None:
    """Helper function to serialize and save configuration data to disk."""
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    Path(file_path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def test_save_config_function(tmp_path):
    """Test that save_config correctly serializes and saves configuration data to disk."""
    target_file = tmp_path / "job_config.json"
    
    sample_data = {
        "project_id": "proj_2026_very_cool_tomogashima_islands",
        "project_name": "very cool tomogashima islands",
        "status": "processing",
        "waypoints": [
            {
                "lat": 34.27491428149796,
                "lng": 135.07999956607821,
                "label": "加太停車場線"
            }
        ]
    }
    
    save_config(str(target_file), sample_data)
    
    # Verify file was written and contents match
    assert target_file.exists()
    loaded_data = json.loads(target_file.read_text(encoding="utf-8"))
    assert loaded_data["project_id"] == "proj_2026_very_cool_tomogashima_islands"
    assert loaded_data["waypoints"][0]["label"] == "加太停車場線"