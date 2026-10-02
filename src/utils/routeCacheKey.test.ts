import { describe, expect, it } from "vitest";
import type { Waypoint } from "../types";
import { routeCacheKey } from "./routeCacheKey";

const wp = (over: Partial<Waypoint> = {}): Waypoint => ({ id: "a", lat: 33.66171, lng: 135.35972, name: "A", routeMode: "walking", ...over });
const to = wp({ id: "b", lat: 33.6679, lng: 135.3436, name: "B" });

describe("routeCacheKey", () => {
  it("names the two ends and the mode", () => {
    expect(routeCacheKey(wp(), to)).toBe("33.66171,135.35972|33.66790,135.34360|walking|");
  });

  it("falls back to driving when the stop has no mode", () => {
    expect(routeCacheKey(wp({ routeMode: undefined as never }), to)).toContain("|driving|");
  });

  it("includes the drawn path only for drawn legs", () => {
    const path: [number, number][] = [[33.1, 135.1]];
    expect(routeCacheKey(wp({ routeMode: "draw", customRoute: path }), to)).toContain(JSON.stringify(path));
    expect(routeCacheKey(wp({ routeMode: "walking", customRoute: path }), to)).not.toContain("33.1");
  });

  it("changes when via points are added, and stays as before when there are none", () => {
    const plain = routeCacheKey(wp(), to);
    expect(routeCacheKey(wp({ viaPoints: [] }), to)).toBe(plain);
    expect(routeCacheKey(wp({ viaPoints: [[33.2, 135.2]] }), to)).toBe(`${plain}|[[33.2,135.2]]`);
  });

  it("changes when a stop moves a little", () => {
    expect(routeCacheKey(wp({ lat: 33.66181 }), to)).not.toBe(routeCacheKey(wp(), to));
  });
});
