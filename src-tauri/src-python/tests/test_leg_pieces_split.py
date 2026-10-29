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


def test_padded_copy_from_an_earlier_run_is_reused(tmp_path, monkeypatch):
    import os
    from services.tts.ttsengine import FFmpegManager
    from services.vdoprocessing.videopipeline import leg_pieces

    src, padded = tmp_path / "L_cont2.mp4", tmp_path / "L_cont2_padded.mp4"
    src.write_bytes(b"x"); padded.write_bytes(b"x")
    os.utime(src, (1, 1))
    monkeypatch.setattr(FFmpegManager, "get_media_duration", staticmethod(lambda p: 12.0 if p.endswith("_padded.mp4") else 10.0))
    monkeypatch.setattr(leg_pieces.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("re-encoded")))
    assert leg_pieces._pad_video_tail("ffmpeg", str(src), 1.5) == str(padded)
