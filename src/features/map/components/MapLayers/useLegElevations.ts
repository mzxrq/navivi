import { useEffect, useMemo, useRef, useState } from "react";
import type { RefObject } from "react";
import type { MapRef } from "react-map-gl/mapbox";
import { useWorkspace } from "../../../../hooks/useWorkspace";
import { elevationAlongPath, recordedLegElevation, sampleIndexes, type LegElevation } from "../../../../utils/elevation";
import type { LatLon } from "../../../../utils/gpxTrack";

export interface LegElevationState {
  legs: LegElevation[];
  /** Legs that are drawn on the map but have no elevation to colour them by. */
  missing: number;
  /** Terrain lookup is what the missing legs need, and it is switched off. */
  needsTerrain: boolean;
}

const keyOf = (p: number[]) => `${p[0].toFixed(5)},${p[1].toFixed(5)}`;

/** Elevation of every route leg: recorded with the GPX when there is some, otherwise read from the map's
 *  3D terrain (only while `sampleTerrain` is true, which needs 3D terrain on and the heatmap wanted). */
export function useLegElevations(mapRef: RefObject<MapRef | null>, is3D: boolean, sampleTerrain: boolean): LegElevationState {
  const { routeSegments, waypoints } = useWorkspace();
  const [tick, setTick] = useState(0);
  const terrain = useRef(new Map<string, number>());

  const base = useMemo(() => {
    const routed = waypoints.filter((wp) => !wp.isStopBy || wp.connectToRoute);
    return routeSegments.map((seg, i) => {
      const positions = seg.positions as LatLon[];
      const from = routed[i];
      const to = routed[i + 1];
      const recorded =
        from && to && seg.mode === "draw" ? recordedLegElevation(positions, from, to, from.customRoute, from.customRouteEle) : null;
      return { positions, mode: seg.mode, recorded };
    });
  }, [routeSegments, waypoints]);

  const wantTerrain = sampleTerrain && is3D;
  useEffect(() => {
    if (!wantTerrain) return;
    const map = mapRef.current?.getMap();
    if (!map) return;
    const sample = () => {
      let added = false;
      for (const leg of base) {
        if (leg.recorded || leg.mode === "calculating" || leg.positions.length < 2) continue;
        for (const i of sampleIndexes(leg.positions)) {
          const k = keyOf(leg.positions[i]);
          if (terrain.current.has(k)) continue;
          // exaggerated: false, or the 1.5x terrain exaggeration of the 3D view would inflate every slope.
          const v = map.queryTerrainElevation({ lat: leg.positions[i][0], lng: leg.positions[i][1] }, { exaggerated: false });
          if (typeof v === "number" && Number.isFinite(v)) {
            terrain.current.set(k, v);
            added = true;
          }
        }
      }
      if (added) setTick((t) => t + 1);
    };
    sample();
    map.on("idle", sample);
    return () => {
      map.off("idle", sample);
    };
  }, [wantTerrain, base, mapRef]);

  return useMemo(() => {
    let missing = 0;
    const legs = base.map((leg): LegElevation => {
      if (leg.recorded) return { positions: leg.positions, ele: leg.recorded, source: "recorded" };
      if (wantTerrain && leg.positions.length >= 2 && leg.mode !== "calculating") {
        const idx = sampleIndexes(leg.positions);
        const ele = idx.map((i) => terrain.current.get(keyOf(leg.positions[i])));
        if (ele.every((v) => v !== undefined)) {
          const full = elevationAlongPath(leg.positions, idx.map((i) => leg.positions[i]), ele as number[]);
          if (full) return { positions: leg.positions, ele: full, source: "terrain" };
        }
      }
      if (leg.mode !== "calculating" && leg.positions.length >= 2) missing++;
      return { positions: leg.positions, ele: null, source: null };
    });
    return { legs, missing, needsTerrain: missing > 0 && !is3D };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base, wantTerrain, is3D, tick]);
}
