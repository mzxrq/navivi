from pathlib import Path

from services.vdoprocessing.photo_credit import credit_items, credit_text
from services.vdoprocessing.vdoexporter import write_caption_ass


def test_each_credited_photo_gets_its_share_of_the_clip_in_its_corner(tmp_path):
    wp = {"images": ["a.jpg", "b.jpg", "c.jpg"], "imageCredits": {
        "a.jpg": {"text": "Town office", "corner": "left"},
        "c.jpg": {"author": "Taro", "license": "CC BY 4.0", "url": "https://x"},
    }}
    items = credit_items(wp, 9.0)
    assert [(i["start"], i["end"], i["align"]) for i in items] == [(0.0, 3.0, "left"), (6.0, 9.0, "right")]
    assert items[1]["title"]["text"].endswith("Taro · CC BY 4.0")
    assert credit_items({**wp, "videos": ["v.mp4"]}, 9.0) == []  # the user's own footage
    assert credit_text({"text": "  ", "author": "", "license": ""}) == ""

    ass = Path(write_caption_ass([], None, (1920, 1080), tmp_path / "t.ass", texts=items)).read_text(encoding="utf-8")
    boxed = [line for line in ass.splitlines() if line.startswith("Dialogue") and ",TextBox," in line]
    assert len(boxed) == 2 and "Town office" in boxed[0] and "\\3a&H66&" in boxed[0]


def test_the_saved_look_sizes_every_credit_but_keeps_its_corner():
    look = {"margin_v": 48, "align": "center", "title_style": {"font_size": 40, "background_opacity": 0.8}}
    item = credit_items({"images": ["a.jpg"], "imageCredits": {"a.jpg": {"text": "Town", "corner": "left"}}}, 4.0, look)[0]
    assert item["align"] == "left" and item["margin_v"] == 48
    assert item["title"]["style"]["font_size"] == 40 and item["title"]["style"]["background"] is True

def test_credits_match_the_absolute_paths_the_pipeline_uses():
    wp = {"images": ["C:\\p\\assets\\image\\image (5).png", "C:\\p\\.navivi\\upscaled\\honden_x2.jpg"], "imageCredits": {
        "assets/image/image (5).png": {"text": "CC-04 Wikipedia", "corner": "left"},
        "assets/image/honden.jpg": {"text": "Shrine office"},
    }}
    items = credit_items(wp, 8.0)
    assert [(i["title"]["text"], i["align"]) for i in items] == [
        ("ⓘ CC-04 Wikipedia", "left"), ("ⓘ Shrine office", "right"),
    ]
