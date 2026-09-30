import { Waypoint } from "../types";

/** Badge text for the stop at `index`: "S" start, "E" end, "+n" for the n-th
 * stop-by in a run of stop-bys, otherwise the stop's number (stop-bys skipped). */
export function stopLabel(waypoints: Waypoint[], index: number): string {
  if (index === 0) return "S";
  if (index === waypoints.length - 1 && waypoints.length > 1) return "E";
  if (waypoints[index]?.isStopBy) {
    let n = 0;
    for (let i = index; i >= 0 && waypoints[i].isStopBy; i--) n++;
    return `+${n}`;
  }
  let n = 1;
  for (let i = 1; i < index; i++) if (!waypoints[i].isStopBy) n++;
  return String(n);
}
