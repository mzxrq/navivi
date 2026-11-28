"""Themed cards as drop-in style files, and the hud.json layout."""

import io
import json
import re
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from services import video_text
from services.hudtheme import cards, layout, model, styles

JA = video_text.labels_for("ja")


def _style(folder, card, name, text):
    (folder / card).mkdir(parents=True, exist_ok=True)
    (folder / card / name).write_text(text, encoding="utf-8")


@pytest.fixture
def mine(tmp_path, monkeypatch):
    folder = tmp_path / "Styles"
    monkeypatch.setenv("NAVIVI_STYLES_DIR", str(folder))
    return folder


def _title(style="default", title="t"):
    return cards.title_card(model.load_theme("sea"), title, True, "a", "a", JA, style=style).html


def test_a_file_added_to_the_styles_folder_is_found_and_used(mine):
    assert styles.available("title") == ["default"]
    _style(mine, "title", "ribbon.html", '<div class="card ribbon">{{ title }}</div>')

    assert styles.available("title") == ["default", "ribbon"]
    assert _title("ribbon", "友ヶ島") == '<div class="card ribbon">友ヶ島</div>'


def test_an_svg_file_is_a_style_too_and_names_are_escaped(mine):
    _style(mine, "title", "flat.svg", '<svg class="card" width="10" height="10"><text>{{ title }}</text></svg>')

    assert "<text>&lt;b&gt;</text>" in _title("flat", "<b>")


def test_the_users_file_wins_over_the_built_in_one(mine):
    _style(mine, "title", "default.html", '<div class="card">own</div>')

    assert _title() == '<div class="card">own</div>'


@pytest.mark.parametrize("broken", [
    '<div class="card">{{ no_such_value }}</div>',
    '<div class="card">{% if %}</div>',
    '<div class="box">no card root</div>',
    '<div class="card">{{ title.__class__.__mro__[1].__subclasses__() }}</div>',  # the sandbox
    '<div class="card">{% include "../secret.html" %}</div>',
])
def test_a_broken_or_hostile_style_falls_back_to_the_built_in_one(mine, broken):
    _style(mine, "title", "default.html", broken)
    _style(mine, "title", "bad.html", broken)

    for name in ("default", "bad"):
        assert 'class="card grow"' in _title(name)


@pytest.mark.parametrize("name", ["missing", "../title/default", "a b", ""])
def test_an_unknown_or_path_like_style_name_gives_the_default(mine, name):
    assert 'class="card grow"' in _title(name)


def test_a_strip_style_without_its_progress_line_is_not_used(mine):
    _style(mine, "strip", "noline.html", '<div class="card">x</div>')
    segments = model.route_segments([1.0, 2.0], ["walking"] * 2, [(0.0, "S", "a"), (2.0, "E", "b")])

    html = cards.strip_card(model.load_theme("sea"), segments, "a", "b", style="noline").html

    assert 'data-line="48 398 36"' in html


def test_a_style_can_use_the_built_in_artwork(mine):
    _style(mine, "title", "boat.html", '<div class="card"><svg>{% include "parts/ferry.svg" %}</svg></div>')

    assert re.search(r"<(path|rect|polygon|circle)\b", _title("boat"))  # whatever the boat looks like


def test_a_style_runs_no_script_and_loads_nothing_but_the_fonts(mine):
    pytest.importorskip("playwright")
    from services.hudtheme import render

    # Red if the page could run the handler; the remote picture must simply not load.
    _style(mine, "title", "evil.html",
           '<div class="card" style="width:40px;height:40px;background:#00ff00">'
           '<img src="https://example.invalid/x.png" onerror="this.parentNode.style.background=\'#ff0000\'"></div>')
    card = cards.title_card(model.load_theme("sea"), "t", True, "a", "a", JA, style="evil")

    picture = render.render_cards([card], 1.0)[0]

    assert picture.getpixel((render.PAD + 35, render.PAD + 35))[:3] == (0, 255, 0)


@pytest.mark.parametrize("seconds", [1320, 11 * 3600 + 59 * 60])  # the long time has to be shrunk to its box
def test_the_banners_distance_and_time_are_the_same_size(seconds):
    sync_api = pytest.importorskip("playwright.sync_api")
    from services.hudtheme import render

    card = cards.totals_card(model.load_theme("sea"), 0.76, seconds, JA, leg=True)

    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-gpu"])
        page = render._new_page(browser, 1.0)
        page.evaluate("html => { document.body.innerHTML = html; }", card.html)
        page.evaluate(render._FIT_JS)
        sizes = page.eval_on_selector_all(".num", "els => els.map(el => getComputedStyle(el).fontSize)")
        browser.close()

    assert len(sizes) == 2 and sizes[0] == sizes[1]


