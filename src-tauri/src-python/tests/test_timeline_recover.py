from services.vdoprocessing.videopipeline.pipeline import recover_narration_paths


def _timeline(**track_extra):
    return {
        "video_tracks": [
            {"clip_id": "a", "file_path": "a.mp4", **track_extra},
            {"clip_id": "b", "file_path": "b.mp4"},
        ],
        "ui_state": {
            "tracks": [{"id": "v", "type": "video"}, {"id": "au", "type": "audio"}],
            "clips": [
                {"id": "a", "trackId": "v", "startTime": 0},
                {"id": "b", "trackId": "v", "startTime": 10},
                {"id": "n1", "trackId": "au", "type": "audio", "startTime": 10, "source": "b.wav"},
            ],
        },
    }


def test_relinks_audio_by_start_time():
    data = _timeline()
    assert recover_narration_paths(data) == 1
    assert data["video_tracks"][1]["audio_path"] == "b.wav"
    assert "audio_path" not in data["video_tracks"][0]


def test_leaves_pipeline_manifests_alone():
    data = _timeline(audio_path="x.wav")
    assert recover_narration_paths(data) == 0
    assert "audio_path" not in data["video_tracks"][1]
