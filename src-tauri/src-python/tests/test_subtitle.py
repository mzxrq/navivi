"""Unit tests for services/localization/subtitle.py."""

import pytest

from services.localization.subtitle import (
    MasterSubtitleAssembler,
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

    def test_split_clauses_empty_text_returns_empty_list(self):
        assert TextSegmenter.split_clauses("") == []
        assert TextSegmenter.split_clauses("   ") == []

    def test_split_clauses_no_delimiters_returns_whole_text(self):
        assert TextSegmenter.split_clauses("no punctuation here") == [
            "no punctuation here"
        ]

    def test_split_lines_short_text_stays_one_caption(self):
        text = "a" * 24
        assert TextSegmenter.split_lines(text, max_chars_per_line=24) == [text]

    def test_split_lines_breaks_at_space_not_mid_word(self):
        text = "a" * 10 + " " + "b" * 10
        assert TextSegmenter.split_lines(text, max_chars_per_line=12) == ["a" * 10, "b" * 10]

    def test_split_lines_no_natural_break_falls_back_to_hard_cut(self):
        assert TextSegmenter.split_lines("あ" * 30, max_chars_per_line=10) == ["あ" * 10] * 3

    def test_split_lines_never_starts_a_line_with_closing_punctuation(self):
        text = "曲がりくねった道を2時間21分ほど歩くと、"
        assert TextSegmenter.split_lines(text, max_chars_per_line=20) == [text]
        assert TextSegmenter.split_lines("「" + "あ" * 9 + "」です", max_chars_per_line=10)[1][0] != "」"

    def test_split_lines_balances_at_a_phrase_end(self):
        lines = TextSegmenter.split_lines("昔の修験者たちが歩いた古い道に入っていきます", max_chars_per_line=20)
        assert lines == ["昔の修験者たちが歩いた", "古い道に入っていきます"]

    def test_long_text_is_never_truncated(self):
        text = " ".join(["word"] * 20)
        assert " ".join(TextSegmenter.split_lines(text, max_chars_per_line=8)) == text

    def test_split_lines_empty_text_returns_nothing(self):
        assert TextSegmenter.split_lines("") == []


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

    def test_a_clause_too_long_for_one_line_becomes_consecutive_one_line_cues(self):
        cues = SubtitleBuilder.build("自然豊かな風景の中で静かに佇む歴史ある寺院です。", 5.0, [])
        assert [c.text for c in cues] == ["自然豊かな風景の中で静かに", "佇む歴史ある寺院です。"]
        assert all("\n" not in c.text for c in cues)
        assert cues[0].end == pytest.approx(cues[1].start)
        assert cues[-1].end == pytest.approx(5.0)

    def test_wrap_mode_keeps_two_lines_per_cue_and_never_truncates(self):
        cues = SubtitleBuilder.build("あ" * 50 + "。", 6.0, [], max_chars_per_line=10, lines_per_caption=2)
        assert [c.text.count("\n") for c in cues] == [1, 1, 1]
        assert "".join(c.text.replace("\n", "") for c in cues) == "あ" * 50 + "。"

    def test_caption_layout_reads_project_settings(self):
        from services.localization.subtitle import caption_layout

        assert caption_layout(None) == {"max_chars_per_line": 20, "lines_per_caption": 1}
        settings = {"subtitle_long_lines": "wrap", "caption_style": {"max_chars_per_line": 16}}
        assert caption_layout(settings) == {"max_chars_per_line": 16, "lines_per_caption": 2}

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


class TestMasterSubtitleAssembler:
    def test_assemble_shifts_each_segment_by_its_offset(self):
        seg1 = [SubtitleCue(0.0, 1.0, "a")]
        seg2 = [SubtitleCue(0.0, 1.0, "b")]
        master = MasterSubtitleAssembler.assemble([seg1, seg2], [0.0, 10.0])
        assert master[0].start == 0.0
        assert master[1].start == 10.0
        assert master[1].end == 11.0

    def test_assemble_mismatched_lengths_raises(self):
        with pytest.raises(ValueError):
            MasterSubtitleAssembler.assemble([[]], [0.0, 1.0])

    def test_assemble_empty_input_returns_empty(self):
        assert MasterSubtitleAssembler.assemble([], []) == []


def test_bracket_tags_are_left_out_of_subtitles():
    from services.localization.subtitle import SubtitleBuilder

    cues = SubtitleBuilder.build("[明るく] 皆さん、[whispers]こんにちは！【笑】「三輪神社」です。", 6.0, [])
    text = "".join(c.text for c in cues)
    assert text == "皆さん、こんにちは！「三輪神社」です。"
