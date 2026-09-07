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
      )}

      {/* 3. Dynamic Generated Segments */}
      {routeSegments.map((segment, idx) => {
        if (segment.mode === "direct") {
          return (
            <Polyline
              key={`dir-${idx}`}
              positions={segment.positions}
              pathOptions={{ color: "#a1a1aa", weight: 4, dashArray: "8, 8" }}
            />
          );
        }
        if (segment.mode === "curve") {
          return (
            <Polyline
              key={`crv-${idx}`}
              positions={segment.positions}
              pathOptions={{ color: "#a855f7", weight: 4, dashArray: "10, 10" }}
            />
          );
        }
        if (segment.mode === "walking") {
          return (
            <Polyline
              key={`wlk-${idx}`}
              positions={segment.positions}
              pathOptions={{
                color: hexLineColor,
                weight: settings.line_thickness,
                dashArray: "2, 6",
                lineCap: "round",
              }}
            />
          );
        }
        // Default Driving
        return (
          <Polyline
            key={`drv-${idx}`}
            positions={segment.positions}
            pathOptions={{
              color: hexLineColor,
              weight: settings.line_thickness,
            }}
          />
        );
      })}
    </>
  );
}