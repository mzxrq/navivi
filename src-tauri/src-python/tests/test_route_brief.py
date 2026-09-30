"""Offline tests for the route brief (the facts an overview narrator tells).

Synthetic routes in different places: nothing here depends on a real project."""

from services.localization.route_brief import (
    build_brief,
    heading,
    split_crossings,
    transition_text,
)


def _line(lat0, lng0, lat1, lng1, n):
    """n + 1 points evenly along a straight line."""
    return [[lat0 + (lat1 - lat0) * i / n, lng0 + (lng1 - lng0) * i / n] for i in range(n + 1)]


def _key(a, b, mode):
    return f"{a['lat']:.5f},{a['lng']:.5f}|{b['lat']:.5f},{b['lng']:.5f}|{mode}|"


def _wp(label, lat, lng, mode="walking", **extra):
    return {"label": label, "lat": lat, "lng": lng, "routeMode": mode, **extra}


class TestHeading:
    def test_compass_points(self):
        assert heading(35.0, 139.0, 35.1, 139.0) == "北"
        assert heading(35.0, 139.0, 35.0, 139.1) == "東"
        assert heading(35.0, 139.0, 34.9, 138.9) == "南西"

    def test_southern_hemisphere(self):
        assert heading(-33.9, 151.2, -34.0, 151.2) == "南"


class TestCrossings:
    def test_a_dense_walk_is_one_piece(self):
        assert [p["mode"] for p in split_crossings(_line(35.0, 139.0, 35.0, 139.02, 80), "walking")] == ["walking"]

    def test_a_boat_hidden_in_a_walk_is_split_out(self):
        # 1 km of dense path, then a 3 km crossing in 300 m hops, then 1 km of path
        walk1 = _line(35.0, 139.0, 35.0, 139.011, 50)
        boat = _line(35.0, 139.011, 35.0, 139.044, 10)[1:]
        walk2 = _line(35.0, 139.044, 35.0, 139.055, 50)[1:]
        pieces = split_crossings(walk1 + boat + walk2, "walking")
        assert [p["mode"] for p in pieces] == ["walking", "ferry", "walking"]
        assert 2.5 < pieces[1]["km"] < 3.5

    def test_a_short_sparse_stretch_is_not_a_boat(self):
        # a straight road the router stored as 3 sparse points: not a crossing
        pts = _line(35.0, 139.0, 35.0, 139.005, 20) + _line(35.0, 139.005, 35.0, 139.03, 3)[1:]
        assert [p["mode"] for p in split_crossings(pts, "walking")] == ["walking"]

    def test_only_walks_are_split(self):
        pts = _line(35.0, 139.0, 35.0, 139.1, 20)
        assert [p["mode"] for p in split_crossings(pts, "driving")] == ["driving"]


def _project():
    a = _wp("中央駅", 35.000, 139.000)
    b = _wp("古い寺", 35.000, 139.010)                    # 1st visible stop
    seen = _wp("大きな橋", 35.0005, 139.015, isStopBy=True)  # beside leg b -> c
    c = _wp("川の渡し", 35.000, 139.020, mode="walking")  # 2nd, then a boat hides in the walk
    d = _wp("島の神社", 35.000, 139.060, mode="draw")      # 3rd, hand-drawn after it
    e = _wp("中央駅 (Return)", 35.000, 139.080)
    cache = {
        _key(a, b, "walking"): _line(35.0, 139.0, 35.0, 139.01, 40),
        _key(b, c, "walking"): _line(35.0, 139.01, 35.0, 139.02, 40),
        _key(c, d, "walking"): (
            _line(35.0, 139.02, 35.0, 139.025, 20)
            + _line(35.0, 139.025, 35.0, 139.055, 10)[1:]
            + _line(35.0, 139.055, 35.0, 139.06, 20)[1:]
        ),
        # a hand-drawn leg clicked every ~180 m: sparse, but not a boat
        _key(d, e, "draw"): _line(35.0, 139.06, 35.0, 139.08, 10),
    }
    return {"waypoints": [a, b, seen, c, d, e], "settings": {}}, cache


