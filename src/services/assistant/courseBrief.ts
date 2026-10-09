import type { AiEngine } from "../ai/engine";
import { completeText } from "../ollamaApi";

// What a trail brochure or itinerary says beyond place names: the stops in order, how to get from each to the next, the
// walking times, and the practical notes. Every field is optional: documents differ, and a model that cannot fill a field
// leaves it out.
export interface CourseStop {
  name: string;
  directions?: string; // how to get here from the previous stop, from the document's own words
  minutes?: number; // walking/travel time from the previous stop
}

export interface CourseBrief {
  stops: CourseStop[];
  travel?: "walking" | "driving";
  distance?: string;
  duration?: string;
  difficulty?: string;
  intro?: string;
  advice?: string[];
  outward?: string; // how to reach the start
  returnTrip?: string; // how to get back from the end to a main station
}

const MAX_SOURCE_CHARS = 14_000;
const MAX_DIRECTIONS_CHARS = 280;

export function courseBriefPrompt(sourceText: string): string {
  return `Read the text below, a course guide or itinerary, and return ONLY one JSON object (no other text) with these keys; leave out any key the text does not support, and never invent anything.
{"travel": "walking" or "driving", "stops": [{"name": "place name, specific enough for a map", "directions": "how to get here from the previous stop, in the text's own words, 1-2 sentences", "minutes": <a number, only when the text gives the time from the previous stop>}], "distance": "", "duration": "", "difficulty": "", "intro": "one sentence about the course", "advice": ["practical notes"], "outward": "how to reach the start", "returnTrip": "how to get back from the end"}
"stops" are only the places the traveler actually passes, in travel order from the start to the goal (stations, temples, summits, passes, bus stops). Map labels such as rivers, tunnels and roads are not stops. "minutes" is the time from the previous stop when the text gives one: a "[course times: stop -> time -> stop]" line lists the stops in order with the time between each pair (convert hours to minutes).
Text:
${sourceText.slice(0, MAX_SOURCE_CHARS)}`;
}

const text = (v: unknown): string | undefined => (typeof v === "string" && v.trim() ? v.trim() : undefined);

// Turns the model's reply into valid fields only; anything malformed is dropped, not guessed.
export function parseCourseBrief(reply: string): CourseBrief | null {
  const match = reply.match(/\{[\s\S]*\}/);
  let raw: any;
  try {
    raw = JSON.parse(match ? match[0] : reply);
  } catch {
    return null;
  }
  if (!raw || typeof raw !== "object" || !Array.isArray(raw.stops)) return null;
  const stops: CourseStop[] = [];
  for (const s of raw.stops) {
    const name = text(typeof s === "string" ? s : s?.name);
    if (!name) continue;
    const stop: CourseStop = { name };
    const directions = text(s?.directions);
    if (directions) stop.directions = directions.slice(0, MAX_DIRECTIONS_CHARS);
    const minutes = Number(s?.minutes);
    if (Number.isFinite(minutes) && minutes > 0 && minutes <= 600) stop.minutes = Math.round(minutes);
    stops.push(stop);
  }
  const brief: CourseBrief = { stops };
  if (raw.travel === "walking" || raw.travel === "driving") brief.travel = raw.travel;
  for (const key of ["distance", "duration", "difficulty", "intro", "outward", "returnTrip"] as const) {
    const v = text(raw[key]);
    if (v) brief[key] = v;
  }
  const advice = Array.isArray(raw.advice) ? raw.advice.map((a: unknown) => text(a)).filter((a: string | undefined): a is string => !!a) : [];
  if (advice.length) brief.advice = advice;
  return brief;
}

const TIMES_HEADER = "[course times";

// "1 hr. 20 min." -> 80; 0 when the text is not a duration.
export function minutesOf(text: string): number {
  const hours = text.match(/(\d+)\s*(?:hours?|hrs?|h|時間)/i);
  const minutes = text.match(/(\d+)\s*(?:minutes?|mins?|分)/i);
  return (hours ? parseInt(hours[1], 10) * 60 : 0) + (minutes ? parseInt(minutes[1], 10) : 0);
}

