import { describe, expect, it } from "vitest";
import { LatLon, distanceMeters, legAlongTrack, legElevations, nearestIndex, simplifyTrack, stopsAlongTrack, tidyPlaceName } from "./gpxTrack";

// A track going east along a line of latitude, one point every 0.001 degrees (about 92 m).
const line = (n: number, lat = 34): LatLon[] => Array.from({ length: n }, (_, i) => [lat, 135 + i * 0.001]);

describe("distanceMeters", () => {
  it("is zero for the same point and about 111 km per degree of latitude", () => {
    expect(distanceMeters([34, 135], [34, 135])).toBe(0);
    expect(distanceMeters([34, 135], [35, 135])).toBeGreaterThan(111000);
    expect(distanceMeters([34, 135], [35, 135])).toBeLessThan(111500);
  });
});

describe("nearestIndex", () => {
  it("finds the closest recorded point", () => {
    expect(nearestIndex(line(10), 34.0001, 135.0042)).toBe(4);
  });
});

describe("simplifyTrack", () => {
  it("drops points on a straight line and keeps both ends", () => {
    const out = simplifyTrack(line(20), 5);
    expect(out).toEqual([line(20)[0], line(20)[19]]);
  });

  it("keeps a corner", () => {
    const corner: LatLon[] = [
      [34, 135],
      [34, 135.01],
      [34.01, 135.01],
    ];
    expect(simplifyTrack(corner, 5)).toHaveLength(3);
  });

  it("leaves tracks of one or two points alone", () => {
    expect(simplifyTrack([[34, 135]], 5)).toEqual([[34, 135]]);
  });
});

describe("tidyPlaceName", () => {
  it("removes the country and postcode that map exports put in front of an address", () => {
    expect(tidyPlaceName("日本、〒649-0101 和歌山県和歌山市加太")).toBe("和歌山県和歌山市加太");
  });

  it("leaves other names, and never returns an empty one", () => {
    expect(tidyPlaceName("三段壁")).toBe("三段壁");
    expect(tidyPlaceName("日本、")).toBe("日本、");
  });
});

describe("stopsAlongTrack", () => {
  const track = line(21);

  it("adds the start and the end of the track when no named stop is near them", () => {
    const stops = stopsAlongTrack(track, [{ lat: 34, lon: 135.01, name: "Middle" }]);
    expect(stops.map((s) => [s.name, s.index])).toEqual([
      ["", 0],
      ["Middle", 10],
      ["", 20],
    ]);
  });

  it("uses a named stop near the start or end instead of adding one", () => {
    const stops = stopsAlongTrack(track, [
      { lat: 34, lon: 135.0001, name: "Start" },
      { lat: 34, lon: 135.0199, name: "End" },
    ]);
    expect(stops.map((s) => s.name)).toEqual(["Start", "End"]);
  });

  it("puts named stops in the order they are walked, not the order they are listed", () => {
    const stops = stopsAlongTrack(track, [
      { lat: 34, lon: 135.015, name: "B" },
      { lat: 34, lon: 135.005, name: "A" },
    ]);
    expect(stops.map((s) => s.name).filter(Boolean)).toEqual(["A", "B"]);
  });

  it("returns nothing for an empty track", () => {
    expect(stopsAlongTrack([], [{ lat: 1, lon: 1, name: "x" }])).toEqual([]);
  });
});

describe("legAlongTrack", () => {
  const bend: LatLon[] = [
    [34, 135],
    [34, 135.005],
    [34.005, 135.005],
    [34.005, 135.01],
  ];
  const stop = (index: number) => ({ lat: bend[index][0], lng: bend[index][1], name: "", index });

  it("returns the points between two stops, without the stops themselves", () => {
    expect(legAlongTrack(bend, stop(0), stop(3))).toEqual([bend[1], bend[2]]);
  });

  it("returns null when the stops are next to each other or the leg is straight", () => {
    expect(legAlongTrack(bend, stop(0), stop(1))).toBeNull();
    expect(legAlongTrack(line(10), stop(0), { lat: 34, lng: 135.009, name: "", index: 9 })).toBeNull();
  });
});

describe("elevation along a leg", () => {
  it("keeps the elevation of the points that survive simplification", () => {
    const track = Array.from({ length: 12 }, (_, i) => [34 + (i % 2 ? 0.001 : 0), 135 + i * 0.001, 100 + i]);
    const stops = [
      { lat: 34, lng: 135, name: "", index: 0 },
      { lat: 34, lng: 135.011, name: "", index: 11 },
    ];
    const inner = legAlongTrack(track, stops[0], stops[1], 4)!;
    expect(inner.length).toBeGreaterThan(0);
    for (const p of inner) expect(p[2]).toBe(100 + Math.round((p[1] - 135) / 0.001));
    const ele = legElevations(inner, track[0][2], track[11][2])!;
    expect(ele).toHaveLength(inner.length + 2);
    expect(ele[0]).toBe(100);
    expect(ele[ele.length - 1]).toBe(111);
  });

  it("is null when the track has no elevation", () => {
    expect(legElevations([[34, 135], [34, 135.1]])).toBeNull();
  });
});
