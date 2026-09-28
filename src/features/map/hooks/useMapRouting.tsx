import { useRef, useEffect } from "react";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { getCurve, fillRouteCoordinates } from "../../../utils/mapUtils";
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

const fetchPairSegment = async (
  lat1: number,
  lng1: number,
  lat2: number,
  lng2: number,
  mode: string,
  apiKey: string,
) => {
  let positions: [number, number][] = [];

  if (mode === "curve") {
    positions = getCurve([lat1, lng1], [lat2, lng2]);
  } else if (mode === "walking" || mode === "ferry") {
    try {
      if (!apiKey) throw new Error("missing_api_key");
      const url = `https://api.openrouteservice.org/v2/directions/foot-hiking?api_key=${apiKey}&start=${lng1},${lat1}&end=${lng2},${lat2}`;
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
      console.warn("[ORS Walk] Failed, falling back to OSRM foot:", error);
      try {
        const osrmUrl = `https://router.project-osrm.org/route/v1/foot/${lng1},${lat1};${lng2},${lat2}?overview=full&geometries=geojson`;
        const osrmRes = await fetchWithTimeout(osrmUrl);
        const osrmData = await osrmRes.json();
        if (osrmData.routes && osrmData.routes.length > 0) {
          positions = osrmData.routes[0].geometry.coordinates.map(
            (coord: [number, number]) => [coord[1], coord[0]],
          );
        } else {
          positions = [[lat1, lng1], [lat2, lng2]];
        }
      } catch {
        positions = [[lat1, lng1], [lat2, lng2]];
      }
    }
  } else {
    // driving
    try {
      const url = `https://router.project-osrm.org/route/v1/driving/${lng1},${lat1};${lng2},${lat2}?overview=full&geometries=geojson`;
      const response = await fetchWithTimeout(url);
      const data = await response.json();
      if (data.routes && data.routes.length > 0) {
        positions = data.routes[0].geometry.coordinates.map(
          (coord: [number, number]) => [coord[1], coord[0]],
        );
      } else {
        positions = [[lat1, lng1], [lat2, lng2]];
      }
    } catch (error) {
      positions = [[lat1, lng1], [lat2, lng2]];
    }
  }

  return positions;
};

const fetchSegmentWithVia = async (
  wp1: any,
  wp2: any,
  mode: string,
  apiKey: string,
) => {
  const points: [number, number][] = [
    [wp1.lat, wp1.lng],
    ...(wp1.viaPoints || []),
    [wp2.lat, wp2.lng],
  ];

  let fullPositions: [number, number][] = [];

  for (let i = 0; i < points.length - 1; i++) {
    const p1 = points[i];
    const p2 = points[i + 1];
    const segmentPositions = await fetchPairSegment(
      p1[0], p1[1],
      p2[0], p2[1],
      mode,
      apiKey
    );
    
    // Stitch segments, avoiding duplicate end-start coordinates
    if (i === 0) {
      fullPositions = segmentPositions;
    } else {
      if (segmentPositions.length > 0 && fullPositions.length > 0) {
        const lastFull = fullPositions[fullPositions.length - 1];
        const firstSeg = segmentPositions[0];
        if (lastFull[0] === firstSeg[0] && lastFull[1] === firstSeg[1]) {
          fullPositions = [...fullPositions, ...segmentPositions.slice(1)];
        } else {
          fullPositions = [...fullPositions, ...segmentPositions];
        }
      } else {
        fullPositions = [...fullPositions, ...segmentPositions];
      }
    }
  }

  return fullPositions;
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
  } else {
    positions = await fetchSegmentWithVia(wp1, wp2, mode, apiKey);
  }

  return { index, positions, mode, cacheKey };
};

export function useMapRouting() {
  const {
    waypoints,
    setRouteSegments,
    routingCache,
    setRoutingCache,
    settings,
  } = useWorkspace();
  const latestSegmentsRef = useRef<
    { positions: [number, number][]; mode: string }[]
  >([]);

  useEffect(() => {
    const routedWaypoints = waypoints.filter(
      (wp) => !wp.isStopBy || wp.connectToRoute,
    );

    if (routedWaypoints.length < 2) {
      setRouteSegments([]);
      return;
    }

    const apiKey = settings.ors_api_key || import.meta.env.VITE_ORS_API_KEY;
    const newSegments: { positions: [number, number][]; mode: string }[] = [];
    const fetchQueue: {
      index: number;
      wp1: any;
      wp2: any;
      mode: string;
      cacheKey: string;
    }[] = [];

    for (let i = 0; i < routedWaypoints.length - 1; i++) {
      const wp1 = routedWaypoints[i];
      const wp2 = routedWaypoints[i + 1];
      const mode = wp1.routeMode || "driving";
      const customHash =
        mode === "draw" ? JSON.stringify(wp1.customRoute || []) : "";
      const viaHash = 
        wp1.viaPoints ? JSON.stringify(wp1.viaPoints) : "";
        
      const cacheKey = `${wp1.lat.toFixed(5)},${wp1.lng.toFixed(5)}|${wp2.lat.toFixed(5)},${wp2.lng.toFixed(5)}|${mode}|${customHash}|${viaHash}`;

      // straight line but mode is neither Direct or Draw, ignore cache
      const cachedData = routingCache[cacheKey];
      const isFailedCache =
        cachedData &&
        cachedData.length === 2 &&
        mode !== "direct" &&
        mode !== "draw" && 
        !(wp1.viaPoints && wp1.viaPoints.length > 0);

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
      isCancelled = true;
      clearTimeout(debounce);
    };
  }, [waypoints, setRouteSegments, routingCache, setRoutingCache, settings.ors_api_key]);
}
