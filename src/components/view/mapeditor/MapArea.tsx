import { useEffect, useState } from "react";
import Map, { ViewStateChangeEvent, Marker } from "react-map-gl/mapbox";
import { listen } from "@tauri-apps/api/event";
import { UploadCloud, MapPin, Pencil } from "../../ui/icons";
import { MapSettings } from "../../modal/MapSettings";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useTheme } from "../../../hooks/useTheme";
import { useMapRouting } from "../../../hooks/useMapRouting";
import { useFileActions } from "../../../hooks/useFileActions";
import { loadProjectData } from "../../../services/fileSystem";
import { RouteLayer } from "./MapLayers/RouteLayer";

export function MapArea() {
  const { theme, mapTheme } = useTheme();
  const {
    waypoints,
    setWaypoints,
    activeWaypointId,
    settings,
    setIsDirty,
    routePoints,
    drawnRoute,
    setDrawnRoute,
  } = useWorkspace();
  const { importRouteFile } = useFileActions();

  // Overlays & Modes
  const [isHovering, setIsHovering] = useState(false);
  const [isAddMode, setIsAddMode] = useState(false);
  const [isDrawMode, setIsDrawMode] = useState(false);
  const [isProcessing] = useState(false);
  const [uploadedRouteLine, setUploadedRouteLine] = useState<
    [number, number][]
  >([]);

  // Mapbox View State
  const [viewState, setViewState] = useState({
    longitude: settings.start_coords?.[1] || 135.5023,
    latitude: settings.start_coords?.[0] || 34.6937,
    zoom: 13,
  });

  useMapRouting();

  const isDarkMap =
    mapTheme === "dark" ||
    (mapTheme === "sync" &&
      (theme === "dark" ||
        (theme === "system" &&
          window.matchMedia("(prefers-color-scheme: dark)").matches)));

  const mapboxStyle = isDarkMap
    ? "mapbox://styles/mapbox/dark-v11"
    : "mapbox://styles/mapbox/streets-v12";

  const handleMapClick = (e: any) => {
    if (isDrawMode && activeWaypointId) {
      setWaypoints(prev => prev.map(wp => {
        if (wp.id === activeWaypointId) {
          const existing = wp.customRoute || [];
          return { ...wp, routeMode: "draw", customRoute: [...existing, [e.lngLat.lat, e.lngLat.lng]] };
        }
        return wp;
      }));
      setIsDirty(true);
      return;
    }

    if (!isAddMode) return;
    handleAddWaypoint(e.lngLat.lat, e.lngLat.lng);
  };

  const handleMapContextMenu = (e: any) => {
    e.originalEvent.preventDefault();
    if (isDrawMode && activeWaypointId) {
      setWaypoints(prev => prev.map(wp => {
        if (wp.id === activeWaypointId && wp.customRoute?.length) {
          return { ...wp, customRoute: wp.customRoute.slice(0, -1) };
        }
        return wp;
      }));
      return;
    }
    window.dispatchEvent(
      new CustomEvent("open-context-menu", {
        detail: {
          x: e.originalEvent.clientX,
          y: e.originalEvent.clientY,
          type: "map-canvas",
          data: {
            lat: e.lngLat.lat,
            lng: e.lngLat.lng,
            handleAddWaypoint,
          },
        },
      }),
    );
  };

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
        imagePans: [],
        narration: "",
        routeMode: "walking",
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

  // Drag and Drop Listeners
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
          if (
            path.toLowerCase().endsWith(".json") ||
            path.toLowerCase().endsWith(".navivi")
          ) {
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

  const mapboxToken =
    settings?.mapbox_api_key || import.meta.env.VITE_MAPBOX_TOKEN;

  const activeIndex = waypoints.findIndex((w) => w.id === activeWaypointId);
  const activeWp = activeIndex !== -1 ? waypoints[activeIndex] : null;
  const nextWp = activeIndex !== -1 && activeIndex < waypoints.length - 1 ? waypoints[activeIndex + 1] : null;

  return (
    <main className="flex-1 relative bg-zinc-100 dark:bg-[#09090b] overflow-hidden transition-colors">
      <div className="absolute top-4 right-4 z-500 flex items-center gap-2">
        <button
          onClick={() => {
            setIsDrawMode(!isDrawMode);
            if (!isDrawMode) setIsAddMode(false);
          }}
          title="Draw Route"
          className={`flex items-center gap-2 px-4 py-2.5 rounded-full drop-shadow-xl transition-all font-bold text-xs ${isDrawMode ? "bg-navi-600 hover:bg-navi text-white shadow-purple-500/25" : "bg-white dark:bg-zinc-800 text-zinc-700  hover:bg-zinc-200 dark:text-zinc-200 dark:hover:bg-zinc-500"}`}
        >
          <Pencil className="w-3.5 h-3.5" />
        </button>

        <button
          onClick={() => {
            setIsAddMode(!isAddMode);
            if (!isAddMode) setIsDrawMode(false);
          }}
          title="Add Pin"
          className={`flex items-center gap-2 px-4 py-2.5 rounded-full transition-all drop-shadow-xl font-bold text-xs ${isAddMode ? "bg-red-500 hover:bg-red-600 text-white shadow-purple-500/25" : "bg-white dark:bg-zinc-800 text-zinc-700  hover:bg-zinc-200 dark:text-zinc-200 dark:hover:bg-zinc-500"}`}
        >
          <MapPin className="w-3.5 h-3.5" />
        </button>

        <MapSettings />
      </div>
      {isDrawMode && activeWp && nextWp && (
        <div className="absolute top-20 left-1/2 -translate-x-1/2 z-500 bg-zinc-900/95 dark:bg-zinc-100/95 text-white dark:text-zinc-900 px-5 py-2.5 rounded-full shadow-2xl flex items-center gap-3 backdrop-blur-md animate-in slide-in-from-top-4 border border-white/10 dark:border-black/10">
          <span className="flex items-center gap-2 text-[10px] font-black tracking-widest text-amber-400 dark:text-amber-600 uppercase">
              <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
              Layer Active  
          </span>
          <div className="w-px h-4 bg-white/20 dark:bg-black/20" />
          <span className="text-xs font-medium opacity-90 truncate max-w-37.5" title={activeWp.name}>
            {activeWp.name}
          </span>
          <span className="text-xs opacity-50 font-black">→</span>
          <span className="text-xs font-medium opacity-90 truncate max-w-37.5" title={nextWp.name}>
            {nextWp.name}
          </span>
        </div>
      )}
      {/* MAPBOX CANVAS */}
      <div className="absolute inset-0 z-0">
        <Map
          {...viewState}
          onMove={(evt: ViewStateChangeEvent) => setViewState(evt.viewState)}
          onClick={handleMapClick}
          onContextMenu={handleMapContextMenu}
          mapStyle={mapboxStyle}
          mapboxAccessToken={mapboxToken}
          attributionControl={false}
          dragRotate={true}
          doubleClickZoom={!isDrawMode}
        >
          <RouteLayer
            uploadedRouteLine={uploadedRouteLine}
            routePoints={routePoints}
            drawnRoute={drawnRoute}
          />

          {/* TEMP WAYPOINT MARKERS (Until we move them to a separate component if needed) */}
          {waypoints.map((wp, index) => (
            <Marker
              key={wp.id}
              longitude={wp.lng}
              latitude={wp.lat}
              draggable
              onDragEnd={(e) => {
                const { lat, lng } = e.lngLat;
                setWaypoints((prev) =>
                  prev.map((w) => (w.id === wp.id ? { ...w, lat, lng } : w)),
                );
              }}
              anchor="bottom"
            >
              <div className="flex flex-col items-center group cursor-grab active:cursor-grabbing">
                <div className="bg-navi text-white text-[10px] font-bold px-2 py-0.5 rounded shadow-md border border-white/20 mb-1 opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap">
                  {wp.name || `${index + 1}`}
                </div>
                <div className="w-4 h-4 bg-white border-4 border-navi rounded-full shadow-lg" />
                <div className="w-1 h-3 bg-navi/50 rounded-b-full shadow-sm" />
              </div>
            </Marker>
          ))}

          {isDrawMode && activeWaypointId &&
            waypoints.find(w => w.id === activeWaypointId)?.customRoute?.map((pos, idx) => (
              <Marker
                key={`drawn-node-${idx}`}
                latitude={pos[0]}
                longitude={pos[1]}
                draggable
                onDragEnd={(e) => {
                  setWaypoints(prev => prev.map(wp => {
                    if (wp.id === activeWaypointId && wp.customRoute) {
                      const newRoute = [...wp.customRoute];
                      newRoute[idx] = [e.lngLat.lat, e.lngLat.lng];
                      return { ...wp, customRoute: newRoute };
                    }
                    return wp;
                  }));
                  setIsDirty(true);
                }}
              >
                <div className="w-3 h-3 bg-amber-500 border-2 border-white rounded-full shadow-md cursor-grab active:cursor-grabbing hover-scale-125 transition-transform" />
              </Marker>
            ))}
        </Map>
      </div>

      {/* OVERLAYS */}
      {isHovering && (
        <div className="absolute inset-0 z-600 bg-white/80 dark:bg-zinc-950/80 backdrop-blur-sm border-2 border-dashed border-zinc-400 dark:border-zinc-500 m-4 rounded-2xl flex flex-col items-center justify-center transition-all animate-in fade-in">
          <div className="w-16 h-16 rounded-2xl bg-zinc-900 dark:bg-zinc-200 text-zinc-100 dark:text-zinc-900 flex items-center justify-center mb-4 shadow-lg scale-110">
            <UploadCloud className="w-8 h-8" />
          </div>
          <p className="text-zinc-900 dark:text-zinc-200 font-medium text-lg">
            Drop any GPS file to Load
          </p>
        </div>
      )}

      {isProcessing && (
        <div className="absolute inset-0 z-600 bg-white/50 dark:bg-zinc-950/50 backdrop-blur-sm flex flex-col items-center justify-center transition-all animate-in fade-in">
          <div className="w-12 h-12 border-4 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin mb-4" />
          <p className="text-zinc-900 dark:text-zinc-200 font-bold text-sm tracking-widest uppercase">
            Parsing Route Data...
          </p>
        </div>
      )}
    </main>
  );
}
