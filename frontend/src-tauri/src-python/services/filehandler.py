"""
filehandler.py (OOP Refactored)
---------------------------------------------------------------------------
Handles raw GPS file storage, project asset management, TTS audio generation, 
and project initialization structures.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Union
import requests

# =============================================================================
# RAW GPS FILE MANAGER
# =============================================================================

class RawGPSFileManager:
    """Manages secure storage and collision-free naming of incoming raw GPS files."""

    def __init__(self, storage_dir: Union[str, Path] = Path("data/inputs/gpsdata/rawdata")):
        self.storage_dir = Path(storage_dir)

    def store_file(self, source_path_str: Union[str, Path]) -> str:
        """
        Copies a raw file from the frontend and renames it using the current date, time, 
        and a sequence number (01-99) to prevent identical timestamp collisions.
        Example: 'track.gpx' becomes '20260810_130008_01.gpx'
        """
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        source_path = Path(source_path_str)
        
        if not source_path.exists():
            print(f"Error: Could not find raw file at {source_path}")
            return ""

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_extension = source_path.suffix 
        
        destination_path = None
        new_filename = ""

        for i in range(1, 100):
            sequence = f"{i:02d}"
            new_filename = f"{timestamp}_{sequence}{file_extension}"
            destination_path = self.storage_dir / new_filename
            
            if not destination_path.exists():
                break
        else:
            print("Error: Exceeded 99 files in the exact same second!")
            return ""

        try:
            print(f"Storing raw file safely as {new_filename}...")
            shutil.copy2(source_path, destination_path)
            return str(destination_path.resolve())
            
        except Exception as e:
            print(f"Failed to store raw file: {e}")
            return ""


# =============================================================================
# PROJECT ASSET HANDLER
# =============================================================================

class ProjectAssetHandler:
    """Handles project-specific asset storage and cross-platform normalization."""

    @staticmethod
    def save_asset_image(project_dir: Union[str, Path], source_image_path: Union[str, Path]) -> str:
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
            
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        original_stem = src_path.stem
        suffix = src_path.suffix.lower()
        
        target_filename = f"{original_stem}_{timestamp_str}{suffix}"
        target_path = assets_dir / target_filename
        
        shutil.copy2(src_path, target_path)
        print(f"🖼️ Asset image saved to: {target_path}")
        
        return str(target_path).replace("\\", "/")


# =============================================================================
# TTS AUDIO GENERATOR
# =============================================================================

class TTSAudioGenerator:
    """Interfaces with the local text-to-speech service to generate audio files."""

    def __init__(self, server_url: str = "http://localhost:8000/v1/audio/speech"):
        self.server_url = server_url

    def generate_and_save(self, text: str, output_path: Union[str, Path] = "output.mp3") -> Optional[str]:
        """
        Sends text to the local Irodori-TTS server and saves the response as an audio file.
        """
        payload = {
            "model": "irodori-tts",
            "input": text,
            "voice": "default",
            "response_format": "mp3"
        }
        
        try:
            response = requests.post(self.server_url, json=payload)
            
            if response.status_code == 200:
                with open(output_path, "wb") as f:
                    f.write(response.content)
                print(f"Audio successfully saved to: {output_path}")
                return str(output_path)
            else:
                print(f"Error from server ({response.status_code}): {response.text}")
                return None
                
        except requests.exceptions.ConnectionError:
            print("Error: Could not connect to the Irodori-TTS server. Make sure it is running on http://localhost:8000")
            return None
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            return None


# =============================================================================
# PROJECT INITIALIZER
# =============================================================================

class ProjectInitializer:
    """Manages workspace folder layouts and initializes project configuration states."""

    def __init__(self, base_dir: Union[str, Path] = Path("data/projects")):
        self.base_dir = Path(base_dir)

    def initialize(self, user_id: str, project_name: str, base_settings: Optional[Dict[str, Any]] = None) -> str:
        """
        Initializes a dedicated project folder structure and creates 
        an initial project.json metadata configuration file.
        
        Returns the absolute or relative path to the created project.json file.
        """
        safe_slug = "".join(c.lower() if c.isalnum() else "_" for c in project_name).strip("_")
        if not safe_slug:
            safe_slug = "untitled_project"

        project_dir = self.base_dir / user_id / safe_slug
        assets_dir = project_dir / "assets"
        res_images_dir = project_dir / "res_images"

        project_dir.mkdir(parents=True, exist_ok=True)
        assets_dir.mkdir(exist_ok=True)
        res_images_dir.mkdir(exist_ok=True)

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

        config_path = project_dir / "project.json"
        temp_path = project_dir / "project.json.tmp"

        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        
        temp_path.replace(config_path)

        print(f"📁 Project initialized successfully at: {config_path}")
        return str(config_path)


# =============================================================================
# BACKWARDS-COMPATIBLE MODULE-LEVEL FUNCTIONS (FACADE WRAPPERS)
# =============================================================================

_gps_manager = RawGPSFileManager()
_asset_handler = ProjectAssetHandler()
_tts_generator = TTSAudioGenerator()
_project_initializer = ProjectInitializer()

def store_raw_file_with_datetime(source_path_str: str) -> str:
    return _gps_manager.store_file(source_path_str)

def save_project_asset_image(project_dir: str | Path, source_image_path: str | Path) -> str:
    return _asset_handler.save_asset_image(project_dir, source_image_path)

def generate_and_save_audio(text: str, output_path: str = "output.mp3", server_url: str = "http://localhost:8000/v1/audio/speech") -> str | None:
    # Allows dynamic overriding of server_url via functional parameters if required
    generator = TTSAudioGenerator(server_url=server_url) if server_url != "http://localhost:8000/v1/audio/speech" else _tts_generator
    return generator.generate_and_save(text, output_path)

def initialize_new_project(user_id: str, project_name: str, base_settings: dict = None) -> str:
    return _project_initializer.initialize(user_id, project_name, base_settings)