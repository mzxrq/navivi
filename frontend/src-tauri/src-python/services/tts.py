"""
TTS processor for generating speech audio via the Irodori TTS service.
"""
import httpx
import uuid
from pathlib import Path

# Directory to store generated audio files
OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

async def call_irodori_api(text: str) -> bytes:
    """
    Makes an HTTP POST request to the local Irodori TTS API to generate speech.
    
    Args:
        text (str): The text to synthesize.
        
    Returns:
        bytes: The raw audio content.
        
    Raises:
        Exception: If the API request fails.
    """
    url = "http://localhost:8088/v1/audio/speech"
    payload = {
        "model": "irodori-tts",
        "input": text,
        "voice": "none" 
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, timeout=30.0)
        
        if response.status_code != 200:
            print(f"Server returned {response.status_code}: {response.text}")
            raise Exception(f"API request failed with status {response.status_code}")
            
        return response.content

async def get_irodori_speech(text: str) -> str:
    """
    Generates speech audio for the given text and saves it to a local file.
    
    Args:
        text (str): The text to synthesize.
        
    Returns:
        str: The absolute or relative path to the saved WAV file.
    """
    file_id = str(uuid.uuid4())
    file_path = OUTPUT_DIR / f"{file_id}.wav"
    
    # Call the API to get raw audio bytes
    audio_content = await call_irodori_api(text)
    
    # Save the audio content to disk
    with open(file_path, "wb") as f:
        f.write(audio_content)
        
    return str(file_path)