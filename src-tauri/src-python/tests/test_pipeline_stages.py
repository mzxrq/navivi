"""run_full_pipeline announces exactly PIPELINE_STAGES stages on every path.

The frontend's progress bar and stage list read the "[n/N]" counter, so a
path that calls tracker.stage() more (or fewer) times than it declares
shows up as "[9/8]" or a bar that never reaches the end.
"""

import json
from unittest.mock import MagicMock

import pytest

from services.vdoprocessing.videopipeline import pipeline


@pytest.fixture
def stubbed_pipeline(monkeypatch):
    """Stubs every step so only the stage bookkeeping runs."""
    class Stages(list):
        pass

    stages = Stages()

    def record_stage(name, total=None):
        stages.append((name, total))

    monkeypatch.setattr(pipeline.tracker, "stage", record_stage)
    monkeypatch.setattr(pipeline.tracker, "show", lambda *a, **k: None)
    monkeypatch.setattr(pipeline.tracker, "clear", lambda *a, **k: None)
    monkeypatch.setattr(pipeline.time, "sleep", lambda *_: None)
    monkeypatch.setattr(pipeline.tuning, "ensure_free_ram", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "sweep_stale_temp_files", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "process_gps", lambda *_: {"summary": {}})
    monkeypatch.setattr(pipeline, "set_route_only_legs", lambda *_: None)
    monkeypatch.setattr(pipeline, "add_default_cues", lambda *_: 0)
    monkeypatch.setattr(pipeline, "add_overview_cues", lambda *_: False)
    monkeypatch.setattr(pipeline, "generate_audio", lambda *a, **k: {})
    monkeypatch.setattr(pipeline, "record_cue_times", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "stop_tts_server", lambda: None)
    monkeypatch.setattr(pipeline, "apply_cued_scripts", lambda *a, **k: 0)
    monkeypatch.setattr(pipeline, "build_subtitles", lambda *a, **k: [])
    monkeypatch.setattr(pipeline, "build_overview_subtitle", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "build_attraction_subtitles", lambda *a, **k: [])
    upscale_calls = []
    monkeypatch.setattr(pipeline, "upscale_waypoint_images", lambda *a, **k: upscale_calls.append(a))
    stages.upscale_calls = upscale_calls
    monkeypatch.setattr(pipeline, "render_attraction_videos", lambda *a, **k: [])
    monkeypatch.setattr(pipeline, "render_route_video", lambda *a, **k: [])
    monkeypatch.setattr(
        pipeline, "compute_leg_narration_splits", lambda videos, *a, **k: (videos, {})
    )
    monkeypatch.setattr(pipeline, "render_intro_clip", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "render_outro_clip", lambda *_: None)
    monkeypatch.setattr(pipeline, "build_timeline", lambda *a, **k: "timeline.json")

    from services.vdoprocessing import comfyui_i2v_client

    monkeypatch.setattr(comfyui_i2v_client, "ComfyUII2VClient", MagicMock())
    return stages


@pytest.mark.parametrize(
    "settings",
    [
        {},
        {"enable_attraction_videos": False},
        {"skip_rich_media": True},
    ],
    ids=["default", "no-attractions", "skip-rich-media"],
)
def test_every_path_announces_exactly_the_declared_stages(tmp_path, stubbed_pipeline, settings):
    (tmp_path / "job_config.json").write_text(
        json.dumps({"directory_path": str(tmp_path), "waypoints": [], "settings": settings}),
        encoding="utf-8",
    )
    (tmp_path / "raw_track.gpx").write_text("", encoding="utf-8")

    pipeline.run_full_pipeline(str(tmp_path / "raw_track.gpx"))

    assert len(stubbed_pipeline) == pipeline.PIPELINE_STAGES
    assert stubbed_pipeline[0][1] == pipeline.PIPELINE_STAGES


@pytest.mark.parametrize(
    "settings, runs",
    [({}, True), ({"skip_rich_media": True}, False), ({"upscale_popup_images": False}, False)],
    ids=["default", "skip-rich-media", "upscale-off"],
)
def test_photo_upscale_stage_respects_settings(tmp_path, stubbed_pipeline, settings, runs):
    (tmp_path / "job_config.json").write_text(
        json.dumps({"directory_path": str(tmp_path), "waypoints": [], "settings": settings}),
        encoding="utf-8",
    )
    (tmp_path / "raw_track.gpx").write_text("", encoding="utf-8")

    pipeline.run_full_pipeline(str(tmp_path / "raw_track.gpx"))

    assert bool(stubbed_pipeline.upscale_calls) is runs
    names = [name for name, _ in stubbed_pipeline]
    assert names[3] == ("Upscaling waypoint photos..." if runs else "Skipping photo upscale...")
