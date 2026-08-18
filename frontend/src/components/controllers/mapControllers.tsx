import { useEffect } from "react";
import { useMap, useMapEvents } from "react-leaflet";

export function MapAutoZoom({ waypoints, projectId }: { waypoints: any[], projectId: string }) {
  const map = useMap();
  useEffect(() => {
    setTimeout(() => map.invalidateSize(), 100);
    if (waypoints.length > 0) {
      const bounds = waypoints.map(wp => [wp.lat, wp.lng] as [number, number]);
      map.fitBounds(bounds, { padding: [50, 50], animate: true });
    }
  }, [projectId, waypoints]);
  return null;
}

export function MapClickListener({
  onMapClick,
}: {
  onMapClick: (lat: number, lng: number) => void;
}) {
  useMapEvents({
    click(e) {
      onMapClick(e.latlng.lat, e.latlng.lng);
    },
  });
  return null;
}