import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from PIL import Image

from services import tuning


def _at(mx, my):
    """(lat, lon) of a point given in Web Mercator metres."""
    from services.mapfetcher.mapgeometry import EARTH_RADIUS_METERS, _inverse_mercator_y

    return _inverse_mercator_y(my), math.degrees(mx / EARTH_RADIUS_METERS)


def test_route_latlon_reads_the_gps_csv(tmp_path: Path):
    from services.projectfiles import gps_data_dir
    from services.vdoprocessing.videopipeline.finale_step import route_latlon

    assert route_latlon(tmp_path) == []
    d = gps_data_dir(tmp_path)
    d.mkdir(parents=True)
    (d / "gpsdata.csv").write_text("index,latitude,longitude\n1,34.1,135.2\n2,,\n3,34.2,135.3\n", encoding="utf-8")
    assert route_latlon(tmp_path) == [(34.1, 135.2), (34.2, 135.3)]


def test_finale_is_off_without_an_outro(tmp_path: Path):
    import json

    from services.vdoprocessing.videopipeline.finale_step import render_finale_clip

    cfg = tmp_path / "job_config.json"
    cfg.write_text(json.dumps({"settings": {"enable_outro": False}, "waypoints": []}), encoding="utf-8")
    assert render_finale_clip(str(cfg)) is None


def test_the_finale_plays_its_narration_from_its_timing_sidecar(tmp_path: Path, monkeypatch):
    import json

    from services import tuning
    from services.vdoprocessing.cliptiming import write_audio_offset
    from services.vdoprocessing.videopipeline import timeline_step
    from services.vdoprocessing.videopipeline.audio_step import FINALE_NARRATION_FILENAME
    from services.vdoprocessing.videopipeline.helpers import project_audio_dir

    monkeypatch.setattr(timeline_step, "_duration", lambda p: 10.0 if p else 0.0)
    (tmp_path / "job_config.json").write_text(json.dumps({"waypoints": []}), encoding="utf-8")
    video = tmp_path / "assets/video"
    video.mkdir(parents=True)
    finale, outro = video / tuning.FINALE_OUTPUT_FILENAME, video / tuning.OUTRO_OUTPUT_FILENAME
    for f in (finale, outro):
        f.write_bytes(b"x")
    voice = Path(project_audio_dir(tmp_path)) / FINALE_NARRATION_FILENAME
    voice.parent.mkdir(parents=True, exist_ok=True)
    voice.write_bytes(b"x")
    write_audio_offset(str(finale), 1.0)
    from services.vdoprocessing.videopipeline.helpers import project_subtitle_dir

    srt = Path(project_subtitle_dir(tmp_path)) / "98_finale_narration.srt"
    srt.parent.mkdir(parents=True, exist_ok=True)
    srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nThat was the whole route.\n", encoding="utf-8")

    path = timeline_step.build_timeline(
        video_paths=[], attraction_videos=[], final_videos=[str(finale), str(outro)], project_dir=str(tmp_path),
    )
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    tracks = data["video_tracks"]
    assert [(c["start"], c["text"]) for c in data["subtitles"]] == [(1.0, "That was the whole route.")]
    assert tracks[0]["audio_path"] and Path(tracks[0]["audio_path"]).name == FINALE_NARRATION_FILENAME
    assert tracks[0]["audio_offset"] == 1.0
    assert not tracks[0].get("fade_into_next_seconds")  # cuts to the outro


