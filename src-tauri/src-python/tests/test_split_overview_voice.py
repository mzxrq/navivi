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


from services.vdoprocessing.videopipeline.intro_step import place_overview_voice  # noqa: E402

OVERVIEW = {"overview_audio_path": "o.wav", "overview_audio_duration": 60.0,
            "overview_cue_times": {"start": 0.2, "1": 10.0}}


def test_split_voice_never_moves_the_overview():
    intro = {"audio_path": "i.wav", "duration_seconds": 8.0, "cue_times": {"scene2": 3.0}}
    seen = {}
    placed = place_overview_voice({}, {**OVERVIEW, "intro_voice": intro}, True,
                                  lambda sec, cues: seen.update(sec=sec, cues=cues) or "00_intro.mp4")
    assert seen == {"sec": intro_voice_seconds(8.0), "cues": {"scene2": 3.0}}
    lead = tuning.INTRO_MAP_LEAD_SECONDS
    assert placed["overview_cues"] == {"start": 0.2 + lead, "1": 10.0 + lead}
    assert placed["overview_audio"] == 60.0 + lead and placed["voice_start"] is None


def test_no_intro_clip_plays_the_opening_first_on_the_overview():
    intro = {"audio_path": "i.wav", "duration_seconds": 8.0, "cue_times": {}}
    placed = place_overview_voice({}, {**OVERVIEW, "intro_voice": intro}, True, lambda sec, cues: None)
    lead = 8.0 + tuning.INTRO_MAP_LEAD_SECONDS
    assert placed["overview_lead"] == lead and placed["overview_cues"]["1"] == 10.0 + lead


def test_one_old_file_shifts_the_overview_back_by_the_intro(monkeypatch):
    from services.tts.ttsengine import FFmpegManager

    monkeypatch.setattr(FFmpegManager, "get_media_duration", classmethod(lambda cls, p: 9.3))
    data = {**OVERVIEW, "overview_cue_times": {"scene2": 4.0, "start": 10.0, "1": 20.0}}
    placed = place_overview_voice({}, data, True, lambda sec, cues: "00_intro.mp4")
    assert placed["voice_start"] == tuning.INTRO_VOICE_LEAD_SECONDS
    shift = 9.3 - tuning.INTRO_VOICE_LEAD_SECONDS
    assert placed["overview_cues"] == {"start": pytest.approx(10.0 - shift), "1": pytest.approx(20.0 - shift)}
    assert placed["overview_audio"] == pytest.approx(60.0 - shift)
    # The voice-over setting off: nothing is shifted (this path once crashed).
    placed = place_overview_voice({"overview_voice_over_intro": False}, data, True, lambda sec, cues: "00_intro.mp4")
    assert placed["overview_cues"]["1"] == 20.0 and placed["overview_audio"] == 60.0


def test_auto_scene_cues_are_stored_once(tmp_path):
    from services.vdoprocessing.videopipeline.audio_step import overview_tagged_script
    from services.vdoprocessing.videopipeline.narration_step import add_overview_cues

    config = tmp_path / "job_config.json"
    project = {
        "waypoints": [], "overview_narration": "神話の道へ。古い社を巡る。昔に戻る。この旅を楽しもう。{start}これが全体のルートです。",
        "overview_narration_is_auto": False, "settings": {"intro_style": "documentary"},
    }
    config.write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
    assert add_overview_cues(str(config)) is True
    assert add_overview_cues(str(config)) is False
    tagged = overview_tagged_script(json.loads(config.read_text(encoding="utf-8")), tmp_path)
    assert tagged.count("{scene}") == 2 and tagged.index("{scene}") < tagged.index("{start}")


def test_old_single_recording_is_read_as_one_file(tmp_path, monkeypatch):
    from services.vdoprocessing.videopipeline import audio_step

    config = tmp_path / "job_config.json"
    config.write_text(json.dumps({"waypoints": [], "overview_narration": SCRIPT}, ensure_ascii=False), encoding="utf-8")
    audio = tmp_path / "assets/audio"
    _touch(audio / "00_overview_narration.wav")
    monkeypatch.setattr(audio_step, "output_is_valid", lambda p: Path(p).exists())
    monkeypatch.setattr("services.tts.ttsengine.AudioProcessor.analyze_pauses",
                        lambda self, p: {"duration_seconds": 30.0, "pauses": []})
    data = audio_step.existing_audio_data(str(config))
    assert data.get("intro_voice") is None and "start" in data["overview_cue_times"]
    assert data["overview_cue_times"]["start"] > 0  # measured in the whole old recording
