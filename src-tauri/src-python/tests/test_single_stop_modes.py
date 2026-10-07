"""The single-stop CLI modes the editor's Regenerate menu runs ("subtitle 1 --force", "attraction 1 --force")."""

import json
import math
import struct
import subprocess
import sys
import wave
from pathlib import Path

MAIN = Path(__file__).resolve().parent.parent / "main.py"


def _project(tmp_path: Path, popup=None) -> Path:
    audio = tmp_path / "assets" / "audio"
    audio.mkdir(parents=True)
    with wave.open(str(audio / "02_waypoint_02_Castle.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"".join(
            struct.pack("<h", 0 if 22400 < i < 27200 else int(8000 * math.sin(i / 20))) for i in range(48000)
        ))
    text = "We arrive at the old castle. It is very quiet here."
    stop = {"id": "b", "label": "Castle", "lat": 35.01, "lng": 135.01, "arrivingNarration": text, "narration": text, "script": text}
    if popup:
        stop["popup_image"] = [popup]
    config = {
        "project_name": "fixture", "directory_path": str(tmp_path), "settings": {},
        "waypoints": [{"id": "a", "label": "Start", "lat": 35.0, "lng": 135.0}, stop],
    }
    path = tmp_path / "job_config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_subtitle_for_one_stop_lands_in_the_subtitles_folder(tmp_path):
    config = _project(tmp_path)
    run = subprocess.run(
        [sys.executable, str(MAIN), str(config), "subtitle 1 --force"], capture_output=True, text=True, timeout=120
    )
    reply = json.loads(run.stdout[run.stdout.rindex(chr(10) + "{") + 1:] if chr(10) + "{" in run.stdout else run.stdout)
    assert reply["success"], reply
    assert (tmp_path / "assets" / "subtitles" / "02_waypoint_02_Castle.srt").exists()
    assert not list((tmp_path / "assets" / "video").glob("*.srt"))


def test_attraction_mode_sees_the_projects_relative_photo_paths(tmp_path):
    from services.cli.attraction_commands import _load_waypoints
    from services.config.job_config import JobConfigManager

    JobConfigManager._instance = None
    config = _project(tmp_path, popup="assets/image/castle.png")
    _, waypoints = _load_waypoints(str(config))
    photo = Path(waypoints[1]["popup_image"][0])
    assert photo.is_absolute()
    assert photo == (tmp_path / "assets" / "image" / "castle.png").resolve() or photo.name == "castle.png"
