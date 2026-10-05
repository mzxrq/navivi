import { describe, expect, it } from "vitest";
import { SseParser } from "./sse";

describe("SseParser", () => {
  it("returns the data of each complete event", () => {
    const p = new SseParser();
    expect(p.push('data: {"a":1}\n\ndata: {"a":2}\n\n')).toEqual(['{"a":1}', '{"a":2}']);
  });

  it("waits for an event that is split across chunks", () => {
    const p = new SseParser();
    expect(p.push('data: {"te')).toEqual([]);
    expect(p.push('xt":"hi"}\n')).toEqual([]);
    expect(p.push("\n")).toEqual(['{"text":"hi"}']);
  });

  it("ignores event names, comments and keep-alives", () => {
    const p = new SseParser();
    expect(p.push("event: content_block_delta\ndata: x\n\n: ping\n\n")).toEqual(["x"]);
  });

  it("handles CRLF, including one split between chunks", () => {
    const p = new SseParser();
    expect(p.push("data: one\r")).toEqual([]);
    expect(p.push("\n\r\ndata: two\r\n\r\n")).toEqual(["one", "two"]);
  });

  it("joins several data lines of one event", () => {
    expect(new SseParser().push("data: a\ndata: b\n\n")).toEqual(["a\nb"]);
  });

  it("flush returns an event the server never closed", () => {
    const p = new SseParser();
    p.push("data: last");
    expect(p.flush()).toEqual(["last"]);
  });

  it("passes [DONE] through for the caller to stop on", () => {
    expect(new SseParser().push("data: [DONE]\n\n")).toEqual(["[DONE]"]);
  });
});
