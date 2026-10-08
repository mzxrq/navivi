"""Turn-by-turn leg scripts for the course style (services/localization/leg_script.py)."""

import json
import math

from services.cli.script_commands import leg_scripts
from services.localization.leg_script import build_leg_scripts, leg_turns, walking_directions

LAT0, LNG0 = 35.0, 139.0
M_LAT = 1 / 110540.0
M_LNG = 1 / (111320.0 * math.cos(math.radians(LAT0)))


def _at(east_m, north_m):
    return [LAT0 + north_m * M_LAT, LNG0 + east_m * M_LNG]


def _path(*corners, step=10.0, wobble=0.0):
    """Points every `step` metres through (east, north) corners, optionally wobbling sideways."""
    out = []
    for (x0, y0), (x1, y1) in zip(corners, corners[1:]):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
        for i in range(n):
            w = wobble * (1 if (len(out) % 2) else -1)
            out.append(_at(x0 + (x1 - x0) * i / n + w, y0 + (y1 - y0) * i / n + w))
    out.append(_at(*corners[-1]))
    return out


def _wp(label, point, **extra):
    return {"id": label, "label": label, "lat": point[0], "lng": point[1], "routeMode": "walking", **extra}


def _key(a, b, mode="walking"):
    return f"{a['lat']:.5f},{a['lng']:.5f}|{b['lat']:.5f},{b['lng']:.5f}|{mode}|"


def test_a_corner_is_read_as_a_turn_with_its_new_heading():
    plan = leg_turns(_path((0, 0), (400, 0), (400, 100)))
    assert plan["heading"] == "東"
    assert len(plan["turns"]) == 1
    turn = plan["turns"][0]
    assert turn["angle"] < -60 and turn["heading"] == "北"  # left, then north


def test_a_wobbly_straight_road_has_no_turns():
    assert leg_turns(_path((0, 0), (0, 600), wobble=3.0))["turns"] == []


def test_directions_read_like_the_reference():
    text = walking_directions("加太駅", "称念寺", _path((0, 0), (400, 0), (400, -100)))
    assert text == "加太駅から東へ進みます。そのまま道なりに進みます。右に曲がって南へ入ると、称念寺が見えてきます。"
    zigzag = walking_directions("A", "B", _path((0, 0), (200, 0), (200, 40), (400, 40), (400, 400)))
    assert "すぐに" in zigzag and "やがて、Bが見えてきます。" in zigzag


def test_a_winding_leg_is_capped():
    corners = [(i * 60.0, 60.0 * (i % 2)) for i in range(30)]
    assert len(leg_turns(_path(*corners))["turns"]) <= 8


def _project():
    a = _wp("加太駅", _at(0, 0))
    b = _wp("称念寺", _at(400, -100), isStopBy=True, connectToRoute=True,
            attractionNarration="称念寺は、小さなお寺です。")
    c = _wp("加太港", _at(800, -100), routeMode="ferry", attractionNarration="フェリーが出る港です。")
    d = _wp("野奈浦桟橋", _at(5000, -100), attractionNarration="島の玄関口です。")
    seen = _wp("常行寺", _at(200, 50), isStopBy=True)
    cache = {
        _key(a, b): _path((0, 0), (400, 0), (400, -100)),
        _key(b, c): _path((400, -100), (800, -100)),
    }
    return {"waypoints": [a, seen, b, c, d], "settings": {"overview_style": "course"}}, cache


def test_every_stop_gets_its_directions_and_opening():
    rows = {r["id"]: r for r in build_leg_scripts(*_project())}
    assert rows["加太駅"]["arriving"] is None
    assert rows["加太駅"]["attraction"] == "ここは加太駅。このコースの出発点です。"
    assert rows["称念寺"]["arriving"].startswith("加太駅から東へ進みます。")
    assert rows["称念寺"]["attraction"] == "時間に余裕があれば立ち寄れる地点、称念寺です。小さなお寺です。"
    assert rows["加太港"]["attraction"] == "加太港です。フェリーが出る港です。"
    assert rows["野奈浦桟橋"]["arriving"] == "加太港からフェリーに乗り、野奈浦桟橋へ渡ります。船はまもなく野奈浦桟橋に到着します。"
    assert rows["野奈浦桟橋"]["attraction"].startswith("ゴールの野奈浦桟橋に到着しました。")
    # an unconnected stop-by is told from the previous stop to where the leg passes it
    assert rows["常行寺"]["arriving"] == "加太駅から東へ、道なりに進むと、常行寺はすぐ先です。"
    assert rows["常行寺"]["attraction"] == "時間に余裕があれば立ち寄れる地点、常行寺です。"


def test_the_next_stop_continues_from_a_stopby_the_walk_pauses_at():
    project, cache = _project()
    project["waypoints"][1]["popup_image"] = "assets/image/jogyoji.jpg"
    rows = {r["id"]: r for r in build_leg_scripts(project, cache)}
    assert rows["常行寺"]["arriving"] == "加太駅から東へ、道なりに進むと、常行寺はすぐ先です。"
    assert rows["称念寺"]["arriving"] == "常行寺から東へ進みます。右に曲がって南へ入ると、称念寺はすぐ先です。"
    project["settings"]["overview_style"] = "walk"  # the walk style only passes it
    rows = {r["id"]: r for r in build_leg_scripts(project, cache)}
    assert rows["称念寺"]["arriving"].startswith("加太駅から東へ進みます。")


def test_openings_are_added_once():
    project, cache = _project()
    for row in build_leg_scripts(project, cache):
        wp = next(w for w in project["waypoints"] if w["id"] == row["id"])
        if row["attraction"]:
            wp["attractionNarration"] = row["attraction"]
    assert all(r["attraction"] is None for r in build_leg_scripts(project, cache))


def test_the_command_returns_the_scripts_and_writes_nothing(tmp_path):
    project, cache = _project()
    cfg = tmp_path / "job_config.json"
    cfg.write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
    (tmp_path / ".navivi").mkdir()
    (tmp_path / ".navivi" / "routecache.json").write_text(json.dumps(cache), encoding="utf-8")
    before = cfg.read_text(encoding="utf-8")
    reply = leg_scripts(str(cfg))
    assert reply["success"] is True and len(reply["scripts"]) == 5
    assert cfg.read_text(encoding="utf-8") == before
