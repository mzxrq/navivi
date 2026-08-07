import { useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { readTextFile } from '@tauri-apps/plugin-fs';
import { MapContainer, Polyline, TileLayer, useMap, useMapEvents, Marker } from "react-leaflet";
import L from 'leaflet';
import { Clock, UploadCloud, CheckCircle2, FileCode } from "lucide-react";

// tailwind map marker
const waypointIcon = L.divIcon({
  className: 'bg-transparent',
  html: `<div class="w-4 h-4 bg-emerald-400 border-2 border-white rounded-full shadow-[0_0_10px_rgba(52,211,153,0.8)] hover:scale-125 transition-transform cursor-pointer"></div>`,
  iconSize: [16, 16],
  iconAnchor: [8, 8],
});

// map controllers
function MapAutoZoom({ routePoints }: { routePoints: [number, number][] }) {
  const map = useMap();
  useEffect(() => {
    setTimeout(() => map.invalidateSize(), 100);
    if (routePoints.length > 0) {
      map.fitBounds(routePoints, { padding: [50, 50], animate: true });
    }
  }, [routePoints, map]);
  return null;
}

function MapClickListener({ onMapClick }: { onMapClick: (lat: number, lng: number) => void }) {
  useMapEvents({
    click(e) {
      onMapClick(e.latlng.lat, e.latlng.lng);
    },
  });
  return null;
}

// function MapController({ routePoints }: { routePoints: [number, number][] }) {
//   const map = useMap();

//   useEffect(() => {
//     // force recalc container size after rendering
//     setTimeout(() => {
//       map.invalidateSize();
//     }, 100)

//     if (routePoints.length > 0) {
//       map.fitBounds(routePoints, { padding: [50, 50], animate: true });
//     }
//   }, [routePoints, map]);
//   return null;
// }

export function MapArea() {
  const [droppedFile, setDroppedFile] = useState<string | null>(null);
  const [isHovering, setIsHovering] = useState(false);
  const [routePoints, setRoutePoints] = useState<[number, number][]>([]);
  const [waypoints, setWaypoints] = useState<[number, number][]>([]);

  // drag and drop
  useEffect(() => {
    const unlistenHover = listen('tauri://drag-enter', () => setIsHovering(true));
    const unlistenLeave = listen ('tauri://drag-leave', () => setIsHovering(false));
    const unlistenDrop = listen<{ paths: string[] }>('tauri://drop', (event) => {
      setIsHovering(false);
      const droppedFiles = event.payload.paths;
      if (droppedFiles && droppedFiles.length > 0) {
        setDroppedFile(droppedFiles[0]);
      }
    });

    return () => {
      unlistenHover.then((f) => f());
      unlistenLeave.then((f) => f());
      unlistenDrop.then((f) => f());
    };
  }, []);

  // parse file gpx, otherwise wait backend
  useEffect(() => {
    if (!droppedFile) return;

    if (droppedFile.toLowerCase().endsWith('.gpx')) {
      const parseGpx = async () => {
        try {
          const fileContent = await readTextFile(droppedFile);
          const parser = new DOMParser();
          const xmlDoc = parser.parseFromString(fileContent, "text/xml");
          const trackPoints = xmlDoc.getElementsByTagName("trkpt");
          const points: [number, number][] = [];

          for (let i = 0; i < trackPoints.length; i++) {
            const lat = parseFloat(trackPoints[i].getAttribute("lat") || "0");
            const lon = parseFloat(trackPoints[i].getAttribute("lon") || "0");
            if (lat && lon) points.push([lat, lon]);
          }
          setRoutePoints(points);
        } catch (error) {
          console.error("Failed to parse GPX:", error);
        }
      };
      parseGpx();
    } else {
      //            //
      // Wait for   //
      // backend    //
      // from Dev 1 //
      //            //
      setRoutePoints([]);
    }
  }, [droppedFile]);

  const handleAddWaypoint = (lat: number, lng: number) => {
    setWaypoints((prev) => [...prev, [lat, lng]]);
  }

  // determine file status
  const isGpx = droppedFile?.toLowerCase().endsWith('.gpx');

  return (
    <main className="flex-1 relative bg-[#09090b] overflow-hidden">
      <div className="absolute inset-0 z-0">
        <MapContainer 
          center={[35.6895, 139.6917]}
          zoom={13}
          zoomControl={false}
          style={{ height: '100%', width: '100%', background: '#09090b' }}
        >
          <TileLayer
            attribution="&copy; OpenStreetMap contributors &copy; CARTO"
            url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}/{r}.png"
          />

          {routePoints.length > 0 && (
            <Polyline
              positions={routePoints}
              pathOptions={{ color: '#3b82f6', weight: 4, opacity: 0.8, lineCap: 'round', lineJoin: 'round' }}
            />
          )}

          {waypoints.map((pos, idx) => (
            <Marker key={idx} position={pos} icon={waypointIcon} />
          ))}

          <MapAutoZoom routePoints={routePoints} />
          <MapClickListener onMapClick={handleAddWaypoint} />
        </MapContainer>
      </div>

      {isHovering && (
        <div className="absolute inset-0 z-50 bg-zinc-950/80 backdrop-blur-sm border-2 border-dashed border-zinc-500 m-4 rounded-2xl flex flex-col items-center justify-center transition-all animate-in fade-in">
          <div className="w-16 h-16 rounded-2xl bg-zinc-200 text-zinc-900 flex items-center justify-center mb-4 shadow-lg shadow-white/10 scale-110">
            <UploadCloud className="w-8 h-8"/>
          </div>
          <p className="text-zinc-200 font-medium text-lg">Drop any GPS file to Load</p>
        </div>
      )}

      {/* floating status */}
      {!isHovering && (
        <div className="absolute top-6 left-6 z-40">
          {droppedFile ? (
            isGpx ? (
              <div className="flex items-center gap-3 bg-zinc-900/90 backdrop-blur-md border border-emerald-500/30 px-4 py-2.5 rounded-xl shadow-lg shadow-black/50">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                <div className="flex flex-col">
                  <span className="text-xs font-bold text-zinc-200 uppercase tracking-wider">Route Loaded</span>
                  <span className="text-[10px] text-zinc-400 font-mono max-w-[200px] truncate" title={droppedFile}>
                    {droppedFile}
                  </span>
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-3 bg-zinc-900/90 backdrop-blur-md border border-amber-500/30 px-4 py-2.5 rounded-xl shadow-lg shadow-black/50">
                <Clock className="w-4 h-4 text-amber-400 animate-pulse" />
                <div className="flex flex-col">
                  <span className="text-xs font-bold text-zinc-200 uppercase tracking-wider">Awaiting Conversion</span>
                  <span className="text-[10px] text-zinc-400 font-mono max-w-[200px] truncate" title={droppedFile}>
                    {droppedFile}
                  </span>
                </div>
              </div>
            )
          ) : (
            <div className="flex items-center gap-3 bg-zinc-900/90 backdrop-blur-md border border-white/10 px-4 py-2.5 rounded-xl shadow-lg shadow-black/50">
              <FileCode className="w-4 h-4 text-zinc-500" />
              <div className="flex flex-col">
                <span className="text-xs font-bold text-zinc-300 uppercase tracking-wider">No Route Loaded</span>
                <span className="text-[10px] text-zinc-500">Drag any GPS file to beign</span>
              </div>
            </div>
          )}
        </div>
      )}
    </main>
  );
}