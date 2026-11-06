import { Waypoint } from "../types";
import { inSubCourse, mainStops } from "./courses";

// Main stops: S, 1, 2, … E (stop-bys +1, +2); sub course stops B1, B2, … (an anchor shows the main stop's label);
// street views their own V1, V2 (never part of the other counts).
export function stopLabel(all: Waypoint[], at: number): string {
  const wp = all[at];
  if (wp?.isStreetView) {
    return `V${all.slice(0, at + 1).filter((w) => w.isStreetView).length}`;
  }
  if (wp && inSubCourse(wp)) {
    const main = all.findIndex((w) => w.id === wp.branchOf);
    if (main !== -1) return stopLabel(all, main);
    return `B${all.filter((w) => inSubCourse(w) && !w.branchOf).indexOf(wp) + 1}`;
  }
  const waypoints = mainStops(all);
  const index = waypoints.indexOf(wp);
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