def test_layout_defaults_then_theme_then_project():
    found = layout.merge({"title": {"x": 40}}, {"title": {"y": 50, "style": "ribbon"}, "modes": {"show": False}})

    assert (found["title"].x, found["title"].y, found["title"].style) == (40.0, 50.0, "ribbon")
    assert found["modes"].show is False and found["totals"] == layout.DEFAULTS["totals"]


def test_bad_layout_values_keep_the_defaults():
    found = layout.merge({
        "title": {"anchor": "middle", "x": "10", "scale": float("nan"), "show": 1, "nope": 3},
        "totals": {"scale": 99}, "strip": 5, "ghost": {}, "notices": {"scale": 1.5, "x": 30},
    })

    assert found["title"] == layout.DEFAULTS["title"] and found["strip"] == layout.DEFAULTS["strip"]
    assert found["totals"].scale == layout.MAX_SCALE
    assert found["notices"].scale == 1.0 and found["notices"].x == 30.0
    assert layout.merge("nonsense") == layout.DEFAULTS


@pytest.mark.parametrize("anchor, at", [
    ("top-left", (20, 10)), ("top-right", (880, 10)), ("bottom-left", (20, 540)),
    ("bottom-right", (880, 540)), ("top-center", (470, 10)), ("middle-center", (470, 285)),
])
def test_a_card_is_placed_from_its_anchor(anchor, at):
    assert layout.place(layout.Entry(anchor, 10, 5), (100, 50), (1000, 600), 2.0) == at


def test_a_card_never_leaves_the_frame():
    assert layout.place(layout.Entry("top-left", 5000, -40), (100, 50), (1000, 600), 1.0) == (900, 0)


def _hud(project, text):
    (project / layout.FILE_NAME).write_text(text, encoding="utf-8")


def test_only_a_readable_hud_json_with_a_theme_makes_a_project_themed(tmp_path):
    assert layout.read(tmp_path) is None and layout.fingerprint(tmp_path) is None
    for text in ("not json", "[1]", '{"layout": {}}', '{"theme": "classic"}', '{"theme": "nope"}'):
        _hud(tmp_path, text)
        assert layout.read(tmp_path) is None, text
    _hud(tmp_path, json.dumps({"theme": "mine", "layout": {"modes": {"show": False}}}))

    assert layout.read(tmp_path) == {"theme": "mine", "layout": {"modes": {"show": False}}}
    assert layout.project_hud(tmp_path, {"theme": "dark"}, "T")["dark"] is True


def test_editing_hud_json_or_a_style_file_changes_the_fingerprint(tmp_path, mine):
    _hud(tmp_path, '{"theme": "sea"}')
    first = layout.fingerprint(tmp_path)
    _style(mine, "title", "x.html", '<div class="card"></div>')
    second = layout.fingerprint(tmp_path)
    _hud(tmp_path, '{"theme": "mine"}')

    assert len({first, second, layout.fingerprint(tmp_path)}) == 3


def test_hud_json_can_name_the_picture(tmp_path):
    _hud(tmp_path, '{"theme": "sea", "scene": "katsuragi"}')

    assert layout.project_hud(tmp_path, {}, "T")["scene"] == "katsuragi"


@pytest.mark.parametrize("dark", [False, True])
def test_a_named_picture_replaces_the_themes_own(mine, dark):
    own = model.load_theme("sea", dark)["scene"]

    assert "#D6301F" in model.load_theme("sea", dark, "katsuragi")["scene"]  # the built-in spider lilies
    assert model.load_theme("sea", dark, "no-such")["scene"] == own
    assert model.load_theme("sea", dark, "../sea")["scene"] == own
    _style(mine, "scene", "katsuragi.svg", '<rect id="my-own"/>')
    assert model.load_theme("sea", dark, "katsuragi")["scene"] == '<rect id="my-own"/>'


def test_the_legs_and_the_outro_use_the_projects_picture(tmp_path):
    from services.vdoprocessing import outro_themed
    from services.vdoprocessing.pydeckrecorder.themed_leg import ThemedLegHud

    _hud(tmp_path, '{"theme": "sea", "scene": "katsuragi"}')
    leg = ThemedLegHud(layout.project_hud(tmp_path, {}, "T"), "sea", "walking", (1.0, 60), (0.0, 0))
    outro = outro_themed.outro_theme(tmp_path, {}, [], "scroll")

    assert "#D6301F" in leg.theme["scene"] and "#D6301F" in outro["scene"]


