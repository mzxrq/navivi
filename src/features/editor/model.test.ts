import { describe, expect, it } from "vitest";
import {
  Segment,
  TimelineData,
  anchorCue,
  autoArrange,
  autoTimeBlocks,
  cuesFromTimed,
  cuesToSrt,
  emptyTimeline,
  fadeIns,
  formatSrtTime,
  kindFromName,
  layout,
  parsePlainBlocks,
  parseTimedSrt,
  timelineFromEditorState,
  timelineFromPipeline,
  toManifest,
  trimmedLength,
} from "./model";

const seg = (id: string, over: Partial<Segment> = {}): Segment => ({
  id,
  label: id,
  kind: "custom",
  video: `assets/video/${id}.mp4`,
  videoDuration: 10,
  trimIn: 0,
  trimOut: 10,
  audioOffset: 0,
  volume: 1,
  muted: false,
  fadeIntoNext: 0,
  ...over,
});

const timeline = (segments: Segment[]): TimelineData => ({ ...emptyTimeline(), segments });

describe("layout", () => {
  it("places clips one after another; narration that runs past its video makes the clip longer", () => {
    const { placed, total } = layout(timeline([seg("a"), seg("b", { trimOut: 5, audio: "b.wav", audioOffset: 2, audioDuration: 9 })]));
    expect(placed.map((p) => [p.start, p.length])).toEqual([
      [0, 10],
      [10, 11],
    ]);
    expect(total).toBe(21);
  });

  it("never lets a trimmed clip get shorter than the minimum", () => {
    expect(trimmedLength(seg("a", { trimIn: 4, trimOut: 4.1 }))).toBe(0.5);
  });
});

describe("fadeIns", () => {
  const fadesOf = (segments: Segment[]) => fadeIns(layout(timeline(segments)).placed);

  it("dissolves into the next clip, at most half its length", () => {
    expect(fadesOf([seg("a", { fadeIntoNext: 0.8 }), seg("b")])).toEqual([0, 0.8]);
    expect(fadesOf([seg("a", { fadeIntoNext: 0.8 }), seg("b", { trimOut: 1 })])).toEqual([0, 0.5]);
  });

  it("skips what the export skips: a last clip, tiny fades, a clip already joined by a fade", () => {
    expect(fadesOf([seg("a"), seg("b", { fadeIntoNext: 0.8 })])).toEqual([0, 0]);
    expect(fadesOf([seg("a", { fadeIntoNext: 0.05 }), seg("b")])).toEqual([0, 0]);
    expect(fadesOf([seg("a", { fadeIntoNext: 0.8 }), seg("b", { fadeIntoNext: 0.8 }), seg("c")])).toEqual([0, 0.8, 0]);
  });
});

describe("kindFromName", () => {
  it.each([
    ["00_intro.mp4", "intro"],
    ["99_OUTRO.mp4", "outro"],
    ["01_overview.mp4", "overview"],
    ["04_attraction_01_x.mp4", "attraction"],
    ["02_waypoint_01_x.mp4", "route"],
    ["my clip.mp4", "custom"],
  ])("%s is %s", (name, kind) => expect(kindFromName(name)).toBe(kind));
});

describe("autoArrange", () => {
  const clips = [
    seg("outro", { kind: "outro", video: "99_outro.mp4" }),
    seg("leg2", { kind: "route", video: "02_waypoint_02_b.mp4" }),
    seg("stop1", { kind: "attraction", video: "04_attraction_01_a.mp4" }),
    seg("overview", { kind: "overview", video: "01_overview.mp4" }),
    seg("mine", { kind: "custom", video: "mine.mp4" }),
    seg("intro", { kind: "intro", video: "00_intro.mp4" }),
    seg("leg1", { kind: "route", video: "02_waypoint_01_a.mp4" }),
  ];

  it("orders intro, overview, each leg then the stop it reaches, your own clips, then the outro", () => {
    const out = autoArrange(timeline(clips));
    expect(out.segments.map((s) => s.id)).toEqual(["intro", "overview", "leg1", "stop1", "leg2", "mine", "outro"]);
  });

  it("fades from a leg into the stop it arrives at and nowhere else", () => {
    const out = autoArrange(timeline(clips));
    expect(Object.fromEntries(out.segments.map((s) => [s.id, s.fadeIntoNext]))).toMatchObject({ leg1: 0.8, leg2: 0, intro: 0, stop1: 0 });
  });

  it("keeps the order of clips it cannot place", () => {
    const out = autoArrange(timeline([seg("x"), seg("y"), seg("z")]));
    expect(out.segments.map((s) => s.id)).toEqual(["x", "y", "z"]);
  });
});

