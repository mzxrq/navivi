"""Shared intro/caption TextStyle: parsing frontend values and ASS output."""

from services.localization import fonts
from services.localization.text_style import TextStyle, parse_color, wrap_line, wrap_text
from services.vdoprocessing import introclip
from services.vdoprocessing.vdoexporter import (
    EDITOR_SUBTITLE_STYLE,
    _subtitle_display_text,
    caption_subtitle_style,
    subtitle_band_px,
    write_caption_ass,
)

BASE = TextStyle(font_family="Meiryo", font_size=40)


class TestParseColor:
    def test_css_hex(self):
        assert parse_color("#ff8000") == ((255, 128, 0), None)
        assert parse_color("#f80") == ((255, 136, 0), None)

    def test_css_hex_with_alpha(self):
        rgb, alpha = parse_color("#00000080")
        assert rgb == (0, 0, 0)
        assert alpha == 128 / 255

    def test_ass_color_is_bgr(self):
        assert parse_color("&H000000FF") == ((255, 0, 0), 1.0)

    def test_rgb_list(self):
        assert parse_color([10, 20, 300]) == ((10, 20, 255), None)

    def test_garbage(self):
        assert parse_color("red") is None
        assert parse_color(None) is None


class TestMerged:
    def test_applies_valid_fields(self):
        s = BASE.merged({"font_family": "Noto Sans JP", "font_size": 55, "color": "#ffcc00", "italic": True})
        assert (s.font_family, s.font_size, s.color, s.italic) == ("Noto Sans JP", 55, (255, 204, 0), True)

    def test_ignores_bad_values(self):
        assert BASE.merged({"font_size": "big", "bold": "yes", "color": "nope"}) == BASE
        assert BASE.merged(None) == BASE

    def test_clamps(self):
        s = BASE.merged({"font_size": 9999, "opacity": 3})
        assert (s.font_size, s.opacity) == (300, 1.0)

    def test_font_name_cannot_break_out_of_tags(self):
        s = BASE.merged({"font_family": "Evil}{\\b1,Font"})
        assert s.font_family == "Evilb1Font"


def test_ass_tags_carry_every_field():
    tags = BASE.merged({"color": "#ff0000", "opacity": 0.5, "outline_width": 3, "letter_spacing": 2}).to_ass_tags()
    for part in (r"\fnMeiryo", r"\fs40", r"\c&H0000FF&", r"\alpha&H7F&", r"\bord3", r"\fsp2"):
        assert part in tags


def test_default_caption_style_matches_old_editor_look():
    s = EDITOR_SUBTITLE_STYLE
    assert (s.font_name, s.font_size, s.border_style, s.outline, s.margin_v) == ("Meiryo", 19, 3, 2.5, 20)
    assert s.outline_color == "&H66000000"
    assert s.primary_color == "&H00FFFFFF"


def test_caption_style_overrides_default():
    style = caption_subtitle_style({"color": "#FFFF00", "font_size": 54, "margin_v": 150}, check_font=False)
    assert style.primary_color == "&H0000FFFF"
    assert style.font_size == round(54 * 288 / 1080)
    assert style.margin_v == 40


def test_bigger_caption_reserves_a_taller_band():
    big = caption_subtitle_style({"font_size": 110, "margin_v": 120}, check_font=False)
    assert subtitle_band_px(1080, big) > subtitle_band_px(1080)


def test_missing_font_falls_back(monkeypatch):
    monkeypatch.setattr(fonts, "_index", lambda: {"meiryo": "Meiryo", "georgia": "Georgia"})
    assert BASE.merged({"font_family": "georgia"}).with_installed_font("Meiryo").font_family == "georgia"
    assert BASE.merged({"font_family": "Nope Sans"}).with_installed_font("Meiryo").font_family == "Meiryo"


def test_unknown_font_list_trusts_the_name(monkeypatch):
    monkeypatch.setattr(fonts, "_index", lambda: {})
    assert BASE.merged({"font_family": "Nope Sans"}).with_installed_font("Meiryo").font_family == "Nope Sans"


def test_intro_events_use_their_styles(tmp_path):
    path = introclip._write_title_ass(
        "Trip", "Day 1", 6.0, tmp_path,
        title_style=introclip.DEFAULT_TITLE_STYLE.merged({"font_family": "Georgia"}),
        subtitle_style=introclip.DEFAULT_SUBTITLE_STYLE.merged({"color": "#00ff00"}),
    )
    title_line, sub_line = [l for l in path.read_text(encoding="utf-8").splitlines() if l.startswith("Dialogue:")]
    assert r"\fnGeorgia" in title_line
    assert r"\c&H00FF00&" in sub_line


