import { useEffect, useState, useRef } from "react";
import Map, { ViewStateChangeEvent, Marker, MapRef } from "react-map-gl/mapbox";
import { listen } from "@tauri-apps/api/event";
import {
  UploadCloud,
  MapPin,
  Pencil,
  SplinePointer,
  Undo,
  Eraser,
} from "../../ui/icons";
import { RouteStyling } from "./MapLayers/RouteStyling";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useTheme } from "../../../hooks/useTheme";
import { useMapRouting } from "../../../hooks/useMapRouting";
import { useFileActions } from "../../../hooks/useFileActions";
import { loadProjectData } from "../../../services/fileSystem";
import { RouteLayer } from "./MapLayers/RouteLayer";
import { NaviPin } from "./MapLayers/NaviPin";

export function MapArea() {
  const { theme, mapTheme } = useTheme();
  const {
    waypoints,
    setWaypoints,
    activeWaypointId,
    settings,
    setIsDirty,
    routePoints,
    updateWaypoint,
    setActiveWaypointId,
  } = useWorkspace();
  const { importRouteFile } = useFileActions();

  // Overlays & Modes
  const [isHovering, setIsHovering] = useState(false);
  const [isAddMode, setIsAddMode] = useState(false);
  const [isDrawMode, setIsDrawMode] = useState(false);
  const [addType, setAddType] = useState<"normal" | "start" | "end" | "stopby">(
    "normal",
  );

  const [isProcessing] = useState(false);
  const [uploadedRouteLine] = useState<[number, number][]>([]);
  const mapRef = useRef<MapRef>(null);
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

  useEffect(() => {
    const timer = setTimeout(() => {
      mapRef.current?.resize();
    }, 150);
    return () => clearTimeout(timer);
  }, []);

  const mapboxStyle = isDarkMap
    ? "mapbox://styles/mapbox/dark-v11"
    : "mapbox://styles/mapbox/streets-v12";

  const handleMapClick = (e: any) => {
    if (isDrawMode && activeWaypointId) {
      setWaypoints((prev) =>
        prev.map((wp) => {
          if (wp.id === activeWaypointId) {
            const existing = wp.customRoute || [];
            return {
              ...wp,
              routeMode: "draw",
              customRoute: [...existing, [e.lngLat.lat, e.lngLat.lng]],
            };
          }
          return wp;
        }),
      );
      setIsDirty(true);
      return;
    }

    if (!isAddMode) return;

    if (addType === "start") {
      handleAddSpWaypoint(e.lngLat.lat, e.lngLat.lng, "start");
    } else if (addType === "end") {
      handleAddSpWaypoint(e.lngLat.lat, e.lngLat.lng, "end");
    } else if (addType === "stopby") {
      handleAddStopByWaypoint(e.lngLat.lat, e.lngLat.lng);
    } else {
      handleAddWaypoint(e.lngLat.lat, e.lngLat.lng);
    }
  };

  const handleUndoDraw = () => {
    if (!activeWaypointId) return;
    setWaypoints((prev) =>
      prev.map((wp) => {
        if (wp.id === activeWaypointId && wp.customRoute?.length) {
          return { ...wp, customRoute: wp.customRoute.slice(0, -1) };
        }
        return wp;
      }),
    );
  };

  const handleClearDraw = () => {
    if (!activeWaypointId) return;
    setWaypoints((prev) =>
      prev.map((wp) =>
        wp.id === activeWaypointId ? { ...wp, customRoute: [] } : wp,
      ),
    );
  };

  const handleMapContextMenu = (e: any) => {
    e.originalEvent.preventDefault();
    e.originalEvent.stopPropagation();

    // context menu payload
    window.dispatchEvent(
      new CustomEvent("open-context-menu", {
        detail: {
          x: e.originalEvent.clientX,
          y: e.originalEvent.clientY,
          type: "map-canvas",
          data: {
            lat: e.lngLat.lat,
            lng: e.lngLat.lng,
            setAsStart: () =>
              handleAddSpWaypoint(e.lngLat.lat, e.lngLat.lng, "start"),
            setAsDestination: () =>
              handleAddSpWaypoint(e.lngLat.lat, e.lngLat.lng, "end"),
            setAsStopBy: () =>
              handleAddStopByWaypoint(e.lngLat.lat, e.lngLat.lng),
            addWaypoint: () => handleAddWaypoint(e.lngLat.lat, e.lngLat.lng),
          },
        },
      }),
    );
  };

  const handleMarkerContextMenu = (e: React.MouseEvent, wpId: string) => {
    e.preventDefault();
    e.stopPropagation();

    window.dispatchEvent(
      new CustomEvent("open-context-menu", {
        detail: {
          x: e.clientX,
          y: e.clientY,
          type: "waypoint-marker",
          targetId: wpId,
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

  const handleAddSpWaypoint = async (
    lat: number,
    lng: number,
    position: "start" | "end",
  ) => {
    const newId = Math.random().toString(36).substring(7);
    const newWp = {
      id: newId,
      lat,
      lng,
      name: "Locating...",
      images: [],
      imagePans: [],
      narration: "",
      routeMode: "driving",
    };

    setWaypoints((prev) => {
      if (position === "start") return [newWp as any, ...prev];
      return [...prev, newWp as any];
    });
    setIsDirty(true);

    try {
      const res = await fetch(
        `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}`,
      );
      const data = await res.json();
      const placeName =
        data.name || data.address?.road || data.address?.city || `Waypoint`;
      setWaypoints((prev) =>
        prev.map((wp) => (wp.id === newId ? { ...wp, name: placeName } : wp)),
      );
    } catch {
      setWaypoints((prev) =>
        prev.map((wp) =>
          wp.id === newId ? { ...wp, name: `Unknown Location` } : wp,
        ),
      );
    }
  };

  const handleAddStopByWaypoint = async (lat: number, lng: number) => {
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
        isStopBy: true,
      },
    ]);
    setIsDirty(true);

    try {
      const res = await fetch(
        `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}`,
      );
      const data = await res.json();
      const placeName =
        data.name || data.address?.road || data.address?.city || `Stop By`;
      setWaypoints((prev) =>
        prev.map((wp) => (wp.id === newId ? { ...wp, name: placeName } : wp)),
      );
    } catch {
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
  const nextWp =
    activeIndex !== -1 && activeIndex < waypoints.length - 1
      ? waypoints[activeIndex + 1]
      : null;

  return (
    <main className="flex-1 relative bg-zinc-100 dark:bg-[#09090b] overflow-hidden transition-colors">
      <div className="absolute top-4 right-4 z-500 flex items-center gap-2">
        {/* --- DRAW TOOLBAR --- */}
        <div
          className={`flex items-center rounded-full drop-shadow-xl transition-all duration-300 ease-out bg-white dark:bg-zinc-800`}
        >
          <div
            className={`flex items-center overflow-hidden transition-all duration-300 ease-out ${isDrawMode ? "max-w-50 opacity-100 px-2" : "max-w-0 opacity-0 px-0"}`}
          >
            <button
              onClick={handleUndoDraw}
              title="Undo Last Point"
              className="p-1.5 text-zinc-500 hover:text-zinc-900 dark:hover:text-white transition-colors"
            >
              <Undo className="w-4 h-4" />
            </button>
            <button
              onClick={handleClearDraw}
              title="Clear Route"
              className="p-1.5 text-zinc-500 hover:text-red-500 transition-colors"
            >
              <Eraser className="w-4 h-4" />
            </button>
            <div className="w-px h-4 bg-zinc-200 dark:bg-zinc-700 mx-1" />
            <button
              onClick={() =>
                activeWp &&
                updateWaypoint(activeWp.id, {
                  drawStyle:
                    activeWp.drawStyle === "spline" ? "linear" : "spline",
                })
              }
              title="Toggle Smooth Turf Spline"
              className={`p-1.5 transition-colors ${activeWp?.drawStyle === "spline" ? "text-amber-500" : "text-zinc-500 hover:text-zinc-900 dark:hover:text-white"}`}
            >
              <SplinePointer className="w-4 h-4" />
            </button>
          </div>

          <button
            onClick={() => {
              const nextState = !isDrawMode;
              setIsDrawMode(nextState);
              if (nextState) {
                setIsAddMode(false);
                if (!activeWaypointId && waypoints.length >= 2) {
                  setActiveWaypointId(waypoints[waypoints.length - 2].id);
                }
              }
            }}
            title="Draw Custom Route"
            className={`flex items-center justify-center w-10 h-10 rounded-full transition-colors ${isDrawMode ? "bg-navi-600 text-white" : "text-zinc-700 dark:text-zinc-200 hover:bg-zinc-200 dark:hover:bg-zinc-700"}`}
          >
            <Pencil className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* --- ✨ NEW: WAYPOINT TOOLBAR --- */}
        <div
          className={`flex items-center rounded-full drop-shadow-xl transition-all duration-300 ease-out ${isAddMode ? "bg-white dark:bg-zinc-800" : ""}`}
        >
          {/* The Expanded Options */}
          <div
            className={`flex items-center overflow-hidden transition-all duration-300 ease-out ${isAddMode ? "max-w-62.5 opacity-100 px-2 gap-1" : "max-w-0 opacity-0 px-0 gap-0"}`}
          >
            <button
              onClick={() => setAddType("start")}
              className={`px-2 py-1 text-[10px] font-bold uppercase tracking-wider rounded transition-colors ${addType === "start" ? "bg-emerald-500/20 text-emerald-600 dark:text-emerald-400" : "text-zinc-500 hover:text-zinc-900 dark:hover:text-white"}`}
            >
              Start
            </button>
            <button
              onClick={() => setAddType("normal")}
              className={`px-2 py-1 text-[10px] font-bold uppercase tracking-wider rounded transition-colors ${addType === "normal" ? "bg-blue-500/20 text-blue-600 dark:text-blue-400" : "text-zinc-500 hover:text-zinc-900 dark:hover:text-white"}`}
            >
              Node
            </button>
            <button
              onClick={() => setAddType("stopby")}
              className={`px-2 py-1 text-[10px] font-bold uppercase tracking-wider rounded transition-colors ${addType === "stopby" ? "bg-amber-500/20 text-amber-600 dark:text-amber-400" : "text-zinc-500 hover:text-zinc-900 dark:hover:text-white"}`}
            >
              Stop By
            </button>
            <button
              onClick={() => setAddType("end")}
              className={`px-2 py-1 text-[10px] font-bold uppercase tracking-wider rounded transition-colors ${addType === "end" ? "bg-red-500/20 text-red-600 dark:text-red-400" : "text-zinc-500 hover:text-zinc-900 dark:hover:text-white"}`}
            >
              End
            </button>
            <div className="w-px h-4 bg-zinc-200 dark:bg-zinc-700 ml-1 mr-1" />
          </div>

          {/* The Main Toggle Button */}
          <button
            onClick={() => {
              setIsAddMode(!isAddMode);
              if (!isAddMode) {
                setIsDrawMode(false);
                setAddType("normal");
              }
            }}
            title="Add Pin"
            className={`flex items-center justify-center w-10 h-10 rounded-full transition-all font-bold ${
              isAddMode
                ? "bg-red-500 hover:bg-red-600 text-white"
                : "bg-white dark:bg-zinc-800 text-zinc-700 hover:bg-zinc-200 dark:text-zinc-200 dark:hover:bg-zinc-500"
            }`}
          >
            <MapPin className="w-3.5 h-3.5" />
          </button>
        </div>

        <RouteStyling />
      </div>

      {isDrawMode && activeWp && nextWp && (
        <div className="absolute top-4 left-5 -translate-x-1 z-250 dark:bg-zinc-900/95 bg-zinc-100/95 dark:text-white text-zinc-900 px-4 py-2 rounded-full shadow-2xl flex items-center gap-3 backdrop-blur-md animate-in slide-in-from-top-4 border border-white/10 dark:border-black/10">
          <span className="flex items-center gap-2 text-[10px] font-black tracking-widest text-amber-400 dark:text-amber-600 uppercase">
            <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
            Active
          </span>
          <div className="w-px h-4 bg-white/20 dark:bg-black/20" />
          <span
            className="text-xs font-medium opacity-90 truncate max-w-37.5"
            title={activeWp.name}
          >
            {activeWp.name}
          </span>
          <span className="text-xs opacity-50 font-black">→</span>
          <span
            className="text-xs font-medium opacity-90 truncate max-w-37.5"
            title={nextWp.name}
          >
            {nextWp.name}
          </span>

          {/* 🛠️ RETRACE PREVIOUS TRAIL BUTTON */}
          {activeIndex > 0 &&
          waypoints[activeIndex - 1]?.customRoute?.length ? (
            <>
              <div className="w-px h-4 bg-white/20 dark:bg-black/20 ml-2" />
              <button
                onClick={() => {
                  const prevRoute = waypoints[activeIndex - 1].customRoute;
                  if (prevRoute) {
                    // Clone and reverse the exact coordinates!
                    const reversed = [...prevRoute].reverse();
                    updateWaypoint(activeWp.id, {
                      customRoute: reversed,
                      routeMode: "draw",
                    });
                    setIsDirty(true);
                  }
                }}
                className="ml-1 px-3 py-1 bg-white/10 hover:bg-white/20 dark:bg-black/10 dark:hover:bg-black/20 rounded text-[10px] font-bold uppercase tracking-wider transition-colors flex items-center gap-1"
                title="Copy and reverse the previous trail"
              >
                Retrace Back
              </button>
            </>
          ) : null}
        </div>
      )}
      {/* MAPBOX CANVAS */}
      <div className="absolute inset-0 z-0">
        <Map
          ref={mapRef}
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
          />

          {waypoints.map((wp, index) => {
            const isStart = index === 0;
            const isEnd =
              index === waypoints.length - 1 && waypoints.length > 1;

            let normalIndex = 1;
            for (let i = 1; i < index; i++) {
              if (!waypoints[i].isStopBy) normalIndex++;
            }

            let pinType: "start" | "end" | "stopby" | "normal" = "normal";
            let label = normalIndex.toString();

            if (isStart) {
              pinType = "start";
              label = "S";
            } else if (isEnd) {
              pinType = "end";
              label = "E";
            }

            if (wp.isStopBy) {
              return (
                <Marker
                  key={wp.id}
                  longitude={wp.lng}
                  latitude={wp.lat}
                  anchor="bottom"
                >
                  <div
                    className="flex flex-col items-center group cursor-grab active:cursor-grabbing hover:-translate-y-1 transition-transform"
                    onContextMenu={(e) => handleMarkerContextMenu(e, wp.id)}
                  >
                    <div className="bg-zinc-900 text-white text-[10px] font-bold px-2 py-0.5 rounded shadow-lg border border-white/20 mb-1 opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap">
                      {wp.name || `Waypoint`}
                    </div>
                    <NaviPin className="w-8 h-8" label="・" pinType="stopby" />
                  </div>
                </Marker>
              );
            }

            return (
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
                <div
                  className="flex flex-col items-center group cursor-grab active:cursor-grabbing hover:-translate-y-1 transition-transform"
                  onContextMenu={(e) => handleMarkerContextMenu(e, wp.id)}
                >
                  <div className="bg-zinc-900 text-white text-[10px] font-bold px-2 py-0.5 rounded shadow-lg border border-white/20 mb-1 opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap">
                    {wp.name || `Waypoint`}
                  </div>

                  <NaviPin label={label} pinType={pinType} />
                </div>
              </Marker>
            );
          })}

          {/* drawn nodes */}
          {isDrawMode &&
            activeWaypointId &&
            waypoints
              .find((w) => w.id === activeWaypointId)
              ?.customRoute?.map((pos, idx) => (
                <Marker
                  key={`drawn-node-${idx}`}
                  latitude={pos[0]}
                  longitude={pos[1]}
                  draggable
                  onDragEnd={(e) => {
                    setWaypoints((prev) =>
                      prev.map((wp) => {
                        if (wp.id === activeWaypointId && wp.customRoute) {
                          const newRoute = [...wp.customRoute];
                          newRoute[idx] = [e.lngLat.lat, e.lngLat.lng];
                          return { ...wp, customRoute: newRoute };
                        }
                        return wp;
                      }),
                    );
                    setIsDirty(true);
                  }}
                >
                  <div className="relative group cursor-grab active:cursor-grabbing">
                    <div className="w-5 h-5 bg-amber-500 border-2 border-white dark:border-zinc-900 rounded-full shadow-md group-hover:scale-110 group-hover:bg-amber-400 transition-all flex items-center justify-center">
                      <span className="text-[9px] font-black text-white dark:text-zinc-900">
                        {idx + 1}
                      </span>
                    </div>
                    <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 opacity-0 group-hover:opacity-100 transition-opacity bg-zinc-900 text-white text-[9px] font-bold px-1.5 py-0.5 rounded pointer-events-none whitespace-nowrap">
                      Anchor {idx + 1}
                    </div>
                  </div>
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
