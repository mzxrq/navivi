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
def test_the_finale_opens_fullscreen_only_when_the_scene_shrinks(shrink):
    from services.vdoprocessing.videopipeline import finale_step

    maps = [Image.new("RGB", (320, 180)) for _ in range(10)]
    extent = (0.0, 1000.0, 0.0, 1000.0)
    lat, lon = _at(500.0, 500.0)
    scene = finale_step._Scene(
        2, (320, 180), Image.new("RGB", (320, 180), (255, 0, 0)), None, None, maps, [(None, extent)] * 10,
        lat, lon, [], 1.0, 64, 36, shrink,
    )
    frames = list(finale_step._pull_back_frames(scene))
    held = int(tuning.FINALE_PHOTO_SECONDS * 2)
    assert len(frames) == held + 10
    photo = (frames[0][:, :, 0] == 255) & (frames[0][:, :, 1] == 0)
    assert photo.all() == shrink and photo.any()  # without the shrink, only the card by its pin
    assert all((f == frames[0]).all() for f in frames[:held])  # beat 1 is held still
    assert not frames[-1].any()  # the card is gone by the end of the pull-back


@pytest.mark.parametrize("narration, setting, shrink", [("", False, False), ("", True, True), ("A shrine.", False, True)])
def test_the_shrink_is_only_dropped_when_the_end_stop_has_no_narration(narration, setting, shrink):
    from services.vdoprocessing.videopipeline.finale_step import _shrinks

    assert _shrinks({"finale_shrink_without_voice": setting}, {"attractionNarration": narration}) is shrink


def test_switching_the_shrink_remakes_the_clip(tmp_path: Path):
    from services.vdoprocessing.videopipeline.finale_step import _clip_key

    keys = [_clip_key(tmp_path, {}, (1920, 1080), None, [], tmp_path / "end.jpg", shrink) for shrink in (True, False)]
    assert keys[0] != keys[1]


def test_the_finale_holds_the_walks_last_frame_then_fades_into_the_same_view():
    from services.vdoprocessing.videopipeline import finale_step

    maps = [Image.new("RGB", (320, 180)) for _ in range(10)]
    extent = (0.0, 1000.0, 0.0, 1000.0)
    lat, lon = _at(500.0, 500.0)
    walk = Image.new("RGB", (320, 180), (0, 0, 200))
    scene = finale_step._Scene(
        10, (320, 180), Image.new("RGB", (320, 180), (255, 0, 0)), None, None, maps, [(None, extent)] * 10,
        lat, lon, [], 1.0, 40, 30, False, handoff=walk, card_offset=(30.0, -50.0),
    )
    frames = list(finale_step._pull_back_frames(scene))
    held = int(tuning.FINALE_PHOTO_SECONDS * 10)
    fading = int(tuning.FINALE_HANDOFF_SECONDS * 10)
    assert len(frames) == held + fading + 10
    assert all((f == np.asarray(walk)).all() for f in frames[:held])
    assert 0 < frames[held][5, 5, 2] < 200  # the walk's overlays fading out
    first = frames[held + fading]
    assert tuple(first[55, 210]) == (255, 0, 0)  # the card where the walk left it: pin (160, 90) + offset
    assert not first[5, 5].any()


def test_the_finale_takes_the_end_view_of_the_walks_last_leg(tmp_path: Path):
    import json

    from services.vdoprocessing.videopipeline.finale_step import _leg_end

    route = tmp_path / "route"
    route.mkdir()
    for name in ("02_waypoint_02_a.mp4", "02_waypoint_10_b.mp4", "02_waypoint_10_b_cont2.mp4"):
        (route / name).write_bytes(b"x" * 4096)
    view = {"lon": 135.0, "lat": 34.0, "zoom": 16.0, "pitch": 0.0, "card": {"box": [1, 2, 3, 4]}}
    (route / "02_waypoint_02_endview.json").write_text(json.dumps(view), encoding="utf-8")
    assert _leg_end(tmp_path) is None  # an earlier leg's view is not the end
    (route / "02_waypoint_10_endview.json").write_text(json.dumps(view), encoding="utf-8")
    assert _leg_end(tmp_path) == (view, route / "02_waypoint_10_b_cont2.mp4")


