import { useMemo } from "react";
import { Source, Layer } from "react-map-gl/mapbox";
import { useWorkspace } from "../../../../hooks/useWorkspace";

interface RouteLayerProps {
  uploadedRouteLine: [number, number][];
  routePoints: [number, number][];
  drawnRoute: [number, number][];
}

export function RouteLayer({ uploadedRouteLine, routePoints, drawnRoute }: RouteLayerProps) {
  const { routeSegments, settings } = useWorkspace();

  const hexLineColor =
    "#" + settings.line_color.map((x) => x.toString(16).padStart(2, "0")).join("");
  const lineWidth = settings.line_thickness || 4;

  const dynamicRouteGeoJSON = useMemo(() => {
    const features = routeSegments.map((segment) => ({
      type: "Feature",
      properties: { 
        mode: segment.mode || "driving" 
      },
      geometry: {
        type: "LineString",
        // Mapbox strictly requires [longitude, latitude] order
        coordinates: segment.positions.map((pos) => [pos[1], pos[0]]),
      },
    }));

    return { type: "FeatureCollection", features };
  }, [routeSegments]);

  // Convert Raw/Uploaded GPX paths
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

  const drawnRouteGeoJSON = useMemo(() => {
    const coords = drawnRoute.length >= 2 ? drawnRoute.map((pos) => [pos[1], pos[0]]) : [];
    return {
      type: "FeatureCollection",
      features: coords.length > 0 ? [
        {
          type: "Feature",
          properties: { mode: "drawn" },
          geometry: { type: "LineString", coordinates: coords },
        }
      ] : []
    };
  }, [drawnRoute]);

  return (
    <>
      {/* RAW / UPLOADED GPX ROUTES                 */}    
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
      
      {/* DYNAMIC ROUTES                     */}
      <Source id="dynamic-routes" type="geojson" data={dynamicRouteGeoJSON as any}>
        
        {/* DRIVING - Solid Line */}
        <Layer
          id="route-driving"
          type="line"
          filter={["==", "mode", "driving"]} // 🛠️ Mapbox filters this instantly on the GPU!
          layout={{ "line-join": "round", "line-cap": "round" }}
          paint={{
            "line-color": hexLineColor,
            "line-width": lineWidth,
          }}
        />

        {/* WALKING - Dashed Line */}
        <Layer
          id="route-walking"
          type="line"
          filter={["==", "mode", "walking"]}
          layout={{ "line-join": "round", "line-cap": "round" }}
          paint={{
            "line-color": hexLineColor,
            "line-width": lineWidth,
            "line-dasharray": [1, 2], // Dash length is multiplied by line-width
          }}
        />

        {/* FERRY - Blue Dashed */}
        <Layer
          id="route-ferry"
          type="line"
          filter={["==", "mode", "ferry"]}
          layout={{ "line-join": "round", "line-cap": "round" }}
          paint={{
            "line-color": "#2563eb",
            "line-width": lineWidth,
            "line-dasharray": [2, 2],
          }}
        />

        {/* DIRECT - Gray Dashed */}
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

        {/* CURVE - Purple Dashed */}
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

        {drawnRoute.length > 0 && (
        <Source id="drawn-routes" type="geojson" data={drawnRouteGeoJSON as any}>
          <Layer 
            id="drawn-routes-line"
            type="line"
            layout={{ "line-join": "round", "line-cap": "round" }}
            paint={{
              "line-color": "#f59e0b",
              "line-border-color": "#fff",
              "line-width": lineWidth,
              "line-border-width": 2,
              "line-dasharray": [2, 2],
            }}
          />
        </Source>
        )}
      </Source>
    </>
  );
}