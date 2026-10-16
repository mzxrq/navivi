import { describe, expect, it } from "vitest";
import { ASCENT_M_PER_HOUR, legEstimate, pathKm, pathProfile, recordedAscent, slopeKm } from "../../src/utils/legEstimate";

// 4 nodes 0.01 deg of longitude apart at 35N (~0.91 km each), so the 60 m smoothing window leaves them as recorded.
const A = { lat: 35, lng: 139 };
const B = { lat: 35, lng: 139.04 };
const nodes = [[35, 139.01], [35, 139.02], [35, 139.03]];
const line = [[A.lat, A.lng], ...nodes, [B.lat, B.lng]];

describe("legEstimate", () => {
  it("walks at 3 km/h and counts at least one minute", () => {
    const km = pathKm(line);
    expect(legEstimate(line, "walking", null).minutes).toBe(Math.round((km / 3) * 60));
    expect(legEstimate([[35, 139], [35, 139.00001]], "walking", null).minutes).toBe(1);
  });

  it("adds an hour per 600 m of climb to a walk, not to a boat", () => {
    const flat = legEstimate(line, "draw", null).minutes;
    expect(legEstimate(line, "draw", 600).minutes).toBe(flat + 60);
    expect(legEstimate(line, "ferry", 600).minutes).toBe(legEstimate(line, "ferry", null).minutes);
    expect(ASCENT_M_PER_HOUR).toBe(600);
  });
});

describe("recordedAscent / slopeKm", () => {
  it("sums only the climbs of the recorded elevation", () => {
    expect(recordedAscent(A, B, nodes, [0, 125, 250, 375, 500])).toBe(500);
    expect(recordedAscent(A, B, nodes, [500, 375, 250, 125, 0])).toBe(0);
  });

  it("is null when elevation is missing or does not fit the drawn line", () => {
    expect(recordedAscent(A, B, nodes, undefined)).toBeNull();
    expect(recordedAscent(A, B, nodes, [0, 100, 200])).toBeNull();
    expect(recordedAscent(A, B, nodes, [null, null, null, null, null])).toBeNull();
  });

  it("makes the path slightly longer when it climbs, and is null without elevation", () => {
    const ele = [0, 125, 250, 375, 500];
    const slope = slopeKm(line, A, B, nodes, ele)!;
    expect(slope).toBeGreaterThan(pathKm(line));
    expect(slope).toBeLessThan(pathKm(line) * 1.1);
    expect(slopeKm(line, A, B, nodes, undefined)).toBeNull();
  });
});

describe("pathProfile", () => {
  // a routed leg: a point every ~91 m along 0.04 deg of longitude, climbing steadily 300 m
  const dense = Array.from({ length: 41 }, (_, i) => [35, 139 + i * 0.001]);
  it("gets climb and slope distance from terrain heights, ignoring the descent", () => {
    const up = pathProfile(dense, dense.map((_, i) => i * 7.5))!;
    expect(up.ascentM).toBeGreaterThan(280);
    expect(up.ascentM).toBeLessThanOrEqual(300);
    expect(up.slopeKm).toBeGreaterThan(pathKm(dense));
    expect(pathProfile(dense, dense.map((_, i) => 300 - i * 7.5))!.ascentM).toBeLessThan(1);
  });
  it("is null when the heights do not match the path", () => {
    expect(pathProfile(dense, [1, 2, 3])).toBeNull();
  });
});