def test_a_themed_leg_frames_the_route_between_its_cards():
    from services.vdoprocessing.pydeckrecorder.leg_camera import _fit_view_for_path, _project_lonlat_to_px
    from services.vdoprocessing.pydeckrecorder.themed_leg import ThemedLegHud

    size, lats = (1920, 1080), [34.27, 34.28]  # a leg that runs straight up the frame
    hud = ThemedLegHud({"theme": "sea"}, "sea", "walking", (1.0, 600), (0.0, 0))

    top, bottom = hud.margins(size, 186.0, 100.0)

    lon, lat, zoom = _fit_view_for_path([135.0, 135.0], lats, size, 0.05, 0.0, bottom, top)
    ys = [_project_lonlat_to_px(135.0, y, lon, lat, zoom, size)[1] for y in lats]
    boxes = hud.room(size, ("next", "leg_banner", "leg_rail", "remaining"))
    under_top = max(box[3] for box in boxes if box[1] < 540)
    over_bottom = min(box[1] for box in boxes if box[1] >= 540)
    assert under_top + 50 < min(ys) and max(ys) < over_bottom - 30  # a pin's height above, a name below


@pytest.mark.parametrize("moved", [
    {"next": {"anchor": "middle-center"}},  # a card in the middle claims no band
    {"leg_rail": {"y": 400}},  # ...and one put far from its edge never takes the whole frame
])
def test_a_card_away_from_its_edge_does_not_squeeze_the_leg_away(moved):
    from services.vdoprocessing.pydeckrecorder.themed_leg import ThemedLegHud

    hud = ThemedLegHud({"theme": "sea", "layout": moved}, "sea", "walking", (1.0, 600), (0.0, 0))

    top, bottom = hud.margins((1920, 1080), 186.0, 100.0)

    assert top + bottom <= 1080 * 0.6


def _panels(hud, **changes):
    from services.mapfetcher.graphicengine import GraphicsEngine
    from services.vdoprocessing.spatial_renderer.course_themed import themed_panels

    arguments = dict(
        w=1280, h=720, loop=True, has_stopbys=True, has_closed=True,
        summary={"total_distance_km": 10.0, "total_duration_seconds": 3600,
                 "mode_breakdown": {"walking": 4.0, "ferry": 6.0},
                 "mode_duration": {"walking": 2400, "ferry": 1200}},
        stops=[(0.0, "S", "駅"), (40.0, "1", "神社"), (100.0, "E", "駅")],
        cum=list(np.linspace(1, 100, 100)), modes=["walking"] * 40 + ["ferry"] * 60)
    return themed_panels(GraphicsEngine(), hud, **{**arguments, **changes})


def test_hud_json_renames_or_hides_the_strips_stretches(tmp_path):
    segments = [model.Segment("walking", 0, 1, "1–3", "神社"), model.Segment("walking", 2, 3, "4–11", "桟橋"),
                model.Segment("walking", 3, 4, "12", "港")]
    _hud(tmp_path, json.dumps({"theme": "sea", "names": {"1-3": "", "4–11": "友ヶ島", "12": 5}}))

    renamed = model.rename(segments, layout.read(tmp_path)["names"])

    assert [s.place for s in renamed] == ["", "友ヶ島", "港"]
    html = cards.strip_card(model.load_theme("sea"), renamed, "a", "b").html
    assert html.count("data-two") == 4 and "神社" not in html and ">1–3</div>" in html  # S, two names, E


@pytest.mark.parametrize("glyph, shown", [("2", True), ("+3", False), ("・", False)])
def test_a_stop_by_card_leaves_out_the_previous_place(glyph, shown):
    html = cards.next_card(model.load_theme("sea"), glyph, "神社", "+2", "常行寺", JA).html

    assert ("常行寺" in html.replace("<wbr>", "")) is shown


@pytest.mark.parametrize("build", [
    lambda theme: cards.next_card(theme, "+3", "神社", "", "", JA),
    lambda theme: cards.place_card(theme, "+3", "神社"),
])
def test_the_number_sits_in_the_middle_of_its_circle(build):
    sync_api = pytest.importorskip("playwright.sync_api")
    from services.hudtheme import render

    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-gpu"])
        page = render._new_page(browser, 8.0)
        page.evaluate("html => { document.body.innerHTML = html; }", build(model.load_theme("sea")).html)
        page.evaluate(render._FIT_JS)
        circle = page.locator(".card > div[style*='border-radius:50%']")
        shot = np.array(Image.open(io.BytesIO(circle.screenshot())).convert("RGB")).astype(int)
        browser.close()

    h, w = shot.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    inside = (xx - w / 2) ** 2 + (yy - h / 2) ** 2 < (w / 2 * 0.75) ** 2  # clear of the white ring
    ys, _ = np.nonzero(inside & (shot > 215).all(axis=2))
    assert abs((ys.min() + ys.max()) / 2 - h / 2) / 8 < 1  # card px


