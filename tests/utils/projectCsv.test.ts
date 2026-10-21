import { describe, expect, it } from "vitest";
import { csvEscape, hasSubtitles, legsCsv, stopsCsv, subtitlesCsv, toCsv } from "../../src/utils/projectCsv";
import { emptyTimeline, type Segment, type TimelineData } from "../../src/features/editor/model";
import type { RouteSegment, Waypoint } from "../../src/types";

const wp = (over: Partial<Waypoint> = {}) => ({ id: Math.random().toString(), lat: 0, lng: 0, name: "", routeMode: "walking", ...over }) as Waypoint;
const lines = (csv: string) => csv.trimEnd().split("\r\n");

describe("csvEscape / toCsv", () => {
  it("quotes commas, quotes and line breaks, and keeps Japanese as is", () => {
    expect(csvEscape("a,b")).toBe('"a,b"');
    expect(csvEscape('say "hi"')).toBe('"say ""hi"""');
    expect(csvEscape("one\ntwo")).toBe('"one\ntwo"');
    expect(csvEscape("白浜、とれとれ")).toBe("白浜、とれとれ");
    expect(csvEscape(undefined)).toBe("");
    expect(csvEscape(0)).toBe("0");
  });

  it("ends every row, including the last, with CRLF", () => {
    expect(toCsv(["a", "b"], [[1, "x,y"]])).toBe('a,b\r\n1,"x,y"\r\n');
  });
});

describe("stopsCsv", () => {
  it("writes one row per stop in order, with labels and counts", () => {
    const list = [
      wp({ name: "Start", lat: 33.7, lng: 135.3, images: ["a.jpg", "b.jpg"] }),
      wp({ name: "Shop", isStopBy: true, arrivingNarration: "Hello, world", viaPoints: [[1, 1]] }),
      wp({ name: "End", routeMode: "driving" }),
    ];
    const rows = lines(stopsCsv(list));
    expect(rows).toHaveLength(4);
    expect(rows[1].startsWith("1,S,Start,33.7,135.3,false,walking,")).toBe(true);
    expect(rows[1]).toContain(",2,0,0");
    expect(rows[2]).toContain('+1,Shop,0,0,true,walking,"Hello, world"');
    expect(rows[3].startsWith("3,E,End,0,0,false,,")).toBe(true);
  });
});

describe("legsCsv", () => {
  const a = wp({ name: "A", lat: 0, lng: 0 });
  const b = wp({ name: "B", lat: 0, lng: 0.01 });
  const c = wp({ name: "C", lat: 0, lng: 0.02 });
  const seg = (positions: [number, number][], mode = "walking"): RouteSegment => ({ positions, mode });

  it("measures a routed leg along its path", () => {
    const rows = lines(legsCsv([a, b], [seg([[0, 0], [0.005, 0.005], [0, 0.01]])]));
    expect(rows[1].startsWith("S,E,A,B,walking,")).toBe(true);
    const [, , , , , meters, basis, , points] = rows[1].split(",");
    expect(basis).toBe("route");
    expect(points).toBe("3");
    expect(Number(meters)).toBeGreaterThan(1570); // detour is longer than the 1112 m straight line
  });

  it("adds the climb from terrain heights, and the time with and without it", () => {
    const path = [[0, 0], [0.005, 0.005], [0, 0.01]] as [number, number][];
    const withClimb = lines(legsCsv([a, b], [seg(path)], [[0, 300, 0]]))[1].split(",");
    const flat = lines(legsCsv([a, b], [seg(path)]))[1].split(",");
    expect(lines(legsCsv([a, b], [seg(path)]))[0].split(",").slice(-5)).toEqual(["ascent_m", "ascent_source", "slope_distance_m", "minutes", "minutes_flat"]);
    expect(withClimb.slice(-5, -3)).toEqual(["300", "terrain"]);
    expect(Number(withClimb[withClimb.length - 2])).toBe(Number(withClimb[withClimb.length - 1]) + 30); // 300 m / 600 m per hour
    expect(flat.slice(-5, -3)).toEqual(["", ""]);
    expect(flat[flat.length - 2]).toBe(flat[flat.length - 1]);
  });

  it("falls back to the straight line when the leg is missing or still calculating", () => {
    const missing = lines(legsCsv([a, b], []))[1].split(",");
    expect(missing[5]).toBe("1111.9");
    expect(missing[6]).toBe("straight");
    const pending = lines(legsCsv([a, b], [seg([[0, 0], [0, 0.01]], "calculating")]))[1].split(",");
    expect(pending[6]).toBe("straight");
  });

  it("skips stop-bys that are not on the route, like the routing hook does", () => {
    const side = wp({ name: "Side", isStopBy: true, lat: 5, lng: 5 });
    const rows = lines(legsCsv([a, side, b, c], [seg([[0, 0], [0, 0.01]]), seg([[0, 0.01], [0, 0.02]])]));
    expect(rows).toHaveLength(3);
    expect(rows[1].startsWith("S,1,A,B,")).toBe(true);
    expect(rows[2].startsWith("1,E,B,C,")).toBe(true);
    const joined = legsCsv([a, { ...side, connectToRoute: true }, b], []);
    expect(lines(joined)).toHaveLength(3);
  });
});

describe("subtitlesCsv", () => {
  const seg = (id: string, label: string, trimOut: number): Segment => ({
    id, label, kind: "route", video: "", videoDuration: trimOut, trimIn: 0, trimOut, audioOffset: 0, volume: 1, muted: false, fadeIntoNext: 0,
  });
  const timeline: TimelineData = {
    ...emptyTimeline(),
    segments: [seg("s1", "Intro", 10), seg("s2", "Leg 1", 20)],
    subtitles: [
      { id: "c2", segmentId: "s2", start: 1, end: 3, text: "second, \"quoted\"" },
      { id: "c1", segmentId: "s1", start: 0.5, end: 2, text: "first" },
    ],
  };

  it("lists cues in timeline order with global times and segment labels", () => {
    const rows = lines(subtitlesCsv(timeline));
    expect(rows[0]).toBe("index,segment,start_s,end_s,text");
    expect(rows[1]).toBe("1,Intro,0.5,2,first");
    expect(rows[2]).toBe('2,Leg 1,11,13,"second, ""quoted"""');
  });

  it("reports whether there is anything to export", () => {
    expect(hasSubtitles(timeline)).toBe(true);
    expect(hasSubtitles(emptyTimeline())).toBe(false);
  });
});
