import { useEffect } from "react";
import { useWorkspace } from "./useWorkspace";
import { useUI } from "./useUI";
import { getCurve } from "../utils/mapUtils";
import { apiEndpoints } from "../config/constants";

export function useMapRouting() {
  const {
    waypoints,
    setRouteSegments,
    settings,
    routingCache,
    setRoutingCache,
  } = useWorkspace();
  const { showToast } = useUI();

useEffect(() => {
  if (waypoints.length < 2) {
    setRouteSegments([]);
    return;
  }

  const fetchAllSegments = async () => {
    const newSegments: { positions: [number, number][]; mode: string }[] = [];
    const newCacheEntries: Record<string, [number, number][]> = {};
    const apiKey = settings.ors_api_key || import.meta.env.VITE_ORS_API_KEY;
    let warnedApiLimit = false;

    for (let i = 0; i < waypoints.length - 1; i++) {
      const wp1 = waypoints[i];
      const wp2 = waypoints[i + 1];
      const mode = wp1.routeMode || "driving";

      const cacheKey = `${wp1.lat.toFixed(5)},${wp1.lng.toFixed(5)}|${wp2.lat.toFixed(5)},${wp2.lng.toFixed(5)}|${mode}`;

      if (routingCache[cacheKey]) {
        newSegments.push({ positions: routingCache[cacheKey], mode });
        continue;
      }

      let positions: [number, number][] = [];

      if (mode === "direct") {
        positions = [
          [wp1.lat, wp1.lng],
          [wp2.lat, wp2.lng],
        ];
      } else if (mode === "curve") {
        positions = getCurve([wp1.lat, wp1.lng], [wp2.lat, wp2.lng]);
      } else if (mode === "ferry") {
        // 1. FERRY MODE: Fetch raw OSM Ferry geometry from Overpass API
        try {
          const minLat = Math.min(wp1.lat, wp2.lat) - 0.02;
          const maxLat = Math.max(wp1.lat, wp2.lat) + 0.02;
          const minLng = Math.min(wp1.lng, wp2.lng) - 0.02;
          const maxLng = Math.max(wp1.lng, wp2.lng) + 0.02;

          const overpassQuery = `[out:json];way["route"="ferry"](${minLat},${minLng},${maxLat},${maxLng});out geom;`;
          const overpassUrl = `https://overpass-api.de/api/interpreter?data=${encodeURIComponent(overpassQuery)}`;

          const res = await fetch(overpassUrl, {
            headers: { "User-Agent": "NaviviApp/1.0" },
          });
          const data = await res.json();

          if (data.elements && data.elements.length > 0) {
            const ferryCoords: [number, number][] = [];
            data.elements.forEach((element: any) => {
              if (element.geometry) {
                element.geometry.forEach((pt: { lat: number; lon: number }) => {
                  ferryCoords.push([pt.lat, pt.lon]);
                });
              }
            });
            positions = [[wp1.lat, wp1.lng], ...ferryCoords, [wp2.lat, wp2.lng]];
          } else {
            throw new Error("No ferry geometry");
          }
        } catch (err) {
          console.warn("[Ferry] Overpass fetch failed, using straight line:", err);
          positions = [[wp1.lat, wp1.lng], [wp2.lat, wp2.lng]];
        }
      } else if (mode === "walking") {
        // 2. WALKING MODE: High-accuracy footpaths via OpenRouteService (foot-hiking)
        try {
          if (!apiKey) throw new Error("missing_api_key");

          const url = `${apiEndpoints.orsBase}/foot-hiking?api_key=${apiKey}&start=${wp1.lng},${wp1.lat}&end=${wp2.lng},${wp2.lat}`;
          const response = await fetch(url);

          if (!response.ok) throw new Error(`HTTP_${response.status}`);

          const data = await response.json();
          if (data.features && data.features.length > 0) {
            positions = data.features[0].geometry.coordinates.map(
              (coord: [number, number]) => [coord[1], coord[0]]
            );
          } else {
            throw new Error("no_route");
          }
        } catch (error) {
          console.warn("[ORS Walking] Failed, falling back to OSRM foot:", error);
          if (!warnedApiLimit && String(error).includes("missing_api_key")) {
            showToast("Missing ORS API Key for walking route. Using standard foot routing.", "warning");
            warnedApiLimit = true;
          }

          // Fallback to OSRM foot profile if ORS key is missing/limited
          try {
            const osrmUrl = `https://router.project-osrm.org/route/v1/foot/${wp1.lng},${wp1.lat};${wp2.lng},${wp2.lat}?overview=full&geometries=geojson`;
            const osrmRes = await fetch(osrmUrl);
            const osrmData = await osrmRes.json();
            if (osrmData.routes && osrmData.routes.length > 0) {
              positions = osrmData.routes[0].geometry.coordinates.map(
                (coord: [number, number]) => [coord[1], coord[0]]
              );
            } else {
              positions = [[wp1.lat, wp1.lng], [wp2.lat, wp2.lng]];
            }
          } catch {
            positions = [[wp1.lat, wp1.lng], [wp2.lat, wp2.lng]];
          }
        }
      } else {
        // 3. DRIVING MODE: Fast, keyless routing via OSRM
        try {
          const url = `https://router.project-osrm.org/route/v1/driving/${wp1.lng},${wp1.lat};${wp2.lng},${wp2.lat}?overview=full&geometries=geojson`;
          const response = await fetch(url);
          const data = await response.json();

          if (data.routes && data.routes.length > 0) {
            positions = data.routes[0].geometry.coordinates.map(
              (coord: [number, number]) => [coord[1], coord[0]]
            );
          } else {
            positions = [[wp1.lat, wp1.lng], [wp2.lat, wp2.lng]];
          }
        } catch (error) {
          positions = [[wp1.lat, wp1.lng], [wp2.lat, wp2.lng]];
        }
      }

      newCacheEntries[cacheKey] = positions;
      newSegments.push({ positions, mode });
    }

    setRouteSegments(newSegments);
    if (Object.keys(newCacheEntries).length > 0) {
      setRoutingCache((prev) => ({ ...prev, ...newCacheEntries }));
    }
  };

  fetchAllSegments();
}, [waypoints, setRouteSegments, showToast, routingCache, setRoutingCache, settings.ors_api_key]);
}