@pytest.mark.parametrize("glyph", ["5", "+4", "+12"])
def test_the_previous_places_number_is_in_a_round_circle(glyph):
    sync_api = pytest.importorskip("playwright.sync_api")
    from services.hudtheme import render

    card = cards.next_card(model.load_theme("sea"), "1", "神社", glyph, "称念寺", JA)

    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-gpu"])
        page = render._new_page(browser, 1.0)
        page.evaluate("html => { document.body.innerHTML = html; }", card.html)
        page.evaluate(render._FIT_JS)
        width, height, text = page.eval_on_selector(
            ".ring", "el => [el.offsetWidth, el.offsetHeight, el.scrollWidth - el.clientWidth]")
        browser.close()

    assert width == height and text <= 0  # round, and the number stays inside it


def test_a_themed_overviews_popup_cards_and_notices_use_the_cards_font():
    pytest.importorskip("playwright")
    from services.mapfetcher.graphicengine import GraphicsEngine
    from services.mapfetcher.graphicengine.glyphs import drawable

    graphics = _panels({"theme": "sea", "title": "t"}).graphics

    for candidates in (graphics.FONT_CANDIDATES_REGULAR, graphics.FONT_CANDIDATES_BOLD):
        assert "ZenMaru" in graphics._card_font(candidates, 20).path
    assert "ZenMaru" not in GraphicsEngine.FONT_CANDIDATES_BOLD[0]  # an unthemed video keeps its font
    assert drawable("Jūzō") == "Juzo"  # neither font has every long vowel: no empty boxes


def test_a_themed_overview_traces_with_the_themed_ferry():
    pytest.importorskip("playwright")
    panels = _panels({"theme": "sea", "title": "t"})

    icon = panels.graphics.transport_icon_sprite(0, 0.0, "ferry", 60)

    stripe = np.array([0x5E, 0x3F, 0xF4])  # BGR of the red stripe in designs/parts/ferry.svg
    assert (np.abs(icon[..., :3].astype(int) - stripe).sum(axis=2) < 40).sum() > 20


def test_a_project_without_a_hud_has_no_themed_panels():
    assert _panels(None) is None


def test_the_keep_clear_boxes_follow_the_cards_wherever_they_are_put():
    pytest.importorskip("playwright")
    usual = _panels({"theme": "sea", "title": "t"})
    moved = _panels({"theme": "sea", "title": "t", "layout": {
        "title": {"anchor": "middle-center", "x": 0, "y": 0}, "modes": {"show": False},
        "notices": {"anchor": "top-left", "x": 10, "y": 120}}})

    assert set(usual.cards) == {"title", "totals", "modes", "strip"}
    assert set(moved.cards) == {"title", "totals", "strip"}
    box = moved.cards["title"].box
    assert abs((box[0] + box[2]) / 2 - 640) < 1 and tuple(box) in moved.reserved
    assert usual.notice_dx == pytest.approx(0, abs=2) and usual.notice_dy == pytest.approx(0, abs=2)
    assert moved.notice_dy < -300 and len(moved.reserved) == len(moved.cards) + 2
    # The strip gives way to the banners at the foot, and keeps its size once they are elsewhere.
    assert usual.cards["strip"].scale <= moved.cards["strip"].scale
    banners = usual.reserved[-2:]
    assert all(usual.cards["strip"].box[0] >= b[2] for b in banners)
    assert getattr(usual.graphics, "equal_stopby_notices", False) is False  # restored


def test_a_themed_frame_draws_the_cards_and_the_progress():
    pytest.importorskip("playwright")
    panels = _panels({"theme": "mine", "title": "t"})
    timing = SimpleNamespace(stats_at=5.0, extras_at=6.0, closed_at=7.0, closed=[{}], stopbys=[{}], trace_end=9.0)
    blank = np.full((720, 1280, 3), 128, np.uint8)

    early = panels.compose(blank.copy(), 0, 1.0, 20.0, "walking", timing, 0.6)
    late = panels.compose(blank.copy(), 300, 10.0, 90.0, "ferry", timing, 0.6)

    left, top, right, bottom = (int(v) for v in panels.cards["modes"].box)
    inside = (slice(top + 5, bottom - 5), slice(left + 5, right - 5))
    assert np.abs(early[inside].astype(int) - 128).max() < 20  # not up yet (only the totals card's shadow)
    assert np.abs(late[inside].astype(int) - 128).mean() > 40
    left, top, right, bottom = (int(v) for v in panels.cards["strip"].box)
    assert not np.array_equal(early[top:bottom, left:right], late[top:bottom, left:right])
