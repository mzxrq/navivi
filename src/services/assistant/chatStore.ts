import { join } from "@tauri-apps/api/path";
import { exists, readTextFile, remove, writeTextFile } from "@tauri-apps/plugin-fs";
import { EMPTY_BRIEF, ProjectBrief } from "./brief";
import type { ChatMessage, Source } from "./converse";

// A project's assistant chat, kept in the project folder as `assistant.json` so that opening, duplicating or sharing the
// project brings the conversation along. It is the user's own work (not rebuildable like `.navivi/`), hence the root.
export const CHAT_FILE = "assistant.json";
const VERSION = 1;
const MAX_MESSAGES = 200;

export interface StoredChat {
  messages: ChatMessage[];
  brief: ProjectBrief;
  sources: Source[];
  attachments: { gpx: string | null; photos: string[] };
}

export const emptyChat = (): StoredChat => ({ messages: [], brief: EMPTY_BRIEF, sources: [], attachments: { gpx: null, photos: [] } });

export const hasContent = (chat: StoredChat) =>
  chat.messages.length > 0 || chat.sources.length > 0 || chat.attachments.gpx !== null || chat.attachments.photos.length > 0 || JSON.stringify(chat.brief) !== JSON.stringify(EMPTY_BRIEF);

const isMessage = (m: unknown): m is ChatMessage =>
  !!m && typeof m === "object" && ((m as ChatMessage).role === "user" || (m as ChatMessage).role === "assistant") && typeof (m as ChatMessage).text === "string";
const isSource = (s: unknown): s is Source => !!s && typeof s === "object" && typeof (s as Source).name === "string" && typeof (s as Source).text === "string";

// Accepts anything that was read from disk: a damaged, hand-edited or newer file gives what can be used, never a crash.
export function parseChat(text: string): StoredChat | null {
  let raw: any;
  try {
    raw = JSON.parse(text);
  } catch {
    return null;
  }
  if (!raw || typeof raw !== "object" || raw.version !== VERSION) return null;
  const messages = (Array.isArray(raw.messages) ? raw.messages.filter(isMessage) : []).slice(-MAX_MESSAGES).map((m: ChatMessage) => ({
    role: m.role,
    text: m.text,
    ...(Array.isArray(m.files) ? { files: m.files.filter((f) => typeof f === "string") } : {}),
  }));
  const attachments = raw.attachments ?? {};
  return {
    messages,
    brief: { ...EMPTY_BRIEF, ...(raw.brief && typeof raw.brief === "object" ? raw.brief : {}) },
    sources: Array.isArray(raw.sources) ? raw.sources.filter(isSource).map((s: Source) => ({ name: s.name, text: s.text })) : [],
    attachments: {
      gpx: typeof attachments.gpx === "string" ? attachments.gpx : null,
      photos: Array.isArray(attachments.photos) ? attachments.photos.filter((p: unknown) => typeof p === "string") : [],
    },
  };
}

export const serializeChat = (chat: StoredChat) =>
  JSON.stringify({ version: VERSION, ...chat, messages: chat.messages.slice(-MAX_MESSAGES) }, null, 1);

// Files the user attached may be gone by now (a moved or shared project): the chat keeps working without them.
async function keepExisting(chat: StoredChat): Promise<StoredChat> {
  const present = async (p: string) => exists(p).catch(() => false);
  const photos: string[] = [];
  for (const p of chat.attachments.photos) if (await present(p)) photos.push(p);
  const gpx = chat.attachments.gpx && (await present(chat.attachments.gpx)) ? chat.attachments.gpx : null;
  return { ...chat, attachments: { gpx, photos } };
}

export async function loadChat(dir: string): Promise<StoredChat | null> {
  try {
    const file = await join(dir, CHAT_FILE);
    if (!(await exists(file))) return null;
    const parsed = parseChat(await readTextFile(file));
    return parsed ? await keepExisting(parsed) : null;
  } catch (e) {
    console.error("Could not read the assistant chat:", e);
    return null;
  }
}

export async function saveChat(dir: string, chat: StoredChat): Promise<void> {
  const file = await join(dir, CHAT_FILE);
  if (!hasContent(chat)) {
    await remove(file).catch(() => {});
    return;
  }
  await writeTextFile(file, serializeChat(chat));
}
