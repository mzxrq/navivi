"""build_timeline puts each leg's destination attraction video right after the leg."""

import json
from pathlib import Path

from services.vdoprocessing.videopipeline.timeline_step import build_timeline


def _touch(p: Path) -> str:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    return str(p)


def _order(timeline_path):
    tracks = json.loads(Path(timeline_path).read_text(encoding="utf-8"))["video_tracks"]
    return [(Path(t["file_path"]).name, t.get("fade_into_next_seconds")) for t in tracks]


def test_attraction_follows_the_leg_that_arrives_at_it(tmp_path):
    ids = ["a", "b", "c", "d"]
    (tmp_path / "job_config.json").write_text(
        json.dumps({"waypoints": [{"id": i} for i in ids]}), encoding="utf-8"
    )
    route = tmp_path / "assets/video/route"
    attr = tmp_path / "assets/video/attraction"
    overview = _touch(route / "01_overview.mp4")
    # leg 1: a -> b (plain). leg 2: b -> d, merged over stop-by c (no piece of its own).
    leg1 = _touch(route / "02_waypoint_01_b.mp4")
    leg2 = _touch(route / "02_waypoint_02_d.mp4")
    (route / "02_waypoint_01_pieces.json").write_text(
        json.dumps({"pieces": [{"file": "02_waypoint_01_b.mp4", "target_waypoint_id": "b"}]}), encoding="utf-8")
    (route / "02_waypoint_02_pieces.json").write_text(
        json.dumps({"pieces": [{"file": "02_waypoint_02_d.mp4", "target_waypoint_id": "d"}]}), encoding="utf-8")
    attractions = [_touch(attr / f"04_attraction_{i:02d}_x.mp4") for i in range(4)]

    videos = [overview, leg1, leg2]
    path = build_timeline(
        video_paths=videos, attraction_videos=attractions, final_videos=videos + attractions,
        project_dir=str(tmp_path), attraction_fade_seconds=0.8,
    )
    names = [n for n, _ in _order(path)]
    assert names == [
        "01_overview.mp4",
        "04_attraction_00_x.mp4",  # nobody arrives at the first waypoint
        "02_waypoint_01_b.mp4", "04_attraction_01_x.mp4",  # leg -> its own attraction
        "04_attraction_02_x.mp4",  # merged stop-by c, passed on the way
        "02_waypoint_02_d.mp4", "04_attraction_03_x.mp4",  # leg -> destination d
    ]
    fades = dict(_order(path))
    assert fades["02_waypoint_01_b.mp4"] == 0.8 and fades["02_waypoint_02_d.mp4"] == 0.8
    assert fades["01_overview.mp4"] is None and fades["04_attraction_00_x.mp4"] is None


def test_a_leg_cut_by_a_connected_stopby_gets_an_attraction_after_each_piece(tmp_path):
    ids = ["a", "b", "c", "d", "e"]
    (tmp_path / "job_config.json").write_text(
        json.dumps({"waypoints": [{"id": i} for i in ids]}), encoding="utf-8")
    route = tmp_path / "assets/video/route"
    attr = tmp_path / "assets/video/attraction"
    # one leg a -> e cut into three pieces: b (connected stop-by), d (connected), e; c is merged in.
    pieces = [("02_waypoint_01_e.mp4", "b"), ("02_waypoint_01_e_cont2.mp4", "d"), ("02_waypoint_01_e_cont3.mp4", "e")]
    videos = [_touch(route / f) for f, _ in pieces]
    (route / "02_waypoint_01_pieces.json").write_text(
        json.dumps({"pieces": [{"file": f, "target_waypoint_id": t} for f, t in pieces]}), encoding="utf-8")
    attractions = [_touch(attr / f"04_attraction_{i:02d}_x.mp4") for i in range(1, 5)]

    path = build_timeline(
        video_paths=videos, attraction_videos=attractions, final_videos=videos + attractions,
        project_dir=str(tmp_path), attraction_fade_seconds=0.8,
    )
    assert [n for n, _ in _order(path)] == [
        "04_attraction_02_x.mp4",  # c: passed on the way, before the leg
        "02_waypoint_01_e.mp4", "04_attraction_01_x.mp4",  # -> b
        "02_waypoint_01_e_cont2.mp4", "04_attraction_03_x.mp4",  # -> d
        "02_waypoint_01_e_cont3.mp4", "04_attraction_04_x.mp4",  # -> e
    ]
    assert all(f == 0.8 for n, f in _order(path) if n.startswith("02_"))


