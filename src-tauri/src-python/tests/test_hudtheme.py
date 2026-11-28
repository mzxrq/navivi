"""The themed ("Illustrated") video design: route data -> cards."""

import re

import pytest

from services import video_text
from services.hudtheme import cards, layout, model
from services.localization.japanese_words import phrases

JA = video_text.labels_for("ja")
EN = video_text.labels_for("en")


def _path(*runs):
    """(cum, modes) from (mode, km) runs, one point every 100 m."""
    cum, modes, d = [], [], 0.0
    for mode, km in runs:
        for _ in range(int(round(km * 10))):
            d += 0.1
            cum.append(round(d, 3))
            modes.append(mode)
    return cum, modes


LOOP_STOPS = [
    (0.0, "S", "加太駅"), (1.0, "1", "加太春日神社"), (1.8, "2", "阿字ヶ峰行者堂"), (2.5, "・", "寄り道"),
    (3.0, "3", "加太港"), (8.0, "4", "友ヶ島桟橋"), (11.0, "5", "友ヶ島灯台"), (18.0, "E", "加太駅"),
]


def test_a_ferry_loop_splits_into_walk_and_boat_and_groups_the_stops():
    cum, modes = _path(("walking", 3), ("ferry", 4), ("walking", 6), ("ferry", 4), ("walking", 1))

    segments = model.route_segments(cum, modes, LOOP_STOPS)

    assert [s.mode for s in segments] == ["walking", "ferry", "walking", "ferry", "walking"]
    assert [s.glyphs for s in segments] == ["1–3", "", "4–5", "", ""]
    assert [s.place for s in segments] == ["加太春日神社", "", "友ヶ島", "", ""]
    assert segments[0].start == 0.0 and segments[-1].end == cum[-1]


def test_a_pier_just_past_the_change_of_mode_is_counted_on_foot():
    cum, modes = _path(("walking", 3), ("ferry", 4), ("walking", 6))
    stops = [(1.0, "1", "加太"), (3.1, "2", "加太港"), (6.9, "3", "桟橋"), (9.0, "4", "灯台"), (12.9, "3", "桟橋 (復帰)")]

    segments = model.route_segments(cum, modes, stops)

    assert [s.glyphs for s in segments] == ["1–2", "", "3–4"]  # the return stop does not end the range at 3


def test_a_short_walk_with_no_stop_is_not_its_own_segment():
    cum, modes = _path(("walking", 3), ("ferry", 10), ("walking", 0.3))

    segments = model.route_segments(cum, modes, [(0.0, "S", "a"), (1.0, "1", "b"), (13.3, "E", "c")])

    assert [s.mode for s in segments] == ["walking", "ferry"]
    assert segments[-1].end == cum[-1]


def test_a_walk_only_route_is_one_segment():
    cum, modes = _path(("walking", 5))

    segments = model.route_segments(cum, modes, [(0.0, "S", "a"), (2.0, "1", "b"), (5.0, "E", "c")])

    assert [(s.mode, s.glyphs) for s in segments] == [("walking", "1")]


def test_the_strip_fills_its_width_in_route_order():
    cum, modes = _path(("walking", 1), ("ferry", 9))
    segments = model.route_segments(cum, modes, [(0.0, "S", "a"), (0.5, "1", "b"), (10.0, "E", "c")])

    spans = model.strip_spans(segments, 48, 398)

    assert spans[0][0] == 48 and spans[-1][1] == 398
    assert spans[0][1] == spans[1][0]
    assert spans[0][1] - spans[0][0] > 80  # a short walk still gets room for its chip
    assert model.strip_x(segments, spans, 0.0) == 48
    assert model.strip_x(segments, spans, 1.0) == spans[0][1]
    assert model.strip_x(segments, spans, 99.0) == 398


def test_mode_cards_follow_the_route_and_leave_out_unused_modes():
    found = model.mode_cards({"ferry": 12.0, "walking": 11.9, "driving": 0.0},
                             {"ferry": 2400, "walking": 9780})

    assert found == [("walking", 11.9, 9780), ("ferry", 12.0, 2400)]


def test_car_and_drive_are_the_same_mode():
    assert model.mode_cards({"car": 2.0, "driving": 1.0}, {"car": 60, "driving": 30}) == [("driving", 3.0, 90)]


def test_climb_ignores_gps_jitter():
    assert model.climb_m([10, 11, 10, 11, 10]) == 0
    assert model.climb_m([0, 100, 50, 250]) == 300


