"""The themed place-name card on attraction clips: drawn onto the timeline's place item, laid over at export."""

import json
import subprocess
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from services.hudtheme import clip_card, layout

WAYPOINTS = [
    {"label": "駅", "lat": 34.0, "lng": 135.0},
    {"label": "神社", "lat": 34.01, "lng": 135.0},
    {"label": "閉鎖", "lat": 34.02, "lng": 135.0, "isStopBy": True, "inaccessible": True},
    {"label": "港", "lat": 34.03, "lng": 135.0},
]


def _hud(project, **more):
    (project / layout.FILE_NAME).write_text(json.dumps({"theme": "mine", **more}), encoding="utf-8")


def test_the_card_wears_the_stops_pin_number():
    assert [clip_card.stop_glyph(WAYPOINTS, i) for i in range(4)] == ["S", "1", "×", "E"]
    assert clip_card.stop_glyph(WAYPOINTS, 9) == ""


def test_a_classic_project_gets_no_card(tmp_path):
    assert clip_card.place_picture(tmp_path, "神社", "1", (1920, 1080)) is None


def test_a_hidden_card_is_said_to_be_hidden(tmp_path):
    _hud(tmp_path, layout={"place": {"show": False}})

    assert clip_card.place_picture(tmp_path, "神社", "1", (1920, 1080)) == {}


def test_the_card_is_drawn_into_the_project_and_placed_by_the_layout(tmp_path):
    pytest.importorskip("playwright")
    _hud(tmp_path)

    left = clip_card.place_picture(tmp_path, "加太春日神社", "1", (1920, 1080))
    _hud(tmp_path, layout={"place": {"anchor": "bottom-right", "scale": 1.5}})
    right = clip_card.place_picture(tmp_path, "加太春日神社", "1", (1920, 1080))

    picture = cv2.imread(str(tmp_path / left["path"]), cv2.IMREAD_UNCHANGED)
    assert left["path"].startswith(".navivi/hud/") and left["text"] == "加太春日神社"
    assert picture.shape == (left["height"], left["width"], 4)  # kept see-through round the card
    # Near the corner: the picture's own margin (for the card's shadow) may hang off the frame.
    assert -50 < left["x"] < 40 and -50 < left["y"] < 40 and left["width"] > 300
    assert right["x"] > 960 and right["y"] > 540 and right["width"] > left["width"] * 1.3
    assert right["path"] != left["path"] and (tmp_path / right["path"]).is_file()


def _items(project, monkeypatch, drawn):
    from services.vdoprocessing.videopipeline.timeline_step import _TrackBuilder

    clip = project / "04_attraction_01_神社.mp4"
    clip.write_bytes(b"")
    clip.with_suffix(".label.json").write_text(json.dumps({"text": "神社", "burned": False}), encoding="utf-8")
    asked = []
    monkeypatch.setattr(clip_card, "place_picture",
                        lambda *a: asked.append(a) or (drawn if drawn is None else dict(drawn)))
    builder = SimpleNamespace(project_dir=str(project), run_waypoints=WAYPOINTS, place_label_look=None,
                              photo_credit_look=None)
    return _TrackBuilder._attraction_text_items(builder, str(clip), clip.name, 6.0, None), asked


def test_the_place_item_carries_the_card(tmp_path, monkeypatch):
    items, asked = _items(tmp_path, monkeypatch, {"path": "a.png", "text": "神社"})

    assert items[0]["kind"] == "place" and items[0]["picture"] == {"path": "a.png", "text": "神社"}
    assert asked[0][1:3] == ("神社", "1")


@pytest.mark.parametrize("drawn, kinds", [(None, ["place"]), ({}, [])])
def test_without_a_theme_the_name_stays_text_and_a_hidden_card_removes_it(tmp_path, monkeypatch, drawn, kinds):
    items, _ = _items(tmp_path, monkeypatch, drawn)

    assert [i["kind"] for i in items] == kinds and all("picture" not in i for i in items)


def _text(title, picture_text, path="card.png"):
    return {"start": 0.5, "end": 1.5, "title": {"text": title}, "subtitle": {"text": ""},
            "picture": {"path": path, "x": 10, "y": 20, "width": 100, "height": 50, "text": picture_text}}


