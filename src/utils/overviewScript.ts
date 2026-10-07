// Mirrors services/localization/cues.CUE_RE: tags are never spoken.
const CUE = /\{(start|arrive|end|distance|goPre\d+|go|\d+)\}/g;

export interface OverviewLength {
  chars_per_second: number;
  target_seconds: number;
  min_seconds: number;
  max_seconds: number;
}

export type LengthVerdict = "empty" | "short" | "ok" | "long";

export const spokenChars = (text: string) => text.replace(CUE, "").length;

export const estimateSeconds = (text: string, charsPerSecond: number) =>
  charsPerSecond > 0 ? Math.round((spokenChars(text) / charsPerSecond) * 10) / 10 : 0;

// Same 3 s of slack as overview_script.in_overview_range.
export function lengthVerdict(seconds: number, { min_seconds, max_seconds }: OverviewLength, tolerance = 3): LengthVerdict {
  if (seconds <= 0) return "empty";
  if (seconds < min_seconds - tolerance) return "short";
  if (seconds > max_seconds + tolerance) return "long";
  return "ok";
}

// The stop number the next {n} button inserts: one after the highest already in the script.
export function nextStopNumber(text: string): number {
  const used = [...text.matchAll(/\{(\d+)\}/g)].map((m) => Number(m[1]));
  return used.length ? Math.max(...used) + 1 : 1;
}