def _stopby_timeline(tmp_path, b_extra=None):
    (tmp_path / "job_config.json").write_text(json.dumps({"waypoints": [
        {"id": "a"}, {"id": "b", "isStopBy": True, **(b_extra or {})},
        {"id": "c", "isStopBy": True, "connectToRoute": True}, {"id": "d"},
    ]}), encoding="utf-8")
    route = tmp_path / "assets/video/route"
    attr = tmp_path / "assets/video/attraction"
    leg = _touch(route / "02_waypoint_01_d.mp4")
    (route / "02_waypoint_01_pieces.json").write_text(
        json.dumps({"pieces": [{"file": "02_waypoint_01_d.mp4", "target_waypoint_id": "d"}]}), encoding="utf-8")
    attractions = [_touch(attr / f"04_attraction_{i:02d}_x.mp4") for i in range(4)]
    path = build_timeline(video_paths=[leg], attraction_videos=attractions, final_videos=[leg] + attractions,
                          project_dir=str(tmp_path))
    return [n for n, _ in _order(path)]


def test_attraction_of_an_unconnected_stopby_is_not_used(tmp_path):
    names = _stopby_timeline(tmp_path)
    assert "04_attraction_01_x.mp4" not in names  # b: stop-by not connected to the route
    assert "04_attraction_02_x.mp4" in names  # c: connected, still used


def test_the_course_style_uses_every_stopby_with_a_photo(tmp_path):
    from services.vdoprocessing.stopby_visits import set_visit_all_stopbys

    set_visit_all_stopbys(True)
    try:
        names = _stopby_timeline(tmp_path, {"popup_image": ["b.jpg"]})
    finally:
        set_visit_all_stopbys(False)
    assert "04_attraction_01_x.mp4" in names


def test_subtitles_are_written_into_the_timeline_to_burn_at_export(tmp_path, monkeypatch):
    from services.vdoprocessing.videopipeline import timeline_step

    lengths = {"02_waypoint_01_b.mp4": 10.0, "leg1.wav": 4.0, "04_attraction_01_x.mp4": 6.0}
    monkeypatch.setattr(timeline_step, "_duration", lambda p: lengths.get(Path(p).name, 0.0) if p else 0.0)
    monkeypatch.setattr(timeline_step, "read_audio_offset", lambda p: 2.0)
    (tmp_path / "job_config.json").write_text(json.dumps({"waypoints": [{"id": "a"}, {"id": "b"}]}), encoding="utf-8")
    route = tmp_path / "assets/video/route"
    leg = _touch(route / "02_waypoint_01_b.mp4")
    (route / "02_waypoint_01_pieces.json").write_text(
        json.dumps({"pieces": [{"file": "02_waypoint_01_b.mp4", "target_waypoint_id": "b"}]}), encoding="utf-8")
    attraction = _touch(tmp_path / "assets/video/attraction/04_attraction_01_x.mp4")
    srt = tmp_path / "leg1.srt"
    srt.write_text("1\n00:00:00,500 --> 00:00:01,500\nhello\n\n2\n00:00:02,000 --> 00:00:03,250\nthere\n", encoding="utf-8")
    attr_srt = tmp_path / "attr.srt"
    attr_srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nlook\n", encoding="utf-8")

    path = build_timeline(
        video_paths=[leg], attraction_videos=[attraction], final_videos=[leg, attraction],
        audio_paths=[_touch(tmp_path / "leg1.wav")], subtitle_paths=[str(srt)], project_dir=str(tmp_path),
        attraction_audio_paths=[None, _touch(tmp_path / "attr.wav")], attraction_subtitle_paths=[None, str(attr_srt)],
    )
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert data["burn_subtitles"] is True
    assert data["video_tracks"][0]["subtitles"] == [
        {"start": 2.5, "end": 3.5, "text": "hello"}, {"start": 4.0, "end": 5.25, "text": "there"}]
    # attraction starts after the 10s leg; attraction narration has no offset
    assert data["subtitles"][-1] == {"start": 11.0, "end": 12.0, "text": "look"}
    assert data["total_duration_seconds"] == 16.0
