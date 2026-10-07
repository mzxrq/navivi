import { describe, expect, it } from "vitest";
import {
  cumulativeMeters,
  elevationAlongPath,
  fillGaps,
  gradientColor,
  legGradients,
  routeProfile,
  sampleIndexes,
  segmentGradients,
  smoothElevations,
} from "./elevation";
import type { LatLon } from "./gpxTrack";

// Points going east, one every 0.0001 degree of longitude (about 9.2 m at latitude 34).
const line = (n: number): LatLon[] => Array.from({ length: n }, (_, i) => [34, 135 + i * 0.0001]);

describe("gradientColor", () => {
  it("is blue downhill, green flat, red uphill, and blends in between", () => {
    expect(gradientColor(-20)).toBe("#2563eb");
    expect(gradientColor(0)).toBe("#10b981");
    expect(gradientColor(25)).toBe("#ef4444");
    expect(gradientColor(2.5)).not.toBe("#10b981");
    expect(gradientColor(2.5)).not.toBe("#f97316");
  });

  it("uses the fallback when there is no slope", () => {
    expect(gradientColor(null, "#123456")).toBe("#123456");
    expect(gradientColor(NaN, "#123456")).toBe("#123456");
  });
});

describe("fillGaps", () => {
  it("interpolates holes and extends the ends", () => {
    expect(fillGaps([null, 10, null, null, 40, undefined])).toEqual([10, 10, 20, 30, 40, 40]);
  });
  it("returns null when nothing is known", () => {
    expect(fillGaps([null, undefined])).toBeNull();
  });
});

describe("smoothing and slope", () => {
  it("does not turn 1 m of GPS noise on a flat track into a steep slope", () => {
    const pts = line(40);
    const dist = cumulativeMeters(pts);
    const noisy = pts.map((_, i) => 50 + (i % 2 ? 1 : -1));
    const pct = segmentGradients(dist, smoothElevations(dist, noisy));
    expect(Math.max(...pct.map(Math.abs))).toBeLessThan(2);
  });

  it("reads a constant climb as its real percent", () => {
    const pts = line(40);
    const dist = cumulativeMeters(pts);
    const ele = dist.map((d) => 100 + d * 0.08);
    const pct = segmentGradients(dist, smoothElevations(dist, ele));
    for (const p of pct) expect(Math.abs(p - 8)).toBeLessThan(1);
  });

  it("caps absurd slopes from coincident points", () => {
    const pct = segmentGradients([0, 0.01, 100], [0, 50, 50], 5);
    expect(Math.max(...pct.map(Math.abs))).toBeLessThanOrEqual(40);
  });
});

describe("legGradients", () => {
  it("is null without elevation and colours each segment otherwise", () => {
    expect(legGradients({ positions: line(5), ele: null, source: null })).toBeNull();
    const pts = line(30);
    const ele = cumulativeMeters(pts).map((d) => d * 0.1);
    const g = legGradients({ positions: pts, ele, source: "recorded" })!;
    expect(g.segments).toHaveLength(29);
    expect(g.segments[10].color).toBe(gradientColor(10));
  });
});

describe("elevationAlongPath", () => {
  it("maps elevations recorded on a few points onto a dense version of the same path", () => {
    const refs = line(3);
    const dense = line(21).map((p, i) => [p[0], 135 + (i * 0.0002) / 20 * 1] as number[]);
    const out = elevationAlongPath(dense, refs, [0, 10, 40])!;
    expect(out).toHaveLength(21);
    expect(out[0]).toBeCloseTo(0);
    expect(out[20]).toBeCloseTo(40);
    expect(out[10]).toBeCloseTo(10, 0);
  });
  it("needs one elevation per reference point", () => {
    expect(elevationAlongPath(line(5), line(3), [1, 2])).toBeNull();
  });
});

describe("routeProfile", () => {
  it("joins legs that have elevation, skips the others and totals gain and loss", () => {
    const a = line(30);
    const b = line(30).map((p): LatLon => [p[0], p[1] + 0.01]);
    const up = cumulativeMeters(a).map((d) => 100 + d * 0.1);
    const down = cumulativeMeters(b).map((d) => 130 - d * 0.1);
    const prof = routeProfile([
      { positions: a, ele: up, source: "recorded" },
      { positions: line(4), ele: null, source: null },
      { positions: b, ele: down, source: "recorded" },
    ])!;
    expect(prof.points).toHaveLength(59);
    expect(prof.gain).toBeGreaterThan(15);
    expect(prof.loss).toBeGreaterThan(15);
    expect(prof.max).toBeGreaterThan(prof.min);
    expect(routeProfile([{ positions: a, ele: null, source: null }])).toBeNull();
  });
});

describe("sampleIndexes", () => {
  it("keeps the ends and thins dense paths", () => {
    const idx = sampleIndexes(line(100), 50);
    expect(idx[0]).toBe(0);
    expect(idx[idx.length - 1]).toBe(99);
    expect(idx.length).toBeLessThan(30);
  });
});
