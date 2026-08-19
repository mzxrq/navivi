import { useEffect, useRef } from "react";
import { useWorkspace } from "./useWorkspace";
import { useUI } from "./useUI";
import { getCurve } from "../utils/mapUtils";
import { apiEndpoints } from "../config/constants";

export function useMapRouting() {
  const { waypoints, setRouteSegments, settings } = useWorkspace();
  const { showToast } = useUI();
  
  const segmentCache = useRef(
    new Map<string, { positions: [number, number][]; mode: string }>(),
  );

  useEffect(() => {
    if (waypoints.length < 2) {
      setRouteSegments([]);
      return;
    }

    const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
    
    const fetchAllSegments = async () => {
      const newSegments: { positions: [number, number][]; mode: string }[] = [];

      const apiKey = settings.ors_api_key || import.meta.env.VITE_ORS_API_KEY;

      let warnedApiLimit = false;
      let warnedNoRoute = false;

      for (let i = 0; i < waypoints.length - 1; i++) {
        const wp1 = waypoints[i];
        const wp2 = waypoints[i + 1];
        const mode = wp1.routeMode || "driving";

        const cacheKey = `${wp1.lat},${wp1.lng}|${wp2.lat},${wp2.lng}|${mode}`;
        
        if (segmentCache.current.has(cacheKey)) {
          newSegments.push(segmentCache.current.get(cacheKey)!);
          continue;
        }

        if (mode === "direct") {
          const seg = {
            positions: [[wp1.lat, wp1.lng], [wp2.lat, wp2.lng]] as [number, number][],
            mode: "direct",
          };
          segmentCache.current.set(cacheKey, seg);
          newSegments.push(seg);
        } else if (mode === "curve") {
          const curvePoints = getCurve([wp1.lat, wp1.lng], [wp2.lat, wp2.lng]);
          const seg = { positions: curvePoints, mode: "curve" };
          segmentCache.current.set(cacheKey, seg);
          newSegments.push(seg);
        } else {
          const profile = mode === "walking" ? "foot-hiking" : "driving-car";

          try {
            if (!apiKey) throw new Error("missing_api_key");

            await sleep(1000); 

            const url = `${apiEndpoints.orsBase}/${profile}?api_key=${apiKey}&start=${wp1.lng},${wp1.lat}&end=${wp2.lng},${wp2.lat}`;
            const response = await fetch(url);

            if (!response.ok) {
              if (response.status === 404) throw new Error("no_route");
              if (response.status === 429 || response.status === 403) throw new Error("quota_limit");
              throw new Error(`HTTP_${response.status}`);
            }

            const data = await response.json();
            if (data.features && data.features.length > 0) {
              const coords = data.features[0].geometry.coordinates.map(
                (coord: [number, number]) => [coord[1], coord[0]],
              );

              const seg = { positions: coords, mode: mode };
              segmentCache.current.set(cacheKey, seg);
              newSegments.push(seg);
              continue;
            }

            throw new Error("no_route"); 
          } catch (error) {
            console.warn(`[ORS] Failed for segment ${i + 1}. Falling back to direct line.`, error);

            const errMsg = error instanceof Error ? error.message : String(error);

            if (errMsg.includes("missing_api_key")) {
             if (!warnedApiLimit) {
              showToast("Missing ORS API Key. Please add your API Key in Settings.", "warning");
                warnedApiLimit = true;
             }
            } 
            else if (errMsg.includes("Failed to fetch") || errMsg.includes("quota_limit")) {
             if (!warnedApiLimit) {
              showToast("Routing limit reached or invalid key. Failling back to direct lines.", "error");
              warnedApiLimit = true;
             }  
            } else if (errMsg.includes("NO_ROUTE") || errMsg.includes("HTTP_")) {
              if (!warnedNoRoute) {
                const modeName = mode.charAt(0).toUpperCase() + mode.slice(1);
                showToast(`${modeName} route unavailable for some segments. Using direct lines.`, "info");
                warnedNoRoute = true;
              }
            }
          }

            const fallbackSeg = {
              positions: [[wp1.lat, wp1.lng], [wp2.lat, wp2.lng]] as [number, number][],
              mode: "direct",
            };
            segmentCache.current.set(cacheKey, fallbackSeg);
            newSegments.push(fallbackSeg);
          }
        }
        setRouteSegments(newSegments);
      };  

    fetchAllSegments();
  }, [waypoints, setRouteSegments, showToast, settings.ors_api_key]);
}