class TestBrief:
    def test_legs_follow_the_route(self):
        brief = build_brief(*_project())
        assert brief["start"] == "中央駅"
        assert [(l["from"], l["to"]) for l in brief["legs"]] == [
            ("中央駅", "古い寺"), ("古い寺", "川の渡し"), ("川の渡し", "島の神社"), ("島の神社", "中央駅"),
        ]
        assert [l["to_number"] for l in brief["legs"]] == [1, 2, 3, None]

    def test_minutes_come_from_the_mode_speeds(self):
        leg = build_brief(*_project())["legs"][0]
        assert 0.85 < leg["km"] < 0.95  # 0.01 deg of longitude at 35N
        assert leg["minutes"] == round(leg["km"] / 3.0 * 60)
        project, cache = _project()
        project["settings"]["mode_speeds_kmh"] = {"walking": 6.0}
        assert build_brief(project, cache)["legs"][0]["minutes"] == round(leg["km"] / 6.0 * 60)

    def test_a_stop_by_is_passed_on_the_nearest_leg(self):
        legs = build_brief(*_project())["legs"]
        assert [l["passes"] for l in legs] == [[], ["大きな橋"], [], []]

    def test_a_hidden_boat_and_a_drawn_leg(self):
        legs = build_brief(*_project())["legs"]
        assert [p["mode"] for p in legs[2]["pieces"]] == ["walking", "ferry", "walking"]
        assert [p["mode"] for p in legs[3]["pieces"]] == ["walking"]  # drawn: never split
        assert legs[3]["is_return"] and legs[3]["mode"] == "walking"

    def test_without_a_route_cache_legs_are_straight(self):
        project, _ = _project()
        leg = build_brief(project, {})["legs"][0]
        assert leg["heading"] == "東" and not leg["winding"]


class TestTransitionText:
    def _leg(self, **over):
        leg = {"from": "A", "to": "B", "mode": "walking", "km": 1.0, "minutes": 20, "heading": "北",
               "winding": False, "passes": [], "is_return": False}
        leg.update(over)
        return leg

    def test_walk(self):
        assert transition_text(self._leg()) == "次は北へ。20分ほど歩くと、Bです。"

    def test_winding_walk_passing_a_place(self):
        text = transition_text(self._leg(winding=True, passes=["C"]))
        assert text == "次は北へ。Cを眺めながら、曲がりくねった道を20分ほど歩くと、Bです。"

    def test_ferry_and_car(self):
        assert transition_text(self._leg(mode="ferry", minutes=15)) == "Aから船に乗り、15分ほどでBへ渡ります。"
        assert transition_text(self._leg(mode="driving", minutes=90)) == (
            "ここからは車で北へ。1時間30分ほど走って、Bへ向かいます。"
        )

    def test_walk_boat_walk_and_return(self):
        pieces = [{"mode": "walking", "minutes": 5}, {"mode": "ferry", "minutes": 10},
                  {"mode": "walking", "minutes": 8}]
        text = transition_text(self._leg(pieces=pieces, is_return=True))
        assert text == "最後は、5分ほど歩き、船で10分ほど渡り、8分ほど歩き、Bへ戻ります。"


# --- the tour-guide script built on the brief -------------------------------

from services.localization.cues import clean_text, cue_tags  # noqa: E402
from services.localization.overview_script import build_tour_script, check_transition  # noqa: E402
from services.localization.route_brief import journeys  # noqa: E402


def _tour_project():
    project, cache = _project()
    project["waypoints"][1]["attractionNarration"] = "古い寺は四百年の歴史があります。駅から歩いて5分です。"
    project["waypoints"][3]["attractionNarration"] = "川の渡しは昔からの船着き場です。"
    project["waypoints"][4]["attractionNarration"] = "島の神社は海の神を祀ります。"
    project.setdefault("settings", {})["overview_describe_stops"] = True  # these tests cover the per-stop descriptions
    return project, cache


