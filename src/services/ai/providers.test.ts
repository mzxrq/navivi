import { describe, expect, it } from "vitest";
import {
  baseUrlOf,
  buildRequest,
  errorMessage,
  listModelsRequest,
  parseModelList,
  sniffImageMime,
  textDelta,
  type OnlineTarget,
} from "./providers";

const target = (over: Partial<OnlineTarget> = {}): OnlineTarget => ({
  provider: "openai",
  model: "m",
  baseUrl: "",
  sendPhotos: true,
  ...over,
});
const photo = { mime: "image/png", base64: "AAAA" };
const req = { prompt: "write", photos: [photo], maxTokens: 500, temperature: 0.4 };

describe("buildRequest", () => {
  it("OpenAI: bearer key, photos as data URLs, max_completion_tokens and no temperature", () => {
    const r = buildRequest(target(), "sk-1", req);
    expect(r.url).toBe("https://api.openai.com/v1/chat/completions");
    expect(r.headers.authorization).toBe("Bearer sk-1");
    const body: any = r.body;
    expect(body.max_completion_tokens).toBe(500);
    expect(body.max_tokens).toBeUndefined();
    expect(body.temperature).toBeUndefined();
    expect(body.stream).toBe(true);
    expect(body.messages[0].content).toEqual([
      { type: "image_url", image_url: { url: "data:image/png;base64,AAAA" } },
      { type: "text", text: "write" },
    ]);
  });

  it("OpenRouter and custom endpoints use max_tokens and keep the temperature", () => {
    const body: any = buildRequest(target({ provider: "openrouter" }), "k", req).body;
    expect(body.max_tokens).toBe(500);
    expect(body.temperature).toBe(0.4);
    const custom = buildRequest(target({ provider: "custom", baseUrl: "http://localhost:1234/v1/" }), "k", req);
    expect(custom.url).toBe("http://localhost:1234/v1/chat/completions");
  });

  it("Anthropic: x-api-key, version header, image blocks before the text", () => {
    const r = buildRequest(target({ provider: "anthropic", model: "claude-x" }), "ak", req);
    expect(r.url).toBe("https://api.anthropic.com/v1/messages");
    expect(r.headers["x-api-key"]).toBe("ak");
    expect(r.headers["anthropic-version"]).toBe("2023-06-01");
    const body: any = r.body;
    expect(body.max_tokens).toBe(500);
    expect(body.temperature).toBe(0.4);
    expect(body.messages[0].content).toEqual([
      { type: "image", source: { type: "base64", media_type: "image/png", data: "AAAA" } },
      { type: "text", text: "write" },
    ]);
  });

  it("Gemini: model in the URL, key in a header, inline_data parts", () => {
    const r = buildRequest(target({ provider: "gemini", model: "gemini-2.5-flash" }), "gk", req);
    expect(r.url).toBe(
      "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:streamGenerateContent?alt=sse",
    );
    expect(r.headers["x-goog-api-key"]).toBe("gk");
    const body: any = r.body;
    expect(body.contents[0].parts).toEqual([{ inline_data: { mime_type: "image/png", data: "AAAA" } }, { text: "write" }]);
    expect(body.generationConfig).toEqual({ maxOutputTokens: 500, temperature: 0.4 });
  });

  it("sends no photos when they are switched off", () => {
    const body: any = buildRequest(target({ sendPhotos: false }), "k", req).body;
    expect(body.messages[0].content).toEqual([{ type: "text", text: "write" }]);
  });
});

describe("textDelta", () => {
  it("reads each provider's streamed text", () => {
    expect(textDelta("openai", { choices: [{ delta: { content: "こ" } }] })).toBe("こ");
    expect(textDelta("openai", { choices: [{ delta: {} }] })).toBe("");
    expect(textDelta("anthropic", { type: "content_block_delta", delta: { type: "text_delta", text: "ん" } })).toBe("ん");
    expect(textDelta("anthropic", { type: "message_start" })).toBe("");
    expect(textDelta("anthropic", { type: "content_block_delta", delta: { type: "input_json_delta" } })).toBe("");
    expect(textDelta("gemini", { candidates: [{ content: { parts: [{ text: "に" }, { text: "ち" }] } }] })).toBe("にち");
  });

  it("leaves out a Gemini thought summary", () => {
    expect(textDelta("gemini", { candidates: [{ content: { parts: [{ text: "hmm", thought: true }, { text: "ok" }] } }] })).toBe("ok");
  });
});

describe("errorMessage", () => {
  it("finds the message in each provider's error shape", () => {
    expect(errorMessage({ error: { message: "Invalid key", type: "x" } })).toBe("Invalid key");
    expect(errorMessage({ type: "error", error: { type: "authentication_error", message: "bad x-api-key" } })).toBe("bad x-api-key");
    expect(errorMessage({ error: "plain" })).toBe("plain");
    expect(errorMessage({ nothing: true })).toBe("");
  });
});

describe("models", () => {
  it("asks each provider's list endpoint with its own auth", () => {
    expect(listModelsRequest("openai", "k").url).toBe("https://api.openai.com/v1/models");
    expect(listModelsRequest("anthropic", "k").headers["x-api-key"]).toBe("k");
    expect(listModelsRequest("gemini", "k").url).toContain("/v1beta/models");
    expect(listModelsRequest("custom", "k", "http://h/v1").url).toBe("http://h/v1/models");
  });

  it("keeps chat models only, sorted and unique", () => {
    const openai = { data: [{ id: "gpt-4o" }, { id: "text-embedding-3-small" }, { id: "whisper-1" }, { id: "gpt-4o-mini" }, { id: "gpt-4o" }] };
    expect(parseModelList("openai", openai)).toEqual(["gpt-4o", "gpt-4o-mini"]);
    const gemini = {
      models: [
        { name: "models/gemini-2.5-flash", supportedGenerationMethods: ["generateContent"] },
        { name: "models/embedding-001", supportedGenerationMethods: ["embedContent"] },
      ],
    };
    expect(parseModelList("gemini", gemini)).toEqual(["gemini-2.5-flash"]);
    expect(parseModelList("anthropic", { data: [{ id: "claude-b" }, { id: "claude-a" }] })).toEqual(["claude-a", "claude-b"]);
    expect(parseModelList("custom", {})).toEqual([]);
  });
});

describe("helpers", () => {
  it("knows an image by its first bytes", () => {
    expect(sniffImageMime("/9j/4AAQ")).toBe("image/jpeg");
    expect(sniffImageMime("iVBORw0K")).toBe("image/png");
    expect(sniffImageMime("UklGRiQA")).toBe("image/webp");
    expect(sniffImageMime("R0lGODlh")).toBe("image/gif");
  });

  it("uses the typed base URL only for the custom provider", () => {
    expect(baseUrlOf("custom", "http://x/v1///")).toBe("http://x/v1");
    expect(baseUrlOf("openai", "http://ignored")).toBe("https://api.openai.com/v1");
  });
});