def test_an_unchanged_finale_is_reused_not_captured_again(tmp_path: Path, monkeypatch):
    import json

    import numpy as np
    from PIL import Image

    from services.mapfetcher import pydeck_overview
    from services.projectfiles import gps_data_dir
    from services.vdoprocessing import outrocard
    from services.vdoprocessing.videopipeline.finale_step import render_finale_clip

    captures = []

    def capture(*args, **kwargs):
        captures.append(1)
        return [(np.zeros((1080, 1920, 3), np.uint8), (135.0, 34.0, 136.0, 35.0))] * 2

    def pipe(frames, part, fps, size):
        Path(part).parent.mkdir(parents=True, exist_ok=True)
        Path(part).write_bytes(b"mp4")
        return True

    monkeypatch.setattr(pydeck_overview, "capture_pydeck_zoom_sequence", capture)
    monkeypatch.setattr(outrocard, "_pipe_frames", pipe)
    Image.new("RGB", (64, 48)).save(tmp_path / "end.jpg")
    d = gps_data_dir(tmp_path)
    d.mkdir(parents=True)
    (d / "gpsdata.csv").write_text("latitude,longitude\n34.1,135.2\n34.2,135.3\n", encoding="utf-8")
    cfg = tmp_path / "job_config.json"
    stops = [{"lat": 34.1, "lng": 135.2}, {"lat": 34.2, "lng": 135.3, "popup_image": str(tmp_path / "end.jpg")}]
    cfg.write_text(json.dumps({"settings": {}, "waypoints": stops}), encoding="utf-8")

    first = render_finale_clip(str(cfg))
    assert first and render_finale_clip(str(cfg)) == first
    assert len(captures) == 1
    render_finale_clip(str(cfg), force=True)
    assert len(captures) == 2


def test_the_finale_lays_out_every_stops_badge_with_no_leader_lines():
    from services.mapfetcher.graphicengine import GraphicsEngine
    from services.vdoprocessing.videopipeline.finale_step import _recap_badges

    extent = (0.0, 1000.0, 0.0, 1000.0)  # Web Mercator metres: a stop at (y, x) metres lands mid-frame
    from services.mapfetcher.mapgeometry import _inverse_mercator_y, EARTH_RADIUS_METERS
    import math

    def at(mx, my):
        return _inverse_mercator_y(my), math.degrees(mx / EARTH_RADIUS_METERS)

    stops = []
    for i, (badge, mx) in enumerate([("S", 200.0), ("1", 400.0), ("2", 600.0), ("E", 800.0)]):
        lat, lon = at(mx, 500.0)
        stops.append({"lat": lat, "lon": lon, "index": i, "order": i, "badge": badge, "name": f"P{i}",
                      "photo": tmp_path_photo(), "color": (0, 160, 0), "at": i})
    badges = _recap_badges(GraphicsEngine(), stops, extent, (1920, 1080), [], None)
    assert len(badges) == 4
    assert all(b.get("suppress_leader_line") for b in badges)

    # A return to stop 1 and a loop's E back at S: same places, so no second badge for either.
    back_to_1 = dict(stops[1], badge="1", index=4, name="P1 (back)")
    end_at_start = dict(stops[0], badge="E", index=5, name="P0 (back)")
    again = _recap_badges(GraphicsEngine(), stops[:3] + [back_to_1, end_at_start], extent, (1920, 1080), [], None)
    assert sorted(b["label"] for b in again) == ["P0", "P1", "P2"]


def tmp_path_photo():
    return "photo.jpg"  # only its presence matters to the layout


def test_the_finale_storyboard_reads_its_file_and_a_project_setting_wins(tmp_path: Path, monkeypatch):
    from services.vdoprocessing import storyboard
    from services.vdoprocessing.storyboard import finale

    monkeypatch.setattr(storyboard, "_DIR", tmp_path)  # the real file is the user's to edit
    (tmp_path / "finale.json").write_text(
        '{"name": "finale", "pin_shape": "teardrop", "card_style": "pill", "shrink_without_voice": true}',
        encoding="utf-8")
    board = finale({})
    assert (board.pin_shape, board.card_style, board.shrink_without_voice) == ("teardrop", "pill", True)
    board = finale({"finale_pin_shape": "dot", "finale_card_style": "popup", "finale_shrink_without_voice": False})
    assert (board.pin_shape, board.card_style, board.shrink_without_voice) == ("dot", "popup", False)
    board = finale({"finale_pin_shape": "star", "finale_card_style": None, "finale_shrink_without_voice": 0})
    assert (board.pin_shape, board.card_style, board.shrink_without_voice) == ("teardrop", "pill", True)


