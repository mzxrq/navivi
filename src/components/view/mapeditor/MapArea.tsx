import { MapSettings } from "../../modal/MapSettings";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useTheme } from "../../../hooks/useTheme";
import { useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { UploadCloud, MapPin } from "../../ui/icons";
import { MapContainer, TileLayer } from "react-leaflet";
import { useMapRouting } from "../../../hooks/useMapRouting";
import { MapAutoZoom, MapEventsHandler, MapPreviewer } from "../../controllers/mapControllers";
import { RouteLayer } from "./MapLayers/RouteLayer";
import { WaypointLayer } from "./MapLayers/WaypointLayer";
import { useFileActions } from "../../../hooks/useFileActions";
import { loadProjectData } from "../../../services/fileSystem";

export function MapArea() {
  const { theme, mapTheme } = useTheme();
  const [uploadedRouteLine] = useState<[number, number][]>([]);
  const [isHovering, setIsHovering] = useState(false);
  const { routePoints } = useWorkspace();
  const { waypoints, setWaypoints, settings, metadata, setIsDirty } = useWorkspace();
  const { importRouteFile } = useFileActions();

  // THE NEW TOGGLE STATE
  const [isAddMode, setIsAddMode] = useState(false);
  const [isProcessing] = useState(false);

  useMapRouting();

  const isDarkMap = mapTheme === "dark" || (mapTheme === "sync" && (theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches)));

  // Safely extract coordinates from Leaflet's custom event wrapper
  const handleMapContextMenu = (e: any, lat: number, lng: number) => {
    const domEvent = e.originalEvent || e; 
    window.dispatchEvent(new CustomEvent("open-context-menu", {
      detail: { 
        x: domEvent.clientX, 
        y: domEvent.clientY, 
        type: "map-canvas", 
        data: { lat, lng, handleAddWaypoint } 
      }
    }));
  };

  // Only add waypoints if the toggle is ON!
  const handleMapClick = (lat: number, lng: number) => {
    if (!isAddMode) return;
    handleAddWaypoint(lat, lng);
  };

  const handleAddWaypoint = async (lat: number, lng: number) => {
    const newId = Math.random().toString(36).substring(7);

    setWaypoints((prev) => [
      ...prev,
      {
        id: newId, lat, lng, name: "Locating...", images: [], imagePans: [], narration: "", routeMode: "driving",
      },
    ]);
    setIsDirty(true);
    
    try {
      const res = await fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}`);
      const data = await res.json();
      const placeName = data.name || data.address?.road || data.address?.city || `Waypoint ${newId.substring(0, 4).toUpperCase()}`;

      setWaypoints((prev) =>
        prev.map((wp) => (wp.id === newId ? { ...wp, name: placeName } : wp)),
      );
    } catch (error) {
      setWaypoints((prev) => prev.map((wp) => wp.id === newId ? { ...wp, name: `Unknown Location` } : wp));
    }
  };

  // Drag and drop listeners...
  useEffect(() => {
    const unlistenHover = listen("tauri://drag-enter", () => setIsHovering(true));
    const unlistenLeave = listen("tauri://drag-leave", () => setIsHovering(false));
    const unlistenDrop = listen<{ paths: string[] }>("tauri://drag-drop", async (event) => {
      setIsHovering(false);
      if (event.payload.paths && event.payload.paths.length > 0) {
        const path = event.payload.paths[0];
        if (path.toLowerCase().endsWith(".json")) {
          await loadProjectData(path);
        } else {
          await importRouteFile(path);
        }
      }
    });

    return () => {
      unlistenHover.then((f) => f());
      unlistenLeave.then((f) => f());
      unlistenDrop.then((f) => f());
    };
  }, []);

  return (
    <main className="flex-1 relative bg-zinc-100 dark:bg-[#09090b] overflow-hidden transition-colors">
      <MapSettings />
      
      {/* FLOATING ACTION BUTTON TO TOGGLE WAYPOINT MODE */}
      <button
        onClick={() => setIsAddMode(!isAddMode)}
        className={`absolute bottom-8 right-8 z-500 flex items-center gap-2 px-5 py-3 rounded-full shadow-xl transition-all font-bold text-sm ${
          isAddMode 
            ? "bg-red-500 hover:bg-red-600 text-white animate-pulse" 
            : "bg-white dark:bg-zinc-800 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-700 border border-zinc-200 dark:border-zinc-700"
        }`}
        title="Toggle Waypoint Addition Mode"
      >
        <MapPin className="w-5 h-5" />
        {isAddMode ? "Click Map to Add" : "Add Waypoint Mode"}
      </button>

      <div className="absolute inset-0 z-0">
        <MapContainer
          center={settings.start_coords || [34.6937, 135.5023]}
          zoom={13} maxZoom={19} zoomControl={false}
          preferCanvas={true}
          style={{ height: "100%", width: "100%", background: "transparent" }}
        >
          <TileLayer
            key={isDarkMap ? "dark-map" : "light-map"}
            maxZoom={19}
            attribution={isDarkMap ? '&copy; <a href="https://carto.com/">CARTO</a>' : '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'}
            url={isDarkMap ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" : "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"}
          />

          <RouteLayer uploadedRouteLine={uploadedRouteLine} routePoints={routePoints} />
          <WaypointLayer />

          <MapAutoZoom waypoints={waypoints} projectId={metadata.project_id}/>
          <MapPreviewer waypoints={waypoints} routePoints={uploadedRouteLine.length > 0 ? uploadedRouteLine : routePoints}/>

          <MapEventsHandler 
            onMapClick={handleMapClick} // NOW USES OUR TOGGLED FUNCTION
            onMapContextMenu={handleMapContextMenu}
            onMapDrag={() => {}}
          />
        </MapContainer>
      </div>

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
      
      {isProcessing && (
        <div className="absolute inset-0 z-100 bg-white/50 dark:bg-zinc-950/50 backdrop-blur-sm flex flex-col items-center justify-center transition-all animate-in fade-in">
          <div className="w-12 h-12 border-4 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin mb-4" />
          <p className="text-zinc-900 dark:text-zinc-200 font-bold text-sm tracking-widest uppercase">
            Parsing Route Data...
          </p>
        </div>
      )}
    </main>
  );
}