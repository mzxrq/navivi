import { useRef, useEffect } from "react";
import { useWorkspace } from "./useWorkspace";
import { getCurve, OsmNode, getDistanceKm, fillRouteCoordinates } from "../utils/mapUtils";
import bezierSpline from "@turf/bezier-spline";
import { lineString } from "@turf/helpers";

// kill switch fetcher
const fetchWithTimeout = async (
  url: string,
  options: RequestInit = {},
  timeout = 5000,
) => {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);
  try {
    const res = await fetch(url, { ...options, signal: controller.signal });
    clearTimeout(id);
    return res;
  } catch (err: any) {
    clearTimeout(id);
    throw err;
  }
};

const fetchSingleSegment = async (
  index: number,
  wp1: any,
  wp2: any,
  mode: string,
  cacheKey: string,
  apiKey: string,
) => {
  let positions: [number, number][] = [];

  if (mode === "direct") {
    positions = [
      [wp1.lat, wp1.lng],
      [wp2.lat, wp2.lng],
    ];
  } else if (mode === "draw") {
    const customNodes = wp1.customRoute || [];
    positions = [[wp1.lat, wp1.lng], ...customNodes, [wp2.lat, wp2.lng]];
  } else if (mode === "curve") {
    // curve
    positions = getCurve([wp1.lat, wp1.lng], [wp2.lat, wp2.lng]);
  } else if (mode === "ferry") {
    // ferry (very fallback: deprecatedd)
    try {
      const minLat = Math.min(wp1.lat, wp2.lat) - 0.05;
      const maxLat = Math.max(wp1.lat, wp2.lat) + 0.05;
      const minLng = Math.min(wp1.lng, wp2.lng) - 0.05;
      const maxLng = Math.max(wp1.lng, wp2.lng) + 0.05;

      const overpassQuery = `[out:json];way["route"="ferry"](${minLat},${minLng},${maxLat},${maxLng});out geom;`;
      const overpassUrl = `https://overpass-api.de/api/interpreter?data=${encodeURIComponent(overpassQuery)}`;

      // 🛠️ 2. Upgraded to use our kill-switch!
      const res = await fetchWithTimeout(overpassUrl, {
        headers: { "User-Agent": "NaviviApp/1.0" },
      });
      if (!res.ok)
        throw new Error(`Overpass API failed with HTTP ${res.status}`);

      const rawText = await res.text();
      if (rawText.trim().startsWith("<"))
        throw new Error("Overpass returned XML.");

      const data = JSON.parse(rawText);

      if (data.elements && data.elements.length > 0) {
        let bestWay: OsmNode[] | null = null;
        let bestScore = Infinity;

        data.elements.forEach((element: any) => {
          if (element.type === "way" && element.geometry) {
            const geom = element.geometry as OsmNode[];
            const distToStart = Math.min(
              ...geom.map((pt) =>
                getDistanceKm(wp1.lat, wp1.lng, pt.lat, pt.lon),
              ),
            );
            const distToEnd = Math.min(
              ...geom.map((pt) =>
                getDistanceKm(wp2.lat, wp2.lng, pt.lat, pt.lon),
              ),
            );
            const score = distToStart + distToEnd;

            if (score < bestScore) {
              bestScore = score;
              bestWay = geom;
            }
          }
        });

        if (bestWay !== null && bestScore < 15) {
          const validWay: OsmNode[] = bestWay;
          const startDist = getDistanceKm(
            wp1.lat,
            wp1.lng,
            validWay[0].lat,
            validWay[0].lon,
          ); // Fixed typo here earlier!
          const endDist = getDistanceKm(
            wp1.lat,
            wp1.lng,
            validWay[validWay.length - 1].lat,
            validWay[validWay.length - 1].lon,
          );

          let formattedFerry: [number, number][] = validWay.map((pt) => [
            pt.lat,
            pt.lon,
          ]);
          if (endDist < startDist) formattedFerry.reverse();

          positions = [
            [wp1.lat, wp1.lng],
            ...formattedFerry,
            [wp2.lat, wp2.lng],
          ];
        } else {
          throw new Error("No suitable ferry connecting these points.");
        }
      } else {
        throw new Error("No ferry routes found in this bounding box.");
      }
    } catch (err) {
      console.warn("[Ferry] Failed, using direct mode:", err);
      positions = [
        [wp1.lat, wp1.lng],
        [wp2.lat, wp2.lng],
      ];
    }
  } else if (mode === "walking") {
    // walking + ferry
    try {
      if (!apiKey) throw new Error("missing_api_key");
      const url = `https://api.openrouteservice.org/v2/directions/foot-hiking?api_key=${apiKey}&start=${wp1.lng},${wp1.lat}&end=${wp2.lng},${wp2.lat}`;

      const response = await fetchWithTimeout(url);
      if (!response.ok) throw new Error(`HTTP_${response.status}`);

      const data = await response.json();
      if (data.features && data.features.length > 0) {
        positions = data.features[0].geometry.coordinates.map(
          (coord: [number, number]) => [coord[1], coord[0]],
        );
      } else {
        throw new Error("no_route");
      }
    } catch (error) {
      console.warn("[ORS Walking] Failed, falling back to OSRM foot:", error);
      try {
        const osrmUrl = `https://router.project-osrm.org/route/v1/foot/${wp1.lng},${wp1.lat};${wp2.lng},${wp2.lat}?overview=full&geometries=geojson`;

        const osrmRes = await fetchWithTimeout(osrmUrl);
        const osrmData = await osrmRes.json();

        if (osrmData.routes && osrmData.routes.length > 0) {
          positions = osrmData.routes[0].geometry.coordinates.map(
            (coord: [number, number]) => [coord[1], coord[0]],
          );
        } else {
          positions = [
            [wp1.lat, wp1.lng],
            [wp2.lat, wp2.lng],
          ];
        }
      } catch {
        positions = [
          [wp1.lat, wp1.lng],
          [wp2.lat, wp2.lng],
        ];
      }
    }
  } else {
    // driving
    try {
      const url = `https://router.project-osrm.org/route/v1/driving/${wp1.lng},${wp1.lat};${wp2.lng},${wp2.lat}?overview=full&geometries=geojson`;
      const response = await fetchWithTimeout(url);
      const data = await response.json();

      if (data.routes && data.routes.length > 0) {
        positions = data.routes[0].geometry.coordinates.map(
          (coord: [number, number]) => [coord[1], coord[0]],
        );
      } else {
        positions = [
          [wp1.lat, wp1.lng],
          [wp2.lat, wp2.lng],
        ];
      }
    } catch (error) {
      positions = [
        [wp1.lat, wp1.lng],
        [wp2.lat, wp2.lng],
      ];
    }
  }

  return { index, positions, mode, cacheKey };
};

