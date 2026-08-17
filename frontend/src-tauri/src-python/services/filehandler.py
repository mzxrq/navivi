import shutil
import sys
from pathlib import Path
from datetime import datetime

def store_raw_file_with_datetime(source_path_str: str) -> str:
    """
    Copies a raw file from the frontend and renames it using the current date, time, 
    and a sequence number (01-99) to prevent identical timestamp collisions.
    Example: 'track.gpx' becomes '20260810_130008_01.gpx'
    """
    # 1. Define the storage folder
    raw_storage_dir = Path("src-python\\data\\inputs\\gpsdata\\rawdata")
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

if __name__ == "__main__":
    if len(sys.argv) > 1:
        source = sys.argv[1]
        result_path = store_raw_file_with_datetime(source)
        # Print the resulting path so Rust can capture it
        if result_path:
            print(result_path)

# Testing
# if __name__ == "__main__":
#     # Example usage
#     test_source_path = "src-tauri\\src-python\\data\\inputs\\gpsdata\\rawdata\\LOG00001.TXT"  # Replace with an actual file path for testing
#     stored_file_path = store_raw_file_with_datetime(test_source_path)
#     if stored_file_path:
#         print(f"File stored at: {stored_file_path}")
#     else:
#         print("File storage failed.")