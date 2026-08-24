"""
services/subtitle.py
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
from typing import Any, Dict, List, Tuple

# Clause delimiters TTS engines (and human speech) naturally pause on.
# Class-level constant so it's swappable for other languages.
_CLAUSE_DELIMITERS = re.compile(r"([、。！？!?])")


@dataclass(frozen=True)
class SubtitleCue:
    """One timed subtitle line: [start, end) in seconds, plus display text."""
    start: float
    end: float
    text: str

    def shifted(self, offset_seconds: float) -> "SubtitleCue":
        """Returns a copy translated forward in time by `offset_seconds`."""
        return SubtitleCue(self.start + offset_seconds, self.end + offset_seconds, self.text)


class TextSegmenter:
    """Splits raw narration text into display-sized subtitle chunks."""

    @staticmethod
    def split_clauses(text: str) -> List[str]:
        """
        Splits on sentence-ending punctuation, keeping the delimiter
        attached to its clause — these are the natural TTS pause points.
        O(n) single regex pass.
        """
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
    def wrap(text: str, max_chars_per_line: int = 20, max_lines: int = 2) -> str:
        """
        Hard-wraps by CHARACTER count, not word count — Japanese has no
        spaces, so word-wrapping is undefined here. O(n) single pass.
        Truncates with an ellipsis rather than silently overflowing frame.
        """
        lines: List[str] = []
        for i in range(0, len(text), max_chars_per_line):
            lines.append(text[i:i + max_chars_per_line])
            if len(lines) == max_lines:
                break
        if len(text) > max_chars_per_line * max_lines:
            lines[-1] = lines[-1][: max_chars_per_line - 1] + "…"
        return "\n".join(lines)


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


class SubtitleBuilder:
    """Facade: raw narration text + audio analysis -> timed SubtitleCue list."""

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
            spans = [(i * per_clause, (i + 1) * per_clause) for i in range(len(clauses))]
        else:
            total_chars = sum(len(c) for c in clauses) or 1
            needed = [mapper.total_speaking_time * (len(c) / total_chars) for c in clauses]
            spans = mapper.allocate(needed)

        return [
            SubtitleCue(start=s, end=e, text=TextSegmenter.wrap(c, max_chars_per_line, max_lines))
            for (s, e), c in zip(spans, clauses)
        ]


class SRTDocument:
    """Serializes SubtitleCue lists to standard .srt format."""

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        millis_total = max(0, round(seconds * 1000))
        hh, rem = divmod(millis_total, 3_600_000)
        mm, rem = divmod(rem, 60_000)
        ss, ms = divmod(rem, 1000)
        return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"

    @classmethod
    def to_string(cls, cues: List[SubtitleCue]) -> str:
        blocks = [
            f"{i}\n{cls._format_timestamp(c.start)} --> {cls._format_timestamp(c.end)}\n{c.text}\n"
            for i, c in enumerate(cues, start=1)
        ]
        return "\n".join(blocks)

    @classmethod
    def write(cls, cues: List[SubtitleCue], output_path: str) -> str:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(cls.to_string(cues))
        return output_path


class MasterSubtitleAssembler:
    """Merges per-segment cue lists into one timeline-shifted master list."""

    @staticmethod
    def assemble(segment_cues: List[List[SubtitleCue]], segment_offsets: List[float]) -> List[SubtitleCue]:
        """O(total_cues) — each segment's cues shifted exactly once."""
        if len(segment_cues) != len(segment_offsets):
            raise ValueError("segment_cues and segment_offsets must be the same length.")
        master: List[SubtitleCue] = []
        for cues, offset in zip(segment_cues, segment_offsets):
            master.extend(cue.shifted(offset) for cue in cues)
        return master