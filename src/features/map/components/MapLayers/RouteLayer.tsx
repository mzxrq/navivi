import { useMemo } from "react";
import { Source, Layer } from "react-map-gl/mapbox";
import { useWorkspace } from "../../../../hooks/useWorkspace";
import { rgbToHex } from "../../../../components/ui/ColorSwatches";

interface RouteLayerProps {
  uploadedRouteLine: number[][];
  routePoints: number[][];
}

export const EARTH_RADIUS_METERS = 6371000;

export function haversineDistanceMeters(
  coord1: [number, number],
  coord2: [number, number]
): number {
  const [lat1, lon1] = coord1;
  const [lat2, lon2] = coord2;

  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);

  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(toRad(lat1)) *
      Math.cos(toRad(lat2)) *
      Math.sin(dLon / 2) *
      Math.sin(dLon / 2);

  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return EARTH_RADIUS_METERS * c;
}

export function computeSegmentSlope(
  p1: number[],
  p2: number[]
): { slopePercent: number | null; distanceMeters: number; hasElevation: boolean } {
  const coord1: [number, number] = [p1[0], p1[1]];
  const coord2: [number, number] = [p2[0], p2[1]];
  const dist = haversineDistanceMeters(coord1, coord2);

  const hasEle1 = p1.length > 2 && p1[2] !== undefined && Number.isFinite(p1[2]);
  const hasEle2 = p2.length > 2 && p2[2] !== undefined && Number.isFinite(p2[2]);

  if (!hasEle1 || !hasEle2) {
    return { slopePercent: null, distanceMeters: dist, hasElevation: false };
  }

  const deltaEle = p2[2] - p1[2];
  if (dist === 0) {
    return { slopePercent: 0, distanceMeters: 0, hasElevation: true };
  }

  const slopePercent = (deltaEle / dist) * 100;
  return { slopePercent, distanceMeters: dist, hasElevation: true };
}

export function getGradientColor(
  slopePercent: number | null,
  fallbackColor: string = "#3b82f6"
): string {
  if (slopePercent === null || slopePercent === undefined || !Number.isFinite(slopePercent)) {
    return fallbackColor;
  }
  if (slopePercent >= 8) return "#ef4444"; // Steep uphill (warm red)
  if (slopePercent >= 3) return "#f97316"; // Moderate uphill (warm orange)
  if (slopePercent >= -3) return "#10b981"; // Flat / gentle (neutral emerald)
  if (slopePercent > -8) return "#06b6d4"; // Moderate downhill (cool cyan)
  return "#2563eb"; // Steep downhill (cool blue)
}

