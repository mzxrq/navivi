"""The overview voice starts on the intro: intro length, timeline placement, export."""

import json
from pathlib import Path

from services import tuning
from services.vdoprocessing.introclip import fitted_layout
from services.vdoprocessing.videopipeline.intro_step import plan_intro_seconds
from services.vdoprocessing.videopipeline.pipeline import move_timed_narration
from services.vdoprocessing.videopipeline.timeline_step import build_timeline


class TestPlanIntroSeconds:
    def test_the_intro_lasts_until_the_start_cue(self):
        assert plan_intro_seconds({}, {"start": 15.2, "1": 20.0}, 70.0) == tuning.INTRO_VOICE_LEAD_SECONDS + 15.2

    def test_clamped(self):
        assert plan_intro_seconds({}, {"start": 1.0}, 70.0) == tuning.INTRO_MIN_SECONDS
        assert plan_intro_seconds({}, {"start": 60.0}, 70.0) == tuning.INTRO_MAX_SECONDS

    def test_no_start_cue_keeps_the_default_slideshow(self):
        n = tuning.INTRO_IMAGE_COUNT
        default = n * tuning.INTRO_PER_IMAGE_SECONDS - (n - 1) * tuning.INTRO_CROSSFADE_SECONDS
        assert plan_intro_seconds({}, None, 70.0) == default

    def test_off_or_no_voice(self):
        assert plan_intro_seconds({"overview_voice_over_intro": False}, {"start": 10.0}, 70.0) is None
        assert plan_intro_seconds({}, {"start": 10.0}, 0.0) is None


class TestFittedLayout:
    def test_photos_add_up_to_the_length(self):
        for duration in (4.0, 9.0, 15.5, 26.0):
            n, per = fitted_layout(duration, 10)
            assert 1 <= n <= tuning.INTRO_MAX_IMAGE_COUNT
            assert abs(n * per - (n - 1) * tuning.INTRO_CROSSFADE_SECONDS - duration) < 1e-6

    def test_never_more_photos_than_there_are(self):
        assert fitted_layout(20.0, 2)[0] == 2
        assert fitted_layout(20.0, 1) == (1, 20.0)


def _touch(p: Path) -> str:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    return str(p)


def test_the_overview_voice_is_placed_on_the_timeline_from_the_intro(tmp_path, monkeypatch):
    from services.vdoprocessing.videopipeline import timeline_step

    lengths = {"00_intro.mp4": 10.0, "01_overview.mp4": 50.0, "overview.wav": 58.0}
    monkeypatch.setattr(timeline_step, "_duration", lambda p: lengths.get(Path(p).name, 0.0) if p else 0.0)
    (tmp_path / "job_config.json").write_text(json.dumps({"waypoints": []}), encoding="utf-8")
    route = tmp_path / "assets/video/route"
    intro = _touch(route / "00_intro.mp4")
    overview = _touch(route / "01_overview.mp4")
    srt = tmp_path / "overview.srt"
    srt.write_text(
        "1\n00:00:01,000 --> 00:00:04,000\nopening\n\n"
        "2\n00:00:08,000 --> 00:00:11,000\nacross\n\n"
        "3\n00:00:20,000 --> 00:00:22,000\nroute\n",
        encoding="utf-8",
    )
    path = build_timeline(
        video_paths=[intro, overview], attraction_videos=[], final_videos=[intro, overview],
        project_dir=str(tmp_path), overview_audio_path=_touch(tmp_path / "overview.wav"),
        overview_subtitle_path=str(srt), overview_voice_start=0.5,
    )
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    intro_track, overview_track = data["video_tracks"]
    assert intro_track["audio_path"] is None and "audio_start" not in intro_track
    assert overview_track["audio_start"] == 0.5 and overview_track["audio_path"].endswith("overview.wav")
    # the overview keeps its own length: the voice started 9.5 s earlier
    assert data["total_duration_seconds"] == 60.0
    assert intro_track["subtitles"] == [
        {"start": 1.5, "end": 4.5, "text": "opening"}, {"start": 8.5, "end": 10.0, "text": "across"}]
    assert overview_track["subtitles"] == [
        {"start": 0.0, "end": 1.5, "text": "across"}, {"start": 10.5, "end": 12.5, "text": "route"}]
    assert [c["start"] for c in data["subtitles"]] == [1.5, 8.5, 10.0, 20.5]


def test_without_a_voice_start_the_overview_is_unchanged(tmp_path, monkeypatch):
    from services.vdoprocessing.videopipeline import timeline_step

    lengths = {"00_intro.mp4": 10.0, "01_overview.mp4": 50.0, "overview.wav": 58.0}
    monkeypatch.setattr(timeline_step, "_duration", lambda p: lengths.get(Path(p).name, 0.0) if p else 0.0)
    (tmp_path / "job_config.json").write_text(json.dumps({"waypoints": []}), encoding="utf-8")
    route = tmp_path / "assets/video/route"
    intro, overview = _touch(route / "00_intro.mp4"), _touch(route / "01_overview.mp4")
    path = build_timeline(
        video_paths=[intro, overview], attraction_videos=[], final_videos=[intro, overview],
        project_dir=str(tmp_path), overview_audio_path=_touch(tmp_path / "overview.wav"),
    )
    tracks = json.loads(Path(path).read_text(encoding="utf-8"))["video_tracks"]
    assert "audio_start" not in tracks[1]
    assert json.loads(Path(path).read_text(encoding="utf-8"))["total_duration_seconds"] == 68.0


def test_a_timed_narration_is_exported_as_unlinked_audio():
    data = {
        "video_tracks": [
            {"file_path": "intro.mp4", "audio_path": None},
            {"file_path": "overview.mp4", "audio_path": "C:/p/overview.wav", "audio_start": 0.5, "audio_offset": 0},
            {"file_path": "leg.mp4", "audio_path": "C:/p/leg.wav", "audio_offset": 2.0},
        ],
        "unlinked_audio": [],
    }
    assert move_timed_narration(data) == 1
    assert data["video_tracks"][1]["audio_path"] is None
    assert data["video_tracks"][2]["audio_path"] == "C:/p/leg.wav"
    assert data["unlinked_audio"] == [{"path": "C:/p/overview.wav", "start": 0.5, "volume": 1.0}]