class TestWrap:
    def test_no_limit_or_short_line_is_untouched(self):
        assert wrap_line("京都の古い町並み", 0) == ["京都の古い町並み"]
        assert wrap_line("短い", 10) == ["短い"]

    def test_english_breaks_at_spaces(self):
        assert wrap_line("We walk through the old town toward the temple gate", 20) == [
            "We walk through", "the old town toward", "the temple gate"]

    def test_japanese_lines_are_balanced(self):
        lines = wrap_line("あ" * 20, 14)
        assert abs(len(lines[0]) - len(lines[1])) <= 1

    def test_japanese_breaks_at_a_phrase_end_near_the_middle(self):
        assert wrap_line("この寺は千年以上の歴史があり今も多くの人が訪れます", 14) == [
            "この寺は千年以上の歴史があり", "今も多くの人が訪れます"]
        assert wrap_line("昔の修験者たちが歩いた古い道に入っていきます", 20) == [
            "昔の修験者たちが歩いた", "古い道に入っていきます"]

    def test_prefers_breaking_after_a_comma(self):
        assert wrap_line("京都の古い町並みを歩いて、清水寺へ向かいます。", 14) == [
            "京都の古い町並みを歩いて、", "清水寺へ向かいます。"]

    def test_kinsoku_and_latin_words(self):
        assert wrap_line("「こんにちは」と言いました。", 6) == ["「こんにち", "は」と", "言いました。"]
        assert wrap_line("ここはBangkokの旧市街です", 8) == ["ここは", "Bangkokの", "旧市街です"]

    def test_keeps_existing_line_breaks(self):
        assert wrap_text("一行目\n二行目はとても長いです", 5) == "一行目\n二行目は\nとても\n長いです"


def test_display_text_wraps_then_trims_closing_marks():
    assert _subtitle_display_text("京都の古い町並みを歩いて、清水寺へ向かいます。", 14) == "京都の古い町並みを歩いて\n清水寺へ向かいます"


def test_position_sets_alignment_and_band():
    top = caption_subtitle_style({"position": "top"}, check_font=False)
    middle = caption_subtitle_style({"position": "middle"}, check_font=False)
    assert (top.alignment, middle.alignment, EDITOR_SUBTITLE_STYLE.alignment) == (6, 10, 2)
    assert subtitle_band_px(1080, top) == 0 == subtitle_band_px(1080, middle)
    assert caption_subtitle_style({"position": "sideways"}, check_font=False).alignment == 2


class TestCaptionAss:
    def _write(self, tmp_path, cues, shared=None, size=(1920, 1080)):
        text = write_caption_ass(cues, shared, size, tmp_path / "c.ass", check_font=False).read_text(encoding="utf-8")
        styles = [l for l in text.splitlines() if l.startswith("Style: S")]  # captions, not the text-track base
        events = [l for l in text.splitlines() if l.startswith("Dialogue:")]
        return text, styles, events

    def test_unstyled_cues_share_one_style(self, tmp_path):
        _, styles, events = self._write(tmp_path, [
            {"start": 0, "end": 1, "text": "一"}, {"start": 1, "end": 2, "text": "二"}])
        assert len(styles) == 1 and styles[0].startswith("Style: S0,Meiryo,71,")
        assert all(",S0,," in e for e in events)

    def test_a_cue_can_have_its_own_style(self, tmp_path):
        _, styles, events = self._write(tmp_path, [
            {"start": 0, "end": 1, "text": "一"},
            {"start": 1, "end": 2, "text": "二", "style": {"position": "top", "color": "#ff0000", "font_family": "Georgia"}}])
        assert len(styles) == 2
        assert styles[1].startswith("Style: S1,Georgia,71,&H000000FF,")
        assert ",8,60,60,75," in styles[1]  # top-centre, numpad numbering
        assert events[1].split(",")[3] == "S1"

    def test_shared_style_and_line_limit_apply(self, tmp_path):
        _, _, events = self._write(tmp_path, [{"start": 0, "end": 1, "text": "京都の古い町並みを歩いて、清水寺へ向かいます。"}],
                                   shared={"max_chars_per_line": 14})
        assert events[0].endswith(r",,京都の古い町並みを歩いて\N清水寺へ向かいます")

    def test_text_cannot_inject_override_tags(self, tmp_path):
        _, _, events = self._write(tmp_path, [{"start": 0, "end": 1, "text": r"a{\b1}b"}])
        assert events[0].endswith(",,a｛＼b1｝b")

    def test_play_res_follows_frame_aspect(self, tmp_path):
        text, _, _ = self._write(tmp_path, [{"start": 0, "end": 1, "text": "x"}], size=(1080, 1920))
        assert "PlayResX: 608\nPlayResY: 1080" in text
