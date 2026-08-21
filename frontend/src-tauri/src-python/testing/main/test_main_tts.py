# testing/test_main_tts.py
from unittest.mock import MagicMock, AsyncMock
from main import generate_audio_tts # type: ignore

def test_generate_audio_tts_success():
    """Test generating TTS audio paths and narration flags successfully from waypoints."""
    # 1. Mock the JobConfigManager to return sample waypoints with text
    mock_job_config = MagicMock()
    mock_job_config.get_waypoints.return_value = [
        {"text": "Turn left at the station"},
        {"text": "Arrive at destination"}
    ]
    
    # 2. Mock the TTSService to return fake WAV audio paths asynchronously
    mock_tts_service = MagicMock()
    mock_tts_service.get_irodori_speech = AsyncMock(side_effect=[
        "audio/wav_1.wav", 
        "audio/wav_2.wav"
    ])
    
    # 3. Execute the function
    paths, has_narration = generate_audio_tts(mock_job_config, mock_tts_service)
    
    # 4. Assertions
    assert paths == ["audio/wav_1.wav", "audio/wav_2.wav"]
    assert has_narration == [True, True]
    assert mock_tts_service.get_irodori_speech.await_count == 2

def test_generate_audio_tts_with_empty_or_failed_text():
    """Test handling of empty text (silence fallback) and API exceptions gracefully."""
    # 1. Mock waypoints: one empty text, one valid text that raises an exception
    mock_job_config = MagicMock()
    mock_job_config.get_waypoints.return_value = [
        {"text": ""},                      # Empty text -> should result in None
        {"text": "This will fail API"}     # Exception -> should fallback to None
    ]
    
    mock_tts_service = MagicMock()
    mock_tts_service.get_irodori_speech = AsyncMock(side_effect=Exception("API Error"))
    
    # 2. Execute the function
    paths, has_narration = generate_audio_tts(mock_job_config, mock_tts_service)
    
    # 3. Assertions (both should gracefully fallback to None and False)
    assert paths == [None, None]
    assert has_narration == [False, False]