export function useMapRouting() {
  const {
    waypoints,
    setRouteSegments,
    settings,
    routingCache,
    setRoutingCache,
  } = useWorkspace();
  const latestSegmentsRef = useRef<
    { positions: [number, number][]; mode: string }[]
  >([]);

  useEffect(() => {
    if (waypoints.length < 2) {
      setRouteSegments([]);
      return;
    }

    const apiKey = settings?.ors_api_key || import.meta.env.VITE_ORS_API_KEY;
    const newSegments: { positions: [number, number][]; mode: string }[] = [];
    const fetchQueue: {
      index: number;
      wp1: any;
      wp2: any;
      mode: string;
      cacheKey: string;
    }[] = [];

    for (let i = 0; i < waypoints.length - 1; i++) {
      const wp1 = waypoints[i];
      const wp2 = waypoints[i + 1];
      const mode = wp1.routeMode || "walking";
      const customHash =
        mode === "draw" ? JSON.stringify(wp1.customRoute || []) : "";
      const cacheKey = `${wp1.lat.toFixed(5)},${wp1.lng.toFixed(5)}|${wp2.lat.toFixed(5)},${wp2.lng.toFixed(5)}|${mode}|${customHash}`;

      // straight line but mode is neither Direct or Draw, ignore cache
      const cachedData = routingCache[cacheKey];
      const isFailedCache =
        cachedData &&
        cachedData.length === 2 &&
        mode !== "direct" &&
        mode !== "draw";

      if (cachedData && !isFailedCache) {
        newSegments[i] = { positions: cachedData, mode };
      } else if (mode === "draw" || mode === "direct") {
        let rawPoints: [number, number][] = [
          [wp1.lat, wp1.lng],
          [wp2.lat, wp2.lng],
        ];

        if (mode === "draw") {
          const customNodes = wp1.customRoute || [];
          rawPoints = [[wp1.lat, wp1.lng], ...customNodes, [wp2.lat, wp2.lng]];
        }
        let dense: [number, number][] = [];

        if (
          mode === "draw" &&
          wp1.drawStyle === "spline" &&
          rawPoints.length >= 3
        ) {
          const turfLine = lineString(rawPoints.map((p) => [p[1], p[0]]));
          const curvedDraw = bezierSpline(turfLine, {
            resolution: 10000,
            sharpness: 0.85,
          });
          dense = curvedDraw.geometry.coordinates.map((c: any) => [c[1], c[0]]);
        } else {
          dense = fillRouteCoordinates(rawPoints, 0.01);
        }
        newSegments[i] = { positions: dense, mode };
        setRoutingCache((prev) => ({ ...prev, [cacheKey]: dense }));
      } else {
        newSegments[i] = {
          positions: [
            [wp1.lat, wp1.lng],
            [wp2.lat, wp2.lng],
          ],
          mode: "calculating",
        };
        fetchQueue.push({ index: i, wp1, wp2, mode, cacheKey });
      }
    }

    latestSegmentsRef.current = [...newSegments];
    setRouteSegments([...newSegments]);

    if (fetchQueue.length === 0) return;

    let isCancelled = false;
    // queue data fetch
    const debounce = setTimeout(async () => {
      for (let i = 0; i < fetchQueue.length; i++) {
        if (isCancelled) break;
        const item = fetchQueue[i];
        const res = await fetchSingleSegment(
          item.index,
          item.wp1,
          item.wp2,
          item.mode,
          item.cacheKey,
          apiKey,
        );
        if (isCancelled) break;
        latestSegmentsRef.current[res.index] = {
          positions: res.positions,
          mode: res.mode,
        };
        setRouteSegments([...latestSegmentsRef.current]);

        if (
          res.positions.length > 2 ||
          res.mode === "direct" ||
          res.mode === "draw"
        ) {
          setRoutingCache((prev) => ({
            ...prev,
            [res.cacheKey]: res.positions,
          }));
        }

        if (i < fetchQueue.length - 1) {
          await new Promise((resolve) => setTimeout(resolve, 400));
        }
      }
    }, 800);

    return () => {
      isCancelled: true;
      clearTimeout(debounce);
    };
  }, [
    waypoints,
    setRouteSegments,
    routingCache,
    setRoutingCache,
    settings?.ors_api_key,
  ]);
}
