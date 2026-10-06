export interface ReadingEntry {
  word: string;
  reading: string;
  auto?: boolean;
}

// Folds a MeCab scan of every script into the project dictionary: manual entries are never touched,
// new words come in as `auto`, and `auto` words no script uses any more (or the shared dictionary now covers) go.
// Returns null when nothing changed, so callers don't mark the project dirty for nothing.
export function mergeAutoReadings(
  current: ReadingEntry[],
  scanned: { word: string; reading: string }[],
  shared: { word: string }[],
): ReadingEntry[] | null {
  const sharedWords = new Set(shared.map((e) => e.word));
  const scannedWords = new Set(scanned.map((e) => e.word));
  const next = current.filter((e) => !e.auto || (scannedWords.has(e.word) && !sharedWords.has(e.word)));
  const known = new Set(next.map((e) => e.word));
  for (const { word, reading } of scanned) {
    if (!word || !reading || known.has(word) || sharedWords.has(word)) continue;
    next.push({ word, reading, auto: true });
    known.add(word);
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
