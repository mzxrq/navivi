import type { Waypoint } from "../types";

// One key per leg, used by the routing hook (to look a leg up) and by saving (to decide which cached legs are still in use).
// "lat,lng|lat,lng|mode|drawnPathHash", plus "|viaPointsHash" only when the leg has via points, which keeps keys cached
// by older versions valid.
export function routeCacheKey(from: Waypoint, to: Waypoint): string {
  const mode = from.routeMode || "driving";
  const drawn = mode === "draw" ? JSON.stringify(from.customRoute || []) : "";
  const via = from.viaPoints?.length ? `|${JSON.stringify(from.viaPoints)}` : "";
  return `${from.lat.toFixed(5)},${from.lng.toFixed(5)}|${to.lat.toFixed(5)},${to.lng.toFixed(5)}|${mode}|${drawn}${via}`;
}
