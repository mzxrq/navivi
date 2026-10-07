import { distanceMeters, type LatLon } from "./gpxTrack";

export type MaybeEle = number | null | undefined;

export const SMOOTH_WINDOW_M = 60;
export const SLOPE_SPAN_M = 60;
export const SLOPE_CAP_PCT = 40;

/** Colour ramp for the heatmap and its legend: percent slope -> colour (blue downhill, green flat, red uphill). */
export const GRADIENT_STOPS: { pct: number; color: string }[] = [
  { pct: -10, color: "#2563eb" },
  { pct: -5, color: "#06b6d4" },
  { pct: 0, color: "#10b981" },
  { pct: 5, color: "#f97316" },
  { pct: 10, color: "#ef4444" },
];

const hexToRgb = (hex: string): [number, number, number] => [
  parseInt(hex.slice(1, 3), 16),
  parseInt(hex.slice(3, 5), 16),
  parseInt(hex.slice(5, 7), 16),
];

export function gradientColor(pct: number | null | undefined, fallback = "#3b82f6"): string {
  if (pct === null || pct === undefined || !Number.isFinite(pct)) return fallback;
  const first = GRADIENT_STOPS[0];
  const last = GRADIENT_STOPS[GRADIENT_STOPS.length - 1];
  if (pct <= first.pct) return first.color;
  if (pct >= last.pct) return last.color;
  for (let i = 1; i < GRADIENT_STOPS.length; i++) {
    const hi = GRADIENT_STOPS[i];
    if (pct > hi.pct) continue;
    const lo = GRADIENT_STOPS[i - 1];
    const f = (pct - lo.pct) / (hi.pct - lo.pct);
    const a = hexToRgb(lo.color);
    const b = hexToRgb(hi.color);
    return "#" + a.map((v, k) => Math.round(v + (b[k] - v) * f).toString(16).padStart(2, "0")).join("");
  }
  return last.color;
}

export function cumulativeMeters(points: number[][]): number[] {
  const out = [0];
  for (let i = 1; i < points.length; i++) {
    out.push(out[i - 1] + distanceMeters([points[i - 1][0], points[i - 1][1]], [points[i][0], points[i][1]]));
  }
  return out;
}

/** Fills unknown values: linear between known neighbours, flat beyond the ends. Null when nothing is known. */
export function fillGaps(ele: MaybeEle[]): number[] | null {
  const known = ele.map((v) => (typeof v === "number" && Number.isFinite(v) ? v : null));
  const idx = known.flatMap((v, i) => (v === null ? [] : [i]));
  if (idx.length === 0) return null;
  const out: number[] = new Array(ele.length);
  let k = 0;
  for (let i = 0; i < ele.length; i++) {
    if (known[i] !== null) {
      out[i] = known[i] as number;
      continue;
    }
    while (k < idx.length && idx[k] < i) k++;
    const next = idx[k];
    const prev = idx[k - 1];
    if (prev === undefined) out[i] = known[next] as number;
    else if (next === undefined) out[i] = known[prev] as number;
    else out[i] = (known[prev] as number) + ((known[next] as number) - (known[prev] as number)) * ((i - prev) / (next - prev));
  }
  return out;
}

/** Moving average over a distance window; recorded elevation is only accurate to a few metres. */
export function smoothElevations(dist: number[], ele: number[], windowM = SMOOTH_WINDOW_M): number[] {
  if (ele.length < 3 || windowM <= 0) return ele.slice();
  const half = windowM / 2;
  const out: number[] = new Array(ele.length);
  let lo = 0;
  let hi = 0;
  let sum = 0;
  const end = dist[ele.length - 1];
  for (let i = 0; i < ele.length; i++) {
    // The window shrinks toward the ends so the first and last stretch are not flattened by one-sided averaging.
    const w = Math.min(half, dist[i] - dist[0], end - dist[i]);
    while (hi < ele.length && dist[hi] <= dist[i] + w) sum += ele[hi++];
    while (lo < ele.length && dist[lo] < dist[i] - w) sum -= ele[lo++];
    out[i] = sum / (hi - lo);
  }
  return out;
}

/** Percent slope of each segment (point i to i+1), measured over at least `spanM` metres so that two
 *  nearby points with a 1 m reading difference do not turn into a 30% wall. */
export function segmentGradients(dist: number[], ele: number[], spanM = SLOPE_SPAN_M): number[] {
  const n = ele.length;
  const out: number[] = [];
  for (let i = 0; i < n - 1; i++) {
    let a = i;
    let b = i + 1;
    while (dist[b] - dist[a] < spanM && (a > 0 || b < n - 1)) {
      if (a > 0) a--;
      if (dist[b] - dist[a] >= spanM) break;
      if (b < n - 1) b++;
    }
    const run = dist[b] - dist[a];
    const pct = run > 0 ? ((ele[b] - ele[a]) / run) * 100 : 0;
    out.push(Math.max(-SLOPE_CAP_PCT, Math.min(SLOPE_CAP_PCT, pct)));
  }
  return out;
}