def test_the_rendered_finale_starts_on_the_walks_last_frame(tmp_path: Path, monkeypatch):
    import json

    from services.mapfetcher import pydeck_overview
    from services.projectfiles import gps_data_dir
    from services.vdoprocessing import outrocard, storyboard
    from services.vdoprocessing.videopipeline import finale_step
    from services.vdoprocessing.videopipeline.helpers import project_video_dir

    asked, frames = {}, []

    def capture(*args, **kwargs):
        asked.update(kwargs)
        return [(np.zeros((1080, 1920, 3), np.uint8), (15027000.0, 15030000.0, 4050000.0, 4052000.0))] * 3

    def pipe(drawn, part, fps, size):
        frames.append(next(iter(drawn)))
        Path(part).write_bytes(b"mp4")
        return True

    board = storyboard.finale({})
    monkeypatch.setattr(storyboard, "finale", lambda settings=None: board.__class__(
        **{**board.__dict__, "shrink_without_voice": False}))
    monkeypatch.setattr(pydeck_overview, "capture_pydeck_zoom_sequence", capture)
    monkeypatch.setattr(outrocard, "_pipe_frames", pipe)
    monkeypatch.setattr(finale_step, "_last_frame", lambda clip, size: Image.new("RGB", size, (0, 0, 200)))
    Image.new("RGB", (64, 48)).save(tmp_path / "end.jpg")
    d = gps_data_dir(tmp_path)
    d.mkdir(parents=True)
    (d / "gpsdata.csv").write_text("latitude,longitude\n34.1,135.2\n34.2,135.3\n", encoding="utf-8")
    route = Path(project_video_dir(tmp_path)) / "route"
    route.mkdir(parents=True, exist_ok=True)
    (route / "02_waypoint_02_b.mp4").write_bytes(b"x" * 4096)
    view = {"lon": 135.3, "lat": 34.2, "zoom": 16.0, "pitch": 0.0, "card": {"box": [800, 300, 380, 214]}}
    (route / "02_waypoint_02_endview.json").write_text(json.dumps(view), encoding="utf-8")
    cfg = tmp_path / "job_config.json"
    end = {"lat": 34.2, "lng": 135.3, "popup_image": str(tmp_path / "end.jpg"), "attractionNarration": ""}
    cfg.write_text(json.dumps({"settings": {}, "waypoints": [{"lat": 34.1, "lng": 135.2}, end]}), encoding="utf-8")

    assert finale_step.render_finale_clip(str(cfg), force=True)
    assert asked["end_view"] == (135.3, 34.2, 16.0) and asked["map_style"].endswith("outdoors-v12")
    assert tuple(frames[0][5, 5]) == (0, 0, 200)


def test_a_zoom_push_can_end_exactly_on_a_given_view(monkeypatch):
    from services.mapfetcher import pydeck_overview

    shot = []
    monkeypatch.setattr(pydeck_overview, "_capture_zoom_raw", lambda base, size, views, *a: shot.extend(views) or [])
    pydeck_overview.capture_pydeck_zoom_sequence(
        {"min_lat": 34.0, "max_lat": 34.1, "min_lon": 135.0, "max_lon": 135.2}, (1920, 1080), 34.02, 135.03, 5,
        route_latlon=[(34.0, 135.0), (34.1, 135.2)], end_view=(135.031, 34.021, 16.0),
    )
    assert shot[-1] == pytest.approx((135.031, 34.021, 16.0))


def test_a_loops_end_pin_is_on_the_map_from_the_first_frame(tmp_path: Path):
    from services.vdoprocessing.videopipeline.finale_step import _finale_stops

    route = [(34.0, 135.0), (34.1, 135.1), (34.0, 135.00001)]
    home = {"lat": 34.0, "lng": 135.0}
    stops = _finale_stops([("S", home), ("E", home)], route, tmp_path, {})
    assert [s["at"] for s in stops] == [0, 2]


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
