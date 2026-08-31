import { useEffect } from "react";
import { useWorkspace } from "./useWorkspace";
import { getCurve, OsmNode, getDistanceKm } from "../utils/mapUtils";

const fetchSingleSegment = async (
  index: number, wp1: any, wp2: any, mode: string, cacheKey: string, apiKey: string
) => {
  let positions: [number, number][] = [];

  if (mode === "direct") {
    positions = [
      [wp1.lat, wp1.lng],
      [wp2.lat, wp2.lng],
    ];
  } else if (mode === "curve") {
    positions = getCurve([wp1.lat, wp1.lng], [wp2.lat, wp2.lng]);
  } else if (mode === "ferry") {
    try {
      const minLat = Math.min(wp1.lat, wp2.lat) - 0.05;
      const maxLat = Math.max(wp1.lat, wp2.lat) + 0.05;
      const minLng = Math.min(wp1.lng, wp2.lng) - 0.05;
      const maxLng = Math.max(wp1.lng, wp2.lng) + 0.05;

      const overpassQuery =
      `[out:json];way["route"="ferry"](${minLat},${minLng},${maxLat},${maxLng});out geom;`;
      const overpassUrl =
      `https://overpass-api.de/api/interpreter?data=${encodeURIComponent(overpassQuery)}`;

      const res = await fetch(overpassUrl, {
        headers: { "User-Agent": "NaviviApp/1.0" },
      });
      const data = await res.json();

      if (data.elements && data.elements.length > 0) {
        let bestWay: OsmNode[] | null = null;
        let bestScore = Infinity;

        data.elements.forEach((element: any) => {
          if (element.type === "way" && element.geometry) {
            const geom = element.geometry as OsmNode[];
            const distToStart = Math.min(...geom.map((pt) => getDistanceKm(wp1.lat, wp1.lng, pt.lat, pt.lon)));
            const distToEnd = Math.min(...geom.map((pt) => getDistanceKm(wp2.lat, wp2.lng, pt.lat, pt.lon)));
            const score = distToStart + distToEnd;

            if (score < bestScore) {
              bestScore = score;
              bestWay = geom;
            }
          }
        });

        if (bestWay !== null && bestScore < 15) {
          const validWay: OsmNode[] = bestWay;
          const startDist = getDistanceKm(wp1.lat, wp1.lngn, validWay[0].lat, validWay[0].lon);
          const endDist = getDistanceKm(wp1.lat, wp1.lng, validWay[validWay.length - 1].lat, validWay[validWay.length - 1].lon);

          let formattedFerry: [number, number][] = validWay.map((pt) => [pt.lat, pt.lon]);

          if (endDist < startDist) {
            formattedFerry.reverse();
          }

          positions = [[wp1.lat, wp1.lng], ...formattedFerry, [wp2.lat, wp2.lng]];
        } else {
          throw new Error("No suitable ferry connecting these points.");
        }
      } 

      } catch (err) {
        console.warn("[Ferry] Overpass fetch failed, using direct mode:", err);
        positions = [[wp1.lat, wp1.lng], [wp2.lat, wp2.lng]];
      }
    } else if (mode === "walking") {
      // walking 
      try {
        if (!apiKey) throw new Error("missing_api_key");

        const url = `https://api.openrouteservice.org/v2/directions/foot-hiking?api_key=${apiKey}&start=${wp1.lng},${wp1.lat}&end=${wp2.lng},${wp2.lat}`;
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

        try {
          const osrmUrl = `https://router.project-osrm.org/route/v1/foot${wp1.lng},${wp1.lat};${wp2.lng},${wp2.lat}?overview=full&geometries=geojson`;
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
  }  else {
    // driving
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

  return { index, positions, mode, cacheKey };
}

export function useMapRouting() {
  const {
    waypoints,
    setRouteSegments,
    settings,
    routingCache,
    setRoutingCache,
  } = useWorkspace();
  

useEffect(() => {
  if (waypoints.length < 2) {
    setRouteSegments([]);
    return;
  }

  const fetchAllSegments = async () => {
    if (waypoints.length < 2) {
      setRouteSegments([]);
      return;
    }

    const apiKey = settings?.ors_api_key || import.meta.env.VITE_ORS_API_KEY;
    const newSegments: { positions: [number, number][]; mode: string }[] = [];
    const promises: Promise<{ index: number; positions: [number, number][]; mode: string; cacheKey: string }>[] = [];

    // s1 loop through and instantly draw cached or ghost line
    for (let i = 0; i < waypoints.length - 1; i++) {
      const wp1 = waypoints[i];
      const wp2 = waypoints[i + 1];
      const mode = wp1.routeMode || "walking";
      const cacheKey = `${wp1.lat.toFixed(5)},${wp1.lng.toFixed(5)}|${wp2.lat.toFixed(5)},${wp2.lng.toFixed(5)}|${mode}`;

      if (routingCache[cacheKey]) {
        newSegments[i] = { positions: routingCache[cacheKey], mode };
      } else {
        newSegments[i] = { positions: [[wp1.lat, wp1.lng], [wp2.lat, wp2.lng]], mode: "calculating" };
        promises.push(fetchSingleSegment(i, wp1, wp2, mode, cacheKey, apiKey));
      }
    }
    // push ui update
    setRouteSegments([...newSegments]);

    // s2 resolve missing routes at the same time
    if (promises.length > 0) {
      const results = await Promise.all(promises);
      const newCacheEntries: Record<string, [number, number][]> = {};

      results.forEach((res) => {
        newSegments[res.index] = { positions: res.positions, mode: res.mode };
        newCacheEntries[res.cacheKey] = res.positions;
      });

      setRouteSegments([...newSegments]);
      setRoutingCache((prev) => ({ ...prev, ...newCacheEntries }));
    }
  };

  fetchAllSegments();
}, [waypoints, setRouteSegments, routingCache, setRoutingCache, settings.ors_api_key]);
}
