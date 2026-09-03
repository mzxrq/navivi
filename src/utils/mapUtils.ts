import { Waypoint } from "../types";
import bezierSpline from "@turf/bezier-spline";
import { lineString } from "@turf/helpers";

export function getCurve(p1: [number, number], p2: [number, number]): [number, number][] {
    const [lat1, lng1] = p1;
    const [lat2, lng2] = p2;
    const midLat = (lat1 + lat2) / 2; // get geo midpoint
    const midLng = (lng1 + lng2) / 2;
    const dx = lat2 - lat1; // get perpendicular offset 
    const dy = lng2 - lng1;
    // this multiplier control how exaggerated the curve is, with 0.1 - 1.0 as multiplier of the total distance
    const curveHeight = 0.2; // this means curve bows out by 20% of total distance
    const controlLat = midLat - (dy * curveHeight);
    const controlLng = midLng + (dx * curveHeight);

    // create Turf LineString
    const line = lineString([[lng1, lat1], [controlLng, controlLat], [lng2, lat2]]);
    // create smooth bezier spline with mister Turf :cool: :sunglasses:
    // resolution = 10000 ensures we get plenty of micro coordinates for video backend :hehe:
    const curved = bezierSpline(line, { resolution: 10000, sharpness: 0.85 });
    return curved.geometry.coordinates.map(coord => [coord[1], coord[0]]);
}

// export const getCurve = (
//     start: [number, number],
//     end: [number, number],
//     segments = 30,
// ) => {
//     const [lat1, lon1] = start;
//     const [lat2, lon2] = end;

//     const mLat = (lat1 + lat2) / 2;
//     const mLon = (lon1 + lon2) / 2;

//     const dLat = lat2 - lat1;
//     const dLon = lon2 - lon1;
//     const ctrlLat = mLat - dLon * 0.2;
//     const ctrlLon = mLon + dLat * 0.2;

//     const curve: [number, number][] = [];
//     for (let i = 0; i <= segments; i++) {
//         const t = i / segments;
//         const u = 1 - t;
//         const lat = u * u * lat1 + 2 * u * t * ctrlLat + t * t * lat2;
//         const lon = u * u * lon1 + 2 * u * t * ctrlLon + t * t * lon2;
//         curve.push([lat, lon]);
//     }
//     return curve;
// };

export function pruneRouteCache(
    waypoints: Waypoint[],
    routeCache: Record<string, [number, number][]>,
): Record<string, [number, number][]> {
    const activeKeys = new Set<string>();

    for (let i = 0; i < waypoints.length - 1; i++) {
        const wp1 = waypoints[i];
        const wp2 = waypoints[i + 1];
        const mode = wp1.routeMode || "driving";

        const key = `${wp1.lat},${wp1.lng}|${wp2.lat},${wp2.lng}|${mode}`;
        activeKeys.add(key);
    }

    const cleanCache: Record<string, [number, number][]> = {};
    let deletedCount = 0;

    for (const [key, routeData] of Object.entries(routeCache)) {
        if (activeKeys.has(key)) {
            cleanCache[key] = routeData;
        } else {
            deletedCount++;
        }
    }

    if (deletedCount > 0) {
        console.log(`Garbage Collector removed ${deletedCount} unused ghost routes.`);
    }

    return cleanCache;
}

export interface OsmNode {
    lat: number;
    lon: number;
}

export const getDistanceKm = (lat1: number, lon1: number, lat2: number, lon2: number) => {
    const R = 6371; // earth radius
    const dLat = (lat2 - lat1) * (Math.PI / 180);
    const dLon = (lon2 - lon1) * (Math.PI / 180);
    const a = Math.sin(dLat/2) * Math.sin(dLat / 2) + Math.cos(lat1 * (Math.PI / 180)) * Math.cos(lat2 * (Math.PI / 180)) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return R * (2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a)));
};

// 🛠️ Fills in empty space between two coordinates to mimic high-res API data
export function fillRouteCoordinates(points: [number, number][], intervalKm: number = 0.01): [number, number][] {
  if (points.length < 2) return points;
  
  const densePath: [number, number][] = [];
  
  for (let i = 0; i < points.length - 1; i++) {
    const p1 = points[i];
    const p2 = points[i + 1];
    
    // Always push the start point of this segment
    densePath.push(p1);
    
    const dist = getDistanceKm(p1[0], p1[1], p2[0], p2[1]);
    
    // If the gap is larger than our interval (e.g., 10 meters), fill it with micro-points!
    if (dist > intervalKm) {
      const steps = Math.floor(dist / intervalKm);
      for (let j = 1; j <= steps; j++) {
        const fraction = j / (steps + 1);
        const lat = p1[0] + (p2[0] - p1[0]) * fraction;
        const lng = p1[1] + (p2[1] - p1[1]) * fraction;
        densePath.push([lat, lng]);
      }
    }
  }
  
  // Push the very final point
  densePath.push(points[points.length - 1]);
  
  return densePath;
}