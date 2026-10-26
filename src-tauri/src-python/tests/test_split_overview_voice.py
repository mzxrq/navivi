"""The overview narration's opening (before {start}) voiced as its own file, played on the intro."""

import json
from pathlib import Path

import pytest

from services import tuning
from services.vdoprocessing.videopipeline import timeline_step
from services.vdoprocessing.videopipeline.audio_step import overview_pieces
from services.vdoprocessing.videopipeline.intro_step import intro_voice_seconds
from services.vdoprocessing.videopipeline.timeline_step import build_timeline

SCRIPT = "神話の道へ。{scene}古い社を巡る。{start}これが全体のルートです。{1}最初の場所。"


def test_opening_is_split_off_at_start():
    opening, rest = overview_pieces({"overview_narration": SCRIPT}, None)
    assert opening == "神話の道へ。{scene}古い社を巡る。"
    assert rest == "{start}これが全体のルートです。{1}最初の場所。"


@pytest.mark.parametrize("config", [
    {"overview_narration": SCRIPT, "enable_intro": False},
    {"overview_narration": SCRIPT, "settings": {"overview_voice_over_intro": False}},
    {"overview_narration": "{start}これが全体のルートです。"},
    {"overview_narration": "開始タグのない台本。"},
])
def test_one_file_when_there_is_no_intro_voice(config):
    assert overview_pieces(config, None) == (None, config["overview_narration"])


def test_intro_lasts_the_opening_voice_in_whole_frames():
    assert intro_voice_seconds(10.0) == pytest.approx(round((0.5 + 10.0 + 0.4) * 30) / 30)
    assert intro_voice_seconds(1.0) == tuning.INTRO_MIN_SECONDS


def _touch(p: Path) -> str:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    return str(p)


def test_each_voice_plays_on_its_own_clip(tmp_path, monkeypatch):
    lengths = {tuning.INTRO_OUTPUT_FILENAME: 9.0, "01_overview.mp4": 70.0, "00_intro_narration.wav": 8.1,
               "00_overview_narration.wav": 60.0}
    monkeypatch.setattr(timeline_step, "_duration", lambda p: lengths.get(Path(p).name, 0.0) if p else 0.0)
    (tmp_path / "job_config.json").write_text(json.dumps({"waypoints": []}), encoding="utf-8")
    route = tmp_path / "assets/video/route"
    intro, overview = _touch(route / tuning.INTRO_OUTPUT_FILENAME), _touch(route / "01_overview.mp4")
    audio = tmp_path / "assets/audio"
    intro_wav, overview_wav = _touch(audio / "00_intro_narration.wav"), _touch(audio / "00_overview_narration.wav")

    path = build_timeline(
        video_paths=[intro, overview], attraction_videos=[], final_videos=[intro, overview],
        project_dir=str(tmp_path), overview_audio_path=overview_wav,
        intro_audio_path=intro_wav, overview_audio_offset=tuning.INTRO_MAP_LEAD_SECONDS,
    )
    first, second = json.loads(Path(path).read_text(encoding="utf-8"))["video_tracks"]
    assert first["audio_path"].endswith("00_intro_narration.wav") and first["audio_offset"] == tuning.INTRO_VOICE_LEAD_SECONDS
    assert second["audio_path"].endswith("00_overview_narration.wav")
    assert second["audio_offset"] == tuning.INTRO_MAP_LEAD_SECONDS and "audio_start" not in second
