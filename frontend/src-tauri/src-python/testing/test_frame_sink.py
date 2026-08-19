# testing/test_frame_sink.py

import pytest
import numpy as np
from pathlib import Path
from unittest.mock import MagicMock, patch
from services.frame_sink import FrameSink

@patch("services.frame_sink.cv2.VideoWriter")
@patch("services.frame_sink.subprocess.Popen")
def test_frame_sink_init_ffmpeg(mock_popen, mock_video_writer, tmp_path):
    """Test initialization when FFmpeg is available and opens successfully[cite: 5]."""
    ffmpeg_path = tmp_path / "ffmpeg.exe"
    ffmpeg_path.touch()  # Create dummy file so exists() returns True
    
    mock_proc = MagicMock()
    mock_popen.return_value = mock_proc
    
    output_file = str(tmp_path / "output.mp4")
    sink = FrameSink(output_file, w=640, h=480, fps=30, ffmpeg_path=ffmpeg_path)
    
    assert sink.proc == mock_proc
    mock_popen.assert_called_once()

@patch("services.frame_sink.cv2.VideoWriter")
@patch("services.frame_sink.subprocess.Popen")
def test_frame_sink_init_fallback(mock_popen, mock_video_writer, tmp_path):
    """Test initialization fallback to OpenCV when FFmpeg is unavailable[cite: 5]."""
    ffmpeg_path = tmp_path / "nonexistent_ffmpeg.exe"
    
    mock_writer = MagicMock()
    mock_writer.isOpened.return_value = True
    mock_video_writer.return_value = mock_writer
    
    output_file = str(tmp_path / "output.mp4")
    sink = FrameSink(output_file, w=640, h=480, fps=30, ffmpeg_path=ffmpeg_path)
    
    assert sink.proc is None
    assert sink._fallback_writer == mock_writer

@patch("services.frame_sink.cv2.VideoWriter")
@patch("services.frame_sink.subprocess.Popen")
def test_frame_sink_write_and_release_opencv(mock_popen, mock_video_writer, tmp_path):
    """Test writing a frame and releasing using the OpenCV fallback mechanism[cite: 5]."""
    ffmpeg_path = tmp_path / "nonexistent_ffmpeg.exe"
    
    mock_writer = MagicMock()
    mock_writer.isOpened.return_value = True
    mock_video_writer.return_value = mock_writer
    
    output_file = str(tmp_path / "output.avi")
    sink = FrameSink(output_file, w=100, h=100, fps=30, ffmpeg_path=ffmpeg_path)
    
    # Create a dummy frame (100x100 BGR)
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    sink.write(frame)
    
    mock_writer.write.assert_called_once()
    
    res = sink.release(output_file)
    mock_writer.release.assert_called_once()
    assert isinstance(res, str)

@patch("services.frame_sink.cv2.VideoWriter")
@patch("services.frame_sink.subprocess.Popen")
def test_frame_sink_write_ffmpeg(mock_popen, mock_video_writer, tmp_path):
    """Test writing a frame through the active FFmpeg process stdin pipe[cite: 5]."""
    ffmpeg_path = tmp_path / "ffmpeg.exe"
    ffmpeg_path.touch()
    
    mock_proc = MagicMock()
    mock_popen.return_value = mock_proc
    
    output_file = str(tmp_path / "output.mp4")
    sink = FrameSink(output_file, w=100, h=100, fps=30, ffmpeg_path=ffmpeg_path)
    
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    sink.write(frame)
    
    # Verify FFmpeg stdin received the byte data
    mock_proc.stdin.write.assert_called_once()