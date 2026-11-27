"""The themed scroll outro: which places, how long, and how it is drawn."""

import json

import pytest

from services.vdoprocessing import outro_themed as ot

BRIEF = {"legs": [{"km": 1.0, "minutes": 10}, {"km": 2.0, "minutes": 20}, {"km": 3.0, "minutes": 30}]}


def wp(lat, name, text="", **extra):
    return {"lat": lat, "lng": 135.0, "label": name, "outroDescription": text, **extra}


def facts(screens):
    return [(s.badge, s.name, s.description, s.km, s.minutes) for s in screens]


def test_every_normal_stop_gets_a_screen_with_its_arriving_leg_described_or_not():
    stops = [wp(34.0, "A", "start"), wp(34.1, "B"), wp(34.2, "C", "  third  "), wp(34.3, "D", "end")]
    assert facts(ot.themed_screens(stops, BRIEF)) == [
        ("S", "A", "start", None, None), ("1", "B", "", 1.0, 10), ("2", "C", "third", 2.0, 20),
        ("E", "D", "end", 3.0, 30)]


def test_stopbys_and_closed_places_have_no_leg():
    stops = [wp(34.0, "A"), wp(34.05, "Shop", "s", isStopBy=True),
             wp(34.1, "Gone", "g", isStopBy=True, inaccessible=True), wp(34.2, "B", "b")]
    assert facts(ot.themed_screens(stops, BRIEF)) == [
        ("S", "A", "", None, None), ("+1", "Shop", "s", None, None), ("×", "Gone", "g", None, None),
        ("E", "B", "b", 1.0, 10)]


@pytest.mark.parametrize("stopbys, closed, names", [
    (True, True, ["A", "Shop", "Skipped", "Gone", "B"]),
    (False, True, ["A", "Gone", "B"]),
    (True, False, ["A", "Shop", "Skipped", "B"]),
    (False, False, ["A", "B"]),
])
def test_the_storyboard_decides_whether_stopbys_and_closed_places_show(stopbys, closed, names):
    stops = [wp(34.0, "A"), wp(34.02, "Shop", isStopBy=True), wp(34.04, "Skipped", "x", skipAssetGeneration=True),
             wp(34.06, "Gone", "g", isStopBy=True, inaccessible=True), wp(34.1, "B")]
    assert [s.name for s in ot.themed_screens(stops, BRIEF, stopbys=stopbys, closed=closed)] == names


def test_a_place_come_back_to_shows_the_visit_that_has_the_description():
    stops = [wp(34.0, "A"), wp(34.1, "B"), wp(34.0, "A (Return)", "home again")]
    assert [(s.badge, s.name, s.description) for s in ot.themed_screens(stops, BRIEF)] == [
        ("1", "B", ""), ("E", "A", "home again")]


def test_a_place_visited_twice_has_one_screen_but_a_stopby_beside_it_keeps_its_own():
    stops = [wp(34.0, "A", "a"), wp(34.0, "Kiosk", "k", isStopBy=True), wp(34.1, "B", "b"),
             wp(34.0, "A (Return)", "again")]
    assert [s.name for s in ot.themed_screens(stops, BRIEF)] == ["A", "Kiosk", "B"]


@pytest.mark.parametrize("text", ["", "   \n ", None])
def test_a_blank_description_is_no_description(text):
    screens = ot.themed_screens([wp(34.0, "A", text), wp(34.1, "B", text)], BRIEF)
    assert [s.description for s in screens] == ["", ""]


def test_without_a_brief_a_screen_has_no_figures():
    stops = [wp(34.0, "A", "a"), wp(34.1, "B", "b")]
    assert [(s.km, s.minutes) for s in ot.themed_screens(stops, None)] == [(None, None), (None, None)]


def test_each_screen_holds_and_then_scrolls():
    times = ot.frame_times(3, 30)
    assert len(times) == 75 + 2 * (24 + 45)
    assert times[:75] == [0.0] * 75
    assert times == sorted(times)
    assert len(set(times)) == 1 + 2 * 24  # holds repeat one picture
    assert len(ot.frame_times(1, 30)) == 75
    assert ot.scroll_keyframes(1) == [(0.0, 0), (100.0, 0)]
    assert [i for _, i in ot.scroll_keyframes(3)] == [0, 0, 1, 1, 2, 2]


