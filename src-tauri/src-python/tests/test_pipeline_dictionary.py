"""A full TTS run speaks the app-wide pronunciation words too, as the single-stop retakes do
(videopipeline/audio_step.generate_audio)."""

import json
import wave

from services.tts import ttsengine
from services.vdoprocessing.videopipeline import audio_step


class _Voice:
    def __init__(self, output_dir):
        self.output_dir, self.spoken, self.bypass_cache = output_dir, [], False

    async def generate_speech(self, text, output_filename):
        self.spoken.append(text)
        path = self.output_dir / output_filename
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(8000)
            w.writeframes(b"\x00\x10" * 8000)
        return str(path)

    def stop_server(self):
        pass


def test_the_app_wide_words_reach_the_voice(monkeypatch, tmp_path):
    config = tmp_path / "job_config.json"
    config.write_text(json.dumps({
        "settings": {
            "global_pronunciation_dictionary": [{"word": "三段壁", "reading": "さんだんべき"}],
            "pronunciation_dictionary": [{"word": "白良浜", "reading": "しららはま"}],
        },
        "waypoints": [{"id": "a", "label": "A", "arrivingNarration": "三段壁から白良浜へ。"}],
    }), encoding="utf-8")
    voices = []
    monkeypatch.setattr(ttsengine, "make_tts_client", lambda settings, out: voices.append(_Voice(out)) or voices[-1])
    monkeypatch.setattr(audio_step, "stop_tts_server", lambda: None)

    audio_step.generate_audio({}, str(config))

    spoken = "".join(voices[0].spoken)
    assert "三段壁" not in spoken and "白良浜" not in spoken  # both dictionaries applied
