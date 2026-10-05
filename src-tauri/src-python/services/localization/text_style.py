"""One text-look shape shared by the intro title, intro subtitle and burned captions.

Mirrors the frontend's TextStyle (src/types/index.ts) so a single font editor
can drive all three. Sizes are pixels on a 1920x1080 frame; colours are CSS
hex. Bad or unknown fields fall back to the default instead of failing a render.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Tuple

from services.localization.subtitle import SubtitleStyle

RGB = Tuple[int, int, int]

# libass scales .srt style values from a 288-line script to the frame height.
_SRT_UNITS_PER_PX = 288 / 1080


def parse_color(value: Any) -> Optional[Tuple[RGB, Optional[float]]]:
    """Returns ((r, g, b), opacity or None) from "#RGB", "#RRGGBB", "#RRGGBBAA",
    [r, g, b], or ASS "&H[AA]BBGGRR" (what the old subtitle settings stored)."""
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            return tuple(max(0, min(255, int(c))) for c in value), None  # type: ignore[return-value]
        except (TypeError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    s = value.strip()
    try:
        if s[:2].upper() == "&H":
            h = s[2:].rstrip("&")
            if len(h) not in (6, 8):
                return None
            alpha = None
            if len(h) == 8:
                alpha = 1 - int(h[:2], 16) / 255
                h = h[2:]
            return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)), alpha
        h = s.lstrip("#")
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        if len(h) not in (6, 8):
            return None
        alpha = int(h[6:8], 16) / 255 if len(h) == 8 else None
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)), alpha
    except ValueError:
        return None


def _num(value: Any, lo: float, hi: float) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return None


def _bgr(rgb: RGB) -> str:
    r, g, b = rgb
    return f"{b:02X}{g:02X}{r:02X}"


def _ass_color(rgb: RGB, opacity: float = 1.0) -> str:
    return f"&H{255 - int(round(opacity * 255)):02X}{_bgr(rgb)}"


# Old-SSA alignment numbers (see SubtitleStyle.alignment), centred horizontally.
_POSITION_ALIGNMENT = {"bottom": 2, "middle": 10, "top": 6}
# The same positions in v4.00+ (numpad) numbering.
_POSITION_NUMPAD = {"bottom": 2, "middle": 5, "top": 8}

# Kinsoku: never start a line with a closer, never end one with an opener.
_NO_LINE_START = set("、。，．・：；？！ー）」』】〕〉》｝)]}!?.,:;%")
_NO_LINE_END = set("（「『【〔〈《｛([{")
_BREAK_AFTER = set("、。，！？")


def _is_word_char(ch: str) -> bool:
    return ch.isascii() and ch.isalnum()


def _break_index(rest: str, max_chars: int, target: int) -> tuple:
    """(cut, skip): the line is rest[:cut], the next starts at rest[cut + skip:]."""
    spaces = [i for i in range(1, min(len(rest), max_chars + 1)) if rest[i] == " "]
    if spaces:
        cut = min(spaces, key=lambda i: abs(i - target))
        return cut, 1
    # Prefer just after a 、/。 near the balanced point.
    window = range(max(1, target - max_chars // 3), min(len(rest) - 1, max_chars) + 1)
    marks = [i for i in window if rest[i - 1] in _BREAK_AFTER]
    if marks:
        return min(marks, key=lambda i: abs(i - target)), 0
    cut = min(target, max_chars)
    while cut < max_chars and rest[cut] in _NO_LINE_START:
        cut += 1
    while cut > 1 and (rest[cut] in _NO_LINE_START or rest[cut - 1] in _NO_LINE_END):
        cut -= 1
    # Don't split a Latin word or number embedded in Japanese text.
    start = cut
    while start > 1 and _is_word_char(rest[start - 1]) and _is_word_char(rest[start]):
        start -= 1
    if start > 1:
        cut = start
    return cut, 0


def wrap_line(line: str, max_chars: int) -> List[str]:
    """Splits one line into balanced lines of at most `max_chars` characters,
    at a space when there is one, else between characters (Japanese).
    Mirrors wrapLine in src/utils/textStyle.ts."""
    if max_chars <= 0 or len(line) <= max_chars:
        return [line]
    count = -(-len(line) // max_chars)
    target = -(-len(line) // count)
    out: List[str] = []
    rest = line
    while len(rest) > max_chars:
        cut, skip = _break_index(rest, max_chars, target)
        out.append(rest[:cut].rstrip())
        rest = rest[cut + skip:].lstrip()
    if rest:
        out.append(rest)
    return out


def wrap_text(text: str, max_chars: int) -> str:
    """Wraps every line of `text`, keeping the line breaks already in it."""
    return "\n".join(part for line in text.split("\n") for part in wrap_line(line, max_chars))


@dataclass(frozen=True)
class TextStyle:
    font_family: str
    font_size: int
    color: RGB = (255, 255, 255)
    opacity: float = 1.0
    bold: bool = True
    italic: bool = False
    underline: bool = False
    outline_width: float = 0.0
    outline_color: RGB = (0, 0, 0)
    shadow: float = 1.0
    shadow_color: RGB = (0, 0, 0)
    letter_spacing: float = 0.0
    # Captions only: a box behind the text instead of an outline.
    background: bool = False
    background_color: RGB = (0, 0, 0)
    background_opacity: float = 0.6
    # Captions only: where on screen, and how far from that edge (px).
    position: str = "bottom"
    margin_v: float = 75.0
    max_chars_per_line: int = 0  # 0 = no limit

    def merged(self, raw: Any) -> "TextStyle":
        if not isinstance(raw, dict):
            return self
        changes: Dict[str, Any] = {}
        family = raw.get("font_family")
        if isinstance(family, str):
            # Characters that would break out of an ASS tag or force_style list.
            family = re.sub(r"[\\{},=:'\r\n]", "", family).strip()[:80]
            if family:
                changes["font_family"] = family
        size = _num(raw.get("font_size"), 8, 300)
        if size is not None:
            changes["font_size"] = int(round(size))
        for key, alpha_key in (
            ("color", "opacity"),
            ("outline_color", None),
            ("shadow_color", None),
            ("background_color", "background_opacity"),
        ):
            parsed = parse_color(raw.get(key))
            if parsed is not None:
                changes[key] = parsed[0]
                if alpha_key and parsed[1] is not None and alpha_key not in raw:
                    changes[alpha_key] = parsed[1]
        for key, lo, hi in (
            ("opacity", 0.0, 1.0),
            ("background_opacity", 0.0, 1.0),
            ("outline_width", 0.0, 20.0),
            ("shadow", 0.0, 20.0),
            ("letter_spacing", -20.0, 50.0),
            ("margin_v", 0.0, 400.0),
        ):
            n = _num(raw.get(key), lo, hi)
            if n is not None:
                changes[key] = n
        for key in ("bold", "italic", "underline", "background"):
            if isinstance(raw.get(key), bool):
                changes[key] = raw[key]
        if raw.get("position") in _POSITION_ALIGNMENT:
            changes["position"] = raw["position"]
        max_chars = _num(raw.get("max_chars_per_line"), 0, 200)
        if max_chars is not None:
            changes["max_chars_per_line"] = int(max_chars)
        return replace(self, **changes)

    def to_ass_tags(self) -> str:
        """Inline override tags for an .ass event (intro text)."""
        return (
            f"\\fn{self.font_family}\\fs{self.font_size}"
            f"\\b{int(self.bold)}\\i{int(self.italic)}\\u{int(self.underline)}"
            f"\\c&H{_bgr(self.color)}&\\3c&H{_bgr(self.outline_color)}&"
            f"\\4c&H{_bgr(self.shadow_color)}&"
            f"\\alpha&H{255 - int(round(self.opacity * 255)):02X}&"
            f"\\bord{self.outline_width:g}\\shad{self.shadow:g}\\fsp{self.letter_spacing:g}"
        )

    def with_installed_font(self, fallback: str) -> "TextStyle":
        """Swap a font that isn't installed for `fallback`, rather than letting
        libass pick an arbitrary substitute."""
        from services.localization.fonts import resolve_font_family

        return replace(self, font_family=resolve_font_family(self.font_family, fallback))

    def to_ass_style_line(self, name: str) -> str:
        """A v4.00+ [V4+ Styles] line in 1080-line units (PlayResY: 1080), for captions."""
        if self.background:
            # libass draws the BorderStyle=3 box in OutlineColour; its padding is Outline.
            box = _ass_color(self.background_color, self.background_opacity)
            outline_color, back_color, border_style = box, box, 3
            outline, shadow = max(self.outline_width, 9.0), 0.0
        else:
            outline_color, back_color, border_style = _ass_color(self.outline_color), _ass_color(self.shadow_color), 1
            outline, shadow = self.outline_width, self.shadow
        flag = lambda b: -1 if b else 0  # noqa: E731
        return (
            f"Style: {name},{self.font_family},{self.font_size},{_ass_color(self.color, self.opacity)},"
            f"&H000000FF,{outline_color},{back_color},{flag(self.bold)},{flag(self.italic)},"
            f"{flag(self.underline)},0,100,100,{self.letter_spacing:g},0,{border_style},{outline:g},{shadow:g},"
            f"{_POSITION_NUMPAD[self.position]},60,60,{int(round(self.margin_v))},1"
        )

    def to_subtitle_style(self) -> SubtitleStyle:
        """force_style for burning an .srt (captions), converted to libass's 288-line units."""
        u = _SRT_UNITS_PER_PX
        if self.background:
            # BorderStyle=3 draws the box in OutlineColour; its padding is Outline.
            box = _ass_color(self.background_color, self.background_opacity)
            outline_color, back_color, border_style = box, box, 3
            outline = max(self.outline_width, 9.0) * u
        else:
            outline_color = _ass_color(self.outline_color)
            back_color = _ass_color(self.shadow_color)
            border_style = 1
            outline = self.outline_width * u
        return SubtitleStyle(
            font_name=self.font_family,
            font_size=max(1, int(round(self.font_size * u))),
            primary_color=_ass_color(self.color, self.opacity),
            outline_color=outline_color,
            back_color=back_color,
            bold=self.bold,
            italic=self.italic,
            underline=self.underline,
            spacing=round(self.letter_spacing * u, 2),
            border_style=border_style,
            outline=round(outline, 2),
            shadow=0.0 if self.background else round(self.shadow * u, 2),
            alignment=_POSITION_ALIGNMENT[self.position],
            margin_v=int(round(self.margin_v * u)),
        )