/** Elevation for each of `positions` (a densified version of the polyline `refs`), by position along the path. */
export function elevationAlongPath(positions: number[][], refs: number[][], refEle: number[]): number[] | null {
  if (positions.length < 2 || refs.length < 2 || refs.length !== refEle.length) return null;
  const pd = cumulativeMeters(positions);
  const rd = cumulativeMeters(refs);
  const pTotal = pd[pd.length - 1];
  const rTotal = rd[rd.length - 1];
  const out: number[] = [];
  let j = 0;
  for (let i = 0; i < positions.length; i++) {
    const d = pTotal > 0 && rTotal > 0 ? (pd[i] / pTotal) * rTotal : 0;
    while (j < refs.length - 2 && rd[j + 1] < d) j++;
    const span = rd[j + 1] - rd[j];
    const f = span > 0 ? Math.min(1, Math.max(0, (d - rd[j]) / span)) : 0;
    out.push(refEle[j] + (refEle[j + 1] - refEle[j]) * f);
  }
  return out;
}

export interface LegElevation {
  positions: LatLon[];
  /** Same length as positions, or null when this leg has no elevation. */
  ele: number[] | null;
  source: "recorded" | "terrain" | null;
}

export interface Gradient {
  segments: { from: LatLon; to: LatLon; pct: number; color: string }[];
}

/** Per-segment slopes for one leg, smoothed. Null when the leg has no elevation. */
export function legGradients(leg: LegElevation): Gradient | null {
  if (!leg.ele || leg.positions.length < 2) return null;
  const dist = cumulativeMeters(leg.positions);
  const pct = segmentGradients(dist, smoothElevations(dist, leg.ele));
  return {
    segments: pct.map((p, i) => ({ from: leg.positions[i], to: leg.positions[i + 1], pct: p, color: gradientColor(p) })),
  };
}

export interface RouteProfile {
  dist: number[];
  ele: number[];
  points: LatLon[];
  totalMeters: number;
  min: number;
  max: number;
  gain: number;
  loss: number;
}

/** One profile over every leg that has elevation, in route order (legs without elevation are skipped). */
export function routeProfile(legs: LegElevation[]): RouteProfile | null {
  const points: LatLon[] = [];
  const dist: number[] = [];
  const ele: number[] = [];
  let offset = 0;
  for (const leg of legs) {
    if (!leg.ele || leg.positions.length < 2) continue;
    const d = cumulativeMeters(leg.positions);
    const s = smoothElevations(d, leg.ele);
    const start = points.length > 0 ? 1 : 0;
    const join = points.length > 0 ? distanceMeters(points[points.length - 1], leg.positions[0]) : 0;
    for (let i = start; i < leg.positions.length; i++) {
      points.push(leg.positions[i]);
      dist.push(offset + join + d[i]);
      ele.push(s[i]);
    }
    offset = dist[dist.length - 1];
  }
  if (points.length < 2) return null;
  let gain = 0;
  let loss = 0;
  // Ignore wiggles under 1 m so smoothing leftovers do not inflate the totals.
  let ref = ele[0];
  for (const e of ele) {
    if (e - ref >= 1) {
      gain += e - ref;
      ref = e;
    } else if (ref - e >= 1) {
      loss += ref - e;
      ref = e;
    }
  }
  return { dist, ele, points, totalMeters: offset, min: Math.min(...ele), max: Math.max(...ele), gain, loss };
}

/** Every `stepM` along the path (plus the last point): fewer terrain lookups for dense legs. */
export function sampleIndexes(positions: number[][], stepM = 20, maxCount = 400): number[] {
  const d = cumulativeMeters(positions);
  const total = d[d.length - 1] || 0;
  const step = Math.max(stepM, total / maxCount);
  const idx = [0];
  let next = step;
  for (let i = 1; i < positions.length - 1; i++) {
    if (d[i] >= next) {
      idx.push(i);
      next = d[i] + step;
    }
  }
  if (positions.length > 1) idx.push(positions.length - 1);
  return idx;
}

/** Recorded elevation for a drawn leg whose geometry is `positions`; null when it was not recorded or the
 *  drawn path was edited since (the saved list only fits [stop, ...customRoute, next stop]). */
export function recordedLegElevation(
  positions: number[][],
  from: { lat: number; lng: number },
  to: { lat: number; lng: number },
  customRoute: number[][] | undefined,
  customRouteEle: MaybeEle[] | undefined,
): number[] | null {
  if (!customRoute || !customRouteEle || customRouteEle.length !== customRoute.length + 2) return null;
  const filled = fillGaps(customRouteEle);
  if (!filled) return null;
  return elevationAlongPath(positions, [[from.lat, from.lng], ...customRoute, [to.lat, to.lng]], filled);
}
