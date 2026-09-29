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
  Navigation,
  ImageIcon,
  X
} from "../../../components/ui/icons";
import { MapToolbar } from "./MapToolbar";
import "@mapbox/mapbox-gl-draw/dist/mapbox-gl-draw.css";
import { mapStyles, mapDefaults } from "../../../config/constants";
import { RouteStyling } from "./MapLayers/RouteStyling";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useTheme } from "../../../hooks/useTheme";
import { useMapRouting } from "../hooks/useMapRouting";
import { useFileActions } from "../../../hooks/useFileActions";
import { useUI } from "../../../hooks/useUI";
import { loadProjectData } from "../../../services/fileSystem";
import { WaypointEditor } from "./WaypointEditor";
import { UnifiedLayersPanel } from "./UnifiedLayersPanel";
import { Waypoint } from "../../../types";
import { LayerManager } from "./MapLayers/LayerManager";
import { RouteLayer } from "./MapLayers/RouteLayer";
import { RainOverlay } from "./MapLayers/RainOverlay";
import { NaviPin } from "./MapLayers/NaviPin";
import { ElevationProfile } from "./ElevationProfile";
import {
  getHistoricalWeather,
  generateMapboxAtmosphereParams,
  WeatherCondition,
} from "../../../services/weatherService";
import { t } from "@lingui/core/macro";
import { useLingui } from "@lingui/react";
import { Trans } from "@lingui/react/macro";

