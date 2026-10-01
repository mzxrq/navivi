"""
Job Configuration Manager (job_config.py)
----------------------------------------------------------------------------
This module provides a singleton class for managing job configuration JSON files.
It allows loading, reading, updating, and saving configurations in a structured manner.
The JobConfigManager is designed to be used across different services, ensuring consistent
access to configuration data.
----------------------------------------------------------------------------
"""

# [I/O] Import necessary libraries for JSON handling and file path management
import json
from pathlib import Path
from typing import Union, Any, Dict, Final, List, Optional

# [Utility] Import the logging setup for consistent logging across services
from services.logger.logger import setup_logger

logger = setup_logger("JobConfigManager")


# [Core] JobConfigManager Singleton Class
class JobConfigManager:
    """
    An OOP singleton class to load, read, update, and save job configuration JSON files.
    """

    _instance = None

    # [Config] Singleton pattern to ensure only one instance exists
    def __new__(cls, config_path=None):
        if cls._instance is None:
            cls._instance = super(JobConfigManager, cls).__new__(cls)
        return cls._instance

    # [Config] Initialize the JobConfigManager with a configuration path
    def __init__(self, config_path: Optional[Union[str, Path]] = None) -> None:
        # [NOTE] [Config] Because __new__ always returns the same singleton instance, __init__ runs on
        # every JobConfigManager(...) call too — this guard skips re-initializing (and re-loading) an
        # already-initialized instance unless a new config_path is explicitly passed in.
        if getattr(self, "_initialized", False) and not config_path:
            return

        # Update path only if explicitly provided, otherwise keep existing or fall back
        if config_path:
            self.config_path = Path(config_path).resolve()
        elif not getattr(self, "config_path", None):
            self.config_path = Path("job_config.json").resolve()

        if not hasattr(self, "data"):
            self.data: Dict[str, Any] = {}

        if self.config_path.exists():
            self.load()

        self._initialized = True

    # [Util/IO] Load the JSON configuration file into memory
    def load(self) -> None:
        """
        Load the JSON configuration file into memory.
        """
        if not self.config_path.exists():
            logger.error(f"Config file not found at: {self.config_path}")
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
            logger.info(f"Successfully loaded configuration from {self.config_path}")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON from {self.config_path}: {e}")
            raise

        self._resolve_relative_paths()

    # Keys whose values are file paths, resolved on load so everything
    # downstream can keep treating them as plain absolute paths.
    _PATH_KEYS_TOP: Final = ("thumbnail_path",)
    _PATH_KEYS_WAYPOINT: Final = ("images", "popup_image", "popup_video", "videos", "customMarker")

    def _resolve_relative_paths(self) -> None:
        """Rewrites every relative path in the loaded config to an absolute
        one, anchored at the folder holding job_config.json itself.

        The app writes absolute paths, but the config is also a file people
        hand-edit, copy between machines and move with the project folder —
        and absolute paths from someone else's Documents folder are worse
        than useless there, while a relative "raw_track.gpx" or
        "assets/image/x.jpg" beside the config travels with it. Before
        this, a relative value was resolved against the process working
        directory, so `py main.py <config>` looked for the track next to
        main.py and failed.

        In memory only: the file on disk is untouched, so a project that
        deliberately keeps relative paths stays that way. An absolute
        value is left exactly as it is, so nothing changes for a config
        the app wrote."""
        anchor = self.config_path.parent

        def absolute(value: Any) -> Any:
            if not isinstance(value, str) or not value.strip():
                return value
            path = Path(value).expanduser()
            if path.is_absolute():
                return value
            return str((anchor / path).resolve())

        def absolute_each(value: Any) -> Any:
            if isinstance(value, list):
                return [absolute(v) for v in value]
            return absolute(value)

        # directory_path anchors the project's own output (video/, cache/,
        # gpsdata/ ...). Missing entirely — as in a hand-written config —
        # means "the folder this config lives in", which is the only
        # sensible reading and beats every downstream default of the
        # working directory.
        directory_path = self.data.get("directory_path")
        self.data["directory_path"] = (
            absolute(directory_path) if directory_path else str(anchor)
        )

        for key in self._PATH_KEYS_TOP:
            if key in self.data:
                self.data[key] = absolute_each(self.data[key])

        source_files = self.data.get("source_files")
        if isinstance(source_files, dict):
            for key, value in source_files.items():
                source_files[key] = absolute_each(value)

        points = list(self.data.get("waypoints") or [])
        for key in ("start_point", "end_point"):
            point = self.data.get(key)
            if isinstance(point, dict):
                points.append(point)
        for point in points:
            if not isinstance(point, dict):
                continue
            for key in self._PATH_KEYS_WAYPOINT:
                if key in point:
                    point[key] = absolute_each(point[key])

    # [Util/IO] Save and update operations
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
            logger.info(f"Successfully saved configuration to {save_path}")

            # Keep self.config_path updated to the new active path
            self.config_path = save_path
        except Exception as e:
            logger.error(f"Failed to save configuration to {save_path}: {e}")
            raise

    # [Util/Config] Accessor methods for configuration properties
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a top-level configuration property.
        """
        return self.data.get(key, default)

    # [Util/Config] Set or update a configuration property
    def set(self, key: str, value: Any) -> None:
        """
        Set or update a top-level configuration property.
        """
        self.data[key] = value

    # [Util/Config] Retrieve the list of waypoints from the configuration
    def get_waypoints(self) -> List[Dict[str, Any]]:
        """
        Retrieve the list of waypoints from the configuration.
        """
        return self.data.get("waypoints", [])

    # [Util/Config] Add a new waypoint to the configuration
    def add_waypoint(self, waypoint: Dict[str, Any]) -> None:
        """
        Add a new waypoint to the configuration list.
        """
        if "waypoints" not in self.data:
            self.data["waypoints"] = []
        self.data["waypoints"].append(waypoint)

    # [Util/Config] Retrieve project settings (fps, duration, etc.)
    def get_settings(self) -> Dict[str, Any]:
        """
        Retrieve project settings (fps, duration, etc.).
        """
        return self.data.get("settings", {})

    # [Util/Config] Update project settings with new values
    def update_settings(self, new_settings: Dict[str, Any]) -> None:
        """
        Update project settings with new values.
        """
        if "settings" not in self.data:
            self.data["settings"] = {}
        self.data["settings"].update(new_settings)

    # [Util/Config] Retrieve the entire configuration data
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the JobConfigManager instance to a dictionary representation.
        """
        return self.data