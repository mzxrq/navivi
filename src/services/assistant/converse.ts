import type { AiEngine } from "../ai/engine";
import { completeText } from "../ollamaApi";
import { cleanBriefPatch, mergeBrief, missingForBuild, ProjectBrief } from "./brief";

export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  files?: string[]; // names of what the user attached with this message
}

export interface Source {
  name: string;
  text: string;
}

export interface ConverseResult {
  reply: string;
  patch: Partial<ProjectBrief>;
  ready: boolean; // enough is known to build the project
}

const HISTORY_TURNS = 8;
const SOURCE_CHARS = 6000; // a local model's default context is small; the builder reads the full text itself
const MESSAGE_CHARS = 1500;

const RULES = `You are the project assistant inside Navivi, an app that turns places and routes into narrated map-route travel videos.
The user describes the video they want, and may attach an itinerary, pamphlet or notes. You fill in a project brief for them.

How to behave:
- Reply in the language of the user's LAST message (Japanese message: Japanese reply), in one to three short sentences. Plain, warm, no emoji, no lists unless asked.
- Take everything you can from the user's words and the attached documents and put it in the brief yourself. Never ask for something the documents already say.
- Ask at most ONE question per reply, and only when the answer would change the video. If the user seems to want you to just decide ("whatever", "you pick", "just do it"), pick sensible defaults and say what you chose.
- Do not invent facts about places. Place names go in "places" in travel order, the way a map search would find them (add the area, e.g. "Kumano Hongu Taisha, Wakayama"). Copy place names exactly as written in the documents or by the user: never translate or reword them, whatever language the video will be in.
- When the brief has places, tell the user what you are going to make in one sentence and that they can press "Create project". Do not claim the project is already created.

After your reply, output the fields you want to set or change, and nothing else, as JSON in this exact tag, even when empty:
<brief>{"name": "", "purpose": "", "audience": "", "languages": ["ja"], "durationMin": 5, "tone": "", "wordCount": {"min": 500, "max": 800}, "scope": "", "mustInclude": [], "avoid": [], "visuals": "", "callToAction": "", "places": []}</brief>
Include only the keys that changed. languages uses "ja" and "en". Lists you send replace the old list, so send the full list.
Field meanings: name = short project title. purpose = why the video exists. audience = who watches. languages = narration languages. durationMin = video length in minutes. tone = how it sounds (e.g. cinematic, calm). wordCount = total narration words. scope = what the script covers. mustInclude = things the script must mention. avoid = topics or styles to leave out (e.g. "complex history"). visuals = what the picture shows. callToAction = what the viewer is invited to do at the end of the video (not an app button). places = stops in order.
Write the <brief> tag exactly as shown, opening tag included.`;

export function buildConversePrompt(input: { history: ChatMessage[]; brief: ProjectBrief; sources: Source[] }): string {
  const sources = input.sources.length
    ? input.sources.map((s) => `--- ${s.name} ---\n${s.text.slice(0, SOURCE_CHARS)}`).join("\n\n")
    : "(none attached)";
  const turns = input.history
    .slice(-HISTORY_TURNS)
    .map((m) => `${m.role === "user" ? "User" : "Assistant"}: ${m.text.slice(0, MESSAGE_CHARS)}${m.files?.length ? ` [attached: ${m.files.join(", ")}]` : ""}`)
    .join("\n");
  return `${RULES}

Current brief:
${JSON.stringify(input.brief)}

Attached documents:
${sources}

Conversation so far:
${turns}
Assistant:`;
}

// The first balanced {...} at or after `from`, string-aware; null when it never closes.
function balancedObject(text: string, from: number): string | null {
  let depth = 0;
  let inString = false;
  for (let i = from; i < text.length; i++) {
    const c = text[i];
    if (inString) {
      if (c === "\\") i++;
      else if (c === '"') inString = false;
    } else if (c === '"') inString = true;
    else if (c === "{") depth++;
    else if (c === "}" && --depth === 0) return text.slice(from, i + 1);
  }
  return null;
}

// Small local models often drop the opening <brief> tag, so the JSON is also found by its first known key.
const BRIEF_KEY = /\{\s*"(?:name|purpose|audience|languages|durationMin|tone|wordCount|scope|mustInclude|avoid|visuals|callToAction|places)"/;

export function parseConverseReply(raw: string): { reply: string; patch: Partial<ProjectBrief> } {
  const tag = raw.indexOf("<brief>");
  const start = tag >= 0 ? raw.indexOf("{", tag) : raw.search(BRIEF_KEY);
  const replyEnd = tag >= 0 ? tag : start >= 0 ? start : raw.length;
  const reply = raw
    .slice(0, replyEnd)
    .replace(/^\s*Assistant:\s*/i, "")
    .replace(/```(?:json)?/g, "")
    .replace(/<\/?brief>/g, "")
    .trim();
  const json = start >= 0 ? balancedObject(raw, start) : null;
  if (!json) return { reply, patch: {} };
  try {
    return { reply, patch: cleanBriefPatch(JSON.parse(json)) };
  } catch {
    return { reply, patch: {} };
  }
}

// A model told to change the video's language sometimes translates the place names too, which would break the map search.
// Same number of stops with none of the old names left is that case; keep the old list.
export function guardPlaces(brief: ProjectBrief, patch: Partial<ProjectBrief>): Partial<ProjectBrief> {
  const next = patch.places;
  if (!next || brief.places.length === 0) return patch;
  const kept = brief.places.some((p) => next.includes(p));
  if (!kept && next.length === brief.places.length) {
    const { places: _dropped, ...rest } = patch;
    return rest;
  }
  return patch;
}

export async function converse(input: { history: ChatMessage[]; brief: ProjectBrief; sources: Source[]; engine: AiEngine; signal?: AbortSignal }): Promise<ConverseResult> {
  const raw = await completeText(buildConversePrompt(input), input.engine, input.signal, { num_ctx: 8192, num_predict: 700 });
  const parsed = parseConverseReply(raw);
  const patch = guardPlaces(input.brief, parsed.patch);
  const reply = parsed.reply.replace(/^\s*(?:places|avoid|mustInclude)\s*:.*$/gim, "").trim();
  const next = mergeBrief(input.brief, patch);
  return { reply, patch, ready: missingForBuild(next).length === 0 };
}
