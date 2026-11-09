"""Unit tests for services/localization/subtitle.py."""

import pytest

from services.localization.subtitle import (
    SpeakingTimelineMapper,
    SRTDocument,
    SubtitleBuilder,
    SubtitleCue,
    SubtitleStyle,
    TextSegmenter,
)


class TestSubtitleStyle:
    def test_to_force_style_contains_all_fields(self):
        style = SubtitleStyle()
        rendered = style.to_force_style()
        assert "FontName=Yu Gothic UI" in rendered
        assert "Alignment=2" in rendered
        assert "Bold=0" in rendered

    def test_bold_true_serializes_to_minus_one(self):
        style = SubtitleStyle(bold=True)
        assert "Bold=-1" in style.to_force_style()

    def test_default_alignment_is_bottom_center_old_ssa(self):
        # Old-SSA numbering (not ASS numpad) — see the docstring/HACK note.
        assert SubtitleStyle().alignment == 2


class TestSubtitleCue:
    def test_shifted_moves_start_and_end_only(self):
        cue = SubtitleCue(start=1.0, end=2.0, text="hello")
        shifted = cue.shifted(5.0)
        assert shifted.start == 6.0
        assert shifted.end == 7.0
        assert shifted.text == "hello"
        # original untouched (frozen dataclass)
        assert cue.start == 1.0


class TestTextSegmenter:
    def test_split_clauses_splits_on_japanese_punctuation(self):
        clauses = TextSegmenter.split_clauses("こんにちは。元気ですか？")
        assert clauses == ["こんにちは。", "元気ですか？"]

    def test_split_clauses_keeps_trailing_text_without_delimiter(self):
        clauses = TextSegmenter.split_clauses("Hello, world and more")
        assert clauses == ["Hello,", "world and more"]

    def test_split_clauses_breaks_at_sentence_ends_and_commas_not_in_numbers(self):
        assert TextSegmenter.split_clauses("約1,200年前、１，５００人が来た！？「すごい。」本当です") == [
            "約1,200年前、", "１，５００人が来た！？", "「すごい。」", "本当です",
        ]

    def test_split_clauses_empty_text_returns_empty_list(self):
        assert TextSegmenter.split_clauses("") == []
        assert TextSegmenter.split_clauses("   ") == []

    def test_split_clauses_no_delimiters_returns_whole_text(self):
        assert TextSegmenter.split_clauses("no punctuation here") == [
            "no punctuation here"
        ]

class TestSpeakingTimelineMapper:
    def test_no_pauses_single_speaking_interval(self):
        mapper = SpeakingTimelineMapper(total_duration=10.0, pauses=[])
        assert mapper.total_speaking_time == 10.0
        spans = mapper.allocate([5.0, 5.0])
        assert spans == [(0.0, 5.0), (5.0, 10.0)]

    def test_pause_in_middle_is_skipped_by_allocation(self):
        # 0-4 speaking, 4-6 silence, 6-10 speaking -> 8s total speaking time.
        mapper = SpeakingTimelineMapper(
            total_duration=10.0, pauses=[{"start": 4.0, "end": 6.0}]
        )
        assert mapper.total_speaking_time == 8.0
        spans = mapper.allocate([4.0, 4.0])
        # First clause consumes the whole first speaking interval (0-4).
        assert spans[0] == (0.0, 4.0)
        # Second clause must start after the pause, not inside it.
        assert spans[1][0] >= 6.0
        assert spans[1][1] == 10.0

    def test_pause_at_the_very_start(self):
        mapper = SpeakingTimelineMapper(
            total_duration=10.0, pauses=[{"start": 0.0, "end": 2.0}]
        )
        spans = mapper.allocate([8.0])
        assert spans[0][0] == 2.0
        assert spans[0][1] == 10.0

    def test_entirely_silent_clip_has_zero_speaking_time(self):
        mapper = SpeakingTimelineMapper(
            total_duration=5.0, pauses=[{"start": 0.0, "end": 5.0}]
        )
        assert mapper.total_speaking_time == 0.0

    def test_unsorted_pauses_get_sorted(self):
        mapper = SpeakingTimelineMapper(
            total_duration=10.0,
            pauses=[{"start": 6.0, "end": 7.0}, {"start": 1.0, "end": 2.0}],
        )
        # Speaking intervals should be (0,1), (2,6), (7,10) in that order.
        assert mapper._speaking_intervals == [(0.0, 1.0), (2.0, 6.0), (7.0, 10.0)]


