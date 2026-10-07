import { beforeEach, describe, expect, it, vi } from "vitest";

const invoke = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));

import { emptyTimeline, type Segment, type TimelineData } from "../features/editor/model";
import { lastJson, refreshStopMedia, regenModes, runRegen } from "./stopRegen";

beforeEach(() => invoke.mockReset());

const both = { hasArrivalVoice: true, hasAttractionVoice: true };
const arrivalOnly = { hasArrivalVoice: true, hasAttractionVoice: false };

describe("regenModes", () => {
  it("redoes the voice, then the subtitles that depend on it", () => {
    expect(regenModes("voice", 3, arrivalOnly)).toEqual(["tts 3 --force", "subtitle 3 --force"]);
    expect(regenModes("voice", 3, both)).toEqual(["tts 3 --force", "attraction-tts 3 --force", "subtitle 3 --force", "subtitle-all"]);
  });

  it("makes sure the photo clip has its narration to size against, without redoing it", () => {
    expect(regenModes("photo", 2, both)).toEqual(["attraction-tts 2", "attraction 2 --force"]);
    expect(regenModes("photo", 2, arrivalOnly)).toEqual(["attraction 2 --force"]);
  });

  it("redoes only the subtitles of the stop", () => {
    expect(regenModes("subtitles", 0, both)).toEqual(["subtitle 0 --force"]);
  });
});

describe("runRegen", () => {
  it("runs the modes one after another and reports a skipped one", async () => {
    invoke
      .mockResolvedValueOnce('progress\n{\n  "success": true,\n  "skipped": "no narration"\n}\n')
      .mockResolvedValueOnce('{\n  "success": true\n}\n');
    const steps: number[] = [];
    const result = await runRegen("C:/p/job_config.json", ["tts 1 --force", "subtitle 1 --force"], (done) => steps.push(done));
    expect(invoke.mock.calls.map((c) => c[1])).toEqual([
      { action: "C:/p/job_config.json", payload: "tts 1 --force" },
      { action: "C:/p/job_config.json", payload: "subtitle 1 --force" },
    ]);
    expect(steps).toEqual([0, 1]);
    expect(result.skipped).toBe("no narration");
  });

  it("stops at the first failure", async () => {
    invoke.mockResolvedValueOnce('{\n  "success": false,\n  "error": "TTS audio not found"\n}\n');
    await expect(runRegen("C:/p/job_config.json", ["subtitle 1 --force", "x"])).rejects.toThrow("TTS audio not found");
    expect(invoke).toHaveBeenCalledTimes(1);
  });
});

describe("lastJson", () => {
  it("reads an indented reply after progress text, and tolerates garbage", () => {
    expect(lastJson('[00:01] working\n{\n  "success": true\n}')).toEqual({ success: true });
    expect(lastJson("Traceback")).toEqual({});
  });
});

const seg = (patch: Partial<Segment>): Segment => ({
  id: "s", label: "x", kind: "route", video: "assets/video/route/a.mp4", videoDuration: 10, trimIn: 0, trimOut: 10,
  audioOffset: 0, volume: 1, muted: false, fadeIntoNext: 0, ...patch,
});

const timeline = (): TimelineData => ({
  ...emptyTimeline(),
  segments: [
    seg({ id: "leg", audio: "assets/audio/02_waypoint_04_Castle.wav", audioDuration: 4, subtitleFile: "assets/subtitles/02_waypoint_04_Castle.srt" }),
    seg({ id: "other", audio: "assets/audio/02_waypoint_05_Park.wav", audioDuration: 4, subtitleFile: "assets/subtitles/02_waypoint_05_Park.srt" }),
    seg({ id: "photo", kind: "attraction", video: "assets/video/attraction/04_attraction_03_Castle.mp4", videoDuration: 6, trimOut: 6 }),
  ],
  subtitles: [
    { id: "c1", segmentId: "leg", start: 0, end: 1, text: "old" },
    { id: "c2", segmentId: "other", start: 0, end: 1, text: "keep" },
  ],
});

describe("refreshStopMedia", () => {
  const io = {
    probe: vi.fn(async (_p: string, kind: string) => (kind === "audio" ? 7 : 9)),
    readText: vi.fn(async () => "1\n00:00:00,000 --> 00:00:02,000\nnew line\n"),
  };

  it("measures a remade voice again and swaps only that clip's cues", async () => {
    const out = await refreshStopMedia(timeline(), 3, "voice", io);
    expect(out?.segments.find((s) => s.id === "leg")?.audioDuration).toBe(7);
    expect(out?.segments.find((s) => s.id === "other")?.audioDuration).toBe(4);
    expect(out?.subtitles.map((c) => c.text).sort()).toEqual(["keep", "new line"]);
  });

  it("measures a remade photo clip and keeps its untrimmed end", async () => {
    const out = await refreshStopMedia(timeline(), 3, "photo", io);
    const photo = out?.segments.find((s) => s.id === "photo");
    expect(photo).toMatchObject({ videoDuration: 9, trimOut: 9 });
    expect(out?.subtitles).toHaveLength(2);
  });

  it("returns null when nothing in the timeline belongs to the stop", async () => {
    expect(await refreshStopMedia(timeline(), 9, "voice", io)).toBeNull();
  });
});