describe("SRT", () => {
  const srt = "1\n00:00:01,000 --> 00:00:03,500\nHello\nthere\n\n2\n00:00:04,000 --> 00:00:05,000\nBye\n";

  it("reads timed cues, including multi-line text", () => {
    expect(parseTimedSrt(srt)).toEqual([
      { start: 1, end: 3.5, text: "Hello\nthere" },
      { start: 4, end: 5, text: "Bye" },
    ]);
  });

  it("copes with a BOM, Windows line endings and dots as the decimal mark", () => {
    const raw = "﻿1\r\n00:00:01.5 --> 00:00:02.25\r\nHi\r\n";
    expect(parseTimedSrt(raw)).toEqual([{ start: 1.5, end: 2.25, text: "Hi" }]);
  });

  it("skips blocks without a time range or without text", () => {
    expect(parseTimedSrt("1\njust text\n\n2\n00:00:01,000 --> 00:00:02,000\n")).toEqual([]);
  });

  it("formats times", () => {
    expect(formatSrtTime(3661.5)).toBe("01:01:01,500");
    expect(formatSrtTime(-4)).toBe("00:00:00,000");
    expect(formatSrtTime(0.0004)).toBe("00:00:00,000");
  });

  it("writes cues back in time order so they read again unchanged", () => {
    const cues = [
      { start: 5, end: 6, text: "second" },
      { start: 1, end: 2, text: "first" },
    ];
    expect(parseTimedSrt(cuesToSrt(cues))).toEqual([cues[1], cues[0]]);
  });

  it("reads an SRT without timestamps as one block per entry", () => {
    expect(parsePlainBlocks("1\nFirst line\n\n2\nSecond line\n")).toEqual(["First line", "Second line"]);
  });

  it("reads plain text as one block per line when there are no paragraphs", () => {
    expect(parsePlainBlocks("one\ntwo\n3\nthree")).toEqual(["one", "two", "three"]);
    expect(parsePlainBlocks("   ")).toEqual([]);
  });
});

describe("placing subtitles", () => {
  const two = timeline([seg("a"), seg("b")]);

  it("puts a timed cue in the clip under its middle, with times relative to that clip", () => {
    const [first, second] = cuesFromTimed(two, [
      { start: 8.5, end: 9.5, text: "in a" },
      { start: 12, end: 14, text: "in b" },
    ]);
    expect(first).toMatchObject({ segmentId: "a", start: 8.5, end: 9.5 });
    expect(second).toMatchObject({ segmentId: "b", start: 2, end: 4 });
  });

  it("moves a cue to another clip when it is dragged there, unless it is pinned", () => {
    const cue = { id: "c", segmentId: "a", start: 1, end: 2, text: "x" };
    expect(anchorCue(two, cue, 12, 13)).toMatchObject({ segmentId: "b", start: 2, end: 3 });
    expect(anchorCue(two, cue, 12, 13, true).segmentId).toBe("a");
  });

  it("spreads text blocks over the narrated time, by their length", () => {
    const narrated = timeline([seg("a", { trimOut: 12, videoDuration: 12, audio: "a.wav", audioOffset: 1, audioDuration: 10 })]);
    const cues = autoTimeBlocks(narrated, ["aaaa", "bbbb"]);
    expect(cues).toHaveLength(2);
    expect(cues[0].start).toBeCloseTo(1);
    expect(cues[0].end).toBeCloseTo(6);
    expect(cues[1].start).toBeCloseTo(6);
    expect(cues[1].end).toBeCloseTo(11);
    expect(cues.every((c) => c.segmentId === "a")).toBe(true);
  });

  it("returns nothing when there is nothing to place", () => {
    expect(autoTimeBlocks(emptyTimeline(), ["a"])).toEqual([]);
    expect(autoTimeBlocks(two, [])).toEqual([]);
  });
});

describe("timeline.json", () => {
  const edited: TimelineData = {
    segments: [seg("a", { audio: "a.wav", audioDuration: 4, audioOffset: 1, trimIn: 1, trimOut: 6 })],
    subtitles: [{ id: "c1", segmentId: "a", start: 1, end: 3, text: "hello" }],
    texts: [],
    music: { path: "assets/audio/music/bed.mp3", label: "bed", volume: 0.3 },
  };

  it("keeps the whole editor state, so the next open gives the same timeline back", () => {
    expect(timelineFromEditorState(toManifest("Trip", edited))).toEqual(edited);
  });

  it("writes what the exporter reads: trim, narration and global subtitle times", () => {
    const manifest = toManifest("Trip", edited);
    expect(manifest.video_tracks[0]).toMatchObject({ file_path: "assets/video/a.mp4", audio_path: "a.wav", audio_offset: 1, trim_in: 1, trim_out: 6 });
    expect(manifest.subtitles).toEqual([{ start: 1, end: 3, text: "hello" }]);
    expect(manifest.burn_subtitles).toBe(true);
    expect(manifest.music).toEqual({ path: "assets/audio/music/bed.mp3", volume: 0.3 });
  });

  it("leaves trim_out empty when the clip is not cut at the end", () => {
    const manifest = toManifest("Trip", timeline([seg("a")]));
    expect(manifest.video_tracks[0].trim_out).toBeNull();
  });

  it("does not take a timeline.json written by the pipeline for an editor state", () => {
    expect(timelineFromEditorState({ video_tracks: [] })).toBeNull();
    expect(timelineFromEditorState({ editor: { version: 99, segments: [] } })).toBeNull();
  });

  it("builds the timeline from the pipeline's own file", async () => {
    const raw = {
      video_tracks: [
        { file_path: "assets/video/route/02_waypoint_01_a.mp4", audio_path: "assets/audio/02_waypoint_01_a.wav", audio_offset: 0.5, fade_into_next_seconds: 0.8 },
        { file_path: "assets/video/attraction/04_attraction_01_a.mp4", type: "static_popup" },
      ],
      burn_subtitles: false,
    };
    const probe = async (_: string, kind: "video" | "audio") => (kind === "video" ? 12 : 7);
    const built = await timelineFromPipeline(raw, probe);
    expect(built.segments).toHaveLength(1);
    expect(built.segments[0]).toMatchObject({ kind: "route", videoDuration: 12, trimOut: 12, audioDuration: 7, audioOffset: 0.5, fadeIntoNext: 0.8 });
  });
});