class TestJourneys:
    def test_trips_run_between_numbered_stops(self):
        project, cache = _project()
        project["waypoints"].insert(1, _wp("小さな祠", 35.0, 139.005, isStopBy=True, connectToRoute=True, pauseAtWaypoint=False))
        cache[_key(project["waypoints"][0], project["waypoints"][1], "walking")] = _line(35.0, 139.0, 35.0, 139.005, 20)
        cache[_key(project["waypoints"][1], project["waypoints"][2], "walking")] = _line(35.0, 139.005, 35.0, 139.01, 20)
        trips = journeys(build_brief(project, cache))
        assert [(t["from"], t["to"], t["to_number"]) for t in trips][0] == ("中央駅", "古い寺", 1)
        assert trips[0]["via"] == ["小さな祠"]
        assert trips[-1]["to_number"] is None and trips[-1]["is_return"]


class TestCheckTransition:
    def _trip(self):
        return journeys(build_brief(*_project()))[2]  # 川の渡し -> 島の神社, walk/boat/walk

    def test_a_line_true_to_the_facts_passes(self):
        trip = self._trip()
        boat = trip["pieces"][1]["minutes"]
        assert check_transition(f"次は東へ。船で{boat}分ほど渡ると、島の神社に着きます。", trip)

    def test_a_wrong_direction_number_or_missing_boat_fails(self):
        trip = self._trip()
        boat = trip["pieces"][1]["minutes"]
        assert not check_transition(f"次は北へ。船で{boat}分ほど渡ると、島の神社に着きます。", trip)
        assert not check_transition("次は東へ。船で45分ほど渡ると、島の神社に着きます。", trip)
        assert not check_transition("次は東へ。のんびり歩くと、島の神社に着きます。", trip)
        assert not check_transition(f"次は東へ。船で{boat}分ほど渡ります。", trip)  # destination unnamed


class TestTourScript:
    def test_without_a_model_every_piece_comes_from_the_facts(self):
        script, report = build_tour_script(*_tour_project())
        assert cue_tags(script) == ["start", "1", "go1", "2", "go2", "3", "go3", "end", "distance"]
        assert {r["used"] for r in report} == {"template"}
        assert "{start}次は" not in script  # setting off: never "next"
        # the stop's own "5分" route claim is left to the way lines
        assert "古い寺は四百年の歴史があります。" in script and "駅から歩いて5分" not in script

    def test_model_text_is_used_only_when_it_checks_out(self):
        def fake(prompt, limit):
            if "道順を案内" in prompt:
                return "次は北へ、3時間歩きます。"  # wrong: rejected for the fact line
            if "■ 場所: 島の神社" in prompt:
                return "島の神社は、海を見守る小さな社です。"
            return None

        script, report = build_tour_script(*_tour_project(), generate=fake)
        used = {r["kind"]: r["used"] for r in report}
        assert used["stop3"] == "model" and used["stop1"] == "template"
        assert all(used[k] == "template" for k in used if k.startswith("way"))
        assert "{3}島の神社は、海を見守る小さな社です。{go}" in script

    def test_the_words_are_all_spoken_and_the_intro_can_be_given(self):
        script, _ = build_tour_script(*_tour_project(), intro_text="{1}ようこそ、川の町へ。")
        assert clean_text(script).startswith("ようこそ、川の町へ。")
        assert cue_tags(script)[0] == "start"

    def test_a_description_that_talks_about_moving_on_is_not_taken(self):
        def fake(prompt, limit):
            if "■ 場所: 古い寺" in prompt:
                return "さあ、次は古い寺へ。四百年の歴史がある寺です。"
            return None

        _, report = build_tour_script(*_tour_project(), generate=fake)
        assert {r["kind"]: r["used"] for r in report}["stop1"] == "template"

    def test_two_lines_in_a_row_never_open_the_same_way(self):
        def fake(prompt, limit):
            if "道順を案内" in prompt:
                return None
            if "オープニング" in prompt:
                return "さあ、ようこそ、川の町の旅へ。"
            return "さあ、古い寺は四百年続く古いお寺です。" if "■ 場所: 古い寺" in prompt else None

        project, cache = _tour_project()
        project["settings"]["overview_intro_chars"] = 30
        _, report = build_tour_script(project, cache, generate=fake, intro_text=None)
        kinds = [r["kind"] for r in report]
        assert report[kinds.index("intro")]["used"] == "model"
        # way0 (template, "まずは…") sits between, so stop1 may open with さあ again
        assert report[kinds.index("stop1")]["used"] == "model"
        texts = [r["text"] for r in report]
        assert all(a.split("、")[0] != b.split("、")[0] for a, b in zip(texts, texts[1:]))


