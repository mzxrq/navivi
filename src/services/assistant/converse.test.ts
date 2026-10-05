import { describe, expect, it, vi } from "vitest";
import { EMPTY_BRIEF, cleanBriefPatch, mergeBrief, missingForBuild } from "./brief";
import { buildConversePrompt, converse, guardPlaces, parseConverseReply } from "./converse";

vi.mock("../ollamaApi", () => ({ completeText: vi.fn() }));
import { completeText } from "../ollamaApi";

describe("cleanBriefPatch", () => {
  it("keeps valid fields and drops malformed ones", () => {
    const patch = cleanBriefPatch({
      name: " Katsuragi ",
      languages: ["JA", "en", "fr", "ja"],
      durationMin: "5",
      wordCount: { min: 500, max: 800 },
      avoid: ["history", 3, ""],
      places: "not a list",
      tone: 12,
    });
    expect(patch).toEqual({ name: "Katsuragi", languages: ["ja", "en"], durationMin: 5, wordCount: { min: 500, max: 800 }, avoid: ["history"] });
  });

  it("rejects impossible lengths and word counts", () => {
    expect(cleanBriefPatch({ durationMin: -1, wordCount: { min: 900, max: 100 } })).toEqual({});
    expect(cleanBriefPatch({ durationMin: null })).toEqual({});
    expect(cleanBriefPatch("nope")).toEqual({});
  });
});

describe("parseConverseReply", () => {
  it("splits the reply from the brief tag", () => {
    const out = parseConverseReply('Sounds good. Which season?\n<brief>{"name":"Kumano","places":["Hongu Taisha"]}</brief>');
    expect(out.reply).toBe("Sounds good. Which season?");
    expect(out.patch).toEqual({ name: "Kumano", places: ["Hongu Taisha"] });
  });

  it("copes with a code fence, a missing close tag and no tag at all", () => {
    expect(parseConverseReply('Hi\n<brief>```json\n{"tone":"calm"}\n```').patch).toEqual({ tone: "calm" });
    expect(parseConverseReply("Just chatting.")).toEqual({ reply: "Just chatting.", patch: {} });
    expect(parseConverseReply("Hi <brief>{broken</brief>").patch).toEqual({});
  });

  it("finds the JSON when the model forgot the opening tag", () => {
    const raw = 'Will do.\n{"name": "Katsuragi {x}", "places": ["A", "B"]}\n\n</brief>';
    expect(parseConverseReply(raw)).toEqual({ reply: "Will do.", patch: { name: "Katsuragi {x}", places: ["A", "B"] } });
  });
});

describe("buildConversePrompt", () => {
  it("includes the brief, a bounded source and only the latest turns", () => {
    const history = Array.from({ length: 12 }, (_, i) => ({ role: "user" as const, text: `message ${i}` }));
    const prompt = buildConversePrompt({ history, brief: mergeBrief(EMPTY_BRIEF, { name: "X" }), sources: [{ name: "trip.pdf", text: "a".repeat(20000) }] });
    expect(prompt).toContain('"name":"X"');
    expect(prompt).toContain("--- trip.pdf ---");
    expect(prompt.length).toBeLessThan(12000);
    expect(prompt).not.toContain("message 0\n");
    expect(prompt).toContain("message 11");
  });
});

describe("guardPlaces", () => {
  const brief = mergeBrief(EMPTY_BRIEF, { places: ["根来寺", "槇尾山"] });
  it("ignores a translated copy of the list", () => {
    expect(guardPlaces(brief, { places: ["Negoro-ji", "Makio-san"], tone: "calm" })).toEqual({ tone: "calm" });
  });
  it("accepts added, removed or reordered stops", () => {
    expect(guardPlaces(brief, { places: ["根来寺", "槇尾山", "金剛山"] }).places).toHaveLength(3);
    expect(guardPlaces(brief, { places: ["槇尾山", "根来寺"] }).places).toEqual(["槇尾山", "根来寺"]);
    expect(guardPlaces(EMPTY_BRIEF, { places: ["A"] }).places).toEqual(["A"]);
  });
});

describe("converse", () => {
  it("is ready once places are known", async () => {
    vi.mocked(completeText).mockResolvedValue('OK, 3 stops.\n<brief>{"places":["A","B","C"]}</brief>');
    const result = await converse({ history: [{ role: "user", text: "go" }], brief: EMPTY_BRIEF, sources: [], engine: "m" as never });
    expect(result.ready).toBe(true);
    expect(result.patch.places).toHaveLength(3);
    expect(missingForBuild(EMPTY_BRIEF)).toEqual(["places"]);
  });
});
