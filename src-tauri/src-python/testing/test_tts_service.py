# testing/test_tts_service.py

import pytest
import wave
import asyncio
import numpy as np
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
from services.tts import TTSService

@pytest.fixture
def tts_instance(tmp_path):
    """Fixture providing a TTSService instance with isolated temporary directories."""
    audio_dir = tmp_path / "audio"
    output_dir = tmp_path / "outputs"
    return TTSService(audio_dir=audio_dir, output_dir=output_dir)

def test_analyze_wav_pauses(tts_instance, tmp_path):
    """Test reading a .wav file and detecting silent pause intervals."""
    wav_file = tmp_path / "test_audio.wav"
    
    framerate = 16000
    loud_chunk = np.ones(int(framerate * 0.1), dtype=np.int16) * 10000
    silent_chunk = np.zeros(int(framerate * 0.5), dtype=np.int16)
    audio_data = np.concatenate([loud_chunk, silent_chunk, loud_chunk])
    
    with wave.open(str(wav_file), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(framerate)
        wf.writeframes(audio_data.tobytes())
        
    result = TTSService.analyze_wav_pauses(str(wav_file), silence_threshold=500, min_pause_duration=0.2)
    
    assert "duration_seconds" in result
    assert "pauses" in result
    assert len(result["pauses"]) == 1
    assert result["pauses"][0]["duration"] >= 0.2

@patch("services.tts.subprocess.run")
def test_get_media_duration(mock_run, tts_instance):
    """Test extracting exact media duration using ffprobe."""
    mock_run.return_value = MagicMock(returncode=0, stdout="12.345\n")
    
    with patch.object(TTSService, "_resolve_ffprobe_bin", return_value="ffprobe.exe"):
        duration = TTSService._get_media_duration("dummy.mp4")
        assert duration == 12.345

@patch("services.tts.subprocess.run")
def test_get_audio_format(mock_run, tts_instance):
    """Test probing sample rate and channel count from an audio file."""
    mock_run.return_value = MagicMock(returncode=0, stdout="24000\n2\n")
    
    with patch.object(TTSService, "_resolve_ffprobe_bin", return_value="ffprobe.exe"):
        sr, ch = TTSService.get_audio_format("dummy.wav")
        assert sr == 24000
        assert ch == 2

def test_detect_reference_audio_format(tts_instance, tmp_path):
    """Test locating the first valid narration file to extract reference audio format."""
    dummy_wav = tmp_path / "narration.wav"
    dummy_wav.touch()
    
    with patch.object(TTSService, "get_audio_format", return_value=(16000, 1)):
        sr, ch = TTSService._detect_reference_audio_format([None, str(dummy_wav)], default_sample_rate=44100)
        assert sr == 16000
        assert ch == 1

    sr_fb, ch_fb = TTSService._detect_reference_audio_format([None, "missing.wav"], default_sample_rate=44100, default_channels=2)
    assert sr_fb == 44100
    assert ch_fb == 2

def test_call_irodori_api(tts_instance):
    """Test successful communication with the local Irodori TTS API."""
    async def run_test():
        mock_response = MagicMock(status_code=200, content=b"RIFF_DUMMY_AUDIO_BYTES")
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            content = await tts_instance.call_irodori_api("Turn left")
            assert content == b"RIFF_DUMMY_AUDIO_BYTES"

    asyncio.run(run_test())

def test_get_irodori_speech(tts_instance):
    """Test generating and saving speech audio to a local WAV file."""
    async def run_test():
        with patch.object(TTSService, "call_irodori_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = b"RIFF_AUDIO_DATA"
            
            saved_path = await tts_instance.get_irodori_speech("Go straight")
            assert Path(saved_path).exists()
            assert Path(saved_path).read_bytes() == b"RIFF_AUDIO_DATA"

    asyncio.run(run_test())

@patch("services.tts.subprocess.run")
def test_assemble_final_deliverable_orchestration(mock_run, tts_instance):
    """Test top-level pipeline orchestration across all assembly stages."""
    mock_run.return_value = MagicMock(returncode=0, stdout="2.0\n")
    
    with patch.object(TTSService, "_get_media_duration", return_value=5.0), \
         patch.object(TTSService, "normalize_segment_audio", return_value="norm_video.mp4"), \
         patch.object(TTSService, "concatenate_video_segments", return_value="full_video.mp4"), \
         patch.object(TTSService, "build_full_narration_master_audio", return_value="full_audio.wav"), \
         patch.object(TTSService, "combine_video_and_master_audio", return_value="final_combined.mp4"):
         
        result = tts_instance.assemble_final_deliverable(
            video_segment_paths=["seg1.mp4"],
            segment_has_narration=[False],
            segment_durations=[5.0],
            segment_narration_audio=[None]
        )
        
        assert result["full_video_path"] == "full_video.mp4"
        assert result["full_audio_path"] == "full_audio.wav"
        assert result["final_combined_path"] == "final_combined.mp4"