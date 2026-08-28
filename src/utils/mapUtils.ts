import L from "leaflet";
import { Waypoint } from "../types";

export const waypointIcon = (number: number, hexColor: string) => {
    return L.divIcon({
        className: "custom-marker",
        html: `<div style="background-color: ${hexColor} !important; width: 24px; height: 24px; border: 2px solid white; border-radius: 50%; box-shadow: 0 0 10px rgba(0,0,0,0.3); display: flex; align-items: center; justify-content: center; color: white; font-size: 10px; font-weight: bold;">
            ${number}
           </div>`,
        iconSize: [24, 24],
        iconAnchor: [12, 12],
    });
};

export const getCurve = (
    start: [number, number],
    end: [number, number],
    segments = 30,
) => {
    const [lat1, lon1] = start;
    const [lat2, lon2] = end;

    const mLat = (lat1 + lat2) / 2;
    const mLon = (lon1 + lon2) / 2;

    const dLat = lat2 - lat1;
    const dLon = lon2 - lon1;
    const ctrlLat = mLat - dLon * 0.2;
    const ctrlLon = mLon + dLat * 0.2;

    const curve: [number, number][] = [];
    for (let i = 0; i <= segments; i++) {
        const t = i / segments;
        const u = 1 - t;
        const lat = u * u * lat1 + 2 * u * t * ctrlLat + t * t * lat2;
        const lon = u * u * lon1 + 2 * u * t * ctrlLon + t * t * lon2;
        curve.push([lat, lon]);
    }
    return curve;
};

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