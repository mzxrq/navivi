export interface ReadingEntry {
  word: string;
  reading: string;
  auto?: boolean;
}

// The same word however it was typed: "友ヶ島 小展望台" = "友ヶ島小展望台", full-width = half-width.
const key = (word: string) => word.normalize("NFKC").replace(/\s/g, "");
export const sameWord = (a: string, b: string) => key(a) === key(b);

// Folds a MeCab scan of every script into the project dictionary: manual entries are never touched,
// new words come in as `auto`, and `auto` words no script uses any more (or that a manual or shared entry,
// or an earlier auto one, already covers) go. Returns null when nothing changed, so callers don't mark the
// project dirty for nothing.
export function mergeAutoReadings(
  current: ReadingEntry[],
  scanned: { word: string; reading: string }[],
  shared: { word: string }[],
): ReadingEntry[] | null {
  const sharedWords = new Set(shared.map((e) => key(e.word)));
  const manualWords = new Set(current.filter((e) => !e.auto).map((e) => key(e.word)));
  const scannedReading = new Map<string, string>();
  for (const e of scanned) if (!scannedReading.has(key(e.word))) scannedReading.set(key(e.word), e.reading);
  const known = new Set(manualWords);
  // An auto word takes the scan's latest reading, so a fix in the reading lookup reaches projects scanned before it.
  const next = current
    .filter((e) => {
      if (!e.auto) return true;
      const k = key(e.word);
      if (!scannedReading.has(k) || sharedWords.has(k) || known.has(k)) return false;
      known.add(k);
      return true;
    })
    .map((e) => {
      const reading = e.auto ? scannedReading.get(key(e.word)) : undefined;
      return reading && reading !== e.reading ? { ...e, reading } : e;
    });
  for (const { word, reading } of scanned) {
    if (!word || !reading || known.has(key(word)) || sharedWords.has(key(word))) continue;
    next.push({ word, reading, auto: true });
    known.add(key(word));
  }
  const same = next.length === current.length && next.every((e, i) => e === current[i]);
  return same ? null : next;
}

// Every narration the voice speaks, one per line, for a single scan.
export function narrationText(
  waypoints: { arrivingNarration?: string; attractionNarration?: string }[],
  overview?: string,
): string {
  return [overview, ...waypoints.flatMap((w) => [w.arrivingNarration, w.attractionNarration])]
    .map((s) => (s ?? "").trim())
    .filter(Boolean)
    .join("\n");
}
