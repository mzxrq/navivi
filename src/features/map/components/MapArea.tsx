import { useEffect, useState, useRef } from "react";
import Map, { Marker, MapRef, Source } from "react-map-gl/mapbox";
import { listen } from "@tauri-apps/api/event";
import { convertFileSrc } from "@tauri-apps/api/core";
import { UploadCloud, ImageIcon } from "../../../components/ui/icons";
import { AddType, MapToolbar } from "./MapToolbar";
import { DrawBar } from "./DrawBar";
import { MapCompass } from "./MapCompass";
import { openContextMenu, separator } from "../../../components/ui/menuItems";
import { useStopMenus } from "../hooks/useStopMenus";
import { Check, Pencil, Plus, Trash2 } from "../../../components/ui/icons";
import "@mapbox/mapbox-gl-draw/dist/mapbox-gl-draw.css";
import { mapStyles } from "../../../config/constants";
import { RouteStyling } from "./MapLayers/RouteStyling";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useTheme } from "../../../hooks/useTheme";
import { useMapRouting } from "../hooks/useMapRouting";
import { useFileActions } from "../../../hooks/useFileActions";
import { takePendingImport } from "../../../utils/pendingImport";
import { useUI } from "../../../hooks/useUI";
import { loadProjectData } from "../../../services/fileSystem";
import { WaypointEditor } from "./WaypointEditor";
import { LayerManager } from "./MapLayers/LayerManager";
import { RouteLayer } from "./MapLayers/RouteLayer";
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
  const { showToast } = useUI();
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
    registerThumbnailGetter,
  } = useWorkspace();
  const { handleDroppedFiles, importPhotos, importRouteFile } = useFileActions();

  useEffect(() => {
    const pending = takePendingImport();
    if (pending?.kind === "route") importRouteFile(pending.path);
  }, []);

  const [isHovering, setIsHovering] = useState(false);
  const [isAddMode, setIsAddMode] = useState(false);
  const [isDrawMode, setIsDrawMode] = useState(false);
  const [isEraserMode, setIsEraserMode] = useState(false);
  const [isViaMode, setIsViaMode] = useState(false);
  const viaTargetWpIdRef = useRef<string | null>(null);
  const [addType, setAddType] = useState<AddType>("normal");
  const [selectedAnchor, setSelectedAnchor] = useState<number | null>(null);

  const [is3D, setIs3D] = useState(false);
  const [isMapLoaded, setIsMapLoaded] = useState(false);
  const [isProcessing] = useState(false);
  const [uploadedRouteLine] = useState<[number, number][]>([]);
  const mapRef = useRef<MapRef>(null);
  const thumbnailCaptureTimeoutRef = useRef<ReturnType<
    typeof setTimeout
  > | null>(null);
  const rightClickStartRef = useRef<{ x: number; y: number } | null>(null);
  const isContextLostRef = useRef(false);

  const [eleHoverPoint, setEleHoverPoint] = useState<number[] | null>(null);
  const [weatherCondition, setWeatherCondition] =
    useState<WeatherCondition>("clear");

  const initialViewState = useRef({
    longitude: settings.start_coords?.[1] || 135.5023,
    latitude: settings.start_coords?.[0] || 34.6937,
    zoom: 13,
    pitch: 0,
    bearing: 0,
  }).current;

  useMapRouting();

  const thumbnailCanvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    registerThumbnailGetter(() => {
      const snap = thumbnailCanvasRef.current;
      if (!snap) return null;
      try {
        return snap.toDataURL("image/png");
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
      const map = mapRef.current?.getMap();
      if (!map || isContextLostRef.current) return;
      map.once("render", () => {
        const source = map.getCanvas();
        if (!source.width || !source.height) return;
        const width = Math.min(640, source.width);
        const height = Math.round((source.height / source.width) * width);
        const snap =
          thumbnailCanvasRef.current ?? document.createElement("canvas");
        snap.width = width;
        snap.height = height;
        try {
          snap.getContext("2d")?.drawImage(source, 0, 0, width, height);
          thumbnailCanvasRef.current = snap;
        } catch (error) {
          console.warn("Unable to capture map thumbnail:", error);
        }
      });
      map.triggerRepaint();
    }, 1500);
  };

  // Called by <Map onLoad>: canvas now exists, safe to attach WebGL handlers
  // A reused map fires "load" while the component mounts, before mapRef is attached: use the event's own map.
  const handleMapLoad = (e?: { target?: mapboxgl.Map }) => {
    const map = e?.target ?? mapRef.current?.getMap();
    if (!map) return;
    map.resize();
    setIsMapLoaded(true);

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

  // The canvas is sized once when created (and a reused map keeps its old size); follow the container instead.
  const mapBoxRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = mapBoxRef.current;
    if (!el) return;
    let frame = 0;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => mapRef.current?.resize());
    });
    observer.observe(el);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, []);

  const handleMapClick = (e: any) => {
    if (isDrawMode && activeWaypointId) {
      setWaypoints((prev) =>
        prev.map((wp) => {
          if (wp.id === activeWaypointId) {
            const existing = wp.customRoute || [];
            let newRoute = [...existing];
            const insertIdx = activeAnchorIndexRef.current;
            if (
              insertIdx !== null &&
              insertIdx >= 0 &&
              insertIdx < newRoute.length
            ) {
              newRoute.splice(insertIdx + 1, 0, [e.lngLat.lat, e.lngLat.lng]);
              window.dispatchEvent(
                new CustomEvent("select-anchor", {
                  detail: { index: insertIdx + 1 },
                }),
              );
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
            return {
              ...wp,
              viaPoints: [
                ...existing,
                [e.lngLat.lat, e.lngLat.lng] as [number, number],
              ],
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

    const { lat, lng } = e.lngLat;
    if (isDrawMode) {
      openContextMenu(e.originalEvent, [
        activeWp &&
          nextWp && {
            label: t`Add point here`,
            icon: Plus,
            onSelect: () => handleMapClick(e),
          },
        {
          label: t`Done drawing`,
          icon: Check,
          onSelect: () => setIsDrawMode(false),
        },
      ]);
      return;
    }
    if (isViaMode) {
      openContextMenu(e.originalEvent, [
        {
          label: t`Add via point here`,
          icon: Plus,
          onSelect: () => handleMapClick(e),
        },
        {
          label: t`Done adjusting`,
          icon: Check,
          onSelect: () =>
            window.dispatchEvent(new CustomEvent("exit-via-mode")),
        },
      ]);
      return;
    }
    openContextMenu(
      e.originalEvent,
      mapMenu(lat, lng, {
        stop: () => handleAddWaypoint(lat, lng),
        stopBy: () => handleAddStopByWaypoint(lat, lng),
        start: () => handleAddSpWaypoint(lat, lng, "start"),
        end: () => handleAddSpWaypoint(lat, lng, "end"),
      }),
    );
  };

  const handleMarkerContextMenu = (e: React.MouseEvent, wpId: string) =>
    openContextMenu(e, stopMenu(wpId));

  const pinDraggedRef = useRef(false);
  const { stopMenu, viaMenu, mapMenu } = useStopMenus();
  const handlePinClick = (e: React.MouseEvent, wpId: string) => {
    e.stopPropagation();
    if (pinDraggedRef.current) {
      pinDraggedRef.current = false;
      return;
    }
    if (isDrawMode || isAddMode || isViaMode) return;
    setActiveWaypointId(wpId);
  };

  const handleAddWaypoint = async (lat: number, lng: number) => {
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

  const removeAnchor = (idx: number) => {
    setWaypoints((prev) =>
      prev.map((wp) =>
        wp.id === activeWaypointId && wp.customRoute
          ? { ...wp, customRoute: wp.customRoute.filter((_, i) => i !== idx) }
          : wp,
      ),
    );
    if (
      activeAnchorIndexRef.current !== null &&
      activeAnchorIndexRef.current >= idx
    ) {
      const index =
        activeAnchorIndexRef.current === idx
          ? null
          : activeAnchorIndexRef.current - 1;
      window.dispatchEvent(
        new CustomEvent("select-anchor", { detail: { index } }),
      );
    }
    setIsDirty(true);
  };

  useEffect(() => {
    const handleFocus = ((e: CustomEvent) => {
      const wp = waypoints.find((w) => w.id === e.detail.wpId);
      const map = mapRef.current?.getMap();
      if (!wp || !map) return;
      map.flyTo({
        center: [wp.lng, wp.lat],
        zoom: Math.max(map.getZoom(), 15),
        duration: 800,
      });
    }) as EventListener;
    window.addEventListener("focus-waypoint", handleFocus);
    return () => window.removeEventListener("focus-waypoint", handleFocus);
  }, [waypoints]);

  const fitToLeg = (wpId: string) => {
    const wpIndex = waypoints.findIndex((w) => w.id === wpId);
    if (wpIndex === -1 || wpIndex >= waypoints.length - 1) return;
    const wp = waypoints[wpIndex];
    const nextWp = waypoints[wpIndex + 1];
    const map = mapRef.current;
    if (!map) return;

    const extra = [...(wp.viaPoints || []), ...(wp.customRoute || [])];
    let lats = [wp.lat, nextWp.lat, ...extra.map((v) => v[0])];
    let lngs = [wp.lng, nextWp.lng, ...extra.map((v) => v[1])];
    if (routeSegments[wpIndex]?.positions?.length) {
      lats = [...lats, ...routeSegments[wpIndex].positions.map((p) => p[0])];
      lngs = [...lngs, ...routeSegments[wpIndex].positions.map((p) => p[1])];
    }
    const minLat = Math.min(...lats);
    const maxLat = Math.max(...lats);
    const minLng = Math.min(...lngs);
    const maxLng = Math.max(...lngs);

    setTimeout(() => {
      try {
        if (minLng === maxLng && minLat === maxLat) {
          map
            .getMap()
            .flyTo({ center: [minLng, minLat], zoom: 15, duration: 800 });
        } else {
          map.getMap().fitBounds(
            [
              [minLng, minLat],
              [maxLng, maxLat],
            ],
            {
              padding: { top: 170, bottom: 80, left: 80, right: 80 },
              duration: 800,
            },
          );
        }
      } catch (e) {
        console.error("[Navivi] Failed to fitBounds:", e);
      }
    }, 150);
  };

  useEffect(() => {
    const handleEnterVia = ((e: CustomEvent) => {
      viaTargetWpIdRef.current = e.detail.wpId;
      setIsViaMode(true);
      setIsAddMode(false);
      setIsDrawMode(false);
      fitToLeg(e.detail.wpId);
    }) as EventListener;

    const handleExitVia = (() => {
      setIsViaMode(false);
      viaTargetWpIdRef.current = null;
    }) as EventListener;

    const handleEnterDraw = ((e: CustomEvent) => {
      if (isViaMode) window.dispatchEvent(new CustomEvent("exit-via-mode"));
      setActiveWaypointId(e.detail.wpId);
      setIsAddMode(false);
      setIsDrawMode(true);
      fitToLeg(e.detail.wpId);
    }) as EventListener;

    window.addEventListener("enter-via-mode", handleEnterVia);
    window.addEventListener("exit-via-mode", handleExitVia);
    window.addEventListener("enter-draw-mode", handleEnterDraw);
    return () => {
      window.removeEventListener("enter-via-mode", handleEnterVia);
      window.removeEventListener("exit-via-mode", handleExitVia);
      window.removeEventListener("enter-draw-mode", handleEnterDraw);
    };
  }, [waypoints, routeSegments, isViaMode]);

  useEffect(() => {
    if (!isDrawMode) setIsEraserMode(false);
    window.dispatchEvent(
      new CustomEvent("select-anchor", { detail: { index: null } }),
    );
  }, [isDrawMode, activeWaypointId]);

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
      setSelectedAnchor(e.detail.index);
    }) as EventListener;
    window.addEventListener("select-anchor", handleSelectAnchor);
    return () =>
      window.removeEventListener("select-anchor", handleSelectAnchor);
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
      <div className="absolute z-200 top-14 left-1/2 -translate-x-1/2 max-w-[calc(100%-2rem)] flex flex-col items-center gap-2 pointer-events-none *:pointer-events-auto">
        <MapToolbar
          isAddMode={isAddMode}
          setIsAddMode={setIsAddMode}
          isDrawMode={isDrawMode}
          setIsDrawMode={setIsDrawMode}
          isEraserMode={isEraserMode}
          setIsEraserMode={setIsEraserMode}
          canErase={!!activeWp && !!nextWp}
          addType={addType}
          setAddType={setAddType}
        />

        {isDrawMode && (
          <DrawBar
            waypoints={waypoints}
            activeWp={nextWp ? activeWp : null}
            nextWp={nextWp}
            isEraserMode={isEraserMode}
            setIsEraserMode={setIsEraserMode}
            onPickLeg={(wpId) => {
              setActiveWaypointId(wpId);
              fitToLeg(wpId);
            }}
            onToggleSpline={() => {
              if (activeWp) {
                updateWaypoint(activeWp.id, {
                  drawStyle:
                    activeWp.drawStyle === "spline" ? "linear" : "spline",
                });
              }
            }}
            onFit={handleZoomToFit}
            onDone={() => setIsDrawMode(false)}
            updateWaypoint={updateWaypoint}
            setIsDirty={setIsDirty}
          />
        )}

        {isViaMode && (
          <div className="flex items-center gap-2 h-9 pl-3.5 pr-1 rounded-xl bg-white/95 dark:bg-zinc-900/95 backdrop-blur-md border border-zinc-200 dark:border-white/10 shadow-sm animate-in fade-in slide-in-from-top-1 duration-150">
            <span className="w-1.5 h-1.5 rounded-full bg-violet-500 shrink-0" />
            <span className="text-[12px] text-zinc-600 dark:text-zinc-300 truncate">
              <Trans>
                Click the map to nudge the route. Drag a via point to move it,
                or right-click it for options.
              </Trans>
            </span>
            <button
              type="button"
              onClick={() => {
                setIsViaMode(false);
                viaTargetWpIdRef.current = null;
                window.dispatchEvent(new CustomEvent("exit-via-mode"));
              }}
              className="h-7 px-2.5 rounded-lg text-[12px] font-semibold bg-navi text-white hover:brightness-110 transition shrink-0"
            >
              <Trans>Done</Trans>
            </button>
          </div>
        )}
      </div>

      <div className="absolute top-14 right-4 z-200 flex items-center gap-0.5 p-1 rounded-xl bg-white/95 dark:bg-zinc-900/95 backdrop-blur-md border border-zinc-200 dark:border-white/10 shadow-sm">
        <MapCompass mapRef={mapRef} ready={isMapLoaded} />

        <RouteStyling />

        <div className="w-px h-4 mx-0.5 bg-zinc-200 dark:bg-white/10" />

        <LayerManager
          selectedStyle={selectedStyle}
          setSelectedStyle={setSelectedStyle}
          mapboxToken={mapboxToken}
          is3D={is3D}
          setIs3D={setIs3D}
        />
      </div>

      {/* MAPBOX CANVAS */}
      <div ref={mapBoxRef} className="absolute inset-0 z-0">
        <Map
          reuseMaps={true}
          ref={mapRef}
          cursor={isEraserMode || isViaMode ? "crosshair" : ""}
          initialViewState={initialViewState}
          onLoad={(e) => handleMapLoad(e)}
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
            const isSelected = wp.id === activeWaypointId && !isDrawMode;

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
                  className="hover:z-20"
                  style={isSelected ? { zIndex: 5 } : undefined}
                >
                  <div
                    className={`relative flex flex-col items-center group cursor-pointer transition-transform ${isSelected ? "-translate-y-1" : "hover:-translate-y-1"}`}
                    onClick={(e) => handlePinClick(e, wp.id)}
                    onContextMenu={(e) => handleMarkerContextMenu(e, wp.id)}
                  >
                    <div
                      className={`pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 z-10 bg-zinc-900 text-white text-[10px] font-bold px-2 py-0.5 rounded shadow-lg border border-white/20 mb-1 transition-opacity whitespace-nowrap ${isSelected ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}
                    >
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
                onDragStart={() => {
                  pinDraggedRef.current = true;
                }}
                onDragEnd={(e) => {
                  const { lat, lng } = e.lngLat;
                  setWaypoints((prev) =>
                    prev.map((w) => (w.id === wp.id ? { ...w, lat, lng } : w)),
                  );
                  setTimeout(() => {
                    pinDraggedRef.current = false;
                  }, 0);
                }}
                anchor="bottom"
                className="hover:z-20"
                style={isSelected ? { zIndex: 5 } : undefined}
              >
                <div
                  className={`relative flex flex-col items-center group cursor-grab active:cursor-grabbing transition-transform ${isSelected ? "-translate-y-1" : "hover:-translate-y-1"}`}
                  onClick={(e) => handlePinClick(e, wp.id)}
                  onContextMenu={(e) => handleMarkerContextMenu(e, wp.id)}
                >
                  <div
                    className={`pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 z-10 bg-zinc-900 text-white text-[10px] font-bold px-2 py-0.5 rounded shadow-lg border border-white/20 mb-1 transition-opacity whitespace-nowrap ${isSelected ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}
                  >
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
                  onClick={(e) => e.stopPropagation()}
                  onContextMenu={(e) => openContextMenu(e, viaMenu(wp.id, idx))}
                >
                  <div className="w-4 h-4 bg-violet-500 border-2 border-white dark:border-zinc-900 rounded-full shadow-md group-hover:scale-125 group-hover:bg-violet-400 transition-all" />
                  <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 opacity-0 group-hover:opacity-100 transition-opacity bg-zinc-900 text-white text-[9px] font-bold px-1.5 py-0.5 rounded pointer-events-none whitespace-nowrap">
                    <Trans>Via {idx + 1} · Right-click for options</Trans>
                  </div>
                </div>
              </Marker>
            )),
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
                      e.stopPropagation();
                      if (!isEraserMode) {
                        const index =
                          activeAnchorIndexRef.current === idx ? null : idx;
                        window.dispatchEvent(
                          new CustomEvent("select-anchor", {
                            detail: { index },
                          }),
                        );
                        return;
                      }
                      removeAnchor(idx);
                    }}
                    onContextMenu={(e) =>
                      openContextMenu(e, [
                        { type: "label", label: t`Point ${idx + 1}` },
                        {
                          label: t`Add new points after this one`,
                          icon: Pencil,
                          checked: selectedAnchor === idx,
                          onSelect: () =>
                            window.dispatchEvent(
                              new CustomEvent("select-anchor", {
                                detail: {
                                  index: selectedAnchor === idx ? null : idx,
                                },
                              }),
                            ),
                        },
                        separator,
                        {
                          label: t`Delete point`,
                          icon: Trash2,
                          danger: true,
                          onSelect: () => removeAnchor(idx),
                        },
                      ])
                    }
                  >
                    <div
                      className={`w-5 h-5 border-2 border-white dark:border-zinc-900 rounded-full shadow-md group-hover:scale-110 transition-all flex items-center justify-center ${
                        isEraserMode
                          ? "bg-amber-500 group-hover:bg-red-500"
                          : selectedAnchor === idx
                            ? "bg-navi ring-4 ring-navi/30"
                            : "bg-amber-500 group-hover:bg-amber-400"
                      }`}
                    >
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