export function RouteLayer({
  uploadedRouteLine,
  routePoints,
}: RouteLayerProps) {
  const { routeSegments, settings, waypoints } = useWorkspace();

  const hexLineColor =
    "#" +
    (settings?.line_color || [59, 130, 246])
      .map((x: number) => x.toString(16).padStart(2, "0"))
      .join("");
  const lineWidth = settings?.line_thickness || 4;

  const hexBorderColor =
    "#" +
    (settings?.route_line_border_color || [255, 255, 255])
      .map((x: number) => x.toString(16).padStart(2, "0"))
      .join("");
  const borderWidth = settings?.route_line_border_thickness || 0;

  const hasElevationData = useMemo(() => {
    const checkPts = (pts: number[][]) =>
      pts.some(
        (pt) => pt.length > 2 && pt[2] !== undefined && Number.isFinite(pt[2])
      );
    return (
      checkPts(routePoints) ||
      checkPts(uploadedRouteLine) ||
      routeSegments.some((seg) => checkPts(seg.positions))
    );
  }, [routePoints, uploadedRouteLine, routeSegments]);

  const heatmapGeoJSON = useMemo(() => {
    const features: any[] = [];

    const processPoints = (pts: number[][], sourceType: string) => {
      if (pts.length < 2) return;
      for (let i = 0; i < pts.length - 1; i++) {
        const p1 = pts[i];
        const p2 = pts[i + 1];
        const { slopePercent, distanceMeters, hasElevation: segHasEle } =
          computeSegmentSlope(p1, p2);
        const segmentColor =
          segHasEle && slopePercent !== null
            ? getGradientColor(slopePercent, hexLineColor)
            : hexLineColor;

        features.push({
          type: "Feature",
          properties: {
            segmentIndex: i,
            sourceType,
            slope: slopePercent,
            distanceMeters,
            color: segmentColor,
            isHeatmapActive: segHasEle,
          },
          geometry: {
            type: "LineString",
            coordinates: [
              [p1[1], p1[0]],
              [p2[1], p2[0]],
            ],
          },
        });
      }
    };

    if (routePoints.length > 0) {
      processPoints(routePoints, "routePoints");
    }
    if (uploadedRouteLine.length > 0) {
      processPoints(uploadedRouteLine, "uploaded");
    }
    if (routePoints.length === 0 && uploadedRouteLine.length === 0) {
      for (const segment of routeSegments) {
        processPoints(segment.positions, segment.mode || "driving");
      }
    }

    return { type: "FeatureCollection", features };
  }, [routePoints, uploadedRouteLine, routeSegments, hexLineColor]);

  const legColors = waypoints
    .filter((wp) => !wp.isStopBy || wp.connectToRoute)
    .map((wp) => (wp.lineColor ? rgbToHex(wp.lineColor) : ""))
    .join(",");

  const dynamicRouteGeoJSON = useMemo(() => {
    const colors = legColors.split(",");
    const features = routeSegments.map((segment, i) => {
      return {
        type: "Feature",
        properties: {
          mode: segment.mode || "driving",
          color: colors[i] || null,
        },
        geometry: {
          type: "LineString",
          coordinates: segment.positions.map((pos) => [pos[1], pos[0]]),
        },
      };
    });

    return { type: "FeatureCollection", features };
  }, [routeSegments, legColors]);

  const rawRouteGeoJSON = useMemo(() => {
    const features = [];
    if (uploadedRouteLine.length > 0) {
      features.push({
        type: "Feature",
        properties: { type: "uploaded" },
        geometry: {
          type: "LineString",
          coordinates: uploadedRouteLine.map((pos) => [pos[1], pos[0]]),
        },
      });
    }
    if (routePoints.length > 0) {
      features.push({
        type: "Feature",
        properties: { type: "raw" },
        geometry: {
          type: "LineString",
          coordinates: routePoints.map((pos) => [pos[1], pos[0]]),
        },
      });
    }
    return { type: "FeatureCollection", features };
  }, [uploadedRouteLine, routePoints]);

  const isHeatmapActive = Boolean(settings?.show_route_heatmap && hasElevationData);

  return (
    <>
      {isHeatmapActive ? (
        <>
          {/* ======================================= */}
          {/* GRADIENT ROUTE HEATMAP                  */}
          {/* ======================================= */}
          <Source
            id="route-gradient-heatmap-source"
            type="geojson"
            data={heatmapGeoJSON as any}
          >
            {borderWidth > 0 && (
              <Layer
                id="route-gradient-heatmap-border"
                type="line"
                layout={{ "line-join": "round", "line-cap": "round" }}
                paint={{
                  "line-color": hexBorderColor,
                  "line-width": lineWidth + borderWidth * 2,
                  "line-opacity": 1,
                }}
              />
            )}
            <Layer
              id="route-gradient-heatmap"
              type="line"
              layout={{ "line-join": "round", "line-cap": "round" }}
              paint={{
                "line-color": ["get", "color"],
                "line-width": lineWidth,
                "line-opacity": 0.95,
              }}
            />
          </Source>

          {/* Render draw overlay if any custom draw lines exist */}
          {routeSegments.some((s) => s.mode === "draw") && (
            <Source
              id="dynamic-routes-draw"
              type="geojson"
              data={dynamicRouteGeoJSON as any}
            >
              <Layer
                id="route-draw-border"
                type="line"
                filter={["==", "mode", "draw"]}
                layout={{ "line-join": "round", "line-cap": "round" }}
                paint={{
                  "line-color": "#ffffff",
                  "line-width": 9,
                }}
              />
              <Layer
                id="route-draw-fill"
                type="line"
                filter={["==", "mode", "draw"]}
                layout={{ "line-join": "round", "line-cap": "round" }}
                paint={{
                  "line-color": "#ff790c",
                  "line-width": 5,
                }}
              />
            </Source>
          )}
        </>
      ) : (
        <>
          {/* ======================================= */}
          {/* RAW / UPLOADED GPX ROUTES               */}
          {/* ======================================= */}
          <Source id="raw-routes" type="geojson" data={rawRouteGeoJSON as any}>
            <Layer
              id="raw-routes-line"
              type="line"
              layout={{ "line-join": "round", "line-cap": "round" }}
              paint={{
                "line-color": hexLineColor,
                "line-width": lineWidth,
                "line-opacity": 0.8,
              }}
            />
          </Source>

          {/* ======================================= */}
          {/* DYNAMIC NAVIVI ROUTES                   */}
          {/* ======================================= */}
          <Source
            id="dynamic-routes"
            type="geojson"
            data={dynamicRouteGeoJSON as any}
          >
            <Layer
              id="route-all-border"
              type="line"
              filter={["!in", "mode", "direct", "curve"]}
              layout={{ "line-join": "round", "line-cap": "round" }}
              paint={{
                "line-color": hexBorderColor,
                "line-width": borderWidth === 0 ? 0 : lineWidth + borderWidth * 2,
                "line-opacity": borderWidth === 0 ? 0 : 1,
              }}
            />
            <Layer
              id="route-line"
              type="line"
              filter={["!in", "mode", "direct", "curve"]}
              layout={{ "line-join": "round", "line-cap": "round" }}
              paint={{
                "line-color": ["coalesce", ["get", "color"], hexLineColor],
                "line-width": lineWidth,
              }}
            />
            <Layer
              id="route-direct"
              type="line"
              filter={["==", "mode", "direct"]}
              layout={{ "line-join": "round", "line-cap": "round" }}
              paint={{
                "line-color": "#a1a1aa",
                "line-width": 4,
                "line-dasharray": [2, 2],
              }}
            />
            <Layer
              id="route-curve"
              type="line"
              filter={["==", "mode", "curve"]}
              layout={{ "line-join": "round", "line-cap": "round" }}
              paint={{
                "line-color": "#a855f7",
                "line-width": 4,
                "line-dasharray": [2, 3],
              }}
            />
          </Source>
        </>
      )}
    </>
  );
}
