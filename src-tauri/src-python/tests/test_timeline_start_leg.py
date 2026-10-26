"""A separate start point's leg is file 02_waypoint_00_* and is placed like any other leg (fix.md #1)."""

import json
from pathlib import Path

from services.vdoprocessing.videopipeline import timeline_step
from services.vdoprocessing.videopipeline.timeline_step import build_timeline


def _touch(p: Path) -> str:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    return str(p)


def test_the_start_points_leg_comes_first_and_each_leg_is_followed_by_its_destination(tmp_path, monkeypatch):
    monkeypatch.setattr(timeline_step, "_duration", lambda p: 5.0 if p else 0.0)
    (tmp_path / "job_config.json").write_text(
        json.dumps({"waypoints": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}), encoding="utf-8")
    route = tmp_path / "assets/video/route"
    attraction = tmp_path / "assets/video/attraction"
    start_leg = _touch(route / "02_waypoint_00_A.mp4")
    leg_ab = _touch(route / "02_waypoint_01_B.mp4")
    for num, target in (("00", "a"), ("01", "b")):
        name = "02_waypoint_00_A.mp4" if num == "00" else "02_waypoint_01_B.mp4"
        (route / f"02_waypoint_{num}_pieces.json").write_text(
            json.dumps({"pieces": [{"file": name, "target_waypoint_id": target}]}), encoding="utf-8")
    att_a = _touch(attraction / "04_attraction_00_A.mp4")
    att_b = _touch(attraction / "04_attraction_01_B.mp4")

    path = build_timeline(
        video_paths=[start_leg, leg_ab], attraction_videos=[att_a, att_b],
        final_videos=[start_leg, leg_ab, att_a, att_b], project_dir=str(tmp_path),
    )
    order = [Path(t["file_path"]).name
             for t in json.loads(Path(path).read_text(encoding="utf-8"))["video_tracks"]]
    assert order == ["02_waypoint_00_A.mp4", "04_attraction_00_A.mp4", "02_waypoint_01_B.mp4", "04_attraction_01_B.mp4"]


def test_the_timeline_uses_the_waypoints_the_run_started_with(tmp_path, monkeypatch, use_run_list=True):
    monkeypatch.setattr(timeline_step, "_duration", lambda p: 5.0 if p else 0.0)
    started = [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}, {"id": "c", "label": "C"}]
    # Edited during the render: B and C swapped.
    (tmp_path / "job_config.json").write_text(
        json.dumps({"waypoints": [started[0], started[2], started[1]]}), encoding="utf-8")
    route = tmp_path / "assets/video/route"
    attraction = tmp_path / "assets/video/attraction"
    legs = []
    for num, name, target in (("01", "02_waypoint_01_B.mp4", "b"), ("02", "02_waypoint_02_C.mp4", "c")):
        legs.append(_touch(route / name))
        (route / f"02_waypoint_{num}_pieces.json").write_text(
            json.dumps({"pieces": [{"file": name, "target_waypoint_id": target}]}), encoding="utf-8")
    atts = [_touch(attraction / "04_attraction_01_B.mp4"), _touch(attraction / "04_attraction_02_C.mp4")]
    path = build_timeline(video_paths=legs, attraction_videos=atts, final_videos=legs + atts,
                          project_dir=str(tmp_path), waypoints=started if use_run_list else None)
    order = [Path(t["file_path"]).name for t in json.loads(Path(path).read_text(encoding="utf-8"))["video_tracks"]]
    assert order == ["02_waypoint_01_B.mp4", "04_attraction_01_B.mp4", "02_waypoint_02_C.mp4", "04_attraction_02_C.mp4"]


def test_a_render_with_scripts_but_no_voice_at_all_fails():
    import pytest

    from services.vdoprocessing.videopipeline.audio_step import require_some_voice

    stops = [{"label": "A", "arrivingNarration": "ようこそ"}]
    with pytest.raises(RuntimeError, match="No narration audio"):
        require_some_voice(stops, {"audio_paths": [None], "attraction_audio_paths": [None], "overview_audio_path": None})
    require_some_voice(stops, {"audio_paths": ["a.wav"], "attraction_audio_paths": [None]})  # one voice: fine
    require_some_voice([{"label": "B"}], {"audio_paths": [None]})  # no scripts: nothing to say
