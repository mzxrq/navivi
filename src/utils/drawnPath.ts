import type { AnchorCurve, Waypoint } from "../types";
import { fillRouteCoordinates, getDistanceKm } from "./mapUtils";

type LatLng = [number, number];
type Handles = { in: LatLng; out: LatLng };
type PathPatch = Pick<Waypoint, "customRoute" | "customRouteCurve" | "drawStyle">;

const lngScale = (lat: number) => Math.max(0.05, Math.cos((lat * Math.PI) / 180));

// The curve of every anchor in wp.customRoute. A stored array that no longer fits the anchors is ignored; an old
// "spline" leg without one reads as every anchor smooth.
export function curvesOf(wp: Pick<Waypoint, "customRoute" | "customRouteCurve" | "drawStyle">): AnchorCurve[] {
  const n = wp.customRoute?.length ?? 0;
  if (wp.customRouteCurve && wp.customRouteCurve.length === n) return wp.customRouteCurve;
  return Array.from({ length: n }, () => (wp.drawStyle === "spline" ? "auto" : null));
}

export const isCurved = (curves: AnchorCurve[]) => curves.some((c) => c !== null);
export const isAllSmooth = (curves: AnchorCurve[]) => curves.length > 0 && curves.every((c) => c !== null);

function autoHandles(prev: LatLng, p: LatLng, next: LatLng): Handles {
  const k = lngScale(p[0]);
  const toNext: LatLng = [next[0] - p[0], (next[1] - p[1]) * k];
  const toPrev: LatLng = [prev[0] - p[0], (prev[1] - p[1]) * k];
  const t: LatLng = [toNext[0] - toPrev[0], toNext[1] - toPrev[1]];
  const len = Math.hypot(t[0], t[1]);
  if (len === 0) return { in: [0, 0], out: [0, 0] };
  const u: LatLng = [t[0] / len, t[1] / len];
  const dNext = Math.hypot(toNext[0], toNext[1]) / 3;
  const dPrev = Math.hypot(toPrev[0], toPrev[1]) / 3;
  return { out: [u[0] * dNext, (u[1] * dNext) / k], in: [-u[0] * dPrev, (-u[1] * dPrev) / k] };
}

// Handle offsets of each node in [from, ...anchors, to]; stops never have handles, corner anchors neither.
export function handlesFor(nodes: LatLng[], curves: AnchorCurve[]): (Handles | null)[] {
  return nodes.map((p, i) => {
    const c = i === 0 || i === nodes.length - 1 ? null : curves[i - 1];
    if (!c) return null;
    return c === "auto" ? autoHandles(nodes[i - 1], p, nodes[i + 1]) : c;
  });
}

// The leg as dense points, one cubic Bezier per stretch between nodes (a straight fill when neither end has a handle).
export function sampleDrawnPath(nodes: LatLng[], curves: AnchorCurve[], stepKm = 0.01): LatLng[] {
  if (nodes.length < 2 || !isCurved(curves)) return fillRouteCoordinates(nodes, stepKm);
  const handles = handlesFor(nodes, curves);
  const out: LatLng[] = [];
  for (let i = 0; i < nodes.length - 1; i++) {
    const p0 = nodes[i];
    const p3 = nodes[i + 1];
    const h0 = handles[i];
    const h3 = handles[i + 1];
    if (!h0 && !h3) {
      out.push(...fillRouteCoordinates([p0, p3], stepKm).slice(0, -1));
      continue;
    }
    const c1: LatLng = h0 ? [p0[0] + h0.out[0], p0[1] + h0.out[1]] : p0;
    const c2: LatLng = h3 ? [p3[0] + h3.in[0], p3[1] + h3.in[1]] : p3;
    const reach = getDistanceKm(p0[0], p0[1], c1[0], c1[1]) + getDistanceKm(c1[0], c1[1], c2[0], c2[1]) + getDistanceKm(c2[0], c2[1], p3[0], p3[1]);
    const steps = Math.min(3000, Math.max(8, Math.ceil(reach / stepKm)));
    for (let s = 0; s < steps; s++) {
      const t = s / steps;
      const u = 1 - t;
      const a = u * u * u;
      const b = 3 * u * u * t;
      const c = 3 * u * t * t;
      const d = t * t * t;
      out.push([a * p0[0] + b * c1[0] + c * c2[0] + d * p3[0], a * p0[1] + b * c1[1] + c * c2[1] + d * p3[1]]);
    }
  }
  out.push(nodes[nodes.length - 1]);
  return out;
}

