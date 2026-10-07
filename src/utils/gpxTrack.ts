export type LatLon = [number, number];

export interface TrackStop {
  lat: number;
  lng: number;
  name: string;
  index: number;
}

const toRad = Math.PI / 180;

export function distanceMeters(a: LatLon, b: LatLon): number {
  const dLat = (b[0] - a[0]) * toRad;
  const dLon = (b[1] - a[1]) * toRad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[0] * toRad) * Math.cos(b[0] * toRad) * Math.sin(dLon / 2) ** 2;
  return 2 * 6371000 * Math.asin(Math.min(1, Math.sqrt(h)));
}

export function nearestIndex(points: LatLon[], lat: number, lon: number): number {
  let best = 0;
  let bestD = Infinity;
  for (let i = 0; i < points.length; i++) {
    const d = (points[i][0] - lat) ** 2 + ((points[i][1] - lon) * Math.cos(lat * toRad)) ** 2;
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  }
  return best;
}

// Douglas-Peucker on a local flat projection; keeps the first and last point.
export function simplifyTrack<T extends number[]>(points: T[], toleranceMeters: number): T[] {
  if (points.length <= 2) return points;
  const lat0 = points[0][0] * toRad;
  const xy = points.map(([lat, lon]) => [lon * toRad * Math.cos(lat0) * 6371000, lat * toRad * 6371000]);
  const keep = new Uint8Array(points.length);
  keep[0] = keep[points.length - 1] = 1;
  const stack: [number, number][] = [[0, points.length - 1]];
  while (stack.length) {
    const [s, e] = stack.pop()!;
    const [x1, y1] = xy[s];
    const [x2, y2] = xy[e];
    const dx = x2 - x1;
    const dy = y2 - y1;
    const len = Math.hypot(dx, dy);
    let far = -1;
    let farD = toleranceMeters;
    for (let i = s + 1; i < e; i++) {
      const d = len === 0 ? Math.hypot(xy[i][0] - x1, xy[i][1] - y1) : Math.abs(dy * xy[i][0] - dx * xy[i][1] + x2 * y1 - y2 * x1) / len;
      if (d > farD) {
        farD = d;
        far = i;
      }
    }
    if (far > -1) {
      keep[far] = 1;
      stack.push([s, far], [far, e]);
    }
  }
  return points.filter((_, i) => keep[i]);
}

// Google Maps exports put "日本、〒000-0000 " in front of every address.
export function tidyPlaceName(name: string): string {
  return name.replace(/^日本、\s*(〒?\d{3}-?\d{4})?\s*/, "").trim() || name;
}

// Stops snapped to positions along the recorded track, in track order. Named stops that sit near the
// start or end replace them; otherwise the track's own start and end are added so no part is cut off.
export function stopsAlongTrack(points: LatLon[], named: { lat: number; lon: number; name: string }[], nearMeters = 150): TrackStop[] {
  if (points.length === 0) return [];
  const last = points.length - 1;
  const stops: TrackStop[] = named
    .map((w) => ({ lat: w.lat, lng: w.lon, name: w.name, index: nearestIndex(points, w.lat, w.lon) }))
    .sort((a, b) => a.index - b.index);

  const first = stops[0];
  if (!first || distanceMeters([first.lat, first.lng], points[0]) > nearMeters) {
    stops.unshift({ lat: points[0][0], lng: points[0][1], name: "", index: 0 });
  }
  const end = stops[stops.length - 1];
  if (last > 0 && distanceMeters([end.lat, end.lng], points[last]) > nearMeters) {
    stops.push({ lat: points[last][0], lng: points[last][1], name: "", index: last });
  }
  return stops;
}

// The leg leaving stop `from` toward `to`, as the inner points of the recorded track between them.
export function legAlongTrack<T extends number[]>(points: T[], from: TrackStop, to: TrackStop, toleranceMeters = 4): T[] | null {
  if (to.index <= from.index + 1) return null;
  const slice = simplifyTrack(points.slice(from.index, to.index + 1), toleranceMeters);
  return slice.length > 2 ? slice.slice(1, -1) : null;
}

// Elevation of a leg as [stop, ...inner points, next stop], parallel to Waypoint.customRoute. Null when the track has none.
export function legElevations(inner: number[][], startEle?: number, endEle?: number): (number | null)[] | null {
  const round = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? Math.round(v * 10) / 10 : null);
  const ele = [round(startEle), ...inner.map((p) => round(p[2])), round(endEle)];
  return ele.some((v) => v !== null) ? ele : null;
}
