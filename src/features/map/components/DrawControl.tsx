import MapboxDraw from "@mapbox/mapbox-gl-draw";
import { useControl } from "react-map-gl/mapbox";
import type { ControlPosition } from "react-map-gl/mapbox";
import React from "react";

type DrawControlProps = ConstructorParameters<typeof MapboxDraw>[0] & {
  position?: ControlPosition;
  onCreate?: (evt: { features: any[] }) => void;
  onUpdate?: (evt: { features: any[]; action: string }) => void;
  onDelete?: (evt: { features: any[] }) => void;
  initialFeatures?: any[];
  drawRef?: React.MutableRefObject<MapboxDraw | null>;
};

export default function DrawControl({
  drawRef,
  initialFeatures,
  ...mapboxDrawOptions
}: DrawControlProps) {
  let drawInstance: MapboxDraw | null = null;

  useControl<MapboxDraw>(
    () => {
      drawInstance = new MapboxDraw(mapboxDrawOptions);
      if (drawRef) {
        drawRef.current = drawInstance;
      }
      return drawInstance;
    },
    ({ map }) => {
      if (mapboxDrawOptions.onCreate)
        map.on("draw.create", mapboxDrawOptions.onCreate);
      if (mapboxDrawOptions.onUpdate)
        map.on("draw.update", mapboxDrawOptions.onUpdate);
      if (mapboxDrawOptions.onDelete)
        map.on("draw.delete", mapboxDrawOptions.onDelete);

      // Load initial features ONLY after the control has been fully attached to the map
      // We use a small timeout to ensure mapbox-gl-draw has initialized its internal ctx
      setTimeout(() => {
        if (drawInstance && initialFeatures && initialFeatures.length > 0) {
          drawInstance.set({
            type: "FeatureCollection",
            features: initialFeatures,
          });
        }
      }, 0);
    },
    ({ map }) => {
      if (mapboxDrawOptions.onCreate)
        map.off("draw.create", mapboxDrawOptions.onCreate);
      if (mapboxDrawOptions.onUpdate)
        map.off("draw.update", mapboxDrawOptions.onUpdate);
      if (mapboxDrawOptions.onDelete)
        map.off("draw.delete", mapboxDrawOptions.onDelete);

      if (drawRef && drawRef.current === drawInstance) {
        drawRef.current = null;
      }
    },
    {
      position: mapboxDrawOptions.position,
    },
  );

  return null;
}
