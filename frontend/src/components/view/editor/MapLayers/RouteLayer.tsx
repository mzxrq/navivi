import { Polyline } from "react-leaflet";
import { useWorkspace } from "../../../../hooks/useWorkspace";

interface RouteLayerProps {
  uploadedRouteLine: [number, number][];
  routePoints: [number, number][];
}

export function RouteLayer({
  uploadedRouteLine,
  routePoints,
}: RouteLayerProps) {
  const { routeSegments, settings } = useWorkspace();

  const hexLineColor =
    "#" +
    settings.line_color.map((x) => x.toString(16).padStart(2, "0")).join("");

  return (
    <>
      {/* 1. Exact GPX path if uploaded (Semi-transparent Blue) */}
      {uploadedRouteLine.length > 0 && (
        <Polyline
          positions={uploadedRouteLine}
          pathOptions={{ color: "#3b82f6", weight: 4, opacity: 0.5 }}
        />
      )}

      {/* 2. Raw Route Points (e.g. dropped GPX) */}
      {routePoints.length > 0 && (
        <Polyline
          positions={routePoints}
          pathOptions={{
            color: "#3b82f6",
            weight: 4,
            opacity: 0.8,
            lineCap: "round",
            lineJoin: "round",
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
