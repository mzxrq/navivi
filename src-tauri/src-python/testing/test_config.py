"""
job_config_handler.py (OOP Refactored)
---------------------------------------------------------------------------
Handles parsing frontend JSON payloads, configuring project directories, 
and persisting states using JobConfigManager.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Union, Dict, Any

from job_config import JobConfigManager


class FrontendConfigHandler:
    """Handles processing and persisting frontend configuration payloads to disk."""

    @staticmethod
    def save_config(json_payload: Union[str, Dict[str, Any]]) -> str:
        """
        Parses a frontend JSON configuration payload, determines the correct project 
        directory, updates the JobConfigManager, and writes 'job_config.json' to disk.
        """
        # Support both raw JSON strings and pre-parsed dictionaries
        config_data = json.loads(json_payload) if isinstance(json_payload, str) else json_payload

        # Prefer an explicitly provided directory_path from the payload if available
        directory_path = config_data.get("directory_path")
        if directory_path:
            project_dir = Path(directory_path).resolve()
        else:
            # Fallback pathing using project ID or name
            project_identifier = config_data.get("project_name") or config_data.get("project_id") or "untitled_project"
            safe_slug = "".join(c.lower() if c.isalnum() else "_" for c in str(project_identifier)).strip("_")
            project_dir = (Path("data/projects") / safe_slug).resolve()

        config_path = project_dir / "job_config.json"

        # Ensure directory and base file exist so JobConfigManager.load() doesn't fail[cite: 1]
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if not config_path.exists():
            config_path.write_text("{}", encoding="utf-8")

        # Initialize the manager using the absolute path[cite: 1]
        config = JobConfigManager(str(config_path))

        # Populate configuration with frontend payload data
        for key, value in config_data.items():
            config.set(key, value)

        # Save changes back to disk[cite: 1]
        config.save()

        return str(config_path)


# =============================================================================
# BACKWARDS-COMPATIBLE MODULE-LEVEL FUNCTION (FACADE WRAPPER)
# =============================================================================

def save_frontend_config(json_payload: str) -> str:
    """Facade wrapper ensuring compatibility with existing code calls."""
    return FrontendConfigHandler.save_config(json_payload)


# =============================================================================
# TEST BLOCK
# =============================================================================

if __name__ == "__main__":
    payload = json.dumps({
      "project_id": "proj_2026_very_cool_tomogashima_islands",
      "user_id": "local_user",
      "project_name": "very cool tomogashima islands",
      "created_at": "2026-08-17T23:08:34.042Z",
      "status": "processing",
      "directory_path": "data/projects/proj_2026_very_cool_tomogashima_islands",
      "source_files": {
        "gps_route": "assets/csv/LOG00002.csv"
      },
      "settings": {
        "fps": 30,
        "duration_seconds": 8,
        "line_color": [0, 200, 255],
        "line_thickness": 2,
        "marker_color": [108, 108, 213],
        "marker_radius": 18,
        "res_duration": 12,
        "pause": 2,
        "summary_hold": 4,
        "summary_fade": 0.5
      },
      "waypoints": [
        {
          "lat": 34.27491428149796,
          "lng": 135.07999956607821,
          "label": "加太停車場線",
          "freeze_seconds": 3,
          "popup_image": None,
          "image_display": "pip",
          "narration": "",
          "routeMode": "walking"
        }
      ]
    })

    print("--- Running Test ---")
    saved_path = save_frontend_config(payload)
    print(f"Success! Configuration written to: {saved_path}")

    # Verify content was saved properly
    with open(saved_path, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    print(f"Verified Project Name in JSON: {saved_data.get('project_name')}")
    print(f"Total Waypoints Saved: {len(saved_data.get('waypoints', []))}")