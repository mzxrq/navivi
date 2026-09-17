import { useEffect, useState, useRef } from "react";
import Map, {
  ViewStateChangeEvent,
  Marker,
  MapRef,
  Source,
  Layer,
} from "react-map-gl/mapbox";
import { listen } from "@tauri-apps/api/event";
import { convertFileSrc } from "@tauri-apps/api/core";
import {
  UploadCloud,
  Navigation,
  ImageIcon,
  ChevronLeft,
  Pencil,
  Layers,
} from "../../../components/ui/icons";
import { ChevronDown, ChevronUp } from "lucide-react";
import { MapToolbar } from "./MapToolbar";
import DrawControl from "./DrawControl";
import "@mapbox/mapbox-gl-draw/dist/mapbox-gl-draw.css";
import { mapStyles, mapDefaults } from "../../../config/constants";
import { RouteStyling } from "./MapLayers/RouteStyling";
import { Rnd } from "react-rnd";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useTheme } from "../../../hooks/useTheme";
import { useMapRouting } from "../hooks/useMapRouting";
import { useFileActions } from "../../../hooks/useFileActions";
import { useUI } from "../../../hooks/useUI";
import { loadProjectData } from "../../../services/fileSystem";
import { WaypointEditor } from "./WaypointEditor";
import { Waypoint } from "../../../types";
import { LayerManager } from "./MapLayers/LayerManager";
import { RouteLayer } from "./MapLayers/RouteLayer";
import { NaviPin } from "./MapLayers/NaviPin";
import { ElevationProfile } from "./ElevationProfile";
import {
  getHistoricalWeather,
  generateMapboxAtmosphereParams,
  WeatherCondition,
} from "../../../services/weatherService";

function RainOverlay() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animId: number;
    let width = (canvas.width =
      canvas.parentElement?.clientWidth || window.innerWidth);
    let height = (canvas.height =
      canvas.parentElement?.clientHeight || window.innerHeight);

    const handleResize = () => {
      if (!canvas) return;
      width = canvas.width =
        canvas.parentElement?.clientWidth || window.innerWidth;
      height = canvas.height =
        canvas.parentElement?.clientHeight || window.innerHeight;
    };
    window.addEventListener("resize", handleResize);

    const dropCount = 120;
    const drops: Array<{
      x: number;
      y: number;
      speed: number;
      length: number;
      opacity: number;
    }> = [];

    for (let i = 0; i < dropCount; i++) {
      drops.push({
        x: Math.random() * width,
        y: Math.random() * height,
        speed: 14 + Math.random() * 10,
        length: 12 + Math.random() * 16,
        opacity: 0.2 + Math.random() * 0.35,
      });
    }

    const render = () => {
      ctx.clearRect(0, 0, width, height);

      for (let i = 0; i < drops.length; i++) {
        const d = drops[i];
        ctx.beginPath();
        ctx.strokeStyle = `rgba(185, 205, 230, ${d.opacity})`;
        ctx.lineWidth = 1.2;
        ctx.lineCap = "round";
        ctx.moveTo(d.x, d.y);
        ctx.lineTo(d.x - 2, d.y + d.length);
        ctx.stroke();

        d.y += d.speed;
        d.x -= 2;

        if (d.y > height) {
          d.y = -d.length;
          d.x = Math.random() * (width + 50);
        }
        if (d.x < -10) {
          d.x = width + 10;
        }
      }

      animId = requestAnimationFrame(render);
    };

    animId = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener("resize", handleResize);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 pointer-events-none z-10 w-full h-full"
    />
  );
}

