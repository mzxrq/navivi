import { useEffect, useRef } from "react";
import { useMap, useMapEvents } from "react-leaflet";
import { Waypoint } from "../../types";

export function MapAutoZoom({ waypoints, projectId }: { waypoints: any[], projectId?: string }) {
  const map = useMap();
  const lastProjectIdRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    setTimeout(() => map.invalidateSize(), 100);
    if (projectId && projectId !== lastProjectIdRef.current && waypoints.length > 0) {
      lastProjectIdRef.current = projectId;
      const bounds = waypoints.map(wp => [wp.lat, wp.lng] as [number, number]);
      map.fitBounds(bounds, { padding: [50, 50], maxZoom: 16, animate: true, duration: 1 });
    }
  }, [projectId, waypoints, map]);
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

export function MapPreviewer({ waypoints, routePoints }: { waypoints: Waypoint[], routePoints?: any[] }) {
  const map = useMap();
  const isPreviewingRef = useRef(false);

  useEffect(() => {
    const startPreview = async () => {
      if (waypoints.length === 0) return;
      isPreviewingRef.current = true;

      // follow route line
      if (routePoints && routePoints.length > 0) {
        map.flyTo(routePoints[0], 16, {duration: 1.5});
        await new Promise((res) => setTimeout(res, 1500));

        let currentIndex = 0;

        const step = Math.max(1, Math.floor(routePoints.length / 500));

        const animateCamera = () => {
          if (!isPreviewingRef.current) return;

          if (currentIndex >= routePoints.length) {
            isPreviewingRef.current = false;
            window.dispatchEvent(new Event("preview-finished"));
            return;
          }

          const currentPoint = routePoints[currentIndex];
          const targetCoord = Array.isArray(currentPoint) ? currentPoint : [currentPoint.lat, currentPoint.lng || currentPoint.lon];

          map.setView(targetCoord as [number, number], map.getZoom(), { animate: false });

          currentIndex += step;
          requestAnimationFrame(animateCamera);
        };
        animateCamera();
      } else {
          for (let i = 0; i < waypoints.length; i++) {
          if (!isPreviewingRef.current) break;

          const wp = waypoints[i];

          map.flyTo([wp.lat, wp.lng], 16, {
            duration: 2,
            easeLinearity: 0.25,
          });

          await new Promise((resolve) => setTimeout(resolve, 3500));
        }

        isPreviewingRef.current = false;
        window.dispatchEvent(new Event("preview-finished"));
      }
    };

    const stopPreview = () => {
      isPreviewingRef.current = false;
    };

    window.addEventListener("start-preview", startPreview);
    window.addEventListener("stop-preview", stopPreview);

    return () => {
      window.removeEventListener("start-preview", startPreview);
      window.removeEventListener("stop-preview", stopPreview);
    };
  }, [map, waypoints, routePoints]);

  return null;
}