import type { Waypoint } from "../../types";
import type { AiEngine } from "../ai/engine";
import { geocodePlace, type GeoPoint } from "../geocode";
import { cleanNarration } from "../narrationPrompt";
import { completeText, generateWaypointScriptStream } from "../ollamaApi";
import type { ProjectBrief } from "./brief";

export interface BuildProgress {
  step: "places" | "geocode" | "scripts";
  done: number;
  total: number;
  label: string;
}

export interface BuiltProject {
  name: string;
  waypoints: Waypoint[];
  failedPlaces: string[];
}

interface BuildInput {
  brief: ProjectBrief;
  sourceText: string;
  engine: AiEngine;
  mapboxToken?: string;
  signal?: AbortSignal;
  onProgress: (p: BuildProgress) => void;
}

const MAX_PLACES = 25;
const EXCERPT_CHARS = 600;
// A narrator reads roughly this many Japanese characters per minute.
const SPOKEN_CHARS_PER_MIN = 300;

const abortIfNeeded = (signal?: AbortSignal) => {
  if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
};

// Trims, drops blanks and repeats (ignoring case and spacing), keeps the first-seen order, caps the count.
export function tidyPlaces(places: unknown[], cap = MAX_PLACES): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const p of places) {
    if (typeof p !== "string") continue;
    const name = p.trim();
    const key = name.toLowerCase().replace(/\s+/g, "");
    if (!name || seen.has(key)) continue;
    seen.add(key);
    out.push(name);
    if (out.length >= cap) break;
  }
  return out;
}

function parsePlaces(reply: string): string[] {
  const match = reply.match(/\[[\s\S]*\]/);
  try {
    const parsed = JSON.parse(match ? match[0] : reply);
    return Array.isArray(parsed) ? tidyPlaces(parsed) : [];
  } catch {
    return [];
  }
}

export function placesPrompt(brief: ProjectBrief, sourceText: string): string {
  const hints = [brief.scope && `Scope: ${brief.scope}`, brief.mustInclude.length > 0 && `Must include: ${brief.mustInclude.join(", ")}`]
    .filter(Boolean)
    .join("\n");
  return `List the places a traveler visits, in the order they visit them, from the text below. Return ONLY a JSON array of place names, each specific enough to look up on a map (add the town or region when the text gives it). No other text.${hints ? `\n${hints}` : ""}\nText:\n${sourceText}`;
}

async function extractPlaces(brief: ProjectBrief, sourceText: string, engine: AiEngine, signal?: AbortSignal): Promise<string[]> {
  if (!sourceText.trim()) return [];
  return parsePlaces(await completeText(placesPrompt(brief, sourceText), engine, signal));
}

// The passage of the source that talks about `place`, starting at a sentence boundary, for the narrator to draw on.
export function findExcerpt(source: string, place: string, cap = EXCERPT_CHARS): string {
  const text = source.replace(/\r/g, "");
  const names = [place, place.split(/[\s、,・]+/)[0]].filter((n) => n && n.length >= 2);
  for (const name of names) {
    const at = text.toLowerCase().indexOf(name.toLowerCase());
    if (at < 0) continue;
    const before = Math.max(text.lastIndexOf("\n", at), text.lastIndexOf("。", at), text.lastIndexOf(". ", at));
    const start = before < 0 || at - before > 120 ? Math.max(0, at - 40) : before + 1;
    return text.slice(start, start + cap).trim();
  }
  return "";
}

const wantsWalking = (brief: ProjectBrief) => /walk|pilgrimage|徒歩|巡礼|散策/i.test(`${brief.scope} ${brief.visuals} ${brief.purpose}`);