export function MapArea() {
  const { theme, mapTheme } = useTheme();
  const { showToast, isRendering } = useUI();
  const {
    waypoints,
    setWaypoints,
    activeWaypointId,
    settings,
    setIsDirty,
    routePoints,
    routeSegments,
    updateWaypoint,
    setActiveWaypointId,
    setProjectThumbnail,
  } = useWorkspace();
  const { handleDroppedFiles, importPhotos } = useFileActions();

  // Overlays & Modes
  const [isHovering, setIsHovering] = useState(false);
  const [isAddMode, setIsAddMode] = useState(false);
  const [isDrawMode, setIsDrawMode] = useState(false);
  const [isEraserMode, setIsEraserMode] = useState(false);
  const [isDrawStatusCollapsed, setIsDrawStatusCollapsed] = useState(false);
  const [addType, setAddType] = useState<"normal" | "start" | "end" | "stopby">(
    "normal",
  );

  const [is3D, setIs3D] = useState(false);
  const [isProcessing] = useState(false);
  const [uploadedRouteLine] = useState<[number, number][]>([]);
  const mapRef = useRef<MapRef>(null);
  const thumbnailCaptureTimeoutRef = useRef<ReturnType<
    typeof setTimeout
  > | null>(null);
  const rightClickStartRef = useRef<{ x: number; y: number } | null>(null);

  const [eleHoverPoint, setEleHoverPoint] = useState<number[] | null>(null);
  const [vehicleGeoJson, setVehicleGeoJson] = useState<any>(null);
  const [weatherCondition, setWeatherCondition] =
    useState<WeatherCondition>("clear");

  // Mapbox View State
  const [viewState, setViewState] = useState({
    longitude: settings.start_coords?.[1] || 135.5023,
    latitude: settings.start_coords?.[0] || 34.6937,
    zoom: 13,
    pitch: 0,
    bearing: 0,
  });

  useMapRouting();

  const captureMapThumbnail = () => {
    if (thumbnailCaptureTimeoutRef.current) {
      clearTimeout(thumbnailCaptureTimeoutRef.current);
    }
    thumbnailCaptureTimeoutRef.current = setTimeout(() => {
      const canvas = mapRef.current?.getMap().getCanvas();
      if (!canvas) return;
      try {
        setProjectThumbnail(canvas.toDataURL("image/png"));
      } catch (error) {
        console.warn("Unable to capture map thumbnail:", error);
      }
    }, 250);
  };

  useEffect(() => {
    return () => {
      if (thumbnailCaptureTimeoutRef.current) {
        clearTimeout(thumbnailCaptureTimeoutRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (
      waypoints.length > 0 ||
      routePoints.length > 0 ||
      routeSegments.length > 0
    ) {
      captureMapThumbnail();
    }
  }, [waypoints.length, routePoints.length, routeSegments.length]);

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

  useEffect(() => {
    const handleHover = ((e: CustomEvent) =>
      setEleHoverPoint(e.detail)) as EventListener;
    window.addEventListener("elevation-hover", handleHover);
    return () => window.removeEventListener("elevation-hover", handleHover);
  }, []);

  useEffect(() => {
    const map = mapRef.current?.getMap();
    if (!map) return;
    const loadModels = () => {
      try {
        if (!map.hasModel("car")) map.addModel("car", "/car.glb");
        if (!map.hasModel("airplane"))
          map.addModel("airplane", "/airplane.glb");
      } catch (e) {
        console.warn("Failed to load models", e);
      }
    };
    map.on("style.load", loadModels);
    if (map.isStyleLoaded()) loadModels();

    return () => {
      map.off("style.load", loadModels);
    };
  }, [selectedStyle]);

  // Historical Weather Sync
  useEffect(() => {
    if (!settings.weather_sync_enabled) {
      setWeatherCondition("clear");
      return;
    }

    let isSubscribed = true;
    const targetWp =
      (activeWaypointId
        ? waypoints.find((w) => w.id === activeWaypointId && w.timestamp)
        : null) || waypoints.find((w) => !!w.timestamp);

    if (!targetWp || !targetWp.timestamp) {
      setWeatherCondition("clear");
      return;
    }

    getHistoricalWeather(targetWp.lat, targetWp.lng, targetWp.timestamp)
      .then((condition) => {
        if (isSubscribed) {
          setWeatherCondition(condition);
        }
      })
      .catch(() => {
        if (isSubscribed) {
          setWeatherCondition("clear");
        }
      });

    return () => {
      isSubscribed = false;
    };
  }, [settings.weather_sync_enabled, waypoints, activeWaypointId]);

  // Mapbox Atmosphere & Fog Effect
  useEffect(() => {
    const map = mapRef.current?.getMap();
    if (!map) return;

    const applyAtmosphere = () => {
      try {
        if (settings.weather_sync_enabled) {
          const atmosphere = generateMapboxAtmosphereParams(weatherCondition);
          if (atmosphere.fog) {
            map.setFog(atmosphere.fog as any);
          } else {
            map.setFog(null as any);
          }
        } else {
          map.setFog(null as any);
        }
      } catch (err) {
        console.warn("Failed to apply Mapbox atmosphere:", err);
      }
    };

    map.on("style.load", applyAtmosphere);
    if (map.isStyleLoaded()) {
      applyAtmosphere();
    }

    return () => {
      map.off("style.load", applyAtmosphere);
      try {
        map.setFog(null as any);
      } catch {}
    };
  }, [settings.weather_sync_enabled, weatherCondition, selectedStyle]);

  useEffect(() => {
    if (!isRendering || routePoints.length < 2) {
      setVehicleGeoJson(null);
      return;
    }
    let frameId: number;
    let startTime = performance.now();
    const duration = 10000;

    const animate = (time: number) => {
      let progress = ((time - startTime) % duration) / duration;

      const totalPoints = routePoints.length;
      const exactIndex = progress * (totalPoints - 1);
      const index1 = Math.floor(exactIndex);
      const index2 = Math.min(index1 + 1, totalPoints - 1);
      const frac = exactIndex - index1;

      const p1 = routePoints[index1];
      const p2 = routePoints[index2];
      const lat = p1[0] + (p2[0] - p1[0]) * frac;
      const lng = p1[1] + (p2[1] - p1[1]) * frac;

      const dy = p2[0] - p1[0];
      const dx = p2[1] - p1[1];
      const bearing = (Math.atan2(dx, dy) * 180) / Math.PI || 0;

      setVehicleGeoJson({
        type: "Feature",
        properties: { rotation: [0, 0, bearing], model: "car" },
        geometry: { type: "Point", coordinates: [lng, lat] },
      });

      frameId = requestAnimationFrame(animate);
    };
    frameId = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(frameId);
  }, [isRendering, routePoints]);

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
            await handleDroppedFiles(event.payload.paths);
          }
        }
      },
    );

    return () => {
      unlistenHover.then((f) => f());
      unlistenLeave.then((f) => f());
      unlistenDrop.then((f) => f());
    };
  }, [handleDroppedFiles]);

  const mapboxToken =
    settings?.mapbox_api_key || import.meta.env.VITE_MAPBOX_TOKEN;

  const handleDrawUpdate = (e: { features: any[] }) => {
    if (!e.features || e.features.length === 0) return;

    // Mapbox Draw outputs GeoJSON [lng, lat]
    // We need to convert it back to [lat, lng] for Navivi's customRoute
    const coordinates = e.features[0].geometry.coordinates as [
      number,
      number,
    ][];
    const naviviRoute = coordinates.map(
      (coord) => [coord[1], coord[0]] as [number, number],
    );

    if (activeWaypointId) {
      setWaypoints((prev) =>
        prev.map((wp) => {
          if (wp.id === activeWaypointId) {
            return { ...wp, customRoute: naviviRoute };
          }
          return wp;
        }),
      );
    } else {
      // Create new waypoint if none is selected
      const newId = crypto.randomUUID();
      const newWp: Waypoint = {
        id: newId,
        name: "Custom Route",
        lat: naviviRoute[0][0],
        lng: naviviRoute[0][1],
        customRoute: naviviRoute,
        isStopBy: false,
        routeMode: "driving",
      };
      setWaypoints((prev) => [...prev, newWp]);
      setActiveWaypointId(newId);
      setIsDrawMode(false); // Switch to select mode to prevent accidental subsequent draws
    }
    setIsDirty(true);
  };

  const handleZoomToFit = () => {
    if (!activeWp || !activeWp.customRoute || activeWp.customRoute.length === 0)
      return;
    const lats = activeWp.customRoute.map((c) => c[0]);
    const lngs = activeWp.customRoute.map((c) => c[1]);
    const minLat = Math.min(...lats);
    const maxLat = Math.max(...lats);
    const minLng = Math.min(...lngs);
    const maxLng = Math.max(...lngs);

    mapRef.current?.fitBounds(
      [
        [minLng, minLat],
        [maxLng, maxLat],
      ],
      { padding: 100, duration: 1000 },
    );
  };

  const activeIndex = waypoints.findIndex((w) => w.id === activeWaypointId);
  const activeWp = activeIndex !== -1 ? waypoints[activeIndex] : null;
  const nextWp =
    activeIndex !== -1 && activeIndex < waypoints.length - 1
      ? waypoints[activeIndex + 1]
      : null;

  return (
    <main className="flex-1 relative bg-zinc-100 dark:bg-[#09090b] overflow-hidden transition-colors">
      {/* --- GEOJSON.IO STYLE TOP TOOLBAR --- */}
      <div className="absolute top-4 left-1/2 -translate-x-1/2 z-200">
        <MapToolbar
          isAddMode={isAddMode}
          setIsAddMode={setIsAddMode}
          isDrawMode={isDrawMode}
          setIsDrawMode={setIsDrawMode}
          isEraserMode={isEraserMode}
          setIsEraserMode={setIsEraserMode}
          activeWp={activeWp}
          onSimplifyRoute={() => {}}
          onBufferRoute={() => {}}
          onShowInfo={() => {}}
          onToggleSpline={() => {
            if (activeWp) {
              updateWaypoint(activeWp.id, {
                drawStyle:
                  activeWp.drawStyle === "spline" ? "linear" : "spline",
              });
            }
          }}
          onZoomTo={handleZoomToFit}
          onClearRoute={() => {
            if (activeWp) {
              updateWaypoint(activeWp.id, { customRoute: [] });
            }
          }}
        />
      </div>

      <div className="absolute top-4 right-4 z-200 flex items-center gap-2">
        <button
          onClick={() => {
            setViewState((prev) => ({
              ...prev,
              pitch: 0,
              bearing: 0,
            }));
          }}
          title="Reset View (North)"
          className="flex items-center justify-center w-10 h-10 rounded-full bg-white dark:bg-zinc-800 text-zinc-700 hover:bg-zinc-200 dark:text-zinc-200 dark:hover:bg-zinc-500 transition-all font-bold drop-shadow-md shadow-md"
        >
          <Navigation
            className="w-4 h-4 transition-transform duration-200"
            style={{ transform: `rotate(${-viewState.bearing}deg)` }}
          />
        </button>

        <RouteStyling />

        <LayerManager
          selectedStyle={selectedStyle}
          setSelectedStyle={setSelectedStyle}
          mapboxToken={mapboxToken}
          is3D={is3D}
          setIs3D={setIs3D}
        />
      </div>

      {/* UNIFIED DRAGGABLE DRAW STATUS & ANCHORS LAYER PANEL */}
      {isDrawMode && activeWp && nextWp && (
        <Rnd
          key="anchors-layer-panel"
          default={{
            x: Math.max(10, window.innerWidth - 660),
            y: 80,
            width: 320,
            height: "auto",
          }}
          enableResizing={false}
          minWidth={250}
          bounds="parent"
          dragHandleClassName="anchors-drag-handle"
          style={{ zIndex: 300 }}
        >
          <div className="w-full bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xl border border-zinc-200 dark:border-zinc-700 rounded-xl shadow-2xl flex flex-col overflow-hidden pointer-events-auto transition-all duration-300 ease-in-out">
            <div className="anchors-drag-handle px-3 py-2 bg-zinc-100/50 dark:bg-zinc-800/50 border-b border-zinc-200 dark:border-zinc-700 flex justify-between items-center cursor-move group">
              <div className="flex items-center gap-2 overflow-hidden pr-2">
                <span
                  className="text-xs font-bold text-zinc-700 dark:text-zinc-300 truncate max-w-24"
                  title={activeWp.name}
                >
                  {activeWp.name}
                </span>
                <span className="text-xs opacity-50 font-black shrink-0">
                  ↁE
                </span>
                <span
                  className="text-xs font-bold text-zinc-700 dark:text-zinc-300 truncate max-w-24"
                  title={nextWp.name}
                >
                  {nextWp.name}
                </span>
                <span className="text-[10px] font-bold text-zinc-500 bg-black/5 dark:bg-white/10 px-1.5 py-0.5 rounded shrink-0">
                  {activeWp.customRoute?.length || 0}
                </span>

                <div className="w-px h-4 bg-black/10 dark:bg-white/20 ml-1 shrink-0" />
                <div className="relative group/copy">
                  <button
                    className="px-2 py-1 bg-black/5 hover:bg-black/10 dark:bg-white/10 dark:hover:bg-white/20 rounded text-[10px] font-bold uppercase tracking-wider transition-colors flex items-center gap-1 shrink-0"
                    title="Copy a trail from another waypoint"
                  >
                    Copy
                  </button>
                  <div className="absolute left-0 top-full mt-2 w-48 bg-white dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-xl shadow-xl py-1.5 z-50 opacity-0 invisible group-hover/copy:opacity-100 group-hover/copy:visible transition-all">
                    <div className="px-3 py-1.5 text-[10px] font-bold text-zinc-500 uppercase tracking-wider border-b border-zinc-100 dark:border-white/5 mb-1">
                      Select Layer to Copy
                    </div>
                    <div className="max-h-40 overflow-y-auto custom-scrollbar">
                      {waypoints.filter(
                        (w) =>
                          w.id !== activeWp.id &&
                          w.customRoute &&
                          w.customRoute.length > 0,
                      ).length === 0 ? (
                        <div className="px-4 py-2 text-xs text-zinc-500 italic">
                          No drawn trails found
                        </div>
                      ) : (
                        waypoints
                          .filter(
                            (w) =>
                              w.id !== activeWp.id &&
                              w.customRoute &&
                              w.customRoute.length > 0,
                          )
                          .map((w) => (
                            <button
                              key={w.id}
                              onClick={() => {
                                if (w.customRoute) {
                                  updateWaypoint(activeWp.id, {
                                    customRoute: [...w.customRoute],
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
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setIsDrawStatusCollapsed(!isDrawStatusCollapsed);
                }}
                className="p-1 hover:bg-black/10 dark:hover:bg-white/10 rounded text-zinc-500 shrink-0"
              >
                {isDrawStatusCollapsed ? (
                  <ChevronDown className="w-4 h-4" />
                ) : (
                  <ChevronUp className="w-4 h-4" />
                )}
              </button>
            </div>

            {!isDrawStatusCollapsed && (
              <div className="flex-1 overflow-y-auto custom-scrollbar flex flex-col p-1 max-h-100">
                {!activeWp.customRoute || activeWp.customRoute.length === 0 ? (
                  <div className="px-4 py-3 text-xs text-zinc-500 italic text-center">
                    No anchors drawn yet
                  </div>
                ) : (
                  activeWp.customRoute.map((anchor, idx) => (
                    <div
                      key={`anchor-mgr-${idx}`}
                      className="flex items-center justify-between p-1 hover:bg-zinc-100 dark:hover:bg-zinc-700 rounded group/anchor"
                    >
                      <div className="flex items-center gap-2">
                        <div className="w-5 h-5 rounded-full bg-amber-500/20 text-amber-600 dark:text-amber-400 flex items-center justify-center text-[10px] font-black shrink-0">
                          {idx + 1}
                        </div>
                        <span className="text-xs text-zinc-700 dark:text-zinc-300 font-mono truncate">
                          {anchor[0].toFixed(5)}, {anchor[1].toFixed(5)}
                        </span>
                      </div>
                      <div className="flex items-center gap-1 opacity-0 group-hover/anchor:opacity-100 transition-opacity">
                        <button
                          disabled={idx === 0}
                          onClick={() => {
                            const newRoute = [...activeWp.customRoute!];
                            [newRoute[idx - 1], newRoute[idx]] = [
                              newRoute[idx],
                              newRoute[idx - 1],
                            ];
                            updateWaypoint(activeWp.id, {
                              customRoute: newRoute,
                            });
                            setIsDirty(true);
                          }}
                          className="p-1 hover:bg-zinc-200 dark:hover:bg-zinc-600 rounded text-zinc-500 disabled:opacity-30"
                          title="Move Up"
                        >
                          Up
                        </button>
                        <button
                          disabled={idx === (activeWp.customRoute?.length ?? 0) - 1}
                          onClick={() => {
                            const newRoute = [...activeWp.customRoute!];
                            [newRoute[idx + 1], newRoute[idx]] = [
                              newRoute[idx],
                              newRoute[idx + 1],
                            ];
                            updateWaypoint(activeWp.id, {
                              customRoute: newRoute,
                            });
                            setIsDirty(true);
                          }}
                          className="p-1 hover:bg-zinc-200 dark:hover:bg-zinc-600 rounded text-zinc-500 disabled:opacity-30"
                          title="Move Down"
                        >
                          Dn
                        </button>
                        <button
                          onClick={() => {
                            const newRoute = [...activeWp.customRoute!];
                            newRoute.splice(idx, 1);
                            updateWaypoint(activeWp.id, {
                              customRoute: newRoute,
                            });
                            setIsDirty(true);
                          }}
                          className="p-1 hover:bg-red-100 dark:hover:bg-red-500/20 hover:text-red-500 rounded text-zinc-500"
                          title="Delete Anchor"
                        >
                          X
                        </button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        </Rnd>
      )}

      {/* MAPBOX CANVAS */}
      <div className="absolute inset-0 z-0">
        <Map
          ref={mapRef}
          preserveDrawingBuffer
          cursor={isEraserMode ? "crosshair" : ""}
          {...viewState}
          onMove={(evt: ViewStateChangeEvent) => setViewState(evt.viewState)}
          onLoad={captureMapThumbnail}
          onMoveEnd={captureMapThumbnail}
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
          terrain={
            is3D ? { source: "mapbox-dem", exaggeration: 1.5 } : undefined
          }
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
                    <NaviPin
                      label={label}
                      pinType={pinType}
                      color={
                        settings.marker_color
                          ? "#" +
                            settings.marker_color
                              .map((x: number) =>
                                x.toString(16).padStart(2, "0"),
                              )
                              .join("")
                          : undefined
                      }
                    />
                  )}
                </div>
              </Marker>
            );
          })}
        </Map>

        {/* HISTORICAL WEATHER RAIN OVERLAY */}
        {settings.weather_sync_enabled && weatherCondition === "rain" && (
          <RainOverlay />
        )}
      </div>

      <ElevationProfile />

      {/* OVERLAYS */}
      {waypoints.length === 0 && !isHovering && (
        <div className="absolute inset-0 z-10 flex items-center justify-center pointer-events-none p-6">
          <div className="pointer-events-auto bg-white/90 dark:bg-navidark-800/90 backdrop-blur-md border-2 border-dashed border-zinc-300 dark:border-white/15 rounded-2xl p-8 max-w-md w-full text-center shadow-xl flex flex-col items-center gap-3 transition-all animate-in fade-in zoom-in-95">
            <div className="w-12 h-12 rounded-xl bg-navi/10 text-navi flex items-center justify-center">
              <ImageIcon className="w-6 h-6" />
            </div>
            <h3 className="text-sm font-bold text-zinc-900 dark:text-white">
              Drop photos here to auto-plot your route
            </h3>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 max-w-xs leading-relaxed">
              EXIF GPS tags from your travel photos will automatically generate
              sequenced stops on the map.
            </p>
            <button
              onClick={importPhotos}
              className="mt-1 px-3.5 py-1.5 bg-navi hover:bg-navi-600 text-white rounded-lg text-xs font-semibold shadow-sm transition-colors flex items-center gap-1.5"
            >
              <ImageIcon className="w-3.5 h-3.5" />
              Select Photos...
            </button>
          </div>
        </div>
      )}

      {isHovering && (
        <div className="absolute inset-0 z-600 bg-white/80 dark:bg-zinc-950/80 backdrop-blur-sm border-2 border-dashed border-zinc-400 dark:border-zinc-500 m-4 rounded-2xl flex flex-col items-center justify-center transition-all animate-in fade-in">
          <div className="w-16 h-16 rounded-2xl bg-zinc-900 dark:bg-zinc-200 text-zinc-100 dark:text-zinc-900 flex items-center justify-center mb-4 shadow-lg scale-110">
            <UploadCloud className="w-8 h-8" />
          </div>
          <p className="text-zinc-900 dark:text-zinc-200 font-medium text-lg">
            Drop photos or GPS files to plot route
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
      {/* --- FLOATING WAYPOINT EDITOR --- */}
      {activeWaypointId && !isDrawMode && !isAddMode && (
        <Rnd
          default={{
            x: window.innerWidth > 1000 ? (window.innerWidth - 800) / 2 : 390,
            y: window.innerHeight - 420,
            width: "min(800px, calc(100vw - 420px))",
            height: 400,
          }}
          bounds="parent"
          enableResizing={false}
          dragHandleClassName="editor-drag-handle"
          className="z-50"
        >
          <div className="w-full h-full pointer-events-auto">
            <WaypointEditor
              wpId={activeWaypointId}
              onClose={() => setActiveWaypointId(null)}
            />
          </div>
        </Rnd>
      )}
    </main>
  );
}