class TestBudget:
    def test_the_target_follows_the_stops_within_60_to_120s(self):
        from services.localization.overview_script import overview_target_seconds

        assert overview_target_seconds({}, 3) == 60.0
        assert overview_target_seconds({}, 8) == 76.0
        assert overview_target_seconds({}, 20) == 120.0
        assert overview_target_seconds({"settings": {"overview_target_seconds": 45}}, 20) == 45.0

    def test_the_pieces_add_up_to_the_target(self):
        from services.localization.overview_script import plan_budget

        project, cache = _tour_project()
        budget = plan_budget(project, build_brief(project, cache))
        assert budget["target"] == 60.0 and budget["fits"]
        assert abs(budget["estimated"] - 60.0) < 0.5
        assert budget["closing"] > 8.0  # the ending can shrink only so far

    def test_the_ending_fits_the_closing_line(self):
        from services.vdoprocessing.spatial_renderer.overview_timing import fit_ending

        assert fit_ending(15.0, 8.0, 4.0, 2.0) == (5.0, 2.0)   # longer line: longer hold
        assert fit_ending(10.0, 8.0, 4.0, 2.0) == (1.0, 1.0)   # shorter: hold, then pause shrink
        assert fit_ending(4.0, 8.0, 4.0, 2.0) == (1.0, 0.5)    # never below the minimums


def _long_route(stops=10):
    """A straight walk east through `stops` numbered places, the Nth with N
    sentences of narration (so later places have more to say)."""
    wps = [_wp("起点", 35.0, 139.0)]
    for n in range(1, stops + 1):
        wps.append(_wp(f"場所{n}", 35.0, 139.0 + 0.004 * n,
                       attractionNarration="ここは古い町並みが残る場所です。" * n))
    wps.append(_wp("起点 (Return)", 35.0, 139.0 + 0.004 * (stops + 1)))
    return {"waypoints": wps, "settings": {"overview_describe_stops": True}}


