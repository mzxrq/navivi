import { fetch } from "@tauri-apps/plugin-http";
import { getApiKey } from "./keys";
import {
  buildRequest,
  errorMessage,
  listModelsRequest,
  parseModelList,
  PROVIDERS,
  textDelta,
  type OnlineProvider,
  type OnlineTarget,
  type ScriptRequest,
} from "./providers";
import { SseParser } from "./sse";

export class MissingKeyError extends Error {
  constructor(public provider: OnlineProvider) {
    super(`No API key for ${PROVIDERS[provider].label}. Add one in Settings > AI models.`);
  }
}

export async function hasApiKey(provider: OnlineProvider): Promise<boolean> {
  try {
    return !!(await getApiKey(provider));
  } catch {
    return false;
  }
}

const HINTS: Record<number, string> = {
  401: "Check the API key.",
  403: "This key is not allowed to use that model.",
  404: "The model or address was not found.",
  429: "Too many requests, or the account has no credit left.",
};

async function failure(res: Response, label: string): Promise<Error> {
  let detail = "";
  try {
    const text = await res.text();
    try {
      detail = errorMessage(JSON.parse(text)) || text;
    } catch {
      detail = text;
    }
  } catch {
    // the status alone has to do
  }
  const hint = HINTS[res.status];
  return new Error(`${label} answered ${res.status}${detail ? `: ${detail.slice(0, 300)}` : ""}${hint ? ` ${hint}` : ""}`);
}

// Streams one answer; `onText` gets everything written so far each time more arrives. Resolves with the whole text.
export async function streamOnline(
  target: OnlineTarget,
  req: ScriptRequest,
  onText: (full: string) => void,
  signal?: AbortSignal,
): Promise<string> {
  const apiKey = await getApiKey(target.provider);
  if (!apiKey) throw new MissingKeyError(target.provider);

  const { url, headers, body } = buildRequest(target, apiKey, req);
  const res = await fetch(url, { method: "POST", headers, body: JSON.stringify(body), signal });
  if (!res.ok || !res.body) throw await failure(res, PROVIDERS[target.provider].label);

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  const sse = new SseParser();
  let full = "";

  const handle = (payload: string): boolean => {
    if (payload === "[DONE]") return true;
    let event: unknown;
    try {
      event = JSON.parse(payload);
    } catch {
      return false;
    }
    const problem = errorMessage(event);
    if (problem) throw new Error(`${PROVIDERS[target.provider].label}: ${problem}`);
    const delta = textDelta(target.provider, event);
    if (delta) {
      full += delta;
      onText(full);
    }
    return false;
  };

  for (;;) {
    const { done, value } = await reader.read();
    const payloads = done ? sse.flush() : sse.push(decoder.decode(value, { stream: true }));
    for (const payload of payloads) if (handle(payload)) return full;
    if (done) return full;
  }
}

// The models the account can use, from the provider itself; empty when the key or address is wrong.
export async function listOnlineModels(provider: OnlineProvider, baseUrl?: string): Promise<string[]> {
  const apiKey = await getApiKey(provider);
  if (!apiKey) throw new MissingKeyError(provider);
  const { url, headers } = listModelsRequest(provider, apiKey, baseUrl);
  const res = await fetch(url, { headers });
  if (!res.ok) throw await failure(res, PROVIDERS[provider].label);
  return parseModelList(provider, await res.json());
}

// A tiny request that proves the key and model work, for the Test button.
export async function testOnline(target: OnlineTarget): Promise<void> {
  await streamOnline({ ...target, sendPhotos: false }, { prompt: "Reply with the word OK.", photos: [], maxTokens: 64 }, () => {});
}
