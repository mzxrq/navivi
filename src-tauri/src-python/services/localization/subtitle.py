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
from typing import Dict, List, Optional, Tuple

from services import tuning
from services.localization.sentence_split import ABBREVIATIONS
from services.logger.logger import setup_logger

# Logging configuration
logger = setup_logger("SubtitleService")

# Clause delimiters TTS engines (and human speech) naturally pause on.
_CLAUSE_DELIMITERS = re.compile(r"([、。！？!?,.])")
_HIDDEN_POINT = "․"  # one dot leader: stands in for a period that must not split a clause
_DECIMAL_POINT = re.compile(r"(?<=\d)\.(?=\d)")
_ABBREVIATION_POINT = re.compile(r"\b(%s)\." % "|".join(ABBREVIATIONS))


def line_budget(text: str, max_chars_per_line: int) -> int:
    """The line length for `text`: the budget counts Japanese characters, and a Latin letter is about half as wide."""
    letters = [c for c in text if c.isalpha()]
    latin = sum(1 for c in letters if c.isascii())
    return max_chars_per_line * 2 if letters and latin * 2 > len(letters) else max_chars_per_line


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
    italic: bool = False
    underline: bool = False
    spacing: float = 0.0  # extra letter spacing, libass units
    border_style: int = 1  # 1 = outline+shadow, 3 = opaque background box
    outline: float = 2.0  # outline thickness in px
    shadow: float = 0.5  # drop-shadow distance in px
    # [HACK] [Subtitle] FFmpeg's `subtitles` filter converts .srt to an old-style SSA
    # script (v4.00, not v4.00+/ASS), so this uses OLD SSA \a numbering, NOT the modern
    # ASS \an numpad convention most references describe — they only agree on the
    # bottom row: bottom 1/2/3, top 5/6/7 (ASS numpad would be 7/8/9), middle
    # 9/10/11 (ASS numpad would be 4/5/6). Verified empirically: introclip.py's
    # centered title needed 10, not 5, to actually land center-screen.
    alignment: int = 2  # bottom-center
    margin_v: int = 10  # vertical margin from frame edge, px
    margin_l: Optional[int] = None  # left margin; None keeps libass's default
    margin_r: Optional[int] = None  # right margin; None keeps libass's default

    def to_force_style(self) -> str:
        """Serializes to the comma-separated key=value string libass expects."""
        bold_flag = -1 if self.bold else 0  # ASS uses -1 for True, 0 for False
        margin_l = f",MarginL={self.margin_l}" if self.margin_l is not None else ""
        margin_r = f",MarginR={self.margin_r}" if self.margin_r is not None else ""
        return (
            f"FontName={self.font_name},FontSize={self.font_size},"
            f"PrimaryColour={self.primary_color},OutlineColour={self.outline_color},"
            f"BackColour={self.back_color},Bold={bold_flag},"
            f"Italic={-1 if self.italic else 0},Underline={-1 if self.underline else 0},"
            f"Spacing={self.spacing:g},BorderStyle={self.border_style},"
            f"Outline={self.outline},Shadow={self.shadow},Alignment={self.alignment},"
            f"MarginV={self.margin_v}{margin_l}{margin_r}"
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
        # The point of "Mt. Kabuto" or "1.5 km" is not a pause: hide it from the split, then give it back.
        text = _DECIMAL_POINT.sub(_HIDDEN_POINT, text)
        text = _ABBREVIATION_POINT.sub(lambda m: m.group(1) + _HIDDEN_POINT, text)
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
        return [c.replace(_HIDDEN_POINT, ".") for c in clauses or [text]]

    @staticmethod
    def split_lines(text: str, max_chars_per_line: int = 24) -> List[str]:
        """A clause too long for one line becomes several one-line captions, broken
        evenly at a space, punctuation or phrase end (kinsoku-safe). Captions are never 2 lines."""
        text = text.strip()
        if not text:
            return []
        # A closing 、。 is dropped on display, so it doesn't count.
        if len(text.rstrip("、。")) <= max_chars_per_line:
            return [text]
        from services.localization.text_style import wrap_line

        return wrap_line(text, max_chars_per_line)


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


# Bracketed TTS performance tags ("[whispers]", "【笑】") are spoken as style, not text.
_BRACKET_TAG = re.compile(r"\s*[\[［【][^\]］】]*[\]］】]\s*")


def strip_bracket_tags(text: str) -> str:
    return _BRACKET_TAG.sub("", text or "")


_TWO_MORA = re.compile(r"[㐀-鿿豈-﫿0-9０-９]")
_UNSPOKEN = re.compile(r"[\s、。！？!?,.「」『』（）()【】\[\]・…]")


def spoken_weight(text: str) -> int:
    """Rough spoken length: a kanji or digit usually reads as ~2 morae."""
    return max(1, sum(0 if _UNSPOKEN.match(ch) else 2 if _TWO_MORA.match(ch) else 1 for ch in text))


def align_to_pauses(
    weights: List[int], speech: List[Tuple[float, float]], max_group: int = 6, unsnapped_cost: float = 1.0,
    soft: Optional[List[bool]] = None,
) -> Optional[List[Tuple[float, float]]]:
    """Places clause boundaries in the voice's real pauses, choosing the pauses whose
    spans best match each clause's spoken length (DP over clause count x pause).
    Clauses with no pause between them share a span by weight. soft[i]: the break after
    clause i is a line split mid-sentence, cheap to leave off a pause. None if it can't fit."""
    n = len(weights)
    if n == 0 or not speech:
        return None
    miss = [unsnapped_cost * (0.1 if soft and soft[i] else 1.0) for i in range(n)]
    # Nodes: 0 = voice start, 1..P = gaps between speech intervals, P+1 = voice end.
    opens = [speech[0][0]] + [s for s, _ in speech[1:]]
    closes = [e for _, e in speech[:-1]] + [speech[-1][1]]
    gap_sum = [0.0]
    for k in range(1, len(speech)):
        gap_sum.append(gap_sum[-1] + opens[k] - closes[k - 1])
    last = len(speech)
    rate = sum(e - s for s, e in speech) / sum(weights)
    prefix = [0]
    for w in weights:
        prefix.append(prefix[-1] + w)

    def spoken(a: int, b: int) -> float:
        return closes[b - 1] - opens[a] - (gap_sum[b - 1] - gap_sum[a])

    inf = float("inf")
    best = [[inf] * (last + 1) for _ in range(n + 1)]
    back: List[List[Optional[Tuple[int, int]]]] = [[None] * (last + 1) for _ in range(n + 1)]
    best[0][0] = 0.0
    for k0 in range(n):
        for a in range(last):
            if best[k0][a] == inf:
                continue
            for k in range(k0 + 1, min(n, k0 + max_group) + 1):
                target = rate * (prefix[k] - prefix[k0])
                extra = sum(miss[k0 : k - 1])
                for b in range(a + 1, last + 1):
                    if (b == last) != (k == n):
                        continue
                    cost = best[k0][a] + (spoken(a, b) - target) ** 2 + extra
                    if cost < best[k][b]:
                        best[k][b] = cost
                        back[k][b] = (k0, a)
    if best[n][last] == inf:
        return None

    spans: List[Tuple[float, float]] = []
    k, b = n, last
    while k > 0:
        k0, a = back[k][b]
        start, end = opens[a], closes[b - 1]
        total = prefix[k] - prefix[k0]
        group = []
        for i in range(k0, k):
            s = start + (end - start) * (prefix[i] - prefix[k0]) / total
            e = start + (end - start) * (prefix[i + 1] - prefix[k0]) / total
            group.append((s, e))
        spans[:0] = group
        k, b = k0, a
    # Hold each caption through the pause until the next one starts.
    return [(s, spans[i + 1][0] if i + 1 < len(spans) else e) for i, (s, e) in enumerate(spans)]


# [Subtitle] SubtitleBuilder: builds timed SubtitleCue list from raw text + pause analysis
class SubtitleBuilder:
    """Facade: raw narration text + audio analysis -> timed SubtitleCue list."""

    # [Core/Subtitle] Main entry point: builds a list of SubtitleCue objects from text and pause data
    @staticmethod
    def build(
        text: str,
        duration_seconds: float,
        pauses: List[Dict[str, float]],
        max_chars_per_line: int = tuning.SUBTITLE_MAX_CHARS_PER_LINE,
        lines_per_caption: int = 1,
    ) -> List[SubtitleCue]:
        clauses, soft = [], []
        for clause in TextSegmenter.split_clauses(strip_bracket_tags(text)):
            lines = TextSegmenter.split_lines(clause, line_budget(clause, max_chars_per_line))
            per = max(1, lines_per_caption)
            parts = ["\n".join(lines[i : i + per]) for i in range(0, len(lines), per)]
            clauses += parts
            soft += [True] * (len(parts) - 1) + [False]
        if not clauses:
            return []

        mapper = SpeakingTimelineMapper(duration_seconds, pauses)
        # [NOTE] [Subtitle] Falls back to even per-clause division when the mapper finds no non-pause
        # (speaking) intervals at all, avoiding a divide-by-zero in the char-proportional allocation below.
        if mapper.total_speaking_time <= 0:
            # Degenerate case (entirely silent clip) — even fallback
            # instead of a division by zero.
            per_clause = duration_seconds / len(clauses)
            spans = [
                (i * per_clause, (i + 1) * per_clause) for i in range(len(clauses))
            ]
        else:
            weights = [spoken_weight(c) for c in clauses]
            spans = align_to_pauses(weights, mapper._speaking_intervals, soft=soft)
            if spans is None:
                total = sum(weights)
                spans = mapper.allocate([mapper.total_speaking_time * w / total for w in weights])

        return [SubtitleCue(start=s, end=e, text=c) for (s, e), c in zip(spans, clauses)]


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


def caption_layout(settings: Optional[dict] = None) -> Dict[str, int]:
    """SubtitleBuilder.build's line options from the project's settings: line length from
    caption_style.max_chars_per_line, and settings.subtitle_long_lines "split" | "wrap"."""
    settings = settings or {}
    style = settings.get("caption_style") or {}
    try:
        max_chars = int(style.get("max_chars_per_line") or 0)
    except (TypeError, ValueError):
        max_chars = 0
    wrap = (settings.get("subtitle_long_lines") or tuning.SUBTITLE_LONG_LINES) == "wrap"
    return {
        "max_chars_per_line": max_chars if max_chars > 0 else tuning.SUBTITLE_MAX_CHARS_PER_LINE,
        "lines_per_caption": 2 if wrap else 1,
    }


def caption_style(settings: Optional[dict] = None) -> SubtitleStyle:
    """The look of burned-in captions: font, size, text colour and box colour come from the project's
    settings (`subtitle_*`), the box shape and position from tuning.CAPTION_*. `settings` can be the
    project's settings or the `subtitle_style` block the editor writes into timeline.json; anything
    missing falls back to the defaults. In box mode libass fills the box with the OUTLINE colour, which
    is why `subtitle_outline_color` is the box colour here."""
    settings = settings or {}
    side = round(tuning.CAPTION_PLAY_RES_X * (1 - tuning.CAPTION_MAX_WIDTH) / 2)
    return SubtitleStyle(
        font_name=settings.get("subtitle_font") or "Yu Gothic UI",
        font_size=int(settings.get("subtitle_font_size") or tuning.CAPTION_DEFAULT_SIZE),
        primary_color=settings.get("subtitle_color") or "&H00FFFFFF",
        outline_color=settings.get("subtitle_outline_color") or tuning.CAPTION_BOX_COLOR,
        bold=bool(settings.get("subtitle_bold", False)),
        border_style=3,
        outline=tuning.CAPTION_BOX_PADDING,
        shadow=0,
        margin_v=tuning.CAPTION_MARGIN_V,
        margin_l=side,
        margin_r=side,
    )
