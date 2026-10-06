import { describe, expect, it } from "vitest";
import { EMPTY_BRIEF } from "./brief";
import { emptyChat, hasContent, parseChat, serializeChat } from "./chatStore";

describe("chatStore", () => {
  it("round-trips a chat", () => {
    const chat = { ...emptyChat(), messages: [{ role: "user" as const, text: "hi", files: ["a.pdf"] }, { role: "assistant" as const, text: "hello" }], sources: [{ name: "a.pdf", text: "Sainen-ji" }] };
    expect(parseChat(serializeChat(chat))).toEqual(chat);
  });

  it("gives nothing for damaged, foreign or newer files", () => {
    expect(parseChat("{oops")).toBeNull();
    expect(parseChat("[]")).toBeNull();
    expect(parseChat(JSON.stringify({ version: 2, messages: [] }))).toBeNull();
  });

  it("keeps what can be used from a half-valid file", () => {
    const parsed = parseChat(JSON.stringify({ version: 1, messages: [{ role: "user", text: "ok" }, { role: "robot", text: "x" }, 5], brief: { name: "Trip" }, sources: [{ name: 1 }], attachments: { photos: ["a.jpg", 3] } }));
    expect(parsed?.messages).toEqual([{ role: "user", text: "ok" }]);
    expect(parsed?.brief).toEqual({ ...EMPTY_BRIEF, name: "Trip" });
    expect(parsed?.sources).toEqual([]);
    expect(parsed?.attachments).toEqual({ gpx: null, photos: ["a.jpg"] });
  });

  it("only the newest messages are kept", () => {
    const messages = Array.from({ length: 250 }, (_, i) => ({ role: "user" as const, text: String(i) }));
    const parsed = parseChat(serializeChat({ ...emptyChat(), messages }));
    expect(parsed?.messages).toHaveLength(200);
    expect(parsed?.messages[199]?.text).toBe("249");
  });

  it("knows an untouched chat from a used one", () => {
    expect(hasContent(emptyChat())).toBe(false);
    expect(hasContent({ ...emptyChat(), brief: { ...EMPTY_BRIEF, name: "x" } })).toBe(true);
  });
});
