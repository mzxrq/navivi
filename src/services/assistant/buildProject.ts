import type { Waypoint } from "../../types";
import { withFoundPhotos } from "../../utils/photoCredits";
import type { PhotoCredit, PlaceQuery } from "../placePhotos";
import type { AiEngine } from "../ai/engine";
import { geocodeRoute } from "../geocode";
import { cleanNarration, legOf } from "../narrationPrompt";
import { completeText, generateWaypointScriptStream } from "../ollamaApi";
import type { ProjectBrief } from "./brief";

export interface BuildProgress {
  step: "places" | "geocode" | "photos" | "scripts";
  done: number;
  total: number;
  label: string;
}

export interface BuiltProject {
  name: string;
  waypoints: Waypoint[];
  failedPlaces: string[];
  uncertainPlaces: string[]; // placed, but only by a wider search: worth a look on the map
  photosAdded: number;
}

// Looks for photos of a stop and brings them onto this PC (see placePhotos.ts); passed in so building stays testable offline.
export type PhotoFinder = (stop: PlaceQuery) => Promise<{ path: string; credit: PhotoCredit }[]>;

interface BuildInput {
  brief: ProjectBrief;
  sourceText: string;
  engine: AiEngine;
  mapboxToken?: string;
  signal?: AbortSignal;
  onProgress: (p: BuildProgress) => void;
  photos?: PhotoFinder;
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

// Maps and OpenStreetMap index most small places under their own script, so a miss is retried under the local name.
export async function localNames(names: string[], region: string | null, engine: AiEngine, signal?: AbortSignal): Promise<Record<string, string>> {
  if (names.length === 0) return {};
  const where = region ? `in ${region} (Japan if it is a Japanese area)` : "";
  const prompt = `Give the name each of these places has on local maps ${where}: the original script (for Japanese places: kanji and kana, e.g. "Sainen-ji Temple" -> "西念寺", "Nishinosho Sta." -> "西ノ庄駅"). Use the exact spelling a map shows; do not guess characters for a name you are unsure of. Return ONLY a JSON object mapping each input exactly as written to its local name. If you do not know a place, map it to itself.
Places: ${JSON.stringify(names)}`;
  const reply = await completeText(prompt, engine, signal, { num_predict: 600 });
  const match = reply.match(/\{[\s\S]*\}/);
  try {
    const parsed = JSON.parse(match ? match[0] : reply);
    const out: Record<string, string> = {};
    for (const name of names) if (typeof parsed?.[name] === "string" && parsed[name].trim() && parsed[name] !== name) out[name] = parsed[name].trim();
    return out;
  } catch {
    return {};
  }
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
// `kind` "arriving" is the short narration while travelling to the stop: only the voice of the video applies, not its length,
// facts or call to action.
export function briefToScriptRequest(brief: ProjectBrief, stopCount: number, stop?: { index: number; excerpt?: string; kind?: "arriving" | "attraction" }): string {
  const lines: string[] = [];
  const last = stop !== undefined && stopCount > 0 && stop.index === stopCount - 1;
  const arriving = stop?.kind === "arriving";
  if (brief.tone) lines.push(`トーン: ${brief.tone}`);
  if (brief.audience) lines.push(`対象視聴者: ${brief.audience}`);
  if (brief.languages.length === 1 && brief.languages[0] === "en") lines.push("ナレーションは英語で書くこと");
  if (brief.avoid.length > 0) lines.push(`避けること: ${brief.avoid.join("、")}`);
  if (arriving) return lines.join("\n");
  const length = perStopLength(brief, stopCount);
  if (length) lines.push(length);
  if (brief.mustInclude.length > 0) lines.push(`含めること: ${brief.mustInclude.join("、")}`);
  if (brief.purpose && (stop === undefined || stop.index === 0 || last)) lines.push(`この動画の目的: ${brief.purpose}`);
  if (brief.callToAction && last) lines.push(`最後に行動を促す: ${brief.callToAction}`);
  if (stop?.excerpt) lines.push(`参考資料のこの場所に関する記述:\n${stop.excerpt}`);
  return lines.join("\n");
}

export async function buildProject({ brief, sourceText, engine, mapboxToken, signal, onProgress, photos }: BuildInput): Promise<BuiltProject> {
  onProgress({ step: "places", done: 0, total: 1, label: "" });
  const places = brief.places.length > 0 ? tidyPlaces(brief.places) : await extractPlaces(brief, sourceText, engine, signal);
  onProgress({ step: "places", done: 1, total: 1, label: "" });

  onProgress({ step: "geocode", done: 0, total: places.length, label: "" });
  const { found, failed: failedPlaces } = await geocodeRoute(places, {
    mapboxToken,
    signal,
    onProgress: (done, label) => onProgress({ step: "geocode", done, total: places.length, label }),
    rename: (names, region) => localNames(names, region, engine, signal),
    hopKm: wantsWalking(brief) ? 15 : 40,
  });
  onProgress({ step: "geocode", done: places.length, total: places.length, label: "" });

  const mode = wantsWalking(brief) ? "walking" : "driving";
  // Stops are named in the language of the video: a Japanese video does not show "Sainen-ji Temple, Wakayama" over a Japanese script.
  const englishOnly = brief.languages.length === 1 && brief.languages[0] === "en";
  const waypoints: Waypoint[] = found.map(({ shortName, localName, point }) => ({
    id: crypto.randomUUID(),
    name: englishOnly ? shortName : localName ?? shortName,
    lat: point.lat,
    lng: point.lng,
    routeMode: mode,
    images: [],
    imagePans: [],
  }));

  // A bonus: a stop without photos is still a good stop, so a lookup that fails only leaves it as it was.
  let photosAdded = 0;
  if (photos) {
    for (const [i, wp] of waypoints.entries()) {
      abortIfNeeded(signal);
      onProgress({ step: "photos", done: i, total: waypoints.length, label: wp.name });
      try {
        const patch = withFoundPhotos(wp, await photos({ name: wp.name, lat: wp.lat, lng: wp.lng, uncertain: found[i].uncertain }));
        if (patch) {
          photosAdded += (patch.images?.length ?? 0) - (wp.images?.length ?? 0);
          Object.assign(wp, patch);
        }
      } catch (e) {
        if (signal?.aborted) throw e;
      }
    }
    onProgress({ step: "photos", done: waypoints.length, total: waypoints.length, label: "" });
  }

  // Both boxes of a stop: the short narration while travelling there, then the one spoken over its photos.
  // Only the second looks up facts, and not for a guessed spot (0, 0 skips it): they would describe the wrong place.
  const total = waypoints.length * 2;
  for (const [i, wp] of waypoints.entries()) {
    for (const [k, kind] of (["arriving", "attraction"] as const).entries()) {
      abortIfNeeded(signal);
      onProgress({ step: "scripts", done: i * 2 + k, total, label: wp.name });
      let script = "";
      const withFacts = kind === "attraction" && !found[i].uncertain;
      await generateWaypointScriptStream(
        wp.name,
        briefToScriptRequest(brief, waypoints.length, { index: i, kind, excerpt: kind === "attraction" ? findExcerpt(sourceText, found[i].name) || findExcerpt(sourceText, found[i].shortName) || findExcerpt(sourceText, wp.name) : undefined }),
        engine,
        brief.name,
        (chunk) => {
          script = chunk;
        },
        withFacts ? wp.lat : 0,
        withFacts ? wp.lng : 0,
        [],
        undefined,
        kind,
        i === 0,
        signal,
        {
          previous: waypoints[i - 1]?.name,
          next: waypoints[i + 1]?.name,
          index: i,
          total: waypoints.length,
          otherScript: kind === "attraction" ? wp.arrivingNarration : undefined,
          otherStops: waypoints.slice(0, i).map((w) => (kind === "arriving" ? w.arrivingNarration : w.attractionNarration) ?? ""),
          // A guessed spot would give a wrong direction.
          ...(found[i].uncertain || found[i === 0 ? 1 : i - 1]?.uncertain ? {} : legOf(waypoints, i)),
        },
      );
      if (kind === "arriving") wp.arrivingNarration = cleanNarration(script);
      else wp.attractionNarration = cleanNarration(script);
    }
  }
  onProgress({ step: "scripts", done: total, total, label: "" });

  const uncertainPlaces = found.filter((f) => f.uncertain).map((f) => f.name);
  return { name: brief.name || `${places[0] ?? "My"} trip`, waypoints, failedPlaces, uncertainPlaces, photosAdded };
}
