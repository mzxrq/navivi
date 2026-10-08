import { join } from "@tauri-apps/api/path";
import { exists, readDir, readTextFile, remove, writeTextFile } from "@tauri-apps/plugin-fs";
import { fileSystem } from "../config/constants";
import type { RecentProjects } from "../types";
import { aiEngine, type AiEngine } from "./ai/engine";
import { duplicateProjectFolder, loadProjectData } from "./fileSystem";
import { completeText } from "./ollamaApi";
import { syncProjectOnOpen } from "./projectStore";

export type VersionLanguage = "en" | "ja";

export const LANGUAGE_NAMES: Record<VersionLanguage, string> = { en: "English", ja: "Japanese" };
export const ENGLISH_KOKORO_VOICE = "af_heart";

const WAYPOINT_TEXT_FIELDS = ["arrivingNarration", "attractionNarration", "narration", "script", "voiceover"] as const;
const BATCH_CHARS = 2500;

type Config = Record<string, any>;
export type TextMap = Record<string, string>;

const isJapaneseChar = (c: string) => /[぀-ヿ㐀-鿿]/.test(c);

// The language a project's text is mostly in: Japanese when kana or kanji are a large share of its letters.
export function guessLanguage(texts: string[]): VersionLanguage {
  let japanese = 0;
  let latin = 0;
  for (const text of texts) {
    for (const c of text) {
      if (isJapaneseChar(c)) japanese += 1;
      else if (/[A-Za-z]/.test(c)) latin += 1;
    }
  }
  return japanese > 0 && japanese * 2 >= latin ? "ja" : "en";
}

const clean = (v: unknown): string => (typeof v === "string" ? v.trim() : "");

// Every piece of text the viewer reads or hears, keyed by where it lives: the stop names first, then the narration.
export function collectTexts(config: Config): { names: TextMap; scripts: TextMap } {
  const names: TextMap = {};
  const scripts: TextMap = {};
  (config.waypoints ?? []).forEach((wp: Config, i: number) => {
    if (clean(wp?.name)) names[`wp.${i}.name`] = wp.name.trim();
    for (const field of WAYPOINT_TEXT_FIELDS) if (clean(wp?.[field])) scripts[`wp.${i}.${field}`] = wp[field].trim();
  });
  for (const key of ["overview_narration", "video_title", "video_subtitle"]) if (clean(config[key])) scripts[key] = config[key].trim();
  if (clean(config.settings?.overview_title)) scripts["settings.overview_title"] = config.settings.overview_title.trim();
  return { names, scripts };
}

// A copy of the project's data in the other language. Readings for Japanese words, the detected area and the
// voice choice belong to the old language and are reset; the caller clears the generated files.
export function applyTranslations(config: Config, translated: TextMap, target: VersionLanguage, name: string): Config {
  const next: Config = JSON.parse(JSON.stringify(config));
  next.project_name = name;
  (next.waypoints ?? []).forEach((wp: Config, i: number) => {
    if (translated[`wp.${i}.name`]) wp.name = translated[`wp.${i}.name`];
    for (const field of WAYPOINT_TEXT_FIELDS) if (translated[`wp.${i}.${field}`]) wp[field] = translated[`wp.${i}.${field}`];
    delete wp.audioUrl;
    delete wp.timestamp;
  });
  for (const key of ["overview_narration", "video_title", "video_subtitle"]) if (translated[key]) next[key] = translated[key];
  // The pipeline replaces an auto-written overview script when the stops change: a translated one must stay.
  if (translated.overview_narration) next.overview_narration_is_auto = false;
  const settings: Config = (next.settings = { ...(next.settings ?? {}) });
  if (translated["settings.overview_title"]) settings.overview_title = translated["settings.overview_title"];
  settings.video_text_language = target;
  settings.pronunciation_dictionary = [];
  settings.global_pronunciation_dictionary = [];
  settings.intro_location_manual = false;
  settings.intro_location_at = "";
  delete settings.marked_regeneration_waypoints;
  if (target === "en") settings.tts = { engine: "kokoro", kokoro_voice: ENGLISH_KOKORO_VOICE, speed: settings.tts?.speed ?? 1 };
  else delete settings.tts;
  return next;
}

export function translationPrompt(items: TextMap, target: VersionLanguage, glossary: TextMap = {}): string {
  const to = LANGUAGE_NAMES[target];
  const from = LANGUAGE_NAMES[target === "en" ? "ja" : "en"];
  const terms = Object.entries(glossary);
  return `Translate each item from ${from} to ${to}. The items are the place names, titles and spoken narration of a travel video.
- Keep the meaning, the order and the number of sentences. Narration is spoken aloud: natural, plain ${to}, same tone as the original.
- Keep numbers, and keep cue tags such as {start}, {end}, {1} exactly where they are.
- Place names: use the form a map or guidebook in ${to} uses${target === "en" ? ' (Hepburn romanization plus the kind of place, e.g. "Sainen-ji Temple", "Mt. Kabuto", "Nishinosho Station")' : " (kanji and kana as shown on local maps)"}.
${terms.length ? `- Always use these names for these places:\n${terms.map(([a, b]) => `  ${a} => ${b}`).join("\n")}\n` : ""}Return ONLY a JSON object mapping each item id to its translation. No other text.
Items: ${JSON.stringify(items)}`;
}

