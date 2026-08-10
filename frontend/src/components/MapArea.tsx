import { invoke } from "@tauri-apps/api/core";
import { useWorkspace } from "../hooks/useWorkspace";
import { useTheme } from "../hooks/useTheme";
import { useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { readTextFile } from "@tauri-apps/plugin-fs";
import { open } from "@tauri-apps/plugin-dialog";
import {
  MapContainer,
  Polyline,
  TileLayer,
  useMap,
  useMapEvents,
  Marker,
  Popup,
} from "react-leaflet";
import L from "leaflet";
import { Clock, UploadCloud, CheckCircle2, FileCode } from "lucide-react";

// tailwind map marker
const waypointIcon = L.divIcon({
  className: "bg-transparent",
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

function MapClickListener({
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

export function MapArea() {
  const [isHovering, setIsHovering] = useState(false);
  const [routeLine, setRouteLine] = useState<[number, number][]>([]);
  const [routePoints, setRoutePoints] = useState<[number, number][]>([]);
  const {
    routeFile: droppedFile,
    setRouteFile: setDroppedFile,
    waypoints,
    setWaypoints,
    updateWaypoint,
  } = useWorkspace();
  const { theme } = useTheme();

  const isDark =
    theme === "dark" ||
    (theme === "system" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);

  // drag and drop get files
  useEffect(() => {
    const unlistenHover = listen("tauri://drag-enter", () =>
      setIsHovering(true),
    );
    const unlistenLeave = listen("tauri://drag-leave", () =>
      setIsHovering(false),
    );
    const unlistenDrop = listen<{ paths: string[] }>(
      "tauri://drag-drop",
      async (event) => {
        setIsHovering(false);
        const droppedFiles = event.payload.paths;

        if (droppedFiles && droppedFiles.length > 0) {
          const sourcePath = droppedFiles[0];
          const filename = sourcePath.split(/[\\/]/).pop() || "dropped.gpx";

          try {
            const safeBackendPath = await invoke<string>(
              "store_file_in_backend",
              {
                sourcePath: sourcePath,
                filename: filename,
              },
            );
            setDroppedFile(safeBackendPath);
          } catch (error) {
            console.error("Failed to copy dragged file:", error);
          }
        }
      },
    );

    return () => {
      unlistenHover.then((f) => f());
      unlistenLeave.then((f) => f());
      unlistenDrop.then((f) => f());
    };
  }, [setDroppedFile]);

  // routing
  useEffect(() => {
    // when have less than 2 waypoint, line can't be drawn so
    // we need validation
    if (waypoints.length < 2) {
      setRouteLine([]);
      return;
    }

    const fetchRoute = async () => {
      try {
        // osrm prefer lon/lat not lat/lon so we format coords first
        const coordinateString = waypoints.map(wp => '${wp.lng},${wp.lat}').join(';');
        // call osrm (free)
        const response = await fetch('https://router.project-osrm.org/route/v1/driving/${coordinateString}?overview=full&geometries=geojson');
        const data = await response.json();

        if (data.routes && data.routes.length > 0) {
          const osrmCoords = data.routes[0].geometry.coordinates.map(
            (coord: [number, number]) => [coord[1], coord[0]]
          )

          setRouteLine(osrmCoords);
        }
      } catch (error) {
        console.error("Routing Engine Failed:", error);
      };
      // tiny delay so it doesnt spam api
      const timeoutId = setTimeout(() => {
        fetchRoute();
      }, 500);

      return () => clearTimeout(timeoutId);
    }
  }, [waypoints]);

  // parse file directly if gpx (if not gpx, gpsbabel goes boom boom and reformat it to gpx/kml/csv/xlsx)
  useEffect(() => {
    if (!droppedFile) return;

    if (droppedFile.toLowerCase().endsWith(".gpx")) {
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
      setRoutePoints([]);
    }
  }, [droppedFile]);

  // waypoints on map click
  const handleAddWaypoint = async (lat: number, lng: number) => {
    const newId = Math.random().toString(36).substring(7);
    setWaypoints((prev) => [
      ...prev,
      { id: newId, lat, lng, name: "Locating...", image: null, narration: "" },
    ]);

    try {
      const res = await fetch(
        `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}`,
      );
      const data = await res.json();
      const placeName =
        data.name ||
        data.address?.road ||
        data.address?.city ||
        `Waypoint ${newId.substring(0, 4).toUpperCase()}`;

      setWaypoints((prev) =>
        prev.map((wp) => (wp.id === newId ? { ...wp, name: placeName } : wp)),
      );
    } catch (error) {
      setWaypoints((prev) =>
        prev.map((wp) =>
          wp.id === newId ? { ...wp, name: `Unknown Location` } : wp,
        ),
      );
    }
  };

  // browse files (same as drag and drop)
  const handleBrowseFiles = async () => {
    const selectedPath = await open({
      multiple: false,
      filters: [
        { name: "GPS Routes", extensions: ["gpx", "fit", "tcx", "kml"] },
      ],
    });

    if (typeof selectedPath === "string") {
      const filename = selectedPath.split(/[\\/]/).pop() || "uploaded.gpx";

      try {
        const safeBackendPath = await invoke<string>("store_file_in_backend", {
          sourcePath: selectedPath,
          filename: filename,
        });
        setDroppedFile(safeBackendPath);
      } catch (error) {
        console.error("Failed to copy file:", error);
      }
    }
  };

  const isGpx = droppedFile?.toLowerCase().endsWith(".gpx");

  return (
    <main className="flex-1 relative bg-zinc-100 dark:bg-[#09090b] overflow-hidden transition-colors">
      <div className="absolute inset-0 z-0">
        <MapContainer
          center={[34.6937, 135.5023]}
          zoom={10}
          zoomControl={false}
          style={{ height: "100%", width: "100%", background: "transparent" }}
        >
          <TileLayer
            attribution="&copy; OpenStreetMap contributors &copy; CARTO"
            url={
              isDark
                ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
                : "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
            }
          />

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

          {waypoints.map((wp) => (
            <Marker 
              key={wp.id}
              position={[wp.lat, wp.lng]}
              draggable={true}
              icon={waypointIcon}
              eventHandlers={{
                dragend: async (e) => {
                  const marker = e.target;
                  const position = marker.getLatLng();
                  updateWaypoint(wp.id, { lat: position.lat, lng: position.lng });
                  // get new location name
                  try {
                    const response = await fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${position.lat}&lon=${position.lng}`);
                    const data = await response.json();

                    const newName = data.address?.road || data.address?.amenity || data.name || "Unnamed Location";
                    updateWaypoint(wp.id, { name: newName });
                  } catch (error) {
                    console.error("Failed to fetch location name:", error);
                  }
                }
              }}>
                <Popup>
                  <div className="font-semibold">{wp.name}</div>
                  {wp.narration && <div className="text-xs text-gray-600 mt-1">{wp.narration}</div>}
                </Popup>
            </Marker>
          ))}

          {routeLine.length > 0 && (
            <Polyline positions={routeLine} pathOptions={{ color: '#3b82f6', weight: 4 }} />
          )}

          <MapAutoZoom routePoints={routePoints} />
          <MapClickListener onMapClick={handleAddWaypoint} />
        </MapContainer>
      </div>

      {/* Drag & Drop Overlay */}
      {isHovering && (
        <div className="absolute inset-0 z-50 bg-white/80 dark:bg-zinc-950/80 backdrop-blur-sm border-2 border-dashed border-zinc-400 dark:border-zinc-500 m-4 rounded-2xl flex flex-col items-center justify-center transition-all animate-in fade-in">
          <div className="w-16 h-16 rounded-2xl bg-zinc-900 dark:bg-zinc-200 text-zinc-100 dark:text-zinc-900 flex items-center justify-center mb-4 shadow-lg scale-110">
            <UploadCloud className="w-8 h-8" />
          </div>
          <p className="text-zinc-900 dark:text-zinc-200 font-medium text-lg">
            Drop any GPS file to Load
          </p>
        </div>
      )}

      {/* Floating Status Panel */}
      {!isHovering && (
        <div className="absolute top-6 left-6 z-40">
          {droppedFile ? (
            isGpx ? (
              <div className="flex items-center gap-3 bg-white/90 dark:bg-zinc-900/90 backdrop-blur-md border border-emerald-500/30 px-4 py-2.5 rounded-xl shadow-lg">
                <CheckCircle2 className="w-4 h-4 text-emerald-500 dark:text-emerald-400" />
                <div className="flex flex-col">
                  <span className="text-xs font-bold text-zinc-800 dark:text-zinc-200 uppercase tracking-wider">
                    Route Loaded
                  </span>
                  <span
                    className="text-[10px] text-zinc-500 dark:text-zinc-400 font-mono max-w-[200px] truncate"
                    title={droppedFile}
                  >
                    {droppedFile}
                  </span>
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-3 bg-white/90 dark:bg-zinc-900/90 backdrop-blur-md border border-amber-500/30 px-4 py-2.5 rounded-xl shadow-lg">
                <Clock className="w-4 h-4 text-amber-500 dark:text-amber-400 animate-pulse" />
                <div className="flex flex-col">
                  <span className="text-xs font-bold text-zinc-800 dark:text-zinc-200 uppercase tracking-wider">
                    Awaiting Conversion
                  </span>
                  <span
                    className="text-[10px] text-zinc-500 dark:text-zinc-400 font-mono max-w-[200px] truncate"
                    title={droppedFile}
                  >
                    {droppedFile}
                  </span>
                </div>
              </div>
            )
          ) : (
            <button
              onClick={handleBrowseFiles}
              className="flex items-center gap-3 bg-white/90 dark:bg-zinc-900/90 hover:bg-zinc-50 dark:hover:bg-zinc-800/95 backdrop-blur-md border border-zinc-200 dark:border-white/10 hover:border-zinc-300 dark:hover:border-zinc-400/50 transition-all px-4 py-2.5 rounded-xl shadow-lg text-left group"
            >
              <FileCode className="w-4 h-4 text-zinc-500 group-hover:text-zinc-700 dark:group-hover:text-zinc-300 transition-colors" />
              <div className="flex flex-col">
                <span className="text-xs font-bold text-zinc-800 dark:text-zinc-300 uppercase tracking-wider group-hover:text-zinc-950 dark:group-hover:text-zinc-100 transition-colors">
                  No Route Loaded
                </span>
                <span className="text-[10px] text-zinc-500 dark:text-zinc-500 group-hover:text-zinc-600 dark:group-hover:text-zinc-400 transition-colors">
                  Drag or click to browse files
                </span>
              </div>
            </button>
          )}
        </div>
      )}
    </main>
  );
}