def test_classic_is_the_default_and_auto_picks_from_the_route(monkeypatch):
    assert model.resolve_theme(None, ["ferry"], 0) is None
    assert model.resolve_theme("classic", ["ferry"], 0) is None
    assert model.resolve_theme("no-such-theme", ["ferry"], 0) is None

    monkeypatch.setattr(model, "theme_ids", lambda: ["countryside", "mountain", "sea", "town"])
    assert model.resolve_theme("auto", ["walking", "ferry"], 900) == "sea"
    assert model.resolve_theme("auto", ["walking"], 900) == "mountain"
    assert model.resolve_theme("auto", ["walking"], 10) == "town"
    assert model.resolve_theme("countryside", ["ferry"], 0) == "countryside"


def test_the_themed_design_is_light_unless_the_project_says_dark():
    assert not model.is_dark({}) and not model.is_dark({"theme": "light"}) and not model.is_dark({"theme": "x"})
    assert model.is_dark({"theme": "dark"})


def test_auto_falls_back_to_a_theme_that_exists():
    assert model.resolve_theme("auto", ["walking"], 10) in model.theme_ids()


def test_place_names_are_escaped_in_every_card():
    nasty = '<img src=x onerror=alert(1)>'
    cum, modes = _path(("walking", 5))
    segments = model.route_segments(cum, modes, [(0.0, "S", nasty), (2.0, "1", nasty), (5.0, "E", nasty)])
    theme = model.load_theme("sea")
    built = [
        cards.title_card(theme, nasty, True, nasty, nasty, JA),
        cards.strip_card(theme, segments, nasty, nasty),
        cards.next_card(theme, "2", nasty, "1", nasty, JA),
        cards.leg_rail_card(theme, "2", "3", 0.3, [(0.5, nasty)]),
    ]
    for card in built:
        assert nasty not in card.html


def test_stop_bys_count_on_through_the_whole_route():
    assert model.stopby_marks([1, 0, 2]) == [["+1"], [], ["+2", "+3"]]


def test_a_stop_by_off_the_route_is_announced_as_an_extra_sight():
    theme = model.load_theme("sea")

    on_route = cards.next_card(theme, "+1", "番所", "1", "加太港", JA).html
    off_route = cards.next_card(theme, "+2", "番所", "1", "加太港", JA, off_route=True).html

    assert "つぎは" in on_route and "追加の見どころ" not in on_route
    assert "追加の見どころ" in off_route and "つぎは" not in off_route
    assert ">+2</div>" in off_route


@pytest.mark.parametrize("theme_id", ["sea", "mine"])
def test_number_circles_wear_the_map_pins_colors(theme_id):
    theme = model.load_theme(theme_id)

    def disc(glyph):  # the next-stop card's big circle
        html = cards.next_card(theme, glyph, "n", "", "", JA).html
        return html.split(f">{glyph}</div>")[0].rsplit("<div", 1)[1]

    assert "background:#4287F5" in disc("2")  # blue, as the map pin
    assert "background:#33261C" in disc("+2")  # a stop-by: the near-black pin
    closed = model.pin_color(theme, "×")
    assert f"background:{closed}" in disc("×") and closed not in (theme["panel"], theme["accent"], theme["primary"])
    rail = cards.leg_rail_card(theme, "S", "2", 0.5, [(0.7, "+1"), (0.8, "×")]).html
    for glyph in ("S", "2", "+1", "×"):
        assert f'fill="{model.pin_color(theme, glyph)}"' in rail
    assert 'class="ring" style="background:#4287F5"' in cards.next_card(theme, "2", "n", "1", "p", JA).html


def test_the_previous_stops_number_is_circled():
    theme = model.load_theme("sea")

    html = cards.next_card(theme, "2", "番所", "1", "加太港", JA).html

    assert 'class="ring"' in html and ">1</span>" in html
    assert 'class="ring"' not in cards.next_card(theme, "1", "番所", "", "", JA).html


def test_the_title_card_says_loop_or_one_way():
    theme = model.load_theme("sea")

    loop = cards.title_card(theme, "友ヶ島", True, "加太駅", "加太駅", JA).html
    one_way = cards.title_card(theme, "熊野", False, "A駅", "B駅", JA).html.replace("<wbr>", "")

    assert "周回" in loop and "発着" in loop
    assert "片道" in one_way and "A駅 → B駅" in one_way


