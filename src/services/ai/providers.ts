export type OnlineProvider = "anthropic" | "openai" | "gemini" | "openrouter" | "custom";
export type AiProviderId = "ollama" | OnlineProvider;

export interface ProviderInfo {
  id: OnlineProvider;
  label: string;
  baseUrl: string;
  keyPage: string;
  defaultModel: string;
  suggested: string[]; // shown until the live model list has been fetched
  askBaseUrl?: boolean;
}

export const PROVIDERS: Record<OnlineProvider, ProviderInfo> = {
  anthropic: {
    id: "anthropic",
    label: "Anthropic (Claude)",
    baseUrl: "https://api.anthropic.com/v1",
    keyPage: "https://console.anthropic.com/settings/keys",
    defaultModel: "claude-haiku-4-5-20251001",
    suggested: ["claude-haiku-4-5-20251001", "claude-sonnet-5-5", "claude-opus-5-5"],
  },
  openai: {
    id: "openai",
    label: "OpenAI",
    baseUrl: "https://api.openai.com/v1",
    keyPage: "https://platform.openai.com/api-keys",
    defaultModel: "gpt-4o-mini",
    suggested: ["gpt-4o-mini", "gpt-4o"],
  },
  gemini: {
    id: "gemini",
    label: "Google Gemini",
    baseUrl: "https://generativelanguage.googleapis.com/v1beta",
    keyPage: "https://aistudio.google.com/apikey",
    defaultModel: "gemini-2.5-flash",
    suggested: ["gemini-2.5-flash", "gemini-2.5-pro"],
  },
  openrouter: {
    id: "openrouter",
    label: "OpenRouter",
    baseUrl: "https://openrouter.ai/api/v1",
    keyPage: "https://openrouter.ai/keys",
    defaultModel: "openai/gpt-4o-mini",
    suggested: ["openai/gpt-4o-mini", "anthropic/claude-haiku-4.5", "google/gemini-2.5-flash"],
  },
  custom: {
    id: "custom",
    label: "Other (OpenAI-compatible)",
    baseUrl: "",
    keyPage: "",
    defaultModel: "",
    suggested: [],
    askBaseUrl: true,
  },
};

export const ONLINE_PROVIDERS = Object.keys(PROVIDERS) as OnlineProvider[];

export const isOnlineProvider = (id: string | undefined): id is OnlineProvider => !!id && id in PROVIDERS;

// What a request needs to know about where it goes.
export interface OnlineTarget {
  provider: OnlineProvider;
  model: string;
  baseUrl: string;
  sendPhotos: boolean;
}

export interface Photo {
  mime: string;
  base64: string;
}

export interface ScriptRequest {
  prompt: string;
  photos: Photo[];
  maxTokens: number;
  temperature?: number;
}

export interface BuiltRequest {
  url: string;
  headers: Record<string, string>;
  body: unknown;
}

const trimSlash = (s: string) => s.replace(/\/+$/, "");

export const baseUrlOf = (provider: OnlineProvider, custom?: string) =>
  trimSlash((provider === "custom" ? custom : "") || PROVIDERS[provider].baseUrl);

// The image type from the first bytes of the file as base64, which is all the APIs need to be told.
export function sniffImageMime(base64: string): string {
  if (base64.startsWith("iVBOR")) return "image/png";
  if (base64.startsWith("R0lGOD")) return "image/gif";
  if (base64.startsWith("UklGR")) return "image/webp";
  return "image/jpeg";
}

