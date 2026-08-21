import { MapSettings } from "../../modal/MapSettings";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useTheme } from "../../../hooks/useTheme";
import { useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { 
  // Clock, 
  UploadCloud,  
  // CheckCircle2,  
  // FileCode, 
  MapPin } from "lucide-react";
import { MapContainer, TileLayer } from "react-leaflet";
import { useMapRouting } from "../../../hooks/useMapRouting";
import { MapAutoZoom, MapEventsHandler, MapPreviewer } from "../../controllers/mapControllers";
import { RouteLayer } from "./MapLayers/RouteLayer";
import { WaypointLayer } from "./MapLayers/WaypointLayer";
import { useFileActions } from "../../../hooks/useFileActions";
import { loadProjectData } from "../../../services/fileSystem";

export function MapArea() {
  const { theme, mapTheme } = useTheme();
  const [uploadedRouteLine] = useState<
    [number, number][]
  >([]);
  const [isHovering, setIsHovering] = useState(false);
  const { routePoints } = useWorkspace();
  const {
    waypoints,
    setWaypoints,
    settings,
    metadata,
    setIsDirty,
  } = useWorkspace();
  const { importRouteFile } = useFileActions();

  const [menu, setMenu] = useState<{ show: boolean; x: number; y: number; lat: number; lng: number } | null>(null);

  useEffect(() => {
    const closeMenu = () => setMenu(null);
    window.addEventListener("click", closeMenu);
    window.addEventListener("close-context-menus", closeMenu);

    return () => {
      window.removeEventListener("click", closeMenu);
      window.removeEventListener("close-context-menus", closeMenu);
    };
  }, []);

  const handleMapContextMenu = (e: MouseEvent, lat: number, lng: number) => {
    window.dispatchEvent(new Event("close-context-menus"));    
    const xPos = e.clientX + 192 > window.innerWidth ? window.innerWidth - 192 : e.clientX;
    const yPos = e.clientY + 130 > window.innerHeight ? window.innerHeight - 130 : e.clientY;
    setMenu({ show: true, x: xPos, y: yPos, lat, lng });
  };

  useMapRouting();
  const [isProcessing, setIsProcessing] = useState(false);

  const isDarkMap = mapTheme === "dark" || (mapTheme === "sync" && (theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches)));

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
        if (event.payload.paths && event.payload.paths.length > 0) {
          const path = event.payload.paths[0];

          if (path.toLowerCase().endsWith(".json")) {
            await loadProjectData(path);
          } else {
            await importRouteFile(path);
          }
        }
      },
    );

    return () => {
      unlistenHover.then((f) => f());
      unlistenLeave.then((f) => f());
      unlistenDrop.then((f) => f());
    };
  }, []);

  // waypoints on map click
  const handleAddWaypoint = async (lat: number, lng: number) => {
    const newId = Math.random().toString(36).substring(7);

    setWaypoints((prev) => [
      ...prev,
      {
        id: newId,
        lat,
        lng,
        name: "Locating...",
        images: [],
        narration: "",
        routeMode: "driving",
      },
    ]);
    setIsDirty(true);
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

  
  // const isGpx = droppedFile?.toLowerCase().endsWith(".gpx");

  return (
    <main 
      className="flex-1 relative bg-zinc-100 dark:bg-[#09090b] overflow-hidden transition-colors"
      onClick={() => setMenu(null)} // Clicking outside closes menu
    >
      <MapSettings />
      
      <div className="absolute inset-0 z-0">
        <MapContainer
          center={settings.start_coords || [34.6937, 135.5023]}
          zoom={10}
          zoomControl={false}
          style={{ height: "100%", width: "100%", background: "transparent" }}
        >
          <TileLayer
            key={isDarkMap ? "dark-map" : "light-map"}
            attribution="&copy; OpenStreetMap contributors &copy; CARTO"
            url={
              isDarkMap
                ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
                : "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
            }
          />

          {/* Clean, abstracted map layers */}
          <RouteLayer 
            uploadedRouteLine={uploadedRouteLine} 
            routePoints={routePoints} 
          />
          <WaypointLayer />

          <MapAutoZoom waypoints={waypoints} projectId={metadata.project_id}/>
          <MapPreviewer waypoints={waypoints} routePoints={uploadedRouteLine.length > 0 ? uploadedRouteLine : routePoints}/>

          {/* New Event Handler */}
          <MapEventsHandler 
            onMapClick={handleAddWaypoint} 
            onMapContextMenu={handleMapContextMenu}
            onMapDrag={() => setMenu(null)}
          />
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
      
      {/* Processing Overlay */}
      {isProcessing && (
        <div className="absolute inset-0 z-[100] bg-white/50 dark:bg-zinc-950/50 backdrop-blur-sm flex flex-col items-center justify-center transition-all animate-in fade-in">
          <div className="w-12 h-12 border-4 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin mb-4" />
          <p className="text-zinc-900 dark:text-zinc-200 font-bold text-sm tracking-widest uppercase">
            Parsing Route Data...
          </p>
        </div>
      )}

      {/* Map Context Menu */}
      {menu?.show && (
        <div
          key={`${menu.x}-${menu.y}`}
          className="fixed z-1000 w-48 bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xl border border-zinc-200 dark:border-white/10 rounded-xl shadow-2xl p-1 animate-in fade-in zoom-in-95 duration-100"
          style={{ top: menu.y, left: menu.x }}
          onContextMenu={(e) => e.preventDefault()} // Prevent native menu on top of this menu
        >
          <div className="flex flex-col text-sm text-zinc-700 dark:text-zinc-300 font-medium">
            <button
              onClick={(e) => {
                e.stopPropagation();
                handleAddWaypoint(menu.lat, menu.lng);
                setMenu(null);
              }}
              className="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors text-left"
            >
              <MapPin className="w-4 h-4" /> Add Waypoint Here
            </button>
            {/* Future option: Add "Search nearby..." or "Paste Coordinates" here */}
          </div>
        </div>
      )}
    </main>
  );
}
