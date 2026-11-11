import pytest

from services.vdoprocessing.outrocard import scrapbook_layout


@pytest.mark.parametrize("count", [1, 5, 11, 20])
def test_cards_fit_the_frame_and_leave_the_stamp_its_own_corner(count):
    w, h = 1920, 1080
    card_w, cards, (sx, sy, sr) = scrapbook_layout(count, (w, h))
    assert len(cards) == count
    half = card_w * 0.75  # a tilted card is a little wider than itself
    for cx, cy, _ in cards:
        assert half * 0.6 < cx < w - half * 0.6 and half * 0.6 < cy < h - half * 0.6
        assert abs(cx - sx) > sr or abs(cy - sy) > sr  # no card under the stamp
    assert sy >= cards[-1][1] - card_w * 0.1  # the cell after the last card, in the bottom row
    # Rows snake: the step from one card to the next is never a jump back across the frame.
    assert all(abs(a[0] - b[0]) < w / 2 for a, b in zip(cards, cards[1:]))


def test_route_badges_and_project_colors():
    from services.vdoprocessing.outrocard import _project_colors, _route_badges

    wps = [{"label": "a"}, {"label": "side", "isStopBy": True}, {"label": "b"}, {"label": "c"}]
    assert [b for b, _ in _route_badges(wps)] == ["S", "1", "E"]  # an unconnected stop-by is not on the route
    assert _project_colors({"marker_color": [0, 0, 255], "line_color": [0, 200, 255]}) == {
        "marker": (255, 0, 0), "line": (255, 200, 0),  # settings are BGR
    }
    assert _project_colors({}) == {}


def test_scrapbook_title_is_an_editable_text_item_in_ink(tmp_path):
    import json

    from services import tuning
    from services.vdoprocessing.videopipeline.outro_step import outro_text_item

    cfg = tmp_path / "job_config.json"
    cfg.write_text(json.dumps({
        "project_name": "p", "video_title": "葛城修験", "video_subtitle": "葛城の道", "waypoints": [],
        "settings": {"enable_outro": True, "outro_style": "scrapbook", "outro_route_info": False},
    }, ensure_ascii=False), encoding="utf-8")
    item = outro_text_item(str(cfg))
    assert item["title"]["text"] == "葛城修験" and item["subtitle"]["text"] == "葛城の道"
    assert item["title"]["style"]["color"] == "#%02X%02X%02X" % tuning.OUTRO_SCRAPBOOK_INK
    assert "box" not in item


def test_a_long_name_never_breaks_inside_its_number():
    from PIL import Image, ImageDraw

    from services.mapfetcher.graphicengine.base import _GraphicsEngineBase as B
    from services.vdoprocessing.outrocard import _name_lines

    draw = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    assert _name_lines(draw, "葛城第二十三経塚", B.FONT_CANDIDATES_BOLD, 30, 20, 160)[0] == ["葛城", "第二十三経塚"]


def test_seal_takes_two_kanji_from_the_heading():
    from services.vdoprocessing.outrocard import seal_text

    assert seal_text("\u845b\u57ce\u4fee\u9a13") == "\u4fee\u9a13"
    assert seal_text("Kyoto walk") == "" and seal_text("") == ""
