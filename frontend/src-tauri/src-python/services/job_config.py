"""
Job Configuration Manager (job_config.py)
"""
'''
This module provides a service for managing job configuration JSON files. It is designed to be used within the Tauri application framework, allowing for seamless integration with the frontend.

How to Use:
"""
from job_config import JobConfigManager

# 1. Initialize the manager with your job config file
config = JobConfigManager("job_config.json")

# 2. Read properties easily
project_name = config.get("project_name")
print(f"Project Name: {project_name}")[cite: 4]

# 3. Access settings or waypoints
fps = config.get_settings().get("fps")
waypoints = config.get_waypoints()
print(f"FPS: {fps}, Total Waypoints: {len(waypoints)}")[cite: 4]

# 4. Modify data
config.set("status", "processing")

# 5. Save changes back to file
config.save()
"""
'''

# Import necessary modules
import json
from pathlib import Path
from typing import Union, Any, Dict, List, Optional
import logging

# Logging configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class JobConfigManager:
    """
    An OOP singleton class to load, read, update, and save job configuration JSON files.
    """

    _instance = None

    def __new__(cls, config_path=None):
        if cls._instance is None:
            cls._instance = super(JobConfigManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, config_path: Optional[Union[str, Path]] = None) -> None: 
        if getattr(self, '_initialized', False) and not config_path:
            return

        # Update path only if explicitly provided, otherwise keep existing or fall back
        if config_path:
            self.config_path = Path(config_path).resolve()
        elif not getattr(self, 'config_path', None):
            self.config_path = Path("job_config.json").resolve()

        if not hasattr(self, 'data'):
            self.data: Dict[str, Any] = {}

        if self.config_path.exists():
            self.load()
            
        self._initialized = True

    # =========================
    # Configuration operations
    # =========================
    def load(self) -> None:
        """
        Load the JSON configuration file into memory.
        """
        if not self.config_path.exists():
            logging.error(f"Config file not found at: {self.config_path}")
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
            logging.info(f"Successfully loaded configuration from {self.config_path}")
        except json.JSONDecodeError as e:
            logging.error(f"Failed to decode JSON from {self.config_path}: {e}")
            raise

    # ========================
    # Save and update operations
    # ========================
    def save(self, target_path: Optional[Union[str, Path]] = None) -> None:
        """
        Save the current configuration state back to a JSON file.
        If no target path is provided, it checks if 'directory_path' exists 
        in the data; otherwise, it saves back to the original config path.
        """
        if target_path:
            save_path = Path(target_path)
        else:
            # Check if directory_path is defined inside the project settings data
            directory_path = self.data.get("directory_path")
            if directory_path:
                save_path = Path(directory_path) / "job_config.json"
            else:
                save_path = self.config_path

        save_path = save_path.resolve()
        save_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            logging.info(f"Successfully saved configuration to {save_path}")
            
            # Keep self.config_path updated to the new active path
            self.config_path = save_path
        except Exception as e:
            logging.error(f"Failed to save configuration to {save_path}: {e}")
            raise


    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a top-level configuration property.
        """
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """
        Set or update a top-level configuration property.
        """
        self.data[key] = value

    def get_waypoints(self) -> List[Dict[str, Any]]:
        """
        Retrieve the list of waypoints from the configuration.
        """
        return self.data.get("waypoints", [])

    def add_waypoint(self, waypoint: Dict[str, Any]) -> None:
        """
        Add a new waypoint to the configuration list.
        """
        if "waypoints" not in self.data:
            self.data["waypoints"] = []
        self.data["waypoints"].append(waypoint)

    def get_settings(self) -> Dict[str, Any]:
        """
        Retrieve project settings (fps, duration, etc.).
        """
        return self.data.get("settings", {})

    def get_all(self) -> Dict[str, Any]:
        """
        Retrieve the entire configuration data.
        """
        return self.data