def test_themed_only_with_a_theme_and_the_scroll_style(tmp_path):
    stops = [wp(34.0, "A", "a")]
    assert ot.outro_theme(tmp_path, {}, stops, "scroll") is None
    (tmp_path / "hud.json").write_text(json.dumps({"theme": "mine"}), encoding="utf-8")
    assert ot.outro_theme(tmp_path, {}, stops, "scroll")["panel"] == "#CC6256"
    assert ot.outro_theme(tmp_path, {}, stops, "grid") is None
    assert ot.outro_theme(tmp_path, {}, [wp(34.0, "A")], "scroll") is not None  # no description needed
    (tmp_path / "hud.json").write_text(json.dumps({"theme": "classic"}), encoding="utf-8")
    assert ot.outro_theme(tmp_path, {}, stops, "scroll") is None


def two_screens(tmp_path, **first):
    from PIL import Image

    photo = tmp_path / "a.png"
    Image.new("RGB", (400, 300), (0, 120, 0)).save(photo)
    base = dict(badge="S", name="A", description="d", photo=str(photo), km=None, minutes=None)
    return [ot.Screen(**{**base, **first}), ot.Screen("E", "B", "b", str(tmp_path / "missing.jpg"), 2.0, 20)]


def mine():
    from services.hudtheme import model

    return model.load_theme("mine")


def test_names_and_descriptions_are_text_not_markup(tmp_path):
    screens = two_screens(tmp_path, name="<b>x</b>", description="<img src=x onerror=alert(1)>")
    html = ot.page_html(screens, mine(), {"title": "T", "kicker": "K"}, (640, 360))
    assert "<b>x</b>" not in html and "&lt;b&gt;" in html and "<img src=x" not in html


def test_frames_are_the_video_size_and_holds_reuse_one_picture(tmp_path):
    html = ot.page_html(two_screens(tmp_path), mine(), {"title": "T", "kicker": ""}, (640, 360))
    times = ot.frame_times(2, 10)
    frames = list(ot.capture_frames(html, times, (640, 360)))  # the missing photo must not raise
    assert len(frames) == len(times) and frames[0].shape == (360, 640, 3)
    assert frames[1] is frames[0]
    assert (frames[-1] != frames[0]).any()


def test_a_scroll_ends_with_the_next_screen_exactly_in_place(tmp_path):
    screens = two_screens(tmp_path)
    html = ot.page_html(screens, mine(), {"title": "T", "kicker": ""}, (640, 360))
    alone = ot.page_html(screens[1:], mine(), {"title": "T", "kicker": ""}, (640, 360))
    last = list(ot.capture_frames(html, [ot.frame_times(2, 10)[-1]], (640, 360)))[0]
    expected = list(ot.capture_frames(alone, [0.0], (640, 360)))[0]
    difference = abs(last.astype(int) - expected.astype(int))
    assert difference[79:84].max() == 0  # nothing of the screen before is left under the title
    # gradients dither a level or two apart after a scroll, and a few edge pixels smooth differently
    assert (difference.max(axis=2) > 4).sum() <= 20


def test_the_backdrop_is_the_artwork_alone(tmp_path):
    html = ot.page_html(two_screens(tmp_path), mine(), {"title": "T", "kicker": ""}, (640, 360))
    bare = ot.capture_backdrop(html, (640, 360))
    full = list(ot.capture_frames(html, [0.0], (640, 360)))[0]
    assert bare.size == (640, 360) and bare.mode == "RGB"
    assert bare.getpixel((320, 30)) != tuple(full[30, 320])  # the title banner is gone
    assert bare.getpixel((150, 138)) != tuple(full[138, 150])  # and so are the cards


