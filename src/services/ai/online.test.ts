import { beforeEach, describe, expect, it, vi } from "vitest";

const invoke = vi.hoisted(() => vi.fn());
const http = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/plugin-http", () => ({ fetch: http }));

import { hasApiKey, listOnlineModels, MissingKeyError, streamOnline, testOnline } from "./online";
import type { OnlineTarget } from "./providers";

const enc = new TextEncoder();
const streamOf = (...chunks: string[]) =>
  new ReadableStream<Uint8Array>({
    start(c) {
      chunks.forEach((s) => c.enqueue(enc.encode(s)));
      c.close();
    },
  });
const ok = (...chunks: string[]) => ({ ok: true, status: 200, body: streamOf(...chunks) });
const target = (over: Partial<OnlineTarget> = {}): OnlineTarget => ({ provider: "openai", model: "m", baseUrl: "", sendPhotos: true, ...over });
const req = { prompt: "p", photos: [], maxTokens: 100 };

beforeEach(() => {
  invoke.mockReset();
  http.mockReset();
  invoke.mockResolvedValue("sk-key");
});

describe("streamOnline", () => {
  it("builds up the answer from OpenAI events split across chunks and stops at [DONE]", async () => {
    http.mockResolvedValue(
      ok('data: {"choices":[{"delta":{"content":"こん"}}]}\n\ndata: {"choices":[{"del', 'ta":{"content":"にちは"}}]}\n\n', "data: [DONE]\n\n"),
    );
    const seen: string[] = [];
    const full = await streamOnline(target(), req, (t) => seen.push(t));
    expect(full).toBe("こんにちは");
    expect(seen).toEqual(["こん", "こんにちは"]);
    const [url, init] = http.mock.calls[0];
    expect(url).toBe("https://api.openai.com/v1/chat/completions");
    expect(init.headers.authorization).toBe("Bearer sk-key");
    expect(invoke).toHaveBeenCalledWith("secret_get", { name: "ai-key:openai" });
  });

  it("reads Anthropic's text deltas", async () => {
    http.mockResolvedValue(
      ok(
        'event: message_start\ndata: {"type":"message_start"}\n\n',
        'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello"}}\n\n',
        'event: message_stop\ndata: {"type":"message_stop"}\n\n',
      ),
    );
    expect(await streamOnline(target({ provider: "anthropic" }), req, () => {})).toBe("Hello");
  });

  it("ends an unterminated final event", async () => {
    http.mockResolvedValue(ok('data: {"choices":[{"delta":{"content":"x"}}]}'));
    expect(await streamOnline(target(), req, () => {})).toBe("x");
  });

  it("explains a rejected key with the provider's message and a hint", async () => {
    http.mockResolvedValue({ ok: false, status: 401, body: null, text: async () => JSON.stringify({ error: { message: "Incorrect API key" } }) });
    await expect(streamOnline(target(), req, () => {})).rejects.toThrow(/OpenAI answered 401: Incorrect API key Check the API key/);
  });

  it("throws an error the provider sends inside the stream", async () => {
    http.mockResolvedValue(ok('data: {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}\n\n'));
    await expect(streamOnline(target({ provider: "anthropic" }), req, () => {})).rejects.toThrow(/Overloaded/);
  });

  it("asks for a key instead of calling out when none is saved", async () => {
    invoke.mockResolvedValue(null);
    await expect(streamOnline(target(), req, () => {})).rejects.toBeInstanceOf(MissingKeyError);
    expect(http).not.toHaveBeenCalled();
    expect(await hasApiKey("openai")).toBe(false);
  });
});

describe("listOnlineModels and testOnline", () => {
  it("lists what the provider offers", async () => {
    http.mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: [{ id: "gpt-4o" }, { id: "whisper-1" }] }) });
    expect(await listOnlineModels("openai")).toEqual(["gpt-4o"]);
  });

  it("the test request goes out without photos and resolves when the answer arrives", async () => {
    http.mockResolvedValue(ok('data: {"choices":[{"delta":{"content":"OK"}}]}\n\n', "data: [DONE]\n\n"));
    await expect(testOnline(target())).resolves.toBeUndefined();
    expect(JSON.parse(http.mock.calls[0][1].body).max_completion_tokens).toBe(64);
  });
});