def test_totals_style_the_units_apart_from_the_numbers_in_any_language():
    theme = model.load_theme("sea")

    ja = cards.totals_card(theme, 23.9, 12180, JA).html
    en = cards.totals_card(theme, 23.9, 12180, EN, remaining=True).html

    assert '23.9<span class="u">' in ja and "合計距離" in ja
    assert '3<span class="u">時間</span>23<span class="u">分</span>' in ja
    assert "Distance left" in en


@pytest.mark.parametrize("theme_id", ["sea", "mine"])
def test_every_theme_builds_every_card(theme_id):
    theme = model.load_theme(theme_id)
    cum, modes = _path(("walking", 3), ("ferry", 5))
    segments = model.route_segments(cum, modes, [(0.0, "S", "a"), (1.0, "1", "b"), (8.0, "E", "c")])

    built = [
        cards.title_card(theme, "t", True, "a", "a", JA), cards.totals_card(theme, 8.0, 600, JA),
        cards.strip_card(theme, segments, "a", "c"), cards.next_card(theme, "+1", "n", "1", "p", JA),
        cards.leg_rail_card(theme, "1", "2", 0.5, [(0.7, "+1")]),
        cards.mode_bar(theme, [(m, 1.0, 60) for m in ("walking", "ferry", "driving", "airplane")], JA),
    ]
    assert all(card.html for card in built)


def test_a_picture_brings_its_own_pattern_and_outro_backdrop():
    plain, katsuragi = model.load_theme("mine"), model.load_theme("mine", scene="katsuragi")

    assert plain["backdrop"] == "" and "<svg" in katsuragi["backdrop"]
    assert katsuragi["pattern"] != plain["pattern"] and "$id" in katsuragi["pattern"]
    assert katsuragi["primary"] == plain["primary"]


def test_your_palette_replaces_the_sea_colors():
    theme = model.load_theme("mine")

    html = (cards.totals_card(theme, 8.0, 600, JA).html + cards.mode_bar(theme, [("ferry", 1.0, 60)], JA).html
            + cards.title_card(theme, "t", True, "a", "a", JA).html)

    for colour in ("#CC6256", "#F9F6EA", "#285943"):
        assert colour in html
    for sea_colour in ("#1E3A5F", "#C73E24", "#FFD77A", "#F2A93B"):
        assert sea_colour not in html


def test_red_is_the_main_color_of_your_theme():
    theme = model.load_theme("mine")

    for card in (cards.title_card(theme, "t", True, "a", "a", JA), cards.next_card(theme, "1", "n", "", "", JA)):
        assert "background:#CC6256" in card.html
    assert 'Z" fill="#CC6256"' in cards.totals_card(theme, 8.0, 600, JA).html
    assert theme["primary"] == theme["mode_colors"]["walking"] == "#CC6256"
    assert theme["mode_colors"]["ferry"] != "#CC6256"  # still told apart from walking


def test_the_leg_banner_gives_this_legs_distance_and_time():
    theme = model.load_theme("sea")

    card = cards.totals_card(theme, 1.4, 1260, JA, leg=True)

    assert "区間距離" in card.html and "所要時間" in card.html
    assert '1.4<span class="u">km</span>' in card.html and '21<span class="u">分</span>' in card.html
    assert "scene-sky" not in card.html  # no picture: the remaining card below already has it
    assert card.width < cards.totals_card(theme, 1.4, 1260, JA).width


def test_the_compass_shows_the_heading_and_keeps_the_ids_the_leg_page_updates():
    card = cards.compass_card(model.load_theme("sea"), 47.3, JA)

    assert "北東 47°" in card.html and 'rotate(47 42 42)' in card.html
    for ident in ("hud-compass-pointer", "hud-compass-letter", "hud-compass-label"):
        assert f'id="{ident}"' in card.html
    assert "NE 360" not in cards.compass_card(model.load_theme("sea"), 359.7, EN).html


@pytest.mark.parametrize("modes", [1, 2, 3, 4])
def test_the_default_layout_keeps_the_overview_cards_apart(modes):
    size = (1010, layout.OVERVIEW_HEIGHT)  # a 16:9 frame in artboard px
    sizes = {"title": (515, 96), "totals": (372, 76), "strip": (447, 76),
             "modes": (186 * min(modes, 2), 40 if modes <= 2 else 72)}

    boxes = [(*layout.place(layout.DEFAULTS[name], s, size, 1.0), *s) for name, s in sizes.items()]

    for i, (x, y, w, h) in enumerate(boxes):
        assert x >= 0 and y >= 0 and x + w <= size[0] and y + h <= size[1]
        for other_x, other_y, other_w, other_h in boxes[i + 1:]:
            assert x + w <= other_x or other_x + other_w <= x or y + h <= other_y or other_y + other_h <= y


