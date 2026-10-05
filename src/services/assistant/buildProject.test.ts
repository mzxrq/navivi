import { describe, expect, it, vi } from "vitest";

vi.mock("../ollamaApi", () => ({ completeText: vi.fn(), generateWaypointScriptStream: vi.fn() }));

import { briefToScriptRequest, buildProject, findExcerpt, tidyPlaces } from "./buildProject";
import { EMPTY_BRIEF } from "./brief";
import { geocodeUrl } from "../geocode";
import * as ollama from "../ollamaApi";

describe("tidyPlaces", () => {
  it("drops blanks and repeats, keeps order, and caps", () => {
    expect(tidyPlaces(["Kyoto", " kyoto ", "", 5, "Nara", "Na ra"])).toEqual(["Kyoto", "Nara"]);
    expect(tidyPlaces(Array.from({ length: 40 }, (_, i) => `P${i}`))).toHaveLength(25);
    expect(tidyPlaces(["a", "b", "c"], 2)).toEqual(["a", "b"]);
  });
});

describe("findExcerpt", () => {
  const source = "序文です。\n熊野本宮大社は参詣道の終点にある古い社です。次の文です。\n別の段落。";
  it("starts at the sentence that mentions the place and caps the length", () => {
    expect(findExcerpt(source, "熊野本宮大社", 20)).toBe("熊野本宮大社は参詣道の終点にある古い社で");
  });
  it("finds the place by its first word and returns nothing when it is absent", () => {
    expect(findExcerpt("We reach Hongu Taisha at noon.", "Hongu Taisha, Tanabe")).toContain("Hongu Taisha");
    expect(findExcerpt(source, "Tokyo")).toBe("");
  });
});

describe("briefToScriptRequest", () => {
  const brief = { ...EMPTY_BRIEF, tone: "calm", audience: "first-time visitors", purpose: "invite visitors", callToAction: "walk the route", avoid: ["complex history"], mustInclude: ["the shrine"] };

  it("carries tone, audience, must include and avoid on every stop", () => {
    const text = briefToScriptRequest(brief, 3, { index: 1 });
    for (const part of ["calm", "first-time visitors", "the shrine", "complex history"]) expect(text).toContain(part);
  });

  it("gives purpose to the first and last stops and the call to action to the last only", () => {
    expect(briefToScriptRequest(brief, 3, { index: 0 })).toContain("invite visitors");
    expect(briefToScriptRequest(brief, 3, { index: 1 })).not.toContain("invite visitors");
    expect(briefToScriptRequest(brief, 3, { index: 2 })).toContain("walk the route");
    expect(briefToScriptRequest(brief, 3, { index: 1 })).not.toContain("walk the route");
  });

  it("splits the word count, or else the running time, over the stops", () => {
    expect(briefToScriptRequest({ ...brief, wordCount: { min: 500, max: 800 } }, 5)).toContain("100〜160語");
    expect(briefToScriptRequest({ ...brief, durationMin: 5 }, 5)).toContain("300文字前後");
    expect(briefToScriptRequest(brief, 5)).not.toMatch(/語を目安|文字前後/);
  });

  it("asks for English when that is the only language, and quotes the stop's excerpt", () => {
    expect(briefToScriptRequest({ ...brief, languages: ["en"] }, 2)).toContain("英語");
    expect(briefToScriptRequest({ ...brief, languages: ["en", "ja"] }, 2)).not.toContain("英語");
    expect(briefToScriptRequest(brief, 2, { index: 0, excerpt: "古い社です" })).toContain("古い社です");
  });
});

describe("geocodeUrl", () => {
  it("uses Mapbox with a proximity bias when there is a token", () => {
    const url = geocodeUrl("Hongu", { mapboxToken: "tk", near: { lat: 33.8, lng: 135.7 } });
    expect(url).toContain("api.mapbox.com");
    expect(url).toContain("proximity=135.7,33.8");
    expect(url).toContain("access_token=tk");
  });
  it("falls back to Nominatim with a viewbox around the previous stop", () => {
    const url = geocodeUrl("熊野", { near: { lat: 33, lng: 135 } });
    expect(url).toContain("nominatim.openstreetmap.org");
    expect(url).toContain(encodeURIComponent("熊野"));
    expect(url).toContain("viewbox=134,34,136,32");
    expect(geocodeUrl("x", {})).not.toContain("viewbox");
  });
});

describe("buildProject", () => {
  it("geocodes the brief's places, reports the ones it cannot find, and writes a script for each stop", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => ({
        json: async () => (String(url).includes("Nowhere") ? { features: [] } : { features: [{ center: [135.7, 33.8] }] }),
      })),
    );
    vi.mocked(ollama.generateWaypointScriptStream).mockImplementation(async (_n, _p, _e, _t, onChunk) => onChunk("「ここは静かです。」"));
    const progress: string[] = [];
    const built = await buildProject({
      brief: { ...EMPTY_BRIEF, name: "Pilgrimage", places: ["Hongu", "Nowhere", "Nachi"] },
      sourceText: "",
      engine: "m",
      mapboxToken: "tk",
      onProgress: (p) => progress.push(p.step),
    });
    expect(built.name).toBe("Pilgrimage");
    expect(built.waypoints.map((w) => w.name)).toEqual(["Hongu", "Nachi"]);
    expect(built.failedPlaces).toEqual(["Nowhere"]);
    expect(built.waypoints[0]).toMatchObject({ lat: 33.8, lng: 135.7, routeMode: "driving", attractionNarration: "ここは静かです。" });
    expect(new Set(progress)).toEqual(new Set(["places", "geocode", "scripts"]));
    vi.unstubAllGlobals();
  });

  it("stops when aborted", async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(
      buildProject({ brief: { ...EMPTY_BRIEF, places: ["A"] }, sourceText: "", engine: "m", mapboxToken: "tk", signal: controller.signal, onProgress: () => {} }),
    ).rejects.toMatchObject({ name: "AbortError" });
  });
});
