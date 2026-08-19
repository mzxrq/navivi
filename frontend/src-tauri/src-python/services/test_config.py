import json
from pathlib import Path
from job_config import JobConfigManager  #

from filehandler import FileHandler  # Ensure this import is correct based on your project structure

def save_frontend_config(json_payload: str) -> str:
    config_data = json.loads(json_payload)
    # Fallback to project_id if project_path isn't explicitly defined in payload keys
    project_name = config_data.get("project_path") or config_data.get("project_id")
    
    project_dir = FileHandler.get_project_directory(project_name)
    config_path = project_dir / "job_config.json"

    # Ensure directory and base file exist so JobConfigManager.load() doesn't fail[cite: 1]
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        config_path.write_text("{}", encoding="utf-8")

    # Initialize the manager[cite: 1]
    config = JobConfigManager(config_path)

    # Populate configuration with frontend payload data
    for key, value in config_data.items():
        config.set(key, value)

    # Save changes back to disk[cite: 1]
    config.save()

    return str(config_path)

if __name__ == "__main__":
    # Your exact JSON payload
    payload = json.dumps({
      "project_id": "proj_2026_very_cool_tomogashima_islands",
      "user_id": "local_user",
      "project_name": "very cool tomogashima islands",
      "created_at": "2026-08-17T23:08:34.042Z",
      "status": "processing",
      "directory_path": "C:\\Users\\user1\\Documents\\Navivi\\Projects\\proj_2026_very_cool_tomogashima_islands",
      "source_files": {
        "gps_route": "C:\\Users\\user1\\Desktop\\work\\navivi\\frontend\\src-tauri\\src-python\\data\\inputs\\gpsdata\\rawdata\\LOG00002.TXT"
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
      "start_point": {
        "lat": 34.27491428149796,
        "lng": 135.07999956607821,
        "label": "加太停車場線"
      },
      "end_point": {
        "lat": 34.274976341511,
        "lng": 135.0802838802338,
        "label": "加太停車場線"
      },
      "waypoints": [
        {
          "lat": 34.27491428149796,
          "lng": 135.07999956607821,
          "label": "加太停車場線",
          "freeze_seconds": 3,
          "popup_image": [],
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