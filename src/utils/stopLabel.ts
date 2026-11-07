import { Waypoint } from "../types";

// S, 1, 2, … E; stop-bys +1, +2; street views their own V1, V2 (never part of the other counts).
export function stopLabel(waypoints: Waypoint[], index: number): string {
  if (waypoints[index]?.isStreetView) {
    return `V${waypoints.slice(0, index + 1).filter((w) => w.isStreetView).length}`;
  }
  if (index === 0) return "S";
  if (index === waypoints.length - 1 && waypoints.length > 1) return "E";
  if (waypoints[index]?.isStopBy) {
    let n = 0;
    for (let i = 1; i <= index; i++) if (waypoints[i].isStopBy && !waypoints[i].isStreetView) n++;
    return `+${n}`;
  }
  let n = 1;
  for (let i = 1; i < index; i++) if (!waypoints[i].isStopBy) n++;
  return String(n);
}
