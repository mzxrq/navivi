"""Text track: the intro's title + subtitle as a timeline item, burned at export."""

import json
from pathlib import Path

from services.vdoprocessing import introclip
from services.vdoprocessing.vdoexporter import write_caption_ass
from services.vdoprocessing.videopipeline import timeline_step
from services.vdoprocessing.videopipeline.intro_step import intro_text_item
from services.vdoprocessing.videopipeline.timeline_step import build_timeline
from services import tuning

ITEM = {"title": {"text": "Bangkok", "style": {"color": "#ffd166"}}, "subtitle": {"text": "A walking tour"}}
# Sizes the layout tests were worked out with, independent of the tuned defaults.
SIZED = {
    "title": {"text": "Bangkok", "style": {"color": "#ffd166", "font_size": 74}},
    "subtitle": {"text": "A walking tour", "style": {"font_size": 36}},
}


def _touch(p: Path) -> str:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    return str(p)


def _events(text: str):
    return [l for l in text.splitlines() if l.startswith("Dialogue:")]


def test_intro_text_spans_the_intro_clip(tmp_path, monkeypatch):
    lengths = {tuning.INTRO_OUTPUT_FILENAME: 9.0, "01_overview.mp4": 20.0}
    monkeypatch.setattr(timeline_step, "_duration", lambda p: lengths.get(Path(p).name, 0.0) if p else 0.0)
    (tmp_path / "job_config.json").write_text(json.dumps({"waypoints": []}), encoding="utf-8")
    route = tmp_path / "assets/video/route"
    intro = _touch(route / tuning.INTRO_OUTPUT_FILENAME)
    overview = _touch(route / "01_overview.mp4")

    path = build_timeline(
        video_paths=[intro, overview], attraction_videos=[], final_videos=[intro, overview],
        project_dir=str(tmp_path), intro_text=ITEM,
    )
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert data["video_tracks"][0]["texts"] == [{"start": 0.0, "end": 9.0, **ITEM}]
    assert "texts" not in data["video_tracks"][1]
    assert data["texts"] == [{"start": 0.0, "end": 9.0, **ITEM}]


def test_no_intro_text_without_an_intro(tmp_path):
    (tmp_path / "job_config.json").write_text(json.dumps({"waypoints": []}), encoding="utf-8")
    overview = _touch(tmp_path / "assets/video/route/01_overview.mp4")
    path = build_timeline(
        video_paths=[overview], attraction_videos=[], final_videos=[overview],
        project_dir=str(tmp_path), intro_text=ITEM,
    )
    assert json.loads(Path(path).read_text(encoding="utf-8"))["texts"] == []


def test_intro_text_item_reads_project_title_and_styles(tmp_path):
    config = tmp_path / "job_config.json"
    config.write_text(json.dumps({
        "project_name": "Trip", "video_title": "Old Town", "video_subtitle": "Day 1",
        "settings": {"intro_title_style": {"font_size": 90}},
    }), encoding="utf-8")
    assert intro_text_item(str(config)) == {
        "kind": "intro",
        "title": {"text": "Old Town", "style": {"font_size": 90}},
        "subtitle": {"text": "Day 1"},
    }


def test_intro_text_item_adds_location_and_place_count(tmp_path):
    config = tmp_path / "job_config.json"
    config.write_text(json.dumps({
        "video_title": "友ヶ島・加太をめぐる道", "video_subtitle": "葛城修験 ゆかりの地",
        "waypoints": [{"id": "s"}, {"id": "a"}, {"id": "b", "isStopBy": True}, {"id": "c", "isStopBy": True, "connectToRoute": True}],
        "settings": {"intro_location": "和歌山県 和歌山市"},
    }), encoding="utf-8")
    item = intro_text_item(str(config))
    assert item["kicker"] == {"text": "和歌山県 和歌山市"}
    assert item["subtitle"] == {"text": "葛城修験 ゆかりの地 · 3 か所"}


def test_place_count_can_be_turned_off(tmp_path):
    config = tmp_path / "job_config.json"
    config.write_text(json.dumps({
        "video_title": "T", "waypoints": [{"id": "a"}], "settings": {"intro_place_count": False},
    }), encoding="utf-8")
    item = intro_text_item(str(config))
    assert item["subtitle"] == {"text": ""} and "kicker" not in item