const withCurves = (route: LatLng[], curves: AnchorCurve[]): PathPatch => ({
  customRoute: route,
  customRouteCurve: isCurved(curves) ? curves : undefined,
  drawStyle: undefined,
});

export const pathOf = (wp: Pick<Waypoint, "customRoute" | "customRouteCurve" | "drawStyle">): PathPatch =>
  withCurves([...(wp.customRoute ?? [])], [...curvesOf(wp)]);

// Every anchor kept its curve, so retracing a smooth path stays smooth: a dragged anchor's two handles trade places.
export function reversedPathOf(wp: Pick<Waypoint, "customRoute" | "customRouteCurve" | "drawStyle">): PathPatch {
  const swap = (c: AnchorCurve): AnchorCurve => (c && c !== "auto" ? { in: c.out, out: c.in } : c);
  return withCurves([...(wp.customRoute ?? [])].reverse(), [...curvesOf(wp)].reverse().map(swap));
}

// A point added to a path that is smooth all the way along is smooth too.
export function insertAnchor(wp: Waypoint, at: number, pos: LatLng): PathPatch {
  const route = [...(wp.customRoute ?? [])];
  const curves = [...curvesOf(wp)];
  const smooth = isAllSmooth(curves);
  route.splice(at, 0, pos);
  curves.splice(at, 0, smooth ? "auto" : null);
  return withCurves(route, curves);
}

export function removeAnchors(wp: Waypoint, indexes: Set<number>): PathPatch {
  const curves = curvesOf(wp);
  return withCurves(
    (wp.customRoute ?? []).filter((_, i) => !indexes.has(i)),
    curves.filter((_, i) => !indexes.has(i)),
  );
}

export function moveAnchor(wp: Waypoint, idx: number, pos: LatLng): PathPatch {
  return withCurves(
    (wp.customRoute ?? []).map((p, i) => (i === idx ? pos : p)),
    [...curvesOf(wp)],
  );
}

export function reorderAnchors(wp: Waypoint, from: number, to: number): PathPatch {
  const route = [...(wp.customRoute ?? [])];
  const curves = [...curvesOf(wp)];
  route.splice(to, 0, route.splice(from, 1)[0]);
  curves.splice(to, 0, curves.splice(from, 1)[0]);
  return withCurves(route, curves);
}

export function toggleAnchorCurve(wp: Waypoint, idx: number): PathPatch {
  const curves = [...curvesOf(wp)];
  curves[idx] = curves[idx] ? null : "auto";
  return withCurves([...(wp.customRoute ?? [])], curves);
}

export function setAllCurves(wp: Waypoint, smooth: boolean): PathPatch {
  const route = [...(wp.customRoute ?? [])];
  return withCurves(route, route.map((): AnchorCurve => (smooth ? "auto" : null)));
}

// Drag one handle of an anchor. The other handle keeps its length but turns to stay opposite, so the curve passes
// through the anchor without a kink.
export function dragHandle(wp: Waypoint, from: LatLng, to: LatLng, idx: number, which: "in" | "out", pos: LatLng): PathPatch {
  const route = [...(wp.customRoute ?? [])];
  const curves = [...curvesOf(wp)];
  const nodes: LatLng[] = [from, ...route, to];
  const current = handlesFor(nodes, curves)[idx + 1];
  if (!current) return withCurves(route, curves);
  const anchor = route[idx];
  const k = lngScale(anchor[0]);
  const dragged: LatLng = [pos[0] - anchor[0], pos[1] - anchor[1]];
  const m: LatLng = [dragged[0], dragged[1] * k];
  const len = Math.hypot(m[0], m[1]);
  const other = which === "out" ? current.in : current.out;
  const otherLen = Math.hypot(other[0], other[1] * k);
  const opposite: LatLng = len === 0 ? other : [(-m[0] / len) * otherLen, ((-m[1] / len) * otherLen) / k];
  curves[idx] = which === "out" ? { out: dragged, in: opposite } : { in: dragged, out: opposite };
  return withCurves(route, curves);
}
