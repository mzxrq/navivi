import type { RouteSegment, Waypoint } from "../types";
import { layout, placedCues, type TimelineData } from "../features/editor/model";
import { distanceMeters, type LatLon } from "./gpxTrack";
import { stopLabel } from "./stopLabel";

type Cell = string | number | boolean | null | undefined;

export function csvEscape(value: Cell): string {
  const s = value === null || value === undefined ? "" : String(value);
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCsv(headers: string[], rows: Cell[][]): string {
  return [headers, ...rows].map((r) => r.map(csvEscape).join(",")).join("\r\n") + "\r\n";
}

const round = (v: number, digits: number) => Math.round(v * 10 ** digits) / 10 ** digits;

export function stopsCsv(waypoints: Waypoint[]): string {
  const rows = waypoints.map((w, i) => [
    i + 1,
    stopLabel(waypoints, i),
    w.name,
    w.lat,
    w.lng,
    !!w.isStopBy,
    i < waypoints.length - 1 ? w.routeMode : "",
    w.arrivingNarration ?? "",
    w.attractionNarration ?? "",
    w.images?.length ?? 0,
    w.videos?.length ?? 0,
    w.viaPoints?.length ?? 0,
  ]);
  return toCsv(
    ["index", "label", "name", "lat", "lng", "is_stop_by", "route_mode", "arriving_narration", "attraction_narration", "photo_count", "video_count", "via_point_count"],
    rows,
  );
}

const pathMeters = (points: LatLon[]) => points.reduce((sum, p, i) => (i ? sum + distanceMeters(points[i - 1], p) : 0), 0);

// A leg is a pair of neighbouring *routed* stops (stop-bys that are not connected to the route are skipped), the same pairing
// useMapRouting uses, so routeSegments[i] is the leg from routed[i] to routed[i + 1]. A leg that is missing or still being
// calculated falls back to the straight line between its stops.
export function legsCsv(waypoints: Waypoint[], routeSegments: RouteSegment[]): string {
  const routed = waypoints.map((w, index) => ({ w, index })).filter(({ w }) => !w.isStopBy || w.connectToRoute);
  const rows: Cell[][] = [];
  for (let i = 0; i < routed.length - 1; i++) {
    const from = routed[i];
    const to = routed[i + 1];
    const seg = routeSegments[i];
    const usable = !!seg && seg.mode !== "calculating" && seg.positions.length >= 2;
    const meters = usable ? pathMeters(seg.positions) : distanceMeters([from.w.lat, from.w.lng], [to.w.lat, to.w.lng]);
    rows.push([
      stopLabel(waypoints, from.index),
      stopLabel(waypoints, to.index),
      from.w.name,
      to.w.name,
      from.w.routeMode,
      round(meters, 1),
      usable ? "route" : "straight",
      from.w.viaPoints?.length ?? 0,
      usable ? seg.positions.length : 2,
    ]);
  }
  return toCsv(["from_label", "to_label", "from_name", "to_name", "mode", "distance_m", "distance_basis", "via_point_count", "point_count"], rows);
}

export const hasSubtitles = (timeline: TimelineData) => timeline.segments.length > 0 && timeline.subtitles.length > 0;

export function subtitlesCsv(timeline: TimelineData): string {
  const { placed } = layout(timeline);
  const label = new Map(placed.map((p) => [p.seg.id, p.seg.label]));
  const rows = placedCues(timeline, placed).map((c, i) => [i + 1, label.get(c.segmentId) ?? "", round(c.globalStart, 2), round(c.globalEnd, 2), c.text]);
  return toCsv(["index", "segment", "start_s", "end_s", "text"], rows);
}
