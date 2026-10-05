import { describe, expect, it, vi } from "vitest";
import { buildGraph, closeGaps, distanceM, findPath, inJapan, tileOf, type LatLng } from "./gsiPaths";

const M = 1 / 111_000; // one metre of latitude, in degrees
const at = (north: number, east: number): LatLng => [34 + north * M, 135 + (east * M) / Math.cos((34 * Math.PI) / 180)];

describe("tiles and place", () => {
  it("puts Tokyo and Gyojado in their z16 tiles", () => {
    expect(tileOf([35.681236, 139.767125])).toEqual([58211, 25806]);
    expect(tileOf([34.273943, 135.069517])).toEqual([57356, 26119]);
  });

  it("knows Japan from elsewhere", () => {
    expect(inJapan([34.27, 135.07])).toBe(true);
    expect(inJapan([51.5, -0.12])).toBe(false);
  });
});

describe("findPath", () => {
  // A trail 0..200 m east with one vertex per end, and a branch north from its middle.
  const graph = buildGraph([
    [at(0, 0), at(0, 100), at(0, 200)],
    [at(100, 100), at(0, 100)],
    [at(500, 500), at(500, 600)],
  ]);
  const length = (path: LatLng[]) => path.slice(1).reduce((sum, p, i) => sum + distanceM(path[i], p), 0);

  it("joins lines that share a vertex into one network", () => {
    const path = findPath(graph, at(100, 100), at(0, 200))!;
    expect(length(path)).toBeCloseTo(200, -1);
  });

  it("snaps onto the middle of a long segment, not only onto its vertices", () => {
    const path = findPath(graph, at(5, 30), at(5, 70))!;
    expect(length(path)).toBeCloseTo(40, -1);
    expect(path[0][0]).toBeCloseTo(at(0, 30)[0], 6);
  });

  it("stays on the trail when both points are on the same segment", () => {
    const path = findPath(graph, at(0, 150), at(0, 120))!;
    expect(path).toHaveLength(2);
    expect(length(path)).toBeCloseTo(30, -1);
  });

  it("gives up when a point is far from every path", () => {
    expect(findPath(graph, at(0, 50), at(300, 300))).toBeNull();
  });

  it("gives up when the two paths are not connected", () => {
    expect(findPath(graph, at(0, 50), at(500, 550))).toBeNull();
  });

  it("finds the shortest way across a 12 x 12 grid (the heap orders many open nodes)", () => {
    const lines: LatLng[][] = [];
    for (let i = 0; i <= 11; i++) {
      lines.push(Array.from({ length: 12 }, (_, j) => at(i * 20, j * 20)));
      lines.push(Array.from({ length: 12 }, (_, j) => at(j * 20, i * 20)));
    }
    const grid = buildGraph(lines);
    expect(length(findPath(grid, at(0, 0), at(0, 220))!)).toBeCloseTo(220, -1);
    // corner to corner: no diagonal lanes, so the shortest walk is the Manhattan distance
    expect(length(findPath(grid, at(0, 0), at(220, 220))!)).toBeCloseTo(440, -1);
  });
});

describe("closeGaps", () => {
  const route: LatLng[] = [at(0, 0), at(0, 100), at(0, 200)];
  const noPath = async () => null;

  it("leaves a route that reaches both stops alone and never asks for a path", async () => {
    const bridge = vi.fn();
    const out = await closeGaps(route, [at(5, 0), at(0, 210)], bridge);
    expect(out).toBe(route);
    expect(bridge).not.toHaveBeenCalled();
  });

  it("fills a short end with the path it finds, then the stop", async () => {
    const stop = at(0, 260);
    const climb: LatLng[] = [at(0, 200), at(30, 230), at(0, 255)];
    const bridge = vi.fn(async (from: LatLng) => (from === route[2] ? climb : null));
    const out = await closeGaps(route, [at(0, 0), stop], bridge);
    expect(bridge).toHaveBeenCalledWith(route[2], stop);
    expect(out).toEqual([...route, ...climb, stop]);
  });

  it("draws a straight segment to the stop when there is no path", async () => {
    const stop = at(0, 260);
    expect(await closeGaps(route, [at(0, 0), stop], noPath)).toEqual([...route, stop]);
  });

  it("closes the start of the route too", async () => {
    const stop = at(0, -60);
    expect(await closeGaps(route, [stop, at(0, 200)], noPath)).toEqual([stop, ...route]);
  });

  describe("when GSI can walk the whole leg", () => {
    const start = at(0, 0);
    const via = at(100, 50);
    const end = at(0, 260);
    const long: LatLng[] = [at(0, 0), at(0, 400), at(0, 200)]; // router went a long way round and stopped short
    const hop = (from: LatLng, to: LatLng): LatLng[] => [from, to];

    it("uses it, through the via point, when it is shorter than router plus fill", async () => {
      const bridge = vi.fn(async (from: LatLng, to: LatLng) => hop(from, to));
      const out = await closeGaps(long, [start, via, end], bridge);
      expect(out).toEqual([start, start, via, via, via, end, end]);
    });

    it("keeps the router's route when the GSI one would be longer", async () => {
      const winding = async (from: LatLng, to: LatLng): Promise<LatLng[]> => [from, at(900, 900), to];
      const out = await closeGaps(long, [start, via, end], winding);
      expect(out[0]).toEqual(long[0]);
      expect(out).toContainEqual(long[1]);
    });

    it("keeps the router's route when one hop has no path", async () => {
      const bridge = async (from: LatLng, to: LatLng) => (to === via ? null : hop(from, to));
      const out = await closeGaps(long, [start, via, end], bridge);
      expect(out).toContainEqual(long[1]);
    });
  });
});
