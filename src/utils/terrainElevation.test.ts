import { describe, expect, it, vi } from "vitest";
import { decodeTerrainRgb, pickZoom, sampleTerrain, segmentElevations, tileCoords, type TerrainTile } from "./terrainElevation";

const flatTile = (h: number): TerrainTile => ({ size: 4, heights: new Float32Array(16).fill(h) });

describe("terrainElevation", () => {
  it("decodes Terrain-RGB", () => {
    expect(decodeTerrainRgb(1, 134, 160)).toBeCloseTo(0, 5);
    expect(decodeTerrainRgb(1, 134, 170)).toBeCloseTo(1, 5);
  });

  it("finds the tile of a point", () => {
    const t = tileCoords(0, 0, 1);
    expect(t).toMatchObject({ x: 1, y: 1 });
    expect(tileCoords(35.0, 135.0, 14).px).toBeGreaterThanOrEqual(0);
  });

  it("uses coarser zooms for long routes", () => {
    const short: [number, number][] = [[35, 135], [35.001, 135.001]];
    const long: [number, number][] = Array.from({ length: 400 }, (_, i) => [35 + i * 0.0075, 135 + i * 0.01]);
    expect(pickZoom(short)).toBe(14);
    expect(pickZoom(long)).toBeLessThan(14);
  });

  it("loads each tile once and reports null for a failed tile", async () => {
    const load = vi.fn(async (_z: number, x: number) => (x % 2 === 0 ? flatTile(100) : null));
    const pts: [number, number][] = [[35, 135], [35, 135.00001], [35, 135.00002]];
    const out = await sampleTerrain(pts, load);
    expect(load).toHaveBeenCalledTimes(1);
    expect(out.every((v) => v === 100 || v === null)).toBe(true);
  });

  it("prefers recorded elevation and falls back to terrain per segment", async () => {
    const load = vi.fn(async () => flatTile(50));
    const drawn = [[35, 135], [35.0005, 135], [35.001, 135]];
    const routed = [[35.001, 135], [35.002, 135]];
    const wps = [
      { lat: 35, lng: 135, routeMode: "draw", customRoute: [[35.0005, 135]], customRouteEle: [10, 20, 30] },
      { lat: 35.001, lng: 135 },
      { lat: 35.002, lng: 135 },
    ];
    const out = await segmentElevations(
      [{ positions: drawn, mode: "draw" }, { positions: routed, mode: "walking" }],
      wps,
      load,
    );
    expect(out[0]).toEqual([10, 20, 30]);
    expect(out[1]).toEqual([50, 50]);
  });

  it("gives null when terrain is unavailable", async () => {
    const out = await segmentElevations([{ positions: [[35, 135], [35.001, 135]], mode: "walking" }], [{ lat: 35, lng: 135 }, { lat: 35.001, lng: 135 }], async () => null);
    expect(out).toEqual([null]);
  });
});