class TestHighlights:
    def test_every_stop_gets_described_even_past_target(self):
        from services.localization.overview_script import plan_budget

        project = _long_route(10)
        budget = plan_budget(project, build_brief(project, {}))
        # Every numbered place is described - target no longer decides which
        # stops get a description, only how the shared time is spent (see
        # plan_budget's docstring); a route with more to say than the
        # 60-120s target simply runs long instead of dropping stops.
        assert set(budget["stops"]) == set(range(1, 11))
        assert all(n in budget["describe"] and budget["describe"][n] > 0 for n in range(1, 11))
        vias = [v for t in budget["trips"] for v in t["via"]]
        assert not vias  # nothing is merely passed - every place is a stop now

    def test_an_opted_out_stop_is_still_skipped(self):
        from services.localization.overview_script import plan_budget

        project = _long_route(3)
        project["waypoints"][2]["overviewHighlight"] = False  # 場所2
        budget = plan_budget(project, build_brief(project, {}))
        assert 2 not in budget["stops"]
        assert 1 in budget["stops"] and 3 in budget["stops"]

    def test_a_stop_hosting_stop_bys_always_stops_for_its_freeze(self):
        from services.localization.overview_script import plan_budget

        project = _long_route(10)
        project["waypoints"].insert(2, _wp("小さな碑", 35.0005, 139.0045, isStopBy=True))  # after 場所1
        budget = plan_budget(project, build_brief(project, {}))
        from services import tuning

        assert 1 in budget["stops"]
        # post-arrival + card + one stop-by
        assert budget["describe"][1] == 1.0 + 2.0 + tuning.STOPBY_BATCH_SECONDS

    def test_a_stopby_batch_gets_its_own_cue_wherever_it_is(self):
        # {goPreN} must not be special-cased to the very first leg - a batch
        # hosted anywhere along the route needs the same "hold until this
        # line is spoken" cue (see overview_script.py's via_batches loop).
        project = _long_route(10)
        # A connected host between stop 3 and stop 4, with one unconnected
        # stop-by riding behind it - mid-route, nowhere near the start.
        project["waypoints"].insert(4, _wp("中間の碑", 35.0, 139.0 + 0.004 * 3 + 0.002,
                                            isStopBy=True, connectToRoute=True, pauseAtWaypoint=False))
        project["waypoints"].insert(5, _wp("隠れ観音", 35.0, 139.0 + 0.004 * 3 + 0.0022,
                                            isStopBy=True, connectToRoute=False))
        script, _ = build_tour_script(project, {}, generate=None)
        assert "隠れ観音が見えてきます。{goPre4}" in script
        assert cue_tags(script).index("goPre4") == cue_tags(script).index("4") - 1

    def test_the_waypoint_flag_forces_or_skips_a_stop(self):
        from services.localization.overview_script import plan_budget

        project = _long_route(10)
        project["waypoints"][1]["overviewHighlight"] = True    # 場所1: least to say
        project["waypoints"][10]["overviewHighlight"] = False  # 場所10: most to say
        budget = plan_budget(project, build_brief(project, {}))
        assert 1 in budget["stops"] and 10 not in budget["stops"]

    def test_only_the_stops_stopped_at_get_cues(self):
        project = _long_route(10)
        script, _ = build_tour_script(project, {})
        from services.localization.overview_script import plan_budget

        stops = plan_budget(project, build_brief(project, {}))["stops"]
        numbered = [t for t in cue_tags(script) if t.isdigit()]
        assert numbered == [str(n) for n in stops]


class TestOverviewIsSeparateFromStopNarration:
    """With overview_describe_stops off, the overview tells only the
    journey: a stop's own narration (its leg / attraction clip's job) is
    never repeated in it. (Since tuning.DEFAULT_OVERVIEW_DESCRIBE_STOPS,
    this is now an explicit opt-out rather than the default.)"""

    def _project(self):
        project, cache = _tour_project()
        project["settings"]["overview_describe_stops"] = False
        return project, cache

    def test_no_stop_description_and_each_stop_named_at_most_once_per_line(self):
        project, cache = self._project()
        asked = []
        script, report = build_tour_script(project, cache, generate=lambda p, n: asked.append(p) or None)
        assert "四百年の歴史" not in script and "海の神を祀ります" not in script
        assert not any("■ 場所:" in p and "参考" in p for p in asked)  # no describe prompt is ever built
        assert cue_tags(script) == ["start", "1", "go1", "2", "go2", "3", "go3", "end", "distance"]
        stops = {r["kind"]: r["text"] for r in report if r["kind"].startswith("stop")}
        assert stops["stop2"] == stops["stop3"] == ""
        assert stops["stop1"] == "大きな橋も、この近くにあります。"  # hosts a stop-by card: says what is around

    def test_time_goes_to_the_way_lines_and_the_overview_still_fits(self):
        from services.localization.overview_script import in_overview_range, plan_budget

        project, cache = self._project()
        budget = plan_budget(project, build_brief(project, cache))
        # only the stop that hosts a stop-by batch keeps time (the map freezes there)
        assert [n for n, v in budget["describe"].items() if v] == [1]
        assert in_overview_range(budget["estimated"])
