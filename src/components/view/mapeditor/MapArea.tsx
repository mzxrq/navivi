import { useEffect, useState, useRef } from "react";
import Map, {
  ViewStateChangeEvent,
  Marker,
  MapRef,
  Source,
} from "react-map-gl/mapbox";
import { listen } from "@tauri-apps/api/event";
import { convertFileSrc } from "@tauri-apps/api/core";
import {
  UploadCloud,
  MapPin,
  Pencil,
  SplinePointer,
  Eraser,
  Play,
  MapPinned,
  Square,
  Navigation,
} from "../../ui/icons";
import { mapStyles, mapDefaults } from "../../../config/constants";
import { RouteStyling } from "./MapLayers/RouteStyling";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useTheme } from "../../../hooks/useTheme";
import { useMapRouting } from "../../../hooks/useMapRouting";
import { useFileActions } from "../../../hooks/useFileActions";
import { useUI } from "../../../hooks/useUI";
import { loadProjectData } from "../../../services/fileSystem";
import { MapStyleMenu } from "./MapLayers/MapStyleMenu";
import { RouteLayer } from "./MapLayers/RouteLayer";
import { NaviPin } from "./MapLayers/NaviPin";

export function MapArea() {
  const { theme, mapTheme } = useTheme();
  const { showToast } = useUI();
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
  const [isEraserMode, setIsEraserMode] = useState(false);
  const [addType, setAddType] = useState<"normal" | "start" | "end" | "stopby">(
    "normal",
  );

  const [is3D, setIs3D] = useState(false);
  const [isProcessing] = useState(false);
  const [uploadedRouteLine] = useState<[number, number][]>([]);
  const mapRef = useRef<MapRef>(null);
  const rightClickStartRef = useRef<{ x: number; y: number } | null>(null);

  // Mapbox View State
  const [viewState, setViewState] = useState({
    longitude: settings.start_coords?.[1] || 135.5023,
    latitude: settings.start_coords?.[0] || 34.6937,
    zoom: 13,
    pitch: 0,
    bearing: 0,
  });

  useMapRouting();

  const isDarkMap =
    mapTheme === "dark" ||
    (mapTheme === "sync" &&
      (theme === "dark" ||
        (theme === "system" &&
          window.matchMedia("(prefers-color-scheme: dark)").matches)));

  // Style Switcher
  const [selectedStyle, setSelectedStyle] = useState<string>(() =>
    isDarkMap ? "dark" : "outdoors",
  );

  useEffect(() => {
    const timer = setTimeout(() => {
      mapRef.current?.resize();
    }, 150);
    return () => clearTimeout(timer);
  }, []);

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

  const handleMapContextMenu = (e: any) => {

    if (rightClickStartRef.current) {
      const dx = Math.abs(
        e.originalEvent.clientX - rightClickStartRef.current.x,
      );
      const dy = Math.abs(
        e.originalEvent.clientY - rightClickStartRef.current.y,
      );
      if (dx > 5 || dy > 5) return;
    }

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
    if (waypoints.length >= mapDefaults.maxWaypoints) {
      showToast(
        `Routes are limited to ${mapDefaults.maxWaypoints} waypoints in this preview build.`,
        "warning",
      );
      return;
    }

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
        routeMode: settings.default_route_mode || "driving",
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
      routeMode: settings.default_route_mode || "driving",
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
        routeMode: settings.default_route_mode || "driving",
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
      <div className="absolute top-4 right-4 z-200 flex items-center gap-2">
        {/* --- DRAW TOOLBAR --- */}
        <div
          className={`flex items-center rounded-full drop-shadow-xl transition-all duration-300 ease-out bg-white dark:bg-zinc-800`}
        >
          <div
            className={`flex items-center overflow-hidden transition-all duration-300 ease-out ${isDrawMode ? "max-w-50 opacity-100 px-2" : "max-w-0 opacity-0 px-0"}`}
          >
            <button
              onClick={() => setIsEraserMode(!isEraserMode)}
              title="Erase Anchor"
              className={`p-1.5 transition-colors ${isEraserMode ? "text-red-500 bg-red-50 dark:bg-red-500/20 rounded-md" : "text-zinc-500 hover:text-red-500"}`}
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

        {/* --- WAYPOINT TOOLBAR --- */}
        <div
          className={`flex items-center rounded-full drop-shadow-xl transition-all duration-300 ease-out ${isAddMode ? "bg-white dark:bg-zinc-800" : ""}`}
        >
          <div
            className={`flex items-center overflow-hidden transition-all duration-300 ease-out ${isAddMode ? "max-w-50 opacity-100 px-2" : "max-w-0 opacity-0 px-0"}`}
          >
            <div className="flex items-center gap-1 w-max">
              <button
                onClick={() => setAddType("start")}
                title="Start"
                className={`p-1.5 rounded transition-colors ${addType === "start" ? "bg-emerald-500/20 text-emerald-600 dark:text-emerald-400" : "text-zinc-500 hover:text-zinc-900 dark:hover:text-white"}`}
              >
                <Play className="w-4 h-4" />
              </button>
              <button
                onClick={() => setAddType("normal")}
                title="Node"
                className={`p-1.5 rounded transition-colors ${addType === "normal" ? "bg-blue-500/20 text-blue-600 dark:text-blue-400" : "text-zinc-500 hover:text-zinc-900 dark:hover:text-white"}`}
              >
                <MapPin className="w-4 h-4" />
              </button>
              <button
                onClick={() => setAddType("stopby")}
                title="Stop By"
                className={`p-1.5 rounded transition-colors ${addType === "stopby" ? "bg-amber-500/20 text-amber-600 dark:text-amber-400" : "text-zinc-500 hover:text-zinc-900 dark:hover:text-white"}`}
              >
                <MapPinned className="w-4 h-4" />
              </button>
              <button
                onClick={() => setAddType("end")}
                title="End"
                className={`p-1.5 rounded transition-colors ${addType === "end" ? "bg-red-500/20 text-red-600 dark:text-red-400" : "text-zinc-500 hover:text-zinc-900 dark:hover:text-white"}`}
              >
                <Square className="w-4 h-4" />
              </button>
              <div className="w-px h-4 bg-zinc-200 dark:bg-zinc-700 mx-1" />
            </div>
          </div>

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

        <button
          onClick={() => setIs3D(!is3D)}
          title="Toggle 2D/3D"
          className={`flex items-center justify-center w-10 h-10 rounded-full transition-all font-bold text-xs ${is3D ? "bg-navi hover:bg-navi-600 text-white shadow-md shadow-navi/25" : "bg-white dark:bg-zinc-800 text-zinc-700 hover:bg-zinc-200 dark:text-zinc-200 dark:hover:bg-zinc-500"}`}
        >
          {is3D ? "3D" : "2D"}
        </button>

        <button
          onClick={() => {
            setViewState((prev) => ({
              ...prev,
              pitch: 0,
              bearing: 0,
            }));
          }}
          title="Reset View (North)"
          className="flex items-center justify-center w-10 h-10 rounded-full bg-white dark:bg-zinc-800 text-zinc-700 hover:bg-zinc-200 dark:text-zinc-200 dark:hover:bg-zinc-500 transition-all font-bold"
        >
          <Navigation
            className="w-4 h-4 transition-transform duration-200"
            style={{ transform: `rotate(${-viewState.bearing}deg)` }}
          />
        </button>

        <RouteStyling />

        <MapStyleMenu
          selectedStyle={selectedStyle}
          setSelectedStyle={setSelectedStyle}
          mapboxToken={mapboxToken}
        />
      </div>

      {isDrawMode && activeWp && nextWp && (
        <div className="absolute top-4 left-5 -translate-x-1 z-250 dark:bg-zinc-900/95 bg-zinc-100/95 dark:text-white text-zinc-900 px-4 py-2 rounded-2xl md:rounded-full shadow-2xl flex items-center gap-3 backdrop-blur-md animate-in slide-in-from-top-4 border border-white/10 dark:border-black/10 flex-wrap max-w-[60vw]">
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

          {/* RETRACE TRAIL SELECTOR */}
          <div className="w-px h-4 bg-white/20 dark:bg-black/20 ml-2" />
          <div className="relative group">
            <button
              className="ml-1 px-3 py-1 bg-white/10 hover:bg-white/20 dark:bg-black/10 dark:hover:bg-black/20 rounded text-[10px] font-bold uppercase tracking-wider transition-colors flex items-center gap-1"
              title="Copy a trail from another waypoint"
            >
              Copy Trail ▾
            </button>
            <div className="absolute right-0 top-full mt-2 w-48 bg-white dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-xl shadow-xl py-1.5 z-50 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all">
              <div className="px-3 py-1.5 text-[10px] font-bold text-zinc-500 uppercase tracking-wider border-b border-zinc-100 dark:border-white/5 mb-1">
                Select Layer to Copy
              </div>
              <div className="max-h-40 overflow-y-auto custom-scrollbar">
                {waypoints.filter(w => w.id !== activeWp.id && w.customRoute && w.customRoute.length > 0).length === 0 ? (
                  <div className="px-4 py-2 text-xs text-zinc-500 italic">No drawn trails found</div>
                ) : (
                  waypoints.filter(w => w.id !== activeWp.id && w.customRoute && w.customRoute.length > 0).map(w => (
                    <button
                      key={w.id}
                      onClick={() => {
                        if (w.customRoute) {
                          const routeCopy = [...w.customRoute];
                          updateWaypoint(activeWp.id, {
                            customRoute: routeCopy,
                            routeMode: "draw",
                          });
                          setIsDirty(true);
                        }
                      }}
                      className="w-full text-left px-4 py-2 text-xs font-semibold text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-navidark-600 truncate"
                    >
                      {w.name || "Waypoint"}
                    </button>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* MAPBOX CANVAS */}
      <div className="absolute inset-0 z-0">
        <Map
          ref={mapRef}
          cursor={isEraserMode ? 'crosshair' : ''}
          {...viewState}
          onMove={(evt: ViewStateChangeEvent) => setViewState(evt.viewState)}
          onClick={handleMapClick}
          onContextMenu={handleMapContextMenu}
          onMouseDown={(e) => {
            if (e.originalEvent.button === 2) {
              rightClickStartRef.current = {
                x: e.originalEvent.clientX,
                y: e.originalEvent.clientY,
              };
            }
          }}
          mapStyle={
            mapStyles.find((s) => s.id === selectedStyle)?.url ||
            mapStyles[0].url
          }
          mapboxAccessToken={mapboxToken}
          attributionControl={false}
          dragRotate={true}
          doubleClickZoom={!isDrawMode}
          terrain={is3D ? { source: "mapbox-dem", exaggeration: 1.5 } : undefined}
        >
          <Source
            id="mapbox-dem"
            type="raster-dem"
            url="mapbox://mapbox.mapbox-terrain-dem-v1"
            tileSize={512}
            maxzoom={14}
          />

          <RouteLayer
            uploadedRouteLine={uploadedRouteLine}
            routePoints={routePoints}
          />

          {waypoints.map((wp, index) => {
            const isStart = index === 0;
            const isEnd =
              index === waypoints.length - 1 && waypoints.length > 1;

            let pinType: "start" | "end" | "stopby" | "normal" = "normal";
            let label = "";

            if (isStart) {
              pinType = "start";
              label = "S";
            } else if (isEnd) {
              pinType = "end";
              label = "E";
            } else if (wp.isStopBy) {
              pinType = "stopby";
              let stopByIndex = 0;
              for (let i = index; i >= 0; i--) {
                if (waypoints[i].isStopBy) stopByIndex++;
                else break;
              }
              label = `+${stopByIndex}`;
            } else {
              let normalIndex = 1;
              for (let i = 1; i < index; i++) {
                if (!waypoints[i].isStopBy) normalIndex++;
              }
              label = normalIndex.toString();
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
                    {wp.customMarker || settings.routeMarker ? (
                      <img
                        src={
                          (wp.customMarker || settings.routeMarker)?.startsWith(
                            "/",
                          ) ||
                          (wp.customMarker || settings.routeMarker)?.match(
                            /^[a-zA-Z]:\\/,
                          )
                            ? convertFileSrc(
                                wp.customMarker || settings.routeMarker || "",
                              )
                            : wp.customMarker || settings.routeMarker
                        }
                        alt="Custom Marker"
                        className="w-10 h-10 object-contain drop-shadow-xl"
                      />
                    ) : (
                      <NaviPin
                        className="w-8 h-8"
                        label={label}
                        pinType="stopby"
                      />
                    )}
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

                  {wp.customMarker || settings.routeMarker ? (
                    <img
                      src={
                        (wp.customMarker || settings.routeMarker)?.startsWith(
                          "/",
                        ) ||
                        (wp.customMarker || settings.routeMarker)?.match(
                          /^[a-zA-Z]:\\/,
                        )
                          ? convertFileSrc(
                              wp.customMarker || settings.routeMarker || "",
                            )
                          : wp.customMarker || settings.routeMarker
                      }
                      alt="Custom Marker"
                      className="w-10 h-10 object-contain drop-shadow-xl"
                    />
                  ) : (
                    <NaviPin label={label} pinType={pinType} color={settings.marker_color ? "#" + settings.marker_color.map((x: number) => x.toString(16).padStart(2, "0")).join("") : undefined} />
                  )}
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
                  draggable={!isEraserMode}
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
                  <div 
                    className={`relative group ${isEraserMode ? 'cursor-crosshair' : 'cursor-grab active:cursor-grabbing'}`}
                    onClick={(e) => {
                      if (isEraserMode) {
                        e.stopPropagation();
                        setWaypoints((prev) =>
                          prev.map((wp) => {
                            if (wp.id === activeWaypointId && wp.customRoute) {
                              const newRoute = wp.customRoute.filter((_, i) => i !== idx);
                              return { ...wp, customRoute: newRoute };
                            }
                            return wp;
                          }),
                        );
                        setIsDirty(true);
                      }
                    }}
                  >
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
