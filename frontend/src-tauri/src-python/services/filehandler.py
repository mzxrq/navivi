"""
File Handler Service (filehandler.py)
"""
'''
This module provides a service for handling file operations such as reading, writing, and managing files. It is designed to be used within the Tauri application framework, allowing for seamless integration with the frontend.

How to Use:
"""
from filehandler import FileHandler

# Get the storage directory path (defaults to User's Documents)[cite: 1]
storage_dir = FileHandler.get_directory_path()
print(f"Files are stored in: {storage_dir}")

# Save a text/CSV file with a timestamp
FileHandler.save_file_with_timestamp(
    file_name="route_data",
    file_type="csv",
    content="latitude,longitude,time\n35.6812,139.7671,12:00:00"
)

# Save a binary file (e.g., an image or raw bytes) with a timestamp
with open("sample.png", "rb") as f:
    binary_content = f.read()

FileHandler.save_file_with_timestamp(
    file_name="map_snapshot",
    file_type="png",
    content=binary_content
)
"""
'''

# Import necessary modules
from pathlib import Path
from datetime import datetime
from click import File

# Define Path for the storage directory
STORAGE_DIR = Path.home() / "Documents"
FILE_CONTENT = File 

class FileHandler:
    """
    A class to handle file operations such as reading, writing, and managing files.
    """

    # =========================
    # Initialization
    # =========================
    def __init__(self, storage_dir: Path = STORAGE_DIR):
        self.storage_dir = storage_dir

    # ==========================
    # File operations
    # ==========================
    @staticmethod
    def get_directory_path() -> Path:
        """
        Get the path to the storage directory.
        """
        return STORAGE_DIR

    # =========================
    # Get project directory path
    # =========================
    @staticmethod
    def get_project_directory(project_name: str) -> Path:
        """
        Get and create the specific directory for a project inside Documents.
        Sanitizes the project name to ensure it's a valid folder name.
        """
        # Clean the project name to remove invalid filesystem characters if needed
        safe_project_name = "".join(c for c in project_name if c.isalnum() or c in (' ', '_', '-')).strip()
        project_dir = STORAGE_DIR / safe_project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        return project_dir

    # ==========================
    # Storage file service with date and time
    # ==========================
    @staticmethod
    def save_file_with_timestamp(file_name: str,file_type: str, content: str) -> None:
        """
        Save a file with the current date and time appended to its name.

        Args:
            file_name (str): The name of the file to be saved.
            file_type (str): The type of the file to be saved.
            content (str): The content to write to the file.
        """
        # 1. Properly create the target directory (e.g., STORAGE_DIR/file_type)
        target_directory = STORAGE_DIR / file_type
        target_directory.mkdir(parents=True, exist_ok=True)

        # 2. Get the current date and time
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 4. Write the content to the file with explicit UTF-8 encoding
        new_file_path = target_directory / f"{file_name}_{timestamp}.{file_type}"
        
        # 4. Write content based on whether it is bytes (binary) or str (text)
        if isinstance(content, bytes):
            new_file_path.write_bytes(content)
        else:
            new_file_path.write_text(content, encoding="utf-8") 

        # DEBUG: Print the new file path for verification
        # print(f"File saved as: {new_file_path}")


    