def test_editing_the_finale_storyboard_file_remakes_the_clip(tmp_path: Path, monkeypatch):
    from services.vdoprocessing import storyboard
    from services.vdoprocessing.videopipeline.finale_step import _clip_key

    monkeypatch.setattr(storyboard, "_DIR", tmp_path)
    keys = []
    for shape in ("teardrop", "dot"):
        (tmp_path / "finale.json").write_text(f'{{"pin_shape": "{shape}"}}', encoding="utf-8")
        keys.append(_clip_key(tmp_path, {}, (1920, 1080), None, [], tmp_path / "end.jpg"))
    assert keys[0] != keys[1]


@pytest.mark.parametrize("shape, teardrops", [("teardrop", 1), ("dot", 0)])
def test_the_finale_map_draws_the_storyboards_pin(shape, teardrops):
    from services.mapfetcher.graphicengine import GraphicsEngine
    from services.vdoprocessing.videopipeline.finale_step import _map_frame

    engine = GraphicsEngine()
    engine.draw_marker = MagicMock()
    extent = (0.0, 1000.0, 0.0, 1000.0)
    lat, lon = _at(500.0, 500.0)
    stop = {"lat": lat, "lon": lon, "at": 1, "badge": "1", "color": (200, 10, 20)}
    frame = np.zeros((1080, 1920, 3), np.uint8)
    out = np.asarray(_map_frame(engine, frame, extent, [_at(100.0, 100.0), (lat, lon)], [stop], (0, 255, 0), 6, 1.0,
                                pin_shape=shape))
    assert engine.draw_marker.call_count == teardrops
    assert bool((out == (200, 10, 20)).all(axis=2).any()) == (shape == "dot")  # the dot is in the stop's color


def test_the_finale_can_lay_the_stops_out_as_pop_up_cards():
    from services.mapfetcher.graphicengine import GraphicsEngine
    from services.vdoprocessing.videopipeline.finale_step import _recap_badges

    stops = []
    for i, (badge, mx) in enumerate([("S", 200.0), ("1", 500.0), ("E", 800.0)]):
        lat, lon = _at(mx, 500.0)
        stops.append({"lat": lat, "lon": lon, "index": i, "order": i, "badge": badge, "name": f"P{i}",
                      "photo": tmp_path_photo(), "color": (0, 160, 0), "at": i})
    cards = _recap_badges(GraphicsEngine(), stops, (0.0, 1000.0, 0.0, 1000.0), (1920, 1080), [], None,
                          card_style="popup")
    assert sorted(c["label"] for c in cards) == ["P0", "P1", "P2"]
    assert all(c["beside_box"] and c["leader_straight"] and not c.get("is_pill_badge") for c in cards)
    # As the overview recap's: small cards close to their pins, each leader in its pin's own color.
    assert all(c["card_scale"] <= tuning.FINALE_POPUP_CARD_SCALE for c in cards)
    assert not any("recap_line_color" in c for c in cards)


@pytest.mark.parametrize("shrink", [True, False])
def test_the_finale_photo_shrinks_only_when_the_scene_says_so(shrink):
    from services.vdoprocessing.videopipeline import finale_step

    maps = [Image.new("RGB", (320, 180)) for _ in range(10)]
    extent = (0.0, 1000.0, 0.0, 1000.0)
    lat, lon = _at(500.0, 500.0)
    scene = finale_step._Scene(
        2, (320, 180), Image.new("RGB", (320, 180), (255, 0, 0)), None, None, maps, [(None, extent)] * 10,
        lat, lon, [], 1.0, 64, 36, shrink,
    )
    after_photo = list(finale_step._pull_back_frames(scene))[int(tuning.FINALE_PHOTO_SECONDS * 2):]
    assert len(after_photo) == 10
    assert bool(after_photo[0].any()) == shrink  # without the shrink, the plain map cuts straight in