// The translations a model returned, for the ids asked about only; anything that is not a non-empty string is left out.
export function parseTranslations(reply: string, ids: string[]): TextMap {
  const match = reply.match(/\{[\s\S]*\}/);
  try {
    const parsed = JSON.parse(match ? match[0] : reply);
    const out: TextMap = {};
    for (const id of ids) if (typeof parsed?.[id] === "string" && parsed[id].trim()) out[id] = parsed[id].trim();
    return out;
  } catch {
    return {};
  }
}

// Groups items so one request stays small enough for a short context window.
export function batches(items: TextMap, limit = BATCH_CHARS): TextMap[] {
  const out: TextMap[] = [];
  let current: TextMap = {};
  let size = 0;
  for (const [id, text] of Object.entries(items)) {
    if (size > 0 && size + text.length > limit) {
      out.push(current);
      current = {};
      size = 0;
    }
    current[id] = text;
    size += text.length;
  }
  if (size > 0) out.push(current);
  return out;
}

async function translate(
  items: TextMap,
  target: VersionLanguage,
  glossary: TextMap,
  engine: AiEngine,
  signal: AbortSignal | undefined,
  onDone: (n: number) => void,
): Promise<{ done: TextMap; failed: string[] }> {
  const done: TextMap = {};
  const failed: string[] = [];
  for (const batch of batches(items)) {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    let got: TextMap = {};
    for (let attempt = 0; attempt < 2 && Object.keys(got).length < Object.keys(batch).length; attempt++) {
      const missing = Object.fromEntries(Object.entries(batch).filter(([id]) => !got[id]));
      const reply = await completeText(translationPrompt(missing, target, glossary), engine, signal, { num_predict: 4000 });
      got = { ...got, ...parseTranslations(reply, Object.keys(missing)) };
    }
    Object.assign(done, got);
    failed.push(...Object.keys(batch).filter((id) => !got[id]));
    onDone(Object.keys(batch).length);
  }
  return { done, failed };
}

// What a finished video baked in the old language, plus the audio and captions made from the old text. The route, stops, photos
// and the user's own clips (assets/video/user) stay.
export const LANGUAGE_BOUND_PATHS = ["timeline.json", "assets/audio", "assets/subtitles", ".navivi/narration_cues.json", ".navivi/overview_narration.json"];

async function clearGenerated(dir: string): Promise<void> {
  for (const rel of LANGUAGE_BOUND_PATHS) {
    const path = await join(dir, ...rel.split("/"));
    if (await exists(path)) await remove(path, { recursive: true });
  }
  const video = await join(dir, "assets", "video");
  if (await exists(video)) {
    for (const entry of await readDir(video)) {
      if (entry.name && entry.name !== "user") await remove(await join(video, entry.name), { recursive: true });
    }
  }
}

export interface LanguageVersionProgress {
  step: "copy" | "names" | "scripts" | "files";
  done: number;
  total: number;
}

export interface LanguageVersionResult {
  dir: string;
  untranslated: number; // texts the model did not return; they stay in the old language
}

export async function createLanguageVersion(input: {
  source: RecentProjects;
  target: VersionLanguage;
  name: string;
  signal?: AbortSignal;
  onProgress?: (p: LanguageVersionProgress) => void;
}): Promise<LanguageVersionResult> {
  const { source, target, name, signal, onProgress } = input;
  if (source.path.toLowerCase().endsWith(`.${fileSystem.extensions.project}`)) {
    throw new Error("This project is still an archive file. Open it once, then make a version of it.");
  }
  onProgress?.({ step: "copy", done: 0, total: 1 });
  const dir = await duplicateProjectFolder(source.path, name);
  try {
    const configPath = await join(dir, fileSystem.configFile);
    const config: Config = JSON.parse(await readTextFile(configPath));
    const engine = aiEngine(config.settings ?? {});
    const { names, scripts } = collectTexts(config);
    const total = Object.keys(names).length + Object.keys(scripts).length;
    let finished = 0;
    const tick = (n: number) => {
      finished += n;
      return finished;
    };

    onProgress?.({ step: "names", done: 0, total });
    const namesDone = await translate(names, target, {}, engine, signal, (n) => onProgress?.({ step: "names", done: tick(n), total }));
    // The narration is translated with the same names, so a stop is called one thing everywhere.
    const glossary: TextMap = {};
    for (const [id, text] of Object.entries(namesDone.done)) glossary[names[id]] = text;
    const scriptsDone = await translate(scripts, target, glossary, engine, signal, (n) => onProgress?.({ step: "scripts", done: tick(n), total }));

    const next = applyTranslations(config, { ...namesDone.done, ...scriptsDone.done }, target, name);
    onProgress?.({ step: "files", done: 0, total: 1 });
    await clearGenerated(dir);
    await writeTextFile(configPath, JSON.stringify(next, null, 2));

    const loaded = await loadProjectData(dir);
    if (!loaded) throw new Error("The new version could not be opened.");
    await syncProjectOnOpen(loaded.data, loaded.selectedPath);
    return { dir, untranslated: namesDone.failed.length + scriptsDone.failed.length };
  } catch (e) {
    // A half-made copy would sit in the project list untranslated; take it away again.
    try {
      await remove(dir, { recursive: true });
    } catch {
      // nothing more to do
    }
    throw e;
  }
}
