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
  background_radius: 0,
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
    if (s.background_radius > 0) css.borderRadius = u(s.background_radius);
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
const isKana = (ch: string) => /^[ぁ-ゟ]$/.test(ch);
const isPhraseStart = (ch: string) => /^[一-鿿ァ-ヺ]$/.test(ch) || isWordChar(ch) || NO_LINE_END.has(ch);

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
  // Rough bunsetsu ends: hiragana (particles, okurigana) followed by kanji/katakana/Latin.
  const phrases: number[] = [];
  for (let i = Math.max(1, target - Math.floor(max / 3)); i <= Math.min(rest.length - 1, max); i++) {
    if (isKana(rest[i - 1]) && isPhraseStart(rest[i])) phrases.push(i);
  }
  if (phrases.length) return [nearest(phrases), 0];
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

// ── Text track (title + subtitle): mirrors introclip.py's defaults and title_events ──

const TEXT_LINE_DEFAULTS = {
  opacity: 1,
  bold: true,
  italic: false,
  underline: false,
  outline_color: "#000000",
  shadow: 1,
  shadow_color: "#000000",
  letter_spacing: 0,
  background: false,
  background_color: "#000000",
  background_opacity: 0.6,
  background_radius: 0,
  position: "middle",
  margin_v: 0,
  max_chars_per_line: 0,
} as const;

export const DEFAULT_TEXT_TITLE_STYLE: Required<TextStyle> = {
  ...TEXT_LINE_DEFAULTS,
  font_family: "Yu Gothic UI",
  font_size: 74,
  color: "#FFFFFF",
  outline_width: 2,
};

export const DEFAULT_TEXT_SUBTITLE_STYLE: Required<TextStyle> = {
  ...TEXT_LINE_DEFAULTS,
  font_family: "Yu Gothic UI",
  font_size: 36,
  color: "#FFFFFF",
  outline_width: 0,
};

export const DEFAULT_TEXT_KICKER_STYLE: Required<TextStyle> = {
  ...TEXT_LINE_DEFAULTS,
  font_family: "Yu Gothic UI",
  font_size: 30,
  color: "#CDD2DC",
  bold: false,
  outline_width: 0,
  letter_spacing: 4,
};

// tuning.py INTRO_LABEL_* / INTRO_SUBTITLE_*.
const LABEL_FADE = 1.1;
const LABEL_SCALE_START = 0.65;
const SUB_DELAY = 0.8;
const SUB_FADE = 0.7;
const SUB_RISE = 28;
const TEXT_FADE = 0.5;

export const TEXT_DEFAULT_MARGIN = 100;

/** Centres (1080p px) of the kicker, title and subtitle lines; mirrors stacked_line_ys in introclip.py. */
export function stackedLineYs(
  cy: number,
  kickerSize: number,
  titleSize: number,
  subSize: number,
  hasKicker: boolean,
  hasTitle: boolean,
  hasSub: boolean,
): { kickerY: number; titleY: number; subY: number } {
  let titleY = cy;
  let subY = cy;
  if (hasTitle && hasSub) {
    titleY = cy - Math.trunc(subSize * 0.6);
    subY = cy + Math.trunc(titleSize * 0.6);
  }
  if (!hasKicker || !(hasTitle || hasSub)) return { kickerY: cy, titleY, subY };
  const [topY, topSize] = hasTitle ? [titleY, titleSize] : [subY, subSize];
  const gap = Math.trunc(0.6 * (kickerSize + topSize));
  const shift = Math.floor(gap / 2);
  return { kickerY: topY - gap + shift, titleY: titleY + shift, subY: subY + shift };
}

/** Vertical centre (1080p px) of a title + subtitle block (kickerSize > 0 adds a kicker above);
 * mirrors text_block_center_y in introclip.py. */
export function textBlockCenterY(
  position: "top" | "middle" | "bottom" | undefined,
  margin: number | undefined,
  titleSize: number,
  subSize: number,
  hasTitle: boolean,
  hasSub: boolean,
  kickerSize = 0,
): number {
  if (position !== "top" && position !== "bottom") return 540;
  let half =
    hasTitle && hasSub ? 0.55 * (titleSize + subSize) : hasTitle || hasSub ? (hasTitle ? titleSize : subSize) / 2 : kickerSize / 2;
  if (kickerSize > 0 && (hasTitle || hasSub)) half += 0.3 * (kickerSize + (hasTitle ? titleSize : subSize));
  const m = Math.max(0, margin ?? TEXT_DEFAULT_MARGIN);
  return Math.round(position === "top" ? m + half : 1080 - m - half);
}

export type LineAnimation = "pop" | "rise" | "fade" | "none";
const LINE_ANIMATIONS: LineAnimation[] = ["pop", "rise", "fade", "none"];

/** A line's (animation, delay); mirrors line_motion in introclip.py. */
export function lineMotion(
  which: "title" | "subtitle" | "kicker",
  animation: string | undefined,
  delay: number | undefined,
  groupAnimation: string | undefined,
  duration: number,
  paired: boolean,
): { animation: LineAnimation; delay: number } {
  const group = groupAnimation === "fade" || groupAnimation === "none" ? groupAnimation : undefined;
  const anim = LINE_ANIMATIONS.includes(animation as LineAnimation)
    ? (animation as LineAnimation)
    : (group ?? (which === "title" ? "pop" : which === "kicker" ? "fade" : "rise"));
  let d: number;
  if (typeof delay === "number" && Number.isFinite(delay)) d = Math.max(0, delay);
  else if (group || which !== "subtitle" || !paired) d = 0;
  else d = Math.min(SUB_DELAY, duration / 4);
  return { animation: anim, delay: Math.min(d, Math.max(0, duration * 0.45)) };
}

/** Opacity, scale and downward shift (1080p px) of one line `t` seconds into an item of `duration`. */
export function lineFrame(t: number, duration: number, animation: LineAnimation, delay: number) {
  const ramp = (x: number, len: number) => (len <= 0 ? 1 : Math.min(1, Math.max(0, x / len)));
  const lt = t - delay;
  const len = Math.max(0, duration - 2 * delay);
  if (lt < 0 || lt > len) return { opacity: 0, scale: 1, rise: 0 };
  if (animation === "pop") {
    const f = Math.min(LABEL_FADE, len / 2);
    const k = Math.min(ramp(lt, f), ramp(len - lt, f));
    return { opacity: k, scale: LABEL_SCALE_START + (1 - LABEL_SCALE_START) * k, rise: 0 };
  }
  if (animation === "rise") {
    const f = Math.min(SUB_FADE, len / 3);
    return { opacity: Math.min(ramp(lt, f), ramp(len - lt, f)), scale: 1, rise: SUB_RISE * (1 - ramp(lt, f)) };
  }
  if (animation === "fade") {
    const f = Math.min(TEXT_FADE, len / 2);
    return { opacity: Math.min(ramp(lt, f), ramp(len - lt, f)), scale: 1, rise: 0 };
  }
  return { opacity: 1, scale: 1, rise: 0 };
}
