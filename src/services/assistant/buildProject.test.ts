import { describe, expect, it, vi } from "vitest";

vi.mock("../ollamaApi", () => ({ completeText: vi.fn(), generateWaypointScriptStream: vi.fn() }));

import { briefToScriptRequest, buildProject, findExcerpt, tidyPlaces, walkReachKm } from "./buildProject";
import { EMPTY_BRIEF } from "./brief";
import { geocodeSettings, geocodeUrl } from "../geocode";

geocodeSettings.nominatimGapMs = 0;
import * as ollama from "../ollamaApi";

describe("tidyPlaces", () => {
  it("drops map labels that are not stops", () => {
    expect(tidyPlaces(["START", "Kyoshi Sta.", "Wakayama Pref.", "Fujito Tunnel", "To Mt. Daifuku/ Okube-toge Pass", "Temple", "Pay attention to the fork", "Mt. Fudatate"])).toEqual(["Kyoshi Sta.", "Mt. Fudatate"]);
  });

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

  it("keeps the arriving narration to the voice of the video, without length, facts or call to action", () => {
    const request = briefToScriptRequest({ ...brief, callToAction: "訪れてください", durationMin: 5 }, 2, { index: 1, kind: "arriving", excerpt: "古い社です" });
    expect(request).toContain("トーン");
    expect(request).not.toContain("訪れてください");
    expect(request).not.toContain("古い社です");
    expect(request).not.toContain("文字前後");
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
  it("reads a course guide: stops in order, walking, and the document's directions go to the arriving script", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ json: async () => ({ features: [{ center: [135.15, 34.29] }] }) })));
    vi.mocked(ollama.completeText).mockResolvedValue(
      JSON.stringify({ travel: "walking", stops: [{ name: "Kyoshi Sta." }, { name: "Kosen-ji Temple", directions: "Turn left along the tracks.", minutes: 15 }] }),
    );
    vi.mocked(ollama.generateWaypointScriptStream).mockClear();
    vi.mocked(ollama.generateWaypointScriptStream).mockImplementation(async (_n, _p, _e, _t, onChunk) => onChunk("ok"));
    const built = await buildProject({ brief: EMPTY_BRIEF, sourceText: "a guide", engine: "m", mapboxToken: "tk", onProgress: () => {} });
    expect(built.course?.stops).toHaveLength(2);
    expect(built.waypoints.map((w) => [w.name, w.routeMode])).toEqual([["Kyoshi Sta.", "walking"], ["Kosen-ji Temple", "walking"]]);
    const arriving = vi.mocked(ollama.generateWaypointScriptStream).mock.calls.filter((c) => c[9] === "arriving");
    expect(arriving[0][12]).not.toHaveProperty("directions");
    expect(arriving[1][12]).toMatchObject({ directions: "Turn left along the tracks.", minutes: 15 });
    vi.unstubAllGlobals();
  });

  it("questions a walking stop that could not be reached in the minutes the document gives", async () => {
    const centers: Record<string, [number, number]> = { A: [135.15, 34.29], B: [135.15, 34.45], C: [135.16, 34.3] };
    vi.stubGlobal("fetch", vi.fn(async (url: string) => ({ json: async () => ({ features: [{ center: centers[String(url).match(/places\/([A-C])\.json/)![1]] }] }) })));
    vi.mocked(ollama.completeText).mockResolvedValueOnce(JSON.stringify({ travel: "walking", stops: [{ name: "A" }, { name: "B", minutes: 15 }, { name: "C", minutes: 120 }] })).mockResolvedValue("A walk.");
    vi.mocked(ollama.generateWaypointScriptStream).mockImplementation(async (_n, _p, _e, _t, onChunk) => onChunk("ok"));
    const built = await buildProject({ brief: EMPTY_BRIEF, sourceText: "a guide", engine: "m", mapboxToken: "tk", onProgress: () => {} });
    expect(built.uncertain).toEqual([false, true, false]);
    expect(walkReachKm(15)).toBeCloseTo(4.1, 1);
    vi.unstubAllGlobals();
  });

  it("asks again when an English video comes back in Japanese, and words the return trip in English", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ json: async () => ({ features: [{ center: [135.7, 33.8] }] }) })));
    const requests: string[] = [];
    vi.mocked(ollama.generateWaypointScriptStream).mockClear();
    vi.mocked(ollama.generateWaypointScriptStream).mockImplementation(async (_n, request, _e, _t, onChunk) => {
      requests.push(request);
      onChunk(request.includes("IMPORTANT") ? "A quiet temple." : "ここは静かです。");
    });
    const built = await buildProject({
      brief: { ...EMPTY_BRIEF, languages: ["en"], places: ["Hongu", "Nachi"] },
      sourceText: "",
      engine: "m",
      mapboxToken: "tk",
      onProgress: () => {},
    });
    expect(built.waypoints.every((w) => w.attractionNarration === "A quiet temple.")).toBe(true);
    expect(requests.filter((r) => r.includes("IMPORTANT")).length).toBe(requests.length / 2);
    expect(briefToScriptRequest({ ...EMPTY_BRIEF, languages: ["en"] }, 2, { index: 1, kind: "attraction", returnTrip: "Take the bus." })).toContain("Getting back");
    vi.unstubAllGlobals();
  });

  it("writes the course introduction and gives the return trip to the last stop only", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ json: async () => ({ features: [{ center: [135.15, 34.29] }] }) })));
    vi.mocked(ollama.completeText)
      .mockResolvedValueOnce(JSON.stringify({ stops: [{ name: "Kyoshi Sta." }, { name: "Narutaki Bus Stop" }], distance: "10 km", returnTrip: "Take the bus to Wakayamashi Sta." }))
      .mockResolvedValueOnce("A 10 km walk.");
    vi.mocked(ollama.generateWaypointScriptStream).mockClear();
    vi.mocked(ollama.generateWaypointScriptStream).mockImplementation(async (_n, _p, _e, _t, onChunk) => onChunk("ok"));
    const built = await buildProject({ brief: { ...EMPTY_BRIEF, languages: ["en"] }, sourceText: "a guide", engine: "m", mapboxToken: "tk", onProgress: () => {} });
    expect(built.overviewIntro).toBe("A 10 km walk.");
    const requests = vi.mocked(ollama.generateWaypointScriptStream).mock.calls.filter((c) => c[9] === "attraction").map((c) => c[1]);
    expect(requests[0]).not.toContain("Wakayamashi");
    expect(requests[1]).toContain("Take the bus to Wakayamashi Sta.");
    vi.unstubAllGlobals();
  });

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
    expect(built.waypoints.map((w) => w.name)).toEqual(["Hongu", "Nowhere", "Nachi"]);
    expect(built.failedPlaces).toEqual([]);
    expect(built.uncertainPlaces).toEqual(["Nowhere"]);
    expect(built.waypoints[0]).toMatchObject({ lat: 33.8, lng: 135.7, routeMode: "driving", arrivingNarration: "ここは静かです。", attractionNarration: "ここは静かです。" });
    expect(vi.mocked(ollama.generateWaypointScriptStream).mock.calls.slice(0, 2).map((c) => c[9])).toEqual(["arriving", "attraction"]);
    expect(new Set(progress)).toEqual(new Set(["places", "geocode", "scripts"]));
    vi.unstubAllGlobals();
  });

  it("adds photos to the stops when given a finder, and carries on when one stop's lookup fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ json: async () => ({ features: [{ center: [135.7, 33.8] }] }) })));
    vi.mocked(ollama.generateWaypointScriptStream).mockImplementation(async (_n, _p, _e, _t, onChunk) => onChunk("script"));
    const credit = { title: "File:A.jpg", author: "Taro", license: "CC BY 4.0", url: "https://commons.wikimedia.org/wiki/File:A.jpg" };
    const asked: string[] = [];
    const steps: string[] = [];
    const built = await buildProject({
      brief: { ...EMPTY_BRIEF, places: ["Hongu", "Broken", "Nachi"] },
      sourceText: "",
      engine: "m",
      mapboxToken: "tk",
      onProgress: (p) => steps.push(p.step),
      photos: async (stop) => {
        asked.push(stop.name);
        if (stop.name === "Broken") throw new Error("offline");
        return [{ path: `C:/Imports/${stop.name}.jpg`, credit }];
      },
    });
    expect(asked).toEqual(["Hongu", "Broken", "Nachi"]);
    expect(built.waypoints.map((w) => w.images)).toEqual([["C:/Imports/Hongu.jpg"], [], ["C:/Imports/Nachi.jpg"]]);
    expect(built.waypoints[0].imageCredits).toEqual({ "C:/Imports/Hongu.jpg": credit });
    expect(built.photosAdded).toBe(2);
    expect(steps.indexOf("photos")).toBeGreaterThan(steps.indexOf("geocode"));
    expect(steps.indexOf("photos")).toBeLessThan(steps.indexOf("scripts"));
    vi.unstubAllGlobals();
  });

  it("looks for no photos unless a finder is given", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ json: async () => ({ features: [{ center: [135.7, 33.8] }] }) })));
    vi.mocked(ollama.generateWaypointScriptStream).mockImplementation(async (_n, _p, _e, _t, onChunk) => onChunk("script"));
    const steps: string[] = [];
    const built = await buildProject({ brief: { ...EMPTY_BRIEF, places: ["Hongu"] }, sourceText: "", engine: "m", mapboxToken: "tk", onProgress: (p) => steps.push(p.step) });
    expect(steps).not.toContain("photos");
    expect(built.photosAdded).toBe(0);
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
