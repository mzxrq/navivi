import { Waypoint } from "../types";

export function stopLabel(waypoints: Waypoint[], index: number): string {
  if (index === 0) return "S";
  if (index === waypoints.length - 1 && waypoints.length > 1) return "E";
  if (waypoints[index]?.isStopBy) {
    let n = 0;
    for (let i = 1; i <= index; i++) if (waypoints[i].isStopBy) n++;
    return `+${n}`;
  }
  let n = 1;
  for (let i = 1; i < index; i++) if (!waypoints[i].isStopBy) n++;
  return String(n);
}
