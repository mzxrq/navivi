"""
Subtitle Service (subtitle.py)
---------------------------------------------------------------------------
Builds sound-synchronized subtitle cues (.srt) from TTS narration text and
its already-computed pause/duration analysis (see tts.AudioProcessor).
Standalone, reusable — no dependency on VideoEditor/JobConfig/ComfyUI.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from services.logger.logger import setup_logger

# Logging configuration
logger = setup_logger("SubtitleService")

# Clause delimiters TTS engines (and human speech) naturally pause on.
_CLAUSE_DELIMITERS = re.compile(r"([、。！？!?,.])")


# [Config] Default subtitle style for libass/FFmpeg `force_style` override
@dataclass(frozen=True)
class SubtitleStyle:
    """
    Maps to libass's `force_style` override syntax for the FFmpeg
    `subtitles` filter. Color fields use ASS's native &HAABBGGRR hex format
    (note: BLUE-GREEN-RED order, NOT RGB — a common gotcha).

    Quick reference for common colors (AA=00 fully opaque, FF fully
    transparent):
      White:  &H00FFFFFF   Black:  &H00000000
      Yellow: &H0000FFFF   Red:    &H000000FF
    """

    font_name: str = "Yu Gothic UI"  # Windows-bundled, handles JP + Latin
    font_size: int = 14  # libass units, scales with video res
    primary_color: str = "&H00FFFFFF"  # caption fill (white)
    outline_color: str = "&H00000000"  # outline/border (black)
    back_color: str = "&H80000000"  # box background, only used if border_style=3
    bold: bool = False
    border_style: int = 1  # 1 = outline+shadow, 3 = opaque background box
    outline: float = 2.0  # outline thickness in px
    shadow: float = 0.5  # drop-shadow distance in px
    alignment: int = (
        2  # ASS numpad-style: 2=bottom-center, 5=middle-center, 8=top-center
    )
    margin_v: int = 10  # vertical margin from frame edge, px

    def to_force_style(self) -> str:
        """Serializes to the comma-separated key=value string libass expects."""
        bold_flag = -1 if self.bold else 0  # ASS uses -1 for True, 0 for False
        return (
            f"FontName={self.font_name},FontSize={self.font_size},"
            f"PrimaryColour={self.primary_color},OutlineColour={self.outline_color},"
            f"BackColour={self.back_color},Bold={bold_flag},BorderStyle={self.border_style},"
            f"Outline={self.outline},Shadow={self.shadow},Alignment={self.alignment},"
            f"MarginV={self.margin_v}"
        )


# [Core] SubtitleCue and SubtitleBuilder
@dataclass(frozen=True)
class SubtitleCue:
    """One timed subtitle line: [start, end) in seconds, plus display text."""

    start: float
    end: float
    text: str

    def shifted(self, offset_seconds: float) -> "SubtitleCue":
        """Returns a copy translated forward in time by `offset_seconds`."""
        return SubtitleCue(
            self.start + offset_seconds, self.end + offset_seconds, self.text
        )


# [Subtitle] TextSegmenter: splits raw narration text into display-sized subtitle chunks
class TextSegmenter:
    """Splits raw narration text into display-sized subtitle chunks."""

    @staticmethod
    def split_clauses(text: str) -> List[str]:
        text = text.strip()
        if not text:
            return []
        parts = _CLAUSE_DELIMITERS.split(text)
        clauses: List[str] = []
        buf = ""
        for part in parts:
            buf += part
            if _CLAUSE_DELIMITERS.fullmatch(part):
                clauses.append(buf.strip())
                buf = ""
        if buf.strip():
            clauses.append(buf.strip())
        return clauses or [text]

    @staticmethod
    def wrap(text: str, max_chars_per_line: int = 24, max_lines: int = 2) -> str:
        """
        PATCH: budget-aware wrapping instead of blind fixed-width chunking.

        OLD BEHAVIOR: every clause >max_chars_per_line got mechanically cut
        at that exact offset, so a 22-char clause with a 20-char budget
        always produced 2 lines even though it would read fine on one line
        at a slightly wider budget — and the cut point ignored word/phrase
        boundaries entirely.

        NEW BEHAVIOR:
          1. If the WHOLE clause fits in max_chars_per_line, return it as a
             single line — no forced wrapping, ever. This alone eliminates
             the vast majority of unnecessary 2-line captions, since most
             TTS clauses (already pre-split on 、。！？!? by split_clauses)
             are short.
          2. If it doesn't fit, find a natural break point (nearest space,
             scanning backward from the ideal midpoint) instead of cutting
             at a fixed character offset — avoids splitting mid-word.
          3. Still respects max_lines and still truncates with an ellipsis
             as an absolute last resort for pathologically long clauses.

        O(k) where k = len(text) — a single backward scan, negligible cost
        even at hundreds of calls per pipeline run.
        """
        text = text.strip()
        if not text:
            return text

        # Case 1: fits on one line — the common case, and the actual fix.
        if len(text) <= max_chars_per_line:
            return text

        # Case 2: needs wrapping — find the best break point for line 1.
        ideal_break = max_chars_per_line
        # Search backward from the width limit for a natural boundary
        # (space, or Japanese-friendly punctuation already stripped by
        # split_clauses, so a plain space search covers mixed-language text).
        break_at = text.rfind(" ", 0, ideal_break + 1)
        if break_at == -1 or break_at < ideal_break * 0.4:
            # No good natural break nearby (common for Japanese, which has
            # no spaces) — fall back to a straight character cut at budget.
            break_at = ideal_break

        lines = [text[:break_at].strip()]
        remainder = text[break_at:].strip()

        for _ in range(max_lines - 1):
            if not remainder:
                break
            if len(remainder) <= max_chars_per_line:
                lines.append(remainder)
                remainder = ""
            else:
                cut = remainder.rfind(" ", 0, max_chars_per_line + 1)
                if cut == -1 or cut < max_chars_per_line * 0.4:
                    cut = max_chars_per_line
                lines.append(remainder[:cut].strip())
                remainder = remainder[cut:].strip()

        if remainder:
            # Still overflow after max_lines — truncate the last line, same
            # ellipsis fallback behavior as before.
            lines[-1] = lines[-1][: max_chars_per_line - 1] + "…"

        return "\n".join(lines)


# [Subtitle] SpeakingTimelineMapper: maps pure speaking-time onto real timeline
class SpeakingTimelineMapper:
    """
    Maps a budget of pure speaking-time (excluding silent pauses) onto the
    real wall-clock timeline of an audio clip.

    TTS speech rate is roughly constant per character for a fixed voice,
    but `pauses` means the clip isn't a uniform speaking stream. Naively
    dividing total_duration evenly across clauses can place subtitle text
    inside a silence. Instead we build the complementary SPEAKING intervals
    (gaps between pauses) and walk clause-duration requests across only
    those intervals.
    """

    def __init__(self, total_duration: float, pauses: List[Dict[str, float]]):
        self.total_duration = total_duration
        self._pauses = sorted(pauses, key=lambda p: p["start"])
        self._speaking_intervals = self._invert_pauses()
        self.total_speaking_time = sum(e - s for s, e in self._speaking_intervals)

    def _invert_pauses(self) -> List[Tuple[float, float]]:
        """O(p) single pass over p pauses to derive complementary speaking gaps."""
        intervals: List[Tuple[float, float]] = []
        cursor = 0.0
        for pause in self._pauses:
            if pause["start"] > cursor:
                intervals.append((cursor, pause["start"]))
            cursor = max(cursor, pause["end"])
        if cursor < self.total_duration:
            intervals.append((cursor, self.total_duration))
        return intervals

    def allocate(self, speaking_durations: List[float]) -> List[Tuple[float, float]]:
        """
        Walks requested speaking-time spans (one per clause) across the
        speaking intervals in order, returning (start, end) on the REAL
        timeline with pauses automatically skipped.

        Two-pointer merge: O(c + p), c = clauses, p = pauses — each
        speaking interval and each clause span is advanced past at most
        once; no nested loop over the cross product.
        """
        if not self._speaking_intervals:
            return [(0.0, 0.0) for _ in speaking_durations]

        results: List[Tuple[float, float]] = []
        interval_idx = 0
        cur_pos = self._speaking_intervals[0][0]

        for need in speaking_durations:
            remaining = need
            seg_start = cur_pos
            while remaining > 1e-6 and interval_idx < len(self._speaking_intervals):
                _, interval_end = self._speaking_intervals[interval_idx]
                available = interval_end - cur_pos
                if available <= 1e-6:
                    interval_idx += 1
                    if interval_idx < len(self._speaking_intervals):
                        cur_pos = self._speaking_intervals[interval_idx][0]
                        if remaining == need:
                            seg_start = cur_pos  # clause starts fresh in next gap
                    continue
                take = min(available, remaining)
                cur_pos += take
                remaining -= take
            results.append((seg_start, cur_pos))
        return results


# [Subtitle] SubtitleBuilder: builds timed SubtitleCue list from raw text + pause analysis
class SubtitleBuilder:
    """Facade: raw narration text + audio analysis -> timed SubtitleCue list."""

    # [Core/Subtitle] Main entry point: builds a list of SubtitleCue objects from text and pause data
    @staticmethod
    def build(
        text: str,
        duration_seconds: float,
        pauses: List[Dict[str, float]],
        max_chars_per_line: int = 20,
        max_lines: int = 2,
    ) -> List[SubtitleCue]:
        clauses = TextSegmenter.split_clauses(text)
        if not clauses:
            return []

        mapper = SpeakingTimelineMapper(duration_seconds, pauses)
        if mapper.total_speaking_time <= 0:
            # Degenerate case (entirely silent clip) — even fallback
            # instead of a division by zero.
            per_clause = duration_seconds / len(clauses)
            spans = [
                (i * per_clause, (i + 1) * per_clause) for i in range(len(clauses))
            ]
        else:
            total_chars = sum(len(c) for c in clauses) or 1
            needed = [
                mapper.total_speaking_time * (len(c) / total_chars) for c in clauses
            ]
            spans = mapper.allocate(needed)

        return [
            SubtitleCue(
                start=s,
                end=e,
                text=TextSegmenter.wrap(c, max_chars_per_line, max_lines),
            )
            for (s, e), c in zip(spans, clauses)
        ]


# [Subtitle] SRTDocument: serializes SubtitleCue lists to .srt format
class SRTDocument:
    """Serializes SubtitleCue lists to standard .srt format."""

    # [Util] Formats a timestamp in seconds to the SRT timestamp format (HH:MM:SS,mmm)
    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        millis_total = max(0, round(seconds * 1000))
        hh, rem = divmod(millis_total, 3_600_000)
        mm, rem = divmod(rem, 60_000)
        ss, ms = divmod(rem, 1000)
        return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"

    # [Core/Subtitle] Converts a list of SubtitleCue objects to a string in .srt format
    @classmethod
    def to_string(cls, cues: List[SubtitleCue]) -> str:
        blocks = [
            f"{i}\n{cls._format_timestamp(c.start)} --> {cls._format_timestamp(c.end)}\n{c.text}\n"
            for i, c in enumerate(cues, start=1)
        ]
        return "\n".join(blocks)

    # [Core/Subtitle] Writes a list of SubtitleCue objects to a .srt file at the specified output path
    @classmethod
    def write(cls, cues: List[SubtitleCue], output_path: str) -> str:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(cls.to_string(cues))
        return output_path


# [Subtitle] MasterSubtitleAssembler: merges per-segment cue lists into one timeline-shifted master list
class MasterSubtitleAssembler:
    """Merges per-segment cue lists into one timeline-shifted master list."""

    # [Core/Subtitle] Assembles multiple segments of SubtitleCue lists into a single master list, applying offsets to each segment
    @staticmethod
    def assemble(
        segment_cues: List[List[SubtitleCue]], segment_offsets: List[float]
    ) -> List[SubtitleCue]:
        """O(total_cues) — each segment's cues shifted exactly once."""
        if len(segment_cues) != len(segment_offsets):
            raise ValueError(
                "segment_cues and segment_offsets must be the same length."
            )
        master: List[SubtitleCue] = []
        for cues, offset in zip(segment_cues, segment_offsets):
            master.extend(cue.shifted(offset) for cue in cues)
        return master