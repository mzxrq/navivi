import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from test_main import PYTHON_SOURCE_DIR  # noqa: F401
import main


class FakeAudioProcessor:
    def __init__(self, output_dir=None):
        pass

    def analyze_pauses(self, path):
        return {"duration_seconds": 1.25, "pauses": []}


class FakeTTSClient:
    def __init__(self, output_dir=None):
        self.output_dir = Path(output_dir)

    async def generate_speech(self, text, output_filename=None):
        output = self.output_dir / output_filename
        with wave.open(str(output), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\x01\x00" * 16000)
        return str(output)


class TestIndividualServices(unittest.TestCase):
    def _config(self, root, waypoints):
        path = root / "job_config.json"
        path.write_text(json.dumps({"waypoints": waypoints}), encoding="utf-8")
        return path

    def test_tts_single_generates_matching_audio_name(self):
        with tempfile.TemporaryDirectory() as temp:
            config = self._config(
                Path(temp), [{"label": "Test Place", "script": "Hello."}]
            )
            with patch("services.tts.ttsengine.IrodoriTTSClient", FakeTTSClient), patch(
                "services.tts.ttsengine.AudioProcessor", FakeAudioProcessor
            ):
                result = main.test_tts(str(config))

            self.assertTrue(result["clip"]["audio_path"].endswith(
                "02_waypoint_01_Test_Place.wav"
            ))

    def test_subtitle_single_writes_srt_from_matching_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = self._config(
                root, [{"label": "Test Place", "script": "Hello."}]
            )
            audio_dir = root / "audio"
            audio_dir.mkdir()
            audio_path = audio_dir / "02_waypoint_01_Test_Place.wav"
            with wave.open(str(audio_path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(b"\x01\x00" * 16000)

            result = main.test_subtitle(str(config))

            subtitle_path = Path(result["subtitle_path"])
            self.assertTrue(subtitle_path.exists())
            self.assertEqual(subtitle_path.name, "02_waypoint_01_Test_Place.srt")
            self.assertEqual(result["cue_count"], 1)

    def test_attraction_single_passes_popup_and_output_name(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / "place.png"
            image.write_bytes(b"image")
            config = self._config(
                root,
                [{"label": "Test Place", "popup_image": str(image)}],
            )
            calls = []

            class FakeGenerator:
                def __init__(self, config):
                    self.output_dir = root / "video"

                def process_attraction_video(self, **kwargs):
                    calls.append(kwargs)
                    output = self.output_dir / kwargs["output_filename"]
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(b"video")
                    return str(output)

            with patch(
                "services.vdoprocessing.img2vdo.AttractionVideoGenerator",
                FakeGenerator,
            ):
                result = main.test_attraction_video(str(config))

            self.assertEqual(
                calls[0]["output_filename"],
                "04_attraction_00_Test_Place.mp4",
            )
            self.assertTrue(result["video_path"].endswith(
                "04_attraction_00_Test_Place.mp4"
            ))

    def test_concat_single_copies_clip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = self._config(root, [])
            video_dir = root / "video"
            video_dir.mkdir()
            source = video_dir / "source.mp4"
            source.write_bytes(b"video")

            result = main.test_video_concat(str(config), str(video_dir), [str(source)])

            self.assertEqual(Path(result["video_path"]).read_bytes(), b"video")


if __name__ == "__main__":
    unittest.main()