class TestSubtitleBuilder:
    def test_build_produces_one_cue_per_clause(self):
        cues = SubtitleBuilder.build(
            text="こんにちは。元気ですか？", duration_seconds=4.0, pauses=[]
        )
        assert len(cues) == 2
        assert cues[0].text == "こんにちは。"
        assert cues[0].start == 0.0
        assert cues[1].end == pytest.approx(4.0)

    def test_build_empty_text_returns_no_cues(self):
        assert SubtitleBuilder.build("", 5.0, []) == []

    def test_build_degenerate_zero_speaking_time_divides_evenly(self):
        cues = SubtitleBuilder.build(
            text="a. b.",
            duration_seconds=6.0,
            pauses=[{"start": 0.0, "end": 6.0}],
        )
        assert len(cues) == 2
        assert cues[0].start == 0.0
        assert cues[0].end == pytest.approx(3.0)
        assert cues[1].end == pytest.approx(6.0)

    def test_cues_start_where_the_voice_resumes_after_each_pause(self):
        # Short in-sentence pauses (7.0, 16.4) must not pull a cue early, which
        # character-proportional timing did by up to 2 s.
        pauses = [(2.2, 3.15), (5.1, 5.9), (7.0, 7.3), (8.05, 9.0), (11.35, 12.45),
                  (14.35, 15.35), (16.4, 16.6), (17.35, 18.45), (20.35, 21.5)]
        cues = SubtitleBuilder.build(
            "西念寺から北へ進みます。そのまま道なりに進みます。左に曲がって北西へ。鋭く右に曲がって東へ。"
            "左に曲がって北西へ。右に曲がって北東へ。そのまま道なりに進みます。左に曲がって北西へ。",
            23.0,
            [{"start": s, "end": e} for s, e in pauses],
        )
        assert [c.start for c in cues] == pytest.approx([0.0, 3.15, 5.9, 9.0, 12.45, 15.35, 18.45, 21.5])
        for a, b in zip(cues, cues[1:]):
            assert a.end == pytest.approx(b.start)

    def test_a_long_sentence_stays_one_cue_on_one_line(self):
        text = "自然豊かな風景の中で静かに佇む歴史ある約1,200年前の寺院です。次へ向かいます。"
        cues = SubtitleBuilder.build(text, 5.0, [])
        assert [c.text for c in cues] == ["自然豊かな風景の中で静かに佇む歴史ある約1,200年前の寺院です。", "次へ向かいます。"]
        assert cues[-1].end == pytest.approx(5.0)

    def test_build_cues_are_in_chronological_order(self):
        cues = SubtitleBuilder.build(
            text="一。二。三。", duration_seconds=9.0, pauses=[]
        )
        for a, b in zip(cues, cues[1:]):
            assert a.end <= b.start + 1e-6


class TestSRTDocument:
    def test_format_timestamp_basic(self):
        assert SRTDocument._format_timestamp(0.0) == "00:00:00,000"
        assert SRTDocument._format_timestamp(1.5) == "00:00:01,500"
        assert SRTDocument._format_timestamp(3661.234) == "01:01:01,234"

    def test_format_timestamp_negative_clamps_to_zero(self):
        assert SRTDocument._format_timestamp(-1.0) == "00:00:00,000"

    def test_to_string_produces_numbered_blocks(self):
        cues = [
            SubtitleCue(0.0, 1.0, "one"),
            SubtitleCue(1.0, 2.0, "two"),
        ]
        text = SRTDocument.to_string(cues)
        assert "1\n00:00:00,000 --> 00:00:01,000\none\n" in text
        assert "2\n00:00:01,000 --> 00:00:02,000\ntwo\n" in text

    def test_to_string_empty_cues_is_empty_string(self):
        assert SRTDocument.to_string([]) == ""

    def test_write_creates_parent_dirs_and_file(self, tmp_path):
        out_path = tmp_path / "nested" / "subs.srt"
        cues = [SubtitleCue(0.0, 1.0, "hi")]
        result = SRTDocument.write(cues, str(out_path))
        assert result == str(out_path)
        assert out_path.exists()
        assert "hi" in out_path.read_text(encoding="utf-8")


def test_bracket_tags_are_left_out_of_subtitles():
    from services.localization.subtitle import SubtitleBuilder

    cues = SubtitleBuilder.build("[明るく] 皆さん、[whispers]こんにちは！【笑】「三輪神社」です。", 6.0, [])
    text = "".join(c.text for c in cues)
    assert text == "皆さん、こんにちは！「三輪神社」です。"