@pytest.mark.parametrize("voice, setting, shrink", [(None, False, False), (None, True, True), ("wav", False, True)])
def test_the_shrink_is_only_dropped_without_narration(voice, setting, shrink):
    from services.vdoprocessing.videopipeline.finale_step import _shrinks

    assert _shrinks({"finale_shrink_without_voice": setting}, voice) is shrink


def test_the_finales_pins_stay_on_top_of_the_leader_lines():
    from services.mapfetcher.graphicengine import GraphicsEngine
    from services.vdoprocessing.videopipeline import finale_step

    engine = GraphicsEngine()
    extent = (0.0, 1920.0, 0.0, 1080.0)
    lat, lon = _at(960.0, 300.0)  # pin tip at (960, 780)
    stops = [{"lat": lat, "lon": lon, "badge": "1", "color": (0, 80, 200)}]
    blank = np.full((1080, 1920, 3), 200, np.uint8)
    pinned = blank.copy()
    finale_step._draw_stop_pins(engine, pinned, extent, stops, "teardrop")
    base = Image.fromarray(pinned[:, :, ::-1].copy())
    card = {"x": 960.0, "y": 780.0, "label": "P", "border_color": (0, 0, 255), "leader_straight": True,
            "beside_box": (900, 300), "card_scale": 0.55, "data": {"popup_image": __file__}}
    over = lambda frame: finale_step._draw_stop_pins(engine, frame, extent, stops, "teardrop")

    # The pin's own solid pixels, along the column the leader climbs (the card ends well above them).
    column = (slice(700, 776), slice(958, 963))
    wanted = np.asarray(base)[column].astype(int)
    solid = np.abs(wanted - 200).max(axis=2) > 60
    changed = lambda out: (np.abs(np.asarray(out)[column].astype(int) - wanted).max(axis=2) > 40)[solid].mean()

    assert solid.sum() > 50
    assert changed(finale_step._with_badges(base, engine, [card], [1.0])) > 0.3  # the leader runs through the pin
    assert changed(finale_step._with_badges(base, engine, [card], [1.0], draw_pins=over)) < 0.05


def test_the_finale_hud_defaults_to_the_overviews_and_a_project_setting_wins(tmp_path: Path, monkeypatch):
    from services.vdoprocessing import storyboard

    monkeypatch.setattr(storyboard, "_DIR", tmp_path)
    (tmp_path / "finale.json").write_text("{}", encoding="utf-8")
    assert storyboard.finale({}).hud == "overview"
    assert storyboard.finale({"finale_hud": "summary"}).hud == "summary"


def _hud_inputs(tmp_path: Path, monkeypatch):
    """A loop S - 1 - E along one line, walked 1 km then 3 km by ferry; themed_panels' arguments are captured."""
    import json

    from services.localization import overview_script, route_brief
    from services.vdoprocessing.spatial_renderer import course_themed

    seen = []
    monkeypatch.setattr(course_themed, "themed_panels", lambda *args: seen.append(args) or "panels")
    legs = [{"mode": "walking", "km": 1.0}, {"mode": "ferry", "km": 3.0}]
    monkeypatch.setattr(route_brief, "load_brief", lambda path: {"legs": legs})
    monkeypatch.setattr(overview_script, "course_summary", lambda brief: {"total_distance_km": 4.0})
    (tmp_path / "job_config.json").write_text(
        json.dumps({"video_title": "Trip", "settings": {}, "waypoints": []}), encoding="utf-8")
    extent = (0.0, 1920.0, 0.0, 1080.0)
    route_px = np.array([[100.0, 500.0], [900.0, 500.0], [100.0, 500.0]])
    stops = []
    for badge, name, x in [("S", "Station", 100.0), ("1", "Pier", 900.0), ("+1", "Stone", 500.0),
                           ("E", "Station", 100.0)]:
        lat, lon = _at(x, 1080.0 - 500.0)
        stops.append({"badge": badge, "name": name, "lat": lat, "lon": lon})
    return seen, (tmp_path / "job_config.json", tmp_path, None, route_px, stops, extent, (1920, 1080))