def test_a_corrupt_photo_falls_back_to_the_scene(tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not a picture")
    html = ot.page_html(two_screens(tmp_path, photo=str(bad)), mine(), {"title": "T", "kicker": ""}, (640, 360))
    assert "data:image" not in html


@pytest.mark.parametrize("text, lines", [
    ("短い説明です。", (3, 3)), ("長い説明です。" * 14, (4, 6)), ("長い説明です。" * 60, (7, 7)), ("x" * 600, (7, 7)),
])
def test_a_long_description_grows_its_box_and_keeps_its_size(tmp_path, text, lines):
    from playwright.sync_api import sync_playwright

    html = ot.page_html(
        two_screens(tmp_path, description=text, name=text), mine(), {"title": text, "kicker": ""}, (1280, 720))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-gpu"])
        page = ot.open_page(browser, html, (1280, 720))
        found = page.locator(".desc").first.evaluate("""e => ({
            size: getComputedStyle(e).fontSize, height: e.clientHeight, all: e.scrollHeight, width: e.clientWidth,
            card: e.closest('.about').getBoundingClientRect().height, bottom: e.closest('.about').getBoundingClientRect().bottom })""")
        name = page.locator(".name").first.evaluate("e => e.getBoundingClientRect().width")
        browser.close()
    assert found["size"] == "15px"
    assert lines[0] * 28 <= found["height"] <= lines[1] * 28 and found["height"] % 28 == 0
    assert found["card"] == found["height"] + 38 and found["width"] <= 335
    assert found["bottom"] <= 590  # on the screen, however long the text
    if lines[1] < 7:
        assert found["all"] <= found["height"] + 1  # every word shows
    assert name <= 410


def test_the_outro_style_does_not_make_the_legs_render_again(tmp_path, monkeypatch):
    from services.hudtheme import layout

    monkeypatch.setenv("NAVIVI_STYLES_DIR", str(tmp_path / "Styles"))
    (tmp_path / "hud.json").write_text(json.dumps({"theme": "mine"}), encoding="utf-8")
    before = layout.fingerprint(tmp_path)
    (tmp_path / "Styles" / "outro").mkdir(parents=True)
    (tmp_path / "Styles" / "outro" / "default.html").write_text('<div class="card"></div>', encoding="utf-8")
    assert layout.fingerprint(tmp_path) == before


def test_the_banner_shows_the_place_the_title_and_the_subtitle(tmp_path):
    heading = {"kicker": "Wakayama City", "title": "Katsuragi", "subtitle": "A day walk · 18 places"}
    html = ot.page_html(two_screens(tmp_path), mine(), heading, (640, 360))
    assert all(text in html for text in heading.values())


def test_the_cards_fill_the_middle_80_percent(tmp_path):
    from playwright.sync_api import sync_playwright

    html = ot.page_html(two_screens(tmp_path), mine(), {"title": "T", "kicker": ""}, (1280, 720))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-gpu"])
        page = ot.open_page(browser, html, (1280, 720))
        photo, stats = page.locator(".photo").first.bounding_box(), page.locator(".stats").first.bounding_box()
        browser.close()
    width = 1280 * 600 / 720
    assert photo["x"] == pytest.approx(width * 0.1, abs=0.5)
    assert stats["x"] + stats["width"] == pytest.approx(width * 0.9, abs=0.5)


@pytest.fixture
def project(tmp_path, monkeypatch):
    from PIL import Image

    from services.vdoprocessing import outrocard

    photo = tmp_path / "a.png"
    Image.new("RGB", (40, 30)).save(photo)
    config = {"project_name": "Trip", "directory_path": str(tmp_path),
              "settings": {"outro_style": "scroll", "outro_route_info": False},
              "waypoints": [wp(34.0, "A", "a", popup_image=[str(photo)]), wp(34.1, "B", "b")]}
    (tmp_path / "job_config.json").write_text(json.dumps(config), encoding="utf-8")
    (tmp_path / "hud.json").write_text(json.dumps({"theme": "mine"}), encoding="utf-8")
    monkeypatch.setattr(outrocard, "_write_scroll_clip", lambda page, out, *a, **k: bool(out.write_bytes(b"classic")))
    return tmp_path


def _render(project):
    from services.vdoprocessing.videopipeline import outro_step

    path = str(project / "job_config.json")
    clip = outro_step.render_outro_clip(path)
    marker = project / "assets" / "video" / ot.MARKER
    return open(clip, "rb").read(), marker.exists(), outro_step.outro_text_item(path)


def test_a_themed_project_renders_the_themed_outro_without_a_timeline_title(project, monkeypatch):
    seen = {}

    def write(out, screens, *a, **k):
        seen["legs"] = [s.km for s in screens]
        return bool(out.write_bytes(b"themed"))

    monkeypatch.setattr(ot, "write_themed_outro", write)
    assert _render(project) == (b"themed", True, None)
    assert seen["legs"][0] is None and seen["legs"][1] > 0  # the figures come even with route info off


def test_a_failed_themed_render_gives_todays_outro_with_its_title(project, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no browser")

    monkeypatch.setattr(ot, "write_themed_outro", boom)
    clip, marked, title = _render(project)
    assert clip == b"classic" and not marked and title["kind"] == "outro"


def test_removing_the_theme_clears_the_marker(project, monkeypatch):
    monkeypatch.setattr(ot, "write_themed_outro", lambda out, *a, **k: bool(out.write_bytes(b"themed")))
    _render(project)
    (project / "hud.json").unlink()
    clip, marked, title = _render(project)
    assert clip == b"classic" and not marked and title is not None


def test_the_themed_clip_has_every_screen_then_the_logos(tmp_path, monkeypatch):
    from PIL import Image

    from services.vdoprocessing import outrocard

    logo_dir = tmp_path / "logo"
    logo_dir.mkdir()
    Image.new("RGBA", (200, 80), (30, 60, 120, 255)).save(logo_dir / "logo.png")
    monkeypatch.setattr(outrocard, "LOGO_DIR", logo_dir)
    piped = []
    monkeypatch.setattr(outrocard, "_pipe_frames", lambda frames, *a: bool(piped.extend(frames)) or True)
    heading = {"title": "T", "kicker": ""}

    assert ot.write_themed_outro(tmp_path / "o.mp4", two_screens(tmp_path), mine(), heading, (640, 360), 10)

    assert len(piped) == len(ot.frame_times(2, 10)) + 8 + 30  # the screens, the logo fade, the logo hold
    assert all(f.shape == (360, 640, 3) for f in piped)
    assert (piped[-1] != piped[0]).any()


def test_each_box_rolls_one_after_another():
    seconds = ot.animation_seconds(3)
    assert seconds == pytest.approx(7.1)
    for slot in range(6):
        keys = ot.scroll_keyframes(3, slot * 0.07, 0.42)
        assert [i for _, i in keys] == [0, 0, 1, 1, 2, 2]
        assert keys[1][0] * seconds / 100 == pytest.approx(2.5 + slot * 0.07, abs=1e-4)
        assert keys[2][0] * seconds / 100 == pytest.approx(2.92 + slot * 0.07, abs=1e-4)


def test_a_tuned_hold_stays_still_however_many_screens(monkeypatch):
    monkeypatch.setattr(ot.tuning, "OUTRO_THEMED_HOLD_SECONDS", 1.55)  # not a whole number of frames
    times = ot.frame_times(30, 30)
    held = times[-1] / ot.animation_seconds(30) * 100
    for slot in range(6):
        keys = ot.scroll_keyframes(30, slot * 0.07, 0.42)
        arrivals = {index: percent for percent, index in reversed(keys)}  # each place's first keyframe
        assert arrivals[29] <= held


BOXES = ("photo", "now", "stats", "about", "upcoming", "next")


def _at(page, t):
    """Each box (and the route line and arrow) at animation time t: where it is, how visible, how far rolled."""
    page.evaluate(ot._SEEK_JS, t)
    return page.evaluate("""names => Object.fromEntries(names.map(name => {
        const e = document.querySelector('.' + name);
        if (!e) return [name, null];
        const r = e.getBoundingClientRect(), strip = e.querySelector('.strip');
        return [name, { top: r.top, height: r.height, opacity: +getComputedStyle(e).opacity,
                        roll: strip ? new DOMMatrix(getComputedStyle(strip).transform).m42 : 0 }];
    }))""", [*BOXES, "route", "arrow"])


def _shown(screens, times):
    from playwright.sync_api import sync_playwright

    html = ot.page_html(screens, mine(), {"title": "T", "kicker": ""}, (1280, 720))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-gpu"])
        page = ot.open_page(browser, html, (1280, 720))
        found = [_at(page, t) for t in times]
        browser.close()
    return found


def test_the_boxes_stay_put_and_their_contents_roll_one_after_another(tmp_path):
    one = two_screens(tmp_path)
    long = one[0]._replace(description="長い説明です。" * 30)
    times = ot.frame_times(3, 30)
    held, moving, second, last = _shown(
        [long, one[0], one[1]], (0.0, times[75 + 3], times[75 + 40], times[-1]))

    for name in (*BOXES, "arrow"):
        assert held[name]["top"] == moving[name]["top"] == second[name]["top"]
    assert [held[n]["roll"] for n in BOXES] == [0] * 6
    assert [second[n]["roll"] for n in BOXES] == pytest.approx([-210, -70, -210, -270, -60, -90])
    assert moving["photo"]["roll"] < 0 and moving["next"]["roll"] == 0  # the next card has not started yet
    assert (held["about"]["height"], second["about"]["height"]) == pytest.approx((234, 122))
    assert [second[n]["opacity"] for n in ("upcoming", "next", "route", "arrow")] == [1] * 4
    assert [last[n]["opacity"] for n in ("upcoming", "next", "route", "arrow")] == [0] * 4


def test_a_single_screen_has_no_arrow(tmp_path):
    screens = two_screens(tmp_path)[:1]
    assert 'class="arrow"' not in ot.page_html(screens, mine(), {"title": "T", "kicker": ""}, (640, 360))
    only = _shown(screens, (0.0,))[0]
    assert [only[n]["opacity"] for n in ("upcoming", "next", "route")] == [0] * 3


def test_a_stop_without_a_description_fades_its_box(tmp_path):
    one = two_screens(tmp_path)
    bare = one[0]._replace(description="")
    times = ot.frame_times(3, 30)
    shown = _shown([bare, one[0], bare], (0.0, times[75 + 40], times[-1]))
    assert [s["about"]["opacity"] for s in shown] == [0, 1, 0]
    assert [s["photo"]["opacity"] for s in shown] == [1, 1, 1]


def test_an_old_custom_style_gives_the_built_in_one(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVIVI_STYLES_DIR", str(tmp_path / "Styles"))
    (tmp_path / "Styles" / "outro").mkdir(parents=True)
    (tmp_path / "Styles" / "outro" / "default.html").write_text(
        '<div class="card">{{ -1 * pitch }}</div>', encoding="utf-8")
    html = ot.page_html(two_screens(tmp_path), mine(), {"title": "T", "kicker": ""}, (640, 360))
    assert 'class="boxes"' in html


def test_the_outro_storyboard_file_hides_stopbys_and_closed_places(project, monkeypatch, tmp_path):
    from services.vdoprocessing import storyboard

    assert storyboard.outro().include_stopby_waypoint is True and storyboard.outro().include_closed_waypoint is True
    boards = tmp_path / "boards"
    boards.mkdir()
    (boards / "outro.json").write_text(
        json.dumps({"include_stopby_waypoint": False, "include_closed_waypoint": "no"}), encoding="utf-8")
    monkeypatch.setattr(storyboard, "_DIR", boards)
    assert storyboard.outro().include_closed_waypoint is True  # only true or false counts

    config = json.loads((project / "job_config.json").read_text(encoding="utf-8"))
    config["waypoints"].insert(1, wp(34.05, "Shop", "s", isStopBy=True))
    (project / "job_config.json").write_text(json.dumps(config), encoding="utf-8")
    seen = []
    monkeypatch.setattr(
        ot, "write_themed_outro", lambda out, screens, *a: seen.extend(s.name for s in screens) or bool(out.write_bytes(b"t")))
    _render(project)
    assert seen == ["A", "B"]