@pytest.mark.parametrize("language", ["ja", "en"])
def test_the_themed_banners_are_the_same_size_and_level(language, monkeypatch):
    from services.mapfetcher.graphicengine import GraphicsEngine

    monkeypatch.setattr(video_text, "current_labels", lambda: video_text.labels_for(language))
    engine = GraphicsEngine()
    plain = [engine.stopby_notice_box(1920, 1080, kind) for kind in ("stopby", "closed")]
    engine.equal_stopby_notices = True
    stopby, closed = [engine.stopby_notice_box(1920, 1080, kind) for kind in ("stopby", "closed")]

    assert stopby == closed  # same width, height, top and bottom (the second is only slid right)
    assert plain[0] != plain[1]  # the classic banners keep their own sizes
    ribbons = [engine._stopby_notice_layout(1920, 1080, kind)[4] for kind in ("stopby", "closed")]
    assert ribbons[0] == ribbons[1]


def test_the_mode_bar_is_one_slim_card_however_many_modes():
    theme = model.load_theme("sea")
    four = [(m, 1.2, 600) for m in ("walking", "ferry", "driving", "airplane")]

    one, bar = cards.mode_bar(theme, four[:1], JA), cards.mode_bar(theme, four, JA)

    assert (one.width, one.height) == (186, 40) and (bar.width, bar.height) == (372, 72)
    for mode, _, _ in four:
        assert theme["mode_colors"][mode] in bar.html
    assert bar.html.count('1.2<span class="u">km</span>') == 4 and "10分" in bar.html.replace('<span class="u">分</span>', "分")


def test_each_time_sits_on_its_modes_pill_right_after_the_distance():
    theme = model.load_theme("mine")

    html = cards.mode_bar(theme, [("walking", 13.9, 7080), ("ferry", 10.0, 5100)], JA).html

    for mode, time in (("walking", "1時間58分"), ("ferry", "1時間25分")):
        assert f"background:{theme['mode_colors'][mode]}" in html.split(time)[0].rsplit("<div", 1)[1]
    assert 'class="split"' in html
    assert 'class="split"' not in cards.mode_bar(theme, [("walking", 1.0, 60)], JA).html


def test_icons_distances_and_time_pills_line_up_in_columns():
    four = [("walking", 52.0, 1860), ("airplane", 450.0, 15900), ("driving", 108.4, 45000), ("ferry", 30.0, 1080)]
    html = cards.mode_bar(model.load_theme("sea"), four, JA).html

    for part in ("icon", "distance", "time"):
        boxes = re.findall(rf'data-part="{part}"[^>]*?left:([\d.]+)px;[^>]*?width:([\d.]+)px', html)
        assert len(boxes) == 4
        # walking over driving, airplane over ferry: the same left edge and width in each column
        assert boxes[0] == boxes[2] and boxes[1] == boxes[3] and boxes[0] != boxes[1]


def test_the_attraction_clips_place_banner_numbers_the_stop_and_grows_with_the_name():
    pytest.importorskip("fugashi")
    theme = model.load_theme("mine")

    card = cards.place_card(theme, "3", "加太春日神社")

    assert "card grow" in card.html and "data-wave" in card.html
    assert f"background:{theme['pins']['stop']}" in card.html and ">3</div>" in card.html
    assert "加太<wbr>春日<wbr>神社" in card.html
    assert "border-radius:50%" not in cards.place_card(theme, "", "加太").html  # no number, no empty circle
    assert "<img" not in cards.place_card(theme, "3", "<img src=x>").html