def test_a_renamed_item_is_drawn_as_text_again(tmp_path):
    from services.vdoprocessing.vdoexporter import split_card_texts

    (tmp_path / "card.png").write_bytes(b"x")
    kept, renamed, lost = (_text("神社", "神社", str(tmp_path / "card.png")),
                           _text("新しい名前", "神社", str(tmp_path / "card.png")),
                           _text("神社", "神社", str(tmp_path / "gone.png")))

    cards, texts = split_card_texts([kept, renamed, lost])

    assert [c["start"] for c in cards] == [0.5] and texts == [renamed, lost]


def _ffmpeg():
    from services.tts.ttsengine import FFmpegManager

    try:
        ffmpeg = FFmpegManager.resolve_ffmpeg_bin()
        subprocess.run([ffmpeg, "-version"], capture_output=True, check=True)
    except (OSError, RuntimeError, subprocess.CalledProcessError):
        pytest.skip("no ffmpeg")
    return ffmpeg


def _red_card(path):
    cv2.imwrite(str(path), np.dstack([np.zeros((50, 100, 2), np.uint8), np.full((50, 100), 255, np.uint8),
                                      np.full((50, 100), 255, np.uint8)]))  # opaque


def _pixel(video, frame_no, x, y):
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
    ok, frame = cap.read()
    cap.release()
    assert ok
    return frame[y, x].astype(int)


def test_cards_stay_when_the_joined_clips_are_tagged_with_different_colours(tmp_path):
    """Clips from different makers carry different colour tags; ffmpeg restarts its filters where they change."""
    from services.vdoprocessing.vdoexporter import VideoExporter, write_caption_ass

    ffmpeg = _ffmpeg()
    parts = []
    for name, tags in (("a", []), ("b", ["-color_range", "tv", "-colorspace", "bt470bg"]), ("c", [])):
        parts.append(tmp_path / f"{name}.mp4")
        subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=gray:s=960x540:d=1:r=10", "-pix_fmt", "yuv420p",
                        "-c:v", "libx264", *tags, str(parts[-1])], capture_output=True, check=True)
    (tmp_path / "list.txt").write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    video, out, card = tmp_path / "in.mp4", tmp_path / "out.mp4", tmp_path / "card.png"
    subprocess.run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(tmp_path / "list.txt"), "-c", "copy",
                    str(video)], capture_output=True, check=True)
    _red_card(card)
    items = [{**_text("神社", "神社", str(card)), "start": second + 0.2, "end": second + 0.8} for second in range(3)]
    ass = write_caption_ass([], None, (960, 540), tmp_path / "subs.ass", texts=[])

    VideoExporter.burn_subtitles(str(video), str(ass), str(out), pictures=items)

    for frame_no in (5, 15, 25):
        blue, green, red = _pixel(out, frame_no, 25, 22)
        assert red > 180 and green < 80, frame_no


def test_the_export_lays_the_card_over_the_picture_for_its_time_only(tmp_path):
    from services.vdoprocessing.vdoexporter import VideoExporter, write_caption_ass

    ffmpeg = _ffmpeg()
    video, out, card = tmp_path / "in.mp4", tmp_path / "out.mp4", tmp_path / "card.png"
    # Half of 1080p: the card's 1080-high numbers must be halved too.
    subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=gray:s=960x540:d=2:r=10", "-pix_fmt", "yuv420p",
                    str(video)], capture_output=True, check=True)
    cv2.imwrite(str(card), np.dstack([np.zeros((50, 100, 2), np.uint8), np.full((50, 100), 255, np.uint8),
                                      np.full((50, 100), 255, np.uint8)]))  # opaque red
    item = _text("神社", "神社", str(card))
    ass = write_caption_ass([], None, (960, 540), tmp_path / "subs.ass", texts=[])

    VideoExporter.burn_subtitles(str(video), str(ass), str(out), pictures=[item])

    def pixel(frame_no, x, y):
        cap = cv2.VideoCapture(str(out))
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
        ok, frame = cap.read()
        cap.release()
        assert ok
        return frame[y, x].astype(int)

    inside = (25, 22)  # card at (10, 20) 100x50 in 1080p -> (5, 10) 50x25 here
    assert pixel(10, *inside)[2] > 180 and pixel(10, *inside)[1] < 80
    assert abs(pixel(10, 80, 50)[2] - pixel(10, 80, 50)[1]) < 20  # outside the card: still grey
    for frame_no in (2, 18):
        assert abs(pixel(frame_no, *inside)[2] - pixel(frame_no, *inside)[1]) < 20
