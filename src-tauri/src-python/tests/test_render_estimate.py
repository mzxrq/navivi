from services import render_estimate as re_


def _config(**settings):
    return {
        "settings": {"res_duration": 10, "duration_seconds": 8, **settings},
        "overview_narration": "abcd",
        "waypoints": [
            {"arrivingNarration": "hello {arrive}", "images": ["a.jpg"]},
            {"arrivingNarration": "", "attractionNarration": "xyz"},
            {},
        ],
    }


def test_workload_counts_chars_clips_and_video_seconds():
    w = re_.workload(_config())
    assert w["tts"] == 4 + 5 + 3
    assert w["attraction"] == 1
    assert w["route"] == 28.0


def test_fast_render_drops_voice_and_clips():
    w = re_.workload(_config(skip_rich_media=True))
    assert w["tts"] == w["attraction"] == w["subtitles"] == 0


def test_history_replaces_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(re_, "history_path", lambda: tmp_path / "t.json")
    monkeypatch.setattr(re_, "hardware_profile", lambda: {"speed_factor": 1.0})
    base = re_.estimate(_config())
    assert base["measured_stages"] == 0
    for _ in range(2):
        re_.StageRecorder._store("route", 28.0, 28.0)
    learned = re_.estimate(_config())
    assert learned["measured_stages"] == 1
    assert learned["stages"]["route"] == 28.0


def test_recorder_ignores_unit_less_and_tiny_stages(tmp_path, monkeypatch):
    monkeypatch.setattr(re_, "history_path", lambda: tmp_path / "t.json")
    rec = re_.StageRecorder(_config(skip_rich_media=True))
    rec.on_stage(2)
    rec.finish()
    assert re_.load_history() == {}
