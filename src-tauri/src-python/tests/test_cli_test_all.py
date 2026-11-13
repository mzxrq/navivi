"""`main.py <config> all --force` clears generated outputs but never the user's own imports."""

from services.cli import combine_commands, helpers as cli_helpers
from services.vdoprocessing.videopipeline import helpers as pipeline_helpers


def test_force_keeps_imported_footage_and_music(monkeypatch, tmp_path):
    (tmp_path / "job_config.json").write_text("{}", encoding="utf-8")
    assets = tmp_path / "assets"
    own = [assets / "video" / "user" / "mine.mp4", assets / "video" / "custom" / "clip.mp4", assets / "audio" / "music" / "song.mp3"]
    generated = [
        assets / "video" / "route" / "02_waypoint_01_leg.mp4",
        assets / "video" / "attraction" / "04_attraction_01.mp4",
        assets / "audio" / "02_waypoint_01.wav",
        assets / "subtitles" / "02_waypoint_01.srt",
    ]
    for path in own + generated:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    stages = []
    monkeypatch.setattr(cli_helpers, "_apply_pipeline_settings", lambda _path: {})
    monkeypatch.setattr(pipeline_helpers, "skip_rich_media", lambda _s: True)
    monkeypatch.setattr(pipeline_helpers, "attraction_videos_enabled", lambda _s: False)
    monkeypatch.setattr(combine_commands._tracker, "stage", lambda name, total=None: stages.append(total))
    for name in ("test_overview_video", "test_residential_video"):
        monkeypatch.setattr(combine_commands, name, lambda *a, **k: {"video_paths": []})
    for name in ("test_intro_video", "test_outro_video"):
        monkeypatch.setattr(combine_commands, name, lambda *a, **k: {})
    monkeypatch.setattr(combine_commands, "test_video_concat", lambda *a, **k: {})

    combine_commands.test_all(str(tmp_path / "job_config.json"), force=True)

    assert all(p.exists() for p in own)
    assert not any(p.exists() for p in generated)
    assert stages[0] == len(stages)  # the [n/N] counter ends on N