def test_kicker_burns_above_the_title(tmp_path):
    item = {"start": 0, "end": 4, **SIZED, "kicker": {"text": "和歌山県", "style": {"font_size": 30}}}
    text = write_caption_ass([], None, (1920, 1080), tmp_path / "t.ass", check_font=False, texts=[item]).read_text(encoding="utf-8")
    kicker, title, sub = _events(text)
    # Gap 0.6 * (30 + 74) = 62, block shifted down 31: kicker 540-21-31, title 540-21+31.
    assert r"\pos(960,488)" in kicker and kicker.endswith("}和歌山県") and r"\fad(500,500)" in kicker
    assert r"\pos(960,550)" in title


def test_text_items_burn_with_their_own_styles(tmp_path):
    text = write_caption_ass([], None, (1920, 1080), tmp_path / "t.ass", check_font=False,
                             texts=[{"start": 1.0, "end": 7.0, **ITEM}]).read_text(encoding="utf-8")
    title, sub = _events(text)
    assert title.startswith("Dialogue: 1,0:00:01.00,0:00:07.00,Text,")
    assert r"\pos(960," in title and r"\c&H66D1FF&" in title and title.endswith("}Bangkok")
    # The subtitle comes in after the title and leaves before it.
    assert sub.startswith("Dialogue: 1,0:00:01.80,0:00:06.20,Text,") and sub.endswith("}A walking tour")


def test_a_line_left_empty_is_not_drawn(tmp_path):
    item = {"start": 0, "end": 4, "title": {"text": ""}, "subtitle": {"text": "Only me"}}
    text = write_caption_ass([], None, (1920, 1080), tmp_path / "t.ass", check_font=False, texts=[item]).read_text(encoding="utf-8")
    (only,) = _events(text)
    assert only.startswith("Dialogue: 1,0:00:00.00,0:00:04.00,") and r"\pos(960,540)" not in only


def test_vertical_frames_centre_the_text(tmp_path):
    text = write_caption_ass([], None, (1080, 1920), tmp_path / "t.ass", check_font=False,
                             texts=[{"start": 0, "end": 4, **ITEM}]).read_text(encoding="utf-8")
    assert r"\pos(304," in _events(text)[0]


def test_title_events_keep_the_intro_animation():
    events = introclip.title_events(
        "T", "S", 0.0, 5.0, introclip.DEFAULT_TITLE_STYLE, introclip.DEFAULT_SUBTITLE_STYLE, 960, 540)
    (t0, t1, title), (s0, s1, sub) = events
    assert (t0, t1) == (0.0, 5.0) and (s0, s1) == (0.8, 4.2)
    assert r"\fad(1100,1100)" in title and r"\fscx65" in title
    assert r"\move(960," in sub


def test_text_block_defaults_to_the_centre():
    assert introclip.text_block_center_y("middle", 100, 74, 36, True, True) == 540
    assert introclip.text_block_center_y("nonsense", 100, 74, 36, True, True) == 540


def test_text_block_top_and_bottom_keep_their_distance_from_the_edge():
    # Two lines: the block is 1.1 * (74 + 36) = 121 px tall.
    assert introclip.text_block_center_y("bottom", 100, 74, 36, True, True) == 920
    assert introclip.text_block_center_y("top", 50, 74, 36, True, True) == 111
    # One line: half its own size.
    assert introclip.text_block_center_y("top", 0, 74, 36, True, False) == 37


def test_positioned_text_item_burns_at_its_place(tmp_path):
    item = {"start": 0, "end": 4, **SIZED, "position": "bottom", "margin_v": 100}
    text = write_caption_ass([], None, (1920, 1080), tmp_path / "t.ass", check_font=False, texts=[item]).read_text(encoding="utf-8")
    title, sub = _events(text)
    assert r"\pos(960,899)" in title  # 920 - int(36 * 0.6)
    assert r"\move(960,992,960,964," in sub  # 920 + int(74 * 0.6), rising 28 px


# --- Attraction place names on the text track ---------------------------------

from services.vdoprocessing.place_label import (  # noqa: E402
    DEFAULT_PLACE_LOOK,
    place_text_item,
    record_place_label,
    unburned_place_label,
)


def test_place_label_sidecar_round_trip(tmp_path):
    clip = tmp_path / "04_attraction_01_x.mp4"
    assert unburned_place_label(clip) is None  # an older clip: label burned in, no sidecar
    record_place_label(clip, "常行寺", burned=False)
    assert unburned_place_label(clip) == "常行寺"
    record_place_label(clip, "常行寺", burned=True)
    assert unburned_place_label(clip) is None
    record_place_label(clip, None, burned=False)
    assert not (tmp_path / "04_attraction_01_x.label.json").exists()