def _luminance(colour):
    def linear(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (linear(int(colour[i:i + 2], 16)) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("theme_id", ["sea", "mine"])
def test_the_dark_version_has_dark_surfaces_that_stay_readable(theme_id):
    light, dark = model.load_theme(theme_id), model.load_theme(theme_id, dark=True)

    for surface in ("paper", "pale", "panel"):
        assert _luminance(dark[surface]) < _luminance(light[surface])
    for surface in ("paper", "pale", "label"):
        assert _contrast(dark["ink"], dark[surface]) >= 4.5
        assert _contrast(dark["muted"], dark[surface]) >= 4.5
    assert _contrast("#FFFFFF", dark["panel"]) >= 4.5 and _contrast(dark["gold"], dark["panel"]) >= 4.5
    assert dark["pins"]["closed"] != dark["panel"] and dark["id"] != light["id"]
    assert dark["scene"] != light["scene"]


@pytest.mark.parametrize("theme_id", ["sea", "mine"])
def test_black_and_white_are_the_dark_versions_main_colors(theme_id):
    theme = model.load_theme(theme_id, dark=True)

    for key in ("panel", "paper", "pale", "label", "ink", "line", "gold", "soft", "muted", "edge", "accent",
                "pattern_dark", "pattern_pale", "sky", "sunset", "water", "hill", "road"):
        value = theme[key]
        assert value[1:3] == value[3:5] == value[5:7], (key, value)  # a grey, from black to white
    colours = set(re.findall(r"#[0-9A-Fa-f]{6}\b", theme["scene"]))
    assert all(c[1:3] == c[3:5] == c[5:7] for c in colours), colours  # the night picture too
    assert theme["pins"]["stop"] == "#4287F5"  # numbers still wear the map pins' colors


@pytest.mark.parametrize("theme_id", ["sea", "mine"])
def test_no_card_keeps_a_white_surface_in_the_dark(theme_id):
    theme = model.load_theme(theme_id, dark=True)
    cum, modes = _path(("walking", 3), ("ferry", 5))
    segments = model.route_segments(cum, modes, [(0.0, "S", "a"), (1.0, "1", "b"), (8.0, "E", "c")])
    built = [
        cards.title_card(theme, "t", True, "a", "a", JA), cards.totals_card(theme, 8.0, 600, JA),
        cards.totals_card(theme, 8.0, 600, JA, leg=True), cards.strip_card(theme, segments, "a", "c"),
        cards.next_card(theme, "+1", "n", "1", "p", JA), cards.leg_rail_card(theme, "1", "2", 0.5, [(0.7, "+1")]),
        cards.mode_bar(theme, [("walking", 1.0, 60)], JA), cards.compass_card(theme, 47, JA),
    ]
    for card in built:
        assert "background:#fff" not in card.html and "border:3px solid #fff;border-radius:24px" not in card.html
    assert 'r="20" fill="#fff"' not in built[5].html  # the walker's circle on the leg bar


def test_the_apps_banners_can_wear_the_dark_themes_surface(monkeypatch):
    from services.mapfetcher.graphicengine import GraphicsEngine

    monkeypatch.setattr(video_text, "current_labels", lambda: JA)
    assert model.notice_colors(model.load_theme("sea")) is None  # light keeps the app's white banner
    theme = model.load_theme("mine", dark=True)
    engine = GraphicsEngine()
    engine.stopby_notice_colors = model.notice_colors(theme)
    body = engine._stopby_notice_layout(1920, 1080)[5]

    layer = engine._stopby_notice_layer(1920, 1080, "stopby")[0]

    paper = tuple(int(theme["paper"][i:i + 2], 16) for i in (1, 3, 5))
    assert layer.getpixel((int(body[2]) - 20, int(body[3]) - 20))[:3] == paper


@pytest.mark.parametrize("name, pieces", [
    ("葛城二十八宿経塚", ["葛城", "二十八宿", "経塚"]),
    ("阿字ヶ峰行者堂", ["阿字ヶ峰", "行者堂"]),
    ("淡嶋神社の参道入口", ["淡嶋", "神社の", "参道", "入口"]),
    ("金剛葛城山頂展望台", ["金剛", "葛城", "山頂", "展望台"]),
    ("第四砲台跡", ["第四", "砲台跡"]),
    ("役行者堂跡（序品窟）", ["役行者堂跡", "（序品窟）"]),
])
def test_a_japanese_name_breaks_only_between_words(name, pieces):
    pytest.importorskip("fugashi")
    assert phrases(name) == pieces


def test_a_name_without_japanese_is_left_to_its_spaces():
    assert phrases("Kada Port Terminal") == ["Kada Port Terminal"]
    assert phrases("") == [""]


def test_the_cards_that_wrap_a_long_name_mark_where_it_may_break():
    pytest.importorskip("fugashi")
    theme = model.load_theme("sea")
    name = "金剛葛城山頂展望台"
    segments = model.route_segments(*_path(("walking", 5)), [(0.0, "S", name), (2.0, "1", name), (5.0, "E", name)])

    title = cards.title_card(theme, name, True, "駅", "駅", JA)
    next_stop = cards.next_card(theme, "2", name, "1", "駅", JA)
    for card in (title, next_stop, cards.strip_card(theme, segments, name, name)):
        assert "金剛<wbr>葛城<wbr>山頂<wbr>展望台" in card.html
    assert "card grow" in title.html and "card grow" in next_stop.html  # they get bigger, not smaller type
