import shutil
import sys
from pathlib import Path
from datetime import datetime
import json
import requests

def store_raw_file_with_datetime(source_path_str: str) -> str:
    """
    Copies a raw file from the frontend and renames it using the current date, time, 
    and a sequence number (01-99) to prevent identical timestamp collisions.
    Example: 'track.gpx' becomes '20260810_130008_01.gpx'
    """
    # 1. Define the storage folder
    raw_storage_dir = Path("data\\inputs\\gpsdata\\rawdata")
    raw_storage_dir.mkdir(parents=True, exist_ok=True)

    source_path = Path(source_path_str)
    
    # 2. Safety check
    if not source_path.exists():
        print(f"Error: Could not find raw file at {source_path}")
        return ""

    # 3. Generate the base Date-Time string
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_extension = source_path.suffix 
    
    destination_path = None
    new_filename = ""

    # 4. Loop 1 to 99 to find an available sequence number
    for i in range(1, 100):
        # Format the number to always have two digits (e.g., 01, 02 ... 99)
        sequence = f"{i:02d}"
        
        # Build the test filename
        new_filename = f"{timestamp}_{sequence}{file_extension}"
        destination_path = raw_storage_dir / new_filename
        
        # If the file does NOT exist, break the loop and use this path!
        if not destination_path.exists():
            break
    else:
        # This triggers only if the loop reaches 99 without breaking
        print("Error: Exceeded 99 files in the exact same second!")
        return ""

    try:
        # 5. Copy and rename the file
        print(f"Storing raw file safely as {new_filename}...")
        shutil.copy2(source_path, destination_path)
        
        return str(destination_path.resolve())
        
    except Exception as e:
        print(f"Failed to store raw file: {e}")
        return ""

def save_project_asset_image(project_dir: str | Path, source_image_path: str | Path) -> str:
    """
    Copies an uploaded image file into the project's 'assets' directory,
    ensures a unique filename to prevent overwrites, and returns the 
    normalized path string to be stored in the waypoint configuration.
    """
    proj_path = Path(project_dir)
    assets_dir = proj_path / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    
    src_path = Path(source_image_path)
    if not src_path.exists():
        raise FileNotFoundError(f"Source image not found: {source_image_path}")
        
    # Generate a unique filename using a timestamp to avoid collisions
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    original_stem = src_path.stem
    suffix = src_path.suffix.lower()
    
    target_filename = f"{original_stem}_{timestamp_str}{suffix}"
    target_path = assets_dir / target_filename
    
    # Copy the file into the project assets folder
    shutil.copy2(src_path, target_path)
    
    print(f"🖼️ Asset image saved to: {target_path}")
    
    # Return path with forward slashes for cross-platform JSON compatibility
    return str(target_path).replace("\\", "/")

def generate_and_save_audio(text: str, output_path: str = "output.mp3", server_url: str = "http://localhost:8000/v1/audio/speech") -> str | None:
    """
    Sends text to the local Irodori-TTS server and saves the response as an audio file.
    
    :param text: The text you want to convert to speech.
    :param output_path: The file path where the MP3 should be saved.
    :param server_url: The URL of the running Irodori-TTS server.
    :return: The path to the saved file if successful, otherwise None.
    """
    payload = {
        "model": "irodori-tts",
        "input": text,
        "voice": "default",
        "response_format": "mp3"
    }
    
    try:
        response = requests.post(server_url, json=payload)
        
        if response.status_code == 200:
            with open(output_path, "wb") as f:
                f.write(response.content)
            print(f"Audio successfully saved to: {output_path}")
            return output_path
        else:
            print(f"Error from server ({response.status_code}): {response.text}")
            return None
            
    except requests.exceptions.ConnectionError:
        print("Error: Could not connect to the Irodori-TTS server. Make sure it is running on http://localhost:8000")
        return None
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None

def initialize_new_project(user_id: str, project_name: str, base_settings: dict = None) -> str:
    """
    Initializes a dedicated project folder structure and creates 
    an initial project.json metadata configuration file.
    
    Returns the absolute or relative path to the created project.json file.
    """
    # 1. Sanitize the project name into a safe directory slug
    safe_slug = "".join(c.lower() if c.isalnum() else "_" for c in project_name).strip("_")
    if not safe_slug:
        safe_slug = "untitled_project"

    # 2. Define directory paths using pathlib
    project_dir = Path("data") / "projects" / user_id / safe_slug
    assets_dir = project_dir / "assets"
    res_images_dir = project_dir / "res_images"

    # Create directories recursively
    project_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(exist_ok=True)
    res_images_dir.mkdir(exist_ok=True)

    # 3. Default video/animation settings mapping to route2vdo configuration
    default_settings = {
        "fps": 30,
        "duration_seconds": 8.0,
        "line_color": [0, 200, 255],
        "line_thickness": 10,
        "marker_color": [0, 0, 255],
        "marker_radius": 18,
        "res_duration": 12.0,
        "pause": 2.0,
        "summary_hold": 4.0,
        "summary_fade": 0.5
    }
    if base_settings:
        default_settings.update(base_settings)

    # 4. Construct project state payload
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    project_id = f"proj_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_slug}"

    payload = {
        "project_id": project_id,
        "user_id": user_id,
        "project_name": project_name,
        "created_at": timestamp,
        "status": "initialized",
        "directory_path": str(project_dir).replace("\\", "/"),
        "source_files": {
            "gps_route": None
        },
        "settings": default_settings,
        "waypoints": []
    }

    # 5. Save project.json using an atomic write pattern (via a temp file)
    config_path = project_dir / "project.json"
    temp_path = project_dir / "project.json.tmp"

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    
    # Safely replace the target file to prevent corruption on crash
    temp_path.replace(config_path)

    print(f"📁 Project initialized successfully at: {config_path}")
    return str(config_path)

# Testing
# if __name__ == "__main__":
#     # Example usage
#     test_source_path = "src-tauri\\src-python\\data\\inputs\\gpsdata\\rawdata\\LOG00001.TXT"  # Replace with an actual file path for testing
#     stored_file_path = store_raw_file_with_datetime(test_source_path)
#     if stored_file_path:
#         print(f"File stored at: {stored_file_path}")
#     else:
#         print("File storage failed.")