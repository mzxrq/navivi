import { useEffect } from "react";
import { useMap, useMapEvents } from "react-leaflet";

export function MapAutoZoom({ waypoints, projectId }: { waypoints: any[], projectId?: string }) {
  const map = useMap();
  useEffect(() => {
    setTimeout(() => map.invalidateSize(), 100);
    if (waypoints.length > 0) {
      const bounds = waypoints.map(wp => [wp.lat, wp.lng] as [number, number]);
      map.fitBounds(bounds, { padding: [50, 50], maxZoom: 14, animate: true, duration: 1 });
    }
  }, [projectId]);
  return null;
}

export function MapEventsHandler({
  onMapClick,
  onMapContextMenu,
  onMapDrag
}: {
  onMapClick: (lat: number, lng: number) => void;
  onMapContextMenu: (e: any, lat: number, lng: number) => void;
  onMapDrag: () => void;
}) {
  useMapEvents({
    click(e) {
      onMapClick(e.latlng.lat, e.latlng.lng);
    },
    contextmenu(e) {
      onMapContextMenu(e.originalEvent, e.latlng.lat, e.latlng.lng);
    },
    dragstart() {
      onMapDrag()
    }
  });
  return null;
}