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


def test_attraction_of_an_unconnected_stopby_is_not_used(tmp_path):
    (tmp_path / "job_config.json").write_text(json.dumps({"waypoints": [
        {"id": "a"}, {"id": "b", "isStopBy": True}, {"id": "c", "isStopBy": True, "connectToRoute": True}, {"id": "d"},
    ]}), encoding="utf-8")
    route = tmp_path / "assets/video/route"
    attr = tmp_path / "assets/video/attraction"
    leg = _touch(route / "02_waypoint_01_d.mp4")
    (route / "02_waypoint_01_pieces.json").write_text(
        json.dumps({"pieces": [{"file": "02_waypoint_01_d.mp4", "target_waypoint_id": "d"}]}), encoding="utf-8")
    attractions = [_touch(attr / f"04_attraction_{i:02d}_x.mp4") for i in range(4)]
    path = build_timeline(video_paths=[leg], attraction_videos=attractions, final_videos=[leg] + attractions,
                          project_dir=str(tmp_path))
    names = [n for n, _ in _order(path)]
    assert "04_attraction_01_x.mp4" not in names  # b: stop-by not connected to the route
    assert "04_attraction_02_x.mp4" in names  # c: connected, still used
