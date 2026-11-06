import json

from services.config.sub_course import sub_config, write_sub_config
from services.vdoprocessing.videopipeline.sub_course_step import merge_tracks


def _job(ends_at_main=False):
    main = [
        {"id": "s", "label": "Start", "lat": 0, "lng": 0},
        {"id": "a", "label": "Shrine", "lat": 1, "lng": 0, "images": ["assets/image/a.jpg"], "attractionNarration": "A shrine."},
        {"id": "e", "label": "Port", "lat": 2, "lng": 0, "arrivingNarration": "We reach the port.", "images": ["assets/image/e.jpg"]},
    ]
    sub = [
        {"id": "x", "branchOf": "a", "label": "Shrine", "lat": 1, "lng": 0, "images": ["assets/image/a.jpg"], "routeMode": "walking"},
        {"id": "b1", "label": "Falls", "lat": 5, "lng": 0, "images": ["assets/image/f.jpg"], "arrivingNarration": "The falls."},
    ]
    if ends_at_main:
        sub.append({"id": "y", "branchOf": "e", "label": "Port", "lat": 2, "lng": 0, "images": ["assets/image/e.jpg"]})
    return {
        "project_id": "p", "settings": {"fps": 30}, "overview_narration": "Hello.", "waypoints": main,
        "source_files": {"gps_route": "raw_track.gpx", "sub_gps_route": "raw_track_sub.gpx"},
        "sub_course": {"name": "Falls way", "waypoints": sub},
    }


def test_the_sub_course_becomes_its_own_small_project(tmp_path):
    config = sub_config(_job(ends_at_main=True), tmp_path)
    stops = config["waypoints"]
    assert [w["id"] for w in stops] == ["x", "b1", "y"]
    assert stops[0]["images"] == [] and stops[0]["arrivingNarration"] == ""  # the branch stop is already shown
    assert stops[-1]["images"] == [] and stops[-1]["arrivingNarration"] == "We reach the port."  # arrives, no clip again
    assert stops[1]["images"] == [str((tmp_path / "assets/image/f.jpg").resolve())]
    assert config["source_files"]["gps_route"] == str((tmp_path / "raw_track_sub.gpx").resolve())
    assert "overview_narration" not in config and config["enable_intro"] is False
    assert config["start_point"]["lat"] == 1 and config["end_point"]["lat"] == 2


def test_no_sub_course_writes_nothing(tmp_path):
    job = _job()
    job["sub_course"]["waypoints"] = job["sub_course"]["waypoints"][:1]
    (tmp_path / "job_config.json").write_text(json.dumps(job), encoding="utf-8")
    assert write_sub_config(tmp_path / "job_config.json") is None
    job["sub_course"] = _job()["sub_course"]
    (tmp_path / "job_config.json").write_text(json.dumps(job), encoding="utf-8")
    assert write_sub_config(tmp_path / "job_config.json").exists()


def test_the_sub_course_clips_go_before_the_outro_with_its_title():
    track = lambda name, d: {"file_path": f"C:/p/{name}", "duration": d}  # noqa: E731
    main = {
        "total_duration_seconds": 30.0,
        "video_tracks": [track("00_intro.mp4", 10), track("leg.mp4", 10), track("99_outro.mp4", 10)],
        "subtitles": [{"start": 12, "end": 14, "text": "main"}, {"start": 22, "end": 24, "text": "outro"}],
        "texts": [],
    }
    sub = {"total_duration_seconds": 8.0, "video_tracks": [track("sub_leg.mp4", 8)], "subtitles": [{"start": 1, "end": 2, "text": "sub"}]}
    from services import tuning

    main["video_tracks"][-1]["file_path"] = f"C:/p/{tuning.OUTRO_OUTPUT_FILENAME}"
    out, shift = merge_tracks(main, sub, "Falls way")
    assert shift == 8.0
    assert [t["file_path"].split("/")[-1] for t in out["video_tracks"]] == ["00_intro.mp4", "leg.mp4", "sub_leg.mp4", tuning.OUTRO_OUTPUT_FILENAME]
    assert [t["order"] for t in out["video_tracks"]] == [0, 1, 2, 3]
    assert [(c["text"], c["start"]) for c in out["subtitles"]] == [("main", 12), ("sub", 21), ("outro", 30)]
    assert out["texts"][0]["title"]["text"] == "Falls way" and out["texts"][0]["start"] == 20
    assert out["video_tracks"][2]["texts"][0]["animation"] == "none"
    assert out["total_duration_seconds"] == 38.0