export function buildRequest(target: OnlineTarget, apiKey: string, req: ScriptRequest): BuiltRequest {
  const base = baseUrlOf(target.provider, target.baseUrl);
  const photos = target.sendPhotos ? req.photos : [];

  if (target.provider === "anthropic") {
    return {
      url: `${base}/messages`,
      headers: { "content-type": "application/json", "x-api-key": apiKey, "anthropic-version": "2023-06-01" },
      body: {
        model: target.model,
        max_tokens: req.maxTokens,
        stream: true,
        ...(req.temperature !== undefined && { temperature: req.temperature }),
        messages: [
          {
            role: "user",
            content: [
              ...photos.map((p) => ({ type: "image", source: { type: "base64", media_type: p.mime, data: p.base64 } })),
              { type: "text", text: req.prompt },
            ],
          },
        ],
      },
    };
  }

  if (target.provider === "gemini") {
    return {
      url: `${base}/models/${encodeURIComponent(target.model)}:streamGenerateContent?alt=sse`,
      headers: { "content-type": "application/json", "x-goog-api-key": apiKey },
      body: {
        contents: [
          {
            role: "user",
            parts: [
              ...photos.map((p) => ({ inline_data: { mime_type: p.mime, data: p.base64 } })),
              { text: req.prompt },
            ],
          },
        ],
        generationConfig: {
          maxOutputTokens: req.maxTokens,
          ...(req.temperature !== undefined && { temperature: req.temperature }),
        },
      },
    };
  }

  // OpenAI and everything that speaks its chat completions API. OpenAI's newer models only take
  // max_completion_tokens and only the default temperature; the others still expect max_tokens.
  const official = target.provider === "openai";
  return {
    url: `${base}/chat/completions`,
    headers: { "content-type": "application/json", authorization: `Bearer ${apiKey}` },
    body: {
      model: target.model,
      stream: true,
      [official ? "max_completion_tokens" : "max_tokens"]: req.maxTokens,
      ...(!official && req.temperature !== undefined && { temperature: req.temperature }),
      messages: [
        {
          role: "user",
          content: [
            ...photos.map((p) => ({ type: "image_url", image_url: { url: `data:${p.mime};base64,${p.base64}` } })),
            { type: "text", text: req.prompt },
          ],
        },
      ],
    },
  };
}

// The new text in one streamed event ("" when the event carries none).
export function textDelta(provider: OnlineProvider, event: any): string {
  if (provider === "anthropic") {
    return event?.type === "content_block_delta" && event.delta?.type === "text_delta" ? (event.delta.text ?? "") : "";
  }
  if (provider === "gemini") {
    const parts: any[] = event?.candidates?.[0]?.content?.parts ?? [];
    return parts.map((p) => (typeof p.text === "string" && !p.thought ? p.text : "")).join("");
  }
  return event?.choices?.[0]?.delta?.content ?? "";
}

// The provider's own explanation when it sends a failure, whether as an HTTP body or as an event in the stream.
export function errorMessage(body: unknown): string {
  const e = (body as any)?.error;
  if (typeof e === "string") return e;
  if (typeof e?.message === "string") return e.message;
  return "";
}

export function listModelsRequest(provider: OnlineProvider, apiKey: string, custom?: string): BuiltRequest {
  const base = baseUrlOf(provider, custom);
  if (provider === "anthropic") {
    return { url: `${base}/models?limit=100`, headers: { "x-api-key": apiKey, "anthropic-version": "2023-06-01" }, body: null };
  }
  if (provider === "gemini") {
    return { url: `${base}/models?pageSize=100`, headers: { "x-goog-api-key": apiKey }, body: null };
  }
  return { url: `${base}/models`, headers: { authorization: `Bearer ${apiKey}` }, body: null };
}

const NOT_A_CHAT_MODEL = /embed|whisper|tts|dall-e|moderation|image|audio|realtime|transcribe|search|computer-use/i;

export function parseModelList(provider: OnlineProvider, json: any): string[] {
  let ids: string[];
  if (provider === "gemini") {
    ids = (json?.models ?? [])
      .filter((m: any) => (m.supportedGenerationMethods ?? []).includes("generateContent"))
      .map((m: any) => String(m.name).replace(/^models\//, ""))
      .filter((id: string) => !NOT_A_CHAT_MODEL.test(id));
  } else {
    ids = (json?.data ?? []).map((m: any) => String(m.id));
    if (provider === "openai") ids = ids.filter((id) => !NOT_A_CHAT_MODEL.test(id));
  }
  return [...new Set(ids)].sort();
}
