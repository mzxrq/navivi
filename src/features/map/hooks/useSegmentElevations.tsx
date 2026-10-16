import { createContext, createElement, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { mapboxTileLoader, segmentElevations } from "../../../utils/terrainElevation";

const keyOf = (seg: { positions: number[][]; mode: string }) => {
  const first = seg.positions[0];
  const last = seg.positions[seg.positions.length - 1];
  return `${seg.mode}|${seg.positions.length}|${first?.join(",")}|${last?.join(",")}`;
};

const Ctx = createContext<(number[] | null | undefined)[]>([]);

/** Elevation of every route segment (index = routeSegments), read from Mapbox terrain tiles, so a routed leg (ORS/OSRM)
 *  has a climb too. It does not need the 3D view. undefined = not looked up yet, null = could not be found (no token,
 *  offline). Same lookup as the GPX save, whose tiles are cached for the session. */
function useLookup(): (number[] | null | undefined)[] {
  const { routeSegments, waypoints, settings } = useWorkspace();
  const token = settings.mapbox_api_key || import.meta.env.VITE_MAPBOX_TOKEN;
  const [found, setFound] = useState<Record<string, number[] | null>>({});
  const keys = useMemo(() => routeSegments.map((s) => (s && s.mode !== "calculating" && s.positions.length > 1 ? keyOf(s) : null)), [routeSegments]);

  useEffect(() => {
    if (!token || keys.every((k) => k === null || k in found)) return;
    let cancelled = false;
    // Wait for the routing to settle: dragging a stop rewrites the segments many times a second.
    const timer = setTimeout(async () => {
      try {
        const result = await segmentElevations(routeSegments, waypoints, mapboxTileLoader(token));
        if (cancelled) return;
        setFound((prev) => {
          const next = { ...prev };
          keys.forEach((k, i) => {
            if (k !== null) next[k] = result[i] ?? null;
          });
          return next;
        });
      } catch {
        if (!cancelled) setFound((prev) => ({ ...prev, ...Object.fromEntries(keys.filter((k): k is string => k !== null).map((k) => [k, null])) }));
      }
    }, 600);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [keys, found, token, routeSegments, waypoints]);

  return useMemo(() => keys.map((k) => (k === null ? undefined : found[k])), [keys, found]);
}

export function SegmentElevationsProvider({ children }: { children: ReactNode }) {
  return createElement(Ctx.Provider, { value: useLookup() }, children);
}

export const useSegmentElevation = (index: number) => useContext(Ctx)[index];
