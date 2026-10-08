"""The course-guide overview script (settings.overview_style "course")."""

from services.localization.cues import clean_text, cue_tags
from services.localization.overview_cues import auto_tag_overview
from services.localization.overview_script import (
    ROUTE_PIVOT_TEXT,
    build_tour_script,
    plan_budget,
    spoken_area,
    stopby_text,
    totals_text,
)
from services.localization.route_brief import build_brief


def _line(lat0, lng0, lat1, lng1, n):
    return [[lat0 + (lat1 - lat0) * i / n, lng0 + (lng1 - lng0) * i / n] for i in range(n + 1)]


def _key(a, b, mode):
    return f"{a['lat']:.5f},{a['lng']:.5f}|{b['lat']:.5f},{b['lng']:.5f}|{mode}|"


def _wp(label, lat, lng, mode="walking", **extra):
    return {"label": label, "lat": lat, "lng": lng, "routeMode": mode, **extra}


def _island_course():
    """Station -> port, a ferry over, four stops on the island, a ferry back, the station."""
    # routeMode is the mode of the leg leaving a waypoint
    station = _wp("加太駅", 35.0, 139.0)
    port = _wp("加太港", 35.0, 139.01, mode="ferry")
    pier = _wp("野奈浦桟橋", 35.0, 139.05)
    stops = [_wp(name, 35.0, 139.05 + 0.004 * k) for k, name in enumerate(["砲台跡", "タカノス山", "南垂水広場", "第四砲台跡"], 1)]
    pier_back = _wp("野奈浦桟橋", 35.0, 139.051, mode="ferry")
    back_port = _wp("加太の港", 35.0, 139.011)
    end = _wp("加太駅 (Return)", 35.0, 139.0001)
    extra = _wp("閼伽井跡", 35.003, 139.06, isStopBy=True,
                attractionNarration="第一経塚がある場所です。訪れるには管理事務所で同意書を受け取る必要があります。")
    waypoints = [station, port, pier, *stops, extra, pier_back, back_port, end]
    route = [w for w in waypoints if not w.get("isStopBy")]
    cache = {_key(a, b, "walking"): _line(a["lat"], a["lng"], b["lat"], b["lng"], 40)
             for a, b in zip(route, route[1:]) if a["routeMode"] == "walking"}
    return {"waypoints": waypoints, "settings": {"overview_style": "course"}}, cache


def test_the_script_follows_the_course_guide_shape():
    script, report = build_tour_script(*_island_course())
    spoken = clean_text(script)
    tags = cue_tags(script)
    assert tags[0] == "start" and "end" in tags
    assert script.index("{start}") < script.index(ROUTE_PIVOT_TEXT) < script.index("{1}")
    assert "加太駅から" in spoken and "フェリーに乗り" in spoken and "そして再びフェリーで海を渡り" in spoken
    assert "砲台跡やタカノス山をめぐり、南垂水広場から第四砲台跡へ。" in spoken
    assert "フェリーは往復2回の乗船です。" in spoken
    assert "コースのゴールは、出発地と同じ加太駅です。" in spoken
    assert "こんにちは" not in spoken and "ようこそ" not in spoken
    # grouped island stops: the walker stops at the end of the sentence, not at each name
    numbered = [t for t in tags if t.isdigit()]
    assert len(numbered) < 7
    assert {r["used"] for r in report} == {"template"}


def test_the_stop_bys_get_their_own_paragraph_with_their_cautions():
    project, _ = _island_course()
    text = stopby_text(project)
    assert text.startswith("黒色で示した地点は、ルート沿いにある追加の見どころです。")
    assert "閼伽井跡" in text and "時間に余裕があれば" in text
    assert "ただし、訪れるには管理事務所で同意書を受け取る必要があります。" in text
    script, _ = build_tour_script(*_island_course())
    assert script.index("{end}") < script.index("黒色で示した地点")


def test_totals_count_the_walk_and_each_crossing():
    brief = build_brief(*_island_course())
    assert totals_text(brief).startswith("徒歩は合計およそ")


def test_the_course_introduction_opens_the_script_verbatim():
    project, cache = _island_course()
    project["settings"]["overview_intro"] = "紀伊水道に浮かぶ無人島・友ヶ島です。{1}このコースは、最初の一歩です。"
    script, report = build_tour_script(project, cache)
    assert script.startswith("紀伊水道に浮かぶ無人島・友ヶ島です。このコースは、最初の一歩です。{start}")
    assert report[0]["used"] == "user"


def test_a_model_opening_is_checked():
    project, cache = _island_course()
    for bad in ("皆さん、こんにちは！加太駅から旅に出ます。", "加太駅は300年の歴史がある駅です。"):
        _, report = build_tour_script(project, cache, generate=lambda p, n, bad=bad: bad if "冒頭" in p else None)
        assert report[0]["used"] == "template"
    good = "加太駅は海辺の町の玄関口です。島の砲台跡を巡ります。このコースは、島をめぐる旅です。"
    script, report = build_tour_script(project, cache, generate=lambda p, n: good if "冒頭" in p else None)
    assert report[0]["used"] == "model" and script.startswith(good)


def test_a_city_named_after_its_prefecture_is_said_once():
    assert spoken_area("和歌山・和歌山市") == "和歌山市"
    assert spoken_area("兵庫・神戸市") == "兵庫・神戸市"
    assert spoken_area("") == ""
    project, cache = _island_course()
    project["settings"]["intro_location"] = "和歌山・和歌山市"
    spoken = clean_text(build_tour_script(project, cache)[0])
    assert "和歌山市" in spoken and "和歌山・" not in spoken
    project["settings"]["overview_style"] = "walk"
    assert "和歌山・" not in clean_text(build_tour_script(project, cache)[0])


def test_the_opening_takes_the_time_left_over():
    project, cache = _island_course()
    budget = plan_budget(project, build_brief(project, cache))
    assert 8.0 <= budget["intro"] <= 24.0
    assert "pivot" in budget


def test_a_hand_written_script_gets_start_before_the_pivot_line():
    text = ("友ヶ島は四つの島からなっています。このコースは、最初の一歩です。これが全体のルートです。"
            "加太駅から港へと向かいます。港からはフェリーに乗り、野奈浦桟橋へ渡ります。")
    tagged = auto_tag_overview(text, ["加太港", "野奈浦桟橋"])
    assert "最初の一歩です。{start}これが全体のルートです。" in tagged
    assert clean_text(tagged) == text


def test_the_users_example_gets_route_and_extras_tags():
    text = ("友ヶ島は四つの島からなっています。これが全体のルートです。加太駅から加太の町を抜けて、港へと向かいます。"
            "島では、砲台跡やタカノス山をめぐり、南垂水広場から第四砲台跡へ。コースのゴールは、出発地と同じ加太駅です。"
            "茶色で示した地点は、ルート沿いにある追加の見どころです。砲台跡の近くの閼伽井跡です。")
    tagged = auto_tag_overview(text, ["砲台跡", "タカノス山"])
    assert "{start}これが全体のルートです。{route}加太駅から" in tagged
    assert "{extras}茶色で示した地点は" in tagged
    assert tagged.index("{1}") < tagged.index("{extras}")  # the extras' 砲台跡 is not the stop
    assert clean_text(tagged) == text
