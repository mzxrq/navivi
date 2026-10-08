import json

from services.vdoprocessing.videopipeline import leg_pieces


def test_piece_toward_unnarrated_stop_by_gets_no_voice(tmp_path, monkeypatch):
    from services.tts.ttsengine import FFmpegManager

    monkeypatch.setattr(FFmpegManager, "resolve_ffmpeg_bin", staticmethod(lambda: "ffmpeg"))
    monkeypatch.setattr(FFmpegManager, "get_media_duration", staticmethod(lambda _p: 10.0))
    route = tmp_path / "route"
    route.mkdir()
    first, second = route / "02_waypoint_03_b.mp4", route / "02_waypoint_03_b_cont2.mp4"
    plan = {"pieces": [{"file": first.name, "target_waypoint_id": "stopby"},
                       {"file": second.name, "target_waypoint_id": "b"}]}
    (route / "02_waypoint_03_pieces.json").write_text(json.dumps(plan), encoding="utf-8")
    waypoints = [{"id": "x"}, {"id": "y"}, {"id": "a"}, {"id": "stopby"}, {"id": "b"}]
    audio = ["x.wav", "y.wav", "a.wav", None, "b.wav"]
    subs = ["x.srt", "y.srt", "a.srt", None, "b.srt"]

    _, splits = leg_pieces.compute_leg_narration_splits(
        [str(first), str(second)], audio, subs, waypoints, str(tmp_path)
    )

    # Before: no entry, so the timeline fell back to the departure's (a.wav) narration and replayed it.
    assert splits[first.stem] == (None, None)
    assert splits[second.stem] == ("b.wav", "b.srt")
