import { useMemo } from "react";
import { Source, Layer } from "react-map-gl/mapbox";
import { useWorkspace } from "../../../../hooks/useWorkspace";

interface RouteLayerProps {
  uploadedRouteLine: [number, number][];
  routePoints: [number, number][];
}

export function RouteLayer({ uploadedRouteLine, routePoints }: RouteLayerProps) {
  const { routeSegments, settings } = useWorkspace();

  const hexLineColor =
    "#" + settings.line_color.map((x) => x.toString(16).padStart(2, "0")).join("");
  const lineWidth = settings.line_thickness || 4;

  const dynamicRouteGeoJSON = useMemo(() => {
    const features = routeSegments.map((segment) => ({
      type: "Feature",
      properties: {
        mode: segment.mode || "driving",
      },
      geometry: {
        type: "LineString",
        coordinates: segment.positions.map((pos) => [pos[1], pos[0]]),
      },
    }));

    return { type: "FeatureCollection", features };
  }, [routeSegments]);

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

  return (
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
            "line-color": "#3b82f6",
            "line-width": 4,
            "line-opacity": 0.5,
          }}
        />
      </Source>

      {/* ======================================= */}
      {/* DYNAMIC NAVIVI ROUTES                   */}
      {/* ======================================= */}
      <Source id="dynamic-routes" type="geojson" data={dynamicRouteGeoJSON as any}>
        
        {/* 🛠️ DRAW BORDER (White, thick, renders underneath) */}
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

        {/* 🛠️ NORMAL ROUTES */}
        <Layer
          id="route-driving"
          type="line"
          filter={["==", "mode", "driving"]}
          layout={{ "line-join": "round", "line-cap": "round" }}
          paint={{ "line-color": hexLineColor, "line-width": lineWidth }}
        />
        <Layer
          id="route-walking"
          type="line"
          filter={["==", "mode", "walking"]}
          layout={{ "line-join": "round", "line-cap": "round" }}
          paint={{ "line-color": hexLineColor, "line-width": lineWidth, "line-dasharray": [1, 2] }}
        />
        <Layer
          id="route-ferry"
          type="line"
          filter={["==", "mode", "ferry"]}
          layout={{ "line-join": "round", "line-cap": "round" }}
          paint={{ "line-color": "#2563eb", "line-width": lineWidth, "line-dasharray": [2, 2] }}
        />
        <Layer
          id="route-direct"
          type="line"
          filter={["==", "mode", "direct"]}
          layout={{ "line-join": "round", "line-cap": "round" }}
          paint={{ "line-color": "#a1a1aa", "line-width": 4, "line-dasharray": [2, 2] }}
        />
        <Layer
          id="route-curve"
          type="line"
          filter={["==", "mode", "curve"]}
          layout={{ "line-join": "round", "line-cap": "round" }}
          paint={{ "line-color": "#a855f7", "line-width": 4, "line-dasharray": [2, 3] }}
        />

        {/* 🛠️ DRAW FILL (Orange, dashed, renders on top) */}
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
    </>
  );
}