export function MapArea() {
  const { i18n } = useLingui();
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
    registerThumbnailGetter,
  } = useWorkspace();
  const { handleDroppedFiles, importPhotos } = useFileActions();

  const [isHovering, setIsHovering] = useState(false);
  const [isAddMode, setIsAddMode] = useState(false);
  const [isDrawMode, setIsDrawMode] = useState(false);
  const [isEraserMode, setIsEraserMode] = useState(false);
  const [isViaMode, setIsViaMode] = useState(false);
  const viaTargetWpIdRef = useRef<string | null>(null);
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
  const isContextLostRef = useRef(false);

  const [eleHoverPoint, setEleHoverPoint] = useState<number[] | null>(null);
  const [vehicleGeoJson, setVehicleGeoJson] = useState<any>(null);
  const [weatherCondition, setWeatherCondition] =
    useState<WeatherCondition>("clear");

  const [viewState, setViewState] = useState({
    longitude: settings.start_coords?.[1] || 135.5023,
    latitude: settings.start_coords?.[0] || 34.6937,
    zoom: 13,
    pitch: 0,
    bearing: 0,
  });


  useMapRouting();

  useEffect(() => {
    registerThumbnailGetter(() => {
      if (isContextLostRef.current) return null;
      try {
        const canvas = mapRef.current?.getMap().getCanvas();
        return canvas ? canvas.toDataURL("image/png") : null;
      } catch (e) {
        return null;
      }
    });
  }, [registerThumbnailGetter]);

  const captureMapThumbnail = () => {
    if (isContextLostRef.current) return;
    if (thumbnailCaptureTimeoutRef.current) {
      clearTimeout(thumbnailCaptureTimeoutRef.current);
    }
    thumbnailCaptureTimeoutRef.current = setTimeout(() => {
      if (isContextLostRef.current) return;
      const canvas = mapRef.current?.getMap().getCanvas();
      if (!canvas) return;
      try {
        setProjectThumbnail(canvas.toDataURL("image/png"));
      } catch (error) {
        console.warn("Unable to capture map thumbnail:", error);
      }
    }, 250);
  };

  // Called by <Map onLoad>: canvas now exists, safe to attach WebGL handlers
  const handleMapLoad = () => {
    const map = mapRef.current?.getMap();
    if (!map) return;

    const canvas = map.getCanvas();

    try {
      if (typeof map.setLanguage === "function") {
        map.setLanguage(i18n.locale);
      }
    } catch (e) {}


    // Prevent the browser from discarding the context silently
    const handleContextLost = (e: Event) => {
      e.preventDefault();
      isContextLostRef.current = true;
      console.warn("[Navivi] WebGL context lost – pausing map operations.");
    };
    const handleContextRestored = () => {
      isContextLostRef.current = false;
      console.info("[Navivi] WebGL context restored.");
    };
    canvas.addEventListener("webglcontextlost", handleContextLost);
    canvas.addEventListener("webglcontextrestored", handleContextRestored);

    // Suppress Mapbox-internal "object does not belong to this context" errors
    // that fire during style reloads — they are benign and self-resolving
    map.on("error", (e: any) => {
      const msg: string = e?.error?.message ?? "";
      if (
        msg.includes("does not belong to this context") ||
        msg.includes("deleteVertexArray") ||
        msg.includes("INVALID_OPERATION")
      ) {
        // swallow — Mapbox recovers on its own after a style reload
        return;
      }
      console.error("[Navivi] Mapbox error:", e);
    });

    captureMapThumbnail();

    // Auto-fit bounds if we have existing waypoints
    if (waypoints.length > 0) {
      let minLng = Infinity;
      let minLat = Infinity;
      let maxLng = -Infinity;
      let maxLat = -Infinity;

      waypoints.forEach((wp) => {
        minLng = Math.min(minLng, wp.lng);
        minLat = Math.min(minLat, wp.lat);
        maxLng = Math.max(maxLng, wp.lng);
        maxLat = Math.max(maxLat, wp.lat);
      });



      if (minLng !== Infinity) {
        if (minLng === maxLng && minLat === maxLat) {
          map.flyTo({ center: [minLng, minLat], zoom: 14, duration: 1000 });
        } else {
          map.fitBounds(
            [
              [minLng, minLat],
              [maxLng, maxLat],
            ],
            { padding: 80, duration: 1000 },
          );
        }
      }
    }
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

  const [selectedStyle, setSelectedStyle] = useState<string>(() =>
    isDarkMap ? "dark" : "outdoors",
  );

  // Mapbox UI/Label Localization
  useEffect(() => {
    const map = mapRef.current?.getMap();
    if (!map) return;
    try {
      if (typeof map.setLanguage === "function") {
        map.setLanguage(i18n.locale);
      }
    } catch (e) {
      console.warn("[Navivi] Could not set map language:", e);
    }
  }, [i18n.locale, selectedStyle, mapRef.current]);


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
            let newRoute = [...existing];
            const insertIdx = activeAnchorIndexRef.current;
            if (insertIdx !== null && insertIdx >= 0 && insertIdx < newRoute.length) {
              newRoute.splice(insertIdx + 1, 0, [e.lngLat.lat, e.lngLat.lng]);
              window.dispatchEvent(new CustomEvent("select-anchor", { detail: { index: insertIdx + 1 } }));
            } else {
              newRoute = [...existing, [e.lngLat.lat, e.lngLat.lng]];
            }
            return {
              ...wp,
              routeMode: "draw",
              customRoute: newRoute,
            };
          }
          return wp;
        }),
      );
      setIsDirty(true);
      return;
    }

    // Via-point placement mode
    if (isViaMode && viaTargetWpIdRef.current) {
      const targetId = viaTargetWpIdRef.current;
      setWaypoints((prev) =>
        prev.map((wp) => {
          if (wp.id === targetId) {
            const existing = wp.viaPoints || [];
            return { ...wp, viaPoints: [...existing, [e.lngLat.lat, e.lngLat.lng] as [number, number]] };
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
        t`Routes are limited to ${mapDefaults.maxWaypoints} waypoints in this preview build.`,
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
        name: t`Locating...`,
        images: [],
        imagePans: [],
        narration: "",
        routeMode: settings.default_route_mode || "walking",
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
          wp.id === newId ? { ...wp, name: t`Unknown Location` } : wp,
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
      name: t`Locating...`,
      images: [],
      imagePans: [],
      narration: "",
      routeMode: settings.default_route_mode || "walking",
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
        data.name || data.address?.road || data.address?.city || t`Waypoint`;
      setWaypoints((prev) =>
        prev.map((wp) => (wp.id === newId ? { ...wp, name: placeName } : wp)),
      );
    } catch {
      setWaypoints((prev) =>
        prev.map((wp) =>
          wp.id === newId ? { ...wp, name: t`Unknown Location` } : wp,
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
        name: t`Locating...`,
        images: [],
        imagePans: [],
        narration: "",
        routeMode: settings.default_route_mode || "walking",
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
        data.name || data.address?.road || data.address?.city || t`Stop By`;
      setWaypoints((prev) =>
        prev.map((wp) => (wp.id === newId ? { ...wp, name: placeName } : wp)),
      );
    } catch {
      setWaypoints((prev) =>
        prev.map((wp) =>
          wp.id === newId ? { ...wp, name: t`Unknown Location` } : wp,
        ),
      );
    }
  };

  // Listen for sidebar "Adjust Route" button
  useEffect(() => {
    const handleEnterVia = ((e: CustomEvent) => {
      viaTargetWpIdRef.current = e.detail.wpId;
      setIsViaMode(true);
      setIsAddMode(false);
      setIsDrawMode(false);

      const wpIndex = waypoints.findIndex(w => w.id === e.detail.wpId);
      if (wpIndex !== -1 && wpIndex < waypoints.length - 1) {
        const wp = waypoints[wpIndex];
        const nextWp = waypoints[wpIndex + 1];
        const map = mapRef.current;
        if (map) {
          // Use the actual routed segment positions for accurate bounding box
          let lats = [wp.lat, nextWp.lat, ...(wp.viaPoints || []).map(v => v[0])];
          let lngs = [wp.lng, nextWp.lng, ...(wp.viaPoints || []).map(v => v[1])];
          
          if (routeSegments[wpIndex] && routeSegments[wpIndex].positions) {
            lats = routeSegments[wpIndex].positions.map(p => p[0]);
            lngs = routeSegments[wpIndex].positions.map(p => p[1]);
          }
          
          const minLat = Math.min(...lats);
          const maxLat = Math.max(...lats);
          const minLng = Math.min(...lngs);
          const maxLng = Math.max(...lngs);
          
          setTimeout(() => {
            try {
              if (minLng === maxLng && minLat === maxLat) {
                map.getMap().flyTo({ center: [minLng, minLat], zoom: 15, duration: 800 });
              } else {
                map.getMap().fitBounds([ [minLng, minLat], [maxLng, maxLat] ], { padding: 80, duration: 800 });
              }
            } catch (e) {
              console.error("[Navivi] Failed to fitBounds:", e);
            }
          }, 150);
        }
      }
    }) as EventListener;
    
    const handleExitVia = (() => {
      setIsViaMode(false);
      viaTargetWpIdRef.current = null;
    }) as EventListener;
    
    window.addEventListener("enter-via-mode", handleEnterVia);
    window.addEventListener("exit-via-mode", handleExitVia);
    return () => {
      window.removeEventListener("enter-via-mode", handleEnterVia);
      window.removeEventListener("exit-via-mode", handleExitVia);
    };
  }, [waypoints, routeSegments]);

  useEffect(() => {
    const handleHover = ((e: CustomEvent) =>
      setEleHoverPoint(e.detail)) as EventListener;
    window.addEventListener("elevation-hover", handleHover);
    return () => window.removeEventListener("elevation-hover", handleHover);
  }, []);

  const activeAnchorIndexRef = useRef<number | null>(null);
  useEffect(() => {
    const handleSelectAnchor = ((e: CustomEvent) => {
      activeAnchorIndexRef.current = e.detail.index;
    }) as EventListener;
    window.addEventListener("select-anchor", handleSelectAnchor);
    return () => window.removeEventListener("select-anchor", handleSelectAnchor);
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

  // Exit via mode if active waypoint changes away
  useEffect(() => {
    if (isViaMode) {
      const onKey = (e: KeyboardEvent) => {
        if (e.key === "Escape") {
          setIsViaMode(false);
          viaTargetWpIdRef.current = null;
          window.dispatchEvent(new CustomEvent("exit-via-mode"));
        }
      };
      window.addEventListener("keydown", onKey);
      return () => window.removeEventListener("keydown", onKey);
    }
  }, [isViaMode]);

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
      <div className="absolute z-200 transition-all duration-300 max-[1159px]:top-16 max-[1159px]:left-4 max-[1159px]:translate-x-0 min-[1160px]:top-16 min-[1160px]:left-1/2 min-[1160px]:-translate-x-1/2">
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

      <div className="absolute top-16 right-4 z-200 flex items-center gap-2">
        <button
          onClick={() => {
            setViewState((prev) => ({
              ...prev,
              pitch: 0,
              bearing: 0,
            }));
          }}
          title={t`Reset View (North)`}
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
        <UnifiedLayersPanel
          activeWp={activeWp}
          nextWp={nextWp}
          waypoints={waypoints}
          updateWaypoint={updateWaypoint}
          setIsDirty={setIsDirty}
        />
      )}

      {/* MAPBOX CANVAS */}
      <div className="absolute inset-0 z-0">
        <Map
          reuseMaps={true}
          ref={mapRef}
          cursor={isEraserMode || isViaMode ? "crosshair" : ""}
          {...viewState}
          onMove={(evt: ViewStateChangeEvent) => setViewState(evt.viewState)}
          onLoad={handleMapLoad}
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
          doubleClickZoom={!isDrawMode && !isViaMode}
          maxZoom={20}
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
              label = t`S`;
            } else if (isEnd) {
              pinType = "end";
              label = t`E`;
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
                      {wp.name || t`Waypoint`}
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
                        alt={t`Custom Marker`}
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
                    {wp.name || t`Waypoint`}
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
                      alt={t`Custom Marker`}
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

          {/* via-point nudge markers */}
          {waypoints.map((wp) =>
            (wp.viaPoints || []).map((pos, idx) => (
              <Marker
                key={`via-${wp.id}-${idx}`}
                latitude={pos[0]}
                longitude={pos[1]}
                draggable
                onDragEnd={(e) => {
                  setWaypoints((prev) =>
                    prev.map((w) => {
                      if (w.id === wp.id && w.viaPoints) {
                        const updated = [...w.viaPoints];
                        updated[idx] = [e.lngLat.lat, e.lngLat.lng];
                        return { ...w, viaPoints: updated };
                      }
                      return w;
                    }),
                  );
                  setIsDirty(true);
                }}
              >
                <div
                  className="relative group cursor-grab active:cursor-grabbing"
                  onClick={(e) => {
                    e.stopPropagation();
                    // Right-click or Ctrl+Click to remove
                  }}
                  onContextMenu={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    setWaypoints((prev) =>
                      prev.map((w) => {
                        if (w.id === wp.id && w.viaPoints) {
                          return { ...w, viaPoints: w.viaPoints.filter((_, i) => i !== idx) };
                        }
                        return w;
                      }),
                    );
                    setIsDirty(true);
                  }}
                >
                  <div className="w-4 h-4 bg-violet-500 border-2 border-white dark:border-zinc-900 rounded-full shadow-md group-hover:scale-125 group-hover:bg-violet-400 transition-all" />
                  <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 opacity-0 group-hover:opacity-100 transition-opacity bg-zinc-900 text-white text-[9px] font-bold px-1.5 py-0.5 rounded pointer-events-none whitespace-nowrap">
                    Via {idx + 1} · Right-click to remove
                  </div>
                </div>
              </Marker>
            ))
          )}

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
                    className={`relative group ${isEraserMode ? "cursor-crosshair" : "cursor-grab active:cursor-grabbing"}`}
                    onClick={(e) => {
                      if (isEraserMode) {
                        e.stopPropagation();
                        setWaypoints((prev) =>
                          prev.map((wp) => {
                            if (wp.id === activeWaypointId && wp.customRoute) {
                              const newRoute = wp.customRoute.filter(
                                (_, i) => i !== idx,
                              );
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
                      <Trans>Anchor {idx + 1}</Trans>
                    </div>
                  </div>
                </Marker>
              ))}
        </Map>

        {/* HISTORICAL WEATHER RAIN OVERLAY */}
        {settings.weather_sync_enabled && weatherCondition === "rain" && (
          <RainOverlay />
        )}
      </div>

      <ElevationProfile />

      {/* OVERLAYS */}
      {waypoints.length === 0 && settings.weather_sync_enabled && (
        <div className="absolute inset-0 z-10 flex items-center justify-center pointer-events-none p-6">
          <div className="pointer-events-auto bg-white/90 dark:bg-navidark-800/90 backdrop-blur-md border-2 border-dashed border-zinc-300 dark:border-white/15 rounded-2xl p-8 max-w-md w-full text-center shadow-xl flex flex-col items-center gap-3 transition-all animate-in fade-in zoom-in-95">
            <div className="w-12 h-12 rounded-xl bg-navi/10 text-navi flex items-center justify-center">
              <ImageIcon className="w-6 h-6" />
            </div>
            <h3 className="text-sm font-bold text-zinc-900 dark:text-white">
              <Trans>Drop photos here to auto-plot your route</Trans>
            </h3>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 max-w-xs leading-relaxed">
              <Trans>
                EXIF GPS tags from your travel photos will automatically
                generate sequenced stops on the map.
              </Trans>
            </p>
            <button
              onClick={importPhotos}
              className="mt-1 px-3.5 py-1.5 bg-navi hover:bg-navi-600 text-white rounded-lg text-xs font-semibold shadow-sm transition-colors flex items-center gap-1.5"
            >
              <ImageIcon className="w-3.5 h-3.5" />
              <Trans>Select Photos...</Trans>
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
            <Trans>Drop photos or GPS files to plot route</Trans>
          </p>
        </div>
      )}

      {isProcessing && (
        <div className="absolute inset-0 z-600 bg-white/50 dark:bg-zinc-950/50 backdrop-blur-sm flex flex-col items-center justify-center transition-all animate-in fade-in">
          <div className="w-12 h-12 border-4 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin mb-4" />
          <p className="text-zinc-900 dark:text-zinc-200 font-bold text-sm tracking-widest uppercase">
            <Trans>Parsing Route Data...</Trans>
          </p>
        </div>
      )}
      {/* --- VIA MODE BANNER --- */}
      {isViaMode && (
        <div className="absolute z-200 pointer-events-none animate-in fade-in zoom-in-95 duration-200 max-[1159px]:top-[120px] max-[1159px]:left-4 max-[1159px]:translate-x-0 min-[1160px]:top-[120px] min-[1160px]:left-1/2 min-[1160px]:-translate-x-1/2">
          <div className="bg-zinc-900/90 dark:bg-zinc-100/90 backdrop-blur-sm text-white dark:text-zinc-900 text-[10px] font-bold px-3 py-1.5 rounded-full shadow-lg border border-zinc-800 dark:border-zinc-200 flex items-center gap-1.5 pointer-events-auto">
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
            <span>Via Mode: Click to nudge route, Right-click to remove</span>
            <button
              onClick={() => { setIsViaMode(false); viaTargetWpIdRef.current = null; window.dispatchEvent(new CustomEvent("exit-via-mode")); }}
              className="ml-1 text-zinc-400 dark:text-zinc-500 hover:text-white dark:hover:text-zinc-900 transition-colors"
            >
              <X className="w-3 h-3" />
            </button>
          </div>
        </div>
      )}

      {/* --- FLOATING WAYPOINT EDITOR --- */}
      {activeWaypointId && !isDrawMode && !isAddMode && (
        <WaypointEditor
          wpId={activeWaypointId}
          onClose={() => setActiveWaypointId(null)}
        />
      )}
    </main>
  );
}
