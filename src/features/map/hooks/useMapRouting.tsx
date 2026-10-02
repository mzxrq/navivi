import { useRef, useEffect } from "react";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { getCurve, fillRouteCoordinates } from "../../../utils/mapUtils";
import bezierSpline from "@turf/bezier-spline";
import { lineString } from "@turf/helpers";
import { routeCacheKey } from "../../../utils/routeCacheKey";
import { closeGaps } from "../../../utils/gsiPaths";

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

  const points: [number, number][] = [
    [wp1.lat, wp1.lng],
    ...(wp1.viaPoints || []),
    [wp2.lat, wp2.lng],
  ];

  if (mode === "direct") {
    positions = points;
  } else if (mode === "draw") {
    const customNodes = wp1.customRoute || [];
    positions = [[wp1.lat, wp1.lng], ...customNodes, [wp2.lat, wp2.lng]];
  } else if (mode === "curve") {
    // curve only supports 2 points, just use start and end
    positions = getCurve([wp1.lat, wp1.lng], [wp2.lat, wp2.lng]);
  } else if (mode === "walking" || mode === "ferry") {
    try {
      if (!apiKey) throw new Error("missing_api_key");
      // Use ORS POST endpoint which supports multiple coordinates
      const url = `https://api.openrouteservice.org/v2/directions/foot-hiking/geojson`;
      const response = await fetchWithTimeout(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: apiKey,
        },
        body: JSON.stringify({
          coordinates: points.map((p) => [p[1], p[0]]), // [lng, lat]
        }),
      });

      if (!response.ok) throw new Error(`HTTP_${response.status}`);
      const data = await response.json();

      if (data.routes && data.routes.length > 0) {
        positions = data.routes[0].geometry.coordinates.map(
          (coord: [number, number]) => [coord[1], coord[0]],
        );
      } else if (data.features && data.features.length > 0) {
        positions = data.features[0].geometry.coordinates.map(
          (coord: [number, number]) => [coord[1], coord[0]],
        );
      } else {
        throw new Error("no_route");
      }
    } catch (error) {
      console.warn("[ORS Walk] Failed, falling back to OSRM foot:", error);
      try {
        const coordsStr = points.map((p) => `${p[1]},${p[0]}`).join(";");
        const osrmUrl = `https://router.project-osrm.org/route/v1/foot/${coordsStr}?overview=full&geometries=geojson`;
        const osrmRes = await fetchWithTimeout(osrmUrl);
        const osrmData = await osrmRes.json();

        if (osrmData.routes && osrmData.routes.length > 0) {
          positions = osrmData.routes[0].geometry.coordinates.map(
            (coord: [number, number]) => [coord[1], coord[0]],
          );
        } else {
          positions = points;
        }
      } catch {
        positions = points;
      }
    }
    if (mode === "walking") {
      positions = await closeGaps(
        positions,
        [wp1.lat, wp1.lng],
        [wp2.lat, wp2.lng],
      );
    }
  } else {
    // driving
    try {
      const coordsStr = points.map((p) => `${p[1]},${p[0]}`).join(";");
      const url = `https://router.project-osrm.org/route/v1/driving/${coordsStr}?overview=full&geometries=geojson`;
      const response = await fetchWithTimeout(url);
      const data = await response.json();

      if (data.routes && data.routes.length > 0) {
        positions = data.routes[0].geometry.coordinates.map(
          (coord: [number, number]) => [coord[1], coord[0]],
        );
      } else {
        positions = points;
      }
    } catch (error) {
      positions = points;
    }
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
      const cacheKey = routeCacheKey(wp1, wp2);

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
        } else if (mode === "direct") {
          rawPoints = [
            [wp1.lat, wp1.lng],
            ...(wp1.viaPoints || []),
            [wp2.lat, wp2.lng],
          ];
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
            ...(wp1.viaPoints || []),
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
          res.positions.length > (item.wp1.viaPoints?.length || 0) + 2 ||
          res.mode === "direct" ||
          res.mode === "draw"
        ) {
          setRoutingCache((prev) => ({
            ...prev,
            [res.cacheKey]: res.positions,
          }));
        }

        if (i < fetchQueue.length - 1) {
          await new Promise((resolve) => setTimeout(resolve, 800));
        }
      }
    }, 800);

    return () => {
      isCancelled = true;
      clearTimeout(debounce);
    };
  }, [
    waypoints,
    setRouteSegments,
    routingCache,
    setRoutingCache,
    settings.ors_api_key,
  ]);
}
