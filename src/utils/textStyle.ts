import type { CSSProperties } from "react";
import type { ProjectSettings, TextStyle } from "../types";

// Mirrors services/localization/text_style.py and DEFAULT_CAPTION_STYLE in vdoexporter.py.
export const DEFAULT_CAPTION_STYLE: Required<TextStyle> = {
  font_family: "Meiryo",
  font_size: 71,
  color: "#FFFFFF",
  opacity: 1,
  bold: false,
  italic: false,
  underline: false,
  outline_width: 9.375,
  outline_color: "#000000",
  shadow: 0,
  shadow_color: "#000000",
  letter_spacing: 0,
  background: true,
  background_color: "#000000",
  background_opacity: 0.6,
  position: "bottom",
  margin_v: 75,
  max_chars_per_line: 0,
};

/** Default, then the project's caption_style, then one subtitle's own overrides — same order as the export. */
export function resolveCaptionStyle(settings: Partial<ProjectSettings>, own?: TextStyle): Required<TextStyle> {
  return { ...DEFAULT_CAPTION_STYLE, ...(settings.caption_style ?? {}), ...(own ?? {}) };
}

const rgba = (hex: string, alpha: number) => {
  const h = hex.replace("#", "");
  const full = h.length === 3 ? [...h].map((c) => c + c).join("") : h.slice(0, 6);
  const n = parseInt(full, 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
};

/** CSS for a TextStyle inside a box with `container-type: size` (1080 px → 100cqh). */
export function textStyleToCss(s: Required<TextStyle>): CSSProperties {
  const u = (px: number) => `${(px / 1080) * 100}cqh`;
  const css: CSSProperties = {
    fontFamily: `"${s.font_family}", Meiryo, "Yu Gothic UI", sans-serif`,
    fontSize: u(s.font_size),
    fontWeight: s.bold ? 700 : 400,
    fontStyle: s.italic ? "italic" : "normal",
    textDecoration: s.underline ? "underline" : "none",
    letterSpacing: u(s.letter_spacing),
    color: rgba(s.color, s.opacity),
  };
  if (s.background) {
    css.backgroundColor = rgba(s.background_color, s.background_opacity);
    css.padding = `${u(s.outline_width * 0.3)} ${u(s.outline_width)}`;
  } else {
    if (s.outline_width > 0) css.WebkitTextStroke = `${u(s.outline_width)} ${s.outline_color}`;
    css.paintOrder = "stroke fill";
    if (s.shadow > 0) css.textShadow = `${u(s.shadow)} ${u(s.shadow)} 0 ${s.shadow_color}`;
  }
  return css;
}

// ── Line wrapping: mirrors wrap_line in services/localization/text_style.py ──

const NO_LINE_START = new Set([..."、。，．・：；？！ー）」』】〕〉》｝)]}!?.,:;%"]);
const NO_LINE_END = new Set([..."（「『【〔〈《｛([{"]);
const BREAK_AFTER = new Set([..."、。，！？"]);
const isWordChar = (ch: string) => /^[A-Za-z0-9]$/.test(ch);

function breakIndex(rest: string[], max: number, target: number): [number, number] {
  const spaces: number[] = [];
  for (let i = 1; i <= Math.min(rest.length - 1, max); i++) if (rest[i] === " ") spaces.push(i);
  const nearest = (xs: number[]) => xs.reduce((a, b) => (Math.abs(b - target) < Math.abs(a - target) ? b : a));
  if (spaces.length) return [nearest(spaces), 1];
  const marks: number[] = [];
  for (let i = Math.max(1, target - Math.floor(max / 3)); i <= Math.min(rest.length - 1, max); i++) {
    if (BREAK_AFTER.has(rest[i - 1])) marks.push(i);
  }
  if (marks.length) return [nearest(marks), 0];
  let cut = Math.min(target, max);
  while (cut < max && NO_LINE_START.has(rest[cut])) cut++;
  while (cut > 1 && (NO_LINE_START.has(rest[cut]) || NO_LINE_END.has(rest[cut - 1]))) cut--;
  let start = cut;
  while (start > 1 && isWordChar(rest[start - 1]) && isWordChar(rest[start])) start--;
  if (start > 1) cut = start;
  return [cut, 0];
}

/** Balanced lines of at most `max` characters; at a space when there is one, else between characters. */
export function wrapLine(line: string, max: number): string[] {
  let rest = Array.from(line);
  if (max <= 0 || rest.length <= max) return [line];
  const target = Math.ceil(rest.length / Math.ceil(rest.length / max));
  const out: string[] = [];
  while (rest.length > max) {
    const [cut, skip] = breakIndex(rest, max, target);
    out.push(rest.slice(0, cut).join("").trimEnd());
    rest = Array.from(rest.slice(cut + skip).join("").trimStart());
  }
  if (rest.length) out.push(rest.join(""));
  return out;
}

export const wrapText = (text: string, max: number) =>
  text.split("\n").flatMap((line) => wrapLine(line, max)).join("\n");
