from pathlib import Path
import services.filehandler as filehandler
from services.filehandler import FileHandler

def test_get_directory_path():
    """Test that get_directory_path returns a valid Path object[cite: 1]."""
    path = FileHandler.get_directory_path()
    assert isinstance(path, Path)

def test_get_project_directory(monkeypatch, tmp_path):
    """Test that project directories are properly sanitized and created[cite: 1]."""
    # Redirect the module-level STORAGE_DIR to the temporary directory
    monkeypatch.setattr(filehandler, "STORAGE_DIR", tmp_path)
    
    project_name = "My Test Project!@#"
    project_dir = FileHandler.get_project_directory(project_name)
    
    assert project_dir.name == "My Test Project"
    assert project_dir.exists()
    assert project_dir.is_dir()

def test_save_file_with_timestamp_text(monkeypatch, tmp_path):
    """Test saving text or CSV files with timestamps[cite: 1]."""
    monkeypatch.setattr(filehandler, "STORAGE_DIR", tmp_path)
    
    file_name = "route_data"
    file_type = "csv"
    content = "latitude,longitude,time\n35.6812,139.7671,12:00:00"
    
    saved_path_str = FileHandler.save_file_with_timestamp(file_name, file_type, content)
    saved_path = Path(saved_path_str)
    
    assert saved_path.exists()
    assert saved_path.parent.name == "csv"
    assert saved_path.read_text(encoding="utf-8") == content

def test_save_file_with_timestamp_binary(monkeypatch, tmp_path):
    """Test saving binary content like images with timestamps[cite: 1]."""
    monkeypatch.setattr(filehandler, "STORAGE_DIR", tmp_path)
    
    file_name = "map_snapshot"
    file_type = "png"
    binary_content = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    
    saved_path_str = FileHandler.save_file_with_timestamp(file_name, file_type, binary_content)
    saved_path = Path(saved_path_str)
    
    assert saved_path.exists()
    assert saved_path.parent.name == "png"
    assert saved_path.read_bytes() == binary_content