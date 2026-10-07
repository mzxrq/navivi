import { useMemo } from "react";
import { Source, Layer } from "react-map-gl/mapbox";
import { useWorkspace } from "../../../../hooks/useWorkspace";
import { rgbToHex } from "../../../../components/ui/ColorSwatches";
import { legGradients, type LegElevation } from "../../../../utils/elevation";

interface RouteLayerProps {
  uploadedRouteLine: number[][];
  routePoints: number[][];
  /** Elevation per route leg (same order as routeSegments); the heatmap colours the legs that have some. */
  legs: LegElevation[];
}

export function RouteLayer({
  uploadedRouteLine,
  routePoints,
  legs,
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

  const heatmapOn = Boolean(settings?.show_route_heatmap);

  const gradients = useMemo(() => (heatmapOn ? legs.map(legGradients) : []), [heatmapOn, legs]);

  const heatmapGeoJSON = useMemo(() => {
    const features: any[] = [];
    gradients.forEach((g, legIndex) => {
      g?.segments.forEach((seg) => {
        features.push({
          type: "Feature",
          properties: { legIndex, slope: seg.pct, color: seg.color },
          geometry: {
            type: "LineString",
            coordinates: [
              [seg.from[1], seg.from[0]],
              [seg.to[1], seg.to[0]],
            ],
          },
        });
      });
    });
    return { type: "FeatureCollection", features };
  }, [gradients]);

  const legColors = waypoints
    .filter((wp) => !wp.isStopBy || wp.connectToRoute)
    .map((wp) => (wp.lineColor ? rgbToHex(wp.lineColor) : ""))
    .join(",");

  const dynamicRouteGeoJSON = useMemo(() => {
    const colors = legColors.split(",");
    const features = routeSegments.flatMap((segment, i) => {
      if (gradients[i]) return []; // painted by the heatmap instead
      return [{
        type: "Feature",
        properties: {
          mode: segment.mode || "driving",
          color: colors[i] || null,
        },
        geometry: {
          type: "LineString",
          coordinates: segment.positions.map((pos) => [pos[1], pos[0]]),
        },
      }];
    });

    return { type: "FeatureCollection", features };
  }, [routeSegments, legColors, gradients]);

  const rawRouteGeoJSON = useMemo(() => {
    const features: any[] = [];
    if (heatmapOn) return { type: "FeatureCollection", features };
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
  }, [uploadedRouteLine, routePoints, heatmapOn]);

  return (
    <>
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

      {/* Legs with elevation, coloured by smoothed slope. Always mounted (empty when off) so toggling only swaps data. */}
      <Source id="route-gradient-heatmap-source" type="geojson" data={heatmapGeoJSON as any}>
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
    </>
  );
}
