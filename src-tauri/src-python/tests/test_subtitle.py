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

    def test_wrap_short_text_returns_single_line_unwrapped(self):
        # Regression: the old behavior force-wrapped even short-ish clauses.
        text = "a" * 24
        assert TextSegmenter.wrap(text, max_chars_per_line=24) == text

    def test_wrap_long_text_breaks_at_space_not_mid_word(self):
        text = "a" * 10 + " " + "b" * 10
        wrapped = TextSegmenter.wrap(text, max_chars_per_line=12, max_lines=2)
        lines = wrapped.split("\n")
        assert lines[0] == "a" * 10
        assert lines[1] == "b" * 10

    def test_wrap_no_natural_break_falls_back_to_hard_cut(self):
        # Japanese-style text has no spaces at all.
        text = "あ" * 30
        wrapped = TextSegmenter.wrap(text, max_chars_per_line=10, max_lines=2)
        lines = wrapped.split("\n")
        assert len(lines) == 2
        assert lines[0] == "あ" * 10

    def test_wrap_overflow_past_max_lines_truncates_with_ellipsis(self):
        text = " ".join(["word"] * 20)
        wrapped = TextSegmenter.wrap(text, max_chars_per_line=8, max_lines=2)
        lines = wrapped.split("\n")
        assert len(lines) == 2
        assert lines[-1].endswith("…")

    def test_wrap_empty_text_returns_empty(self):
        assert TextSegmenter.wrap("") == ""


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
