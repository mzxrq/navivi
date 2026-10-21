import { describe, expect, it } from "vitest";
import {
  curvesOf,
  dragHandle,
  handlesFor,
  insertAnchor,
  moveAnchor,
  removeAnchors,
  reorderAnchors,
  reversedPathOf,
  sampleDrawnPath,
  setAllCurves,
  toggleAnchorCurve,
} from "../../src/utils/drawnPath";

const wp = (extra: object = {}) =>
  ({ id: "a", name: "A", lat: 35, lng: 135, routeMode: "draw", customRoute: [[35.001, 135.001], [35.002, 135.0], [35.003, 135.001]], ...extra }) as any;
const from: [number, number] = [35, 135];
const to: [number, number] = [35.004, 135];

describe("curvesOf", () => {
  it("is all corners for a plain path and all smooth for an old spline leg", () => {
    expect(curvesOf(wp())).toEqual([null, null, null]);
    expect(curvesOf(wp({ drawStyle: "spline" }))).toEqual(["auto", "auto", "auto"]);
  });

  it("ignores a stored list that no longer fits the anchors", () => {
    expect(curvesOf(wp({ customRouteCurve: ["auto"] }))).toEqual([null, null, null]);
  });
});

describe("editing anchors keeps their curves in step", () => {
  const curved = wp({ customRouteCurve: [null, "auto", null] });

  it("toggles one anchor without touching the others", () => {
    expect(toggleAnchorCurve(wp(), 1).customRouteCurve).toEqual([null, "auto", null]);
    expect(toggleAnchorCurve(curved, 1).customRouteCurve).toBeUndefined();
  });

  it("smooths or straightens everything at once", () => {
    expect(setAllCurves(wp(), true).customRouteCurve).toEqual(["auto", "auto", "auto"]);
    expect(setAllCurves(curved, false).customRouteCurve).toBeUndefined();
  });

  it("carries the curve when anchors are inserted, removed, moved or reordered", () => {
    expect(insertAnchor(curved, 1, [35.0015, 135.002]).customRouteCurve).toEqual([null, null, "auto", null]);
    expect(removeAnchors(curved, new Set([0])).customRouteCurve).toEqual(["auto", null]);
    expect(moveAnchor(curved, 1, [35.5, 135.5]).customRouteCurve).toEqual([null, "auto", null]);
    expect(reorderAnchors(curved, 1, 0).customRouteCurve).toEqual(["auto", null, null]);
  });

  it("makes a new point smooth when the whole path is smooth", () => {
    expect(insertAnchor(setAllCurves(wp(), true) as any, 3, [35.0035, 135.0]).customRouteCurve).toEqual(["auto", "auto", "auto", "auto"]);
  });

  it("swaps a dragged anchor's handles when the path is retraced", () => {
    const manual = wp({ customRouteCurve: [null, { in: [1, 2], out: [3, 4] }, null] });
    expect(reversedPathOf(manual).customRouteCurve).toEqual([null, { in: [3, 4], out: [1, 2] }, null]);
  });
});

describe("sampleDrawnPath", () => {
  it("only bends around the smooth anchor", () => {
    const route = wp().customRoute;
    const nodes: [number, number][] = [from, ...route, to];
    const straight = sampleDrawnPath(nodes, [null, null, null]);
    const bent = sampleDrawnPath(nodes, [null, "auto", null]);
    // the corner anchors are still points of the path, so the first and last stretches stay straight lines
    const has = (path: [number, number][], p: [number, number]) => path.some((q) => Math.abs(q[0] - p[0]) < 1e-9 && Math.abs(q[1] - p[1]) < 1e-9);
    expect(has(bent, route[0])).toBe(true);
    expect(has(bent, route[2])).toBe(true);
    expect(has(bent, route[1])).toBe(true);
    expect(bent.length).not.toBe(straight.length);
    expect(bent[0]).toEqual(from);
    expect(bent[bent.length - 1]).toEqual(to);
    // stretch from the start to the first (corner) anchor is unchanged
    const i = bent.findIndex((q) => q[0] === route[0][0] && q[1] === route[0][1]);
    const j = straight.findIndex((q) => q[0] === route[0][0] && q[1] === route[0][1]);
    expect(bent.slice(0, i + 1)).toEqual(straight.slice(0, j + 1));
  });

  it("leaves a straight path alone when nothing is smooth", () => {
    const nodes: [number, number][] = [from, [35.001, 135.0], to];
    expect(sampleDrawnPath(nodes, [null]).every((p) => p[1] === 135)).toBe(true);
  });
});

describe("dragHandle", () => {
  it("turns the other handle to stay opposite and keeps its length", () => {
    const w = wp({ customRouteCurve: [null, "auto", null] });
    const nodes: [number, number][] = [from, ...w.customRoute, to];
    const before = handlesFor(nodes, curvesOf(w))[2]!;
    const anchor = w.customRoute[1] as [number, number];
    const patch = dragHandle(w, from, to, 1, "out", [anchor[0] + 0.0004, anchor[1] + 0.0003]);
    const c = patch.customRouteCurve![1] as { in: [number, number]; out: [number, number] };
    expect(c.out[0]).toBeCloseTo(0.0004, 9);
    expect(c.out[1]).toBeCloseTo(0.0003, 9);
    const k = Math.cos((anchor[0] * Math.PI) / 180);
    const lenBefore = Math.hypot(before.in[0], before.in[1] * k);
    expect(Math.hypot(c.in[0], c.in[1] * k)).toBeCloseTo(lenBefore, 9);
    // opposite direction: cross product ~ 0 and dot product < 0
    const cross = c.out[0] * (c.in[1] * k) - c.out[1] * k * c.in[0];
    expect(Math.abs(cross)).toBeLessThan(1e-12);
    expect(c.out[0] * c.in[0] + c.out[1] * k * c.in[1] * k).toBeLessThan(0);
  });
});
