import { cumulativeMeters, fillGaps, recordedLegElevation, smoothElevations } from "./elevation";
import { distanceMeters, type LatLon } from "./gpxTrack";

// Mirrors services/tuning.py (REPORTED_MODE_SPEED_KMH, MODE_ALIASES, WALKING_ASCENT_M_PER_HOUR) and
// route_brief.py (_leg_ascent_m, build_brief), so the sidebar and the narration quote the same minutes.
const SPEED_KMH: Record<string, number> = { walking: 3, ferry: 35, car: 70, driving: 70, airplane: 500 };
const MODE_ALIAS: Record<string, string> = { direct: "walking", draw: "walking", curve: "airplane" };
export const ASCENT_M_PER_HOUR = 600;

export interface LegEstimate {
  km: number;
  minutes: number;
}

export const pathKm = (positions: number[][]): number => (cumulativeMeters(positions).pop() ?? 0) / 1000;

/** Metres climbed along the leg's recorded elevation (smoothed, descents ignored); null when none was recorded. */
export function recordedAscent(
  from: { lat: number; lng: number },
  to: { lat: number; lng: number },
  customRoute: number[][] | undefined,
  customRouteEle: (number | null)[] | undefined,
): number | null {
  const nodes = customRoute ?? [];
  if (!customRouteEle || customRouteEle.length !== nodes.length + 2) return null;
  const ele = fillGaps(customRouteEle);
  if (!ele) return null;
  const line = [[from.lat, from.lng], ...nodes, [to.lat, to.lng]];
  const smooth = smoothElevations(cumulativeMeters(line), ele);
  return smooth.slice(1).reduce((sum, v, i) => sum + Math.max(0, v - smooth[i]), 0);
}

/** Climb and slope distance from one elevation per path point (recorded or read from terrain tiles). */
export function pathProfile(positions: number[][], rawEle: number[]): { ascentM: number; slopeKm: number } | null {
  if (rawEle.length !== positions.length || positions.length < 2) return null;
  const ele = smoothElevations(cumulativeMeters(positions), rawEle);
  let up = 0;
  let m = 0;
  for (let i = 1; i < positions.length; i++) {
    up += Math.max(0, ele[i] - ele[i - 1]);
    m += Math.hypot(distanceMeters(positions[i - 1] as LatLon, positions[i] as LatLon), ele[i] - ele[i - 1]);
  }
  return { ascentM: up, slopeKm: m / 1000 };
}

/** Slope distance of a drawn leg from its recorded elevation; null without it. */
export function slopeKm(
  positions: number[][],
  from: { lat: number; lng: number },
  to: { lat: number; lng: number },
  customRoute: number[][] | undefined,
  customRouteEle: (number | null)[] | undefined,
): number | null {
  const raw = recordedLegElevation(positions, from, to, customRoute, customRouteEle);
  return raw ? (pathProfile(positions, raw)?.slopeKm ?? null) : null;
}

/** Map distance of the leg and the time to cover it: km / mode speed, plus 1 h per 600 m of climb for a walk with
 *  known climb (the caller passes one only for drawn lines, the only legs that record elevation). */
export function legEstimate(positions: number[][], mode: string, ascentM: number | null): LegEstimate {
  const km = pathKm(positions);
  const kind = MODE_ALIAS[mode] ?? mode;
  let hours = km / (SPEED_KMH[kind] ?? SPEED_KMH.walking);
  if (ascentM !== null && kind === "walking") hours += ascentM / ASCENT_M_PER_HOUR;
  return { km, minutes: Math.max(1, Math.round(hours * 60)) };
}

export interface LegFacts extends LegEstimate {
  slopeKm: number | null;
  ascentM: number | null;
  /** Where the climb comes from: the drawn line's recorded elevation, or the map's terrain tiles (coarser). */
  source: "recorded" | "terrain" | null;
  /** The time without any climb, to see what the climb adds. */
  flatMinutes: number;
}

interface LegEnd {
  lat: number;
  lng: number;
}
interface LegFrom extends LegEnd {
  routeMode?: string;
  customRoute?: number[][];
  customRouteEle?: (number | null)[];
}

/** Everything the sidebar row and the CSV say about one leg. Recorded elevation of a drawn line wins (it is what the
 *  narration uses); otherwise the terrain heights (one per path point, undefined/null = not found) give the climb. */
export function legFacts(from: LegFrom, to: LegEnd, seg: { positions: number[][]; mode: string }, terrain?: number[] | null): LegFacts {
  let ascentM: number | null = null;
  let slope: number | null = null;
  let source: LegFacts["source"] = null;
  if (from.routeMode === "draw") {
    ascentM = recordedAscent(from, to, from.customRoute, from.customRouteEle);
    slope = slopeKm(seg.positions, from, to, from.customRoute, from.customRouteEle);
    if (ascentM !== null) source = "recorded";
  }
  if (source === null && terrain) {
    const profile = pathProfile(seg.positions, terrain);
    if (profile) {
      ascentM = profile.ascentM;
      slope = profile.slopeKm;
      source = "terrain";
    }
  }
  return {
    ...legEstimate(seg.positions, seg.mode, ascentM),
    slopeKm: slope,
    ascentM,
    source,
    flatMinutes: legEstimate(seg.positions, seg.mode, null).minutes,
  };
}
