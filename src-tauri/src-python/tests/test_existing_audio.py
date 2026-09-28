import json
import wave

from services.vdoprocessing.videopipeline.audio_step import existing_audio_data
from services.vdoprocessing.videopipeline.helpers import (
    attraction_audio_filename,
    project_audio_dir,
    waypoint_audio_filename,
)


def _wav(path, seconds, rate=8000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x10\x00" * int(rate * seconds))


def test_existing_audio_is_read_without_tts(tmp_path):
    cfg = {
        "overview_narration": "はじまり。{start}ここへ。{1}つぎへ。{end}おわり。",
        "waypoints": [
            {"id": "a", "label": "駅", "arrivingNarration": "出発です。"},
            {"id": "b", "label": "石標", "isStopBy": True, "connectToRoute": False,
             "arrivingNarration": "とおります。", "attractionNarration": "ここです。"},
            {"id": "c", "label": "神社", "arrivingNarration": "着きます。", "attractionNarration": "神社です。"},
        ],
    }
    (tmp_path / "job_config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    audio_dir = project_audio_dir(tmp_path)
    _wav(audio_dir / waypoint_audio_filename(0, "駅"), 2.0)
    _wav(audio_dir / waypoint_audio_filename(1, "石標"), 2.0)  # unconnected stop-by: ignored
    _wav(audio_dir / attraction_audio_filename(2, "神社"), 3.0)
    _wav(audio_dir / "00_overview_narration.wav", 8.0)

    data = existing_audio_data(str(tmp_path / "job_config.json"))
    assert [round(d) for d in data["audio_durations"]] == [2, 0, 0]  # waypoint 2 has no leg audio yet
    assert data["audio_paths"][1] is None and data["attraction_audio_paths"][1] is None
    assert round(data["attraction_audio_durations"][2]) == 3
    assert round(data["overview_audio_duration"]) == 8
    assert set(data["overview_cue_times"]) == {"start", "1", "end"}
    times = data["overview_cue_times"]
    assert times["start"] < times["1"] < times["end"]
