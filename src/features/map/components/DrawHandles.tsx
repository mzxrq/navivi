import { Layer, Marker, Source } from "react-map-gl/mapbox";
import { t } from "@lingui/core/macro";
import type { Waypoint } from "../../../types";
import { rgbToHex } from "../../../components/ui/ColorSwatches";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { curvesOf, dragHandle, handlesFor, sampleDrawnPath } from "../../../utils/drawnPath";
import { setDrawPreview, useDrawPreview } from "../drawPreview";

type Props = {
  activeWp: Waypoint | null;
  nextWp: Waypoint | null;
  selectedAnchor: number | null;
  onCommit: (patch: Partial<Waypoint>) => void;
};

// While drawing: the leg as it would be if the dragged anchor or handle were dropped now, plus the selected smooth
// anchor's two handles.
export function DrawHandles({ activeWp, nextWp, selectedAnchor, onCommit }: Props) {
  const preview = useDrawPreview();
  const { settings } = useWorkspace();
  if (!activeWp || !nextWp) return null;

  const wp: Waypoint = preview?.wpId === activeWp.id ? { ...activeWp, ...preview.patch } : activeWp;
  const from: [number, number] = [activeWp.lat, activeWp.lng];
  const to: [number, number] = [nextWp.lat, nextWp.lng];
  const route = wp.customRoute ?? [];
  const curves = curvesOf(wp);
  const anchor = selectedAnchor !== null ? route[selectedAnchor] : undefined;
  const handles = anchor && curves[selectedAnchor!] ? handlesFor([from, ...route, to], curves)[selectedAnchor! + 1] : null;

  const color = activeWp.lineColor ? rgbToHex(activeWp.lineColor) : "#" + (settings?.line_color || [59, 130, 246]).map((x: number) => x.toString(16).padStart(2, "0")).join("");
  const width = settings?.line_thickness || 4;

  const ends = handles && anchor ? (["in", "out"] as const).map((which) => ({ which, lat: anchor[0] + handles[which][0], lng: anchor[1] + handles[which][1] })) : [];

  const drag = (which: "in" | "out", lat: number, lng: number) =>
    dragHandle(activeWp, from, to, selectedAnchor!, which, [lat, lng]);

  return (
    <>
      {preview?.wpId === activeWp.id && (
        <Source
          id="draw-preview"
          type="geojson"
          data={{
            type: "Feature",
            properties: {},
            geometry: { type: "LineString", coordinates: sampleDrawnPath([from, ...route, to], curves).map((p) => [p[1], p[0]]) },
          }}
        >
          <Layer id="draw-preview-line" type="line" layout={{ "line-cap": "round", "line-join": "round" }} paint={{ "line-color": color, "line-width": width }} />
        </Source>
      )}
      {anchor && ends.length > 0 && (
        <>
          <Source
            id="curve-handles"
            type="geojson"
            data={{
              type: "FeatureCollection",
              features: ends.map((h) => ({
                type: "Feature",
                properties: {},
                geometry: { type: "LineString", coordinates: [[anchor[1], anchor[0]], [h.lng, h.lat]] },
              })),
            }}
          >
            <Layer id="curve-handles-line" type="line" paint={{ "line-color": "#4287f5", "line-width": 1.5 }} />
          </Source>
          {ends.map((h) => (
            <Marker
              key={`handle-${selectedAnchor}-${h.which}`}
              latitude={h.lat}
              longitude={h.lng}
              draggable
              onDrag={(e) => setDrawPreview({ wpId: activeWp.id, patch: drag(h.which, e.lngLat.lat, e.lngLat.lng) })}
              onDragEnd={(e) => {
                onCommit(drag(h.which, e.lngLat.lat, e.lngLat.lng));
                setDrawPreview(null);
              }}
            >
              <div
                onClick={(e) => e.stopPropagation()}
                title={h.which === "in" ? t`Drag to shape the curve coming into this point` : t`Drag to shape the curve leaving this point`}
                className="w-3 h-3 rotate-45 bg-white dark:bg-zinc-900 border-2 border-navi shadow-sm cursor-grab active:cursor-grabbing"
              />
            </Marker>
          ))}
        </>
      )}
    </>
  );
}