def test_place_item_uses_the_saved_look_over_the_default():
    item = place_text_item("常行寺", {"align": "right", "title_style": {"color": "#ff0000"}})
    assert item["kind"] == "place" and item["title"] == {"text": "常行寺", "style": {"color": "#ff0000"}}
    assert item["align"] == "right" and item["position"] == DEFAULT_PLACE_LOOK["position"]
    assert item["animation"] == "none" and item["subtitle"] == {"text": ""}


def test_only_unburned_attraction_clips_get_a_place_item(tmp_path, monkeypatch):
    monkeypatch.setattr(timeline_step, "_duration", lambda p: 5.0 if p else 0.0)
    (tmp_path / "job_config.json").write_text(json.dumps({"waypoints": [{"id": "a"}, {"id": "b"}]}), encoding="utf-8")
    attr = tmp_path / "assets/video/attraction"
    new = _touch(attr / "04_attraction_00_new.mp4")
    old = _touch(attr / "04_attraction_01_old.mp4")
    record_place_label(new, "加太駅", burned=False)

    path = build_timeline(video_paths=[], attraction_videos=[new, old], final_videos=[new, old], project_dir=str(tmp_path))
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    by_name = {Path(t["file_path"]).name: t for t in data["video_tracks"]}
    assert by_name["04_attraction_00_new.mp4"]["texts"][0]["title"]["text"] == "加太駅"
    assert "texts" not in by_name["04_attraction_01_old.mp4"]
    assert [x["kind"] for x in data["texts"]] == ["place"]


def test_left_aligned_still_label_burns_at_the_corner(tmp_path):
    item = {"start": 0, "end": 5, **place_text_item("常行寺")}
    text = write_caption_ass([], None, (1920, 1080), tmp_path / "t.ass", check_font=False, texts=[item]).read_text(encoding="utf-8")
    (only,) = _events(text)
    # Left edge 22 px in, block centre 10 + 98/2 = 59 px down; no fade or pop.
    assert r"{\an4\pos(22,59)" in only and r"\fad" not in only and r"\fscx" not in only
    assert only.endswith("}常行寺")


def test_fade_animation_fades_both_lines_together():
    events = introclip.title_events(
        "T", "S", 0.0, 4.0, introclip.DEFAULT_TITLE_STYLE, introclip.DEFAULT_SUBTITLE_STYLE, 960, 540,
        align="right", animation="fade")
    assert [(a, b) for a, b, _ in events] == [(0.0, 4.0), (0.0, 4.0)]
    assert all(r"\an6" in t and r"\fad(500,500)" in t and r"\fscx65" not in t for _, _, t in events)


# --- Per-line motion -----------------------------------------------------------


def _motion(title_motion=None, subtitle_motion=None, animation=None, end=6.0):
    return introclip.title_events(
        "T", "S", 0.0, end, introclip.DEFAULT_TITLE_STYLE, introclip.DEFAULT_SUBTITLE_STYLE, 960, 540,
        animation=animation, title_motion=title_motion, subtitle_motion=subtitle_motion)


def test_default_motion_is_the_intro():
    (t0, t1, title), (s0, s1, sub) = _motion()
    assert (t0, t1, s0, s1) == (0.0, 6.0, 0.8, 5.2)
    assert r"\fscx65" in title and r"\move(" in sub


def test_each_line_has_its_own_animation_and_delay():
    # Subtitle first (fades in at once), title pops 1.5 s later.
    (t0, t1, title), (s0, s1, sub) = _motion({"animation": "pop", "delay": 1.5}, {"animation": "fade", "delay": 0})
    assert (t0, t1) == (1.5, 4.5) and (s0, s1) == (0.0, 6.0)
    assert r"\fscx65" in title and r"\fad(500,500)" in sub and r"\move(" not in sub


def test_a_line_can_rise_or_stay_still():
    (_, _, title), (_, _, sub) = _motion({"animation": "rise"}, {"animation": "none"})
    assert r"\move(960," in title and r"\fad" not in sub and r"\pos(960," in sub


def test_item_wide_animation_is_the_fallback():
    (t0, _, title), (s0, _, sub) = _motion(animation="none")
    assert t0 == s0 == 0.0 and r"\fad" not in title and r"\fad" not in sub


def test_a_long_delay_still_leaves_the_line_on_screen():
    ((t0, t1, _), _) = _motion({"delay": 99})
    assert t1 - t0 >= 0.6 - 1e-9


def test_saved_place_look_carries_line_motion():
    item = place_text_item("x", {"title_animation": "fade", "title_delay": 0.3})
    assert item["title"]["animation"] == "fade" and item["title"]["delay"] == 0.3
