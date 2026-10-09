import type { Waypoint } from "../../types";
import { withFoundPhotos } from "../../utils/photoCredits";
import type { PhotoCredit, PlaceQuery } from "../placePhotos";
import type { AiEngine } from "../ai/engine";
import { distanceKm, geocodeRoute, regionHintOf } from "../geocode";
import { cleanNarration, legOf } from "../narrationPrompt";
import { completeText, generateWaypointScriptStream } from "../ollamaApi";
import type { ProjectBrief } from "./brief";
import { extractCourseBrief, writeCourseIntro, type CourseBrief, type CourseStop } from "./courseBrief";

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
  uncertain: boolean[]; // the same, per waypoint (in the order of `waypoints`)
  photosAdded: number;
  overviewIntro: string; // spoken opening for the course overview, written from the document's course facts ("" when none)
  course: CourseBrief | null; // what the document said beyond place names, when it is a course guide
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

// Brochure and map PDFs hand the model their labels too; these are never a stop to visit.
const NOT_A_STOP = /\b(pref|prefecture|river|tunnel|line|view|slope|fork|branch|signpost|marker|repeater|intersection|attention|junction|main hall|start|goal)\b|[/|]/i;
const isStop = (name: string) => !NOT_A_STOP.test(name) && name.split(/\s+/).length <= 6 && !/^(temple|shrine|station|mt|mount|pass)\.?$/i.test(name);

// Trims, drops blanks, repeats and map labels, keeps the first-seen order, caps the count.
const WALK_KM_PER_HOUR = 5;
const JAPANESE = /[\u3040-\u30ff\u3400-\u9fff]/;

// How far apart two stops of a walk can be, from the minutes the document gives between them: generous (people walk
// 2-6 km/h, routes bend), so only a stop that could not be walked to in that time is questioned.
export function walkReachKm(minutes: number): number {
  return 1 + 2.5 * ((minutes / 60) * WALK_KM_PER_HOUR);
}

export function tidyPlaces(places: unknown[], cap = MAX_PLACES): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const p of places) {
    if (typeof p !== "string") continue;
    const name = p.trim();
    const key = name.toLowerCase().replace(/\s+/g, "");
    if (!name || seen.has(key) || !isStop(name)) continue;
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
  return `List the places a traveler visits, in the order they visit them, from the text below. Only the stops of the route itself (stations, temples, shrines, summits, passes, bus stops, landmarks the traveler reaches), starting at the start and ending at the goal; skip map labels such as rivers, tunnels, roads, lines, prefectures, towns used only as regions, and generic words like "Main Hall" or "Temple". If the text has a list of course times or an itinerary, follow that order. A brochure or map PDF is split into a "[text]" part (the written description: follow its order), a "[course times: stop -> time -> stop]" line (the course in order: use it for the order) and a "[labels and captions on the page: not in travel order]" part (map labels: use one only when the written text also visits it). Return ONLY a JSON array of place names, each specific enough to look up on a map (add the town or region when the text gives it). No other text.${hints ? `\n${hints}` : ""}\nText:\n${sourceText}`;
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
export function briefToScriptRequest(brief: ProjectBrief, stopCount: number, stop?: { index: number; excerpt?: string; kind?: "arriving" | "attraction"; returnTrip?: string }): string {
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
  if (stop?.returnTrip && last) {
    const english = brief.languages.length === 1 && brief.languages[0] === "en";
    lines.push(english ? `Getting back (say it in one closing sentence, using only this): ${stop.returnTrip}` : `帰り方(資料に書かれている内容だけを、最後に一言で伝える): ${stop.returnTrip}`);
  }
  if (stop?.excerpt) lines.push(`参考資料のこの場所に関する記述:\n${stop.excerpt}`);
  return lines.join("\n");
}

export async function buildProject({ brief, sourceText, engine, mapboxToken, signal, onProgress, photos }: BuildInput): Promise<BuiltProject> {
  onProgress({ step: "places", done: 0, total: 1, label: "" });
  // A course guide yields the stops with the document's own directions and times; any other text just yields place names.
  let course: CourseBrief | null = null;
  let places: string[];
  const details = new Map<string, CourseStop>();
  if (brief.places.length > 0) places = tidyPlaces(brief.places);
  else {
    course = await extractCourseBrief(sourceText, engine, signal);
    places = course ? tidyPlaces(course.stops.map((st) => st.name)) : [];
    if (places.length < 2) {
      course = null;
      places = await extractPlaces(brief, sourceText, engine, signal);
    } else for (const st of course!.stops) if (!details.has(st.name.trim())) details.set(st.name.trim(), st);
  }
  const walking = wantsWalking(brief) || course?.travel === "walking";
  onProgress({ step: "places", done: 1, total: 1, label: "" });

  onProgress({ step: "geocode", done: 0, total: places.length, label: "" });
  const { found, failed: failedPlaces } = await geocodeRoute(places, {
    mapboxToken,
    signal,
    onProgress: (done, label) => onProgress({ step: "geocode", done, total: places.length, label }),
    rename: (names, region) => localNames(names, region, engine, signal),
    hopKm: walking ? 15 : 40,
    regionHint: regionHintOf(sourceText),
  });
  onProgress({ step: "geocode", done: places.length, total: places.length, label: "" });

  if (walking) {
    for (let i = 1; i < found.length; i++) {
      const minutes = details.get(found[i].name.trim())?.minutes;
      if (minutes && distanceKm(found[i - 1].point, found[i].point) > walkReachKm(minutes)) found[i].uncertain = true;
    }
  }
  const mode = walking ? "walking" : "driving";
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
      const request = briefToScriptRequest(brief, waypoints.length, { index: i, kind, returnTrip: kind === "attraction" ? course?.returnTrip : undefined, excerpt: kind === "attraction" ? findExcerpt(sourceText, found[i].name) || findExcerpt(sourceText, found[i].shortName) || findExcerpt(sourceText, wp.name) : undefined });
      const withFacts = kind === "attraction" && !found[i].uncertain;
      const run = (userRequest: string) =>
        generateWaypointScriptStream(
          wp.name,
          userRequest,
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
          ...(brief.languages.length === 1 ? { language: brief.languages[0] } : {}),
            // What the document itself says about getting here from the previous stop (not for the first stop).
            ...(kind === "arriving" && i > 0 ? { directions: details.get(found[i].name.trim())?.directions, minutes: details.get(found[i].name.trim())?.minutes } : {}),
            // A guessed spot would give a wrong direction.
            ...(found[i].uncertain || found[i === 0 ? 1 : i - 1]?.uncertain ? {} : legOf(waypoints, i)),
          },

        );
      await run(request);
      // A small model sometimes answers an English video in Japanese: ask once more, firmly.
      if (englishOnly && JAPANESE.test(script)) {
        script = "";
        await run(`${request}\nIMPORTANT: Write the narration only in English. Do not use any Japanese characters.`);
      }
      if (kind === "arriving") wp.arrivingNarration = cleanNarration(script);
      else wp.attractionNarration = cleanNarration(script);
    }
  }
  onProgress({ step: "scripts", done: total, total, label: "" });

  const overviewIntro = course ? await writeCourseIntro(course, brief.languages[0] ?? "ja", engine, signal) : "";
  const uncertainPlaces = found.filter((f) => f.uncertain).map((f) => f.name);
  return { name: brief.name || `${places[0] ?? "My"} trip`, waypoints, failedPlaces, uncertainPlaces, uncertain: found.map((f) => f.uncertain), photosAdded, overviewIntro, course };
}
