// Mirrors services/localization/cues.CUE_RE: tags are never spoken.
const CUE = /\{(start|arrive|end|distance|route|extras|scene|open|close|photo:[^{}]+|goPre\d+|go|\d+)\}/g;

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

// The opening (before {start}, heard over the intro photos) and the rest; joinOpening puts them back.
export function splitOpening(text: string): { opening: string; body: string } {
  const at = text.indexOf("{start}");
  return at > 0 ? { opening: text.slice(0, at), body: text.slice(at + "{start}".length) } : { opening: "", body: text };
}

export function joinOpening(opening: string, body: string): string {
  if (!opening.trim()) return body;
  return opening + (body.includes("{start}") ? "" : "{start}") + body;
}

// The stop number the next {n} button inserts: one after the highest already in the script.
export function nextStopNumber(text: string): number {
  const used = [...text.matchAll(/\{(\d+)\}/g)].map((m) => Number(m[1]));
  return used.length ? Math.max(...used) + 1 : 1;
}

// Mirrors overview_script.visible_waypoints: the stops an overview {n} counts (n = position + 1). In the course
// style no stop-by counts, connected or not.
export function numberedStops<W extends { name: string; isStopBy?: boolean; connectToRoute?: boolean; pauseAtWaypoint?: boolean; skipAssetGeneration?: boolean }>(waypoints: W[], course = false): W[] {
  return waypoints.filter(
    (w, i) =>
      i !== 0 && i !== waypoints.length - 1 && !w.skipAssetGeneration &&
      !(w.isStopBy && (course || !(w.connectToRoute && w.pauseAtWaypoint !== false))),
  );
}

// Mirrors overview_cues._NAME_SUFFIXES: dropped to also accept a short form (加太駅 -> 加太).
const NAME_SUFFIXES = ["駅", "神社", "寺", "城", "公園", "港", "橋", "展望台", "資料館", "博物館"];

// Mirrors overview_cues.cue_name_mismatches: each {n} not followed by stop n's name.
export function cueNameMismatches(text: string, names: string[]): { n: number; said: string; expected: string }[] {
  const out: { n: number; said: string; expected: string }[] = [];
  for (const m of text.matchAll(/\{(\d+)\}/g)) {
    const n = Number(m[1]);
    const after = text.slice((m.index ?? 0) + m[0].length, (m.index ?? 0) + m[0].length + 40).replace(CUE, "").trimStart();
    const expected = names[n - 1] ?? "";
    const core = expected.replace(/[（(].*?[)）]/g, "").trim();
    const variants = [expected, core, ...NAME_SUFFIXES.filter((x) => core.endsWith(x) && core.length - x.length >= 2).map((x) => core.slice(0, -x.length))];
    if (!core || !variants.some((v) => v && after.startsWith(v))) {
      out.push({ n, said: after.split(/[、。をへに ]/)[0], expected });
    }
  }
  return out;
}