// The PDF reader writes a brochure's Course Times box as one line "A -> 15 min. -> B -> 1 hr. 20 min. -> C": the course in
// order with the time between stops. Read here in code, because a small model shifts the times by one stop.
export function parseCourseTimes(text: string): CourseStop[] {
  const at = text.indexOf(TIMES_HEADER);
  if (at < 0) return [];
  const line = text.slice(at).split("\n")[1] ?? "";
  const stops: CourseStop[] = [];
  let pending = 0;
  for (const token of line.split(" -> ").map((t) => t.trim())) {
    if (!token) continue;
    const m = /^(?:\d+\s*(?:hours?|hrs?|minutes?|mins?|h|時間|分)\.?\s*)+$/i.test(token) ? minutesOf(token) : 0;
    if (m > 0) {
      pending = m;
      continue;
    }
    const name = token.replace(/\s*\([^)]*\)\s*$/, "").trim();
    if (!name) continue;
    stops.push(pending > 0 && stops.length > 0 ? { name, minutes: pending } : { name });
    pending = 0;
  }
  return stops;
}

const stopKey = (name: string) =>
  name
    .toLowerCase()
    .replace(/\([^)]*\)/g, "")
    .replace(/\bsta\.?\b|\bstation\b/g, "")
    .replace(/[^a-z0-9぀-ヿ㐀-鿿]/g, "");

// The document's own order and minutes win; the model's directions are kept for the stops it names the same way.
export function mergeChain(chain: CourseStop[], brief: CourseBrief | null): CourseBrief {
  const byKey = new Map((brief?.stops ?? []).map((st) => [stopKey(st.name), st]));
  const stops = chain.map((st) => {
    const directions = byKey.get(stopKey(st.name))?.directions;
    return directions ? { ...st, directions } : st;
  });
  return { ...(brief ?? {}), stops, travel: brief?.travel ?? "walking" };
}

// null when the text has no usable course (then the plain place list is used instead).
export async function extractCourseBrief(sourceText: string, engine: AiEngine, signal?: AbortSignal): Promise<CourseBrief | null> {
  if (!sourceText.trim()) return null;
  const chain = parseCourseTimes(sourceText);
  let brief: CourseBrief | null = null;
  try {
    brief = parseCourseBrief(await completeText(courseBriefPrompt(sourceText), engine, signal, { num_predict: 1500 }));
  } catch (e: any) {
    if (e?.name === "AbortError" || signal?.aborted) throw e;
  }
  if (chain.length >= 2) return mergeChain(chain, brief);
  return brief && brief.stops.length >= 2 ? brief : null;
}

// The facts the introduction may use, one per line: nothing here is invented, so the introduction cannot be either.
export function introFacts(course: CourseBrief): string {
  return [
    course.intro && `Course: ${course.intro}`,
    course.distance && `Distance: ${course.distance}`,
    course.duration && `Walking time: ${course.duration}`,
    course.difficulty && `Difficulty: ${course.difficulty}`,
    course.advice?.length && `Advice: ${course.advice.slice(0, 3).join(" / ")}`,
    course.outward && `Getting there: ${course.outward}`,
  ]
    .filter(Boolean)
    .join("\n");
}

// A short spoken opening for the overview video ("course" style), from the course facts only. "" when there are none or the
// model fails: the overview then writes its own opening as before.
export async function writeCourseIntro(course: CourseBrief, language: "ja" | "en", engine: AiEngine, signal?: AbortSignal): Promise<string> {
  const facts = introFacts(course);
  if (!facts) return "";
  const prompt =
    language === "ja"
      ? `次の情報だけを使って、コース紹介動画の冒頭で読み上げるナレーションを日本語の話し言葉で2〜3文(120文字以内)で書いてください。情報にないことは書かず、記号や箇条書きは使わず、本文だけを出力してください。\n${facts}`
      : `Using only the facts below, write 2 or 3 spoken sentences (under 60 words) that open a video about this course. Do not add anything the facts do not say. No lists, no symbols, no title: output only the narration.\n${facts}`;
  try {
    return (await completeText(prompt, engine, signal, { num_predict: 300 })).replace(/^["「]|["」]$/g, "").replace(/\s+/g, " ").trim();
  } catch (e: any) {
    if (e?.name === "AbortError" || signal?.aborted) throw e;
    return "";
  }
}
