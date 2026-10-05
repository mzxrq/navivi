from dataclasses import replace

from services.localization import caption_box
from services.localization.text_style import TextStyle
from services.vdoprocessing.vdoexporter import DEFAULT_CAPTION_STYLE, write_caption_ass


def _flat_measure(monkeypatch, per_char=40.0):
    monkeypatch.setattr(caption_box, "measure_line", lambda style, text: per_char * len(text))


def test_radius_is_clamped_and_optional():
    base = TextStyle(font_family="Arial", font_size=40)
    assert base.background_radius == 0.0
    assert base.merged({"background_radius": 30}).background_radius == 30
    assert base.merged({"background_radius": 9999}).background_radius == 100
    assert base.merged({"background_radius": "x"}).background_radius == 0.0


def test_box_has_a_rounded_rect_per_line_and_sits_at_the_bottom(monkeypatch):
    _flat_measure(monkeypatch)
    style = replace(DEFAULT_CAPTION_STYLE, background_radius=20, font_size=60, margin_v=50)
    box = caption_box.build_box(style, ["abcd", "ab"], 1920)
    assert box is not None
    assert box.drawing.count("m ") == 2
    assert (box.x, box.y) == (960, 1080 - 50 - 120)


def test_radius_never_exceeds_half_the_box(monkeypatch):
    _flat_measure(monkeypatch)
    style = replace(DEFAULT_CAPTION_STYLE, background_radius=100, font_size=40)
    drawing = caption_box.build_box(style, ["a"], 1920).drawing
    assert "b " in drawing
    # one-line box is ~ 40 + 2*pad_y tall, so r <= half of that: the first move is x0 + r
    height = 40 + 2 * max(style.outline_width, 9.0) * 0.3
    first_x = float(drawing.split()[1])
    x0 = 960 - (40 / 2 + max(style.outline_width, 9.0))
    assert abs((first_x - x0) - height / 2) < 0.2


def test_unmeasurable_font_falls_back_to_the_square_box(monkeypatch, tmp_path):
    monkeypatch.setattr(caption_box, "measure_line", lambda style, text: None)
    cues = [{"start": 0, "end": 2, "text": "hello", "style": {"background_radius": 25}}]
    ass = write_caption_ass(cues, None, (1920, 1080), tmp_path / "c.ass", check_font=False).read_text(encoding="utf-8")
    assert r"\p1" not in ass
    assert ",3,9.375,0," in ass  # BorderStyle 3 box


def test_rounded_caption_draws_the_box_under_bare_text(monkeypatch, tmp_path):
    _flat_measure(monkeypatch)
    cues = [{"start": 0, "end": 2, "text": "hello", "style": {"background_radius": 25}}]
    ass = write_caption_ass(cues, None, (1920, 1080), tmp_path / "c.ass", check_font=False).read_text(encoding="utf-8")
    events = [l for l in ass.splitlines() if l.startswith("Dialogue")]
    assert events[0].startswith("Dialogue: 0,") and r"\p1" in events[0]
    assert events[1].startswith("Dialogue: 1,") and events[1].endswith("hello")
    assert ",1,0,0,2," in ass  # bare text style: BorderStyle 1, no outline or shadow