// The length each stop's script should have, from the brief's word count or, failing that, its running time.
function perStopLength(brief: ProjectBrief, stopCount: number): string {
  const stops = Math.max(1, stopCount);
  if (brief.wordCount) {
    const min = Math.max(20, Math.round(brief.wordCount.min / stops));
    const max = Math.max(min, Math.round(brief.wordCount.max / stops));
    return `1か所あたり${min}〜${max}語を目安にする`;
  }
  if (brief.durationMin) {
    const chars = Math.round((brief.durationMin * SPOKEN_CHARS_PER_MIN) / stops / 10) * 10;
    return `1か所あたり${Math.max(60, chars)}文字前後(動画全体で約${brief.durationMin}分)にする`;
  }
  return "";
}

// The "user requests" text for one stop's script (it goes under the prompt's highest-priority request heading).
export function briefToScriptRequest(brief: ProjectBrief, stopCount: number, stop?: { index: number; excerpt?: string }): string {
  const lines: string[] = [];
  const last = stop !== undefined && stopCount > 0 && stop.index === stopCount - 1;
  if (brief.tone) lines.push(`トーン: ${brief.tone}`);
  if (brief.audience) lines.push(`対象視聴者: ${brief.audience}`);
  if (brief.languages.length === 1 && brief.languages[0] === "en") lines.push("ナレーションは英語で書くこと");
  const length = perStopLength(brief, stopCount);
  if (length) lines.push(length);
  if (brief.mustInclude.length > 0) lines.push(`含めること: ${brief.mustInclude.join("、")}`);
  if (brief.avoid.length > 0) lines.push(`避けること: ${brief.avoid.join("、")}`);
  if (brief.purpose && (stop === undefined || stop.index === 0 || last)) lines.push(`この動画の目的: ${brief.purpose}`);
  if (brief.callToAction && last) lines.push(`最後に行動を促す: ${brief.callToAction}`);
  if (stop?.excerpt) lines.push(`参考資料のこの場所に関する記述:\n${stop.excerpt}`);
  return lines.join("\n");
}

export async function buildProject({ brief, sourceText, engine, mapboxToken, signal, onProgress }: BuildInput): Promise<BuiltProject> {
  onProgress({ step: "places", done: 0, total: 1, label: "" });
  const places = brief.places.length > 0 ? tidyPlaces(brief.places) : await extractPlaces(brief, sourceText, engine, signal);
  onProgress({ step: "places", done: 1, total: 1, label: "" });

  const found: { name: string; point: GeoPoint }[] = [];
  const failedPlaces: string[] = [];
  for (const [i, place] of places.entries()) {
    abortIfNeeded(signal);
    onProgress({ step: "geocode", done: i, total: places.length, label: place });
    const point = await geocodePlace(place, { mapboxToken, near: found[found.length - 1]?.point, signal });
    if (point) found.push({ name: place, point });
    else failedPlaces.push(place);
  }
  onProgress({ step: "geocode", done: places.length, total: places.length, label: "" });

  const mode = wantsWalking(brief) ? "walking" : "driving";
  const waypoints: Waypoint[] = found.map(({ name, point }) => ({
    id: crypto.randomUUID(),
    name,
    lat: point.lat,
    lng: point.lng,
    routeMode: mode,
    images: [],
    imagePans: [],
  }));

  for (const [i, wp] of waypoints.entries()) {
    abortIfNeeded(signal);
    onProgress({ step: "scripts", done: i, total: waypoints.length, label: wp.name });
    let script = "";
    await generateWaypointScriptStream(
      wp.name,
      briefToScriptRequest(brief, waypoints.length, { index: i, excerpt: findExcerpt(sourceText, wp.name) }),
      engine,
      brief.name,
      (chunk) => {
        script = chunk;
      },
      wp.lat,
      wp.lng,
      [],
      undefined,
      "attraction",
      i === 0,
      signal,
      { previous: waypoints[i - 1]?.name, next: waypoints[i + 1]?.name, index: i, total: waypoints.length },
    );
    wp.attractionNarration = cleanNarration(script);
  }
  onProgress({ step: "scripts", done: waypoints.length, total: waypoints.length, label: "" });

  return { name: brief.name || `${places[0] ?? "My"} trip`, waypoints, failedPlaces };
}