def test_the_finale_builds_the_overview_hud_from_the_route(tmp_path: Path, monkeypatch):
    from services.vdoprocessing.videopipeline.finale_step import _overview_hud

    seen, args = _hud_inputs(tmp_path, monkeypatch)
    assert _overview_hud({}, *args) is None  # no hud.json: no themed furniture
    (tmp_path / "hud.json").write_text('{"theme": "mine"}', encoding="utf-8")
    assert _overview_hud({"finale_hud": "summary"}, *args) is None
    assert _overview_hud({"finale_hud": "overview"}, *args) == "panels"

    _, hud, w, h, summary, stops, cum, modes, loop = seen[0][:9]
    assert (hud["title"], w, h, summary["total_distance_km"], loop) == ("Trip", 1920, 1080, 4.0, True)
    assert [(g, n) for _, g, n in stops] == [("S", "Station"), ("1", "Pier"), ("E", "Station")]  # no stop-by
    assert stops[0][0] == 0 and abs(stops[1][0] - 800) < 10 and stops[2][0] == cum[-1]
    assert modes[len(modes) // 10] == "walking" and modes[-len(modes) // 10] == "ferry"


def test_the_finales_hold_shows_the_hud_over_the_map():
    from services.vdoprocessing.spatial_renderer.course_themed import _Placed
    from services.vdoprocessing.videopipeline import finale_step

    red = np.zeros((40, 60, 4), np.uint8)
    red[..., 2], red[..., 3] = 255, 255  # BGRA
    panels = SimpleNamespace(cards={"title": _Placed(red, (100.0, 100.0, 160.0, 140.0), 0.0)})
    maps = [Image.new("RGB", (320, 180))]
    scene = finale_step._Scene(10, (320, 180), maps[0], None, None, maps, [(None, None)], 0.0, 0.0, [], 1.0, 64, 36,
                               hud=panels)
    panels.cards["title"] = _Placed(red, (100.0, 100.0, 160.0, 140.0), 0.0)
    last = list(finale_step._hold_frames(scene))[-1]
    assert tuple(last[120, 130]) == (255, 0, 0)


@pytest.mark.parametrize("stopbys, closed, glyphs", [
    (False, False, ["S", "1", "E"]),
    (True, False, ["S", "+1", "+2", "1", "E"]),
    (False, True, ["S", "\u00d7", "1", "\u00d7", "E"]),
    (True, True, ["S", "+1", "\u00d7", "+2", "1", "\u00d7", "E"]),
])
def test_the_finale_lists_stopbys_and_closed_places_only_when_asked(stopbys, closed, glyphs):
    from services.vdoprocessing.videopipeline.finale_step import _finale_badges

    at = lambda i, **kw: {"lat": 34.0 + i / 100, "lng": 135.0, **kw}
    waypoints = [
        at(0), at(1, isStopBy=True, connectToRoute=True), at(2, isStopBy=True, inaccessible=True),
        at(3, isStopBy=True), at(4), at(5, inaccessible=True), at(6),
    ]
    settings = {"finale_include_stopby_waypoint": stopbys, "finale_include_closed_waypoint": closed}
    assert [badge for badge, _ in _finale_badges(waypoints, settings)] == glyphs


def test_the_finale_leaves_stopbys_and_closed_places_out_by_default(tmp_path: Path, monkeypatch):
    from services.vdoprocessing import storyboard

    monkeypatch.setattr(storyboard, "_DIR", tmp_path)
    (tmp_path / "finale.json").write_text("{}", encoding="utf-8")
    board = storyboard.finale({})
    assert (board.include_stopby_waypoint, board.include_closed_waypoint) == (False, False)
