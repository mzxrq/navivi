from pathlib import Path


def test_route_latlon_reads_the_gps_csv(tmp_path: Path):
    from services.projectfiles import gps_data_dir
    from services.vdoprocessing.videopipeline.finale_step import route_latlon

    assert route_latlon(tmp_path) == []
    d = gps_data_dir(tmp_path)
    d.mkdir(parents=True)
    (d / "gpsdata.csv").write_text("index,latitude,longitude\n1,34.1,135.2\n2,,\n3,34.2,135.3\n", encoding="utf-8")
    assert route_latlon(tmp_path) == [(34.1, 135.2), (34.2, 135.3)]


def test_finale_is_off_without_an_outro(tmp_path: Path):
    import json

    from services.vdoprocessing.videopipeline.finale_step import render_finale_clip

    cfg = tmp_path / "job_config.json"
    cfg.write_text(json.dumps({"settings": {"enable_outro": False}, "waypoints": []}), encoding="utf-8")
    assert render_finale_clip(str(cfg)) is None


def test_the_finale_plays_its_narration_from_its_timing_sidecar(tmp_path: Path, monkeypatch):
    import json

    from services import tuning
    from services.vdoprocessing.cliptiming import write_audio_offset
    from services.vdoprocessing.videopipeline import timeline_step
    from services.vdoprocessing.videopipeline.audio_step import FINALE_NARRATION_FILENAME
    from services.vdoprocessing.videopipeline.helpers import project_audio_dir

    monkeypatch.setattr(timeline_step, "_duration", lambda p: 10.0 if p else 0.0)
    (tmp_path / "job_config.json").write_text(json.dumps({"waypoints": []}), encoding="utf-8")
    video = tmp_path / "assets/video"
    video.mkdir(parents=True)
    finale, outro = video / tuning.FINALE_OUTPUT_FILENAME, video / tuning.OUTRO_OUTPUT_FILENAME
    for f in (finale, outro):
        f.write_bytes(b"x")
    voice = Path(project_audio_dir(tmp_path)) / FINALE_NARRATION_FILENAME
    voice.parent.mkdir(parents=True, exist_ok=True)
    voice.write_bytes(b"x")
    write_audio_offset(str(finale), 1.0)
    from services.vdoprocessing.videopipeline.helpers import project_subtitle_dir

    srt = Path(project_subtitle_dir(tmp_path)) / "98_finale_narration.srt"
    srt.parent.mkdir(parents=True, exist_ok=True)
    srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nThat was the whole route.\n", encoding="utf-8")

    path = timeline_step.build_timeline(
        video_paths=[], attraction_videos=[], final_videos=[str(finale), str(outro)], project_dir=str(tmp_path),
    )
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    tracks = data["video_tracks"]
    assert [(c["start"], c["text"]) for c in data["subtitles"]] == [(1.0, "That was the whole route.")]
    assert tracks[0]["audio_path"] and Path(tracks[0]["audio_path"]).name == FINALE_NARRATION_FILENAME
    assert tracks[0]["audio_offset"] == 1.0
    assert not tracks[0].get("fade_into_next_seconds")  # cuts to the outro


def test_an_unchanged_finale_is_reused_not_captured_again(tmp_path: Path, monkeypatch):
    import json

    import numpy as np
    from PIL import Image

    from services.mapfetcher import pydeck_overview
    from services.projectfiles import gps_data_dir
    from services.vdoprocessing import outrocard
    from services.vdoprocessing.videopipeline.finale_step import render_finale_clip

    captures = []

    def capture(*args, **kwargs):
        captures.append(1)
        return [(np.zeros((1080, 1920, 3), np.uint8), (135.0, 34.0, 136.0, 35.0))] * 2

    def pipe(frames, part, fps, size):
        Path(part).parent.mkdir(parents=True, exist_ok=True)
        Path(part).write_bytes(b"mp4")
        return True

    monkeypatch.setattr(pydeck_overview, "capture_pydeck_zoom_sequence", capture)
    monkeypatch.setattr(outrocard, "_pipe_frames", pipe)
    Image.new("RGB", (64, 48)).save(tmp_path / "end.jpg")
    d = gps_data_dir(tmp_path)
    d.mkdir(parents=True)
    (d / "gpsdata.csv").write_text("latitude,longitude\n34.1,135.2\n34.2,135.3\n", encoding="utf-8")
    cfg = tmp_path / "job_config.json"
    stops = [{"lat": 34.1, "lng": 135.2}, {"lat": 34.2, "lng": 135.3, "popup_image": str(tmp_path / "end.jpg")}]
    cfg.write_text(json.dumps({"settings": {}, "waypoints": stops}), encoding="utf-8")

    first = render_finale_clip(str(cfg))
    assert first and render_finale_clip(str(cfg)) == first
    assert len(captures) == 1
    render_finale_clip(str(cfg), force=True)
    assert len(captures) == 2
